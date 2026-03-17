MEMORY.md — FinanceReel AI
Feed this to Claude Code at the start of every session.
WHO I AM
I am building an automated AI pipeline that:
1. Scrapes finance news (Google Trends + SEC filings + NSE/BSE)
2. Generates cinematic video prompts using Claude AI
3. Creates video clips using WAN 2.1 via ComfyUI (currently on Google Colab)
4. Merges clips into a 1-minute Instagram Reel with FFmpeg
5. Scores the video using Gemini Vision AI
6. Judges the score using Claude Opus
7. Sends to Telegram bot for human approval
8. Uploads to Instagram if approved, or regenerates if rejected
CURRENT INFRA: GOOGLE COLAB
* Running on Google Colab Pro (A100 GPU, ~40GB VRAM)
* ComfyUI installed in /content/drive/MyDrive/ComfyUI
* Models stored in Google Drive to avoid re-downloading
* Python pipeline calls ComfyUI via HTTP API on 127.0.0.1:8188
* WAN 2.1 model: wan2.1_t2v_1.3B_fp16.safetensors (fits in Colab A100)
* Output clips saved to /content/drive/MyDrive/finreel/output/
* Colab kept alive with Cloudflare tunnel for ComfyUI UI access
* Pipeline triggered manually or via Colab cell scheduler
FUTURE INFRA: MAC M5 (migrate later)
* Mac M5, 24GB unified memory, 512GB storage
* ComfyUI will run locally with MPS backend
* Use PYTORCH_ENABLE_MPS_FALLBACK=1 flag
* Use fp16 models only (fp8 not supported on MPS)
* WAN 2.2 has MPS bug — stick with WAN 2.1
* Schedule via launchd at 6AM + 6PM IST daily
PROJECT FOLDER STRUCTURE
finreel-ai/ ├── MEMORY.md                  ← this file ├── ARCHITECTURE.md            ← full system design ├── main.py                    ← entry point + orchestrator ├── .env                       ← all API keys ├── requirements.txt │ ├── pipeline/ │   ├── __init__.py │   ├── data_scraper.py        ← Google Trends + SEC + yfinance │   ├── prompt_gen.py          ← Claude → 12 cinematic prompts │   ├── comfyui_client.py      ← HTTP + WebSocket API to ComfyUI │   ├── video_merge.py         ← FFmpeg smart cinematic merger │   ├── gemini_scorer.py       ← Gemini Vision video scorer │   ├── claude_judge.py        ← Claude Opus final approval judge │   ├── telegram_gate.py       ← Telegram bot human review gate │   ├── cdn_upload.py          ← Cloudinary temp public URL │   └── instagram.py           ← Meta Graph API publisher │ ├── comfyui_workflows/ │   └── wan21_t2v.json         ← WAN 2.1 workflow exported from ComfyUI │ ├── assets/ │   ├── finance_bgm_01.mp3     ← royalty-free background music │   └── finance_bgm_02.mp3 │ └── output/                    ← auto-created at runtime     ├── clips/                 ← raw WAN 2.1 output clips     ├── normalized/            ← after resize + color grade     ├── captioned/             ← after captions added     └── final/                 ← final 60s reels
API KEYS NEEDED (in .env)
ANTHROPIC_API_KEY=           # Claude (prompt gen + judge) GEMINI_API_KEY=              # Gemini Vision (video scorer) TELEGRAM_BOT_TOKEN=          # Telegram bot TELEGRAM_CHAT_ID=            # your personal Telegram chat ID INSTAGRAM_ACCESS_TOKEN=      # Meta Graph API long-lived token INSTAGRAM_USER_ID=           # Instagram professional account ID CLOUDINARY_URL=              # cloudinary://key:secret@cloud_name COMFYUI_URL=http://127.0.0.1:8188
MODELS USED
Model Purpose Provider claude-opus-4-5 Prompt generation + Final judge Anthropic gemini-2.0-flash-exp Video frame analysis + scoring Google wan2.1_t2v_1.3B_fp16 Text-to-video clip generation ComfyUI local
VIDEO SPECS (Instagram Reel)
* Format: MP4, H264, AAC
* Resolution: 1080×1920 (9:16)
* FPS: 24
* Duration: exactly 60 seconds
* Audio: AAC 48kHz stereo, 30% volume background music
* moov atom must be at front of file (faststart flag in FFmpeg)
CONTENT STRATEGY
* Topics: Indian stock market (NSE/BSE), global finance news, company filings, Google Trends finance keywords
* Tone: Cinematic, professional, information-dense, Instagram-native
* Post schedule: 6:00 AM IST + 6:00 PM IST daily
* Each video: 12 clips × 5 seconds = 60 seconds total
NARRATIVE STRUCTURE (12 clips, 5s each)
Clip 01      → HOOK     : Dramatic opener, grab in first 3 seconds Clip 02-03   → CONTEXT  : Set the scene, what's happening in markets Clip 04-08   → DATA     : Main information, key stats, company news Clip 09-10   → CLIMAX   : Big insight, turning point, key takeaway Clip 11-12   → CTA      : Follow for more, end card, branding
SCORING THRESHOLDS
* Gemini scores 5 metrics out of 10: visual_quality, hook_strength, narrative_flow, information_value, audience_appeal
* PASS condition: average ≥ 7.5 AND no single metric < 6.0
* If FAIL → Gemini returns improvement_tips → pipeline regenerates
* Max retries: 3 (after 3 fails, send to Telegram anyway with failure flag)
* Claude Opus reviews scorecard and gives APPROVE / REJECT + reasoning
* If Claude rejects → regeneration_brief sent back to prompt_gen.py
TELEGRAM APPROVAL FLOW
1. Bot sends video + scorecard + Claude verdict to your Telegram
2. Two inline buttons: ✅ YES — Upload / ❌ NO — Reject
3. If YES → immediately upload to Instagram
4. If NO → bot asks "What's wrong?" → your text reply parsed by Claude → extracted as fix brief → full pipeline reruns
5. Timeout: 30 minutes (if no reply, skip this run and log it)
COMFYUI API PATTERN (how we call it)
# 1. POST /prompt with workflow JSON + injected text prompt # 2. Connect WebSocket ws://127.0.0.1:8188/ws?clientId={uuid} # 3. Listen for {"type": "executing", "data": {"node": null}} → means done # 4. GET /history/{prompt_id} → get output filename # 5. Move file from ComfyUI/output/ to our output/clips/
FFMPEG MERGE PIPELINE (5 stages)
Stage 1: Normalize   → scale=1080:1920, fps=24, H264 Stage 2: Color Grade → eq=contrast=1.15:saturation=1.2 + teal-orange curves Stage 3: Captions    → drawtext overlay per segment type (hook/context/data/climax/cta) Stage 4: xfade Merge → chained xfade filter (crossfade/zoomin/wiperight per segment) Stage 5: Audio       → add bgm.mp3 at volume=0.3, afade in/out, -shortest flag
KEY CONSTRAINTS TO REMEMBER
* Colab session dies after inactivity — use Cloudflare tunnel keepalive
* WAN 2.1 1.3B on A100: ~3-5 min per 5s clip → 12 clips = ~40-60 min total
* Instagram requires publicly accessible video URL → use Cloudinary free tier
* Instagram Graph API: must poll container status until "FINISHED" before publishing
* Long-lived Instagram token expires in 60 days → refresh it monthly
* Telegram bot must use polling (not webhook) on Colab since no public IP
WHAT'S NOT BUILT YET (TODO)
* [ ] comfyui_client.py — WebSocket polling implementation
* [ ] gemini_scorer.py — Gemini File API upload + scoring
* [ ] claude_judge.py — Opus judge with JSON output
* [ ] telegram_gate.py — Bot with inline buttons + reason collection
* [ ] cdn_upload.py — Cloudinary upload helper
* [ ] instagram.py — Graph API 3-step publish flow
* [ ] main.py — Full orchestrator with retry loop
* [ ] Colab notebook — All-in-one setup + run cell
