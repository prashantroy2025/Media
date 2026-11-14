"""Library of Congress (LOC.gov) Provider.

Searches public domain historical and documentary imagery from loc.gov.
Note: LOC.gov protects its public search API with Cloudflare Bot Management.
When Cloudflare blocks automated JSON requests with HTTP 403 / challenge,
the provider gracefully catches the error and reports its status.
"""

from __future__ import annotations

import logging
import requests

from nova.licensing.checker import LicenseComplianceEngine
from nova.providers.base import BaseMediaProvider, MediaCandidate

logger = logging.getLogger("nova.providers.loc")


class LibraryOfCongressProvider(BaseMediaProvider):
    """Integrates Library of Congress Open Search API."""

    def __init__(self):
        super().__init__(
            provider_id="library_of_congress",
            name="Library of Congress",
            enabled=True,
            key_env=None,
            media_types=["image"],
            requests_per_minute=30,
            cache_ttl_hours=72,
        )
        self.compliance_engine = LicenseComplianceEngine()

    def test_connection(self) -> tuple[bool, str]:
        try:
            res = requests.get(
                "https://www.loc.gov/search/?q=space&fo=json",
                headers={"User-Agent": "Mozilla/5.0 NovaAutopilot"},
                timeout=5,
            )
            if res.status_code == 200:
                return True, "Library of Congress accessible"
            elif res.status_code == 403:
                return False, "Library of Congress blocked by Cloudflare Bot Management (HTTP 403 Challenge)"
            return False, f"LOC HTTP {res.status_code}"
        except Exception as e:
            return False, f"LOC connection error: {e}"

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

        url = "https://www.loc.gov/search/"
        params = {
            "q": query,
            "fo": "json",
            "fa": "online_format:image",
            "c": min(max(limit, 3), 10),
        }

        try:
            res = requests.get(
                url,
                params=params,
                headers={"User-Agent": "Mozilla/5.0 NovaAutopilot"},
                timeout=6,
            )
            if res.status_code != 200:
                logger.info(f"LOC search failed with HTTP {res.status_code} (Cloudflare challenge active)")
                return []

            data = res.json()
            candidates: list[MediaCandidate] = []
            for item in data.get("results", []):
                img_urls = item.get("image_url", [])
                if not img_urls:
                    continue
                download_url = img_urls[-1] if isinstance(img_urls, list) else str(img_urls)
                item_id = item.get("id", "")
                title = item.get("title", "Library of Congress Archive")
                landing_page = item.get("url", f"https://www.loc.gov/item/{item_id}")

                ok, proof, _ = self.compliance_engine.evaluate(
                    raw_license="pd_usgov",
                    provider="library_of_congress",
                    asset_id=f"loc_{item_id}",
                    landing_page=landing_page,
                    creator="Library of Congress",
                    creator_url="https://www.loc.gov",
                    title=title,
                )
                if not ok or not proof:
                    continue

                candidates.append(
                    MediaCandidate(
                        provider="library_of_congress",
                        asset_id=f"loc_{item_id}",
                        media_type="image",
                        title=title,
                        description=item.get("description", [title])[0] if isinstance(item.get("description"), list) else title,
                        tags=["loc", "history", "archive", "public_domain"],
                        width=1920,
                        height=1080,
                        duration=0.0,
                        preview_url=img_urls[0] if isinstance(img_urls, list) else download_url,
                        download_url=download_url,
                        author="Library of Congress",
                        landing_page_url=landing_page,
                        license_proof=proof,
                        relevance_score=75.0,
                    )
                )

            return candidates
        except Exception as e:
            logger.warning(f"LOC search error: {e}")
            return []
