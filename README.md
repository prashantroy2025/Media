# Nova Autopilot v5.0 🚀

> **Local-First Autonomous AI Short-Video Studio & Auto-Publisher**  
> Tailored for **Prashant Roy** (`@NovaPrashantroy` / **PRASHANT ROY**) for generating high-energy **English Fact & Shock-News Shorts** targeting a **high-value English-speaking audience (US, UK, CA, AU)** for **YouTube Shorts** and **Instagram Reels**.

---

## 🌟 Overview: What's New in v4.0 & v5.0

**Nova Autopilot v5.0** eliminates the four core defects of previous iterations while adding safe top-creator pattern learning, sentence-level semantic visual matching, and millisecond-accurate forced alignment:

1. **Forced Alignment Subtitle Synchronization (`nova.alignment`)**:
   - Runs `faster-whisper` (`tiny`, CPU int8) directly on the **final trimmed master voice audio**.
   - Aligns Whisper timestamps to script tokens via `difflib.SequenceMatcher`, preserving script spelling, capitalization, and punctuation.
   - Sync Quality Gate enforces **Median Drift $\le 100$ ms** and **Max Drift $\le 250$ ms** (Measured in production: **0.0 ms**).
   - Word highlight frames synchronized within 80ms of vocalization.
2. **Provider Gating & Semantic Visual Relevance (`nova.visuals`, `nova.relevance`)**:
   - **NASA Gating**: NASA media provider is strictly locked to `space_science` niche with confirmed space entities, eliminating random cosmic clips on business/tech stories.
   - **Multi-Candidate Search**: Queries Pexels, Pixabay, Wikimedia Commons, and Openverse in parallel.
   - **`VisualRelevanceScorer`**: Calibrated threshold ($\ge 40.0/100$) evaluating subject match (40%), search query match (35%), action match (15%), and motion bonus (10%).
   - **Dynamic Kinetic Explainer Cards**: Procedural typography cards with tech grid and Ken Burns motion if no stock candidate passes relevance threshold.
   - Generates interactive `alignment_report.html` for visual verification.
3. **Advanced Coherent Scriptwriter (`nova.scriptwriter`)**:
   - **Single Source of Truth**: Unified ordered sentence contracts (`sentences[]`). Sentence 0 is the hook; pipeline speaks and captions each sentence once, eliminating duplicated openings.
   - **Duplicate Sentence Guard**: Rejects token Jaccard $\ge 0.80$ and identical opening 6 words.
   - **Fact Fidelity (`verify_fact_fidelity`)**: Asserts preservation of subject, action stems/synonyms, and causal outcome (solving the "apple fell and spoiled" loose paraphrasing problem).
   - **Adjacent-Pair Coherence Critic**: Scores logical progression between sentence pairs ($\ge 3.0/5.0$).
   - **Golden Evaluation Harness**: `python -m nova eval-scripts` validates 12 fixed topics (100% fact retention, 4.6/5.0 coherence).
4. **Safe Top-Creator Pattern Learning (`nova.patterns`)**:
   - **Reference Channel Tracker**: Cheap official YouTube Data API caller tracking top creators (`@TwoMinutePapers`, `@Fireship`, `@CompanyMan`, `@Veritasium`), calculating outlier scores ($O = \text{views} / \text{median\_views}$), and filtering Shorts ($\le 180$s).
   - **Pattern Library**: Structural templates enforcing the **mandatory $\le 4$-word consecutive overlap rule**.
   - **Study Notes Page (`/study-notes`)**: Review UI interface with strict regex copy-guard rejecting raw transcripts, timestamps (`00:15`), and caption tags (`[Music]`).
   - **"Same Topic, Different Angle"**: Generates 7 distinct angles with distinctiveness scoring and an 8-gram verbatim overlap originality guard.
5. **Interactive Review Studio Enhancements**:
   - Sentence-by-sentence beat map showing role badges, fact IDs, and assigned visual provider/relevance scores.
   - Forced alignment sync drift metrics card.
   - Inline "Fix Sentence" editor and "Regenerate Script Only" buttons.
   - Dedicated Study Notes page with copy-guard warnings.
6. **Premium-Audience Niche Mix**:
   - **50% AI & Technology** (`ai_tech`), **25% Business & Economics** (`business`), **25% Space & Science** (`space_science`).
   - Deficit-based scheduler with anti-streak guardrail (max 2 consecutive).
   - Dual-unit measurement engine (`60 miles (96.56 km)`).
   - Strict business compliance & mandatory regulatory disclaimer.

---

## 📋 System Requirements

