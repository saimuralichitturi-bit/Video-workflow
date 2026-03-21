"""
scraper.py
Scrape reels from public Instagram accounts using instaloader + cookies.
No login required — uses exported browser cookies (Netscape format).

Modes:
  --mode full     → scrape all accounts, return top_n reel data
  --mode refresh  → re-scrape metrics for existing reel_ids only
"""

import json
import os
import sys
import argparse
import logging
import http.cookiejar
from datetime import datetime, timezone
from pathlib import Path

import instaloader

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

CONFIG_PATH  = Path(__file__).parent.parent / "config" / "accounts.json"
WEIGHTS_PATH = Path(__file__).parent.parent / "config" / "scoring_weights.json"


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def build_loader() -> instaloader.Instaloader:
    L = instaloader.Instaloader(
        quiet=True,
        download_videos=False,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        compress_json=False,
        sleep=True,
        max_connection_attempts=1,   # don't retry for 30 min — fail fast
        request_timeout=60,
    )

    cookies_file = (
        os.environ.get("IG_COOKIES_FILE") or
        os.environ.get("YTDLP_COOKIES_FILE")
    )

    if cookies_file and Path(cookies_file).exists():
        log.info(f"Loading cookies from {cookies_file}")
        jar = http.cookiejar.MozillaCookieJar()
        jar.load(cookies_file, ignore_discard=True, ignore_expires=True)
        L.context._session.cookies = jar
    else:
        log.warning("No cookies file found — scraping without auth (may hit rate limits)")

    return L


def parse_post(post, account_cfg: dict) -> dict:
    now = datetime.now(timezone.utc)
    posted_at = post.date_utc.replace(tzinfo=timezone.utc) if post.date_utc.tzinfo is None else post.date_utc
    hours_since = max(1.0, (now - posted_at).total_seconds() / 3600)

    caption = post.caption or ""
    hashtags = [w for w in caption.split() if w.startswith("#")]

    return {
        "reel_id":            post.shortcode,
        "pk":                 str(post.mediaid),
        "account":            account_cfg["username"],
        "niche":              account_cfg["niche"],
        "url":                f"https://www.instagram.com/p/{post.shortcode}/",
        "posted_at":          posted_at.isoformat(),
        "duration_sec":       int(post.video_duration or 0),
        "hours_since_posted": round(hours_since, 2),
        "view_count":         post.video_view_count or 0,
        "like_count":         post.likes or 0,
        "comment_count":      post.comments or 0,
        "share_count":        0,
        "save_count":         0,
        "caption_full":       caption,
        "hashtags_all":       hashtags,
        "scraped_at":         now.isoformat(),
        "_thumb_url":         post.url,
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


def scrape_account(L: instaloader.Instaloader, account_cfg: dict) -> list[dict]:
    username = account_cfg["username"]
    n = account_cfg["reels_to_scrape"]
    reels = []

    try:
        profile = instaloader.Profile.from_username(L.context, username)
        log.info(f"  {username}: {profile.followers} followers")

        count = 0
        for post in profile.get_posts():
            if not post.is_video:
                continue
            raw = parse_post(post, account_cfg)
            raw["view_velocity"]   = compute_view_velocity(raw["view_count"], raw["hours_since_posted"])
            raw["engagement_rate"] = compute_engagement_rate(
                raw["like_count"], raw["comment_count"],
                raw["share_count"], raw["view_count"]
            )
            reels.append(raw)
            count += 1
            if count >= n:
                break

        log.info(f"  {username}: scraped {len(reels)} reels")
    except instaloader.exceptions.ConnectionException as e:
        if "429" in str(e) or "Too Many Requests" in str(e):
            log.warning(f"  {username}: rate limited (429) — skipping, will retry next run")
        else:
            log.error(f"  {username}: connection error — {e}")
    except Exception as e:
        log.error(f"  {username}: failed — {e}")

    return reels


def scrape_all_accounts(config: dict) -> list[dict]:
    import time
    L = build_loader()
    all_reels = []
    for i, acc in enumerate(config["accounts"]):
        if i > 0:
            time.sleep(8)   # pause between accounts to avoid rate limits
        log.info(f"Scraping {acc['username']} ({acc['niche']})...")
        all_reels.extend(scrape_account(L, acc))
    return all_reels


def rescrape_metrics(reel_list: list[dict]) -> list[dict]:
    """Refresh mode: re-scrape metrics for known shortcodes."""
    L = build_loader()
    results = []
    now = datetime.now(timezone.utc)

    for entry in reel_list:
        code = entry.get("reel_id")
        log.info(f"  Refreshing {code}...")
        try:
            post = instaloader.Post.from_shortcode(L.context, code)
            posted_at = post.date_utc.replace(tzinfo=timezone.utc)
            hours_since = max(1.0, (now - posted_at).total_seconds() / 3600)
            results.append({
                "reel_id":            code,
                "account":            entry.get("account"),
                "niche":              entry.get("niche"),
                "view_count":         post.video_view_count or 0,
                "like_count":         post.likes or 0,
                "comment_count":      post.comments or 0,
                "share_count":        entry.get("share_count", 0),
                "save_count":         entry.get("save_count", 0),
                "hours_since_posted": round(hours_since, 2),
                "scraped_at":         now.isoformat(),
            })
            log.info(f"  {code}: {post.video_view_count} views")
        except Exception as e:
            log.error(f"  {code}: failed — {e}")

    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["full", "refresh"], default="full")
    parser.add_argument("--reel-ids-json")
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
