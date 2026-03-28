from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from time import sleep
import json
import re

import os
SESSION_ID = os.environ.get("IG_SESSION_ID", "")
TARGET_USERNAME = os.environ.get("IG_TARGET_USERNAME", "finance.and.stockmarkets")

def get_driver():
    options = Options()
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--disable-infobars")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--headless=new")
    options.add_argument("--remote-debugging-port=9222")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    options.add_experimental_option("excludeSwitches", ["enable-logging"])
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    return driver

def inject_session(driver, username):
    driver.get(f"https://www.instagram.com/{username}/")
    sleep(2)
    driver.add_cookie({
        "name": "sessionid",
        "value": SESSION_ID,
        "domain": ".instagram.com",
    })
    driver.refresh()
    sleep(3)
    print(f"✅ Session injected for @{username}")

def scroll_and_collect(driver, callback, max_scrolls=10):
    last_height = driver.execute_script("return document.body.scrollHeight")
    no_change_count = 0
    scrolls = 0

    while scrolls < max_scrolls and no_change_count < 3:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        sleep(3)
        callback(driver)
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            no_change_count += 1
        else:
            no_change_count = 0
        last_height = new_height
        scrolls += 1
        print(f"   📜 Scroll {scrolls}/{max_scrolls}")

def extract_text_safe(driver, selectors):
    """Try multiple selectors, return first match"""
    for selector in selectors:
        try:
            el = driver.find_element(By.CSS_SELECTOR, selector)
            text = el.text.strip()
            if text:
                return text
        except:
            continue
    return "N/A"

def extract_reel_data(driver, reel_url):
    driver.get(reel_url)
    sleep(3)

    shortcode = reel_url.rstrip("/").split("/")[-1]

    # Caption — try multiple selectors
    caption = extract_text_safe(driver, [
        "h1._ap3a",
        "h1",
        "div._a9zs span",
        "div[class*='caption'] span",
        "span._ap3a._aaco._aacu._aacx._aad7._aade",
        "div.C4VMK span",
    ])

    # Likes — try multiple selectors
    likes = extract_text_safe(driver, [
        "span.x193iq5w[dir='auto']",
        "div._aacl._aaco._aacw._aacx._aad7 span",
        "section span span",
        "div[class*='like'] span",
        "button[type='button'] span span",
    ])

    # Comments count
    comments = extract_text_safe(driver, [
        "div._ae2s._ae3v._ae3w span",
        "ul._a9ym li span",
        "span[aria-label*='comment']",
    ])

    # Try getting page source for likes/views via regex
    page_source = driver.page_source
    
    # Extract likes from page source
    likes_match = re.search(r'"like_count":(\d+)', page_source)
    if likes_match:
        likes = likes_match.group(1)

    # Extract view count
    views_match = re.search(r'"play_count":(\d+)', page_source)
    views = views_match.group(1) if views_match else "N/A"

    # Extract comment count
    comments_match = re.search(r'"comment_count":(\d+)', page_source)
    comments = comments_match.group(1) if comments_match else "N/A"

    # Extract caption from page source if not found
    if caption == "N/A":
        caption_match = re.search(r'"caption":\{"text":"(.*?)"', page_source)
        if caption_match:
            caption = caption_match.group(1)

    hashtags = re.findall(r"#\w+", caption) if caption != "N/A" else []
    mentions = re.findall(r"@\w+", caption) if caption != "N/A" else []

    return {
        "shortcode": shortcode,
        "url": reel_url,
        "likes": likes,
        "views": views,
        "comments": comments,
        "caption": caption,
        "hashtags": hashtags,
        "mentions": mentions,
    }

def scrape_reels(username):
    driver = get_driver()
    reels_data = []
    reel_links = []

    try:
        inject_session(driver, username)

        driver.get(f"https://www.instagram.com/{username}/reels/")
        sleep(4)
        print(f"🔍 Scraping reels for @{username}...")

        def collect_reel_links(driver):
            anchors = driver.find_elements(By.TAG_NAME, "a")
            for a in anchors:
                href = a.get_attribute("href")
                if href and "/reel/" in href and href not in reel_links:
                    reel_links.append(href)

        scroll_and_collect(driver, collect_reel_links, max_scrolls=8)
        print(f"✅ Found {len(reel_links)} reel links\n")

        for i, reel_url in enumerate(reel_links[:20]):
            try:
                data = extract_reel_data(driver, reel_url)
                reels_data.append(data)
                print(f"✅ [{i+1}] likes:{data['likes']} views:{data['views']} comments:{data['comments']} tags:{len(data['hashtags'])} | {reel_url}")
            except Exception as e:
                print(f"❌ [{i+1}] Failed: {e}")
            sleep(2)

    finally:
        driver.quit()

    with open(f"{username}_reels.json", "w", encoding="utf-8") as f:
        json.dump(reels_data, f, indent=2, ensure_ascii=False)

    print(f"\n💾 Saved {len(reels_data)} reels to {username}_reels.json")
    return reels_data

if __name__ == "__main__":
    scrape_reels(TARGET_USERNAME)