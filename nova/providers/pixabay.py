"""Pixabay Media Provider (Video & Image)."""

import logging
import os
from typing import Optional
import requests

from nova.licensing.checker import LicenseComplianceEngine
from nova.licensing.models import LicenseProof
from nova.providers.base import BaseMediaProvider, MediaCandidate

logger = logging.getLogger("nova.providers.pixabay")


class PixabayProvider(BaseMediaProvider):
    """Integrates Pixabay Video and Image APIs under Pixabay Content License."""

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(
            provider_id="pixabay",
            name="Pixabay",
            enabled=True,
            key_env="PIXABAY_API_KEY",
            media_types=["video", "image"],
            requests_per_minute=90,
            cache_ttl_hours=24,
        )
        self.api_key = api_key or os.getenv("PIXABAY_API_KEY", "")
        self.compliance_engine = LicenseComplianceEngine()

    def test_connection(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "Missing PIXABAY_API_KEY"
        try:
            res = requests.get(
                "https://pixabay.com/api/",
                params={"key": self.api_key, "q": "nature", "per_page": 3},
                timeout=5,
            )
            if res.status_code == 200:
                return True, "Pixabay API authenticated successfully"
            return False, f"Pixabay HTTP {res.status_code}: {res.text[:100]}"
        except Exception as e:
            return False, f"Pixabay connection error: {e}"

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
        url = "https://pixabay.com/api/videos/"
        params = {
            "key": self.api_key,
            "q": query,
            "video_type": "all",
            "per_page": min(max(limit, 3), 20),
        }
        try:
            res = requests.get(url, params=params, timeout=6)
            if res.status_code != 200:
                logger.warning(f"[Pixabay] Video search error {res.status_code}: {res.text[:100]}")
                return []

            data = res.json()
            results: list[MediaCandidate] = []
            for hit in data.get("hits", []):
                videos = hit.get("videos", {})
                chosen = (
                    videos.get("large")
                    or videos.get("medium")
                    or videos.get("small")
                    or {}
                )
                download_url = chosen.get("url")
                if not download_url:
                    continue

                asset_id = f"pixabay_v_{hit.get('id')}"
                landing_page = hit.get("pageURL") or f"https://pixabay.com/videos/id-{hit.get('id')}/"
                creator = hit.get("user") or "Pixabay Contributor"
                creator_url = f"https://pixabay.com/users/{hit.get('user')}-{hit.get('user_id')}/"

                ok, proof, _ = self.compliance_engine.evaluate(
                    raw_license="pixabay",
                    provider="pixabay",
                    asset_id=asset_id,
                    landing_page=landing_page,
                    creator=creator,
                    creator_url=creator_url,
                )
                if not ok or not proof:
                    continue

                tags = [t.strip().lower() for t in hit.get("tags", "").split(",") if t.strip()]
                preview_url = hit.get("picture_id", "")
                if preview_url and not preview_url.startswith("http"):
                    preview_url = f"https://i.vimeocdn.com/video/{preview_url}_640x360.jpg"

                results.append(
                    MediaCandidate(
                        provider="pixabay",
                        asset_id=asset_id,
                        title=hit.get("tags", query),
                        description=f"Pixabay video {hit.get('id')} ({tags})",
                        tags=tags,
                        preview_url=preview_url or download_url,
                        download_url=download_url,
                        media_type="video",
                        width=chosen.get("width", 1920),
                        height=chosen.get("height", 1080),
                        duration=float(hit.get("duration", 0)),
                        author=creator,
                        creator_url=creator_url,
                        landing_page_url=landing_page,
                        license_proof=proof,
                        aspect_ratio=(chosen.get("width", 16) / max(chosen.get("height", 9), 1)),
                    )
                )
            return results
        except Exception as e:
            logger.error(f"[Pixabay] Video search exception: {e}")
            return []

    def _search_images(self, query: str, limit: int) -> list[MediaCandidate]:
        url = "https://pixabay.com/api/"
        params = {
            "key": self.api_key,
            "q": query,
            "image_type": "photo",
            "per_page": min(max(limit, 3), 20),
        }
        try:
            res = requests.get(url, params=params, timeout=6)
            if res.status_code != 200:
                logger.warning(f"[Pixabay] Image search error {res.status_code}: {res.text[:100]}")
                return []

            data = res.json()
            results: list[MediaCandidate] = []
            for hit in data.get("hits", []):
                download_url = hit.get("largeImageURL") or hit.get("webformatURL")
                if not download_url:
                    continue

                asset_id = f"pixabay_i_{hit.get('id')}"
                landing_page = hit.get("pageURL") or f"https://pixabay.com/photos/id-{hit.get('id')}/"
                creator = hit.get("user") or "Pixabay Contributor"
                creator_url = f"https://pixabay.com/users/{hit.get('user')}-{hit.get('user_id')}/"

                ok, proof, _ = self.compliance_engine.evaluate(
                    raw_license="pixabay",
                    provider="pixabay",
                    asset_id=asset_id,
                    landing_page=landing_page,
                    creator=creator,
                    creator_url=creator_url,
                )
                if not ok or not proof:
                    continue

                tags = [t.strip().lower() for t in hit.get("tags", "").split(",") if t.strip()]
                w = hit.get("imageWidth", 1920)
                h = hit.get("imageHeight", 1080)

                results.append(
                    MediaCandidate(
                        provider="pixabay",
                        asset_id=asset_id,
                        title=hit.get("tags", query),
                        description=f"Pixabay photo {hit.get('id')} ({tags})",
                        tags=tags,
                        preview_url=hit.get("previewURL") or download_url,
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
            logger.error(f"[Pixabay] Image search exception: {e}")
            return []
