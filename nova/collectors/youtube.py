"""YouTube Data API collector for trending tech videos in India."""

import os
from datetime import UTC, datetime

from googleapiclient.discovery import build

from nova.collectors.base import BaseCollector, RawTopic
from nova.logging_setup import logger


class YouTubeTrendingCollector(BaseCollector):
    def __init__(self, region_code: str = "IN", category_id: str = "28", timeout_seconds: int = 15):
        super().__init__(name="youtube_trending", timeout_seconds=timeout_seconds)
        self.region_code = region_code
        self.category_id = category_id
        self.api_key = os.getenv("YOUTUBE_API_KEY") or os.getenv("GOOGLE_API_KEY")

    def fetch(self) -> list[RawTopic]:
        if not self.api_key:
            logger.info("YOUTUBE_API_KEY / GOOGLE_API_KEY not configured in .env; skipping YouTube trending collector.")
            return []

        youtube = build("youtube", "v3", developerKey=self.api_key)
        request = youtube.videos().list(
            part="snippet,statistics",
            chart="mostPopular",
            regionCode=self.region_code,
            videoCategoryId=self.category_id,
            maxResults=15,
        )
        response = request.execute()

        topics: list[RawTopic] = []
        for item in response.get("items", []):
            snippet = item.get("snippet", {})
            stats = item.get("statistics", {})
            title = snippet.get("title", "").strip()
            if not title:
                continue

            view_count = int(stats.get("viewCount", 1000))
            score = min(view_count / 10000.0, 50.0)

            topics.append(
                RawTopic(
                    title=title,
                    summary=snippet.get("description", "")[:400],
                    source_name=self.name,
                    source_url=f"https://www.youtube.com/watch?v={item.get('id')}",
                    region=self.region_code,
                    raw_score=score,
                    published_at=datetime.now(UTC),
                    extra_metadata={"view_count": view_count, "channel_title": snippet.get("channelTitle")},
                )
            )

        return topics
