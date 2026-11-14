"""Prefetches High-Demand Licensed Assets for Common Niche Themes."""

import logging
from pathlib import Path
from typing import Optional

from nova.library.catalog import MediaLibraryCatalog
from nova.providers.registry import ProviderRegistry

logger = logging.getLogger("nova.library.prefetch")

NICHE_THEMES = {
    "ai_tech": [
        "microchip semiconductor silicon",
        "server room data center racks",
        "robotics automated factory",
        "artificial intelligence neural network",
        "computer programming code screen",
    ],
    "space": [
        "space telescope galaxy stars",
        "mars surface landscape",
        "saturn rings planetary orbit",
        "spacecraft rocket launch",
        "nebula cosmic gas cloud",
    ],
    "business": [
        "modern corporate skyscraper city",
        "stock exchange financial market",
        "global shipping container port",
        "business executives meeting boardroom",
        "financial charts graph economy",
    ],
}


def prefetch_niche_media(
    niche: str = "ai_tech",
    limit_per_theme: int = 2,
    media_type: str = "video",
    storage_dir: str | Path = "data/library/media",
) -> int:
    """Pre-downloads verified, licensed assets for a given niche and indexes them in local library."""
    registry = ProviderRegistry()
    catalog = MediaLibraryCatalog(storage_dir=storage_dir)

    target_niches = [niche] if niche in NICHE_THEMES else list(NICHE_THEMES.keys())
    total_downloaded = 0

    for current_niche in target_niches:
        themes = NICHE_THEMES.get(current_niche, [])
        logger.info(f"[Prefetch] Starting asset prefetch for niche '{current_niche}' ({len(themes)} themes)")

        for theme in themes:
            logger.info(f"[Prefetch] Searching theme '{theme}'...")
            try:
                candidates = registry.search_all(
                    query=theme,
                    media_type=media_type,
                    niche=current_niche,
                    limit_per_provider=2,
                    total_limit=limit_per_theme,
                )
                for cand in candidates:
                    # Check if already present in library
                    if catalog.get_asset(cand.asset_id):
                        logger.debug(f"[Prefetch] Asset {cand.asset_id} already in library, skipping.")
                        continue

                    # Download asset
                    prov = registry.get_provider(cand.provider)
                    if not prov:
                        continue

                    try:
                        local_path = prov.download(cand, dest_dir=storage_dir)
                        catalog.add_asset(cand, local_path, niche=current_niche)
                        total_downloaded += 1
                        logger.info(f"[Prefetch] Downloaded and catalogued: {cand.title} ({cand.provider}) -> {local_path}")
                    except Exception as de:
                        logger.warning(f"[Prefetch] Failed downloading {cand.asset_id}: {de}")
            except Exception as se:
                logger.warning(f"[Prefetch] Search failed for theme '{theme}': {se}")

    logger.info(f"[Prefetch] Complete! Successfully prefetched {total_downloaded} assets.")
    return total_downloaded
