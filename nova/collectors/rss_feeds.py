"""RSS feed collector for top AI and technology news sources."""

from datetime import UTC, datetime

import feedparser
import requests
from bs4 import BeautifulSoup

from nova.collectors.base import BaseCollector, RawTopic

DEFAULT_TECH_FEEDS: dict[str, str] = {
    "techcrunch_ai": "https://techcrunch.com/category/artificial-intelligence/feed/",
    "theverge_tech": "https://www.theverge.com/rss/index.xml",
    "arstechnica": "https://feeds.arstechnica.com/arstechnica/index",
    "venturebeat_ai": "https://venturebeat.com/category/ai/feed/",
}


class RSSNewsCollector(BaseCollector):
    def __init__(self, feeds: dict[str, str] = None, timeout_seconds: int = 15):
        super().__init__(name="rss_tech_news", timeout_seconds=timeout_seconds)
        self.feeds = feeds or DEFAULT_TECH_FEEDS

    def fetch(self) -> list[RawTopic]:
        topics: list[RawTopic] = []
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko)"
        }

        for source_key, url in self.feeds.items():
            try:
                resp = requests.get(url, headers=headers, timeout=self.timeout_seconds)
                if resp.status_code != 200:
                    continue
                parsed = feedparser.parse(resp.content)
                for entry in parsed.entries[:10]:
                    title = entry.get("title", "").strip()
                    if not title:
                        continue

                    raw_summary = entry.get("summary") or entry.get("description") or ""
                    soup = BeautifulSoup(raw_summary, "html.parser")
                    clean_summary = soup.get_text(separator=" ").strip()[:500]

                    topics.append(
                        RawTopic(
                            title=title,
                            summary=clean_summary or title,
                            source_name=f"rss_{source_key}",
                            source_url=entry.get("link", url),
                            region="GLOBAL",
                            raw_score=15.0,
                            published_at=datetime.now(UTC),
                            extra_metadata={"feed_key": source_key},
                        )
                    )
            except Exception:
                continue

        return topics
