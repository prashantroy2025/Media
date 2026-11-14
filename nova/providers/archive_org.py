"""Internet Archive Media Provider (Public Domain & Historical Footage)."""

import logging
from typing import Optional
import requests

from nova.licensing.checker import LicenseComplianceEngine
from nova.providers.base import BaseMediaProvider, MediaCandidate

logger = logging.getLogger("nova.providers.archive_org")


class InternetArchiveProvider(BaseMediaProvider):
    """Integrates Internet Archive API filtered strictly for public domain & Prelinger historical archives."""

    def __init__(self):
        super().__init__(
            provider_id="internet_archive",
            name="Internet Archive",
            enabled=True,
            key_env=None,  # Keyless public search API
            media_types=["video", "image"],
            requests_per_minute=40,
            cache_ttl_hours=72,
        )
        self.compliance_engine = LicenseComplianceEngine()

    def test_connection(self) -> tuple[bool, str]:
        try:
            params = {
                "q": "prelinger AND mediatype:movies",
                "fl[]": "identifier",
                "rows": 1,
                "output": "json",
            }
            res = requests.get("https://archive.org/advancedsearch.php", params=params, timeout=5)
            if res.status_code == 200:
                return True, "Internet Archive search accessible"
            return False, f"Internet Archive HTTP {res.status_code}: {res.text[:100]}"
        except Exception as e:
            return False, f"Internet Archive connection error: {e}"

    def _do_search(
        self,
        query: str,
        media_type: str,
        orientation: str,
        min_resolution: str,
        limit: int,
    ) -> list[MediaCandidate]:
        mtype_filter = "movies" if media_type == "video" else ("image" if media_type == "image" else "(movies OR image)")
        # Search publicdomain or prelinger collection
        search_query = f"({query}) AND mediatype:{mtype_filter} AND (licenseurl:*publicdomain* OR collection:prelinger)"

        params = {
            "q": search_query,
            "fl[]": ["identifier", "title", "description", "creator", "licenseurl", "mediatype", "year"],
            "sort[]": "downloads desc",
            "rows": min(max(limit, 3), 15),
            "output": "json",
        }

        try:
            res = requests.get("https://archive.org/advancedsearch.php", params=params, timeout=8)
            if res.status_code != 200:
                logger.warning(f"[InternetArchive] HTTP {res.status_code}")
                return []

            data = res.json()
            docs = data.get("response", {}).get("docs", [])
            results: list[MediaCandidate] = []

            for doc in docs:
                identifier = doc.get("identifier")
                if not identifier:
                    continue

                title = doc.get("title", query)
                creator = doc.get("creator", "Internet Archive / Prelinger Archives")
                if isinstance(creator, list):
                    creator = ", ".join(creator)
                landing_page = f"https://archive.org/details/{identifier}"
                preview_url = f"https://archive.org/services/img/{identifier}"

                doc_mtype = "video" if doc.get("mediatype") == "movies" else "image"
                # Construct download URL (standard archive.org derived mp4 or image)
                download_url = f"https://archive.org/download/{identifier}/{identifier}.mp4" if doc_mtype == "video" else preview_url

                asset_id = f"ia_{identifier}"
                ok, proof, _ = self.compliance_engine.evaluate(
                    raw_license="public domain",
                    provider="internet_archive",
                    asset_id=asset_id,
                    landing_page=landing_page,
                    creator=creator,
                    creator_url=landing_page,
                    title=title,
                )
                if not ok or not proof:
                    continue

                results.append(
                    MediaCandidate(
                        provider="internet_archive",
                        asset_id=asset_id,
                        title=title,
                        description=str(doc.get("description", ""))[:300],
                        tags=[w.strip().lower() for w in query.split()],
                        preview_url=preview_url,
                        download_url=download_url,
                        media_type=doc_mtype,
                        width=1920,
                        height=1080,
                        duration=30.0 if doc_mtype == "video" else 0.0,
                        author=creator,
                        creator_url=landing_page,
                        landing_page_url=landing_page,
                        license_proof=proof,
                        aspect_ratio=4.0 / 3.0 if doc_mtype == "video" else 16.0 / 9.0,
                    )
                )

                if len(results) >= limit:
                    break

            return results
        except Exception as e:
            logger.error(f"[InternetArchive] Search error: {e}")
            return []
