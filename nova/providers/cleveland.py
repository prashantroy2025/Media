"""Cleveland Museum of Art Open Access Provider (CC0 Public Domain)."""

import logging
from typing import Optional
import requests

from nova.licensing.checker import LicenseComplianceEngine
from nova.providers.base import BaseMediaProvider, MediaCandidate

logger = logging.getLogger("nova.providers.cleveland")


class ClevelandMuseumProvider(BaseMediaProvider):
    """Integrates Cleveland Museum of Art Open Access API (Keyless CC0 Public Domain)."""

    def __init__(self):
        super().__init__(
            provider_id="cleveland_museum",
            name="Cleveland Museum of Art",
            enabled=True,
            key_env=None,
            media_types=["image"],
            requests_per_minute=60,
            cache_ttl_hours=72,
        )
        self.compliance_engine = LicenseComplianceEngine()

    def test_connection(self) -> tuple[bool, str]:
        try:
            res = requests.get(
                "https://openaccess-api.clevelandart.org/api/artworks/",
                params={"q": "gold", "cc0": "1", "has_image": "1", "limit": 1},
                timeout=5,
            )
            if res.status_code == 200:
                return True, "Cleveland Museum of Art API accessible (CC0)"
            return False, f"Cleveland HTTP {res.status_code}"
        except Exception as e:
            return False, f"Cleveland connection error: {e}"

    def _do_search(
        self,
        query: str,
        media_type: str,
        orientation: str,
        min_resolution: str,
        limit: int,
    ) -> list[MediaCandidate]:
        if media_type not in ("image", "all"):
            return []

        url = "https://openaccess-api.clevelandart.org/api/artworks/"
        params = {
            "q": query,
            "cc0": "1",
            "has_image": "1",
            "limit": min(max(limit, 3), 15),
        }

        try:
            res = requests.get(url, params=params, timeout=6)
            if res.status_code != 200:
                return []

            data = res.json()
            results: list[MediaCandidate] = []
            for item in data.get("data", []):
                images = item.get("images", {})
                web_img = images.get("web", {})
                download_url = web_img.get("url")
                if not download_url:
                    continue

                cma_id = item.get("id")
                asset_id = f"cma_{cma_id}"
                title = item.get("title", f"Cleveland Art {cma_id}")
                creators = item.get("creators", [])
                artist = creators[0].get("description", "Cleveland Museum of Art") if creators else "Cleveland Museum of Art"
                landing_page = item.get("url", f"https://www.clevelandart.org/art/{cma_id}")

                ok, proof, _ = self.compliance_engine.evaluate(
                    raw_license="cc0",
                    provider="cleveland_museum",
                    asset_id=asset_id,
                    landing_page=landing_page,
                    creator=artist,
                    creator_url=landing_page,
                    title=title,
                )
                if not ok or not proof:
                    continue

                w = int(web_img.get("width", 1920) or 1920)
                h = int(web_img.get("height", 1080) or 1080)
                preview_url = images.get("print", {}).get("url") or download_url

                results.append(
                    MediaCandidate(
                        provider="cleveland_museum",
                        asset_id=asset_id,
                        title=title,
                        description=f"{title} ({item.get('creation_date', '')}) - {artist}",
                        tags=[w.strip().lower() for w in query.split()],
                        preview_url=preview_url,
                        download_url=download_url,
                        media_type="image",
                        width=w,
                        height=h,
                        duration=0.0,
                        author=artist,
                        creator_url=landing_page,
                        landing_page_url=landing_page,
                        license_proof=proof,
                        aspect_ratio=(w / max(h, 1)),
                    )
                )

                if len(results) >= limit:
                    break

            return results
        except Exception as e:
            logger.error(f"[Cleveland] Search error: {e}")
            return []
