"""Base class and data contracts for Nova Autopilot topic collectors."""

import hashlib
import re
from abc import ABC
from dataclasses import dataclass, field
from datetime import datetime

from nova.logging_setup import logger


@dataclass
class RawTopic:
    title: str
    summary: str
    source_name: str
    source_url: str
    region: str = "US"
    niche: str = "ai_tech"
    raw_score: float = 1.0
    published_at: datetime | None = None
    extra_metadata: dict = field(default_factory=dict)

    @property
    def dedupe_hash(self) -> str:
        """Generates a stable sha256 hash based on normalized title."""
        clean_title = re.sub(r"[^\w\s]", "", self.title.lower()).strip()
        clean_title = re.sub(r"\s+", " ", clean_title)
        return hashlib.sha256(clean_title.encode("utf-8")).hexdigest()


TopicItem = RawTopic


class BaseCollector(ABC):
    """Abstract collector with isolation, timeouts, and safe execution."""

    name: str = "base"

    def __init__(self, name_or_settings=None, timeout_seconds: int = 15, name: str | None = None, **kwargs):
        if name:
            self.name = name
            self.settings = kwargs.get("settings", None)
        elif isinstance(name_or_settings, str):
            self.name = name_or_settings
            self.settings = kwargs.get("settings", None)
        else:
            self.settings = name_or_settings
        self.timeout_seconds = timeout_seconds

    def collect(self) -> list[RawTopic]:
        """Subclasses can override collect() or fetch()."""
        return []

    def fetch(self) -> list[RawTopic]:
        return self.collect()

    def run_safe(self) -> list[RawTopic]:
        """Executes fetch with exception handling and logging so one source never crashes the pipeline."""
        logger.info(f"Collecting topics from: [bold cyan]{self.name}[/bold cyan]...")
        try:
            results = self.fetch() or self.collect()
            logger.info(f"Successfully collected {len(results)} items from {self.name}.")
            return results
        except Exception as e:
            logger.warning(f"Collector '{self.name}' failed gracefully: {e}", exc_info=False)
            return []
