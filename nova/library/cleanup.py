"""Storage Cap Management & LRU Eviction for Local Media Library."""

import logging
from pathlib import Path
from typing import Optional

from nova.db import DatabaseManager, LibraryAsset, Video
from nova.library.catalog import MediaLibraryCatalog

logger = logging.getLogger("nova.library.cleanup")

DEFAULT_STORAGE_CAP_BYTES = 20 * 1024 * 1024 * 1024  # 20 GB default


def cleanup_library(
    max_bytes: int = DEFAULT_STORAGE_CAP_BYTES,
    db_path: str | Path = "data/nova.db",
    dry_run: bool = False,
) -> tuple[int, int]:
    """Evicts least recently used assets when total storage exceeds max_bytes.

    Strictly protects assets linked to queued or published videos.
    Returns:
        (evicted_count, freed_bytes)
    """
    catalog = MediaLibraryCatalog(db_path=db_path)
    db = catalog.db

    # 1. Update protected status by inspecting queued / published videos
    with db.session() as session:
        active_videos = session.query(Video).filter(Video.status.in_(["queued", "published", "scheduled"])).all()
        protected_asset_ids = set()
        for v in active_videos:
            for attr in v.attributions:
                if attr.asset_id:
                    protected_asset_ids.add(attr.asset_id)

        # Flag protected assets in library
        for asset_id in protected_asset_ids:
            asset = session.query(LibraryAsset).filter_by(asset_id=asset_id).first()
            if asset:
                asset.is_protected = True
        session.commit()

        # 2. Check total library size
        rows = session.query(LibraryAsset).all()
        total_size = sum(r.file_size_bytes or 0 for r in rows)

        if total_size <= max_bytes:
            logger.info(
                f"[LibraryCleanup] Total storage ({round(total_size / (1024 * 1024), 2)} MB) "
                f"is within cap ({round(max_bytes / (1024 * 1024), 2)} MB). No eviction needed."
            )
            return 0, 0

        target_bytes = int(max_bytes * 0.85)  # Evict down to 85% of threshold
        bytes_to_free = total_size - target_bytes

        logger.info(
            f"[LibraryCleanup] Storage exceeded: {round(total_size / (1024 * 1024), 2)} MB > "
            f"{round(max_bytes / (1024 * 1024), 2)} MB. Evicting ~{round(bytes_to_free / (1024 * 1024), 2)} MB."
        )

        # Query candidates for LRU eviction: unprotected first, oldest last_used_at, lowest usage_count
        evict_candidates = (
            session.query(LibraryAsset)
            .filter_by(is_protected=False)
            .order_by(LibraryAsset.last_used_at.asc(), LibraryAsset.usage_count.asc())
            .all()
        )

        evicted_count = 0
        freed_bytes = 0

        for asset in evict_candidates:
            if freed_bytes >= bytes_to_free:
                break

            file_path = Path(asset.local_path)
            f_size = asset.file_size_bytes or (file_path.stat().st_size if file_path.exists() else 0)

            if not dry_run:
                try:
                    if file_path.exists():
                        file_path.unlink()
                    session.delete(asset)
                    session.commit()
                except Exception as e:
                    logger.warning(f"[LibraryCleanup] Error removing {file_path}: {e}")
                    continue

            evicted_count += 1
            freed_bytes += f_size

        logger.info(
            f"[LibraryCleanup] Eviction complete. Removed {evicted_count} assets, "
            f"freed {round(freed_bytes / (1024 * 1024), 2)} MB."
        )
        return evicted_count, freed_bytes
