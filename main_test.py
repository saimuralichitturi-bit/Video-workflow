"""
main_test.py
Scrape top 5 reels per account using Selenium + session cookie.
Runs locally — no VM, no GitHub Actions needed.

Usage:
    python main_test.py

Set your Instagram sessionid in IG_SESSION_ID env var or hardcode below.
"""

import os
import json
import re
from pathlib import Path
from time import sleep
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# ── CONFIG ────────────────────────────────────────────────────────────────────
SESSION_FILE = Path(__file__).parent / "session.json"

ACCOUNTS = [
    "marketsbyzerodha",
    "wealth",
    "indianfinance.in",
]

TOP_N = 5          # top reels to keep per account
MAX_SCROLLS = 8    # how far to scroll on reels page to collect links
# ─────────────────────────────────────────────────────────────────────────────


def load_session_id() -> str:
    """Read sessionid from session.json cookies dict."""
    if not SESSION_FILE.exists():
        raise FileNotFoundError(
            f"session.json not found at {SESSION_FILE}\n"
            "Run this once to create it:\n"
            "  python -c \"from instagrapi import Client; cl = Client(); "
            "cl.login('YOUR_USERNAME','YOUR_PASSWORD'); cl.dump_settings('session.json')\""
        )

    with open(SESSION_FILE) as f:
        data = json.load(f)

    cookies = data.get("cookies", {})
    session_id = cookies.get("sessionid", "")

    if not session_id:
        raise ValueError(
            "session.json has no sessionid cookie — session may be empty.\n"
            "Re-login with instagrapi to populate it:\n"
            "  python -c \"from instagrapi import Client; cl = Client(); "
            "cl.login('YOUR_USERNAME','YOUR_PASSWORD'); cl.dump_settings('session.json')\""
        )

    return session_id


def load_all_cookies() -> dict:
    """Return all cookies from session.json."""
    with open(SESSION_FILE) as f:
        return json.load(f).get("cookies", {})
# ─────────────────────────────────────────────────────────────────────────────


def get_driver():
    options = Options()
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_experimental_option("excludeSwitches", ["enable-logging"])
    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()), options=options
    )
    driver.set_window_size(1280, 900)
    return driver


def inject_session(driver, username, cookies: dict):
    driver.get(f"https://www.instagram.com/{username}/")
    sleep(2)
    for name, value in cookies.items():
        try:
            driver.add_cookie({"name": name, "value": str(value), "domain": ".instagram.com"})
        except Exception:
            pass
    driver.refresh()
    sleep(3)


def collect_reel_links(driver, username, max_scrolls=MAX_SCROLLS):
    driver.get(f"https://www.instagram.com/{username}/reels/")
    sleep(4)

    links = []
    last_height = driver.execute_script("return document.body.scrollHeight")
    no_change = 0

    for scroll in range(max_scrolls):
        for a in driver.find_elements(By.TAG_NAME, "a"):
            href = a.get_attribute("href")
            if href and "/reel/" in href and href not in links:
                links.append(href)

        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        sleep(3)

        new_height = driver.execute_script("return document.body.scrollHeight")
        no_change = 0 if new_height != last_height else no_change + 1
        last_height = new_height

        print(f"  scroll {scroll+1}/{max_scrolls} — {len(links)} links found")
        if no_change >= 3:
            break

    return links


def extract_reel_data(driver, reel_url, account):
    driver.get(reel_url)
    sleep(3)

    shortcode = reel_url.rstrip("/").split("/")[-1]
    page_source = driver.page_source

    likes_match   = re.search(r'"like_count":(\d+)', page_source)
    views_match   = re.search(r'"play_count":(\d+)', page_source)
    comments_match = re.search(r'"comment_count":(\d+)', page_source)
    caption_match = re.search(r'"caption":\{"text":"(.*?)"', page_source)

    likes    = int(likes_match.group(1))    if likes_match    else 0
    views    = int(views_match.group(1))    if views_match    else 0
    comments = int(comments_match.group(1)) if comments_match else 0
    caption  = caption_match.group(1)       if caption_match  else ""

    hashtags = re.findall(r"#\w+", caption)

    return {
        "shortcode":  shortcode,
        "account":    account,
        "url":        reel_url,
        "views":      views,
        "likes":      likes,
        "comments":   comments,
        "caption":    caption,
        "hashtags":   hashtags,
        "scraped_at": datetime.utcnow().isoformat(),
    }


def scrape_account(driver, username, cookies: dict):
    print(f"\n{'='*50}")
    print(f"Scraping @{username}...")

    inject_session(driver, username, cookies)
    links = collect_reel_links(driver, username)
    print(f"  Found {len(links)} reel links")

    reels = []
    for i, url in enumerate(links[:20]):   # visit up to 20, pick top 5 after
        try:
            data = extract_reel_data(driver, url, username)
            reels.append(data)
            print(f"  [{i+1}] views:{data['views']:,}  likes:{data['likes']:,}  {url}")
        except Exception as e:
            print(f"  [{i+1}] failed: {e}")
        sleep(2)

    top = sorted(reels, key=lambda r: r["views"], reverse=True)[:TOP_N]
    print(f"  Top {TOP_N} by views:")
    for r in top:
        print(f"    {r['shortcode']} — {r['views']:,} views, {r['likes']:,} likes")

    return top


def main():
    cookies = load_all_cookies()
    print(f"Loaded session from {SESSION_FILE} ({len(cookies)} cookies)")

    driver = get_driver()
    all_results = {}

    try:
        for account in ACCOUNTS:
            try:
                top_reels = scrape_account(driver, account, cookies)
                all_results[account] = top_reels
            except Exception as e:
                print(f"  ERROR scraping {account}: {e}")
                all_results[account] = []
    finally:
        driver.quit()

    out_file = f"reels_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*50}")
    print(f"Saved to {out_file}")
    total = sum(len(v) for v in all_results.values())
    print(f"Total: {total} reels across {len(ACCOUNTS)} accounts")


if __name__ == "__main__":
    main()
