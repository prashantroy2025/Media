"""SEC.gov EDGAR / USGov Public Domain Provider.

Provides official US Government filings, corporate disclosures, and regulatory metadata.
US Government works are in the public domain under 17 U.S.C. § 105.
Complies with SEC FAIR USE policy by requiring a custom User-Agent.
"""

from __future__ import annotations

import logging
from typing import Any
import requests

from nova.licensing.checker import LicenseComplianceEngine
from nova.providers.base import BaseMediaProvider, MediaCandidate

logger = logging.getLogger("nova.providers.sec_gov")


class SecGovProvider(BaseMediaProvider):
    """Integrates SEC EDGAR Public Domain API for corporate and financial entities."""

    USER_AGENT = "NovaAutopilot PublicDomainMedia research@nova.internal"

    def __init__(self):
        super().__init__(
            provider_id="sec_gov",
            name="U.S. Securities and Exchange Commission (SEC EDGAR)",
            enabled=True,
            key_env=None,
            media_types=["image"],
            requests_per_minute=60,
            cache_ttl_hours=48,
        )
        self.compliance_engine = LicenseComplianceEngine()
        self._tickers_cache: dict[str, dict[str, Any]] | None = None

    def test_connection(self) -> tuple[bool, str]:
        try:
            res = requests.get(
                "https://www.sec.gov/files/company_tickers.json",
                headers={"User-Agent": self.USER_AGENT},
                timeout=5,
            )
            if res.status_code == 200:
                return True, "SEC EDGAR accessible (USGov Public Domain)"
            return False, f"SEC HTTP {res.status_code}"
        except Exception as e:
            return False, f"SEC connection error: {e}"

    def _ensure_tickers(self) -> dict[str, dict[str, Any]]:
        if self._tickers_cache is not None:
            return self._tickers_cache

        try:
            res = requests.get(
                "https://www.sec.gov/files/company_tickers.json",
                headers={"User-Agent": self.USER_AGENT},
                timeout=6,
            )
            if res.status_code == 200:
                data = res.json()
                # Map lowercase title and ticker to info
                cache: dict[str, dict[str, Any]] = {}
                for item in data.values():
                    cik = str(item.get("cik_str", "")).zfill(10)
                    ticker = str(item.get("ticker", "")).upper()
                    title = str(item.get("title", ""))
                    info = {"cik": cik, "ticker": ticker, "title": title}
                    cache[ticker.lower()] = info
                    cache[title.lower()] = info
                self._tickers_cache = cache
                return cache
        except Exception as e:
            logger.warning(f"Could not load SEC company tickers: {e}")

        self._tickers_cache = {}
        return self._tickers_cache

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

        tickers = self._ensure_tickers()
        q_clean = query.lower().strip()
        matched_companies: list[dict[str, Any]] = []

        # Find matching companies in SEC database
        words = q_clean.split()
        for key, info in tickers.items():
            if key in q_clean or any(w in key for w in words if len(w) > 3):
                if info not in matched_companies:
                    matched_companies.append(info)
                    if len(matched_companies) >= limit:
                        break

        candidates: list[MediaCandidate] = []
        for comp in matched_companies:
            cik = comp["cik"]
            ticker = comp["ticker"]
            title = comp["title"]
            asset_id = f"sec_edgar_{ticker.lower()}_{cik}"
            landing_page = f"https://www.sec.gov/edgar/browse/?CIK={cik}"

            ok, proof, _ = self.compliance_engine.evaluate(
                raw_license="pd_usgov",
                provider="sec_gov",
                asset_id=asset_id,
                landing_page=landing_page,
                creator="U.S. Securities and Exchange Commission (EDGAR)",
                creator_url="https://www.sec.gov",
                title=f"SEC Filing Record: {title} ({ticker})",
            )
            if not ok or not proof:
                continue

            candidates.append(
                MediaCandidate(
                    provider="sec_gov",
                    asset_id=asset_id,
                    media_type="image",
                    title=f"SEC Regulatory Record: {title} ({ticker})",
                    description=f"Official US Government SEC EDGAR regulatory registration and corporate disclosure for {title}.",
                    tags=["sec", "edgar", "usgov", "finance", "regulation", ticker.lower()],
                    width=1920,
                    height=1080,
                    duration=0.0,
                    preview_url=f"https://www.sec.gov/edgar/browse/?CIK={cik}",
                    download_url=f"https://data.sec.gov/submissions/CIK{cik}.json",
                    author="U.S. Securities and Exchange Commission",
                    landing_page_url=landing_page,
                    license_proof=proof,
                    relevance_score=85.0,
                )
            )

        return candidates
