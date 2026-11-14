"""Local Media Library Catalog & Storage Manager."""

from datetime import UTC, datetime
import json
import logging
from pathlib import Path
from typing import Any, Optional

from sqlalchemy.orm import Session

from nova.db import DatabaseManager, LibraryAsset
from nova.licensing.models import LicenseProof
from nova.providers.base import MediaCandidate
from nova.providers.hasher import compute_dhash

logger = logging.getLogger("nova.library.catalog")


class MediaLibraryCatalog:
    """Manages indexing, retrieval, and metadata storage for local media assets."""

    def __init__(self, db_path: str | Path = "data/nova.db", storage_dir: str | Path = "data/library/media"):
        self.db = DatabaseManager(str(db_path))
        self.db.init_db()
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def add_asset(
        self,
        candidate: MediaCandidate,
        local_path: Path | str,
        niche: str = "general",
    ) -> LibraryAsset:
        """Indexes a downloaded asset into the SQLite media library catalog."""
        path_obj = Path(local_path)
        if not path_obj.exists():
            raise FileNotFoundError(f"Media file not found at {local_path}")

        file_size = path_obj.stat().st_size

        # Compute dhash for images if not already present
        dhash = candidate.dhash or ""
        if not dhash and candidate.media_type == "image":
            try:
                dhash = compute_dhash(path_obj)
            except Exception:
                pass

        proof_dict = candidate.license_proof.to_dict() if candidate.license_proof else {}

        with self.db.session() as session:
            existing = session.query(LibraryAsset).filter_by(asset_id=candidate.asset_id).first()
            if existing:
                existing.local_path = str(path_obj.resolve())
                existing.file_size_bytes = file_size
                existing.dhash = dhash
                existing.last_used_at = datetime.now(UTC)
                session.commit()
                return existing

            new_asset = LibraryAsset(
                asset_id=candidate.asset_id,
                provider=candidate.provider,
                media_type=candidate.media_type,
                local_path=str(path_obj.resolve()),
                title=candidate.title[:300],
                description=candidate.description,
                tags_json=json.dumps(candidate.tags),
                niche=niche,
                width=candidate.width,
                height=candidate.height,
                duration=candidate.duration,
                file_size_bytes=file_size,
                dhash=dhash,
                license_id=candidate.license_proof.license_id if candidate.license_proof else "unknown",
                license_name=candidate.license_name,
                license_url=candidate.license_proof.license_url if candidate.license_proof else "",
                landing_page_url=candidate.landing_page_url,
                creator_name=candidate.author,
                creator_url=candidate.creator_url,
                attribution_required=candidate.license_proof.attribution_required if candidate.license_proof else False,
                attribution_text=candidate.license_proof.attribution_text if candidate.license_proof else "",
                commercial_use_ok=candidate.license_proof.commercial_use_ok if candidate.license_proof else True,
                modifications_ok=candidate.license_proof.modifications_ok if candidate.license_proof else True,
                is_public_domain=candidate.license_proof.is_public_domain if candidate.license_proof else False,
                license_proof_json=json.dumps(proof_dict),
                downloaded_at=datetime.now(UTC),
                last_used_at=datetime.now(UTC),
                usage_count=0,
                is_protected=False,
            )
            session.add(new_asset)
            session.commit()
            session.refresh(new_asset)
            return new_asset

    def get_asset(self, asset_id: str) -> Optional[LibraryAsset]:
        with self.db.session() as session:
            return session.query(LibraryAsset).filter_by(asset_id=asset_id).first()

    def mark_used(self, asset_id: str, protect: bool = False) -> None:
        """Marks asset as recently used and optionally flags as protected (queued/published)."""
        with self.db.session() as session:
            asset = session.query(LibraryAsset).filter_by(asset_id=asset_id).first()
            if asset:
                asset.usage_count += 1
                asset.last_used_at = datetime.now(UTC)
                if protect:
                    asset.is_protected = True
                session.commit()

    def list_assets(self, limit: int = 50, media_type: str = "", niche: str = "") -> list[dict[str, Any]]:
        with self.db.session() as session:
            q = session.query(LibraryAsset)
            if media_type:
                q = q.filter_by(media_type=media_type)
            if niche and niche != "all":
                q = q.filter_by(niche=niche)
            rows = q.order_by(LibraryAsset.last_used_at.desc()).limit(limit).all()

            results = []
            for r in rows:
                results.append({
                    "asset_id": r.asset_id,
                    "provider": r.provider,
                    "media_type": r.media_type,
                    "title": r.title,
                    "local_path": r.local_path,
                    "license_id": r.license_id,
                    "creator_name": r.creator_name,
                    "duration": r.duration,
                    "file_size_bytes": r.file_size_bytes,
                    "usage_count": r.usage_count,
                    "is_protected": r.is_protected,
                    "downloaded_at": r.downloaded_at.isoformat() if r.downloaded_at else "",
                })
            return results

    def get_stats(self) -> dict[str, Any]:
        with self.db.session() as session:
            total_assets = session.query(LibraryAsset).count()
            rows = session.query(LibraryAsset.file_size_bytes, LibraryAsset.media_type).all()
            total_bytes = sum(r[0] or 0 for r in rows)
            videos_count = sum(1 for r in rows if r[1] == "video")
            images_count = sum(1 for r in rows if r[1] == "image")
            audio_count = sum(1 for r in rows if r[1] == "audio")

            return {
                "total_assets": total_assets,
                "total_size_mb": round(total_bytes / (1024 * 1024), 2),
                "total_size_gb": round(total_bytes / (1024 * 1024 * 1024), 3),
                "videos_count": videos_count,
                "images_count": images_count,
                "audio_count": audio_count,
            }

    @staticmethod
    def to_candidate(asset: LibraryAsset) -> MediaCandidate:
        """Converts database LibraryAsset into a runtime MediaCandidate."""
        tags = []
        if asset.tags_json:
            try:
                tags = json.loads(asset.tags_json)
            except Exception:
                pass

        proof = None
        if asset.license_proof_json:
            try:
                proof = LicenseProof.from_dict(json.loads(asset.license_proof_json))
            except Exception:
                pass

        if not proof:
            proof = LicenseProof(
                provider=asset.provider,
                asset_id=asset.asset_id,
                license_id=asset.license_id,
                license_name=asset.license_name,
                license_url=asset.license_url,
                landing_page_url=asset.landing_page_url,
                creator_name=asset.creator_name,
                creator_url=asset.creator_url,
                attribution_required=asset.attribution_required,
                attribution_text=asset.attribution_text,
                commercial_use_ok=asset.commercial_use_ok,
                modifications_ok=asset.modifications_ok,
                is_public_domain=asset.is_public_domain,
            )

        return MediaCandidate(
            provider=asset.provider,
            asset_id=asset.asset_id,
            title=asset.title,
            description=asset.description or "",
            tags=tags,
            preview_url=asset.local_path,
            download_url=asset.local_path,
            media_type=asset.media_type,
            width=asset.width,
            height=asset.height,
            duration=asset.duration,
            author=asset.creator_name,
            creator_url=asset.creator_url,
            landing_page_url=asset.landing_page_url,
            license_proof=proof,
            aspect_ratio=(asset.width / max(asset.height, 1)),
            dhash=asset.dhash or None,
            local_path=asset.local_path,
        )
