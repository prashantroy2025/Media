"""Unit Tests for Local Media Library Catalog, Searcher & LRU Eviction."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from PIL import Image

from nova.db import DatabaseManager, LibraryAsset, Video
from nova.library.catalog import MediaLibraryCatalog
from nova.library.cleanup import cleanup_library
from nova.library.searcher import MediaLibrarySearcher
from nova.licensing.models import LicenseProof
from nova.providers.base import MediaCandidate


def test_library_catalog_add_and_retrieve(tmp_path):
    db_file = tmp_path / "test_nova.db"
    catalog = MediaLibraryCatalog(db_path=db_file, storage_dir=tmp_path / "media")

    # Create dummy local file
    fake_asset_path = tmp_path / "media" / "sample.mp4"
    fake_asset_path.parent.mkdir(parents=True, exist_ok=True)
    fake_asset_path.write_bytes(b"0" * 4096)

    proof = LicenseProof(
        provider="nasa_library",
        asset_id="nasa_apollo_11",
        license_id="pd_usgov",
        license_name="US Government Work (Public Domain)",
        license_url="https://usa.gov",
        landing_page_url="https://images.nasa.gov",
        creator_name="NASA",
        is_public_domain=True,
    )

    cand = MediaCandidate(
        provider="nasa_library",
        asset_id="nasa_apollo_11",
        title="Apollo 11 Moon Landing",
        description="Footage of lunar landing",
        tags=["apollo", "moon", "nasa", "space"],
        preview_url=str(fake_asset_path),
        download_url=str(fake_asset_path),
        media_type="video",
        license_proof=proof,
        local_path=str(fake_asset_path),
    )

    asset = catalog.add_asset(cand, fake_asset_path, niche="space_science")
    assert asset.asset_id == "nasa_apollo_11"
    assert asset.file_size_bytes == 4096

    # Retrieve asset
    retrieved = catalog.get_asset("nasa_apollo_11")
    assert retrieved is not None
    assert retrieved.title == "Apollo 11 Moon Landing"

    # Search asset via offline searcher
    searcher = MediaLibrarySearcher(db_path=db_file)
    results = searcher.search("moon landing apollo", media_type="video")
    assert len(results) == 1
    assert results[0].asset_id == "nasa_apollo_11"
    assert results[0].relevance_score >= 50.0


def test_library_lru_cleanup_protects_queued_assets(tmp_path):
    db_file = tmp_path / "test_nova.db"
    db_mgr = DatabaseManager(str(db_file))
    db_mgr.init_db()

    media_dir = tmp_path / "media"
    media_dir.mkdir(parents=True, exist_ok=True)

    # Asset 1: Unprotected old file (1 MB)
    p1 = media_dir / "old_unprotected.mp4"
    p1.write_bytes(b"1" * (1024 * 1024))

    # Asset 2: Protected active file (1 MB)
    p2 = media_dir / "active_queued.mp4"
    p2.write_bytes(b"2" * (1024 * 1024))

    with db_mgr.session() as session:
        a1 = LibraryAsset(
            asset_id="asset_old",
            provider="pixabay",
            media_type="video",
            local_path=str(p1),
            title="Old Asset",
            file_size_bytes=1024 * 1024,
            last_used_at=datetime.now(UTC) - timedelta(days=30),
            usage_count=1,
            is_protected=False,
        )
        a2 = LibraryAsset(
            asset_id="asset_queued",
            provider="nasa_library",
            media_type="video",
            local_path=str(p2),
            title="Queued Asset",
            file_size_bytes=1024 * 1024,
            last_used_at=datetime.now(UTC),
            usage_count=5,
            is_protected=True,
        )
        session.add_all([a1, a2])
        session.commit()

    # Trigger cleanup with max cap of 1.5 MB (forcing eviction of ~500 KB+)
    evicted, freed = cleanup_library(max_bytes=int(1.5 * 1024 * 1024), db_path=db_file)
    assert evicted == 1
    assert freed == 1024 * 1024

    # Verify a1 was deleted and a2 survived
    assert not p1.exists()
    assert p2.exists()

    with db_mgr.session() as session:
        assert session.query(LibraryAsset).filter_by(asset_id="asset_old").first() is None
        assert session.query(LibraryAsset).filter_by(asset_id="asset_queued").first() is not None
