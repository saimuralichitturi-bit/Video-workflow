# MEMORY.md — Instagram Reel Scraper Pipeline

---

## Project Overview

Automated pipeline that scrapes reels from target Instagram accounts, downloads top performing videos, stores them in Google Drive with full metadata JSON tags, updates metrics every 6 hours, and selects 1 best reference video per niche based on computed scores.

---

## Repository Structure

```
instagram-reel-scraper/
│
├── .github/
│   └── workflows/
│       ├── daily_download.yml       ← runs 6AM IST daily, full pipeline
│       └── refresh_metrics.yml      ← runs every 6 hours, metrics only
│
├── config/
│   ├── accounts.json                ← target Instagram accounts list
│   └── scoring_weights.json         ← virality score formula weights
│
├── scripts/
│   ├── scraper.py                   ← fetch reel list + raw metrics
│   ├── downloader.py                ← download video + thumbnail
│   ├── metrics.py                   ← compute all scores
│   ├── drive_handler.py             ← upload/download/update Drive files
│   ├── selector.py                  ← pick best reference video
│   └── groq_context.py              ← convert why_clone_this via Groq API
│
├── requirements.txt
└── MEMORY.md                        ← this file
```

---

## GitHub Secrets Required

```
INSTAGRAM_SESSION_ID     ← instagrapi session cookie (not password)
GDRIVE_SERVICE_KEY       ← Google Drive service account JSON key (base64 encoded)
GROQ_API_KEY             ← Groq API key for Llama 3.3 70B
```

---

## Config Files

### config/accounts.json

```json
{
  "accounts": [
    {
      "username":          "zerodha",
      "niche":             "finance",
      "reels_to_scrape":   10,
      "top_n_download":    5
    },
    {
      "username":          "nikhilkamath",
      "niche":             "finance",
      "reels_to_scrape":   10,
      "top_n_download":    5
    },
    {
      "username":          "warikoo",
      "niche":             "motivation",
      "reels_to_scrape":   10,
      "top_n_download":    5
    }
  ]
}
```

### config/scoring_weights.json

```json
{
  "view_velocity":      0.35,
  "engagement_rate":    0.25,
  "retention_proxy":    0.30,
  "recency_boost":      0.10,

  "retention_signals": {
    "comment_signal":   0.35,
    "like_signal":      0.25,
    "share_signal":     0.30,
    "save_signal":      0.10
  },

  "selection_thresholds": {
    "min_virality_score":   0.75,
    "min_retention_grade":  "B",
    "min_view_count":       500000,
    "min_share_to_view":    0.005
  }
}
```

---

## Google Drive Folder Structure

```
AI_Reel_Generator/
│
├── reels_library/
│   └── {niche}/
│       └── {account}/
│           ├── {account}_{reel_id}.mp4
│           ├── {account}_{reel_id}.json
│           └── {account}_{reel_id}_thumb.jpg
│
├── top_reference/
│   ├── current_best.mp4             ← symlink/copy of best reel
│   ├── current_best.json            ← metadata of best reel
│   └── selection_log.json           ← history of selections
│
└── state/
    └── last_run_state.json          ← tracks last top5 per account
```

### File Naming Convention

```
{account}_{reel_id}.mp4
{account}_{reel_id}.json
{account}_{reel_id}_thumb.jpg

Example:
zerodha_ABC123.mp4
zerodha_ABC123.json
zerodha_ABC123_thumb.jpg
```

---

## Metadata JSON Tag Structure

Every reel gets a `.json` sidecar file with the same filename as the `.mp4`.

