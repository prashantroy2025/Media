# Nova Autopilot v9.0 🚀

> **Local-First Autonomous AI Short-Video Studio, Cinematic Motion Engine & Auto-Publisher**  
> Tailored for **Prashant Roy** (`@NovaPrashantroy` / **PRASHANT ROY**) for generating high-energy, premium **English Fact & Shock-News Shorts** targeting a **high-value English-speaking audience (US, UK, CA, AU)** for **YouTube Shorts**, **Instagram Reels**, and **TikTok**.

---

## 🌟 Overview: What's New in v9.0 Studio Transformation

**Nova Autopilot v9.0** transforms the system from a pipeline into a **Full Autonomous AI Short-Form Video Production Studio**:

1. **Professional Creator Presets (`nova.presets`)**:
   - 10 distinct, finely-tuned creator profiles: `viral_facts`, `documentary`, `cinematic_storytelling`, `dark_mystery`, `financial_education`, `investigative_journalism`, `historical_explainer`, `technology`, `news_explainer`, `high_energy_educational`.
   - Each preset customizes cut cadence, transition styles, color grading LUTs, typography, safe zone positioning, motion intensity, and background sound design.
   - CLI command to inspect presets: `python -m nova presets`.

2. **Timeline-Based Video Transitions Engine (`nova.transitions`)**:
   - Hardware-accelerated FFmpeg `xfade` chaining with Apple Silicon `h264_videotoolbox` support.
   - Smooth crossfades, dynamic whips (`slideleft`, `slideright`), zoom transitions (`zoomin`), and directional wipes.
   - Frame padding via `tpad` to guarantee sub-millisecond video-audio synchronization with zero cut seams.

3. **Cinematic Caption & Typography Engine (`nova.captions`)**:
   - 7 distinct caption design presets with active word karaoke highlighting.
   - Rounded pill background panels, outlined text, shadow glow, and strict Reels/Shorts UI safe zone adherence (`y=1380`).

4. **Reference Video & Image Intelligence (`nova.reference_engine`)**:
   - Extracts editing rhythm, shot duration distribution, dominant color palettes, and transition frequency from reference videos or screenshots.
   - 5 reference matching modes: `reference_inspired`, `reference_matched_pacing`, `reference_matched_composition`, `reference_matched_animation`, `reference_matched_typography_colors`.
   - CLI command: `python -m nova analyze-reference <file>` saves reusable reference JSON profiles (`assets/references/`).

5. **Advanced Audio & Sound Design Director (`nova.sound_designer`)**:
   - Contextual procedural SFX placement: impact hits on numerical facts, whooshes on transitions, risers for suspense, and pops on tags.
   - Vocal mastering with 80 Hz high-pass EQ and 3 kHz presence boost.
   - Dynamic narration ducking to -18 dB and EBU R128 broadcast normalization (-14 LUFS, -1.5 dBTP).

6. **Modular AI Video Generation Framework (`nova.providers.ai_video`)**:
   - Pluggable provider architecture supporting Google Veo, Runway Gen-3/Gen-4, Luma Dream Machine, Kling AI, and local mock testing.
   - Fallback hierarchy: AI Video -> Stock Footage (Pexels, Pixabay, NASA, Wikimedia) -> Motion Graphics.

7. **Autonomous Video Critic & 10-Point Scorecard (`nova.critic`)**:
   - 10-point evaluation: Technical Integrity, Audio Sync, Editing Cadence, Scene Variety, Visual Relevance, Caption Readability, Motion Design, Transition Smoothness, Color Consistency, 9:16 Framing.
   - Generates interactive HTML critic reports (`output/critic_report_<id>.html`) and JSON summaries.
   - Accessible via Review Studio UI at `/critic/{video_id}`.

8. **Three Production Modes (`--mode`)**:
   - `fast`: High-speed generation bypassing heavy video rendering and using direct cuts.
   - `professional`: Full broadcast pipeline with hardware `xfade` transitions, motion graphics, sound design, and color grading (default).
   - `premium_ai`: Professional pipeline augmented with AI hero video generation when providers are configured.

---

## 🌟 Overview: What's New in v7.0 & v8.0

**Nova Autopilot v8.0** elevates video production from standard template concatenation to **cinematic motion design, empirical scorecard verification, and a robust Three-Tier sensitive news policy**:

