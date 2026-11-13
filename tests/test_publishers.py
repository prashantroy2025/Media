"""Unit tests for publishing interfaces, MockPublisher, and daily caps."""

from datetime import UTC, datetime

from nova.config import load_config
from nova.db import DatabaseManager, Publication, Script, Topic, Video
from nova.publishers import PublishingManager


def test_mock_publisher(tmp_path):
    settings = load_config()
    db_mgr = DatabaseManager(tmp_path / "pub_test.db")
    session = db_mgr.session()

    topic = Topic(dedupe_hash="pub_hash", title="Test Pub", source_name="src")
    session.add(topic)
    session.commit()

    script = Script(
        topic_id=topic.id,
        title="Test Pub Title",
        hook="Hook",
        scenes_json="[]",
        cta="CTA",
        hashtags="#Test",
        description="Desc",
    )
    session.add(script)
    session.commit()

    video = Video(
        script_id=script.id,
        video_path=str(tmp_path / "mock.mp4"),
        duration_seconds=25.0,
        status="pending_review",
    )
    session.add(video)
    session.commit()
    video_id = video.id
    session.close()

    pub_mgr = PublishingManager(settings, db_mgr, dry_run=True)
    results = pub_mgr.publish_video(video_id)

    assert len(results) >= 1
    assert any(r.platform == "youtube" and r.status == "success" for r in results)

    # Check publication record in DB
    s2 = db_mgr.session()
    saved_pubs = s2.query(Publication).filter(Publication.video_id == video_id).all()
    assert len(saved_pubs) >= 1
    assert saved_pubs[0].status == "success"
    assert "mock_" in saved_pubs[0].platform_post_id

    # Check updated video status
    updated_video = s2.query(Video).filter(Video.id == video_id).first()
    assert updated_video.status == "published"
    s2.close()


def test_daily_publishing_cap(tmp_path):
    settings = load_config()
    settings.publishing.daily_cap = 2
    db_mgr = DatabaseManager(tmp_path / "cap_test.db")
    session = db_mgr.session()

    topic = Topic(dedupe_hash="cap_hash", title="Cap Test", source_name="src")
    session.add(topic)
    session.commit()
    script = Script(topic_id=topic.id, title="Cap Title", hook="H", scenes_json="[]")
    session.add(script)
    session.commit()
    video = Video(script_id=script.id, video_path="v.mp4")
    session.add(video)
    session.commit()

    # Add 2 publications today
    now = datetime.now(UTC)
    p1 = Publication(video_id=video.id, platform="youtube", status="success", published_at=now)
    p2 = Publication(video_id=video.id, platform="instagram", status="success", published_at=now)
    session.add_all([p1, p2])
    session.commit()
    session.close()

    pub_mgr = PublishingManager(settings, db_mgr, dry_run=True)
    can_pub, reason = pub_mgr.can_publish_today()
    assert can_pub is False
    assert "Daily publishing cap reached" in reason