```json
{
  "identity": {
    "reel_id":              "ABC123",
    "account":              "zerodha",
    "niche":                "finance",
    "url":                  "instagram.com/reel/ABC123",
    "posted_at":            "2025-03-17T10:30:00Z",
    "downloaded_at":        "2025-03-19T06:00:00Z",
    "last_updated_at":      "2025-03-19T12:00:00Z",
    "duration_sec":         45,
    "aspect_ratio":         "9:16",
    "language":             "en"
  },

  "raw_metrics": {
    "view_count":           1250000,
    "like_count":           45000,
    "comment_count":        1200,
    "share_count":          8500,
    "save_count":           3200,
    "scraped_at":           "2025-03-19T12:00:00Z"
  },

  "computed_metrics": {
    "hours_since_posted":       48,
    "view_velocity":            26041,
    "view_velocity_label":      "viral",
    "view_velocity_meaning":    "views per hour since posted",
    "engagement_rate_pct":      4.38,
    "engagement_label":         "high",
    "engagement_meaning":       "((likes+comments+shares)/views)x100",
    "like_to_view_pct":         3.60,
    "comment_to_view_pct":      0.096,
    "share_to_view_pct":        0.68,
    "save_to_view_pct":         0.25,
    "share_save_ratio":         2.65,
    "share_save_meaning":       "shares/saves — high means viral content"
  },

  "retention_proxy": {
    "score":                0.74,
    "grade":                "A",
    "grade_scale": {
      "A": "0.70-1.00 — people watched most of it",
      "B": "0.50-0.69 — decent watch time",
      "C": "0.30-0.49 — high drop-off",
      "D": "0.00-0.29 — people swiped away fast"
    },
    "signals": {
      "comment_signal": {
        "value":    0.076,
        "score":    0.76,
        "weight":   0.35,
        "meaning":  "comments/views — high means watched enough to react"
      },
      "like_signal": {
        "value":    0.036,
        "score":    0.72,
        "weight":   0.25,
        "meaning":  "likes/views — high means hook worked + watched enough"
      },
      "share_signal": {
        "value":    0.0068,
        "score":    0.91,
        "weight":   0.30,
        "meaning":  "shares/views — highest intent signal, watched fully"
      },
      "save_signal": {
        "value":    0.0025,
        "score":    0.68,
        "weight":   0.10,
        "meaning":  "saves/views — saved means will watch again"
      }
    },
    "formula": "(comment x 0.35) + (like x 0.25) + (share x 0.30) + (save x 0.10)"
  },

  "virality": {
    "score":                0.81,
    "tier":                 "A",
    "tier_scale": {
      "S": "0.90-1.00 — clone immediately",
      "A": "0.75-0.89 — strong reference",
      "B": "0.55-0.74 — decent reference",
      "C": "0.00-0.54 — skip this video"
    },
    "ready_for_cloning":    true,
    "clone_priority":       "high",
    "score_breakdown": {
      "view_velocity_contribution":     0.284,
      "engagement_contribution":        0.201,
      "retention_proxy_contribution":   0.245,
      "recency_contribution":           0.080
    },
    "formula": "(velocity x 0.35) + (engagement x 0.25) + (retention x 0.30) + (recency x 0.10)"
  },

  "content": {
    "caption_full":         "full original caption text here",
    "caption_keywords":     ["investing", "mutual funds", "SIP", "wealth", "beginner"],
    "hashtags_all":         ["#finance", "#investing", "#zerodha", "#SIP", "#wealth"],
    "hashtags_top5":        ["#finance", "#investing", "#SIP", "#wealth", "#beginner"],
    "audio_title":          "original audio - zerodha",
    "audio_is_original":    true,
    "has_text_overlay":     true,
    "has_captions":         true,
    "has_cta":              true,
    "cta_text":             "follow for more",
    "topic_summary":        "beginner guide to SIP investing",
    "content_type":         "educational",
    "tone":                 "conversational"
  },

  "decision_summary": {
    "virality_score":       0.81,
    "tier":                 "A",
    "retention_grade":      "A",
    "engagement_rate_pct":  4.38,
    "total_views":          1250000,
    "total_likes":          45000,
    "total_shares":         8500,
    "total_comments":       1200,
    "total_saves":          3200,
    "view_velocity":        26041,
    "hours_since_posted":   48,
    "top_hashtags":         ["#finance", "#investing", "#SIP"],
    "hook_type":            "question",
    "pacing":               "fast",
    "bpm":                  128,
    "mood":                 "energetic",
    "ready_for_cloning":    true,
    "clone_priority":       "high",
    "why_clone_this": [
      "share rate 3x above average",
      "retention grade A",
      "fast pacing matches viral trend",
      "question hook highest CTR type",
      "128 BPM matches top trending audio"
    ],
    "clone_strategy":       ""
  },

  "drive": {
    "video_filename":       "zerodha_ABC123.mp4",
    "json_filename":        "zerodha_ABC123.json",
    "thumb_filename":       "zerodha_ABC123_thumb.jpg",
    "folder_path":          "AI_Reel_Generator/reels_library/finance/zerodha/",
    "video_file_id":        "",
    "json_file_id":         "",
    "thumb_file_id":        "",
    "file_size_mb":         0
  }
}
```

---

## Metrics Computation Formulas

### View Velocity
```
view_velocity = view_count / hours_since_posted

Labels:
  > 50000   → explosive
  > 10000   → viral
  > 1000    → trending
  <= 1000   → normal
```

### Engagement Rate
```
engagement_rate_pct = ((likes + comments + shares) / views) x 100

Labels:
  > 8%    → viral
  > 3%    → high
  > 1%    → average
  <= 1%   → low
```

