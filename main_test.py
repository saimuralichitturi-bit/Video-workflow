"""
main_test.py
1. Scrape top reels by likes from Instagram accounts
2. Upload timestamped JSON to Cloudflare R2
3. Use Groq Llama to pick the best reel of the day
4. Append best reel to best_reels_log.json (cumulative, committed to repo)
5. Clean up R2 files older than 10 days

Usage (local):  python main_test.py
Usage (CI):     env vars passed via GitHub Actions secrets
"""

import os
import json
import re
import http.cookiejar
from pathlib import Path
from time import sleep
from datetime import datetime, timezone, timedelta

import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# ── load .env locally ─────────────────────────────────────────────────────────
_env = Path(__file__).parent / ".env"
if _env.exists():
    for _line in _env.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

# ── CONFIG ────────────────────────────────────────────────────────────────────
ACCOUNTS = [
    "marketsbyzerodha",
    "wealth",
    "indianfinance.in",
]

TOP_N          = 5    # top reels per account
MAX_SCROLLS    = 1    # 1 scroll is enough for ~20 links
R2_RETAIN_DAYS = 10   # delete R2 files older than this

COOKIES_FILE  = Path(os.environ.get("IG_COOKIES_FILE", "www.instagram.com_cookies.txt"))
R2_WORKER_URL = os.environ.get("R2_WORKER_URL", "").rstrip("/")
R2_API_KEY    = os.environ.get("R2_API_KEY", "")
GROQ_API_KEY  = os.environ.get("GROQ_API_KEY", "")
BEST_LOG_FILE = Path(__file__).parent / "best_reels_log.json"
# ─────────────────────────────────────────────────────────────────────────────


# ── R2 helpers ────────────────────────────────────────────────────────────────

def r2_put(path: str, data) -> bool:
    if not R2_WORKER_URL or not R2_API_KEY:
        return False
    body = json.dumps(data, ensure_ascii=False) if isinstance(data, (dict, list)) else data
    resp = requests.put(
        f"{R2_WORKER_URL}/{path}",
        data=body,
        headers={"Content-Type": "application/json", "X-API-Key": R2_API_KEY},
        timeout=30,
    )
    ok = resp.status_code in (200, 201)
    if not ok:
        print(f"  R2 PUT failed [{resp.status_code}]: {resp.text[:200]}")
    return ok


def r2_get(path: str):
    if not R2_WORKER_URL or not R2_API_KEY:
        return None
    resp = requests.get(
        f"{R2_WORKER_URL}/{path}",
        headers={"X-API-Key": R2_API_KEY},
        timeout=30,
    )
    if resp.status_code == 200:
        return resp.json()
    return None


def r2_delete(path: str):
    if not R2_WORKER_URL or not R2_API_KEY:
        return
    resp = requests.delete(
        f"{R2_WORKER_URL}/{path}",
        headers={"X-API-Key": R2_API_KEY},
        timeout=30,
    )
    if resp.status_code in (200, 204):
        print(f"  Deleted from R2: {path}")
    else:
        print(f"  R2 DELETE failed [{resp.status_code}]: {path}")


def cleanup_old_r2_files():
    """Delete R2 files older than R2_RETAIN_DAYS using manifest.json."""
    manifest = r2_get("manifest.json") or {"files": []}
    cutoff   = datetime.now(timezone.utc) - timedelta(days=R2_RETAIN_DAYS)
    keep     = []

    for entry in manifest.get("files", []):
        try:
            uploaded_at = datetime.fromisoformat(entry["uploaded_at"])
            if uploaded_at < cutoff:
                print(f"  Removing old R2 file: {entry['filename']}")
                r2_delete(entry["filename"])
            else:
                keep.append(entry)
        except Exception:
            keep.append(entry)

    manifest["files"] = keep
    return manifest


def upload_to_r2(all_results: dict, filename: str, manifest: dict):
    """Upload JSON and update manifest."""
    if r2_put(filename, all_results):
        print(f"  Uploaded: {filename}")
        manifest["files"].append({
            "filename":    filename,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
        })
    r2_put("latest.json", all_results)
    r2_put("manifest.json", manifest)


# ── Groq best-reel picker ─────────────────────────────────────────────────────

