"""
Local test script — run this BEFORE GitHub Actions.
Loads .env, tests Instagram login, saves a session file for reuse.

Usage:
    python test_local.py
"""

import os
import json
from pathlib import Path

# Load .env manually
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

SESSION_FILE = Path(__file__).parent / "instagram_session.json"

from instagrapi import Client
from instagrapi.exceptions import ChallengeRequired, LoginRequired
import instagrapi.extractors as _extractors

# Monkey-patch: Instagram removed pinned_channels_info but instagrapi still expects it
_orig_broadcast = _extractors.extract_broadcast_channel
def _safe_broadcast(data):
    data.setdefault("pinned_channels_info", {"pinned_channels_list": []})
    return _orig_broadcast(data)
_extractors.extract_broadcast_channel = _safe_broadcast

def login() -> Client:
    cl = Client()
    cl.delay_range = [1, 3]

    username = os.environ.get("INSTA_USERNAME")
    password = os.environ.get("INSTA_PASSWORD")
    if not username or not password:
        raise ValueError("INSTA_USERNAME and INSTA_PASSWORD not set in .env")

    print(f"Logging in as {username}...")
    try:
        cl.login(username, password)
    except Exception as e:
        if "challenge" in str(e).lower() or "ChallengeRequired" in str(type(e)):
            print(f"Challenge required: {e}")
            code = input("Check your email/SMS and enter the 6-digit code: ").strip()
            cl.challenge_resolve(cl.last_json)
            cl.challenge_send_security_code(code)
        else:
            raise

    cl.dump_settings(SESSION_FILE)
    print(f"Login successful, session saved to {SESSION_FILE}")
    return cl


def test_scrape(cl: Client):
    print("\nTesting scrape for zerodha...")
    try:
        user = cl.user_info_by_username("zerodha")
        print(f"  User ID: {user.pk}")
        print(f"  Followers: {user.follower_count}")

        medias = cl.user_medias(user.pk, amount=20)
        clips = [m for m in medias if m.media_type == 2]
        print(f"  Fetched {len(clips)} videos/reels")
        for c in clips[:3]:
            print(f"    - {c.code}: {c.view_count} views, {c.like_count} likes, type={getattr(c,'product_type','?')}")
    except ChallengeRequired:
        print("  ERROR: Instagram challenge required.")
        print("  Fix: Open Instagram in your browser, complete any verification,")
        print("       then get a fresh sessionid from cookies and update .env")
    except Exception as e:
        print(f"  ERROR: {e}")


if __name__ == "__main__":
    try:
        cl = login()
        test_scrape(cl)
        print("\nLocal test PASSED. Safe to run on GitHub Actions.")
    except Exception as e:
        print(f"\nFAILED: {e}")
        print("\nSteps to fix:")
        print("1. Open Instagram in Chrome (same browser/network)")
        print("2. F12 -> Application -> Cookies -> instagram.com -> sessionid")
        print("3. Copy the value and update INSTA_SESSION in .env")
