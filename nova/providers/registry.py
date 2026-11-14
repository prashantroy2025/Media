"""Provider Registry, Parallel Query Dispatcher, Deduplication & Unified Ranking."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
from pathlib import Path
from typing import Any, Optional
import yaml

from nova.licensing.checker import LicenseComplianceEngine
from nova.providers.archive_org import InternetArchiveProvider
from nova.providers.artic import ArtInstituteChicagoProvider
from nova.providers.base import BaseMediaProvider, MediaCandidate
from nova.providers.cleveland import ClevelandMuseumProvider
from nova.providers.coverr import CoverrProvider
from nova.providers.europeana import EuropeanaProvider
from nova.providers.freesound import FreesoundProvider
from nova.providers.generated_maps import GeneratedMapsProvider
from nova.providers.hasher import compute_dhash, hamming_distance, is_near_duplicate
from nova.providers.jamendo import JamendoProvider
from nova.providers.loc import LibraryOfCongressProvider
from nova.providers.met_museum import MetMuseumProvider
from nova.providers.nasa import NasaProvider
from nova.providers.pexels import PexelsProvider
from nova.providers.pixabay import PixabayProvider
from nova.providers.openverse import OpenverseProvider
from nova.providers.router import DomainRouter
from nova.providers.sec_gov import SecGovProvider
from nova.providers.smithsonian import SmithsonianProvider
from nova.providers.unsplash import UnsplashProvider
from nova.providers.wikimedia import WikimediaProvider

logger = logging.getLogger("nova.providers.registry")


class ProviderRegistry:
    """Manages multi-provider dispatch, deduplication, and unified ranking."""

    def __init__(self, config_path: str | Path = "config/media_providers.yaml"):
        self.config_path = Path(config_path)
        self.router = DomainRouter(config_path=self.config_path)
        self.compliance_engine = LicenseComplianceEngine()

        # Initialize provider instances
        self.providers: dict[str, BaseMediaProvider] = {
            "pixabay": PixabayProvider(),
            "pexels": PexelsProvider(),
            "nasa_library": NasaProvider(),
            "wikimedia_commons": WikimediaProvider(),
            "openverse": OpenverseProvider(),
            "internet_archive": InternetArchiveProvider(),
            "met_museum": MetMuseumProvider(),
            "artic": ArtInstituteChicagoProvider(),
            "cleveland_museum": ClevelandMuseumProvider(),
            "smithsonian": SmithsonianProvider(),
            "europeana": EuropeanaProvider(),
            "freesound": FreesoundProvider(),
            "unsplash": UnsplashProvider(),
            "coverr": CoverrProvider(),
            "jamendo": JamendoProvider(),
            "generated_maps": GeneratedMapsProvider(),
            "library_of_congress": LibraryOfCongressProvider(),
            "sec_gov": SecGovProvider(),
        }

        self._sync_with_config()

    def _sync_with_config(self) -> None:
        """Applies enabled flags and settings from YAML config."""
        if not self.config_path.exists():
            return
        try:
            with open(self.config_path, encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
            prov_cfg = config.get("providers", {})
            for pid, cfg in prov_cfg.items():
                if pid in self.providers:
                    if "enabled" in cfg:
                        self.providers[pid].enabled = bool(cfg["enabled"])
        except Exception as e:
            logger.error(f"Error syncing provider config: {e}")

    def get_provider(self, provider_id: str) -> Optional[BaseMediaProvider]:
        return self.providers.get(provider_id)

    def list_providers(self) -> list[dict[str, Any]]:
        """Returns metadata status for all registered providers."""
        results = []
        for pid, p in self.providers.items():
            has_key = bool(getattr(p, "api_key", None)) if p.key_env else True
            status = "enabled" if p.enabled else "disabled"
            if p.key_env and not has_key:
                status = "needs_key"
            if pid in ("coverr", "jamendo"):
                status = "needs_decision"

            results.append({
                "id": pid,
                "name": p.name,
                "enabled": p.enabled,
                "key_env": p.key_env,
                "has_key": has_key,
                "status": status,
                "media_types": p.media_types,
                "is_circuit_open": p.is_circuit_open,
            })
        return results

    def search_all(
        self,
        query: str,
        media_type: str = "video",
        niche: str = "",
        domain: str = "",
        limit_per_provider: int = 4,
        total_limit: int = 12,
    ) -> list[MediaCandidate]:
        """Dispatches parallel searches across prioritized providers and returns ranked, deduplicated candidates."""
        # 1. Determine domain and provider priority
        active_domain = domain or self.router.detect_domain(query, niche=niche)
        priority_ids = self.router.get_providers_for_domain(active_domain)

        # Build list of active providers to query
        providers_to_query: list[BaseMediaProvider] = []
        for pid in priority_ids:
            p = self.providers.get(pid)
            if p and p.enabled and not p.is_circuit_open:
                if not p.key_env or getattr(p, "api_key", None):
                    providers_to_query.append(p)

        # Fallback to general providers if domain list is small
        for p in self.providers.values():
            if p not in providers_to_query and p.enabled and not p.is_circuit_open:
                if not p.key_env or getattr(p, "api_key", None):
                    if len(providers_to_query) < 6:
                        providers_to_query.append(p)

        logger.info(
            f"[ProviderRegistry] Searching '{query}' (domain={active_domain}, media_type={media_type}) "
            f"across {len(providers_to_query)} providers: {[p.provider_id for p in providers_to_query]}"
        )

        all_candidates: list[MediaCandidate] = []

        # 2. Parallel query execution with ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(len(providers_to_query), 5)) as executor:
            future_to_provider = {
                executor.submit(
                    p.search,
                    query=query,
                    media_type=media_type,
                    limit=limit_per_provider,
                ): p
                for p in providers_to_query
            }
            for future in as_completed(future_to_provider):
                prov = future_to_provider[future]
                try:
                    cands = future.result()
                    all_candidates.extend(cands)
                except Exception as e:
                    logger.warning(f"Provider {prov.name} raised search exception: {e}")

        # 3. Deduplication (URL-based and dhash)
        deduped = self._deduplicate_candidates(all_candidates)

        # 4. Multi-factor unified ranking
        ranked = self._rank_candidates(deduped, query=query, domain=active_domain, priority_ids=priority_ids)

        return ranked[:total_limit]

    def search_beat(
        self,
        queries: list[str],
        media_type: str = "video",
        niche: str = "",
        domain: str = "",
        limit_per_query: int = 3,
        total_limit: int = 15,
    ) -> list[MediaCandidate]:
        """Searches across 3-6 query variants for a single beat and returns unified, ranked candidates."""
        if not queries:
            return []

        all_candidates: list[MediaCandidate] = []
        # Search the top variants
        for q in queries[:4]:
            results = self.search_all(
                query=q,
                media_type=media_type,
                niche=niche,
                domain=domain,
                limit_per_provider=limit_per_query,
                total_limit=8,
            )
            all_candidates.extend(results)

        deduped = self._deduplicate_candidates(all_candidates)
        # Re-rank against the primary query
        active_domain = domain or self.router.detect_domain(queries[0], niche=niche)
        priority_ids = self.router.get_providers_for_domain(active_domain)
        ranked = self._rank_candidates(deduped, query=queries[0], domain=active_domain, priority_ids=priority_ids)
        return ranked[:total_limit]

    def _deduplicate_candidates(self, candidates: list[MediaCandidate]) -> list[MediaCandidate]:
        """Eliminates exact and perceptual duplicates."""
        seen_urls: set[str] = set()
        unique: list[MediaCandidate] = []

        for c in candidates:
            # Check URL
            norm_url = c.download_url.strip().lower()
            if norm_url in seen_urls:
                continue
            seen_urls.add(norm_url)

            # Check dhash if precomputed
            if c.dhash:
                duplicate_found = False
                for existing in unique:
                    if existing.dhash and is_near_duplicate(c.dhash, existing.dhash, threshold=6):
                        duplicate_found = True
                        break
                if duplicate_found:
                    continue

            unique.append(c)

        return unique

    def _rank_candidates(
        self,
        candidates: list[MediaCandidate],
        query: str,
        domain: str,
        priority_ids: list[str],
    ) -> list[MediaCandidate]:
        """Scores and sorts candidates based on domain priority, keyword overlap, and media fidelity."""
        q_words = [w.strip().lower() for w in query.split() if len(w.strip()) > 2]

        for c in candidates:
            score = 30.0  # base score

            # 1. Domain provider priority (+25 for top provider, scaling down)
            if c.provider in priority_ids:
                rank_idx = priority_ids.index(c.provider)
                score += max(25.0 - (rank_idx * 5.0), 5.0)

            # 2. Keyword relevance (+10 per matched keyword in title/tags/description)
            searchable_text = f"{c.title} {' '.join(c.tags)} {c.description}".lower()
            matched_keywords = sum(1 for kw in q_words if kw in searchable_text)
            score += min(matched_keywords * 12.0, 36.0)

            # 3. Media aspect ratio and resolution
            if c.width >= 1920 or c.height >= 1080:
                score += 10.0
            if c.media_type == "video" and c.duration >= 3.0:
                score += 8.0

            # 4. Public domain bonus (no attribution burden)
            if c.license_proof and c.license_proof.is_public_domain:
                score += 5.0

            c.relevance_score = round(min(score, 100.0), 1)

        candidates.sort(key=lambda x: x.relevance_score, reverse=True)
        return candidates
