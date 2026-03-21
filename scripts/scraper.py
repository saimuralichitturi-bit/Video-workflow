"""
scraper.py
Scrape reels from public Instagram accounts using yt-dlp (no login required).
Extracts metadata: views, likes, comments, caption, duration, timestamp.

Modes:
  --mode full     → scrape all accounts, return top_n reel data
  --mode refresh  → re-scrape metrics for existing reel_ids only
"""

import json
import os
import sys
import argparse
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

CONFIG_PATH  = Path(__file__).parent.parent / "config" / "accounts.json"
WEIGHTS_PATH = Path(__file__).parent.parent / "config" / "scoring_weights.json"


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def get_cookie_args() -> list[str]:
    """Return yt-dlp cookie arguments based on what's available."""
    # GitHub Actions: cookies written to file from secret
    cookie_file = os.environ.get("YTDLP_COOKIES_FILE")
    if cookie_file and os.path.exists(cookie_file):
        return ["--cookies", cookie_file]
    # Local: extract from Chrome automatically
    return ["--cookies-from-browser", "chrome"]


def ytdlp_extract(url: str, max_items: int = 10) -> list[dict]:
    """Run yt-dlp --dump-json on an Instagram profile or reel URL."""
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--dump-json",
        "--no-download",
        "--quiet",
        "--no-warnings",
        "--playlist-items", f"1:{max_items}",
        *get_cookie_args(),
        url
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        entries = []
        for line in result.stdout.strip().splitlines():
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return entries
    except subprocess.TimeoutExpired:
        log.error(f"  yt-dlp timed out for {url}")
        return []
    except Exception as e:
        log.error(f"  yt-dlp failed for {url}: {e}")
        return []


def parse_entry(entry: dict, account_cfg: dict) -> dict:
    """Convert yt-dlp JSON entry to our raw reel format."""
    now = datetime.now(timezone.utc)

    # Parse timestamp
    ts = entry.get("timestamp") or entry.get("upload_date")
    if isinstance(ts, int):
        posted_at = datetime.fromtimestamp(ts, tz=timezone.utc)
    elif isinstance(ts, str) and len(ts) == 8:
        # YYYYMMDD format
        posted_at = datetime.strptime(ts, "%Y%m%d").replace(tzinfo=timezone.utc)
    else:
        posted_at = now

    hours_since = max(1.0, (now - posted_at).total_seconds() / 3600)

    caption = entry.get("title") or entry.get("description") or ""
    hashtags = [w for w in caption.split() if w.startswith("#")]

    # reel_id = shortcode from URL or id field
    reel_id = entry.get("id", "")
    webpage_url = entry.get("webpage_url", "")
    # Instagram shortcode is the last path segment
    shortcode = webpage_url.rstrip("/").split("/")[-1] if webpage_url else reel_id

    return {
        "reel_id":            shortcode or reel_id,
        "pk":                 reel_id,
        "account":            account_cfg["username"],
        "niche":              account_cfg["niche"],
        "url":                webpage_url or f"instagram.com/p/{reel_id}",
        "posted_at":          posted_at.isoformat(),
        "duration_sec":       int(entry.get("duration") or 0),
        "hours_since_posted": round(hours_since, 2),
        "view_count":         int(entry.get("view_count") or 0),
        "like_count":         int(entry.get("like_count") or 0),
        "comment_count":      int(entry.get("comment_count") or 0),
        "share_count":        0,
        "save_count":         0,
        "caption_full":       caption,
        "hashtags_all":       hashtags,
        "scraped_at":         now.isoformat(),
        "_thumb_url":         entry.get("thumbnail", ""),
    }


def compute_view_velocity(view_count: int, hours: float) -> dict:
    velocity = view_count / hours
    if velocity > 50000:   label = "explosive"
    elif velocity > 10000: label = "viral"
    elif velocity > 1000:  label = "trending"
    else:                  label = "normal"
    return {"value": round(velocity, 2), "label": label}


def compute_engagement_rate(likes: int, comments: int, shares: int, views: int) -> dict:
    if views == 0:
        return {"pct": 0.0, "label": "low"}
    rate = ((likes + comments + shares) / views) * 100
    if rate > 8:   label = "viral"
    elif rate > 3: label = "high"
    elif rate > 1: label = "average"
    else:          label = "low"
    return {"pct": round(rate, 4), "label": label}


def scrape_all_accounts(config: dict) -> list[dict]:
    all_reels = []
    for acc in config["accounts"]:
        username = acc["username"]
        n = acc["reels_to_scrape"]
        url = f"https://www.instagram.com/{username}/"
        log.info(f"Scraping {username} ({acc['niche']}) — {url}")

        entries = ytdlp_extract(url, max_items=n)
        if not entries:
            log.warning(f"  {username}: no entries returned")
            continue

        for e in entries:
            raw = parse_entry(e, acc)
            raw["view_velocity"]    = compute_view_velocity(raw["view_count"], raw["hours_since_posted"])
            raw["engagement_rate"]  = compute_engagement_rate(
                raw["like_count"], raw["comment_count"],
                raw["share_count"], raw["view_count"]
            )
            all_reels.append(raw)

        log.info(f"  {username}: {len(entries)} reels scraped")

    return all_reels


def rescrape_metrics(reel_list: list[dict]) -> list[dict]:
    """Refresh mode: re-scrape metrics for known reel shortcodes."""
    results = []
    now = datetime.now(timezone.utc)
    for entry in reel_list:
        code = entry.get("reel_id")
        url  = f"https://www.instagram.com/p/{code}/"
        log.info(f"  Refreshing {code}...")
        entries = ytdlp_extract(url, max_items=1)
        if not entries:
            log.warning(f"  {code}: could not refresh")
            continue
        e = entries[0]
        posted_ts = e.get("timestamp")
        if isinstance(posted_ts, int):
            posted_at = datetime.fromtimestamp(posted_ts, tz=timezone.utc)
            hours_since = max(1.0, (now - posted_at).total_seconds() / 3600)
        else:
            hours_since = entry.get("hours_since_posted", 1)

        results.append({
            "reel_id":            code,
            "account":            entry.get("account"),
            "niche":              entry.get("niche"),
            "view_count":         int(e.get("view_count") or 0),
            "like_count":         int(e.get("like_count") or 0),
            "comment_count":      int(e.get("comment_count") or 0),
            "share_count":        entry.get("share_count", 0),
            "save_count":         entry.get("save_count", 0),
            "hours_since_posted": round(hours_since, 2),
            "scraped_at":         now.isoformat(),
        })
        log.info(f"  {code}: {e.get('view_count', 0)} views")

    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["full", "refresh"], default="full")
    parser.add_argument("--reel-ids-json", help="JSON with reel_id list (refresh mode)")
    parser.add_argument("--out", default="/tmp/scraper_output.json")
    args = parser.parse_args()

    config = load_config()

    if args.mode == "full":
        result = scrape_all_accounts(config)
    else:
        if not args.reel_ids_json or not os.path.exists(args.reel_ids_json):
            log.error("--reel-ids-json required for refresh mode")
            sys.exit(1)
        with open(args.reel_ids_json) as f:
            reel_list = json.load(f)
        result = rescrape_metrics(reel_list)

    with open(args.out, "w") as f:
        json.dump(result, f, indent=2)
    log.info(f"Output: {args.out} ({len(result)} reels)")


if __name__ == "__main__":
    main()
