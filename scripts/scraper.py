"""
scraper.py
Fetch reels from target Instagram accounts, compute raw + virality scores,
and return top_n reels per account.

Modes:
  --mode full     → scrape all accounts, return top_n reel data (used by daily_download.yml)
  --mode refresh  → re-scrape metrics for existing reel_ids only (used by refresh_metrics.yml)
"""

import json
import os
import sys
import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path

from instagrapi import Client
from instagrapi.exceptions import LoginRequired, ChallengeRequired

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent.parent / "config" / "accounts.json"
WEIGHTS_PATH = Path(__file__).parent.parent / "config" / "scoring_weights.json"


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)

def load_weights():
    with open(WEIGHTS_PATH) as f:
        return json.load(f)

def instagram_login() -> Client:
    session_id = os.environ.get("INSTAGRAM_SESSION_ID")
    if not session_id:
        raise ValueError("INSTAGRAM_SESSION_ID env var not set")
    cl = Client()
    cl.login_by_sessionid(session_id)
    log.info("Instagram login successful")
    return cl


def fetch_account_reels(cl: Client, username: str, n: int) -> list:
    try:
        user = cl.user_info_by_username(username)
        clips = cl.user_clips(user.pk, amount=n)
        log.info(f"  {username}: fetched {len(clips)} reels")
        return clips
    except ChallengeRequired:
        log.error(f"  {username}: challenge required — session needs refresh")
        return []
    except Exception as e:
        log.error(f"  {username}: failed to fetch reels — {e}")
        return []


def build_raw_data(media, account_cfg: dict) -> dict:
    now = datetime.now(timezone.utc)
    posted_at = media.taken_at.replace(tzinfo=timezone.utc) if media.taken_at.tzinfo is None else media.taken_at
    hours_since = max(1.0, (now - posted_at).total_seconds() / 3600)

    caption_text = ""
    if media.caption_text:
        caption_text = media.caption_text
    elif hasattr(media, "caption") and media.caption:
        caption_text = getattr(media.caption, "text", "")

    # Extract hashtags from caption
    hashtags = [w for w in caption_text.split() if w.startswith("#")]

    return {
        "reel_id":          media.code,
        "pk":               str(media.pk),
        "account":          account_cfg["username"],
        "niche":            account_cfg["niche"],
        "url":              f"instagram.com/reel/{media.code}",
        "posted_at":        posted_at.isoformat(),
        "duration_sec":     int(media.video_duration or 0),
        "hours_since_posted": round(hours_since, 2),
        "view_count":       media.view_count or 0,
        "like_count":       media.like_count or 0,
        "comment_count":    media.comment_count or 0,
        "share_count":      0,  # not exposed by Instagram private API
        "save_count":       0,  # not exposed by Instagram private API
        "caption_full":     caption_text,
        "hashtags_all":     hashtags,
        "scraped_at":       now.isoformat(),
    }


def compute_view_velocity(view_count: int, hours: float) -> dict:
    velocity = view_count / hours
    if velocity > 50000:
        label = "explosive"
    elif velocity > 10000:
        label = "viral"
    elif velocity > 1000:
        label = "trending"
    else:
        label = "normal"
    return {"value": round(velocity, 2), "label": label}


def compute_engagement_rate(likes: int, comments: int, shares: int, views: int) -> dict:
    if views == 0:
        return {"pct": 0.0, "label": "low"}
    rate = ((likes + comments + shares) / views) * 100
    if rate > 8:
        label = "viral"
    elif rate > 3:
        label = "high"
    elif rate > 1:
        label = "average"
    else:
        label = "low"
    return {"pct": round(rate, 4), "label": label}


def scrape_all_accounts(cl: Client, config: dict) -> list[dict]:
    """Full mode: scrape all accounts, return raw reel data."""
    all_reels = []
    for acc in config["accounts"]:
        log.info(f"Scraping {acc['username']} ({acc['niche']})...")
        medias = fetch_account_reels(cl, acc["username"], acc["reels_to_scrape"])
        for m in medias:
            raw = build_raw_data(m, acc)
            vel = compute_view_velocity(raw["view_count"], raw["hours_since_posted"])
            eng = compute_engagement_rate(
                raw["like_count"], raw["comment_count"],
                raw["share_count"], raw["view_count"]
            )
            raw["view_velocity"] = vel
            raw["engagement_rate"] = eng
            all_reels.append(raw)
    return all_reels


def rescrape_metrics(cl: Client, reel_ids: list[dict]) -> list[dict]:
    """Refresh mode: re-scrape raw metrics for known reel_ids."""
    results = []
    now = datetime.now(timezone.utc)
    for entry in reel_ids:
        code = entry.get("reel_id")
        try:
            media = cl.media_info_by_url(f"https://www.instagram.com/reel/{code}/")
            posted_at = media.taken_at.replace(tzinfo=timezone.utc) if media.taken_at.tzinfo is None else media.taken_at
            hours_since = max(1.0, (now - posted_at).total_seconds() / 3600)
            results.append({
                "reel_id":       code,
                "account":       entry.get("account"),
                "niche":         entry.get("niche"),
                "view_count":    media.view_count or 0,
                "like_count":    media.like_count or 0,
                "comment_count": media.comment_count or 0,
                "share_count":   entry.get("share_count", 0),
                "save_count":    entry.get("save_count", 0),
                "hours_since_posted": round(hours_since, 2),
                "scraped_at":    now.isoformat(),
            })
            log.info(f"  refreshed {code}: {media.view_count} views")
        except Exception as e:
            log.error(f"  failed to refresh {code}: {e}")
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["full", "refresh"], default="full")
    parser.add_argument("--reel-ids-json", help="Path to JSON with reel_id list (refresh mode)")
    parser.add_argument("--out", default="/tmp/scraper_output.json")
    args = parser.parse_args()

    config = load_config()

    try:
        cl = instagram_login()
    except Exception as e:
        log.error(f"Login failed: {e}")
        sys.exit(1)

    if args.mode == "full":
        result = scrape_all_accounts(cl, config)
    else:
        if not args.reel_ids_json or not os.path.exists(args.reel_ids_json):
            log.error("--reel-ids-json required for refresh mode")
            sys.exit(1)
        with open(args.reel_ids_json) as f:
            reel_ids = json.load(f)
        result = rescrape_metrics(cl, reel_ids)

    with open(args.out, "w") as f:
        json.dump(result, f, indent=2)
    log.info(f"Output written to {args.out} ({len(result)} reels)")


if __name__ == "__main__":
    main()
