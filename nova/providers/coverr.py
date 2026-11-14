"""Coverr Media Provider (Disabled by Default - Commercial Restriction Notice)."""

import logging
import os
from typing import Optional
from nova.providers.base import BaseMediaProvider, MediaCandidate

logger = logging.getLogger("nova.providers.coverr")


class CoverrProvider(BaseMediaProvider):
    """Coverr provider disabled by default due to commercial API terms & logo watermark requirements."""

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(
            provider_id="coverr",
            name="Coverr",
            enabled=False,  # Explicitly disabled
            key_env="COVERR_API_KEY",
            media_types=["video"],
        )
        self.api_key = api_key or os.getenv("COVERR_API_KEY", "")

    def test_connection(self) -> tuple[bool, str]:
        return (
            False,
            "Coverr is DISABLED by default: Free API Terms of Service prohibit commercial/monetized "
            "video use without enterprise contract and require visible on-screen attribution branding.",
        )

    def _do_search(
        self,
        query: str,
        media_type: str,
        orientation: str,
        min_resolution: str,
        limit: int,
    ) -> list[MediaCandidate]:
        logger.warning("[Coverr] Provider is disabled due to commercial terms restriction.")
        return []
