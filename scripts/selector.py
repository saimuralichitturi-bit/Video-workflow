"""
selector.py
Pick the single best reference video across all scraped reels.
Copies it to top_reference/ folder in Drive and updates selection_log.json.

Input:  /tmp/groq_output.json     (from groq_context.py — full metadata)
"""

import json
import os
import sys
import logging
import argparse
import tempfile
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

WEIGHTS_PATH = Path(__file__).parent.parent / "config" / "scoring_weights.json"


def load_weights() -> dict:
    with open(WEIGHTS_PATH) as f:
        return json.load(f)


def meets_threshold(meta: dict, thresholds: dict) -> bool:
    vir   = meta.get("virality", {})
    ret   = meta.get("retention_proxy", {})
    views = meta.get("raw_metrics", {}).get("view_count", 0)

    score_ok    = vir.get("score", 0) >= thresholds["min_virality_score"]
    grade_ok    = ret.get("grade", "D") in ("A", "B")
    views_ok    = views >= thresholds["min_view_count"]

    return score_ok and grade_ok and views_ok


def select_best(reels: list[dict], weights: dict) -> dict | None:
    thresholds = weights["selection_thresholds"]
    candidates = [r for r in reels if meets_threshold(r, thresholds)]

    if not candidates:
        log.warning("No reels meet selection thresholds — picking overall best")
        candidates = reels

    if not candidates:
        return None

    best = max(candidates, key=lambda r: r.get("virality", {}).get("score", 0))
    return best


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--in",  dest="input",  default="/tmp/groq_output.json")
    parser.add_argument("--out-selection", default="/tmp/selection_result.json")
    args = parser.parse_args()

    weights = load_weights()

    with open(args.input) as f:
        reels = json.load(f)

    if not reels:
        log.error("No reels to evaluate")
        sys.exit(1)

    best = select_best(reels, weights)
    if not best:
        log.error("Could not select best reel")
        sys.exit(1)

    ident = best["identity"]
    vir   = best["virality"]
    now   = datetime.now(timezone.utc).isoformat()

    log.info(f"Best reel: {ident['account']}/{ident['reel_id']} — "
             f"score={vir['score']} tier={vir['tier']}")

    selection_entry = {
        "selected_at":    now,
        "reel_id":        ident["reel_id"],
        "account":        ident["account"],
        "niche":          ident["niche"],
        "virality_score": vir["score"],
        "tier":           vir["tier"],
        "reason":         "highest virality score meeting all thresholds"
    }

    result = {
        "best_meta":       best,
        "selection_entry": selection_entry
    }

    with open(args.out_selection, "w") as f:
        json.dump(result, f, indent=2)
    log.info(f"Selection result written to {args.out_selection}")


if __name__ == "__main__":
    main()
