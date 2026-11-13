"""Business and Economics news collector for high-value corporate stories."""

import re
from datetime import UTC, datetime

import feedparser
import requests

from nova.collectors.base import BaseCollector, RawTopic
from nova.logging_setup import logger

BUSINESS_FEEDS = [
    ("https://feeds.bbci.co.uk/news/business/rss.xml", "BBC Business"),
    ("https://search.cnbc.com/rs/search/combinedlist/view.xml?partnerId=wrss01&id=10001147", "CNBC Business"),
    ("https://search.cnbc.com/rs/search/combinedlist/view.xml?partnerId=wrss01&id=10000664", "CNBC Finance"),
]


class BusinessNewsCollector(BaseCollector):
    """Collects breaking business, market mechanism, and corporate economy stories."""

    def __init__(self, timeout_seconds: int = 15):
        super().__init__(name="business_news", timeout_seconds=timeout_seconds)

    def fetch(self) -> list[RawTopic]:
        topics: list[RawTopic] = []
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        }

        for feed_url, feed_name in BUSINESS_FEEDS:
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

                    if not title or len(title) < 12:
                        continue

                    # Filter out pure ticker movements (e.g. "DOW closes up 12 pts")
                    if any(
                        term in title.lower()
                        for term in ["futures rise", "futures fall", "midday report", "stocks close"]
                    ):
                        continue

                    topics.append(
                        RawTopic(
                            title=title[:200],
                            summary=clean_summary[:400] or f"Business story from {feed_name} covering {title}.",
                            source_name=f"business_{feed_name.lower().replace(' ', '_')}",
                            source_url=link,
                            region="US",
                            niche="business",
                            raw_score=82.0,
                            published_at=datetime.now(UTC),
                            extra_metadata={"feed": feed_name},
                        )
                    )
            except Exception as e:
                logger.debug(f"Feed '{feed_name}' failed: {e}")
                continue

        logger.info(f"Business News collector fetched {len(topics)} corporate/economy topics.")
        return topics
