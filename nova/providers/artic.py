"""Art Institute of Chicago Media Provider (CC0 Public Domain)."""

import logging
from typing import Optional
import requests

from nova.licensing.checker import LicenseComplianceEngine
from nova.providers.base import BaseMediaProvider, MediaCandidate

logger = logging.getLogger("nova.providers.artic")


class ArtInstituteChicagoProvider(BaseMediaProvider):
    """Integrates Art Institute of Chicago Open Access API (Keyless CC0 Public Domain)."""

    def __init__(self):
        super().__init__(
            provider_id="artic",
            name="Art Institute of Chicago",
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
                "https://api.artic.edu/api/v1/artworks/search",
                headers={"User-Agent": "Mozilla/5.0"},
                params={"q": "paris", "limit": 1},
                timeout=5,
            )
            if res.status_code == 200:
                return True, "Art Institute of Chicago API accessible (CC0)"
            elif res.status_code == 403:
                return False, "Art Institute of Chicago blocked by Cloudflare Bot Management (HTTP 403)"
            return False, f"ArtIC HTTP {res.status_code}"
        except Exception as e:
            return False, f"ArtIC connection error: {e}"

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

        url = "https://api.artic.edu/api/v1/artworks/search"
        params = {
            "q": query,
            "query[term][is_public_domain]": "true",
            "fields": "id,title,artist_title,image_id,is_public_domain,date_display",
            "limit": min(max(limit, 3), 15),
        }

        try:
            res = requests.get(url, params=params, timeout=6)
            if res.status_code != 200:
                return []

            data = res.json()
            results: list[MediaCandidate] = []
            for item in data.get("data", []):
                if not item.get("is_public_domain"):
                    continue

                image_id = item.get("image_id")
                if not image_id:
                    continue

                # IIIF image delivery
                download_url = f"https://www.artic.edu/iiif/2/{image_id}/full/1686,/0/default.jpg"
                preview_url = f"https://www.artic.edu/iiif/2/{image_id}/full/843,/0/default.jpg"
                art_id = item.get("id")
                asset_id = f"artic_{art_id}"
                title = item.get("title", f"Art Institute Artwork {art_id}")
                artist = item.get("artist_title") or "Art Institute of Chicago"
                landing_page = f"https://www.artic.edu/artworks/{art_id}"

                ok, proof, _ = self.compliance_engine.evaluate(
                    raw_license="cc0",
                    provider="artic",
                    asset_id=asset_id,
                    landing_page=landing_page,
                    creator=artist,
                    creator_url=landing_page,
                    title=title,
                )
                if not ok or not proof:
                    continue

                results.append(
                    MediaCandidate(
                        provider="artic",
                        asset_id=asset_id,
                        title=title,
                        description=f"{title} ({item.get('date_display', '')}) by {artist}",
                        tags=[w.strip().lower() for w in query.split()],
                        preview_url=preview_url,
                        download_url=download_url,
                        media_type="image",
                        width=1920,
                        height=1080,
                        duration=0.0,
                        author=artist,
                        creator_url=landing_page,
                        landing_page_url=landing_page,
                        license_proof=proof,
                        aspect_ratio=4.0 / 3.0,
                    )
                )

                if len(results) >= limit:
                    break

            return results
        except Exception as e:
            logger.error(f"[ArtIC] Search error: {e}")
            return []
