"""AI and Technology breaking news collector."""

import re
from datetime import UTC, datetime

import feedparser
import requests

from nova.collectors.base import BaseCollector, RawTopic
from nova.logging_setup import logger

TECH_FEEDS = [
    ("https://www.theverge.com/rss/index.xml", "The Verge Tech"),
    ("https://feeds.arstechnica.com/arstechnica/technology-lab", "Ars Technica Tech"),
    ("https://www.technologyreview.com/feed/", "MIT Technology Review"),
]


class TechNewsCollector(BaseCollector):
    """Collects breaking AI, robotics, computing, and technology articles."""

    def __init__(self, timeout_seconds: int = 15):
        super().__init__(name="tech_news", timeout_seconds=timeout_seconds)

    def fetch(self) -> list[RawTopic]:
        topics: list[RawTopic] = []
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        }

        for feed_url, feed_name in TECH_FEEDS:
            try:
                resp = requests.get(feed_url, headers=headers, timeout=self.timeout_seconds)
                if resp.status_code != 200:
                    continue

                feed = feedparser.parse(resp.content)
                for entry in feed.entries[:8]:
                    title = entry.get("title", "").strip()
                    summary = entry.get("summary", "").strip()
                    clean_summary = re.sub(r"<[^>]+>", "", summary).strip()
                    link = entry.get("link", "")

                    if not title or len(title) < 10:
                        continue

                    # Filter out TV/movie reviews
                    if any(term in title.lower() for term in ["review:", "trailer:", "box office", "season finale"]):
                        continue

                    topics.append(
                        RawTopic(
                            title=title[:200],
                            summary=clean_summary[:400] or f"Technology story from {feed_name}.",
                            source_name=f"tech_{feed_name.lower().replace(' ', '_')}",
                            source_url=link,
                            region="US",
                            niche="ai_tech",
                            raw_score=85.0,
                            published_at=datetime.now(UTC),
                            extra_metadata={"feed": feed_name},
                        )
                    )
            except Exception as e:
                logger.debug(f"Feed '{feed_name}' failed: {e}")
                continue

        logger.info(f"Tech News collector fetched {len(topics)} AI/tech topics.")
        return topics
