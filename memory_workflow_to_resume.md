# FinanceReel AI — Session Memory
**Repo:** saimuralichitturi-bit/Video-workflow  
**Runtime:** Google Colab T4 (15.6GB VRAM)  
**Last updated:** 2026-03-29

---

## Pipeline Status

| Stage | Description | Status | Output |
|-------|-------------|--------|--------|
| Stage 1 | yt-dlp video download | ✅ Done | `reference_video.mp4` |
| Stage 2 | Video analyzer | ✅ Done | `style_dna/video_dna.json` |
| Stage 3 | Audio analyzer | ✅ Done | `style_dna/audio_dna.json` |
| Stage 4 | Script generator | ✅ Done | `style_dna/script_expanded.json` |
| Stage 5 | Frame generator | ✅ Done | `style_dna/frames/` (32 frames, 360x640) |
| Stage 6A | Voice clone | 🔄 In progress | SparkTTS running |
| Stage 6B | Voice style clone | ⏳ Pending | — |
| Stage 6C | Music generator | ⏳ Pending | — |
| Stage 6D | SFX generator | ⏳ Pending | — |
| Stage 6E | Audio mix | ⏳ Pending | — |
| Stage 7 | Assembler | ⏳ Pending | `final_reel.mp4` |

---

## Key Files on Disk

```
/content/
├── script.json                          # base script (8 scenes)
├── script_expanded.json                 # expanded (32 sub-shots)
├── voice_reference_10s.wav              # trimmed reference audio
├── stage2_output (1).zip
├── stage3_output.zip
├── stage5_frames.zip
├── stage6a_voiceover.zip
├── Spark-TTS/                           # SparkTTS repo
│   ├── cli/
│   │   ├── SparkTTS.py                  # manually fetched
│   │   ├── inference.py                 # manually fetched
│   │   └── __init__.py
│   └── pretrained_models/Spark-TTS-0.5B/
└── style_dna/
    ├── video_dna.json
    ├── audio_dna.json
    ├── script.json
    ├── script_expanded.json
    ├── frames/                          # 32 x 360x640 PNG frames
    ├── frames_manifest.json
    ├── voiceover/                       # scene WAVs + full_voiceover.wav
    ├── vocals_stem.wav
    ├── drums_stem.wav
    ├── bass_stem.wav
    └── music_stem.wav
```

---

## Script Summary

**Topic:** Ather Energy fundamental analysis — is it a good buy?  
**Duration:** 60 seconds  
**Total sub-shots:** 32  
**Cuts per minute:** 34.3  
**Hook:** "Ather Energy's stock has crashed 34 percent from its peak, but is this a buying opportunity or a trap now"  
**CTA:** "Invest in Ather Energy at your own risk, with a long-term perspective and thorough research"

### Scene voiceover lines (18-23 words each)
| Scene | Mood | Voiceover |
|-------|------|-----------|
| 00 | Hook | Ather Energy's stock has crashed 34 percent from its peak, but is this a buying opportunity or a trap now |
| 01 | Cautious | Ather Energy's stock has crashed 34 percent from its peak, but is this a buying opportunity or a trap now |
| 02 | Excited | Ather Energy is India's leading premium electric vehicle scooter manufacturer with its flagship 450X model selling well now |
| 03 | Optimistic | Revenue is growing at 42 percent year over year, with sales of 1753 crore rupees and expanding to new cities rapidly |
| 04 | Concerned | However, the company is still burning cash with a net loss of 1059 crore rupees and negative EBITDA margin |
| 05 | Competitive | Competition is heating up with Ola Electric's price cuts, TVS iQube, and Bajaj Chetak gaining traction in the market |
| 06 | Bullish | The bull case is strong with Hero MotoCorp's 37 percent stake, and India's low EV penetration offering a huge runway |
| 07 | Bearish | However, the bear case is valid with no clear profitability timeline, and dependence on China for battery supplies |
| 08 | Cautious | In conclusion, Ather Energy is a high risk high reward stock, suitable only for patient investors with 3-5 year horizon |
| 99 | CTA | Invest in Ather Energy at your own risk, with a long-term perspective and thorough research, only if you can afford to lose |

---

## Audio DNA Summary

| Metric | Value |
|--------|-------|
| BPM | 117.45 |
| Mood | speech_heavy |
| Genre | pop_upbeat |
| Energy | high |
| Beat count | 177 |
| Cut points | 89 |
| Speaking rate | fast |
| Pitch mean | 240.19 Hz |
| Drum density | 3.01 hits/sec |
| Bass presence | light |

---

## Video DNA Summary

| Metric | Value |
|--------|-------|
| Total scenes | 57 |
| Duration | 91.6s |
| FPS | 30 |
| Pacing | very_fast (37.3 cuts/min) |
| Avg brightness | 0.49 |
| Global palette | #5c93d1 #755b53 #d2cfd3 #2a262d #ddc033 #a6948e |

