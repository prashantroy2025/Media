"""Publisher dispatcher with rate limiting and daily caps."""

from datetime import UTC, datetime

from nova.config import NovaSettings
from nova.db import DatabaseManager, Publication, Video
from nova.logging_setup import logger
from nova.publishers.base import BasePublisher, MockPublisher, PublishResult
from nova.publishers.instagram import InstagramPublisher
from nova.publishers.youtube import YouTubePublisher


class PublishingManager:
    def __init__(self, settings: NovaSettings, db_mgr: DatabaseManager, dry_run: bool = False):
        self.settings = settings
        self.db_mgr = db_mgr
        self.dry_run = dry_run
        self.publishers: dict[str, BasePublisher] = {}
        self._init_publishers()

    def _init_publishers(self):
        if self.dry_run:
            self.publishers["youtube"] = MockPublisher("youtube", self.settings.app.output_dir)
            self.publishers["instagram"] = MockPublisher("instagram", self.settings.app.output_dir)
        else:
            if self.settings.publishing.platforms.get("youtube", True):
                self.publishers["youtube"] = YouTubePublisher(self.settings)
            if self.settings.publishing.platforms.get("instagram", False):
                self.publishers["instagram"] = InstagramPublisher(self.settings)

    def can_publish_today(self) -> tuple[bool, str]:
        """Enforces daily cap and minimum gap between posts."""
        session = self.db_mgr.session()
        try:
            today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
            today_count = (
                session.query(Publication)
                .filter(
                    Publication.published_at >= today_start,
                    Publication.status == "success",
                )
                .count()
            )

            if today_count >= self.settings.publishing.daily_cap:
                return (
                    False,
                    f"Daily publishing cap reached ({today_count}/{self.settings.publishing.daily_cap} posts).",
                )

            last_pub = (
                session.query(Publication)
                .filter(Publication.status == "success")
                .order_by(Publication.published_at.desc())
                .first()
            )
            if last_pub:
                last_time = last_pub.published_at
                if last_time.tzinfo is None:
                    last_time = last_time.replace(tzinfo=UTC)
                hours_since = (datetime.now(UTC) - last_time).total_seconds() / 3600.0
                if hours_since < self.settings.publishing.min_gap_hours:
                    return (
                        False,
                        f"Minimum interval between posts not met ({hours_since:.1f}h / {self.settings.publishing.min_gap_hours}h required).",
                    )

            return True, "OK"
        finally:
            session.close()

    def publish_video(self, video_id: int, platform_name: str | None = None) -> list[PublishResult]:
        """Publishes an approved video to specified or all configured platforms."""
        session = self.db_mgr.session()
        try:
            video = session.query(Video).filter(Video.id == video_id).first()
            if not video:
                raise ValueError(f"Video with ID {video_id} not found.")

            script = video.script
            if not script:
                raise ValueError(f"Video {video_id} is missing an associated script.")

            targets = [platform_name] if platform_name else list(self.publishers.keys())
            results: list[PublishResult] = []

            for target in targets:
                pub = self.publishers.get(target)
                if not pub:
                    logger.warning(f"No publisher configured for platform '{target}'")
                    continue

                res = pub.publish(video, script)
                results.append(res)

                # Persist publication record
                db_pub = Publication(
                    video_id=video.id,
                    platform=res.platform,
                    platform_post_id=res.platform_post_id,
                    platform_url=res.platform_url,
                    status=res.status,
                    error_message=res.error_message,
                )
                session.add(db_pub)

                if res.status == "success":
                    video.status = "published"

            session.commit()
            return results
        except Exception as e:
            session.rollback()
            logger.error(f"Publishing failed for video {video_id}: {e}", exc_info=True)
            raise
        finally:
            session.close()
