"""Openverse Media Provider (Commercial-Safe CC0 & CC-BY Images)."""

import logging
from typing import Optional
import requests

from nova.licensing.checker import LicenseComplianceEngine
from nova.providers.base import BaseMediaProvider, MediaCandidate

logger = logging.getLogger("nova.providers.openverse")


class OpenverseProvider(BaseMediaProvider):
    """Integrates Openverse API (formerly Creative Commons Search) filtered strictly for commercial reuse."""

    def __init__(self):
        super().__init__(
            provider_id="openverse",
            name="Openverse",
            enabled=True,
            key_env=None,  # Keyless public API
            media_types=["image"],
            requests_per_minute=60,
            cache_ttl_hours=48,
        )
        self.compliance_engine = LicenseComplianceEngine()

    def test_connection(self) -> tuple[bool, str]:
        try:
            headers = {"User-Agent": "NovaAutopilot/8.0 (Openverse Integration)"}
            res = requests.get(
                "https://api.openverse.org/v1/images/",
                headers=headers,
                params={"q": "galaxy", "page_size": 1, "license_type": "commercial,modification"},
                timeout=5,
            )
            if res.status_code == 200:
                return True, "Openverse API accessible (commercial CC filter)"
            return False, f"Openverse HTTP {res.status_code}: {res.text[:100]}"
        except Exception as e:
            return False, f"Openverse connection error: {e}"

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

        headers = {"User-Agent": "NovaAutopilot/8.0 (Commercial Video Pipeline; contact@nova-autopilot.ai)"}
        params = {
            "q": query,
            "page_size": min(max(limit, 3), 20),
            # Explicitly request only commercial and modification allowed licenses
            "license_type": "commercial,modification",
        }

        try:
            res = requests.get("https://api.openverse.org/v1/images/", headers=headers, params=params, timeout=3)
            if res.status_code != 200:
                logger.warning(f"[Openverse] HTTP {res.status_code}")
                self.record_failure()
                return []

            data = res.json()
            results: list[MediaCandidate] = []
            for hit in data.get("results", []):
                download_url = hit.get("url")
                if not download_url:
                    continue

                asset_id = f"openverse_{hit.get('id')}"
                landing_page = hit.get("foreign_landing_url") or hit.get("detail_url") or ""
                creator = hit.get("creator") or "Openverse Contributor"
                creator_url = hit.get("creator_url") or ""
                license_code = hit.get("license", "")
                license_ver = hit.get("license_version", "")
                raw_license = f"CC {license_code.upper()} {license_ver}".strip()

                ok, proof, reason = self.compliance_engine.evaluate(
                    raw_license=raw_license,
                    provider="openverse",
                    asset_id=asset_id,
                    landing_page=landing_page,
                    creator=creator,
                    creator_url=creator_url,
                    title=hit.get("title", ""),
                    raw_license_url=hit.get("license_url", ""),
                )
                if not ok or not proof:
                    logger.debug(f"[Openverse] Skipped asset {asset_id} ({raw_license}): {reason}")
                    continue

                w = hit.get("width") or 1920
                h = hit.get("height") or 1080
                tags = [t.get("name", "").strip().lower() for t in hit.get("tags", []) if isinstance(t, dict)]

                results.append(
                    MediaCandidate(
                        provider="openverse",
                        asset_id=asset_id,
                        title=hit.get("title", query),
                        description=f"Openverse asset {hit.get('id')}",
                        tags=tags or [w.strip().lower() for w in query.split()],
                        preview_url=hit.get("thumbnail") or download_url,
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

                if len(results) >= limit:
                    break

            return results
        except Exception as e:
            logger.warning(f"[Openverse] Search error: {e}")
            self.record_failure()
            return []
