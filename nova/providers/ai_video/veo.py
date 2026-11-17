"""Google Veo AI Video Generation Provider Adapter."""

from __future__ import annotations

import base64
import os
import time
from pathlib import Path
from typing import Any

import requests

from nova.gemini import _mask_api_key, _parse_gemini_keys
from nova.logging_setup import logger
from nova.providers.ai_video.base import (
    AIVideoJob,
    AIVideoJobStatus,
    BaseAIVideoProvider,
)


class GoogleVeoProvider(BaseAIVideoProvider):
    """Integrates Google Veo video generation via Google AI / Vertex."""

    def __init__(self, api_key: str | None = None, timeout_seconds: int = 120):
        raw_key = api_key or os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
        self.api_keys = _parse_gemini_keys(raw_key)
        primary_key = self.api_keys[0] if self.api_keys else (str(api_key or "") if api_key else "")
        super().__init__(api_key=primary_key, timeout_seconds=timeout_seconds)
        self.endpoint_url = "https://generativelanguage.googleapis.com/v1beta/models/veo-3.1-fast-generate-001:predict"

    @property
    def provider_id(self) -> str:
        return "google_veo"

    def is_configured(self) -> bool:
        return bool(self.api_keys or self.api_key)

    def generate_video_from_text(
        self,
        prompt: str,
        duration_seconds: float = 4.0,
        aspect_ratio: str = "9:16",
        dest_path: Path | None = None,
    ) -> AIVideoJob:
        if not self.is_configured():
            return AIVideoJob(
                job_id="veo_unconfigured",
                provider=self.provider_id,
                prompt=prompt,
                status=AIVideoJobStatus.FAILED,
                duration_seconds=duration_seconds,
                error_message="GEMINI_API_KEY / GOOGLE_API_KEY not configured for Google Veo.",
            )

        job_id = f"veo_{int(time.time())}"
        payload = {
            "instances": [{"prompt": f"{prompt}, 9:16 vertical orientation, cinematic 4k, photorealistic"}],
            "parameters": {
                "sampleCount": 1,
                "durationSeconds": int(min(duration_seconds, 8.0)),
                "aspectRatio": "9:16",
            },
        }

        keys_to_try = list(self.api_keys) if self.api_keys else ([self.api_key] if self.api_key else [])
        last_error = ""

        for key in keys_to_try:
            url = f"{self.endpoint_url}?key={key}"
            masked = _mask_api_key(key)
            try:
                logger.info(f"[Veo] Requesting text-to-video using key [{masked}] for: '{prompt[:60]}...'")
                res = requests.post(url, json=payload, timeout=self.timeout_seconds)
                if res.status_code == 200:
                    data = res.json()
                    predictions = data.get("predictions", [])
                    if predictions and "bytesBase64Encoded" in predictions[0]:
                        raw_bytes = base64.b64decode(predictions[0]["bytesBase64Encoded"])
                        target = dest_path or Path(f"assets/cache/ai_video/{job_id}.mp4")
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(raw_bytes)
                        return AIVideoJob(
                            job_id=job_id,
                            provider=self.provider_id,
                            prompt=prompt,
                            status=AIVideoJobStatus.COMPLETED,
                            duration_seconds=duration_seconds,
                            output_video_path=str(target),
                            cost_usd=0.08,
                        )
                elif res.status_code == 429 or res.status_code in (400, 401, 403):
                    last_error = f"Veo API returned HTTP {res.status_code}: {res.text[:200]}"
                    logger.warning(f"[Veo] Key [{masked}] failed ({res.status_code}). Failing over to next key...")
                    continue
                else:
                    last_error = f"Veo API returned HTTP {res.status_code}: {res.text[:200]}"
            except Exception as e:
                last_error = str(e)
                logger.warning(f"[Veo] Key [{masked}] exception: {e}. Rotating to next key...")
                continue

        return AIVideoJob(
            job_id=job_id,
            provider=self.provider_id,
            prompt=prompt,
            status=AIVideoJobStatus.FAILED,
            duration_seconds=duration_seconds,
            error_message=last_error or "All configured Veo API keys failed.",
        )

    def generate_video_from_image(
        self,
        image_path: Path,
        prompt: str = "",
        duration_seconds: float = 4.0,
        aspect_ratio: str = "9:16",
        dest_path: Path | None = None,
    ) -> AIVideoJob:
        return self.generate_video_from_text(prompt, duration_seconds, aspect_ratio, dest_path)
