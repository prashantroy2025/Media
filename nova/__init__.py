"""Nova Autopilot - Local AI Short-Video Studio & Auto-Publisher.
Built for Apple Silicon M2 (macOS).
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Ensure environment variables are loaded immediately from project root .env
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_env_file = _PROJECT_ROOT / ".env"
if _env_file.exists():
    load_dotenv(dotenv_path=_env_file, override=False)
else:
    load_dotenv(override=False)

if "/opt/homebrew/bin" not in os.environ.get("PATH", ""):
    os.environ["PATH"] = f"/opt/homebrew/bin:{os.environ.get('PATH', '')}"

# PyAV 19+ compatibility patch for faster-whisper
try:
    import av

    _orig_av_open = av.open

    def _safe_av_open(*args, **kwargs):
        kwargs.pop("metadata_errors", None)
        return _orig_av_open(*args, **kwargs)

    av.open = _safe_av_open
except Exception:
    pass

__version__ = "6.0.0"