| Component | Requirement |
|---|---|
| **Hardware** | Apple Silicon Mac (M1 / M2 / M3 / M4), 8 GB unified memory |
| **OS** | macOS 12+ (Tested on macOS Sequoia 15 / Apple M2) |
| **Python** | Python 3.11 or Python 3.12 (in `.venv`) |
| **FFmpeg** | `ffmpeg` & `ffprobe` installed via Homebrew with `h264_videotoolbox` |
| **Local LLM** | [Ollama](https://ollama.ai) with `llama3.2:3b` (or `qwen2.5:3b`) |

---

## ⚡ Quick Start in 3 Steps

### Step 1: System Health Check (Doctor)
Verify your local environment, FFmpeg hardware acceleration, keyless media APIs, and sound assets:
```bash
cd nova-autopilot
.venv/bin/python -m nova doctor
```

### Step 2: Check Niche Mix Distribution
Inspect your rolling 14-day and 30-day content distribution:
```bash
.venv/bin/python -m nova niches
```

### Step 3: Run Full Pipeline Dry-Run (Batch of 3 Videos)
Generate 3 distinct, fully produced English shorts across target niches with mock publishing:
```bash
.venv/bin/python -m nova dry-run --count 3
```
Your rendered videos, thumbnails, contact sheets, and schedule slots will be in `output/` and registered in `data/nova.db`!

---

## 🛠️ Complete CLI Command Reference

All operations are run through the `nova` CLI:

```bash
# Run batch of N videos with automatic deficit niche balancing
python -m nova run --count 3

# Force a specific niche for the batch
python -m nova run --count 1 --niche business
python -m nova run --count 1 --niche space_science
python -m nova run --count 1 --niche ai_tech

# Dry-run batch of N videos (Mock publisher, no external posting)
python -m nova dry-run --count 3

# Inspect rolling 14-day and 30-day niche distribution vs target weights
python -m nova niches

# Reset learned weights back to config.yaml defaults
python -m nova niches --reset

# Process due videos in local publish queue (Instagram / launchd)
python -m nova process-queue

# Fetch fresh royalty-free mood music tracks into assets/music/
python -m nova fetch-music

# Regenerate a video with a fresh script or visual pass
python -m nova regenerate --video-id 25

# Run individual pipeline stages
python -m nova collect       # Collect fresh facts & corporate news
python -m nova rank          # Score topics for surprise & niche fit
python -m nova script        # Generate grounded script for top topic
python -m nova render        # Render MP4 with subtitles and audio
python -m nova publish --video-id 25  # Manually publish an approved video

# Evaluate scriptwriter fact grounding & coherence on golden topics
python -m nova eval-scripts

# Track reference channels for viral outliers via official YouTube API
python -m nova track-references

# Start Review Studio Web UI
python -m nova ui --port 8765

# Pull real views and likes stats from platforms & optimize weights
python -m nova analytics
```

---

## 🖥️ Review Queue Web UI, Study Notes & Alignment

Nova Autopilot defaults to `publish_mode: review`. Before any video is published, it awaits your review in the Studio UI:

```bash
python -m nova ui
```
Open **[http://127.0.0.1:8765](http://127.0.0.1:8765)**:

- **Target Publishing Slot Banner**: Displays scheduled prime-time slot in **🇺🇸 US Eastern** (`America/New_York`) and **🇮🇳 IST** (`Asia/Kolkata`).
- **Niche Filter Buttons**: Filter pending queue by **All**, **🤖 AI & Tech**, **📈 Business**, or **🚀 Space & Science**.
- **14-Day Niche Mix Status**: Live progress indicators comparing current share against target distribution (50% / 25% / 25%).
- **faster-whisper Subtitle Sync Card**: Displays median word drift, max drift, and sync pass/fail status.
- **Sentence Beat Map**: Sentence-by-sentence breakdown with roles (`hook`, `context`, `escalation`, `twist`, `payoff`), fact IDs, visual intent queries, and assigned provider/relevance score.
- **Inline Sentence Editor**: Quick inline form to edit/fix any single sentence without full regeneration.
- **Creator Study Notes (`/study-notes`)**: Analytical note-taking page with automated copy-guard (blocks transcripts, timestamps, and captions).
- **Quality Gate Audit Card**: Real-time pass/fail indicators for Duration (20s–40s), Pacing (150–200 WPM), Hook length (<=12 words), Fact grounding citations, Spatial variance flat frame detection, and **Business Financial Advice Compliance**.
- **Visual Contact Sheet Preview**: Visual grid of extracted frames across the video duration to inspect visual quality at a glance.
- **Source Facts & Citations**: Direct links and extracts of verified facts cited from SEC EDGAR, arXiv, BBC, CNBC, Wikipedia, or NASA.
- **Media Attribution Table**: Itemized list of all footage, photo, and music creators with license names.
- **One-Click Actions**: **Approve & Publish**, **Regenerate Script Only**, or **Reject**.

---

## ⏰ macOS Automation & Wake Scheduling

To automate background publishing while your Mac is in sleep mode:

1. **Enable Launchd Agent** (checks publish queue every 10 minutes):
   ```bash
   cp scripts/com.nova.autopilot.publish_queue.plist ~/Library/LaunchAgents/
   launchctl load ~/Library/LaunchAgents/com.nova.autopilot.publish_queue.plist
   ```
2. **Configure Power Management Wake Times**:
   ```bash
   bash scripts/setup_pmset_wake.sh
   ```
   This schedules your Mac to wake 5 minutes before US prime times (21:25:00 IST / 11:55 AM Eastern).
3. **Cancel Wake Schedule**:
   ```bash
   bash scripts/remove_pmset_wake.sh
   ```

---

## 🔒 Platform Safety, Copyright & Privacy

- **100% Original Commentary**: No downloaded creator videos, no copied article text. Sources are used solely for topic discovery and factual claims.
- **Attributed Visuals & Audio**: Only public domain (NASA, Wikimedia) or licensed royalty-free stock media (Pexels, Pixabay) are used. Every clip and track is logged with its license in `stock_attributions`.
- **Zero Financial Advice**: Strict compliance engine guarantees educational framing with mandatory disclaimers and rejected speculative phrasing.
- **Mandatory AI Disclosure**: Automatically marks YouTube synthetic media disclosures and appends AI transparency notices in captions and descriptions.
- **Zero Secret Leaks**: `.env` and SQLite databases are strictly excluded by `.gitignore`.

---

## 📄 License

Licensed under the MIT License. Developed for Prashant Roy (`@NovaPrashantroy`).
