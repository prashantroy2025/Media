"""Google Trends RSS Collector for India trending queries."""

from datetime import UTC, datetime

import feedparser
import requests
from bs4 import BeautifulSoup

from nova.collectors.base import BaseCollector, RawTopic


class GoogleTrendsCollector(BaseCollector):
    def __init__(self, geo: str = "IN", timeout_seconds: int = 15):
        super().__init__(name=f"google_trends_{geo}", timeout_seconds=timeout_seconds)
        self.geo = geo
        self.feed_url = f"https://trends.google.com/trending/rss?geo={geo}"

    def fetch(self) -> list[RawTopic]:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        }
        resp = requests.get(self.feed_url, headers=headers, timeout=self.timeout_seconds)
        resp.raise_for_status()

        feed = feedparser.parse(resp.content)
        topics: list[RawTopic] = []

        for entry in feed.entries:
            title = entry.get("title", "").strip()
            if not title:
                continue

            summary_raw = entry.get("summary", "")
            soup = BeautifulSoup(summary_raw, "html.parser")
            clean_summary = soup.get_text(separator=" ").strip()

            # Approximate approx_traffic if available
            traffic = entry.get("ht_approx_traffic", "10K+")
            score = 10.0
            if "100K" in traffic or "200K" in traffic:
                score = 25.0
            elif "500K" in traffic or "1M" in traffic:
                score = 50.0

            # Classify niche based on topic keywords
            niche = "ai_tech"
            lower_text = f"{title} {clean_summary}".lower()
            if any(
                w in lower_text
                for w in [
                    "economy",
                    "inflation",
                    "stock",
                    "dollar",
                    "ceo",
                    "company",
                    "bank",
                    "billion",
                    "market",
                    "revenue",
                    "fed",
                ]
            ):
                niche = "business"
            elif any(
                w in lower_text
                for w in [
                    "space",
                    "nasa",
                    "planet",
                    "star",
                    "physics",
                    "telescope",
                    "moon",
                    "galaxy",
                    "astronomy",
                    "science",
                ]
            ):
                niche = "space_science"

            topics.append(
                RawTopic(
                    title=title,
                    summary=clean_summary or f"Trending search query in {self.geo}: {title}",
                    source_name=self.name,
                    source_url=entry.get("link", self.feed_url),
                    region=self.geo,
                    niche=niche,
                    raw_score=score,
                    published_at=datetime.now(UTC),
                    extra_metadata={"approx_traffic": traffic},
                )
            )

        return topics
