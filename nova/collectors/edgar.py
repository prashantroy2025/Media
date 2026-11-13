"""SEC EDGAR collector for corporate filings, press releases, and executive disclosures."""

import os
from datetime import UTC, datetime

import feedparser
import requests

from nova.collectors.base import BaseCollector, RawTopic
from nova.logging_setup import logger


class EDGARCollector(BaseCollector):
    """Collects corporate announcements and filings from the US SEC EDGAR public feeds."""

    def __init__(self, timeout_seconds: int = 15):
        super().__init__(name="sec_edgar", timeout_seconds=timeout_seconds)
        self.feed_url = "https://www.sec.gov/news/pressreleases.rss"

    def fetch(self) -> list[RawTopic]:
        contact_email = os.getenv("CONTACT_EMAIL", "prashantroy.dev@gmail.com")
        headers = {
            "User-Agent": f"NovaStudio/3.0 (Prashant Roy; contact: {contact_email})",
            "Accept-Encoding": "gzip, deflate",
            "Host": "www.sec.gov",
        }

        topics: list[RawTopic] = []
        try:
            resp = requests.get(self.feed_url, headers=headers, timeout=self.timeout_seconds)
            if resp.status_code != 200:
                logger.debug(f"SEC EDGAR returned status {resp.status_code}")
                return []

            feed = feedparser.parse(resp.content)
            for entry in feed.entries[:10]:
                title = entry.get("title", "").strip()
                summary = entry.get("summary", "").strip()
                link = entry.get("link", "https://www.sec.gov")

                if not title:
                    continue

                topics.append(
                    RawTopic(
                        title=f"SEC Disclosure: {title}"[:200],
                        summary=summary[:400]
                        or f"Official US Securities and Exchange Commission filing regarding {title}.",
                        source_name=self.name,
                        source_url=link,
                        region="US",
                        niche="business",
                        raw_score=80.0,
                        published_at=datetime.now(UTC),
                        extra_metadata={"agency": "U.S. SEC"},
                    )
                )
        except Exception as e:
            logger.debug(f"SEC EDGAR collector encountered error: {e}")

        logger.info(f"SEC EDGAR collector fetched {len(topics)} corporate disclosures.")
        return topics
