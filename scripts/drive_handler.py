"""
drive_handler.py
Google Drive operations:
  - Build the folder structure
  - Upload video, thumbnail, JSON sidecar
  - List existing reel_ids (for dedup)
  - Update existing JSON files (metrics refresh)
  - Copy files to top_reference/

Auth: uses a service account JSON key.
The service account must be shared on the root Drive folder.

Env vars:
  GDRIVE_ROOT_FOLDER_ID  ← ID of "AI_Reel_Generator" folder shared with service account
  GDRIVE_SERVICE_KEY     ← base64-encoded service account JSON (used by CI)
  GDRIVE_KEY_PATH        ← path to service_account.json (used locally)
"""

import json
import os
import base64
import io
import logging
import argparse
import tempfile
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from google.oauth2 import service_account

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive"]


def get_credentials():
    key_path = os.environ.get("GDRIVE_KEY_PATH")
    if key_path and os.path.exists(key_path):
        return service_account.Credentials.from_service_account_file(key_path, scopes=SCOPES)

    key_b64 = os.environ.get("GDRIVE_SERVICE_KEY")
    if key_b64:
        key_json = base64.b64decode(key_b64).decode()
        info = json.loads(key_json)
        return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)

    raise ValueError("No Google Drive credentials found. Set GDRIVE_KEY_PATH or GDRIVE_SERVICE_KEY")


def build_service():
    creds = get_credentials()
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def get_or_create_folder(service, name: str, parent_id: str) -> str:
    """Return existing folder ID or create it."""
    q = (
        f"name='{name}' and mimeType='application/vnd.google-apps.folder' "
        f"and '{parent_id}' in parents and trashed=false"
    )
    res = service.files().list(q=q, fields="files(id, name)").execute()
    files = res.get("files", [])
    if files:
        return files[0]["id"]

    meta = {
        "name":     name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents":  [parent_id]
    }
    folder = service.files().create(body=meta, fields="id").execute()
    log.info(f"  Created folder: {name}")
    return folder["id"]


def ensure_folder_path(service, root_id: str, path_parts: list[str]) -> str:
    """Walk/create nested folder path and return leaf folder ID."""
    current_id = root_id
    for part in path_parts:
        current_id = get_or_create_folder(service, part, current_id)
    return current_id


def file_exists(service, name: str, parent_id: str) -> str | None:
    """Return file_id if file exists in folder, else None."""
    q = f"name='{name}' and '{parent_id}' in parents and trashed=false"
    res = service.files().list(q=q, fields="files(id)").execute()
    files = res.get("files", [])
    return files[0]["id"] if files else None


def upload_file(service, local_path: str, name: str, parent_id: str, mime: str) -> str:
    """Upload file, return file_id."""
    media = MediaFileUpload(local_path, mimetype=mime, resumable=True)
    meta  = {"name": name, "parents": [parent_id]}
    f = service.files().create(body=meta, media_body=media, fields="id").execute()
    return f["id"]


def update_file(service, file_id: str, local_path: str, mime: str):
    """Update existing file content."""
    media = MediaFileUpload(local_path, mimetype=mime, resumable=True)
    service.files().update(fileId=file_id, media_body=media).execute()


def download_file(service, file_id: str, out_path: str):
    """Download a file by ID."""
    req = service.files().get_media(fileId=file_id)
    with open(out_path, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, req)
        done = False
        while not done:
            _, done = downloader.next_chunk()


def list_json_files_in_library(service, root_id: str) -> list[dict]:
    """
    List all .json sidecar files under reels_library/.
    Returns [{name, id, parents}]
    """
    q = f"name contains '.json' and '{root_id}' in parents and trashed=false"
    results = []
    page_token = None
    while True:
        res = service.files().list(
            q=q,
            fields="nextPageToken, files(id, name, parents)",
            pageToken=page_token,
            pageSize=200
        ).execute()
        results.extend(res.get("files", []))
        page_token = res.get("nextPageToken")
        if not page_token:
            break
    return results


def get_all_existing_reel_ids(service, root_id: str) -> list[str]:
    """
    Scan entire Drive tree under root_id for .json files,
    extract reel_ids to avoid re-downloading.
    """
    # Search recursively
    q = "name contains '.json' and trashed=false"
    results = []
    page_token = None
    while True:
        res = service.files().list(
            q=q,
            fields="nextPageToken, files(id, name)",
            pageToken=page_token,
            pageSize=500
        ).execute()
        results.extend(res.get("files", []))
        page_token = res.get("nextPageToken")
        if not page_token:
            break

    # Parse reel_id from filename: {account}_{reel_id}.json
    reel_ids = []
    for f in results:
        name = f["name"]
        if name.endswith(".json") and "_" in name:
            # reel_id is everything after the first underscore, minus .json
            reel_id = name[name.index("_") + 1:].replace(".json", "")
            reel_ids.append(reel_id)
    return reel_ids


