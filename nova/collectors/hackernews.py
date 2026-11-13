"""Hacker News top stories collector."""

from datetime import UTC, datetime

import requests

from nova.collectors.base import BaseCollector, RawTopic


class HackerNewsCollector(BaseCollector):
    def __init__(self, limit: int = 25, timeout_seconds: int = 15):
        super().__init__(name="hackernews", timeout_seconds=timeout_seconds)
        self.limit = limit
        self.top_stories_url = "https://hacker-news.firebaseio.com/v0/topstories.json"
        self.item_url_fmt = "https://hacker-news.firebaseio.com/v0/item/{}.json"

    def fetch(self) -> list[RawTopic]:
        resp = requests.get(self.top_stories_url, timeout=self.timeout_seconds)
        resp.raise_for_status()
        story_ids = resp.json()[: self.limit]

        topics: list[RawTopic] = []
        for sid in story_ids:
            try:
                item_resp = requests.get(self.item_url_fmt.format(sid), timeout=5)
                if item_resp.status_code != 200:
                    continue
                item = item_resp.json()
                if not item or item.get("type") != "story":
                    continue

                title = item.get("title", "").strip()
                score = float(item.get("score", 1.0))
                url = item.get("url") or f"https://news.ycombinator.com/item?id={sid}"

                topics.append(
                    RawTopic(
                        title=title,
                        summary=f"Hacker News top story with {score} points and {item.get('descendants', 0)} comments.",
                        source_name=self.name,
                        source_url=url,
                        region="GLOBAL",
                        niche="ai_tech",
                        raw_score=min(score / 10.0, 50.0),
                        published_at=datetime.fromtimestamp(item.get("time", 0), tz=UTC),
                        extra_metadata={"comments": item.get("descendants", 0), "score": score},
                    )
                )
            except Exception:
                continue

        return topics
