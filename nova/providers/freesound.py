"""Freesound Audio Provider (CC0 Sound Effects, Optional Key)."""

import logging
import os
from typing import Optional
import requests

from nova.licensing.checker import LicenseComplianceEngine
from nova.providers.base import BaseMediaProvider, MediaCandidate

logger = logging.getLogger("nova.providers.freesound")


class FreesoundProvider(BaseMediaProvider):
    """Integrates Freesound API filtered for CC0 sound effects. Requires free key."""

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(
            provider_id="freesound",
            name="Freesound",
            enabled=True,
            key_env="FREESOUND_API_KEY",
            media_types=["audio"],
            requests_per_minute=60,
            cache_ttl_hours=72,
        )
        self.api_key = api_key or os.getenv("FREESOUND_API_KEY", "")
        self.compliance_engine = LicenseComplianceEngine()

    def test_connection(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "Missing FREESOUND_API_KEY (free key from https://freesound.org/help/developers/)"
        try:
            res = requests.get(
                "https://freesound.org/apiv2/search/text/",
                params={"token": self.api_key, "query": "whoosh", "page_size": 1},
                timeout=5,
            )
            if res.status_code == 200:
                return True, "Freesound API authenticated successfully"
            return False, f"Freesound HTTP {res.status_code}"
        except Exception as e:
            return False, f"Freesound connection error: {e}"

    def _do_search(
        self,
        query: str,
        media_type: str,
        orientation: str,
        min_resolution: str,
        limit: int,
    ) -> list[MediaCandidate]:
        if not self.api_key or media_type not in ("audio", "all"):
            return []

        url = "https://freesound.org/apiv2/search/text/"
        params = {
            "token": self.api_key,
            "query": query,
            "filter": 'license:"Creative Commons 0"',
            "fields": "id,name,tags,description,previews,username,url,duration",
            "page_size": min(max(limit, 3), 15),
        }

        try:
            res = requests.get(url, params=params, timeout=6)
            if res.status_code != 200:
                return []

            data = res.json()
            results: list[MediaCandidate] = []
            for hit in data.get("results", []):
                previews = hit.get("previews", {})
                audio_url = previews.get("preview-hq-mp3") or previews.get("preview-lq-mp3")
                if not audio_url:
                    continue

                fs_id = hit.get("id")
                asset_id = f"fs_{fs_id}"
                title = hit.get("name", query)
                username = hit.get("username", "Freesound Contributor")
                landing_page = hit.get("url", f"https://freesound.org/people/{username}/sounds/{fs_id}/")

                ok, proof, _ = self.compliance_engine.evaluate(
                    raw_license="cc0",
                    provider="freesound",
                    asset_id=asset_id,
                    landing_page=landing_page,
                    creator=username,
                    creator_url=f"https://freesound.org/people/{username}/",
                    title=title,
                )
                if not ok or not proof:
                    continue

                results.append(
                    MediaCandidate(
                        provider="freesound",
                        asset_id=asset_id,
                        title=title,
                        description=str(hit.get("description", ""))[:200],
                        tags=[t.lower() for t in hit.get("tags", [])],
                        preview_url=audio_url,
                        download_url=audio_url,
                        media_type="audio",
                        width=0,
                        height=0,
                        duration=float(hit.get("duration", 0)),
                        author=username,
                        creator_url=f"https://freesound.org/people/{username}/",
                        landing_page_url=landing_page,
                        license_proof=proof,
                        aspect_ratio=0.0,
                    )
                )

                if len(results) >= limit:
                    break

            return results
        except Exception as e:
            logger.error(f"[Freesound] Search error: {e}")
            return []