def upload_reel(service, root_id: str, entry: dict) -> dict:
    """
    Upload video + thumbnail + JSON sidecar for one reel.
    Returns updated drive fields dict.
    """
    meta        = entry["meta"]
    video_path  = entry.get("video_path")
    thumb_path  = entry.get("thumb_path")
    identity    = meta["identity"]
    drive_cfg   = meta["drive"]

    # Build folder: reels_library/{niche}/{account}/
    folder_id = ensure_folder_path(service, root_id, [
        "reels_library",
        identity["niche"],
        identity["account"]
    ])

    video_id = thumb_id = json_id = ""

    # Upload video
    if video_path and os.path.exists(video_path):
        video_fname = drive_cfg["video_filename"]
        existing = file_exists(service, video_fname, folder_id)
        if not existing:
            video_id = upload_file(service, video_path, video_fname, folder_id, "video/mp4")
            log.info(f"    Uploaded video: {video_fname}")
        else:
            video_id = existing
            log.info(f"    Video already exists: {video_fname}")

    # Upload thumbnail
    if thumb_path and os.path.exists(thumb_path):
        thumb_fname = drive_cfg["thumb_filename"]
        existing = file_exists(service, thumb_fname, folder_id)
        if not existing:
            thumb_id = upload_file(service, thumb_path, thumb_fname, folder_id, "image/jpeg")
            log.info(f"    Uploaded thumb: {thumb_fname}")
        else:
            thumb_id = existing

    # Update metadata with file IDs
    meta["identity"]["downloaded_at"] = meta["identity"].get("downloaded_at") or \
        __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    meta["drive"]["video_file_id"] = video_id
    meta["drive"]["thumb_file_id"] = thumb_id

    # Upload JSON sidecar
    json_fname = drive_cfg["json_filename"]
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
        json.dump(meta, tf, indent=2)
        tf_path = tf.name

    existing_json = file_exists(service, json_fname, folder_id)
    if existing_json:
        update_file(service, existing_json, tf_path, "application/json")
        json_id = existing_json
        log.info(f"    Updated JSON: {json_fname}")
    else:
        json_id = upload_file(service, tf_path, json_fname, folder_id, "application/json")
        log.info(f"    Uploaded JSON: {json_fname}")

    os.unlink(tf_path)
    meta["drive"]["json_file_id"] = json_id
    return meta


def update_json_on_drive(service, file_id: str, meta: dict):
    """Overwrite JSON sidecar on Drive with updated metrics."""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
        json.dump(meta, tf, indent=2)
        tf_path = tf.name
    update_file(service, file_id, tf_path, "application/json")
    os.unlink(tf_path)


def copy_to_top_reference(service, root_id: str, best_meta: dict):
    """Copy best reel files to top_reference/ folder."""
    ref_folder_id = get_or_create_folder(service, "top_reference", root_id)
    drive_cfg = best_meta["drive"]

    def copy_file(src_id, dest_name):
        existing = file_exists(service, dest_name, ref_folder_id)
        if existing:
            service.files().delete(fileId=existing).execute()
        body = {"name": dest_name, "parents": [ref_folder_id]}
        service.files().copy(fileId=src_id, body=body).execute()
        log.info(f"  Copied to top_reference/{dest_name}")

    if drive_cfg.get("video_file_id"):
        copy_file(drive_cfg["video_file_id"], "current_best.mp4")
    if drive_cfg.get("json_file_id"):
        copy_file(drive_cfg["json_file_id"], "current_best.json")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["upload", "list-ids", "update-jsons"], required=True)
    parser.add_argument("--manifest",    default="/tmp/download_manifest.json")
    parser.add_argument("--updated-jsons", default="/tmp/updated_jsons.json")
    parser.add_argument("--out-existing-ids", default="/tmp/existing_reel_ids.json")
    args = parser.parse_args()

    root_id = os.environ.get("GDRIVE_ROOT_FOLDER_ID")
    if not root_id:
        raise ValueError("GDRIVE_ROOT_FOLDER_ID env var not set")

    service = build_service()

    if args.mode == "list-ids":
        ids = get_all_existing_reel_ids(service, root_id)
        with open(args.out_existing_ids, "w") as f:
            json.dump(ids, f)
        log.info(f"Found {len(ids)} existing reel IDs")

    elif args.mode == "upload":
        with open(args.manifest) as f:
            manifest = json.load(f)

        for entry in manifest:
            if entry.get("failed"):
                log.warning(f"  Skipping failed: {entry['meta']['identity']['reel_id']}")
                continue
            try:
                upload_reel(service, root_id, entry)
            except Exception as e:
                log.error(f"  Upload failed for {entry['meta']['identity']['reel_id']}: {e}")

    elif args.mode == "update-jsons":
        with open(args.updated_jsons) as f:
            updated = json.load(f)  # list of {file_id, meta}
        for item in updated:
            try:
                update_json_on_drive(service, item["file_id"], item["meta"])
                log.info(f"  Updated {item['meta']['drive']['json_filename']}")
            except Exception as e:
                log.error(f"  Failed to update {item.get('file_id')}: {e}")


if __name__ == "__main__":
    main()