1. **Empirical 25-Point Audit Scorecard (`nova.audit`)**:
   - Automated quality scorecard CLI: `python -m nova audit-video <video_id>` and `python -m nova audit-system`.
   - Generates interactive self-contained HTML reports (`output/audit_<id>.html`) and machine-readable JSON summaries.
   - Enforces strict empirical pass thresholds:
     - **Scorecard Pass Rate**: $\ge 90.0\%$
     - **Loudness**: $-14.0 \pm 2.0$ LUFS (EBU R128) & True Peak $< -1.0$ dBTP
     - **Dead Silence**: $\le 0.40$s inside vocal track
     - **Speech Pace**: $160 \text{--} 185$ WPM
     - **Intelligibility (WER)**: $\le 3.0\%$ via independent faster-whisper audit
     - **Subtitle Drift**: Median $\le 60$ ms, Max $\le 250$ ms
     - **Visual Integrity**: $0$ black frames, $0$ freeze stretches, $< 10.0\%$ fallback cards
     - **Visual Cut Cadence**: Median $1.8 \text{--} 2.8$s, Max $\le 4.0$s
     - **Semantic Relevance**: $\ge 90.0\%$ above threshold
     - **Compliance**: $100\%$ licensed assets with attribution records

2. **Cinematic Motion Design Engine (`nova.motion`)**:
   - **Supersampled Easing Overlays**: 2x supersampled Pillow rendering with quadratic, cubic, spring overshoot, and exponential easing curves.
   - **Kinetic Key-Term Pop**: Key phrases dynamically pop into view synchronized to Whisper word timestamps with color accenting.
   - **Animated Counters**: Numerical figures (e.g., "$130 Million", "40,000 units") animate smoothly with rolling count-ups.
   - **Lower-Third Source Tag**: Sleek glassmorphic credential tag in opening seconds displaying source verification badge.
   - **Video Progress Bar**: Unobtrusive progress indicator animating along the bottom safe zone.
   - **Open-License Icons & Procedural SFX**: 11 MIT open-license icons (`assets/icons/`) and 4 synthesized CC0 sound effects (`assets/sfx/whoosh.wav`, `impact.wav`, `riser.wav`, `pop.wav`).
   - **Transparent QuickTime Stream**: Overlays rendered to an isolated RGBA stream (`.mov`) and composited in a single FFmpeg pass.

3. **Frame 0 Hook Architecture & Broadcast Color Grading (`nova.renderer`)**:
   - **Instant Visual Engagement**: Frame 0 displays an animated hook card with theme-matched color styling, transitioning within 0.3s.
   - **Color Grading**: Broadcast-calibrated filter complex (`eq=contrast=1.06:brightness=0.01:saturation=1.08,unsharp=3:3:0.4,vignette=PI/5`).
   - **Broadcast Standard Encoding**: Strictly enforces standard `yuv420p` (`tv` color range) with H.264 High Profile and Web Faststart (`+faststart`).

4. **Sound Design & Mastering (`nova.music`, `nova.sfx`)**:
   - **EBU R128 Broadcast Normalization**: Two-pass FFmpeg `loudnorm` mastering targeting $-14$ LUFS and $-1.5$ dBTP.
   - **Dynamic Voice Ducking**: Background music automatically ducks to 12% during narration and recovers during pauses.

5. **Sensitive News Mode & Three-Tier Topic Policy (`nova.topic_safety`)**:
   - Configured via `config/topic_policy.yaml`:
     - **Tier A (Normal)**: Standard evergreen, scientific, and mainstream tech news.
     - **Tier B (Sensitive News Allowed)**: Regulatory actions, corporate legal controversies, and policy shifts. Strictly requires 1 primary source (e.g., `.gov`, `.gov.uk`, SEC EDGAR) or 2 independent reputable outlets. Enforces neutral tone, non-sensational titles, "as of [Date]" freshness anchors, and mandatory human review sign-off.
     - **Tier C (Prohibited)**: Sensational scandals, unverified criminal rumors, and partisan political advocacy strictly blocked.
   - **Dispatch Auto-Publish Guard**: Pipeline enforces hard blocking on Tier B topics, locking them in the Review Queue until manually signed off.

6. **Review Studio Enhancements (`nova.review_ui`)**:
   - **Scorecard Badges**: Color-coded pass/fail scorecard indicators on dashboard and review cards.
   - **Direct Audit Viewer**: Standalone `/audit/{video_id}` endpoint rendering interactive 25-point audit scorecards.
   - **Interactive Compliance Checklist**: 5-point manual sign-off modal for Tier B videos (`/api/videos/{id}/checklist`).
   - **Shot Swapper**: Instant asset replacement per shot (`/api/videos/{id}/swap-shot`).
   - **Topic Policy Manager**: Built-in visual configuration editor at `/policy`.

7. **Voice Evaluation Benchmark & Pronunciation Engine (`nova.voice_eval`, `nova.utils.normalizer`)**:
   - Benchmark suite generating side-by-side voice comparisons (`output/voice_samples/` & `voice_comparison.html`).
   - Rule-based text normalizer with phonetic expansion and pronunciation override dictionary (`config/pronunciations.yaml`).

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

## 🛠️ Installation & Setup Guide

Follow these steps to set up Nova Autopilot on your local machine:

### 1. Clone the repository
```bash
git clone https://github.com/prashantroy2025/Media.git
cd Media/nova-autopilot # or cd nova-autopilot
```

