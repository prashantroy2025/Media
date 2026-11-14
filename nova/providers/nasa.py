"""NASA Image and Video Library Provider (Public Domain)."""

import logging
from typing import Optional
import requests

from nova.licensing.checker import LicenseComplianceEngine
from nova.providers.base import BaseMediaProvider, MediaCandidate

logger = logging.getLogger("nova.providers.nasa")


class NasaProvider(BaseMediaProvider):
    """Integrates NASA Image and Video Library (Keyless, US Government Public Domain)."""

    def __init__(self):
        super().__init__(
            provider_id="nasa_library",
            name="NASA Image and Video Library",
            enabled=True,
            key_env=None,  # Keyless public API
            media_types=["video", "image"],
            requests_per_minute=60,
            cache_ttl_hours=48,
        )
        self.compliance_engine = LicenseComplianceEngine()

    def test_connection(self) -> tuple[bool, str]:
        try:
            res = requests.get(
                "https://images-api.nasa.gov/search",
                params={"q": "moon", "media_type": "image", "page_size": 1},
                timeout=5,
            )
            if res.status_code == 200:
                return True, "NASA Library API accessible (Keyless Public Domain)"
            return False, f"NASA HTTP {res.status_code}: {res.text[:100]}"
        except Exception as e:
            return False, f"NASA connection error: {e}"

    def _do_search(
        self,
        query: str,
        media_type: str,
        orientation: str,
        min_resolution: str,
        limit: int,
    ) -> list[MediaCandidate]:
        candidates: list[MediaCandidate] = []

        # Map to NASA media_type parameter
        target_types = []
        if media_type in ("video", "all"):
            target_types.append("video")
        if media_type in ("image", "all"):
            target_types.append("image")

        for mtype in target_types:
            url = "https://images-api.nasa.gov/search"
            params = {
                "q": query,
                "media_type": mtype,
                "page_size": min(max(limit, 3), 10),
            }
            try:
                res = requests.get(url, params=params, timeout=7)
                if res.status_code != 200:
                    continue

                data = res.json()
                items = data.get("collection", {}).get("items", [])
                for item in items:
                    data_list = item.get("data", [])
                    if not data_list:
                        continue
                    meta = data_list[0]
                    nasa_id = meta.get("nasa_id", "")
                    if not nasa_id:
                        continue

                    title = meta.get("title", query)
                    description = meta.get("description", "")[:400]
                    center = meta.get("center", "NASA")
                    photographer = meta.get("photographer", "") or center
                    tags = meta.get("keywords", [])
                    if isinstance(tags, str):
                        tags = [t.strip().lower() for t in tags.split(",")]

                    landing_page = f"https://images.nasa.gov/details/{nasa_id}"

                    # Find preview and asset download URL
                    preview_url = ""
                    for link in item.get("links", []):
                        if link.get("rel") == "preview" or link.get("render") == "image":
                            preview_url = link.get("href", "")
                            break

                    download_url = ""
                    if mtype == "image":
                        # For images, preview can be used or large if accessible
                        download_url = preview_url.replace("~thumb.jpg", "~large.jpg").replace("~thumb.jpg", "~orig.jpg")
                        if not download_url:
                            download_url = preview_url
                    elif mtype == "video":
                        # Fetch video asset manifest
                        manifest_url = item.get("href")
                        if manifest_url:
                            try:
                                mres = requests.get(manifest_url, timeout=4)
                                if mres.status_code == 200:
                                    files = mres.json()
                                    # Pick ~medium.mp4, ~orig.mp4 or ~large.mp4
                                    for f in files:
                                        if f.endswith("~medium.mp4") or f.endswith(".mp4"):
                                            download_url = f
                                            if "~orig.mp4" in f or "~large.mp4" in f:
                                                break
                            except Exception:
                                pass

                    if not download_url:
                        continue

                    asset_id = f"nasa_{mtype}_{nasa_id}"
                    ok, proof, _ = self.compliance_engine.evaluate(
                        raw_license="pd-usgov",
                        provider="nasa_library",
                        asset_id=asset_id,
                        landing_page=landing_page,
                        creator=f"NASA / {photographer}",
                        creator_url="https://www.nasa.gov",
                    )
                    if not ok or not proof:
                        continue

                    candidates.append(
                        MediaCandidate(
                            provider="nasa_library",
                            asset_id=asset_id,
                            title=title,
                            description=description,
                            tags=tags,
                            preview_url=preview_url or download_url,
                            download_url=download_url,
                            media_type=mtype,
                            width=1920,
                            height=1080,
                            duration=20.0 if mtype == "video" else 0.0,
                            author=f"NASA / {photographer}",
                            creator_url="https://www.nasa.gov",
                            landing_page_url=landing_page,
                            license_proof=proof,
                            aspect_ratio=16.0 / 9.0,
                        )
                    )
                    if len(candidates) >= limit:
                        break
            except Exception as e:
                logger.error(f"[NASA] Search exception for {mtype}: {e}")

        return candidates[:limit]
