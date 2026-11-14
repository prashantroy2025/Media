"""Wikimedia Commons Media Provider with Strict License Filtering."""

import logging
from typing import Optional
import urllib.parse
import requests

from nova.licensing.checker import LicenseComplianceEngine
from nova.providers.base import BaseMediaProvider, MediaCandidate

logger = logging.getLogger("nova.providers.wikimedia")


class WikimediaProvider(BaseMediaProvider):
    """Integrates Wikimedia Commons API, strictly enforcing allow-listed licenses (CC0, PDM, CC-BY).

    Explicitly rejects CC BY-SA (copyleft), NC, and ND licenses.
    """

    def __init__(self):
        super().__init__(
            provider_id="wikimedia_commons",
            name="Wikimedia Commons",
            enabled=True,
            key_env=None,  # Keyless public API
            media_types=["image", "video"],
            requests_per_minute=60,
            cache_ttl_hours=48,
        )
        self.compliance_engine = LicenseComplianceEngine()

    def test_connection(self) -> tuple[bool, str]:
        try:
            headers = {"User-Agent": "NovaAutopilot/8.0 (Wikimedia API Client)"}
            res = requests.get(
                "https://commons.wikimedia.org/w/api.php",
                headers=headers,
                params={"action": "query", "meta": "siteinfo", "format": "json"},
                timeout=5,
            )
            if res.status_code == 200:
                return True, "Wikimedia Commons API accessible"
            return False, f"Wikimedia HTTP {res.status_code}: {res.text[:100]}"
        except Exception as e:
            return False, f"Wikimedia connection error: {e}"

    def _do_search(
        self,
        query: str,
        media_type: str,
        orientation: str,
        min_resolution: str,
        limit: int,
    ) -> list[MediaCandidate]:
        headers = {"User-Agent": "NovaAutopilot/8.0 (Commercial Video Pipeline; contact@nova-autopilot.ai)"}
        # Add filetype filter if video is requested
        search_q = query
        if media_type == "video":
            search_q += " filetype:video"

        params = {
            "action": "query",
            "generator": "search",
            "gsrsearch": search_q,
            "gsrnamespace": 6,  # File namespace
            "gsrlimit": min(max(limit * 2, 8), 30),  # Request extra to account for filtered SA/NC licenses
            "prop": "imageinfo",
            "iiprop": "url|size|extmetadata|mime",
            "format": "json",
        }

        try:
            res = requests.get("https://commons.wikimedia.org/w/api.php", headers=headers, params=params, timeout=7)
            if res.status_code != 200:
                logger.warning(f"[Wikimedia] HTTP {res.status_code}")
                return []

            data = res.json()
            pages = data.get("query", {}).get("pages", {})
            results: list[MediaCandidate] = []

            for page_id, page_info in pages.items():
                imageinfo_list = page_info.get("imageinfo", [])
                if not imageinfo_list:
                    continue

                ii = imageinfo_list[0]
                mime = ii.get("mime", "").lower()
                is_video = "video" in mime or mime.endswith("webm") or mime.endswith("mp4")
                is_valid_image = mime in ("image/jpeg", "image/png", "image/webp")

                if not is_video and not is_valid_image:
                    continue
                if media_type == "video" and not is_video:
                    continue
                if media_type == "image" and not is_valid_image:
                    continue

                meta = ii.get("extmetadata", {})
                license_short = meta.get("LicenseShortName", {}).get("value", "")
                license_url = meta.get("LicenseUrl", {}).get("value", "")
                artist_raw = meta.get("Artist", {}).get("value", "Wikimedia Contributor")
                title = page_info.get("title", "").replace("File:", "")
                download_url = ii.get("url", "")
                landing_page = ii.get("descriptionurl", f"https://commons.wikimedia.org/wiki/File:{urllib.parse.quote(title)}")

                # Strip HTML tags from artist string if present
                clean_artist = artist_raw
                if "<" in clean_artist:
                    import re
                    clean_artist = re.sub(r"<[^>]+>", "", clean_artist).strip()

                asset_id = f"wiki_{page_id}"

                # Strict license check!
                ok, proof, reason = self.compliance_engine.evaluate(
                    raw_license=license_short or license_url,
                    provider="wikimedia_commons",
                    asset_id=asset_id,
                    landing_page=landing_page,
                    creator=clean_artist[:100],
                    creator_url=landing_page,
                    title=title,
                    raw_license_url=license_url,
                )

                if not ok or not proof:
                    logger.debug(f"[Wikimedia] Skipped non-compliant asset {title} ({license_short}): {reason}")
                    continue

                w = ii.get("width", 1920)
                h = ii.get("height", 1080)
                thumb_url = ii.get("thumburl", download_url)

                results.append(
                    MediaCandidate(
                        provider="wikimedia_commons",
                        asset_id=asset_id,
                        title=title,
                        description=meta.get("ImageDescription", {}).get("value", title)[:300],
                        tags=[w.strip().lower() for w in query.split()],
                        preview_url=thumb_url or download_url,
                        download_url=download_url,
                        media_type="video" if is_video else "image",
                        width=w,
                        height=h,
                        duration=15.0 if is_video else 0.0,
                        author=clean_artist[:100],
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
            logger.error(f"[Wikimedia] Search error: {e}")
            return []
