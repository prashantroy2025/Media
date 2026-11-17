"""Runway Gen-3 Alpha AI Video Generation Provider Adapter."""

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


class RunwayVideoProvider(BaseAIVideoProvider):
    """Integrates Runway Gen-3 Alpha text-to-video / image-to-video API."""

    def __init__(self, api_key: str | None = None, timeout_seconds: int = 180):
        key = api_key or os.getenv("RUNWAY_API_KEY", "")
        super().__init__(api_key=key, timeout_seconds=timeout_seconds)
        self.base_url = "https://api.dev.runwayml.com/v1"

    @property
    def provider_id(self) -> str:
        return "runway"

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
                job_id="runway_unconfigured",
                provider=self.provider_id,
                prompt=prompt,
                status=AIVideoJobStatus.FAILED,
                duration_seconds=duration_seconds,
                error_message="RUNWAY_API_KEY not configured in environment.",
            )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "X-Runway-Version": "2024-09-13",
            "Content-Type": "application/json",
        }
        payload = {
            "promptText": prompt,
            "model": "gen3a_turbo",
            "duration": int(min(duration_seconds, 10)),
            "ratio": "768:1280",  # 9:16 equivalent vertical
        }

        try:
            res = requests.post(f"{self.base_url}/tasks", headers=headers, json=payload, timeout=30)
            if res.status_code in (200, 201):
                task_id = res.json().get("id", f"runway_{int(time.time())}")
                # Poll task status
                return self._poll_task(task_id, prompt, duration_seconds, dest_path, headers)
            return AIVideoJob(
                job_id=f"runway_{int(time.time())}",
                provider=self.provider_id,
                prompt=prompt,
                status=AIVideoJobStatus.FAILED,
                duration_seconds=duration_seconds,
                error_message=f"Runway API returned HTTP {res.status_code}: {res.text[:200]}",
            )
        except Exception as e:
            return AIVideoJob(
                job_id=f"runway_{int(time.time())}",
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

    def _poll_task(
        self, task_id: str, prompt: str, duration: float, dest_path: Path | None, headers: dict
    ) -> AIVideoJob:
        start_t = time.time()
        while time.time() - start_t < self.timeout_seconds:
            try:
                res = requests.get(f"{self.base_url}/tasks/{task_id}", headers=headers, timeout=20)
                if res.status_code == 200:
                    data = res.json()
                    status = data.get("status", "").upper()
                    if status == "SUCCEEDED":
                        artifacts = data.get("output", [])
                        if artifacts:
                            video_url = artifacts[0]
                            target = dest_path or Path(f"assets/cache/ai_video/{task_id}.mp4")
                            target.parent.mkdir(parents=True, exist_ok=True)
                            v_resp = requests.get(video_url, timeout=60)
                            target.write_bytes(v_resp.content)
                            return AIVideoJob(
                                job_id=task_id,
                                provider=self.provider_id,
                                prompt=prompt,
                                status=AIVideoJobStatus.COMPLETED,
                                duration_seconds=duration,
                                output_video_path=str(target),
                                cost_usd=0.25,
                            )
                    elif status in ("FAILED", "CANCELLED"):
                        return AIVideoJob(
                            job_id=task_id,
                            provider=self.provider_id,
                            prompt=prompt,
                            status=AIVideoJobStatus.FAILED,
                            duration_seconds=duration,
                            error_message=data.get("failure", "Runway generation failed."),
                        )
                time.sleep(4.0)
            except Exception as e:
                time.sleep(4.0)

        return AIVideoJob(
            job_id=task_id,
            provider=self.provider_id,
            prompt=prompt,
            status=AIVideoJobStatus.FAILED,
            duration_seconds=duration,
            error_message="Runway generation timed out.",
        )
