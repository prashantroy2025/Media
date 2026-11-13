"""Science & Tech News RSS Collector: BBC Science, NASA, ScienceDaily, Phys.org, Ars Technica."""

import feedparser

from nova.collectors.base import BaseCollector, TopicItem
from nova.config import NovaSettings
from nova.logging_setup import logger

SCIENCE_FEEDS = [
    ("BBC Science", "http://feeds.bbci.co.uk/news/science_and_environment/rss.xml"),
    ("NASA Breaking News", "https://www.nasa.gov/news-release/feed/"),
    ("ScienceDaily", "https://www.sciencedaily.com/rss/all.xml"),
    ("Phys.org", "https://phys.org/rss-feed/"),
    ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
]


class ScienceNewsCollector(BaseCollector):
    name = "science_news"

    def __init__(self, settings: NovaSettings):
        super().__init__(settings)
        self.headers = {"User-Agent": "NovaAutopilot/2.0 (contact: info@novastudio.local)"}

    def collect(self) -> list[TopicItem]:
        items: list[TopicItem] = []

        for source_label, feed_url in SCIENCE_FEEDS:
            try:
                feed = feedparser.parse(feed_url, request_headers=self.headers)
                for entry in feed.entries[:6]:
                    title = getattr(entry, "title", "").strip()
                    summary = getattr(entry, "summary", "").strip()
                    link = getattr(entry, "link", "")

                    if title and len(title) > 10:
                        items.append(
                            TopicItem(
                                title=title,
                                summary=summary,
                                source_name=f"science_{source_label.lower().replace(' ', '_')}",
                                source_url=link,
                                niche="space_science",
                                raw_score=88.0,
                            )
                        )
            except Exception as e:
                logger.warning(f"Error fetching {source_label} feed ({feed_url}): {e}")

        logger.info(f"Science News collector fetched {len(items)} topics across {len(SCIENCE_FEEDS)} feeds.")
        return items
