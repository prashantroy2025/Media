"""Smithsonian Open Access Provider (CC0, Optional Key via api.data.gov)."""

import logging
import os
from typing import Optional
import requests

from nova.licensing.checker import LicenseComplianceEngine
from nova.providers.base import BaseMediaProvider, MediaCandidate

logger = logging.getLogger("nova.providers.smithsonian")


class SmithsonianProvider(BaseMediaProvider):
    """Integrates Smithsonian Open Access API (CC0). Requires free API key from api.data.gov."""

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(
            provider_id="smithsonian",
            name="Smithsonian Open Access",
            enabled=True,
            key_env="SMITHSONIAN_API_KEY",
            media_types=["image"],
            requests_per_minute=50,
            cache_ttl_hours=72,
        )
        self.api_key = api_key or os.getenv("SMITHSONIAN_API_KEY", "")
        self.compliance_engine = LicenseComplianceEngine()

    def test_connection(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "Missing SMITHSONIAN_API_KEY (free key from https://api.data.gov/signup/)"
        try:
            res = requests.get(
                "https://api.si.edu/openaccess/api/v1.0/search",
                params={"api_key": self.api_key, "q": "apollo", "rows": 1},
                timeout=5,
            )
            if res.status_code == 200:
                return True, "Smithsonian API authenticated successfully (CC0)"
            return False, f"Smithsonian HTTP {res.status_code}"
        except Exception as e:
            return False, f"Smithsonian connection error: {e}"

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

        url = "https://api.si.edu/openaccess/api/v1.0/search"
        params = {
            "api_key": self.api_key,
            "q": query,
            "rows": min(max(limit, 3), 15),
        }

        try:
            res = requests.get(url, params=params, timeout=6)
            if res.status_code != 200:
                return []

            data = res.json()
            rows = data.get("response", {}).get("rows", [])
            results: list[MediaCandidate] = []

            for row in rows:
                content = row.get("content", {})
                descriptive = content.get("descriptiveNonRepeating", {})
                online_media = descriptive.get("online_media", {})
                media_list = online_media.get("media", [])
                if not media_list:
                    continue

                chosen_img = None
                for m in media_list:
                    if m.get("type") == "Images":
                        chosen_img = m.get("content")
                        break
                if not chosen_img:
                    continue

                si_id = row.get("id")
                asset_id = f"si_{si_id}"
                title = row.get("title", query)
                creator = descriptive.get("record_link", "Smithsonian Institution")
                landing_page = descriptive.get("record_link", f"https://www.si.edu/object/{si_id}")

                ok, proof, _ = self.compliance_engine.evaluate(
                    raw_license="cc0",
                    provider="smithsonian",
                    asset_id=asset_id,
                    landing_page=landing_page,
                    creator="Smithsonian Institution",
                    creator_url="https://www.si.edu",
                    title=title,
                )
                if not ok or not proof:
                    continue

                results.append(
                    MediaCandidate(
                        provider="smithsonian",
                        asset_id=asset_id,
                        title=title,
                        description=f"Smithsonian artifact: {title}",
                        tags=[w.strip().lower() for w in query.split()],
                        preview_url=chosen_img,
                        download_url=chosen_img,
                        media_type="image",
                        width=1920,
                        height=1080,
                        duration=0.0,
                        author="Smithsonian Institution",
                        creator_url="https://www.si.edu",
                        landing_page_url=landing_page,
                        license_proof=proof,
                        aspect_ratio=4.0 / 3.0,
                    )
                )

                if len(results) >= limit:
                    break

            return results
        except Exception as e:
            logger.error(f"[Smithsonian] Search error: {e}")
            return []
