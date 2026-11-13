"""Reddit RSS Collector: Topic idea inspiration from r/todayilearned, r/interestingasfuck, r/science."""

import re

import feedparser

from nova.collectors.base import BaseCollector, TopicItem
from nova.config import NovaSettings
from nova.logging_setup import logger

SUBREDDITS = [
    "todayilearned",
    "interestingasfuck",
    "science",
]


class RedditIdeasCollector(BaseCollector):
    name = "reddit_ideas"

    def __init__(self, settings: NovaSettings):
        super().__init__(settings)
        self.headers = {"User-Agent": "NovaAutopilot/2.0 (contact: info@novastudio.local)"}

    def collect(self) -> list[TopicItem]:
        items: list[TopicItem] = []

        for sub in SUBREDDITS:
            feed_url = f"https://www.reddit.com/r/{sub}/.rss"
            try:
                feed = feedparser.parse(feed_url, request_headers=self.headers)
                for entry in feed.entries[:8]:
                    raw_title = getattr(entry, "title", "").strip()
                    link = getattr(entry, "link", "")

                    # Clean "TIL that..." prefix
                    clean_title = re.sub(r"^TIL\s+(that\s+)?", "", raw_title, flags=re.IGNORECASE).strip()

                    # Filter short or empty titles
                    if len(clean_title) >= 15:
                        items.append(
                            TopicItem(
                                title=clean_title,
                                summary="Topic idea for mind-blowing facts & science explainer.",
                                source_name=f"reddit_r_{sub}",
                                source_url=link,
                                raw_score=80.0,
                            )
                        )
            except Exception as e:
                logger.warning(f"Error fetching Reddit r/{sub} feed: {e}")

        logger.info(f"Reddit Ideas collector fetched {len(items)} topic ideas.")
        return items
