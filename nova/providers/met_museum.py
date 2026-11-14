"""The Metropolitan Museum of Art Open Access Provider (CC0 Public Domain)."""

import logging
from typing import Optional
import requests

from nova.licensing.checker import LicenseComplianceEngine
from nova.providers.base import BaseMediaProvider, MediaCandidate

logger = logging.getLogger("nova.providers.met_museum")


class MetMuseumProvider(BaseMediaProvider):
    """Integrates The Metropolitan Museum of Art Open Access API (Keyless CC0)."""

    def __init__(self):
        super().__init__(
            provider_id="met_museum",
            name="The Metropolitan Museum of Art",
            enabled=True,
            key_env=None,
            media_types=["image"],
            requests_per_minute=50,
            cache_ttl_hours=72,
        )
        self.compliance_engine = LicenseComplianceEngine()

    def test_connection(self) -> tuple[bool, str]:
        try:
            res = requests.get(
                "https://collectionapi.metmuseum.org/public/collection/v1.1/search",
                params={"q": "sun", "hasImages": "true", "limit": 1},
                timeout=5,
            )
            if res.status_code == 200:
                return True, "Met Museum Collection API accessible (v1.1 Elastic CC0)"
            return False, f"Met Museum HTTP {res.status_code}"
        except Exception as e:
            return False, f"Met Museum connection error: {e}"

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

        search_url = "https://collectionapi.metmuseum.org/public/collection/v1.1/search"
        try:
            res = requests.get(search_url, params={"q": query, "hasImages": "true", "limit": min(limit * 2, 10)}, timeout=6)
            if res.status_code != 200:
                return []

            data = res.json()
            object_ids = data.get("objectIDs", []) or []
            results: list[MediaCandidate] = []

            # Inspect first few objects
            for obj_id in object_ids[: min(limit * 2, 10)]:
                try:
                    obj_res = requests.get(
                        f"https://collectionapi.metmuseum.org/public/collection/v1/objects/{obj_id}",
                        timeout=4,
                    )
                    if obj_res.status_code != 200:
                        continue
                    obj = obj_res.json()

                    if not obj.get("isPublicDomain"):
                        continue

                    img_url = obj.get("primaryImage") or obj.get("primaryImageSmall")
                    if not img_url:
                        continue

                    title = obj.get("title", f"Met Museum Artifact {obj_id}")
                    artist = obj.get("artistDisplayName") or "The Metropolitan Museum of Art"
                    landing_page = obj.get("objectURL") or f"https://www.metmuseum.org/art/collection/search/{obj_id}"
                    asset_id = f"met_{obj_id}"

                    ok, proof, _ = self.compliance_engine.evaluate(
                        raw_license="cc0",
                        provider="met_museum",
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
                            provider="met_museum",
                            asset_id=asset_id,
                            title=title,
                            description=f"{title} ({obj.get('objectDate', '')}) - {artist}",
                            tags=[w.strip().lower() for w in query.split()],
                            preview_url=obj.get("primaryImageSmall") or img_url,
                            download_url=img_url,
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
                except Exception:
                    continue

            return results
        except Exception as e:
            logger.error(f"[MetMuseum] Search error: {e}")
            return []
