"""
metrics.py
Compute all derived metrics + virality scores for scraped reels.
Normalizes view_velocity and engagement_rate across the entire batch
(percentile rank within niche).

Input:  /tmp/scraper_output.json  (from scraper.py)
Output: /tmp/metrics_output.json  (full metadata per reel)
"""

import json
import argparse
import logging
from pathlib import Path
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

WEIGHTS_PATH = Path(__file__).parent.parent / "config" / "scoring_weights.json"


def load_weights() -> dict:
    with open(WEIGHTS_PATH) as f:
        return json.load(f)


def percentile_rank(value: float, all_values: list[float]) -> float:
    """0-1 percentile rank of value within a list."""
    if len(all_values) <= 1:
        return 1.0
    below = sum(1 for v in all_values if v < value)
    return round(below / (len(all_values) - 1), 4)


def grade_retention(score: float) -> str:
    if score >= 0.70:
        return "A"
    elif score >= 0.50:
        return "B"
    elif score >= 0.30:
        return "C"
    return "D"


def grade_virality_tier(score: float) -> str:
    if score >= 0.90:
        return "S"
    elif score >= 0.75:
        return "A"
    elif score >= 0.55:
        return "B"
    return "C"


def compute_retention_proxy(raw: dict, weights: dict) -> dict:
    views = raw["view_count"]
    if views == 0:
        return {"score": 0.0, "grade": "D", "signals": {}}

    rw = weights["retention_signals"]

    comment_val = raw["comment_count"] / views
    like_val    = raw["like_count"]    / views
    share_val   = raw["share_count"]   / views
    save_val    = raw["save_count"]    / views

    # Simple 0-1 scale via tanh-like normalization (cap at known maxes)
    def norm(val, cap):
        return min(1.0, val / cap) if cap > 0 else 0.0

    c_score = norm(comment_val, 0.10)
    l_score = norm(like_val,    0.05)
    sh_score = norm(share_val,  0.01)
    sv_score = norm(save_val,   0.005)

    retention_score = (
        c_score  * rw["comment_signal"] +
        l_score  * rw["like_signal"]    +
        sh_score * rw["share_signal"]   +
        sv_score * rw["save_signal"]
    )
    retention_score = round(min(1.0, retention_score), 4)

    return {
        "score": retention_score,
        "grade": grade_retention(retention_score),
        "grade_scale": {
            "A": "0.70-1.00 — people watched most of it",
            "B": "0.50-0.69 — decent watch time",
            "C": "0.30-0.49 — high drop-off",
            "D": "0.00-0.29 — people swiped away fast"
        },
        "signals": {
            "comment_signal": {
                "value":   round(comment_val, 6),
                "score":   round(c_score, 4),
                "weight":  rw["comment_signal"],
                "meaning": "comments/views — high means watched enough to react"
            },
            "like_signal": {
                "value":   round(like_val, 6),
                "score":   round(l_score, 4),
                "weight":  rw["like_signal"],
                "meaning": "likes/views — high means hook worked + watched enough"
            },
            "share_signal": {
                "value":   round(share_val, 6),
                "score":   round(sh_score, 4),
                "weight":  rw["share_signal"],
                "meaning": "shares/views — highest intent signal, watched fully"
            },
            "save_signal": {
                "value":   round(save_val, 6),
                "score":   round(sv_score, 4),
                "weight":  rw["save_signal"],
                "meaning": "saves/views — saved means will watch again"
            }
        },
        "formula": "(comment x 0.35) + (like x 0.25) + (share x 0.30) + (save x 0.10)"
    }