### 2. Create a Python virtual environment
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install requirements
```bash
pip install -r requirements.txt
```

### 4. Copy `.env.example` to `.env`
```bash
cp .env.example .env
```
> [!IMPORTANT]
> **Credential Security**:
> - `.env` is private, local-only, and strictly ignored by Git (`.gitignore`).
> - `.env.example` contains placeholders only and is the **only** template file committed to GitHub.
> - Never commit `.env`, service-account JSONs, private keys, or API tokens to GitHub.

### 5. Add personal API credentials
Open `.env` in your editor and configure your credentials:
```bash
# LLM Providers (Ollama runs locally for free; cloud LLMs optional)
GEMINI_API_KEY=your_gemini_api_key_here
GROQ_API_KEY=your_groq_api_key_here

# Visual & Audio Providers (Free tiers available)
NASA_API_KEY=DEMO_KEY
PEXELS_API_KEY=your_pexels_api_key_here
PIXABAY_API_KEY=your_pixabay_api_key_here
```

### 6. Configure Google Cloud credentials (if required)
For YouTube auto-publishing or Google Cloud integrations:
1. Download your OAuth 2.0 Client Secret JSON from Google Cloud Console.
2. Save it locally to `credentials/client_secret.json`.
3. If using a Google Cloud Service Account, place your JSON key at `credentials/service-account.json` and ensure `.env` specifies:
   ```bash
   GOOGLE_APPLICATION_CREDENTIALS=./credentials/service-account.json
   ```
4. All files in `credentials/` and `service-account*.json` are automatically ignored by Git.

### 7. Run Nova Autopilot
Run the doctor tool to verify your environment and API credentials:
```bash
python -m nova doctor
# or
.venv/bin/python scripts/doctor.py
```

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

# Safe "Fresh Start" / Reset (wipe generated data, keep setup & credentials)
python -m nova reset --list          # Dry run: audit tables, rows, and files without touching anything
python -m nova reset                 # Interactive reset: prompts for confirmation phrase 'DELETE GENERATED DATA'
python -m nova reset --yes           # Non-interactive reset (bypasses prompt)
python -m nova reset --cache         # Also clear stock media download cache in assets/cache/
python -m nova reset --logs          # Also clear runtime log files in data/logs/
python -m nova reset --keep-learning # Purge videos/scripts/topics but preserve learned hook/niche statistics
python -m nova reset --only-demo     # Clean demo records and orphaned files only
python -m nova fresh-start           # Friendly alias for 'python -m nova reset'

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

# Run 25-point empirical scorecard audit on a specific video
python -m nova audit-video 114

# Run system-wide scorecard audit across all rendered videos
python -m nova audit-system

# Run 3-voice TTS benchmark & generate voice_comparison.html
python -m nova voice-eval

# Run full regression evaluation suite (100+ tests)
python -m nova eval-all

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

## 🔄 Safe Fresh-Start & System Reset (`reset` / `fresh-start`)

Nova Autopilot provides a dedicated, safety-hardened reset facility (`python -m nova reset` or `python -m nova fresh-start`) to cleanly wipe generated experiment data (topics, scripts, videos, queue slots, output files) while guaranteeing that your setup, API keys, credentials, and configurations survive.

### Safety Guarantees
1. **Verified SQLite Online Backup**: A consistent, live database snapshot is created using `sqlite3.Connection.backup()` into `data/backups/nova_<timestamp>.db` before any destructive action is taken.
2. **Mac Trash Recovery**: Generated files in `output/` are moved to the macOS Trash (`~/.Trash` / `send2trash`) so files can be recovered if needed. Files are never permanently deleted unless `--permanent` is explicitly passed.
3. **Strict Path Validation**: All target paths are strictly validated to prevent deleting any file outside the project, or dangerous directories (`/`, `~`, `~/Desktop`, parent directory).
4. **Active Process Locks**: Refuses to run if the Review Studio Web UI is listening on port 8765 or a pipeline PID lock (`data/pipeline.lock`) is active.
5. **Interactive Confirmation**: Prompts you to type `DELETE GENERATED DATA` before proceeding unless bypassed with `--yes`.
6. **Autoincrement Reset**: Clears `sqlite_sequence` for generated tables so your first fresh production video begins at ID #1.

### Reset Options
| Flag | Description |
|---|---|
| `--list` | **Dry run (default)**: Lists all tables, row counts, and files that would be cleared without modifying anything. |
| `--yes`, `-y` | Executes the reset without requiring manual confirmation typing. |
| `--cache` | Optional: Clears the stock media download cache (`assets/cache/`). |
| `--logs` | Optional: Clears rotating execution logs (`data/logs/`). |
| `--keep-learning` | Preserves creator pattern statistics and learned hook scores. |
| `--only-demo` | Clears only demo records (`is_demo=1`) and orphaned video files. |
| `--permanent` | Bypasses macOS Trash and uses permanent filesystem deletion. |

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
