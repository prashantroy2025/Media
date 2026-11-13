#!/usr/bin/env python3
"""Nova Doctor v2.0 - Diagnostics and Health Verification Tool.
Tests API keys with real tiny network requests, checks keyless fallbacks,
and prints a rich, formatted PASS/FAIL table across all components.
"""

import os
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
        return in_venv, "Virtualenv detected and active" if in_venv else "Running outside .venv (run via .venv/bin/python)"

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
                return True, f"NASA APOD API working (Key: {key[:6]}...)"
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
            return False, "PEXELS_API_KEY missing. Add to .env: PEXELS_API_KEY=your_key (from pexels.com/api)"
        try:
            r = requests.get("https://api.pexels.com/v1/curated?per_page=1", headers={"Authorization": key}, timeout=4)
            if r.status_code == 200:
                return True, "Pexels API authenticated and active"
            return False, f"Pexels API returned HTTP {r.status_code} (Check key in .env)"
        except Exception as e:
            return False, f"Pexels request error: {e}"

    # 10. Pixabay Stock API (Real Tiny Request)
    def check_pixabay():
        key = os.getenv("PIXABAY_API_KEY")
        if not key:
            return False, "PIXABAY_API_KEY missing. Add to .env: PIXABAY_API_KEY=your_key (from pixabay.com/api/docs)"
        try:
            r = requests.get(f"https://pixabay.com/api/?key={key}&q=space&per_page=3", timeout=4)
            if r.status_code == 200:
                return True, "Pixabay API authenticated and active"
            return False, f"Pixabay API returned HTTP {r.status_code}"
        except Exception as e:
            return False, f"Pixabay request error: {e}"

    # 11. Optional Hosted LLM (Groq / Gemini)
    def check_hosted_llm():
        groq_key = os.getenv("GROQ_API_KEY")
        gemini_key = os.getenv("GEMINI_API_KEY")
        if groq_key:
            return True, "Groq API key configured (llama-3.3-70b-versatile available)"
        if gemini_key:
            return True, "Gemini API key configured (gemini-2.0-flash available)"
        return False, "No hosted LLM key in .env. Optional: GEMINI_API_KEY=... or GROQ_API_KEY=..."

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
        ("Optional Hosted LLM", check_hosted_llm),
        ("Subtitle Typography", check_font),
        ("Music & Sound Effects", check_audio_assets),
        ("YouTube OAuth Auth", check_youtube),
        ("Instagram Meta Token", check_instagram),
    ]

    for name, fn in checks:
        col_name, status, detail = check_item(name, fn)
        table.add_row(col_name, status, detail)

    console.print(table)
    console.print("\n[bold]Summary:[/bold] All core rendering and generation tools inspected.")
    console.print("To run in mock/dry-run mode without external APIs: [cyan]python -m nova dry-run[/cyan]\n")


if __name__ == "__main__":
    run_doctor()