---

## Stage 6A — Voice Clone

**Model:** SparkAudio/Spark-TTS-0.5B  
**Repo cloned to:** `/content/Spark-TTS`  
**cli/ source:** manually fetched from GitHub raw  
**Reference audio:** `voice_stems/htdemucs/your_voice_raw/vocals.wav` (91s clean demucs vocal)  
**Reference transcript:** "India markets roar back with nifty jumping 374 points in just one day. Yesterday's losers are crying while investors are celebrating. Here's what smart money is doing right now."

**Voice cloners tried (all failed on Colab Python 3.12):**
- fish-speech — CLI broken, no module
- Coqui XTTS-v2 — Python 3.12 not supported
- Kokoro — no voice cloning, preset only
- CSM-1B (sesame) — gated, wrong input format
- Chatterbox — torchaudio/pkg_resources broken
- Parler-TTS — text description only, no real clone
- F5-TTS — protobuf conflicts

**SparkTTS import fix (use this after session restart):**
```python
import importlib.util, sys

spec   = importlib.util.spec_from_file_location(
    "SparkTTS", "/content/Spark-TTS/cli/SparkTTS.py"
)
module = importlib.util.module_from_spec(spec)
sys.modules["SparkTTS"] = module
spec.loader.exec_module(module)
SparkTTS = module.SparkTTS
```

---

## Session Restore Script

Run this after every kernel restart:

```python
import json, os, shutil, sys, importlib.util

# Copy scripts to style_dna if needed
for f in ["script.json", "script_expanded.json"]:
    if os.path.exists(f"/content/{f}") and not os.path.exists(f"/content/style_dna/{f}"):
        shutil.copy(f"/content/{f}", f"/content/style_dna/{f}")

# Load DNA files
with open("/content/style_dna/video_dna.json") as f:
    video_dna = json.load(f)
with open("/content/style_dna/audio_dna.json") as f:
    audio_dna = json.load(f)
with open("/content/style_dna/script_expanded.json") as f:
    script = json.load(f)

# Restore shots list
palette    = video_dna["global_palette"]
brightness = video_dna["avg_brightness"]
STYLE_SUFFIX = (
    f"cinematic photography, photorealistic, sharp focus, "
    f"Instagram reel vertical frame 9:16, "
    f"color palette: {' '.join(palette[:3])}, "
    f"professional lighting, "
    f"{'bright high-key' if brightness > 0.5 else 'moody cinematic'} lighting, "
    f"4K quality, no text overlays"
)

shots = []
for scene in script["scenes"]:
    for ss in scene.get("sub_shots", []):
        shots.append({
            "scene_id"  : scene["scene_id"],
            "sub_id"    : ss["sub_id"],
            "duration"  : ss["duration_sec"],
            "prompt"    : f"{ss['visual_prompt'].rstrip('.')}. Mood: {scene['mood']}. {STYLE_SUFFIX}",
            "voiceover" : scene["voiceover"],
            "caption"   : scene["caption"],
            "filename"  : f"scene_{scene['scene_id']:02d}_shot_{ss['sub_id']:02d}.png",
            "filepath"  : f"style_dna/frames/scene_{scene['scene_id']:02d}_shot_{ss['sub_id']:02d}.png",
        })

# Restore voiceover lines
lines, seen = [], set()
lines.append({"scene_id": 0,  "text": script["hook"], "output_path": "style_dna/voiceover/scene_00_hook.wav"})
for scene in script["scenes"]:
    sid = scene["scene_id"]
    if sid in seen: continue
    seen.add(sid)
    lines.append({"scene_id": sid, "text": scene["voiceover"], "output_path": f"style_dna/voiceover/scene_{sid:02d}.wav"})
lines.append({"scene_id": 99, "text": script["cta"], "output_path": "style_dna/voiceover/scene_99_cta.wav"})

REF_TEXT = "India markets roar back with nifty jumping 374 points in just one day. Yesterday's losers are crying while investors are celebrating. Here's what smart money is doing right now."
REF_AUDIO = "voice_stems/htdemucs/your_voice_raw/vocals.wav"

print(f"Restored: {len(shots)} shots, {len(lines)} vo lines")
print(f"Frames on disk: {sum(1 for s in shots if os.path.exists(s['filepath']))}")
print(f"Voiceover: {'EXISTS' if os.path.exists('style_dna/voiceover/full_voiceover.wav') else 'MISSING'}")
```

---

## Next Steps

1. ✅ Complete Stage 6A — SparkTTS voice generation (10 lines)
2. ⏳ Stage 7 — Assembler (MoviePy stitch frames + voiceover + music)
   - Hard cuts every 1.5-2s matching cut_timestamps from audio_dna
   - Caption burn-in per scene
   - Background music from music_stem.wav
   - Output: `final_reel.mp4` (360x640, 60s, 24fps)
