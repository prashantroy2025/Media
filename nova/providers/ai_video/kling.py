"""Kling AI Video Generation Provider Adapter."""

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


class KlingVideoProvider(BaseAIVideoProvider):
    """Integrates Kling AI video generation API."""

    def __init__(self, api_key: str | None = None, timeout_seconds: int = 180):
        key = api_key or os.getenv("KLING_API_KEY", "")
        super().__init__(api_key=key, timeout_seconds=timeout_seconds)
        self.base_url = "https://api.klingai.com/v1"

    @property
    def provider_id(self) -> str:
        return "kling"

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
                job_id="kling_unconfigured",
                provider=self.provider_id,
                prompt=prompt,
                status=AIVideoJobStatus.FAILED,
                duration_seconds=duration_seconds,
                error_message="KLING_API_KEY not configured in environment.",
            )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model_name": "kling-v1",
            "prompt": prompt,
            "duration": int(min(duration_seconds, 10)),
            "aspect_ratio": "9:16",
        }

        try:
            res = requests.post(f"{self.base_url}/videos/text2video", headers=headers, json=payload, timeout=30)
            if res.status_code in (200, 201):
                task_id = res.json().get("data", {}).get("task_id", f"kling_{int(time.time())}")
                return self._poll_kling(task_id, prompt, duration_seconds, dest_path, headers)
            return AIVideoJob(
                job_id=f"kling_{int(time.time())}",
                provider=self.provider_id,
                prompt=prompt,
                status=AIVideoJobStatus.FAILED,
                duration_seconds=duration_seconds,
                error_message=f"Kling API returned HTTP {res.status_code}: {res.text[:200]}",
            )
        except Exception as e:
            return AIVideoJob(
                job_id=f"kling_{int(time.time())}",
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

    def _poll_kling(
        self, task_id: str, prompt: str, duration: float, dest_path: Path | None, headers: dict
    ) -> AIVideoJob:
        start_t = time.time()
        while time.time() - start_t < self.timeout_seconds:
            try:
                res = requests.get(f"{self.base_url}/videos/text2video/{task_id}", headers=headers, timeout=20)
                if res.status_code == 200:
                    data = res.json().get("data", {})
                    status = data.get("task_status", "").lower()
                    if status == "succeed":
                        video_url = data.get("task_result", {}).get("videos", [{}])[0].get("url")
                        if video_url:
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
                                cost_usd=0.20,
                            )
                    elif status == "failed":
                        return AIVideoJob(
                            job_id=task_id,
                            provider=self.provider_id,
                            prompt=prompt,
                            status=AIVideoJobStatus.FAILED,
                            duration_seconds=duration,
                            error_message=data.get("task_status_msg", "Kling generation failed."),
                        )
                time.sleep(4.0)
            except Exception:
                time.sleep(4.0)

        return AIVideoJob(
            job_id=task_id,
            provider=self.provider_id,
            prompt=prompt,
            status=AIVideoJobStatus.FAILED,
            duration_seconds=duration,
            error_message="Kling generation timed out.",
        )
