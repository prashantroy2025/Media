"""Unsplash Media Provider (Unsplash License, Optional Key)."""

import logging
import os
from typing import Optional
import requests

from nova.licensing.checker import LicenseComplianceEngine
from nova.providers.base import BaseMediaProvider, MediaCandidate

logger = logging.getLogger("nova.providers.unsplash")


class UnsplashProvider(BaseMediaProvider):
    """Integrates Unsplash API. Requires free developer key (UNSPLASH_ACCESS_KEY)."""

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(
            provider_id="unsplash",
            name="Unsplash",
            enabled=True,
            key_env="UNSPLASH_ACCESS_KEY",
            media_types=["image"],
            requests_per_minute=50,
            cache_ttl_hours=24,
        )
        self.api_key = api_key or os.getenv("UNSPLASH_ACCESS_KEY", "")
        self.compliance_engine = LicenseComplianceEngine()

    def test_connection(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "Missing UNSPLASH_ACCESS_KEY (free developer key from https://unsplash.com/developers)"
        try:
            headers = {"Authorization": f"Client-ID {self.api_key}"}
            res = requests.get(
                "https://api.unsplash.com/photos/random",
                headers=headers,
                timeout=5,
            )
            if res.status_code == 200:
                return True, "Unsplash API authenticated successfully"
            return False, f"Unsplash HTTP {res.status_code}"
        except Exception as e:
            return False, f"Unsplash connection error: {e}"

    def _do_search(
        self,
        query: str,
        media_type: str,
        orientation: str,
        min_resolution: str,
        limit: int,
    ) -> list[MediaCandidate]:
        if not self.api_key or media_type not in ("image", "all"):
            return []

        headers = {"Authorization": f"Client-ID {self.api_key}"}
        url = "https://api.unsplash.com/search/photos"
        params = {
            "query": query,
            "per_page": min(max(limit, 3), 15),
        }

        try:
            res = requests.get(url, headers=headers, params=params, timeout=6)
            if res.status_code != 200:
                return []

            data = res.json()
            results: list[MediaCandidate] = []
            for hit in data.get("results", []):
                urls = hit.get("urls", {})
                download_url = urls.get("regular") or urls.get("full")
                if not download_url:
                    continue

                u_id = hit.get("id")
                asset_id = f"unsplash_{u_id}"
                user = hit.get("user", {})
                creator = user.get("name", "Unsplash Photographer")
                creator_url = user.get("links", {}).get("html", "")
                landing_page = hit.get("links", {}).get("html", f"https://unsplash.com/photos/{u_id}")

                ok, proof, _ = self.compliance_engine.evaluate(
                    raw_license="unsplash",
                    provider="unsplash",
                    asset_id=asset_id,
                    landing_page=landing_page,
                    creator=creator,
                    creator_url=creator_url,
                    title=hit.get("description", query),
                )
                if not ok or not proof:
                    continue

                w = hit.get("width", 1920)
                h = hit.get("height", 1080)
                results.append(
                    MediaCandidate(
                        provider="unsplash",
                        asset_id=asset_id,
                        title=hit.get("alt_description") or hit.get("description") or query,
                        description=f"Unsplash photo by {creator}",
                        tags=[w.strip().lower() for w in query.split()],
                        preview_url=urls.get("small", download_url),
                        download_url=download_url,
                        media_type="image",
                        width=w,
                        height=h,
                        duration=0.0,
                        author=creator,
                        creator_url=creator_url,
                        landing_page_url=landing_page,
                        license_proof=proof,
                        aspect_ratio=(w / max(h, 1)),
                    )
                )

                if len(results) >= limit:
                    break

            return results
        except Exception as e:
            logger.error(f"[Unsplash] Search error: {e}")
            return []
