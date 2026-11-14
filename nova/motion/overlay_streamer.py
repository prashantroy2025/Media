"""Streaming Pipeline for Motion Overlays in Nova Autopilot v8.0.

Streams Pillow-supersampled RGBA frames directly to an FFmpeg subprocess, producing
a memory-safe transparent QuickTime MOV stream (PNG codec) containing all animated
visual design components (kinetic pops, counters, comparisons, progress bars, source tags).
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from PIL import Image

from nova.logging_setup import logger
from nova.motion.components import MotionComponent

FFMPEG_BIN = "/opt/homebrew/bin/ffmpeg" if os.path.exists("/opt/homebrew/bin/ffmpeg") else "ffmpeg"


def render_motion_overlay_stream(
    components: list[MotionComponent],
    total_duration: float,
    dest_mov_path: str | Path,
    niche: str = "ai_tech",
    fps: int = 30,
    width: int = 1080,
    height: int = 1920,
) -> Path:
    """Renders all motion components into a transparent RGBA MOV video stream."""
    out_path = Path(dest_mov_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    total_frames = max(1, int(round(total_duration * fps)))
    logger.info(
        f"Rendering motion overlay stream: {len(components)} components across {total_frames} frames ({total_duration:.2f}s @ {fps}fps)..."
    )

    ffmpeg_cmd = [
        FFMPEG_BIN,
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgba",
        "-s",
        f"{width}x{height}",
        "-r",
        str(fps),
        "-i",
        "-",
        "-c:v",
        "png",
        "-r",
        str(fps),
        "-pix_fmt",
        "rgba",
        str(out_path),
    ]

    proc = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    t_start = time.time()
    try:
        for frame_idx in range(total_frames):
            t_rel = frame_idx / float(fps)

            # Create transparent RGBA canvas
            frame_img = Image.new("RGBA", (width, height), (0, 0, 0, 0))

            # Render each active component
            for comp in components:
                comp.render_frame(frame_img, t_rel=t_rel, niche=niche)

            # Write raw bytes
            proc.stdin.write(frame_img.tobytes())

        proc.stdin.close()
        proc.wait(timeout=60)
    except Exception as e:
        proc.kill()
        raise RuntimeError(f"Motion overlay rendering failed: {e}") from e

    elapsed = time.time() - t_start
    logger.info(f"Motion overlay stream successfully rendered in {elapsed:.2f}s -> {out_path} ({out_path.stat().st_size / 1024:.1f} KB)")
    return out_path
