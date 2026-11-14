"""Offline Instant Local Media Library Searcher."""

import json
import logging
from pathlib import Path
from typing import Optional

from nova.db import DatabaseManager, LibraryAsset
from nova.library.catalog import MediaLibraryCatalog
from nova.providers.base import MediaCandidate

logger = logging.getLogger("nova.library.searcher")


class MediaLibrarySearcher:
    """Performs offline instant searches against local cached media assets."""

    def __init__(self, db_path: str | Path = "data/nova.db"):
        self.catalog = MediaLibraryCatalog(db_path=db_path)

    def search(
        self,
        query: str,
        media_type: str = "video",
        niche: str = "",
        min_relevance: float = 35.0,
        limit: int = 6,
    ) -> list[MediaCandidate]:
        """Searches local library for matching assets before querying online APIs."""
        q_words = [w.strip().lower() for w in query.split() if len(w.strip()) > 2]
        if not q_words:
            return []

        candidates: list[MediaCandidate] = []

        with self.catalog.db.session() as session:
            db_query = session.query(LibraryAsset)
            if media_type != "all":
                db_query = db_query.filter_by(media_type=media_type)

            assets = db_query.all()
            for asset in assets:
                # Confirm file actually exists on disk
                if not Path(asset.local_path).exists():
                    continue

                # Compute keyword overlap score
                tags = []
                if asset.tags_json:
                    try:
                        tags = json.loads(asset.tags_json)
                    except Exception:
                        pass

                searchable_text = f"{asset.title} {' '.join(tags)} {asset.description}".lower()
                matches = sum(1 for kw in q_words if kw in searchable_text)
                if matches == 0:
                    continue

                score = min(matches * 25.0 + 30.0, 100.0)
                if niche and asset.niche == niche:
                    score = min(score + 15.0, 100.0)

                # Penalize overly used assets slightly
                if asset.usage_count > 3:
                    score = max(score - (asset.usage_count * 2.0), 20.0)

                if score >= min_relevance:
                    cand = MediaLibraryCatalog.to_candidate(asset)
                    cand.relevance_score = round(score, 1)
                    candidates.append(cand)

        candidates.sort(key=lambda x: x.relevance_score, reverse=True)
        return candidates[:limit]
