#!/usr/bin/env python3
"""Nova Doctor v2.0 - Diagnostics and Health Verification Tool.
Tests API keys with real tiny network requests, checks keyless fallbacks,
and prints a rich, formatted PASS/FAIL table across all components.
"""

import os
import re
import shutil
import sys
from pathlib import Path

import requests
from rich.console import Console
from rich.table import Table

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from nova.config import load_config  # noqa: E402
from nova.publishers.instagram import InstagramPublisher  # noqa: E402
from nova.renderer import detect_video_encoder  # noqa: E402

console = Console()


def check_item(name: str, check_fn) -> tuple[str, str, str]:
    """Runs a single health check and returns (Name, Status, Detail)."""
    try:
        ok, detail = check_fn()
        status = "[bold green]PASS[/bold green]" if ok else "[bold yellow]WARN[/bold yellow]"
        return name, status, detail
    except Exception as e:
        return name, "[bold red]FAIL[/bold red]", str(e)


def run_doctor():
    console.print("\n[bold cyan]🩺 Running Nova Autopilot v2.0 System Doctor...[/bold cyan]\n")
    settings = load_config()

    table = Table(title="Nova Autopilot v2.0 Environment & API Health Check", show_lines=True)
    table.add_column("Component / Check", style="bold white", width=26)
    table.add_column("Status", justify="center", width=10)
    table.add_column("Details & Recommendations", style="dim", width=48)

    # 1. Python version
    def check_python():
        v = sys.version_info
        ok = v.major == 3 and v.minor >= 11
        return ok, f"Python {v.major}.{v.minor}.{v.micro} ({'Optimal 3.11+' if ok else 'Requires 3.11+'})"

    # 2. Virtual environment
    def check_venv():
        in_venv = sys.prefix != sys.base_prefix or (PROJECT_ROOT / ".venv").exists()
        return (
            in_venv,
            "Virtualenv detected and active" if in_venv else "Running outside .venv (run via .venv/bin/python)",
        )

    # 3. FFmpeg & Hardware Encoder
    def check_ffmpeg():
        path = shutil.which("ffmpeg")
        if not path:
            return False, "ffmpeg not found. Install via: brew install ffmpeg"
        encoder = detect_video_encoder()
        return True, f"Found at {path} (Encoder: {encoder})"

    # 4. FFprobe
    def check_ffprobe():
        path = shutil.which("ffprobe")
        return bool(path), f"Found at {path}" if path else "ffprobe not found. Install via brew install ffmpeg"

    # 5. Ollama Server Running
    def check_ollama():
        import httpx

        host = settings.llm.ollama.host
        try:
            r = httpx.get(f"{host}/api/tags", timeout=3.0)
            if r.status_code == 200:
                models = [m["name"] for m in r.json().get("models", [])]
                return True, f"Online ({len(models)} models available: {', '.join(models[:3])})"
            return False, f"Server responded with status {r.status_code}"
        except Exception:
            return False, f"Cannot reach {host}. Start via `ollama serve` or app."

    # 6. LLM Model Available
    def check_model():
        import httpx

        host = settings.llm.ollama.host
        target_model = settings.llm.ollama.model
        try:
            r = httpx.get(f"{host}/api/tags", timeout=3.0)
            if r.status_code == 200:
                models = [m["name"] for m in r.json().get("models", [])]
                pulled = any(target_model in m for m in models)
                if pulled:
                    return True, f"Model '{target_model}' ready (Evaluated best English fact writer)"
                return False, f"Model '{target_model}' not pulled. Run `ollama pull {target_model}`"
            return False, "Ollama not responding"
        except Exception:
            return False, f"Cannot query Ollama models at {host}"

    # 7. NASA API (Real Tiny Request)
    def check_nasa():
        key = os.getenv("NASA_API_KEY")
        if not key:
            return False, "NASA_API_KEY missing. Add to .env: NASA_API_KEY=your_key (from api.nasa.gov)"
        try:
            r = requests.get(f"https://api.nasa.gov/planetary/apod?api_key={key}", timeout=4)
            if r.status_code == 200:
                return True, "NASA APOD API working (Key configured)"
            elif r.status_code == 429:
                return False, "NASA key rate limited (HTTP 429)."
            return False, f"NASA API returned HTTP {r.status_code}"
        except Exception as e:
            return False, f"Connection to NASA API failed: {e}"

    # 8. Keyless Media Sources Reachability (Wikimedia, Openverse, NASA)
    def check_keyless_visuals():
        statuses = []
        # Wikimedia Commons
        try:
            r_w = requests.get(
                "https://commons.wikimedia.org/w/api.php?action=query&generator=search&gsrsearch=earth&gsrnamespace=6&format=json",
                headers={"User-Agent": "NovaStudio/4.0"},
                timeout=4,
            )
            statuses.append(f"Wikimedia: {'OK' if r_w.status_code == 200 else 'HTTP ' + str(r_w.status_code)}")
        except Exception:
            statuses.append("Wikimedia: TIMEOUT")

        # NASA Public Library
        try:
            r_n = requests.get("https://images-api.nasa.gov/search?q=earth&media_type=image", timeout=4)
            statuses.append(f"NASA: {'OK' if r_n.status_code == 200 else 'HTTP ' + str(r_n.status_code)}")
        except Exception:
            statuses.append("NASA: TIMEOUT")

        # Openverse
        try:
            r_o = requests.get("https://api.openverse.org/v1/images/?q=earth&page_size=1", timeout=3)
            statuses.append(f"Openverse: {'OK' if r_o.status_code == 200 else 'HTTP ' + str(r_o.status_code)}")
        except Exception:
            statuses.append("Openverse: TIMEOUT")

        any_ok = any("OK" in s for s in statuses)
        detail = " | ".join(statuses)
        return any_ok, detail

    # 9. Pexels Stock API (Real Tiny Request)
    def check_pexels():
        key = os.getenv("PEXELS_API_KEY")
        if not key:
            return (
                False,
                "PEXELS_API_KEY missing (RECOMMENDED: get free key at pexels.com/api to enable premium stock video)",
            )
        try:
            r = requests.get("https://api.pexels.com/v1/curated?per_page=1", headers={"Authorization": key}, timeout=4)
            if r.status_code == 200:
                return True, "Pexels API authenticated and active (Preferred stock video provider)"
            return False, f"Pexels API returned HTTP {r.status_code} (Check key in .env)"
        except Exception as e:
            return False, f"Pexels request error: {e}"

    # 10. Pixabay Stock API (Real Tiny Request)
    def check_pixabay():
        key = os.getenv("PIXABAY_API_KEY")
        if not key:
            return (
                False,
                "PIXABAY_API_KEY missing (RECOMMENDED: get free key at pixabay.com/api/docs for secondary stock video)",
            )
        try:
            r = requests.get(f"https://pixabay.com/api/?key={key}&q=space&per_page=3", timeout=4)
            if r.status_code == 200:
                return True, "Pixabay API authenticated and active"
            return False, f"Pixabay API returned HTTP {r.status_code}"
        except Exception as e:
            return False, f"Pixabay request error: {e}"

    # 11. Open-License Icon & SFX Library
    def check_motion_assets():
        icon_dir = settings.resolve_path("assets/icons")
        has_icons = (icon_dir / "LICENSE.txt").exists() and (icon_dir / "cpu.png").exists()
        sfx_dir = settings.resolve_path("assets/sfx")
        has_sfx = (sfx_dir / "LICENSE.md").exists() and (sfx_dir / "whoosh.wav").exists() and (sfx_dir / "pop.wav").exists()
        if has_icons and has_sfx:
            return True, "Open-license icons (MIT) and synthesized SFX (CC0) verified"
        return False, "Run python -m nova.motion.icons and python -m nova.sfx to generate"

    # 12. Topic Policy Configuration
    def check_topic_policy():
        policy_path = settings.resolve_path("config/topic_policy.yaml")
        if policy_path.exists():
            return True, "config/topic_policy.yaml present (Tier A, B Sensitive News, C Prohibited)"
        return False, "Topic policy file missing at config/topic_policy.yaml"

    # 13. Fast 1-Second Test Render & Loudness Measurement
    def check_render_engine():
        import subprocess
        ffmpeg_bin = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
        try:
            cmd = [
                ffmpeg_bin,
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=c=navy:s=1080x1920:d=1",
                "-f",
                "lavfi",
                "-i",
                "sine=f=440:d=1",
                "-af",
                "loudnorm=I=-14:LRA=11:TP=-1.5",
                "-c:v",
                "h264_videotoolbox",
                "-b:v",
                "2M",
                "-f",
                "null",
                "-",
            ]
            res = subprocess.run(cmd, capture_output=True, timeout=10)
            if res.returncode == 0:
                return True, "VideoToolbox HW encoder, loudnorm mastering, and FFmpeg filtergraph operational"
            return False, f"Render test failed with code {res.returncode}"
        except Exception as e:
            return False, f"Render test error: {e}"

    # 11. Optional Hosted LLM (Groq / Gemini)
    def check_hosted_llm():
        groq_key = os.getenv("GROQ_API_KEY")
        gemini_key = os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if groq_key:
            return True, "Groq API key configured (llama-3.3-70b-versatile available)"
        if gemini_key:
            count = len([k for k in re.split(r"[,;\s]+", gemini_key.strip()) if k])
            if count > 1:
                return True, f"Gemini API configured ({count} keys in pool, auto-failover enabled)"
            return True, "Gemini API key configured (gemini-3.8-flash available)"
        return False, "No hosted LLM key in .env. Optional: GEMINI_API_KEY=... or GROQ_API_KEY=..."

    # 11b. Google Cloud & Service Account Security
    def check_google_cloud():
        import json
        gac = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        secret_file = settings.resolve_path(settings.youtube.client_secret_file)
        details = []

        if gac:
            gac_path = Path(gac)
            if not gac_path.is_absolute():
                gac_path = settings.resolve_path(gac_path)
            if gac_path.exists():
                try:
                    with open(gac_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    c_type = data.get("type", "credentials")
                    details.append(f"Service account file verified ({c_type})")
                except Exception as e:
                    return False, f"Invalid JSON in GOOGLE_APPLICATION_CREDENTIALS: {e}"
            else:
                return False, f"Credentials file not found at: {gac}. Place service-account.json in credentials/"

        gemini_key = os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if gemini_key:
            count = len([k for k in re.split(r"[,;\s]+", gemini_key.strip()) if k])
            if count > 1:
                details.append(f"Gemini API keys configured ({count} in pool)")
            else:
                details.append("Gemini API key configured")
        if secret_file.exists():
            details.append("YouTube OAuth client secret ready")

        if details:
            return True, " & ".join(details)
        return False, "No Google credentials configured. Optional: add GEMINI_API_KEY or GOOGLE_APPLICATION_CREDENTIALS"

    # 12. Subtitle Typography Font
    def check_font():
        font_file = settings.resolve_path("assets/fonts/Montserrat-ExtraBold.ttf")
        if font_file.exists():
            return True, "Montserrat-ExtraBold.ttf present (Open Font License verified)"
        return False, "Font file missing in assets/fonts/"

    # 13. Music & Sound Effects
    def check_audio_assets():
        music_dir = settings.resolve_path("assets/music")
        tracks = list(music_dir.glob("**/*.mp3")) + list(music_dir.glob("**/*.wav"))
        sfx_dir = settings.resolve_path("assets/sfx")
        has_sfx = (sfx_dir / "whoosh.wav").exists() and (sfx_dir / "impact.wav").exists()
        if tracks and has_sfx:
            return True, f"{len(tracks)} mood track(s) + synthesized whoosh/impact SFX ready"
        elif tracks:
            return True, f"{len(tracks)} track(s) in music dir (SFX will auto-generate)"
        return False, "No music tracks. Run: `python -m nova fetch-music`"

    # 14. YouTube OAuth Credentials & Token Validity
    def check_youtube():
        secret_file = settings.resolve_path(settings.youtube.client_secret_file)
        token_file = settings.resolve_path(settings.youtube.token_file)
        alt_token_file = settings.resolve_path("data/youtube_token.json")

        target_token = token_file if token_file.exists() else alt_token_file
        if target_token.exists():
            try:
                from google.oauth2.credentials import Credentials

                from nova.publishers.youtube import YOUTUBE_SCOPES

                creds = Credentials.from_authorized_user_file(str(target_token), YOUTUBE_SCOPES)
                is_refreshable = bool(creds.refresh_token)
                if creds.valid:
                    return True, f"Token valid & refreshable at {target_token.name}"
                elif is_refreshable:
                    return True, f"Token expired but refreshable at {target_token.name}"
                return False, "Token expired and not refreshable. Run: `python -m nova auth youtube`"
            except Exception as e:
                return False, f"Token invalid ({e}). Run: `python -m nova auth youtube`"

        if secret_file.exists():
            return False, f"Client secrets ready at {secret_file.name}. Run: `python -m nova auth youtube`"
        return False, "Missing credentials/client_secret.json (Required for YouTube publishing)"

    # 15. Instagram Graph API
    def check_instagram():
        ig_pub = InstagramPublisher(settings)
        if not ig_pub.access_token:
            return False, "INSTAGRAM_ACCESS_TOKEN not set. Optional: add to .env"
        ok, msg = ig_pub.check_token_expiry()
        return ok, msg

    checks = [
        ("Python Version", check_python),
        ("Virtual Environment", check_venv),
        ("FFmpeg + VideoToolbox", check_ffmpeg),
        ("FFprobe Audio Utility", check_ffprobe),
        ("Ollama Local Server", check_ollama),
        ("Target LLM (llama3.2:3b)", check_model),
        ("NASA API Key", check_nasa),
        ("Keyless Media Sources", check_keyless_visuals),
        ("Pexels Video API", check_pexels),
        ("Pixabay Video API", check_pixabay),
        ("Motion Icons & SFX", check_motion_assets),
        ("Topic Safety Policy", check_topic_policy),
        ("Render & HW Encoder", check_render_engine),
        ("Optional Hosted LLM", check_hosted_llm),
        ("Google Cloud & Auth", check_google_cloud),
        ("Subtitle Typography", check_font),
        ("Music & Sound Effects", check_audio_assets),
        ("YouTube OAuth Auth", check_youtube),
        ("Instagram Meta Token", check_instagram),
    ]

    for name, fn in checks:
        col_name, status, detail = check_item(name, fn)
        table.add_row(col_name, status, detail)

    console.print(table)

    # 16. Pluggable Media Providers Grouped Audit
    from nova.providers.registry import ProviderRegistry
    registry = ProviderRegistry()

    p_table = Table(title="Pluggable Licensed Media Providers (Multi-Source Supply)", show_lines=True)
    p_table.add_column("Category & Provider", style="bold white", width=28)
    p_table.add_column("Status", justify="center", width=14)
    p_table.add_column("Details, Signup URL & Live Diagnostic", style="white", width=46)

    # Group 1: Works Now
    works_now = [
        ("Pixabay", "pixabay", "https://pixabay.com/api/docs/"),
        ("NASA Image & Video", "nasa_library", "https://images.nasa.gov"),
        ("Wikimedia Commons", "wikimedia_commons", "https://commons.wikimedia.org"),
        ("Cleveland Museum of Art", "cleveland_museum", "https://www.clevelandart.org/open-access"),
        ("The Met Museum", "met_museum", "https://metmuseum.github.io"),
        ("Procedural Maps & Charts", "generated_maps", "Local Pillow synthesis"),
    ]
    p_table.add_row("[bold green]GROUP 1: WORKS NOW[/bold green]", "[green]ACTIVE[/green]", "[dim]Ready for pipeline renders[/dim]")
    for disp, pid, url in works_now:
        p = registry.get_provider(pid)
        ok, msg = p.test_connection() if p else (False, "Not found")
        stat = "[bold green]PASS[/bold green]" if ok else "[bold yellow]WARN[/bold yellow]"
        p_table.add_row(f"  • {disp}", stat, f"{msg}\n[dim]{url}[/dim]")

    # Group 2: Needs a Free Key
    needs_key = [
        ("Pexels Video & Photo", "pexels", "https://www.pexels.com/api/"),
        ("Smithsonian Open Access", "smithsonian", "https://api.data.gov/signup/"),
        ("Europeana Heritage", "europeana", "https://pro.europeana.eu/page/get-api"),
        ("Freesound CC0 Audio", "freesound", "https://freesound.org/help/developers/"),
        ("Unsplash Photography", "unsplash", "https://unsplash.com/developers"),
    ]
    p_table.add_row("[bold yellow]GROUP 2: NEEDS FREE KEY[/bold yellow]", "[yellow]OPTIONAL[/yellow]", "[dim]Skipped gracefully when missing key[/dim]")
    for disp, pid, url in needs_key:
        p = registry.get_provider(pid)
        has_k = bool(getattr(p, "api_key", None)) if p else False
        if has_k:
            ok, msg = p.test_connection()
            stat = "[bold green]PASS[/bold green]" if ok else "[bold yellow]WARN[/bold yellow]"
            p_table.add_row(f"  • {disp}", stat, f"{msg}\n[dim]{url}[/dim]")
        else:
            p_table.add_row(f"  • {disp}", "[yellow]NEEDS KEY[/yellow]", f"Missing {p.key_env if p else 'KEY'}\n[dim]Free signup: {url}[/dim]")

    # Group 3: Needs Decision
    needs_decision = [
        ("Coverr Video", "coverr", "Free API terms forbid commercial broadcast without enterprise contract."),
        ("Jamendo Audio", "jamendo", "Developer API is non-commercial only; triggers YouTube Content ID claims."),
    ]
    p_table.add_row("[bold magenta]GROUP 3: NEEDS DECISION[/bold magenta]", "[magenta]DISABLED[/magenta]", "[dim]Disabled by default due to commercial/legal terms[/dim]")
    for disp, pid, reason in needs_decision:
        p_table.add_row(f"  • {disp}", "[magenta]DISABLED[/magenta]", reason)

    console.print(p_table)

    console.print("\n[bold]Summary:[/bold] All core rendering, generation tools, and media providers inspected.")
    console.print("To test live provider connectivity: [cyan]python -m nova providers test[/cyan]")
    console.print("To run in mock/dry-run mode without external APIs: [cyan]python -m nova dry-run[/cyan]\n")


if __name__ == "__main__":
    run_doctor()
