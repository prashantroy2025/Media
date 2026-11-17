"""AI Video Provider Factory with graceful fallback."""

from __future__ import annotations

import os
from typing import Optional

from nova.logging_setup import logger
from nova.providers.ai_video.base import BaseAIVideoProvider
from nova.providers.ai_video.kling import KlingVideoProvider
from nova.providers.ai_video.luma import LumaVideoProvider
from nova.providers.ai_video.mock import MockAIVideoProvider
from nova.providers.ai_video.runway import RunwayVideoProvider
from nova.providers.ai_video.veo import GoogleVeoProvider


class AIVideoProviderFactory:
    """Instantiates configured AI video providers with automatic fallback handling."""

    @staticmethod
    def get_provider(provider_name: str | None = None) -> BaseAIVideoProvider:
        """Returns the requested provider if configured, or the best available one."""
        name = (provider_name or os.getenv("AI_VIDEO_PROVIDER", "auto")).lower()

        if name == "mock":
            return MockAIVideoProvider()
        elif name in ("google_veo", "veo"):
            return GoogleVeoProvider()
        elif name == "runway":
            return RunwayVideoProvider()
        elif name == "luma":
            return LumaVideoProvider()
        elif name == "kling":
            return KlingVideoProvider()

        # Auto detection: select first configured provider
        for candidate in [GoogleVeoProvider(), RunwayVideoProvider(), LumaVideoProvider(), KlingVideoProvider()]:
            if candidate.is_configured():
                logger.info(f"Auto-selected active AI video provider: [cyan]{candidate.provider_id}[/cyan]")
                return candidate

        # Default fallback to mock provider if none configured
        return MockAIVideoProvider()
