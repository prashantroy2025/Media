"""arXiv AI and Machine Learning collector for cutting-edge paper discoveries."""

import re
from datetime import UTC, datetime

import feedparser
import requests

from nova.collectors.base import BaseCollector, RawTopic
from nova.logging_setup import logger


class ArxivAICollector(BaseCollector):
    """Collects recent research abstracts from arXiv cs.AI and cs.LG."""

    def __init__(self, timeout_seconds: int = 15):
        super().__init__(name="arxiv_ai", timeout_seconds=timeout_seconds)
        self.feed_urls = [
            ("https://rss.arxiv.org/rss/cs.AI", "arXiv Artificial Intelligence"),
            ("https://rss.arxiv.org/rss/cs.LG", "arXiv Machine Learning"),
        ]
        self.fallback_feed_urls = [
            ("http://export.arxiv.org/rss/cs.AI", "arXiv Artificial Intelligence (fallback)"),
            ("http://export.arxiv.org/rss/cs.LG", "arXiv Machine Learning (fallback)"),
        ]

    def fetch(self) -> list[RawTopic]:
        topics: list[RawTopic] = []
        headers = {"User-Agent": "NovaStudio/3.0 (research aggregator; contact: prashantroy.dev@gmail.com)"}

        urls_to_try = list(self.feed_urls)

        for url, source_label in urls_to_try:
            try:
                resp = requests.get(url, headers=headers, timeout=self.timeout_seconds)
                if resp.status_code != 200:
                    logger.warning(f"arXiv feed '{url}' returned HTTP {resp.status_code}")
                    continue

                feed = feedparser.parse(resp.content)
                if not feed.entries:
                    logger.warning(f"arXiv feed '{url}' returned 0 entries in parsed XML.")
                    continue

                for entry in feed.entries[:8]:
                    raw_title = entry.get("title", "").strip()
                    # Clean arXiv title prefix like "arXiv:2502.12345v1 [cs.AI] Title"
                    clean_title = re.sub(r"^[^\(]*\((?:arXiv:[^\)]+)\):\s*", "", raw_title)
                    clean_title = re.sub(r"^Title:\s*", "", clean_title)

                    raw_summary = entry.get("summary", "").strip()
                    # Strip HTML tags
                    clean_summary = re.sub(r"<[^>]+>", "", raw_summary)
                    clean_summary = re.sub(r"\s+", " ", clean_summary).strip()

                    link = entry.get("link", "")
                    if not clean_title or len(clean_title) < 10:
                        continue

                    topics.append(
                        RawTopic(
                            title=clean_title[:200],
                            summary=clean_summary[:500],
                            source_name=self.name,
                            source_url=link,
                            region="GLOBAL",
                            niche="ai_tech",
                            raw_score=85.0,
                            published_at=datetime.now(UTC),
                            extra_metadata={"category": source_label},
                        )
                    )
            except Exception as e:
                logger.debug(f"arXiv feed '{url}' failed: {e}")
                continue

        logger.info(f"arXiv collector fetched {len(topics)} papers.")
        return topics
