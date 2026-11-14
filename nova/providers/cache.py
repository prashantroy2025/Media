"""Persistent Response Cache for Provider Search Queries."""

import hashlib
import json
import logging
from pathlib import Path
import time
from typing import Any, Optional

logger = logging.getLogger("nova.providers.cache")


class ProviderResponseCache:
    """Caches API search responses on disk honoring provider-specific TTLs."""

    def __init__(self, cache_dir: str | Path = "data/cache/providers"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_key(self, provider: str, query: str, media_type: str) -> str:
        raw = f"{provider}:{media_type}:{query.strip().lower()}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    def get(self, provider: str, query: str, media_type: str, ttl_hours: int = 24) -> Optional[list[dict]]:
        key = self._cache_key(provider, query, media_type)
        file_path = self.cache_dir / f"{key}.json"
        if not file_path.exists():
            return None

        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)

            cached_at = data.get("timestamp", 0)
            if time.time() - cached_at > ttl_hours * 3600:
                return None  # expired

            return data.get("candidates")
        except Exception as e:
            logger.debug(f"Cache read error for {provider}/{query}: {e}")
            return None

    def set(self, provider: str, query: str, media_type: str, candidates: list[dict]):
        key = self._cache_key(provider, query, media_type)
        file_path = self.cache_dir / f"{key}.json"
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "provider": provider,
                        "query": query,
                        "media_type": media_type,
                        "timestamp": time.time(),
                        "candidates": candidates,
                    },
                    f,
                    indent=2,
                )
        except Exception as e:
            logger.debug(f"Cache write error for {provider}/{query}: {e}")
