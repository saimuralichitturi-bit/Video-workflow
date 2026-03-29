"""
main_test.py
Scrape top 5 reels by likes from Instagram accounts.
Uses cookies file to stay logged in and get real metrics.

Usage (local):
    python main_test.py
    # cookies loaded from www.instagram.com_cookies.txt automatically

Usage (CI):
    IG_COOKIES_FILE=/tmp/ig_cookies.txt python main_test.py
"""

import os
import json
import re
import http.cookiejar
from pathlib import Path
from time import sleep
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# ── CONFIG ────────────────────────────────────────────────────────────────────
ACCOUNTS = [
    "marketsbyzerodha",
    "wealth",
    "indianfinance.in",
]

TOP_N       = 5    # top reels to keep per account
MAX_SCROLLS = 1    # 1 scroll gives ~20 reels, enough to pick top 5

# Cookies file — Netscape format exported from Chrome
COOKIES_FILE = Path(
    os.environ.get("IG_COOKIES_FILE", "www.instagram.com_cookies.txt")
)
# ─────────────────────────────────────────────────────────────────────────────


def get_driver():
    options = Options()
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1280,900")

    if os.environ.get("CI"):
        options.add_argument("--headless=new")
        options.add_argument("--remote-debugging-port=9222")
        proxy = os.environ.get("SOCKS_PROXY", "socks5://localhost:1080")
        options.add_argument(f"--proxy-server={proxy}")
        options.add_argument(
            "--user-agent=Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )

    options.add_experimental_option("excludeSwitches", ["enable-logging"])
    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()), options=options
    )
    return driver


def inject_cookies(driver):
    """Load Netscape cookies file and inject into Chrome session."""
    if not COOKIES_FILE.exists():
        print(f"WARNING: cookies file not found at {COOKIES_FILE} — scraping without login")
        return

    # Navigate to instagram first so we can set cookies for the domain
    driver.get("https://www.instagram.com/")
    sleep(2)

    jar = http.cookiejar.MozillaCookieJar()
    jar.load(str(COOKIES_FILE), ignore_discard=True, ignore_expires=True)

    injected = 0
    for cookie in jar:
        if "instagram.com" in cookie.domain:
            try:
                driver.add_cookie({
                    "name":   cookie.name,
                    "value":  cookie.value,
                    "domain": cookie.domain,
                    "path":   cookie.path,
                    "secure": cookie.secure,
                })
                injected += 1
            except Exception:
                pass

    driver.refresh()
    sleep(3)
    print(f"  Injected {injected} cookies — logged in as Instagram user")


def dismiss_login_modal(driver):
    """Close Instagram's 'Log in to see more' popup if it appears."""
    try:
        from selenium.webdriver.common.keys import Keys
        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        sleep(1)
    except Exception:
        pass
    try:
        close_btn = driver.find_element(
            By.CSS_SELECTOR,
            "div[role='dialog'] [aria-label='Close']"
        )
        close_btn.click()
        sleep(1)
    except Exception:
        pass


def collect_reel_links(driver, username):
    driver.get(f"https://www.instagram.com/{username}/reels/")
    sleep(4)
    dismiss_login_modal(driver)

    links = []
    last_height = driver.execute_script("return document.body.scrollHeight")
    no_change = 0

    for scroll in range(MAX_SCROLLS):
        dismiss_login_modal(driver)

        for a in driver.find_elements(By.TAG_NAME, "a"):
            href = a.get_attribute("href")
            if href and "/reel/" in href and href not in links:
                links.append(href)

        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        sleep(3)

        new_height = driver.execute_script("return document.body.scrollHeight")
        no_change = 0 if new_height != last_height else no_change + 1
        last_height = new_height

        print(f"  scroll {scroll+1}/{MAX_SCROLLS} — {len(links)} links found")
        if no_change >= 3:
            break

    return links


def extract_reel_data(driver, reel_url, account):
    driver.get(reel_url)
    sleep(3)
    dismiss_login_modal(driver)

    shortcode   = reel_url.rstrip("/").split("/")[-1]
    page_source = driver.page_source

    # Instagram embeds metrics JSON in page source when logged in
    # Use maximal match to get the largest (most accurate) value
    def extract_max(pattern, source):
        matches = re.findall(pattern, source)
        return max((int(m) for m in matches), default=0)

    likes    = extract_max(r'"like_count"\s*:\s*(\d+)', page_source)
    views    = extract_max(r'"video_view_count"\s*:\s*(\d+)', page_source)
    if views == 0:
        views = extract_max(r'"play_count"\s*:\s*(\d+)', page_source)
    comments = extract_max(r'"comment_count"\s*:\s*(\d+)', page_source)

    caption_match = re.search(r'"edge_media_to_caption".*?"text"\s*:\s*"(.*?)"', page_source, re.DOTALL)
    if not caption_match:
        caption_match = re.search(r'"accessibility_caption"\s*:\s*"(.*?)"', page_source)
    caption = caption_match.group(1) if caption_match else ""

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


def scrape_account(driver, username):
    print(f"\n{'='*50}")
    print(f"Scraping @{username}...")

    links = collect_reel_links(driver, username)
    print(f"  Found {len(links)} reel links")

    if not links:
        print("  No links found — Instagram may be blocking. Check cookies.")
        return []

    reels = []
    for i, url in enumerate(links[:20]):
        try:
            data = extract_reel_data(driver, url, username)
            reels.append(data)
            print(f"  [{i+1}] likes:{data['likes']:,}  views:{data['views']:,}  {url}")
        except Exception as e:
            print(f"  [{i+1}] failed: {e}")
        sleep(2)

    top = sorted(reels, key=lambda r: r["likes"], reverse=True)[:TOP_N]
    print(f"  Top {TOP_N} by likes:")
    for r in top:
        print(f"    {r['shortcode']} — {r['likes']:,} likes, {r['views']:,} views")

    return top


def main():
    driver = get_driver()
    all_results = {}

    try:
        inject_cookies(driver)

        for account in ACCOUNTS:
            try:
                top_reels = scrape_account(driver, account)
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