### Retention Proxy Score
```
comment_signal = comment_count / view_count
like_signal    = like_count    / view_count
share_signal   = share_count   / view_count
save_signal    = save_count    / view_count

Each signal normalized to 0-1 scale using percentile rank
across all scraped reels in the same niche.

retention_score = (comment_signal x 0.35)
                + (like_signal    x 0.25)
                + (share_signal   x 0.30)
                + (save_signal    x 0.10)

Grades:
  A: score >= 0.70
  B: score >= 0.50
  C: score >= 0.30
  D: score <  0.30
```

### Virality Score (Final)
```
recency_boost = max(0, 1 - (hours_since_posted / 168))
(168 hours = 7 days, boost decays linearly to 0)

virality_score = (view_velocity_normalized x 0.35)
               + (engagement_rate_normalized x 0.25)
               + (retention_score x 0.30)
               + (recency_boost x 0.10)

Tiers:
  S: score >= 0.90
  A: score >= 0.75
  B: score >= 0.55
  C: score <  0.55
```

---

## Reference Video Selection Logic

```
STEP 1: Filter candidates
  Must have ALL 3:
    virality.score       >= 0.75
    retention_proxy.grade = A or B
    raw_metrics.view_count >= 500000

STEP 2: Rank by virality_score descending

STEP 3: Pick rank 1 as current_best

STEP 4: Copy to top_reference/ folder in Drive
  top_reference/current_best.mp4
  top_reference/current_best.json

STEP 5: Append to selection_log.json
  {
    "selected_at":     "2025-03-19T06:00:00Z",
    "reel_id":         "ABC123",
    "account":         "zerodha",
    "virality_score":  0.81,
    "tier":            "A",
    "reason":          "highest virality score meeting all thresholds"
  }
```

---

## Groq API Usage

### Where It Is Used

Only one place in the entire pipeline:

```
decision_summary.why_clone_this[]
        ↓
Sent to Groq API → Llama 3.3 70B
        ↓
Returns: clone_strategy (natural language)
        ↓
Written back to decision_summary.clone_strategy
in the JSON file on Drive
```

### Model Details
```
Provider:  Groq
Model:     llama-3.3-70b-versatile
Endpoint:  api.groq.com/openai/v1/chat/completions
Temp:      0.7
MaxTokens: 500
Free tier: 14,400 requests/day
           6,000 tokens/min
```

### Prompt Structure
```
System:
  You are a viral video strategist.
  Convert these performance signals into
  a clear clone strategy in 2-3 sentences.
  Output plain text only.

User:
  Why this reel works:
  - share rate 3x above average
  - retention grade A
  - fast pacing matches viral trend
  - question hook highest CTR type
  - 128 BPM matches top trending audio
```

---

## GitHub Actions Workflows

### workflow 1: daily_download.yml

```
Trigger:   cron 0 0 30 * * (6AM IST = 00:30 UTC)
           also: workflow_dispatch (manual)

Steps:
  1. Checkout repo
  2. Setup Python 3.10
  3. Install requirements.txt
  4. Decode GDRIVE_SERVICE_KEY secret → service_account.json
  5. Run scripts/scraper.py
       → reads config/accounts.json
       → for each account:
           fetch latest N reels via instagrapi
           compute raw metrics
           compute virality scores
           pick top_n by virality_score
  6. Run scripts/downloader.py
       → for each top reel:
           check if already in Drive (by reel_id)
           if not → download .mp4 + thumb
           upload to Drive
  7. Run scripts/metrics.py
       → compute all scores
       → build full metadata JSON
  8. Run scripts/groq_context.py
       → send why_clone_this to Groq
       → get clone_strategy back
       → write into JSON
  9. Run scripts/drive_handler.py
       → upload .json sidecar files
  10. Run scripts/selector.py
       → pick 1 best reference video
       → copy to top_reference/ in Drive
       → update selection_log.json
  11. Cleanup /tmp/ runner files
```

### workflow 2: refresh_metrics.yml

```
Trigger:   cron 0 */6 * * * (every 6 hours)

Steps:
  1. Checkout repo
  2. Setup Python 3.10
  3. Install requirements.txt
  4. Decode GDRIVE_SERVICE_KEY → service_account.json
  5. Run scripts/drive_handler.py
       → list all .json files from Drive
       → download each .json
  6. Run scripts/scraper.py (metrics only mode)
       → for each reel_id in JSONs:
           re-scrape: view_count, like_count,
                      comment_count, share_count
  7. Run scripts/metrics.py (recompute only)
       → recompute: computed_metrics
       → recompute: retention_proxy
       → recompute: virality score + tier
       → update: last_updated_at timestamp
  8. Run scripts/drive_handler.py
       → re-upload updated .json files
       → overwrite existing (same file_id)
  9. Run scripts/selector.py
       → re-evaluate: is current_best still best?
       → if new winner → update top_reference/
```

