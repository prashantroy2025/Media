"""US Prime-Time Scheduling Engine with automatic timezone conversion and DST support."""

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from nova.config import NovaSettings
from nova.db import DatabaseManager, Video
from nova.logging_setup import logger

US_EASTERN = ZoneInfo("America/New_York")
IST = ZoneInfo("Asia/Kolkata")


class ScheduleEngine:
    """Computes next available publishing slots aligned with US East Coast peak viewing hours."""

    def __init__(self, settings: NovaSettings, db_mgr: DatabaseManager | None = None):
        self.settings = settings
        self.db_mgr = db_mgr

    def get_existing_scheduled_slots(self, min_time: datetime | None = None) -> list[datetime]:
        """Fetches already scheduled video UTC datetimes from DB."""
        if not self.db_mgr:
            return []
        session = self.db_mgr.session()
        try:
            cutoff = min_time if min_time is not None else datetime.now(UTC)
            if cutoff.tzinfo is not None:
                # SQLite stored naive UTC timestamps
                cutoff_naive = cutoff.astimezone(UTC).replace(tzinfo=None)
            else:
                cutoff_naive = cutoff

            records = (
                session.query(Video.scheduled_time_utc)
                .filter(
                    Video.scheduled_time_utc.is_not(None),
                    Video.scheduled_time_utc >= cutoff_naive,
                )
                .all()
            )
            return [r[0].replace(tzinfo=UTC) if r[0].tzinfo is None else r[0] for r in records if r[0]]
        except Exception as e:
            logger.warning(f"Could not load existing scheduled slots: {e}")
            return []
        finally:
            session.close()

    def calculate_next_slot(
        self,
        reference_time: datetime | None = None,
        min_lead_minutes: int = 30,
        min_spacing_hours: float = 2.0,
    ) -> tuple[datetime, datetime, datetime]:
        """Calculates the next optimal publishing slot in US Eastern prime time.

        Returns (utc_datetime, us_eastern_datetime, ist_datetime).
        Always handles US Daylight Saving Time (EDT vs EST) automatically via zoneinfo.
        """
        if reference_time is None:
            reference_time = datetime.now(UTC)
        elif reference_time.tzinfo is None:
            reference_time = reference_time.replace(tzinfo=UTC)

        existing_slots = self.get_existing_scheduled_slots(min_time=reference_time)
        now_eastern = reference_time.astimezone(US_EASTERN)

        # Build candidate windows from config or defaults
        configured_windows = self.settings.schedule.windows
        window_times: list[tuple[time, time]] = []
        for w in configured_windows:
            s_h, s_m = map(int, w.start.split(":"))
            e_h, e_m = map(int, w.end.split(":"))
            window_times.append((time(s_h, s_m), time(e_h, e_m)))

        if not window_times:
            # Fallback default prime-time windows: 12:30 PM & 7:00 PM Eastern
            window_times = [(time(12, 30), time(13, 0)), (time(19, 0), time(21, 0))]

        # Search up to 14 days ahead for next valid slot
        for day_offset in range(14):
            day_eastern = (now_eastern + timedelta(days=day_offset)).date()

            for start_t, end_t in window_times:
                # Target the beginning or mid-window
                target_eastern = datetime.combine(day_eastern, start_t, tzinfo=US_EASTERN)

                # Must be at least min_lead_minutes into the future
                if (target_eastern - now_eastern).total_seconds() < min_lead_minutes * 60:
                    continue

                target_utc = target_eastern.astimezone(UTC)

                # Check spacing against already scheduled slots
                conflict = False
                for ex in existing_slots:
                    if abs((target_utc - ex).total_seconds()) < min_spacing_hours * 3600:
                        conflict = True
                        break

                if not conflict:
                    target_ist = target_eastern.astimezone(IST)
                    logger.info(
                        f"Calculated next publishing slot: [bold green]{target_eastern.strftime('%Y-%m-%d %I:%M %p %Z')}[/bold green] "
                        f"(IST: {target_ist.strftime('%Y-%m-%d %I:%M %p %Z')}, UTC: {target_utc.strftime('%Y-%m-%dT%H:%M:%SZ')})"
                    )
                    return target_utc, target_eastern, target_ist

        # Fallback to 24 hours from reference if full
        fallback_eastern = (now_eastern + timedelta(days=1)).replace(hour=19, minute=0, second=0, microsecond=0)
        return (
            fallback_eastern.astimezone(UTC),
            fallback_eastern,
            fallback_eastern.astimezone(IST),
        )

    def assign_schedule(
        self,
        video: Video,
        reference_time: datetime | None = None,
    ) -> Video:
        """Assigns the next prime-time slot to the Video model and formats timestamps."""
        utc_dt, us_dt, ist_dt = self.calculate_next_slot(reference_time=reference_time)
        video.scheduled_time_utc = utc_dt
        video.scheduled_time_us_eastern = us_dt.isoformat()
        video.scheduled_time_ist = ist_dt.isoformat()
        return video

    @staticmethod
    def build_youtube_publish_at(utc_dt: datetime) -> str:
        """Formats UTC datetime into YouTube Data API RFC 3339 publishAt string (e.g. 2026-11-14T17:00:00Z)."""
        if utc_dt.tzinfo is None:
            utc_dt = utc_dt.replace(tzinfo=UTC)
        else:
            utc_dt = utc_dt.astimezone(UTC)
        return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
