"""Tests for local publish queue manager, enqueueing, due items, and missed grace periods."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from nova.config import load_config
from nova.db import DatabaseManager, PublishQueue, Script, Video
from nova.publish_queue import PublishQueueManager
from nova.publishers.base import PublishResult


def test_enqueue_video_and_get_due_items():
    settings = load_config()
    db_mgr = DatabaseManager(":memory:")
    session = db_mgr.session()

    script = Script(title="Queue Test Short", scenes_json="[]", facts_used_json="[]", hook="Test hook")
    session.add(script)
    session.commit()

    video = Video(script_id=script.id, video_path="mock.mp4", duration_seconds=25.0)
    session.add(video)
    session.commit()

    queue_mgr = PublishQueueManager(settings, db_mgr)

    # 1. Enqueue in the past (already due)
    past_due_time = datetime.now(UTC) - timedelta(minutes=5)
    item = queue_mgr.enqueue_video(video.id, platform="instagram", scheduled_time_utc=past_due_time)

    assert item is not None
    assert item.status == "pending"

    # 2. Get due items
    due = queue_mgr.get_due_items()
    assert len(due) == 1
    assert due[0].id == item.id

    # 3. Process due items with mock publisher
    mock_pub = MagicMock()
    mock_pub.publish.return_value = {
        "instagram": PublishResult(
            platform="instagram", platform_post_id="ig_123", platform_url="https://instagr.am/p/123", status="success"
        )
    }
    queue_mgr.pub_mgr = mock_pub

    summary = queue_mgr.process_due_items()
    assert summary["succeeded"] == 1
    assert summary["failed"] == 0

    # Verify item status is completed
    session = db_mgr.session()
    updated_item = session.query(PublishQueue).filter(PublishQueue.id == item.id).first()
    assert updated_item.status == "completed"
    assert updated_item.published_at is not None
    session.close()


def test_missed_items_after_grace_period():
    settings = load_config()
    db_mgr = DatabaseManager(":memory:")
    session = db_mgr.session()

    script = Script(title="Old Video", scenes_json="[]", facts_used_json="[]", hook="Old hook")
    session.add(script)
    session.commit()

    video = Video(script_id=script.id, video_path="old.mp4", duration_seconds=25.0)
    session.add(video)
    session.commit()

    # Enqueued 36 hours ago (exceeds default 24h grace period)
    way_past = datetime.now(UTC) - timedelta(hours=36)
    q = PublishQueue(
        video_id=video.id, platform="instagram", scheduled_time_utc=way_past.replace(tzinfo=None), status="pending"
    )
    session.add(q)
    session.commit()
    session.close()

    queue_mgr = PublishQueueManager(settings, db_mgr)
    due = queue_mgr.get_due_items(grace_period_hours=24.0)

    # Should be filtered out of due items and marked missed
    assert len(due) == 0

    session = db_mgr.session()
    updated = session.query(PublishQueue).filter(PublishQueue.id == q.id).first()
    assert updated.status == "missed"
    assert "Missed publishing window" in updated.error_message
    session.close()