def build_full_metadata(raw: dict, vel_norm: float, eng_norm: float, weights: dict) -> dict:
    w = weights
    now = datetime.now(timezone.utc).isoformat()
    views  = raw["view_count"]
    likes  = raw["like_count"]
    cmnts  = raw["comment_count"]
    shares = raw["share_count"]
    saves  = raw["save_count"]
    hours  = raw["hours_since_posted"]

    engagement_pct = ((likes + cmnts + shares) / views * 100) if views else 0

    retention = compute_retention_proxy(raw, weights)

    recency_boost = max(0.0, round(1 - (hours / 168), 4))

    virality_score = round(
        vel_norm * w["view_velocity"]   +
        eng_norm * w["engagement_rate"] +
        retention["score"] * w["retention_proxy"] +
        recency_boost * w["recency_boost"],
        4
    )

    tier = grade_virality_tier(virality_score)
    ready = virality_score >= w["selection_thresholds"]["min_virality_score"] and \
            retention["grade"] in ("A", "B") and \
            views >= w["selection_thresholds"]["min_view_count"]

    caption = raw.get("caption_full", "")
    hashtags = raw.get("hashtags_all", [])

    return {
        "identity": {
            "reel_id":         raw["reel_id"],
            "account":         raw["account"],
            "niche":           raw["niche"],
            "url":             raw["url"],
            "posted_at":       raw["posted_at"],
            "downloaded_at":   "",
            "last_updated_at": now,
            "duration_sec":    raw.get("duration_sec", 0),
            "aspect_ratio":    "9:16",
            "language":        "en"
        },
        "raw_metrics": {
            "view_count":    views,
            "like_count":    likes,
            "comment_count": cmnts,
            "share_count":   shares,
            "save_count":    saves,
            "scraped_at":    raw.get("scraped_at", now)
        },
        "computed_metrics": {
            "hours_since_posted":        round(hours, 2),
            "view_velocity":             raw.get("view_velocity", {}).get("value", 0),
            "view_velocity_label":       raw.get("view_velocity", {}).get("label", ""),
            "view_velocity_meaning":     "views per hour since posted",
            "engagement_rate_pct":       round(engagement_pct, 4),
            "engagement_label":          raw.get("engagement_rate", {}).get("label", ""),
            "engagement_meaning":        "((likes+comments+shares)/views)x100",
            "like_to_view_pct":          round(likes / views * 100, 4) if views else 0,
            "comment_to_view_pct":       round(cmnts / views * 100, 4) if views else 0,
            "share_to_view_pct":         round(shares / views * 100, 4) if views else 0,
            "save_to_view_pct":          round(saves / views * 100, 4) if views else 0,
            "share_save_ratio":          round(shares / saves, 4) if saves else 0,
            "share_save_meaning":        "shares/saves — high means viral content"
        },
        "retention_proxy": retention,
        "virality": {
            "score":            virality_score,
            "tier":             tier,
            "tier_scale": {
                "S": "0.90-1.00 — clone immediately",
                "A": "0.75-0.89 — strong reference",
                "B": "0.55-0.74 — decent reference",
                "C": "0.00-0.54 — skip this video"
            },
            "ready_for_cloning": ready,
            "clone_priority":    "high" if tier == "S" else "medium" if tier == "A" else "low",
            "score_breakdown": {
                "view_velocity_contribution":   round(vel_norm * w["view_velocity"], 4),
                "engagement_contribution":      round(eng_norm * w["engagement_rate"], 4),
                "retention_proxy_contribution": round(retention["score"] * w["retention_proxy"], 4),
                "recency_contribution":         round(recency_boost * w["recency_boost"], 4)
            },
            "formula": "(velocity x 0.35) + (engagement x 0.25) + (retention x 0.30) + (recency x 0.10)"
        },
        "content": {
            "caption_full":      caption,
            "caption_keywords":  [],
            "hashtags_all":      hashtags,
            "hashtags_top5":     hashtags[:5],
            "audio_title":       "",
            "audio_is_original": True,
            "has_text_overlay":  False,
            "has_captions":      False,
            "has_cta":           False,
            "cta_text":          "",
            "topic_summary":     "",
            "content_type":      "educational",
            "tone":              "conversational"
        },
        "decision_summary": {
            "virality_score":      virality_score,
            "tier":                tier,
            "retention_grade":     retention["grade"],
            "engagement_rate_pct": round(engagement_pct, 4),
            "total_views":         views,
            "total_likes":         likes,
            "total_shares":        shares,
            "total_comments":      cmnts,
            "total_saves":         saves,
            "view_velocity":       raw.get("view_velocity", {}).get("value", 0),
            "hours_since_posted":  round(hours, 2),
            "top_hashtags":        hashtags[:3],
            "hook_type":           "",
            "pacing":              "",
            "bpm":                 0,
            "mood":                "",
            "ready_for_cloning":   ready,
            "clone_priority":      "high" if tier == "S" else "medium" if tier == "A" else "low",
            "why_clone_this":      [],
            "clone_strategy":      ""
        },
        "drive": {
            "video_filename": f"{raw['account']}_{raw['reel_id']}.mp4",
            "json_filename":  f"{raw['account']}_{raw['reel_id']}.json",
            "thumb_filename": f"{raw['account']}_{raw['reel_id']}_thumb.jpg",
            "folder_path":    f"AI_Reel_Generator/reels_library/{raw['niche']}/{raw['account']}/",
            "video_file_id":  "",
            "json_file_id":   "",
            "thumb_file_id":  "",
            "file_size_mb":   0
        }
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--in",  dest="input",  default="/tmp/scraper_output.json")
    parser.add_argument("--out", dest="output", default="/tmp/metrics_output.json")
    args = parser.parse_args()

    weights = load_weights()

    with open(args.input) as f:
        reels = json.load(f)

    if not reels:
        log.warning("No reels to process")
        with open(args.output, "w") as f:
            json.dump([], f)
        return

    # Normalize velocity + engagement per niche using percentile rank
    niches = set(r["niche"] for r in reels)
    vel_norms = {}
    eng_norms = {}

    for niche in niches:
        batch = [r for r in reels if r["niche"] == niche]
        vels = [r.get("view_velocity", {}).get("value", 0) if isinstance(r.get("view_velocity"), dict) else 0 for r in batch]
        engs = [r.get("engagement_rate", {}).get("pct", 0) if isinstance(r.get("engagement_rate"), dict) else 0 for r in batch]
        for r in batch:
            rid = r["reel_id"]
            v = r.get("view_velocity", {}).get("value", 0) if isinstance(r.get("view_velocity"), dict) else 0
            e = r.get("engagement_rate", {}).get("pct", 0) if isinstance(r.get("engagement_rate"), dict) else 0
            vel_norms[rid] = percentile_rank(v, vels)
            eng_norms[rid] = percentile_rank(e, engs)

    results = []
    for r in reels:
        rid = r["reel_id"]
        meta = build_full_metadata(r, vel_norms.get(rid, 0.5), eng_norms.get(rid, 0.5), weights)
        results.append(meta)
        log.info(f"  {rid}: virality={meta['virality']['score']} tier={meta['virality']['tier']}")

    with open(args.output, "w") as f:
        json.dump(results, f, indent=2)
    log.info(f"Metrics written to {args.output} ({len(results)} reels)")


if __name__ == "__main__":
    main()