def pick_best_with_groq(all_results: dict) -> dict | None:
    """Use Groq Llama 3.3 70B to pick the single best reel to clone."""
    all_reels = [r for reels in all_results.values() for r in reels]
    if not all_reels:
        return None

    if not GROQ_API_KEY:
        print("  GROQ_API_KEY not set — using top-likes fallback")
        best = max(all_reels, key=lambda r: r["likes"])
        best["groq_reason"] = "fallback: highest likes"
        return best

    summary = json.dumps([
        {
            "shortcode": r["shortcode"],
            "account":   r["account"],
            "likes":     r["likes"],
            "views":     r["views"],
            "comments":  r["comments"],
            "caption":   r["caption"][:300],
            "hashtags":  r["hashtags"][:5],
        }
        for r in all_reels
    ], indent=2)

    prompt = f"""You are a finance content strategist analyzing Instagram reels.
Pick the single best reel to study and recreate based on:
1. High engagement (likes + comments vs views ratio)
2. Trending finance topic in the caption
3. Good hashtag strategy

Reels data:
{summary}

Reply with ONLY this JSON (no extra text):
{{"shortcode": "...", "reason": "one sentence why this is the best to clone"}}"""

    try:
        from groq import Groq
        client   = Groq(api_key=GROQ_API_KEY)
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150,
            temperature=0.2,
        )
        text  = response.choices[0].message.content.strip()
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            picked     = json.loads(match.group())
            shortcode  = picked.get("shortcode", "")
            reason     = picked.get("reason", "")
            for reel in all_reels:
                if reel["shortcode"] == shortcode:
                    reel["groq_reason"] = reason
                    print(f"  Groq picked: {shortcode} — {reason}")
                    return reel
    except Exception as e:
        print(f"  Groq failed: {e} — using fallback")

    best = max(all_reels, key=lambda r: r["likes"])
    best["groq_reason"] = "fallback: highest likes"
    return best


# ── best_reels_log.json ───────────────────────────────────────────────────────

def append_to_best_log(best_reel: dict):
    """Append today's best reel to best_reels_log.json."""
    log = []
    if BEST_LOG_FILE.exists():
        with open(BEST_LOG_FILE) as f:
            log = json.load(f)

    log.append({
        "date":       datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "shortcode":  best_reel["shortcode"],
        "account":    best_reel["account"],
        "url":        best_reel["url"],
        "likes":      best_reel["likes"],
        "views":      best_reel["views"],
        "comments":   best_reel["comments"],
        "caption":    best_reel.get("caption", "")[:300],
        "hashtags":   best_reel.get("hashtags", []),
        "groq_reason": best_reel.get("groq_reason", ""),
        "scraped_at": best_reel.get("scraped_at", ""),
    })

    with open(BEST_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)

    print(f"  Appended to {BEST_LOG_FILE.name} (total {len(log)} entries)")


# ── Selenium scraper ──────────────────────────────────────────────────────────

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
    return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)


def inject_cookies(driver):
    if not COOKIES_FILE.exists():
        print(f"WARNING: {COOKIES_FILE} not found — scraping without login")
        return
    driver.get("https://www.instagram.com/")
    sleep(2)
    jar = http.cookiejar.MozillaCookieJar()
    jar.load(str(COOKIES_FILE), ignore_discard=True, ignore_expires=True)
    injected = 0
    for c in jar:
        if "instagram.com" in c.domain:
            try:
                driver.add_cookie({"name": c.name, "value": c.value,
                                   "domain": c.domain, "path": c.path, "secure": c.secure})
                injected += 1
            except Exception:
                pass
    driver.refresh()
    sleep(3)
    print(f"  Injected {injected} cookies")


def dismiss_modal(driver):
    try:
        from selenium.webdriver.common.keys import Keys
        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        sleep(1)
    except Exception:
        pass
    try:
        driver.find_element(By.CSS_SELECTOR, "div[role='dialog'] [aria-label='Close']").click()
        sleep(1)
    except Exception:
        pass


