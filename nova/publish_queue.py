"""Local Publish Queue for platforms (e.g. Instagram Reels) requiring local execution at scheduled times."""

from datetime import UTC, datetime, timedelta

from nova.config import NovaSettings
from nova.db import DatabaseManager, PublishQueue, Video
from nova.logging_setup import logger
from nova.publishers import PublishingManager
from nova.schedule_engine import ScheduleEngine


class PublishQueueManager:
    """Manages enqueueing and dispatching scheduled video uploads."""

    def __init__(self, settings: NovaSettings, db_mgr: DatabaseManager, dry_run: bool = False):
        self.settings = settings
        self.db_mgr = db_mgr
        self.pub_mgr = PublishingManager(settings, db_mgr, dry_run=dry_run)
        self.schedule_engine = ScheduleEngine(settings, db_mgr)

    def enqueue_video(
        self,
        video_id: int,
        platform: str = "instagram",
        scheduled_time_utc: datetime | None = None,
    ) -> PublishQueue:
        """Adds a video to the local publish queue for future dispatch."""
        session = self.db_mgr.session()
        try:
            video = session.query(Video).filter(Video.id == video_id).first()
            if not video:
                raise ValueError(f"Video #{video_id} not found in database.")

            if scheduled_time_utc is None:
                if video.scheduled_time_utc:
                    scheduled_time_utc = video.scheduled_time_utc
                else:
                    utc_dt, us_dt, ist_dt = self.schedule_engine.calculate_next_slot()
                    scheduled_time_utc = utc_dt
                    video.scheduled_time_utc = utc_dt
                    video.scheduled_time_us_eastern = us_dt.isoformat()
                    video.scheduled_time_ist = ist_dt.isoformat()

            # Ensure UTC timezone
            if scheduled_time_utc.tzinfo is not None:
                scheduled_time_naive = scheduled_time_utc.astimezone(UTC).replace(tzinfo=None)
            else:
                scheduled_time_naive = scheduled_time_utc

            # Check if already enqueued
            existing = (
                session.query(PublishQueue)
                .filter(
                    PublishQueue.video_id == video_id,
                    PublishQueue.platform == platform,
                    PublishQueue.status.in_(["pending", "processing"]),
                )
                .first()
            )

            if existing:
                logger.info(f"Video #{video_id} is already in publish queue for {platform} (id={existing.id}).")
                return existing

            queue_item = PublishQueue(
                video_id=video_id,
                platform=platform,
                scheduled_time_utc=scheduled_time_naive,
                status="pending",
                attempts=0,
            )
            session.add(queue_item)
            session.commit()
            session.refresh(queue_item)
            logger.info(
                f"[bold green]Enqueued Video #{video_id} for {platform} at {scheduled_time_naive.strftime('%Y-%m-%d %H:%M UTC')}[/bold green] "
                f"(Queue ID #{queue_item.id})"
            )
            return queue_item
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to enqueue video #{video_id}: {e}", exc_info=True)
            raise
        finally:
            session.close()

    def get_due_items(self, grace_period_hours: float = 24.0) -> list[PublishQueue]:
        """Returns pending queue items whose scheduled time has arrived."""
        session = self.db_mgr.session()
        try:
            now_utc = datetime.now(UTC).replace(tzinfo=None)
            cutoff_missed = now_utc - timedelta(hours=grace_period_hours)

            # Query pending or failed with < 3 attempts
            items = (
                session.query(PublishQueue)
                .filter(
                    PublishQueue.status.in_(["pending", "failed"]),
                    PublishQueue.attempts < 3,
                    PublishQueue.scheduled_time_utc <= now_utc,
                )
                .order_by(PublishQueue.scheduled_time_utc.asc())
                .all()
            )

            due: list[PublishQueue] = []
            for item in items:
                # If older than grace period, mark as missed
                if item.scheduled_time_utc < cutoff_missed and item.status == "pending":
                    item.status = "missed"
                    item.error_message = (
                        f"Missed publishing window: scheduled for {item.scheduled_time_utc}, grace period expired."
                    )
                    logger.warning(
                        f"Publish queue item #{item.id} (Video #{item.video_id}) marked missed (exceeded {grace_period_hours}h grace period)."
                    )
                else:
                    due.append(item)

            session.commit()
            return due
        finally:
            session.close()

    def process_due_items(self) -> dict[str, int]:
        """Processes all currently due items in the queue."""
        due_items = self.get_due_items()
        summary = {"processed": 0, "succeeded": 0, "failed": 0, "missed": 0}

        if not due_items:
            logger.info("Publish queue check: no items currently due.")
            return summary

        logger.info(f"Processing {len(due_items)} due items from publish queue...")

        for item in due_items:
            summary["processed"] += 1
            session = self.db_mgr.session()
            try:
                # Reload item inside session
                q_record = session.query(PublishQueue).filter(PublishQueue.id == item.id).first()
                if not q_record or q_record.status == "completed":
                    continue

                q_record.status = "processing"
                q_record.attempts += 1
                session.commit()

                video = session.query(Video).filter(Video.id == q_record.video_id).first()
                if not video or not video.script:
                    q_record.status = "failed"
                    q_record.error_message = f"Video or script record missing for ID #{q_record.video_id}"
                    session.commit()
                    summary["failed"] += 1
                    continue

                # Publish to target platform
                logger.info(f"Dispatching scheduled publish for Video #{video.id} to {q_record.platform}...")
                results = self.pub_mgr.publish(video, platforms=[q_record.platform])
                res = results.get(q_record.platform)

                if res and res.status == "success":
                    q_record.status = "completed"
                    q_record.published_at = datetime.now(UTC).replace(tzinfo=None)
                    q_record.error_message = None
                    summary["succeeded"] += 1
                    logger.info(
                        f"[bold green]Scheduled publish succeeded for Video #{video.id} ({q_record.platform})![/bold green]"
                    )
                else:
                    err_msg = res.error_message if res else "Unknown publishing error"
                    q_record.status = "failed" if q_record.attempts >= 3 else "pending"
                    q_record.error_message = err_msg
                    summary["failed"] += 1
                    logger.warning(f"Publish failed for item #{q_record.id}: {err_msg} (Attempt {q_record.attempts}/3)")

                session.commit()
            except Exception as e:
                session.rollback()
                logger.error(f"Unexpected error processing queue item #{item.id}: {e}", exc_info=True)
                summary["failed"] += 1
            finally:
                session.close()

        return summary
