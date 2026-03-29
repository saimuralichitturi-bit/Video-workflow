"""
main_test.py
Scrape top 5 reels by likes from public Instagram accounts.
No login required — works on public accounts.

Usage:
    python main_test.py
"""

import json
import re
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

TOP_N = 5          # top reels to keep per account
MAX_SCROLLS = 8    # how far to scroll to collect reel links
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

    # Headless + proxy when running in CI (GitHub Actions)
    import os
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


def dismiss_login_modal(driver):
    """Close Instagram's 'Log in to see more' popup if it appears."""
    try:
        close_btn = driver.find_element(
            By.CSS_SELECTOR,
            "button[aria-label='Close'], div[role='dialog'] svg[aria-label='Close']"
        )
        close_btn.click()
        sleep(1)
    except Exception:
        pass
    # Also dismiss by pressing Escape
    try:
        from selenium.webdriver.common.keys import Keys
        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
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

    shortcode    = reel_url.rstrip("/").split("/")[-1]
    page_source  = driver.page_source

    likes_match    = re.search(r'"like_count":(\d+)', page_source)
    views_match    = re.search(r'"play_count":(\d+)', page_source)
    comments_match = re.search(r'"comment_count":(\d+)', page_source)
    caption_match  = re.search(r'"caption":\{"text":"(.*?)"', page_source)

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


def scrape_account(driver, username):
    print(f"\n{'='*50}")
    print(f"Scraping @{username}...")

    links = collect_reel_links(driver, username)
    print(f"  Found {len(links)} reel links")

    reels = []
    for i, url in enumerate(links[:20]):   # visit up to 20, pick top N after
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
