"""Pexels Media Provider (Video & Image)."""

import logging
import os
from typing import Optional
import requests

from nova.licensing.checker import LicenseComplianceEngine
from nova.providers.base import BaseMediaProvider, MediaCandidate

logger = logging.getLogger("nova.providers.pexels")


class PexelsProvider(BaseMediaProvider):
    """Integrates Pexels Video and Image APIs under Pexels License."""

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(
            provider_id="pexels",
            name="Pexels",
            enabled=True,
            key_env="PEXELS_API_KEY",
            media_types=["video", "image"],
            requests_per_minute=50,
            cache_ttl_hours=24,
        )
        self.api_key = api_key or os.getenv("PEXELS_API_KEY", "")
        self.compliance_engine = LicenseComplianceEngine()

    def test_connection(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "Missing PEXELS_API_KEY (optional free key from https://www.pexels.com/api/)"
        try:
            headers = {"Authorization": self.api_key}
            res = requests.get(
                "https://api.pexels.com/v1/curated",
                headers=headers,
                params={"per_page": 1},
                timeout=5,
            )
            if res.status_code == 200:
                return True, "Pexels API authenticated successfully"
            return False, f"Pexels HTTP {res.status_code}: {res.text[:100]}"
        except Exception as e:
            return False, f"Pexels connection error: {e}"

    def _do_search(
        self,
        query: str,
        media_type: str,
        orientation: str,
        min_resolution: str,
        limit: int,
    ) -> list[MediaCandidate]:
        if not self.api_key:
            return []

        candidates: list[MediaCandidate] = []
        if media_type in ("video", "all"):
            candidates.extend(self._search_videos(query, limit))

        if media_type in ("image", "all") and len(candidates) < limit:
            remaining = limit - len(candidates)
            candidates.extend(self._search_images(query, remaining))

        return candidates[:limit]

    def _search_videos(self, query: str, limit: int) -> list[MediaCandidate]:
        headers = {"Authorization": self.api_key}
        params = {"query": query, "per_page": min(max(limit, 3), 15)}
        try:
            res = requests.get("https://api.pexels.com/videos/search", headers=headers, params=params, timeout=6)
            if res.status_code != 200:
                logger.warning(f"[Pexels] Video search HTTP {res.status_code}")
                return []

            data = res.json()
            results: list[MediaCandidate] = []
            for hit in data.get("videos", []):
                files = hit.get("video_files", [])
                chosen = None
                for vf in files:
                    if vf.get("quality") == "hd" or vf.get("width", 0) >= 1280:
                        chosen = vf
                        break
                if not chosen and files:
                    chosen = files[0]

                if not chosen or not chosen.get("link"):
                    continue

                asset_id = f"pexels_v_{hit.get('id')}"
                landing_page = hit.get("url", f"https://www.pexels.com/video/{hit.get('id')}/")
                creator = hit.get("user", {}).get("name", "Pexels Contributor")
                creator_url = hit.get("user", {}).get("url", "")

                ok, proof, _ = self.compliance_engine.evaluate(
                    raw_license="pexels",
                    provider="pexels",
                    asset_id=asset_id,
                    landing_page=landing_page,
                    creator=creator,
                    creator_url=creator_url,
                )
                if not ok or not proof:
                    continue

                w = chosen.get("width", 1920)
                h = chosen.get("height", 1080)
                results.append(
                    MediaCandidate(
                        provider="pexels",
                        asset_id=asset_id,
                        title=f"Pexels Video {hit.get('id')}",
                        description=f"Pexels footage by {creator}",
                        tags=[w.strip().lower() for w in query.split()],
                        preview_url=hit.get("image", chosen.get("link")),
                        download_url=chosen.get("link"),
                        media_type="video",
                        width=w,
                        height=h,
                        duration=float(hit.get("duration", 0)),
                        author=creator,
                        creator_url=creator_url,
                        landing_page_url=landing_page,
                        license_proof=proof,
                        aspect_ratio=(w / max(h, 1)),
                    )
                )
            return results
        except Exception as e:
            logger.error(f"[Pexels] Video search exception: {e}")
            return []

    def _search_images(self, query: str, limit: int) -> list[MediaCandidate]:
        headers = {"Authorization": self.api_key}
        params = {"query": query, "per_page": min(max(limit, 3), 15)}
        try:
            res = requests.get("https://api.pexels.com/v1/search", headers=headers, params=params, timeout=6)
            if res.status_code != 200:
                logger.warning(f"[Pexels] Image search HTTP {res.status_code}")
                return []

            data = res.json()
            results: list[MediaCandidate] = []
            for hit in data.get("photos", []):
                src = hit.get("src", {})
                download_url = src.get("large2x") or src.get("large") or src.get("original")
                if not download_url:
                    continue

                asset_id = f"pexels_i_{hit.get('id')}"
                landing_page = hit.get("url", f"https://www.pexels.com/photo/{hit.get('id')}/")
                creator = hit.get("photographer", "Pexels Photographer")
                creator_url = hit.get("photographer_url", "")

                ok, proof, _ = self.compliance_engine.evaluate(
                    raw_license="pexels",
                    provider="pexels",
                    asset_id=asset_id,
                    landing_page=landing_page,
                    creator=creator,
                    creator_url=creator_url,
                )
                if not ok or not proof:
                    continue

                w = hit.get("width", 1920)
                h = hit.get("height", 1080)
                results.append(
                    MediaCandidate(
                        provider="pexels",
                        asset_id=asset_id,
                        title=hit.get("alt", f"Pexels Photo {hit.get('id')}"),
                        description=f"Pexels photo by {creator}: {hit.get('alt', '')}",
                        tags=[w.strip().lower() for w in query.split()],
                        preview_url=src.get("medium", download_url),
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
            return results
        except Exception as e:
            logger.error(f"[Pexels] Image search exception: {e}")
            return []
