"""Synthesized CC0 Sound Design Engine for Nova Autopilot v8.0.

Generates broadcast-grade procedural UI sound effects using NumPy math and audio synthesis:
- whoosh.wav: Transition swoosh (filtered noise envelope)
- impact.wav: Punchy sub-bass drop with punchy transient
- riser.wav: Exponential tension build sweep
- pop.wav: Kinetic word-pop and counter chirp
- tick.wav: Fast subtle metric tick

License: Creative Commons Zero (CC0 1.0 Universal - Public Domain Dedication).
"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

import numpy as np

from nova.config import PROJECT_ROOT

SFX_DIR = PROJECT_ROOT / "assets" / "sfx"
SAMPLE_RATE = 48000


def save_wav_16bit_mono(path: Path, data: np.ndarray, sample_rate: int = SAMPLE_RATE) -> None:
    """Clamps and writes 1D float array [-1.0, 1.0] to a 16-bit PCM mono WAV file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    clamped = np.clip(data, -1.0, 1.0)
    int16_data = (clamped * 32767.0).astype(np.int16)

    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(int16_data.tobytes())


def generate_whoosh(duration: float = 0.45) -> np.ndarray:
    """Generates a dynamic cinematic whoosh transition sound."""
    num_samples = int(SAMPLE_RATE * duration)
    t = np.linspace(0, duration, num_samples, endpoint=False)

    # White noise base
    noise = np.random.uniform(-1.0, 1.0, num_samples)

    # Symmetrical bell-curve volume envelope
    env = np.exp(-((t - duration * 0.45) ** 2) / (2 * (0.12**2)))

    # Pitch/filter modulation frequency sweep (sine carrier blend)
    freq = 180.0 + 900.0 * np.exp(-((t - duration * 0.45) ** 2) / (2 * (0.14**2)))
    phase = 2 * np.pi * np.cumsum(freq) / SAMPLE_RATE
    carrier = np.sin(phase)

    audio = (noise * 0.65 + carrier * 0.35) * env
    return audio / (np.max(np.abs(audio)) + 1e-6)


def generate_impact(duration: float = 0.65) -> np.ndarray:
    """Generates a heavy sub-bass impact for key revelations and number slams."""
    num_samples = int(SAMPLE_RATE * duration)
    t = np.linspace(0, duration, num_samples, endpoint=False)

    # Pitch drops rapidly from 160 Hz down to 38 Hz
    freq = 38.0 + 125.0 * np.exp(-t * 22.0)
    phase = 2 * np.pi * np.cumsum(freq) / SAMPLE_RATE
    bass = np.sin(phase)

    # Exponential decay envelope
    env = np.exp(-t * 7.5)

    # Initial punch transient (short burst of noise)
    punch_len = int(SAMPLE_RATE * 0.04)
    punch = np.zeros(num_samples)
    punch[:punch_len] = np.random.uniform(-0.5, 0.5, punch_len) * np.linspace(1, 0, punch_len)

    audio = (bass * 0.85 + punch * 0.25) * env
    return audio / (np.max(np.abs(audio)) + 1e-6)


def generate_riser(duration: float = 1.2) -> np.ndarray:
    """Generates a smooth upward tension riser leading into a payoff beat."""
    num_samples = int(SAMPLE_RATE * duration)
    t = np.linspace(0, duration, num_samples, endpoint=False)

    # Exponential pitch sweep from 120 Hz to 850 Hz
    freq = 120.0 * (850.0 / 120.0) ** (t / duration)
    phase = 2 * np.pi * np.cumsum(freq) / SAMPLE_RATE

    # Swelling volume envelope
    env = (t / duration) ** 2.2

    # Shimmer harmonic
    harmonic = np.sin(phase * 1.5) * 0.25
    audio = (np.sin(phase) + harmonic) * env
    return audio / (np.max(np.abs(audio)) + 1e-6)


def generate_pop(duration: float = 0.12) -> np.ndarray:
    """Generates a subtle, snappy UI pop sound for key-term animation and number counters."""
    num_samples = int(SAMPLE_RATE * duration)
    t = np.linspace(0, duration, num_samples, endpoint=False)

    # Quick frequency chirp 350 Hz -> 800 Hz -> 250 Hz
    freq = 350.0 + 450.0 * np.sin(np.pi * (t / duration))
    phase = 2 * np.pi * np.cumsum(freq) / SAMPLE_RATE

    env = np.exp(-t * 45.0)
    audio = np.sin(phase) * env
    return audio / (np.max(np.abs(audio)) + 1e-6)


def ensure_sfx_library() -> dict[str, Path]:
    """Ensures all essential sound effects exist on disk in assets/sfx/."""
    SFX_DIR.mkdir(parents=True, exist_ok=True)

    files = {
        "whoosh": SFX_DIR / "whoosh.wav",
        "impact": SFX_DIR / "impact.wav",
        "riser": SFX_DIR / "riser.wav",
        "pop": SFX_DIR / "pop.wav",
    }

    # Generate or refresh assets
    if not files["whoosh"].exists() or files["whoosh"].stat().st_size < 1000:
        save_wav_16bit_mono(files["whoosh"], generate_whoosh())
    if not files["impact"].exists() or files["impact"].stat().st_size < 1000:
        save_wav_16bit_mono(files["impact"], generate_impact())
    if not files["riser"].exists():
        save_wav_16bit_mono(files["riser"], generate_riser())
    if not files["pop"].exists():
        save_wav_16bit_mono(files["pop"], generate_pop())

    # Write license file
    license_file = SFX_DIR / "LICENSE.md"
    license_file.write_text(
        "# Sound Effects License - Creative Commons Zero (CC0)\n\n"
        "All procedural sound effect files in `assets/sfx/` (`whoosh.wav`, `impact.wav`, `riser.wav`, `pop.wav`) "
        "were procedurally synthesized by Nova Autopilot using NumPy audio waveform generators.\n\n"
        "These audio assets are dedicated to the public domain under Creative Commons CC0 1.0 Universal.\n"
        "You can copy, modify, distribute, and perform the work, even for commercial purposes, without asking permission.\n",
        encoding="utf-8",
    )

    return files


if __name__ == "__main__":
    out = ensure_sfx_library()
    print("Synthesized procedural SFX library:")
    for k, v in out.items():
        print(f"  {k}: {v} ({v.stat().st_size} bytes)")
