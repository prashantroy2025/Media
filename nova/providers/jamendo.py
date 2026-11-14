"""Jamendo Audio Provider (Disabled by Default - Content ID & Non-Commercial Notice)."""

import logging
import os
from typing import Optional
from nova.providers.base import BaseMediaProvider, MediaCandidate

logger = logging.getLogger("nova.providers.jamendo")


class JamendoProvider(BaseMediaProvider):
    """Jamendo provider disabled by default due to non-commercial developer terms & YouTube Content ID risk."""

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(
            provider_id="jamendo",
            name="Jamendo",
            enabled=False,  # Explicitly disabled
            key_env="JAMENDO_CLIENT_ID",
            media_types=["audio"],
        )
        self.api_key = api_key or os.getenv("JAMENDO_CLIENT_ID", "")

    def test_connection(self) -> tuple[bool, str]:
        return (
            False,
            "Jamendo is DISABLED by default: Free Developer API terms restrict usage strictly to non-commercial "
            "purposes, and free catalog tracks trigger automated YouTube Content ID copyright strikes/claims.",
        )

    def _do_search(
        self,
        query: str,
        media_type: str,
        orientation: str,
        min_resolution: str,
        limit: int,
    ) -> list[MediaCandidate]:
        logger.warning("[Jamendo] Provider is disabled due to non-commercial terms and Content ID risks.")
        return []
