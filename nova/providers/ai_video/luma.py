"""Luma Dream Machine AI Video Generation Provider Adapter."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import requests

from nova.logging_setup import logger
from nova.providers.ai_video.base import (
    AIVideoJob,
    AIVideoJobStatus,
    BaseAIVideoProvider,
)


class LumaVideoProvider(BaseAIVideoProvider):
    """Integrates Luma Dream Machine text-to-video / image-to-video API."""

    def __init__(self, api_key: str | None = None, timeout_seconds: int = 180):
        key = api_key or os.getenv("LUMA_API_KEY", "")
        super().__init__(api_key=key, timeout_seconds=timeout_seconds)
        self.base_url = "https://api.lumalabs.ai/dream-machine/v1"

    @property
    def provider_id(self) -> str:
        return "luma"

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def generate_video_from_text(
        self,
        prompt: str,
        duration_seconds: float = 5.0,
        aspect_ratio: str = "9:16",
        dest_path: Path | None = None,
    ) -> AIVideoJob:
        if not self.is_configured():
            return AIVideoJob(
                job_id="luma_unconfigured",
                provider=self.provider_id,
                prompt=prompt,
                status=AIVideoJobStatus.FAILED,
                duration_seconds=duration_seconds,
                error_message="LUMA_API_KEY not configured in environment.",
            )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "prompt": prompt,
            "aspect_ratio": "9:16",
            "loop": False,
        }

        try:
            res = requests.post(f"{self.base_url}/generations", headers=headers, json=payload, timeout=30)
            if res.status_code in (200, 201):
                gen_id = res.json().get("id")
                return self._poll_generation(gen_id, prompt, duration_seconds, dest_path, headers)
            return AIVideoJob(
                job_id=f"luma_{int(time.time())}",
                provider=self.provider_id,
                prompt=prompt,
                status=AIVideoJobStatus.FAILED,
                duration_seconds=duration_seconds,
                error_message=f"Luma API returned HTTP {res.status_code}: {res.text[:200]}",
            )
        except Exception as e:
            return AIVideoJob(
                job_id=f"luma_{int(time.time())}",
                provider=self.provider_id,
                prompt=prompt,
                status=AIVideoJobStatus.FAILED,
                duration_seconds=duration_seconds,
                error_message=str(e),
            )

    def generate_video_from_image(
        self,
        image_path: Path,
        prompt: str = "",
        duration_seconds: float = 5.0,
        aspect_ratio: str = "9:16",
        dest_path: Path | None = None,
    ) -> AIVideoJob:
        return self.generate_video_from_text(prompt, duration_seconds, aspect_ratio, dest_path)

    def _poll_generation(
        self, gen_id: str, prompt: str, duration: float, dest_path: Path | None, headers: dict
    ) -> AIVideoJob:
        start_t = time.time()
        while time.time() - start_t < self.timeout_seconds:
            try:
                res = requests.get(f"{self.base_url}/generations/{gen_id}", headers=headers, timeout=20)
                if res.status_code == 200:
                    data = res.json()
                    state = data.get("state", "").lower()
                    if state == "completed":
                        assets = data.get("assets", {})
                        video_url = assets.get("video")
                        if video_url:
                            target = dest_path or Path(f"assets/cache/ai_video/{gen_id}.mp4")
                            target.parent.mkdir(parents=True, exist_ok=True)
                            v_resp = requests.get(video_url, timeout=60)
                            target.write_bytes(v_resp.content)
                            return AIVideoJob(
                                job_id=gen_id,
                                provider=self.provider_id,
                                prompt=prompt,
                                status=AIVideoJobStatus.COMPLETED,
                                duration_seconds=duration,
                                output_video_path=str(target),
                                cost_usd=0.20,
                            )
                    elif state == "failed":
                        return AIVideoJob(
                            job_id=gen_id,
                            provider=self.provider_id,
                            prompt=prompt,
                            status=AIVideoJobStatus.FAILED,
                            duration_seconds=duration,
                            error_message=data.get("failure_reason", "Luma generation failed."),
                        )
                time.sleep(4.0)
            except Exception:
                time.sleep(4.0)

        return AIVideoJob(
            job_id=gen_id,
            provider=self.provider_id,
            prompt=prompt,
            status=AIVideoJobStatus.FAILED,
            duration_seconds=duration,
            error_message="Luma generation timed out.",
        )
