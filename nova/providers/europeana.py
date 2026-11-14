"""Europeana Cultural Heritage Provider (CC0, PDM, CC-BY with Free Key)."""

import logging
import os
from typing import Optional
import requests

from nova.licensing.checker import LicenseComplianceEngine
from nova.providers.base import BaseMediaProvider, MediaCandidate

logger = logging.getLogger("nova.providers.europeana")


class EuropeanaProvider(BaseMediaProvider):
    """Integrates Europeana REST API. Requires free developer key from Europeana."""

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(
            provider_id="europeana",
            name="Europeana",
            enabled=True,
            key_env="EUROPEANA_API_KEY",
            media_types=["image"],
            requests_per_minute=50,
            cache_ttl_hours=72,
        )
        self.api_key = api_key or os.getenv("EUROPEANA_API_KEY", "")
        self.compliance_engine = LicenseComplianceEngine()

    def test_connection(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "Missing EUROPEANA_API_KEY (free key from https://pro.europeana.eu/page/get-api)"
        try:
            res = requests.get(
                "https://api.europeana.eu/record/v2/search.json",
                params={"wskey": self.api_key, "query": "renaissance", "rows": 1, "reusability": "open"},
                timeout=5,
            )
            if res.status_code == 200:
                return True, "Europeana API authenticated successfully"
            return False, f"Europeana HTTP {res.status_code}"
        except Exception as e:
            return False, f"Europeana connection error: {e}"

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

        url = "https://api.europeana.eu/record/v2/search.json"
        params = {
            "wskey": self.api_key,
            "query": query,
            "reusability": "open",
            "media": "true",
            "rows": min(max(limit, 3), 15),
        }

        try:
            res = requests.get(url, params=params, timeout=6)
            if res.status_code != 200:
                return []

            data = res.json()
            items = data.get("items", [])
            results: list[MediaCandidate] = []

            for item in items:
                edmPreview = item.get("edmPreview", [])
                img_url = edmPreview[0] if edmPreview else None
                if not img_url:
                    continue

                item_id = item.get("id", "").replace("/", "_")
                asset_id = f"europeana_{item_id}"
                title_list = item.get("title", [query])
                title = title_list[0] if title_list else query
                rights = item.get("rights", [""])[0]
                landing_page = item.get("guid", f"https://www.europeana.eu/item{item.get('id', '')}")

                ok, proof, _ = self.compliance_engine.evaluate(
                    raw_license=rights,
                    provider="europeana",
                    asset_id=asset_id,
                    landing_page=landing_page,
                    creator="Europeana Contributor",
                    creator_url=landing_page,
                    title=title,
                    raw_license_url=rights,
                )
                if not ok or not proof:
                    continue

                results.append(
                    MediaCandidate(
                        provider="europeana",
                        asset_id=asset_id,
                        title=title,
                        description=f"Europeana item {title}",
                        tags=[w.strip().lower() for w in query.split()],
                        preview_url=img_url,
                        download_url=img_url,
                        media_type="image",
                        width=1920,
                        height=1080,
                        duration=0.0,
                        author="Europeana Contributor",
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
            logger.error(f"[Europeana] Search error: {e}")
            return []