def collect_reel_links(driver, username):
    driver.get(f"https://www.instagram.com/{username}/reels/")
    sleep(4)
    dismiss_modal(driver)
    links      = []
    last_h     = driver.execute_script("return document.body.scrollHeight")
    no_change  = 0
    for scroll in range(MAX_SCROLLS):
        dismiss_modal(driver)
        for a in driver.find_elements(By.TAG_NAME, "a"):
            href = a.get_attribute("href")
            if href and "/reel/" in href and href not in links:
                links.append(href)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        sleep(3)
        new_h     = driver.execute_script("return document.body.scrollHeight")
        no_change = 0 if new_h != last_h else no_change + 1
        last_h    = new_h
        print(f"  scroll {scroll+1}/{MAX_SCROLLS} — {len(links)} links")
        if no_change >= 3:
            break
    return links


def extract_reel_data(driver, reel_url, account):
    driver.get(reel_url)
    sleep(3)
    dismiss_modal(driver)

    shortcode = reel_url.rstrip("/").split("/")[-1]
    src       = driver.page_source

    # Locate the JSON chunk specific to this reel by shortcode
    pos   = src.find(f'"{shortcode}"')
    chunk = src[pos:pos + 2000] if pos != -1 else src

    def first_match(pattern, text):
        m = re.search(pattern, text)
        return int(m.group(1)) if m else 0

    likes    = first_match(r'"like_count"\s*:\s*(\d+)', chunk)
    views    = first_match(r'"video_view_count"\s*:\s*(\d+)', chunk)
    if views == 0:
        views = first_match(r'"play_count"\s*:\s*(\d+)', chunk)
    if views == 0:
        views = first_match(r'"view_count"\s*:\s*(\d+)', chunk)
    comments = first_match(r'"comment_count"\s*:\s*(\d+)', chunk)

    # caption from the reel-specific chunk first, fallback to full page
    cap = re.search(r'"caption_text"\s*:\s*"(.*?)"', chunk)
    if not cap:
        cap = re.search(r'"edge_media_to_caption".*?"text"\s*:\s*"(.*?)"', src, re.DOTALL)
    if not cap:
        cap = re.search(r'"accessibility_caption"\s*:\s*"(.*?)"', src)
    caption  = cap.group(1) if cap else ""
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
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }


def scrape_account(driver, username):
    print(f"\n{'='*50}\nScraping @{username}...")
    links = collect_reel_links(driver, username)
    print(f"  Found {len(links)} reel links")
    if not links:
        print("  No links — check cookies or account name")
        return []
    reels = []
    for i, url in enumerate(links[:20]):
        try:
            data = extract_reel_data(driver, url, username)
            reels.append(data)
            print(f"  [{i+1}] likes:{data['likes']:,}  views:{data['views']:,}  comments:{data['comments']:,}")
        except Exception as e:
            print(f"  [{i+1}] failed: {e}")
        sleep(2)
    top = sorted(reels, key=lambda r: r["likes"], reverse=True)[:TOP_N]
    print(f"  Top {TOP_N}: " + ", ".join(f"{r['shortcode']}({r['likes']:,}L)" for r in top))
    return top


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    driver      = get_driver()
    all_results = {}

    try:
        inject_cookies(driver)
        for account in ACCOUNTS:
            try:
                all_results[account] = scrape_account(driver, account)
            except Exception as e:
                print(f"  ERROR {account}: {e}")
                all_results[account] = []
    finally:
        driver.quit()

    total = sum(len(v) for v in all_results.values())
    print(f"\n{'='*50}\nScraped {total} reels across {len(ACCOUNTS)} accounts")

    # 1. Cleanup R2 files older than 10 days + get updated manifest
    print("\n[R2] Cleaning up old files...")
    manifest = cleanup_old_r2_files()

    # 2. Upload today's results to R2
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    filename  = f"reels_{timestamp}.json"
    print(f"[R2] Uploading {filename}...")
    upload_to_r2(all_results, filename, manifest)

    # 3. Save locally too
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)
    print(f"[local] Saved {filename}")

    # 4. Groq picks best reel
    print("\n[Groq] Picking best reel...")
    best = pick_best_with_groq(all_results)

    if best:
        print(f"\nBest reel: {best['account']}/{best['shortcode']}")
        print(f"  likes:{best['likes']:,}  views:{best['views']:,}  comments:{best['comments']:,}")
        print(f"  reason: {best.get('groq_reason','')}")

        # 5. Append to best_reels_log.json
        append_to_best_log(best)
    else:
        print("No reels found — nothing to log")


if __name__ == "__main__":
    main()
