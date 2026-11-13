"""Tests for US Prime-Time scheduling engine and timezone conversion."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from nova.config import load_config
from nova.db import DatabaseManager, Script, Video
from nova.schedule_engine import ScheduleEngine

US_EASTERN = ZoneInfo("America/New_York")
IST = ZoneInfo("Asia/Kolkata")


def test_calculate_next_slot_morning_finds_lunch_peak():
    settings = load_config()
    engine = ScheduleEngine(settings)

    # Reference time: 9:00 AM US Eastern
    ref_dt = datetime(2026, 6, 15, 9, 0, tzinfo=US_EASTERN)
    utc_dt, eastern_dt, ist_dt = engine.calculate_next_slot(reference_time=ref_dt)

    # Should pick 12:00 PM Eastern
    assert eastern_dt.hour == 12
    assert eastern_dt.minute == 0
    assert eastern_dt.date() == ref_dt.date()

    # Verify IST conversion: 12:00 PM EDT (UTC-4) = 4:00 PM UTC = 9:30 PM IST (+5:30)
    assert ist_dt.hour == 21
    assert ist_dt.minute == 30


def test_calculate_next_slot_afternoon_finds_evening_prime():
    settings = load_config()
    engine = ScheduleEngine(settings)

    # Reference time: 2:00 PM US Eastern
    ref_dt = datetime(2026, 6, 15, 14, 0, tzinfo=US_EASTERN)
    utc_dt, eastern_dt, ist_dt = engine.calculate_next_slot(reference_time=ref_dt)

    # Should pick 18:00 (6:00 PM) Eastern
    assert eastern_dt.hour == 18
    assert eastern_dt.minute == 0
    assert eastern_dt.date() == ref_dt.date()


def test_calculate_next_slot_late_night_rolls_to_next_day():
    settings = load_config()
    engine = ScheduleEngine(settings)

    # Reference time: 10:00 PM US Eastern
    ref_dt = datetime(2026, 6, 15, 22, 0, tzinfo=US_EASTERN)
    utc_dt, eastern_dt, ist_dt = engine.calculate_next_slot(reference_time=ref_dt)

    # Should pick 12:00 PM on next day (June 16)
    assert eastern_dt.hour == 12
    assert eastern_dt.date() == (ref_dt.date() + timedelta(days=1))


def test_conflict_avoidance_spacing():
    settings = load_config()
    db_mgr = DatabaseManager(":memory:")
    session = db_mgr.session()

    script = Script(title="Existing Scheduled Video", scenes_json="[]", facts_used_json="[]", hook="Test hook")
    session.add(script)
    session.commit()

    # Pre-schedule a video at 12:00 PM Eastern tomorrow
    existing_eastern = datetime(2026, 6, 16, 12, 0, tzinfo=US_EASTERN)
    existing_utc = existing_eastern.astimezone(UTC)
    vid = Video(script_id=script.id, video_path="test.mp4", scheduled_time_utc=existing_utc)
    session.add(vid)
    session.commit()

    engine = ScheduleEngine(settings, db_mgr=db_mgr)
    ref_dt = datetime(2026, 6, 15, 22, 0, tzinfo=US_EASTERN)

    utc_dt, eastern_dt, ist_dt = engine.calculate_next_slot(reference_time=ref_dt)

    # 12:00 PM is occupied, so it should advance to the next window (18:00 PM)
    assert eastern_dt.hour == 18
    assert eastern_dt.date() == (ref_dt.date() + timedelta(days=1))
    session.close()


def test_youtube_publish_at_formatting():
    dt = datetime(2026, 11, 14, 17, 30, 0, tzinfo=UTC)
    payload = ScheduleEngine.build_youtube_publish_at(dt)
    assert payload == "2026-11-14T17:30:00Z"