---

## What Updates Every 6 Hours vs What Stays Fixed

### Updates Every 6 Hours (refresh_metrics.yml)
```
raw_metrics.view_count
raw_metrics.like_count
raw_metrics.comment_count
raw_metrics.share_count
raw_metrics.save_count
raw_metrics.scraped_at
computed_metrics        (fully recalculated)
retention_proxy         (fully recalculated)
virality                (fully recalculated)
decision_summary        (fully recalculated)
identity.last_updated_at
```

### Never Changes After Download (daily_download.yml only)
```
identity.reel_id
identity.account
identity.niche
identity.url
identity.posted_at
identity.downloaded_at
identity.duration_sec
identity.aspect_ratio
content.caption_full
content.hashtags_all
content.audio_title
drive.video_file_id
drive.video_filename
drive.file_size_mb
```

---

## Python Dependencies (requirements.txt)

```
instagrapi==2.1.2        ← Instagram private API wrapper
yt-dlp                   ← video downloader
google-api-python-client ← Google Drive API
google-auth-httplib2     ← Drive auth
google-auth-oauthlib     ← Drive auth
groq                     ← Groq API client
requests                 ← HTTP calls
python-dateutil          ← date parsing
```

---

## Key Design Decisions

### Why instagrapi (not Apify)
```
Apify  → paid after free tier, 3-day file expiry
instagrapi → free, session_id login (no password risk),
             gets all metrics we need
Risk: private API, may break on Instagram updates
Mitigation: pin version in requirements.txt
```

### Why session_id (not username/password)
```
Safer: session_id expires, does not expose password
How to get: login to Instagram in browser
            → DevTools → Application → Cookies
            → copy sessionid value
```

### Why sidecar JSON (not database)
```
Simple: one file per video, self-contained
Portable: Drive is the single source of truth
No infra: no Supabase, no extra costs
Readable: open JSON in any editor to check state
```

### Why Groq only for why_clone_this
```
Only this field needs NLP conversion
(raw signal list → readable strategy text)
All other computations are pure math
Zero GPU usage on Kaggle for this step
Free tier is more than enough
```

---

## Error Handling Strategy

```
scraper.py fails for one account
  → log error, skip that account
  → continue with remaining accounts
  → do not fail entire workflow

downloader.py fails for one reel
  → log error, mark in JSON as download_failed: true
  → continue with remaining reels
  → retry on next daily run

Drive upload fails
  → retry 3 times with 5 second backoff
  → if still fails → log and skip
  → JSON on Drive may be stale until next run

instagrapi challenge/2FA triggered
  → workflow fails with clear error message
  → manual intervention needed
  → refresh session_id in GitHub Secrets
```

---

## State Tracking

### state/last_run_state.json

```json
{
  "last_daily_run":       "2025-03-19T00:30:00Z",
  "last_metrics_refresh": "2025-03-19T12:00:00Z",
  "current_best": {
    "reel_id":            "ABC123",
    "account":            "zerodha",
    "niche":              "finance",
    "virality_score":     0.81,
    "tier":               "A",
    "selected_at":        "2025-03-19T06:00:00Z"
  },
  "accounts_status": {
    "zerodha":       "ok",
    "nikhilkamath":  "ok",
    "warikoo":       "challenge_required"
  },
  "total_reels_in_library": 47
}
```

---

## Downstream Usage

### How AI Reel Generator Uses the Output

```
Reads: top_reference/current_best.json
  → decision_summary.clone_strategy   (from Groq)
  → decision_summary.why_clone_this   (raw signals)
  → decision_summary.top_hashtags     (content context)
  → decision_summary.hook_type        (script structure)
  → decision_summary.pacing           (video pacing)
  → decision_summary.bpm              (music tempo)
  → decision_summary.mood             (audio energy)
  → content.topic_summary             (niche context)

Reads: top_reference/current_best.mp4
  → run PySceneDetect for scene list
  → extract keyframes per scene
  → feed into FLUX + SkyReels frame gen

All other pipeline stages run from Kaggle notebooks
using the Drive files as input.
```

---

## Quick Reference — Score Thresholds

```
WORTH CLONING (all 3 must be true):
  virality_score     >= 0.75   (tier A or S)
  retention_grade    =  A or B
  view_count         >= 500,000

VIRAL SIGNALS (bonus):
  share_to_view_pct  >  0.5%
  comment_to_view    >  0.05%
  view_velocity      >  10,000 views/hour

SKIP THIS VIDEO:
  virality_score     <  0.55   (tier C)
  retention_grade    =  C or D
  view_count         <  500,000
```