"""
downloader.py
Download top reels (video + thumbnail) and upload them to Google Drive.
Skips any reel already present in Drive (checks by reel_id in folder).

Input:  /tmp/metrics_output.json   (from metrics.py — full metadata)
        config/accounts.json       (for top_n_download per account)
Output: updates drive.video_file_id, drive.thumb_file_id, drive.file_size_mb
        in metadata JSON files on Drive
"""

import json
import os
import sys
import argparse
import logging
import tempfile
from pathlib import Path

import yt_dlp
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent.parent / "config" / "accounts.json"


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


def build_account_top_n(config: dict) -> dict:
    """Returns {username: top_n_download}"""
    return {a["username"]: a["top_n_download"] for a in config["accounts"]}


def select_top_reels(metadata: list[dict], top_n_map: dict) -> list[dict]:
    """Pick top_n reels per account sorted by virality_score descending."""
    from collections import defaultdict
    per_account = defaultdict(list)
    for m in metadata:
        per_account[m["identity"]["account"]].append(m)

    selected = []
    for account, reels in per_account.items():
        n = top_n_map.get(account, 5)
        sorted_reels = sorted(reels, key=lambda r: r["virality"]["score"], reverse=True)
        selected.extend(sorted_reels[:n])
    return selected


def download_video(reel_url: str, out_path: str) -> bool:
    """Download reel .mp4 using yt-dlp."""
    ydl_opts = {
        "format":           "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "outtmpl":          out_path,
        "quiet":            True,
        "no_warnings":      True,
        "merge_output_format": "mp4",
    }
    session_id = os.environ.get("INSTAGRAM_SESSION_ID", "")
    if session_id:
        ydl_opts["cookiefile"] = None  # yt-dlp can use session cookies via extractor args
        ydl_opts["extractor_args"] = {
            "instagram": {"sessionid": session_id}
        }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([f"https://www.instagram.com/reel/{reel_url}/"])
        return True
    except Exception as e:
        log.error(f"    yt-dlp download failed: {e}")
        return False


def download_thumbnail(thumb_url: str, out_path: str) -> bool:
    """Download thumbnail image."""
    if not thumb_url:
        return False
    try:
        r = requests.get(thumb_url, timeout=30)
        r.raise_for_status()
        with open(out_path, "wb") as f:
            f.write(r.content)
        return True
    except Exception as e:
        log.error(f"    thumbnail download failed: {e}")
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--metrics-json",   default="/tmp/metrics_output.json")
    parser.add_argument("--existing-ids-json", default="/tmp/existing_reel_ids.json",
                        help="JSON list of reel_ids already in Drive (skip these)")
    parser.add_argument("--out-dir",        default="/tmp/downloads")
    parser.add_argument("--out-manifest",   default="/tmp/download_manifest.json")
    args = parser.parse_args()

    config = load_config()
    top_n_map = build_account_top_n(config)

    with open(args.metrics_json) as f:
        metadata = json.load(f)

    existing_ids = set()
    if os.path.exists(args.existing_ids_json):
        with open(args.existing_ids_json) as f:
            existing_ids = set(json.load(f))

    top_reels = select_top_reels(metadata, top_n_map)
    log.info(f"Selected {len(top_reels)} reels for download")

    os.makedirs(args.out_dir, exist_ok=True)
    manifest = []

    for meta in top_reels:
        reel_id = meta["identity"]["reel_id"]
        account = meta["identity"]["account"]

        if reel_id in existing_ids:
            log.info(f"  {account}/{reel_id}: already in Drive, skipping")
            continue

        video_fname = meta["drive"]["video_filename"]
        thumb_fname = meta["drive"]["thumb_filename"]
        video_path  = os.path.join(args.out_dir, video_fname)
        thumb_path  = os.path.join(args.out_dir, thumb_fname)

        log.info(f"  Downloading {account}/{reel_id}...")

        video_ok = download_video(reel_id, video_path)
        if not video_ok:
            meta["identity"]["download_failed"] = True
            manifest.append({"meta": meta, "video_path": None, "thumb_path": None, "failed": True})
            continue

        # Try to get thumbnail URL from instagrapi (stored in meta if available)
        thumb_url = meta.get("_thumb_url", "")
        thumb_ok = download_thumbnail(thumb_url, thumb_path) if thumb_url else False

        file_size_mb = round(os.path.getsize(video_path) / (1024 * 1024), 2) if os.path.exists(video_path) else 0
        meta["drive"]["file_size_mb"] = file_size_mb

        manifest.append({
            "meta":       meta,
            "video_path": video_path if video_ok else None,
            "thumb_path": thumb_path if thumb_ok else None,
            "failed":     False
        })
        log.info(f"    {video_fname} ({file_size_mb} MB)")

    with open(args.out_manifest, "w") as f:
        json.dump(manifest, f, indent=2)
    log.info(f"Download manifest: {args.out_manifest} ({len(manifest)} entries)")


if __name__ == "__main__":
    main()
