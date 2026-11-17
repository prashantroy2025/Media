"""Mock / Offline AI Video Provider for deterministic local testing."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

from nova.providers.ai_video.base import (
    AIVideoJob,
    AIVideoJobStatus,
    BaseAIVideoProvider,
)


class MockAIVideoProvider(BaseAIVideoProvider):
    """Produces synthetic motion gradient MP4s locally using FFmpeg."""

    @property
    def provider_id(self) -> str:
        return "mock"

    def is_configured(self) -> bool:
        return True

    def generate_video_from_text(
        self,
        prompt: str,
        duration_seconds: float = 3.0,
        aspect_ratio: str = "9:16",
        dest_path: Path | None = None,
    ) -> AIVideoJob:
        job_id = f"mock_{int(time.time()*1000)}"
        target = dest_path or Path(f"assets/cache/ai_video/{job_id}.mp4")
        target.parent.mkdir(parents=True, exist_ok=True)

        ffmpeg_bin = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
        cmd = [
            ffmpeg_bin, "-y",
            "-f", "lavfi",
            "-i", f"color=c=0x111c30:s=1080x1920:r=30:d={duration_seconds}",
            "-c:v", "libx264", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p",
            str(target.resolve()),
        ]
        res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if res.returncode == 0 and target.exists():
            return AIVideoJob(
                job_id=job_id,
                provider=self.provider_id,
                prompt=prompt,
                status=AIVideoJobStatus.COMPLETED,
                duration_seconds=duration_seconds,
                output_video_path=str(target),
                cost_usd=0.0,
            )
        return AIVideoJob(
            job_id=job_id,
            provider=self.provider_id,
            prompt=prompt,
            status=AIVideoJobStatus.FAILED,
            duration_seconds=duration_seconds,
            error_message="Failed to generate mock video via FFmpeg.",
        )

    def generate_video_from_image(
        self,
        image_path: Path,
        prompt: str = "",
        duration_seconds: float = 3.0,
        aspect_ratio: str = "9:16",
        dest_path: Path | None = None,
    ) -> AIVideoJob:
        return self.generate_video_from_text(prompt, duration_seconds, aspect_ratio, dest_path)
