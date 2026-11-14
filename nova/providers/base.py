"""Base Media Provider Architecture & Candidate Models.

Defines the universal MediaCandidate schema and BaseMediaProvider abstract class
with built-in token-bucket rate limiting, disk caching, circuit breaker,
and exponential backoff retries.
"""

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
import logging
from pathlib import Path
import time
from typing import Any, Optional
import urllib.request
import requests

from nova.licensing.models import LicenseProof
from nova.providers.cache import ProviderResponseCache
from nova.providers.rate_limiter import TokenBucketRateLimiter

logger = logging.getLogger("nova.providers.base")


@dataclass
class MediaCandidate:
    """Universal media asset candidate across all providers."""

    provider: str
    asset_id: str
    title: str
    description: str
    tags: list[str]
    preview_url: str
    download_url: str
    media_type: str  # 'video', 'image', 'audio'
    width: int = 1920
    height: int = 1080
    duration: float = 0.0  # seconds (video/audio)
    author: str = ""
    creator_url: str = ""
    landing_page_url: str = ""
    license_proof: Optional[LicenseProof] = None
    aspect_ratio: float = 16.0 / 9.0
    dhash: Optional[str] = None
    relevance_score: float = 0.0
    local_path: Optional[str] = None

    @property
    def creator_name(self) -> str:
        return self.author

    @property
    def asset_url(self) -> str:
        return self.landing_page_url

    @property
    def license_name(self) -> str:
        return self.license_proof.license_name if self.license_proof else ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.license_proof:
            data["license_proof"] = self.license_proof.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MediaCandidate":
        cdata = dict(data)
        lp = cdata.get("license_proof")
        if isinstance(lp, dict):
            cdata["license_proof"] = LicenseProof.from_dict(lp)
        return cls(**cdata)


class BaseMediaProvider(ABC):
    """Abstract base provider with resilient networking, caching, and rate limiting."""

    def __init__(
        self,
        provider_id: str,
        name: str,
        enabled: bool = True,
        key_env: Optional[str] = None,
        media_types: Optional[list[str]] = None,
        requests_per_minute: int = 60,
        cache_ttl_hours: int = 24,
        circuit_cooldown_seconds: float = 180.0,
    ):
        self.provider_id = provider_id
        self.name = name
        self.enabled = enabled
        self.key_env = key_env
        self.media_types = media_types or ["video", "image"]
        self.rate_limiter = TokenBucketRateLimiter(requests_per_minute=requests_per_minute)
        self.cache = ProviderResponseCache()
        self.cache_ttl_hours = cache_ttl_hours
        self.circuit_cooldown_seconds = circuit_cooldown_seconds

        self._consecutive_failures = 0
        self._circuit_open_until = 0.0

    @property
    def is_circuit_open(self) -> bool:
        """Checks if the circuit breaker is actively tripping."""
        return time.monotonic() < self._circuit_open_until

    def record_success(self) -> None:
        """Resets circuit breaker failure count upon successful response."""
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0

    def record_failure(self) -> None:
        """Increments failure count and trips circuit breaker after 3 failures."""
        self._consecutive_failures += 1
        if self._consecutive_failures >= 3:
            self._circuit_open_until = time.monotonic() + self.circuit_cooldown_seconds
            logger.warning(
                f"[{self.name}] Circuit breaker tripped! Provider paused for {self.circuit_cooldown_seconds}s"
            )

    def search(
        self,
        query: str,
        media_type: str = "video",
        orientation: str = "all",
        min_resolution: str = "720p",
        limit: int = 10,
    ) -> list[MediaCandidate]:
        """Queries provider with caching, rate limiting, and circuit breaker protection."""
        if not self.enabled:
            return []

        if media_type != "all" and media_type not in self.media_types:
            return []

        if self.is_circuit_open:
            logger.info(f"[{self.name}] Skipping search query '{query}': circuit open.")
            return []

        clean_query = query.strip()
        if not clean_query:
            return []

        # 1. Check persistent response cache
        cached_data = self.cache.get(self.provider_id, clean_query, media_type, ttl_hours=self.cache_ttl_hours)
        if cached_data is not None:
            logger.debug(f"[{self.name}] Cache hit for '{clean_query}' ({media_type})")
            return [MediaCandidate.from_dict(d) for d in cached_data]

        # 2. Acquire rate limit token
        if not self.rate_limiter.acquire(blocking=True, timeout=5.0):
            logger.warning(f"[{self.name}] Rate limit token acquisition timed out for '{clean_query}'")
            return []

        # 3. Perform network search with retries
        candidates = []
        for attempt in range(2):
            try:
                candidates = self._do_search(
                    clean_query,
                    media_type=media_type,
                    orientation=orientation,
                    min_resolution=min_resolution,
                    limit=limit,
                )
                self.record_success()
                break
            except Exception as e:
                logger.warning(f"[{self.name}] Search attempt {attempt + 1} failed for '{clean_query}': {e}")
                if attempt == 0:
                    time.sleep(0.5)
                else:
                    self.record_failure()
                    return []

        # 4. Save to cache
        if candidates:
            self.cache.set(self.provider_id, clean_query, media_type, [c.to_dict() for c in candidates])

        return candidates

    @abstractmethod
    def _do_search(
        self,
        query: str,
        media_type: str,
        orientation: str,
        min_resolution: str,
        limit: int,
    ) -> list[MediaCandidate]:
        """Provider-specific search implementation to be implemented by subclasses."""
        pass

    def download(self, candidate: MediaCandidate, dest_dir: Path | str = "data/cache/media") -> Path:
        """Downloads the media asset file to local disk."""
        target_dir = Path(dest_dir) / self.provider_id
        target_dir.mkdir(parents=True, exist_ok=True)

        ext = ".mp4" if candidate.media_type == "video" else (".mp3" if candidate.media_type == "audio" else ".jpg")
        safe_id = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in candidate.asset_id)
        local_path = target_dir / f"{safe_id}{ext}"

        if local_path.exists() and local_path.stat().st_size > 1000:
            candidate.local_path = str(local_path)
            return local_path

        # Acquire rate limit token for downloading
        self.rate_limiter.acquire(blocking=True, timeout=5.0)

        # Download with stream
        headers = {"User-Agent": "NovaAutopilot/8.0 (Licensed Media Engine)"}
        with requests.get(candidate.download_url, headers=headers, stream=True, timeout=15) as r:
            r.raise_for_status()
            with open(local_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=65536):
                    f.write(chunk)

        candidate.local_path = str(local_path)
        return local_path

    @abstractmethod
    def test_connection(self) -> tuple[bool, str]:
        """Verifies API key and connectivity with a lightweight ping or search."""
        pass
