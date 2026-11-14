"""Reference Channel Tracker for Nova Autopilot v4.0.

Collects public video metadata and identifies viral outlier videos using cheap YouTube Data API calls
(playlistItems.list and videos.list: ~1 quota unit each, avoiding 100-unit search.list).
Tracks daily quota budget and computes age-adjusted outlier scores.
"""

import math
import os
import re
from datetime import UTC, datetime
from typing import Any

from googleapiclient.discovery import build

from nova.config import NovaSettings
from nova.db import DatabaseManager, ReferenceVideo
from nova.logging_setup import logger


def parse_iso_duration(duration_str: str) -> float:
    """Parses ISO 8601 duration string (e.g. PT1M25S, PT45S, PT1H2M) into seconds."""
    if not duration_str:
        return 0.0
    match = re.match(r"^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$", duration_str)
    if not match:
        return 0.0
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return float(hours * 3600 + minutes * 60 + seconds)


class ReferenceChannelTracker:
    def __init__(self, settings: NovaSettings, db_mgr: DatabaseManager):
        self.settings = settings
        self.db_mgr = db_mgr
        self.quota_budget = getattr(settings.research, "max_daily_quota_units", 500)
        self.outlier_threshold = getattr(settings.research, "outlier_threshold", 3.0)
        self.units_used_today = 0
        self.last_quota_reset = datetime.now(UTC).date()
        self.api_key = os.getenv("YOUTUBE_API_KEY", "")

    def _check_and_increment_quota(self, units: int = 1) -> bool:
        """Enforces daily quota budget."""
        today = datetime.now(UTC).date()
        if today != self.last_quota_reset:
            self.units_used_today = 0
            self.last_quota_reset = today

        if self.units_used_today + units > self.quota_budget:
            logger.warning(
                f"YouTube API research quota budget exceeded ({self.units_used_today}/{self.quota_budget} units used)."
            )
            return False
        self.units_used_today += units
        return True

    def _get_youtube_client(self):
        """Constructs authenticated or key-based YouTube Data API service."""
        if self.api_key:
            return build("youtube", "v3", developerKey=self.api_key)

        token_file = self.settings.resolve_path(self.settings.youtube.token_file)
        if token_file.exists():
            try:
                from google.oauth2.credentials import Credentials

                creds = Credentials.from_authorized_user_file(str(token_file))
                return build("youtube", "v3", credentials=creds)
            except Exception as e:
                logger.debug(f"Could not load OAuth credentials for research tracker: {e}")
        return None

    def compute_outlier_score(self, view_count: int, median_views: float, published_at: datetime | None) -> float:
        """Computes outlier score: ratio of video views to recent channel median, adjusted for age.

        Outlier score >= 3.0 indicates significant viral breakout above typical channel performance.
        """
        if median_views <= 0:
            return 1.0

        raw_ratio = view_count / max(100.0, median_views)
        if not published_at:
            return round(raw_ratio, 2)

        if published_at.tzinfo is None:
            pub_aware = published_at.replace(tzinfo=UTC)
        else:
            pub_aware = published_at

        age_hours = max(1.0, (datetime.now(UTC) - pub_aware).total_seconds() / 3600.0)
        # Gentle age factor: videos under 48 hours get slight boost for velocity
        if age_hours < 48:
            velocity_multiplier = math.sqrt(48.0 / age_hours)
            raw_ratio *= min(2.0, velocity_multiplier)

        return round(raw_ratio, 2)

    def track_channels(self) -> list[ReferenceVideo]:
        """Iterates configured reference channels and stores recent video metadata and outlier metrics."""
        channels = getattr(self.settings.research, "reference_channels", [])
        if not channels:
            logger.info("No reference channels configured in config.yaml.")
            return []

        client = self._get_youtube_client()
        if not client:
            logger.info("No YouTube API credentials available for reference tracker. Using stored/mock data.")
            return self._load_recent_outliers()

        saved_videos: list[ReferenceVideo] = []
        for ch in channels:
            if not self._check_and_increment_quota(1):
                break
            try:
                vids = self._track_single_channel(client, ch)
                saved_videos.extend(vids)
            except Exception as e:
                logger.warning(f"Failed to track reference channel '{ch.name}': {e}")

        return saved_videos

    def _track_single_channel(self, client: Any, channel_cfg: Any) -> list[ReferenceVideo]:
        """Resolves uploads playlist, reads recent videos with playlistItems.list & videos.list."""
        # 1. Resolve Uploads Playlist ID
        uploads_playlist_id = None
        if channel_cfg.channel_id:
            res = client.channels().list(part="contentDetails,snippet", id=channel_cfg.channel_id).execute()
        elif channel_cfg.handle:
            res = client.channels().list(part="contentDetails,snippet", forHandle=channel_cfg.handle).execute()
        else:
            return []

        items = res.get("items", [])
        if not items:
            return []

        channel_id = items[0]["id"]
        channel_title = items[0]["snippet"].get("title", channel_cfg.name)
        uploads_playlist_id = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

        # 2. Fetch recent uploads (1 unit)
        if not self._check_and_increment_quota(1):
            return []

        pl_res = (
            client.playlistItems()
            .list(part="contentDetails,snippet", playlistId=uploads_playlist_id, maxResults=20)
            .execute()
        )
        pl_items = pl_res.get("items", [])
        if not pl_items:
            return []

        video_ids = [item["contentDetails"]["videoId"] for item in pl_items]

        # 3. Fetch statistics & details in batch (1 unit)
        if not self._check_and_increment_quota(1):
            return []

        vid_res = client.videos().list(part="snippet,contentDetails,statistics", id=",".join(video_ids)).execute()
        vid_items = vid_res.get("items", [])

        # Compute median views
        views_list = [int(v.get("statistics", {}).get("viewCount", 0)) for v in vid_items]
        views_sorted = sorted(views_list)
        n = len(views_sorted)
        median_views = (
            (views_sorted[n // 2] if n % 2 != 0 else (views_sorted[n // 2 - 1] + views_sorted[n // 2]) / 2)
            if n > 0
            else 1000.0
        )

        records: list[ReferenceVideo] = []
        session = self.db_mgr.session()
        try:
            for v in vid_items:
                v_id = v["id"]
                snippet = v.get("snippet", {})
                stats = v.get("statistics", {})
                c_details = v.get("contentDetails", {})

                title = snippet.get("title", "")
                pub_str = snippet.get("publishedAt", "")
                try:
                    pub_dt = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                except Exception:
                    pub_dt = datetime.now(UTC)

                dur_sec = parse_iso_duration(c_details.get("duration", "PT0S"))
                is_short = dur_sec <= 180.0
                v_count = int(stats.get("viewCount", 0))
                l_count = int(stats.get("likeCount", 0))
                c_count = int(stats.get("commentCount", 0))
                tags = snippet.get("tags", [])

                score = self.compute_outlier_score(v_count, median_views, pub_dt)

                existing = session.query(ReferenceVideo).filter(ReferenceVideo.video_id == v_id).first()
                if existing:
                    existing.view_count = v_count
                    existing.like_count = l_count
                    existing.comment_count = c_count
                    existing.outlier_score = score
                    existing.fetched_at = datetime.now(UTC)
                    records.append(existing)
                else:
                    new_ref = ReferenceVideo(
                        channel_id=channel_id,
                        channel_title=channel_title,
                        video_id=v_id,
                        title=title,
                        published_at=pub_dt,
                        duration_seconds=dur_sec,
                        is_short=is_short,
                        view_count=v_count,
                        like_count=l_count,
                        comment_count=c_count,
                        tags_json=str(tags),
                        outlier_score=score,
                        niche=channel_cfg.niche,
                        fetched_at=datetime.now(UTC),
                    )
                    session.add(new_ref)
                    records.append(new_ref)
            session.commit()
        finally:
            session.close()

        return records

    def fetch_most_popular_us(self, category_id: str | None = None) -> list[dict]:
        """Low-cost platform-wide trend signal via videos.list?chart=mostPopular (1 unit)."""
        client = self._get_youtube_client()
        if not client or not self._check_and_increment_quota(1):
            return []

        kwargs: dict[str, Any] = {
            "part": "snippet,contentDetails,statistics",
            "chart": "mostPopular",
            "regionCode": "US",
            "maxResults": 15,
        }
        if category_id:
            kwargs["videoCategoryId"] = category_id

        try:
            res = client.videos().list(**kwargs).execute()
            items = res.get("items", [])
            results = []
            for item in items:
                dur = parse_iso_duration(item.get("contentDetails", {}).get("duration", ""))
                results.append(
                    {
                        "id": item["id"],
                        "title": item.get("snippet", {}).get("title", ""),
                        "channel_title": item.get("snippet", {}).get("channelTitle", ""),
                        "duration_seconds": dur,
                        "is_short": dur <= 180.0,
                        "views": int(item.get("statistics", {}).get("viewCount", 0)),
                    }
                )
            return results
        except Exception as e:
            logger.warning(f"Could not fetch mostPopular chart: {e}")
            return []

    def _load_recent_outliers(self, min_score: float = 2.5) -> list[ReferenceVideo]:
        """Loads validated outliers from database."""
        session = self.db_mgr.session()
        try:
            return (
                session.query(ReferenceVideo)
                .filter(ReferenceVideo.outlier_score >= min_score)
                .order_by(ReferenceVideo.outlier_score.desc())
                .limit(20)
                .all()
            )
        finally:
            session.close()
