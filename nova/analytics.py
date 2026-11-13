"""Analytics engine for fetching published video metrics (views, likes) and updating topic ranking weights."""

import json
from datetime import UTC, datetime, timedelta

import requests
from googleapiclient.discovery import build

from nova.config import NovaSettings
from nova.db import DatabaseManager, Publication
from nova.logging_setup import logger
from nova.niches import NicheLearningLoop
from nova.publishers.youtube import YouTubePublisher


class AnalyticsManager:
    def __init__(self, settings: NovaSettings, db_mgr: DatabaseManager):
        self.settings = settings
        self.db_mgr = db_mgr

    def refresh_all_stats(self) -> int:
        """Pulls latest stats for published videos across all supported platforms."""
        session = self.db_mgr.session()
        updated_count = 0
        try:
            publications = session.query(Publication).filter(Publication.status == "success").all()
            if not publications:
                logger.info("No published videos found in database to refresh stats.")
                return 0

            yt_pubs = [
                p for p in publications if p.platform == "youtube" and not p.platform_post_id.startswith("mock_")
            ]
            if yt_pubs:
                updated_count += self._refresh_youtube_stats(yt_pubs, session)

            ig_pubs = [
                p for p in publications if p.platform == "instagram" and not p.platform_post_id.startswith("mock_")
            ]
            if ig_pubs:
                updated_count += self._refresh_instagram_stats(ig_pubs, session)

            session.commit()
            logger.info(f"Refreshed stats for {updated_count} publications.")

            # Trigger guardrailed niche weight optimization
            try:
                loop = NicheLearningLoop(self.settings, self.db_mgr)
                loop.evaluate_and_adjust_weights()
            except Exception as le:
                logger.warning(f"Niche weight learning loop skipped: {le}")

            return updated_count
        except Exception as e:
            session.rollback()
            logger.error(f"Error during stats refresh: {e}", exc_info=True)
            return 0
        finally:
            session.close()

    def _refresh_youtube_stats(self, pubs: list[Publication], session) -> int:
        yt_pub = YouTubePublisher(self.settings)
        creds = yt_pub.get_credentials()
        if not creds:
            logger.warning("YouTube credentials not available to fetch video metrics.")
            return 0

        youtube = build("youtube", "v3", credentials=creds)
        video_ids = [p.platform_post_id for p in pubs]

        # Chunk into groups of 50
        count = 0
        for i in range(0, len(video_ids), 50):
            chunk = video_ids[i : i + 50]
            try:
                res = youtube.videos().list(part="statistics", id=",".join(chunk)).execute()
                stats_map = {item["id"]: item.get("statistics", {}) for item in res.get("items", [])}

                for p in pubs:
                    if p.platform_post_id in stats_map:
                        st = stats_map[p.platform_post_id]
                        p.views = int(st.get("viewCount", p.views))
                        p.likes = int(st.get("likeCount", p.likes))
                        p.comments = int(st.get("commentCount", p.comments))
                        count += 1

                        # Update topic score to reflect real performance
                        if p.video and p.video.script and p.video.script.topic:
                            topic = p.video.script.topic
                            topic.raw_score = max(topic.raw_score, min(p.views / 50.0, 100.0))
            except Exception as e:
                logger.warning(f"Failed to fetch YouTube batch statistics: {e}")

        # Attempt YouTube Analytics API for country breakdown and retention
        self._refresh_youtube_analytics(pubs, creds)
        return count

    def _refresh_youtube_analytics(self, pubs: list[Publication], creds):
        """Fetches geographic views (US, GB, CA, AU) and retention from YouTube Analytics API."""
        try:
            yt_analytics = build("youtubeAnalytics", "v2", credentials=creds)
            end_date = datetime.now(UTC).strftime("%Y-%m-%d")
            start_date = (datetime.now(UTC) - timedelta(days=90)).strftime("%Y-%m-%d")

            for p in pubs:
                vid_id = p.platform_post_id
                try:
                    res = (
                        yt_analytics.reports()
                        .query(
                            ids="channel==MINE",
                            startDate=start_date,
                            endDate=end_date,
                            metrics="views,estimatedMinutesWatched,averageViewDuration",
                            dimensions="country",
                            filters=f"video=={vid_id}",
                        )
                        .execute()
                    )

                    rows = res.get("rows", [])
                    country_breakdown = {}
                    total_dur = 0.0
                    total_views = 0
                    for row in rows:
                        country_code = row[0]
                        c_views = int(row[1])
                        c_dur = float(row[3]) if len(row) > 3 else 0.0
                        country_breakdown[country_code] = c_views
                        total_views += c_views
                        total_dur += c_dur * c_views

                    if country_breakdown:
                        p.views_by_country_json = json.dumps(country_breakdown)
                    if total_views > 0:
                        avg_dur = round(total_dur / total_views, 1)
                        p.avg_view_duration_seconds = avg_dur
                        if p.video and p.video.duration_seconds and p.video.duration_seconds > 0:
                            p.retention_rate = round(min(1.0, avg_dur / p.video.duration_seconds), 3)
                except Exception as e:
                    logger.debug(f"YouTube Analytics query for {vid_id} skipped: {e}")
        except Exception as e:
            logger.debug(f"YouTube Analytics API client unavailable: {e}")

    def _refresh_instagram_stats(self, pubs: list[Publication], session) -> int:
        token = self.settings.instagram.access_token
        if not token:
            return 0

        count = 0
        for p in pubs:
            url = f"https://graph.facebook.com/v19.0/{p.platform_post_id}/insights"
            params = {"metric": "reach,plays,likes,comments", "access_token": token}
            try:
                res = requests.get(url, params=params, timeout=10)
                if res.status_code == 200:
                    data = res.json().get("data", [])
                    for metric in data:
                        m_name = metric.get("name")
                        val = metric.get("values", [{}])[0].get("value", 0)
                        if m_name in ["plays", "reach"]:
                            p.views = max(p.views, val)
                        elif m_name == "likes":
                            p.likes = max(p.likes, val)
                        elif m_name == "comments":
                            p.comments = max(p.comments, val)
                    count += 1
            except Exception:
                pass
        return count
