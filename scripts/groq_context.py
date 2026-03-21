"""
groq_context.py
Send why_clone_this signals to Groq (Llama 3.3 70B) and get clone_strategy back.
Updates clone_strategy in all metadata JSONs.

Input:  /tmp/metrics_output.json  (from metrics.py)
Output: /tmp/groq_output.json     (same list with clone_strategy filled in)
"""

import json
import os
import time
import logging
import argparse

from groq import Groq

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a viral video strategist. "
    "Convert these performance signals into a clear clone strategy in 2-3 sentences. "
    "Output plain text only. No bullet points, no markdown."
)


def build_user_prompt(signals: list[str]) -> str:
    lines = "\n".join(f"- {s}" for s in signals)
    return f"Why this reel works:\n{lines}"


def generate_clone_strategy(client: Groq, signals: list[str]) -> str:
    if not signals:
        return ""
    try:
        chat = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": build_user_prompt(signals)}
            ],
            temperature=0.7,
            max_tokens=500
        )
        return chat.choices[0].message.content.strip()
    except Exception as e:
        log.error(f"  Groq API error: {e}")
        return ""


def build_why_clone_signals(meta: dict) -> list[str]:
    """Auto-generate why_clone_this signals from computed metrics if empty."""
    existing = meta.get("decision_summary", {}).get("why_clone_this", [])
    if existing:
        return existing

    signals = []
    vm = meta.get("computed_metrics", {})
    vir = meta.get("virality", {})
    ret = meta.get("retention_proxy", {})

    if vm.get("share_to_view_pct", 0) > 0.5:
        signals.append(f"share rate {vm['share_to_view_pct']:.2f}% — 3x above average")
    if ret.get("grade") in ("A", "B"):
        signals.append(f"retention grade {ret['grade']}")
    if vm.get("view_velocity_label") in ("viral", "explosive"):
        signals.append(f"view velocity {vm.get('view_velocity', 0):.0f}/hr — {vm['view_velocity_label']}")
    if vm.get("engagement_label") in ("high", "viral"):
        signals.append(f"engagement rate {vm.get('engagement_rate_pct', 0):.2f}% — {vm['engagement_label']}")
    if vir.get("tier") in ("S", "A"):
        signals.append(f"virality tier {vir['tier']} — score {vir['score']}")

    return signals or ["high virality score", "strong engagement signals"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--in",  dest="input",  default="/tmp/metrics_output.json")
    parser.add_argument("--out", dest="output", default="/tmp/groq_output.json")
    args = parser.parse_args()

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY env var not set")

    client = Groq(api_key=api_key)

    with open(args.input) as f:
        reels = json.load(f)

    for i, meta in enumerate(reels):
        if not meta.get("virality", {}).get("ready_for_cloning", False):
            continue  # only process reels worth cloning

        signals = build_why_clone_signals(meta)
        meta["decision_summary"]["why_clone_this"] = signals

        log.info(f"  [{i+1}/{len(reels)}] Generating clone_strategy for {meta['identity']['reel_id']}...")
        strategy = generate_clone_strategy(client, signals)
        meta["decision_summary"]["clone_strategy"] = strategy
        log.info(f"    → {strategy[:80]}...")

        # Rate limit: stay under 6000 tokens/min on free tier
        if i < len(reels) - 1:
            time.sleep(2)

    with open(args.output, "w") as f:
        json.dump(reels, f, indent=2)
    log.info(f"Groq output written to {args.output}")


if __name__ == "__main__":
    main()
