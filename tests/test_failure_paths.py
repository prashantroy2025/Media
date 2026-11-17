"""Failure-path resilience tests for Nova Autopilot.
Ensures graceful degradation without unhandled exceptions.
"""

from pathlib import Path
from unittest.mock import patch

from nova.collectors.base import BaseCollector
from nova.config import load_config
from nova.db import DatabaseManager, Script, Topic, Video
from nova.music import MusicManager
from nova.publishers import PublishingManager
from nova.publishers.instagram import InstagramPublisher
from nova.publishers.youtube import YouTubePublisher
from nova.scriptwriter import Scriptwriter


def test_failure_no_internet_collector():
    """Simulates complete network failure during topic collection."""

    class FailingCollector(BaseCollector):
        def fetch(self):
            raise ConnectionError("Simulated DNS resolution failure / No Internet")

    collector = FailingCollector("failing_source")
    # Must not raise, returns empty list
    results = collector.run_safe()
    assert results == []


def test_failure_empty_music_folder(tmp_path):
    """Simulates empty music directory, ensuring voice-only fallback without crash."""
    settings = load_config()
    settings.music.default_volume = 0.12
    empty_dir = tmp_path / "empty_music"
    empty_dir.mkdir()

    mm = MusicManager(settings)
    mm.music_dir = empty_dir
    track, _ = mm.get_track()
    assert track is None


def test_failure_llm_not_running(tmp_path):
    """Simulates Ollama daemon being offline; raises ScriptGenerationFailedError (no template shipped)."""
    import pytest

    from nova.scriptwriter import ScriptGenerationFailedError

    settings = load_config()
    settings.llm.ollama.host = "http://127.0.0.1:9999"  # non-existent port
    settings.llm.gemini.api_key = None
    settings.llm.groq.api_key = None
    db_mgr = DatabaseManager(tmp_path / "test_llm_fail.db")
    session = db_mgr.session()

    topic = Topic(
        dedupe_hash="offline_test",
        title="Offline Resilience Topic",
        summary="Testing fallback when Ollama is offline.",
        source_name="test",
        source_url="https://test.com",
    )
    session.add(topic)
    session.commit()

    writer = Scriptwriter(settings, db_mgr)
    with pytest.raises(ScriptGenerationFailedError) as exc_info:
        writer.generate_script(topic)
    assert "refusing to ship generic template" in str(exc_info.value).lower()
    session.close()


def test_failure_llm_invalid_json(tmp_path):
    """Simulates LLM producing malformed non-JSON output; raises ScriptGenerationFailedError."""
    import pytest

    from nova.scriptwriter import ScriptGenerationFailedError

    settings = load_config()
    db_mgr = DatabaseManager(tmp_path / "test_json_fail.db")
    session = db_mgr.session()

    topic = Topic(
        dedupe_hash="json_test",
        title="Malformed Output Test",
        summary="Summary",
        source_name="test",
        source_url="https://test.com",
    )
    session.add(topic)
    session.commit()

    writer = Scriptwriter(settings, db_mgr)
    # Stub _call_llm to return plain non-JSON rambling text
    with patch.object(
        writer, "_call_llm", return_value="I am an AI and here is some random story without any JSON braces."
    ):
        with pytest.raises(ScriptGenerationFailedError) as exc_info:
            writer.generate_script(topic)
    assert "refusing to ship generic template" in str(exc_info.value).lower()
    session.close()


def test_failure_missing_credentials():
    """Simulates publishing with missing YouTube/Instagram credentials."""
    settings = load_config()
    settings.youtube.client_secret_file = "non_existent_secret.json"
    settings.youtube.token_file = "non_existent_token.json"
    settings.instagram.access_token = None

    db_mgr = DatabaseManager(":memory:")
    PublishingManager(settings, db_mgr, dry_run=False)

    # Should report error gracefully in PublishResult rather than crashing
    yt_pub = YouTubePublisher(settings)
    yt_pub.alt_token_path = Path("non_existent_alt.json")
    video = Video(id=999, video_path="fake.mp4")
    script = Script(title="T", description="D", hashtags="#T")
    res = yt_pub.publish(video, script)

    assert res.status == "error"
    assert "Missing or invalid" in res.error_message


def test_failure_expired_instagram_token():
    """Simulates expired Instagram token."""
    settings = load_config()
    settings.instagram.access_token = "invalid_or_expired_token_test"
    ig_pub = InstagramPublisher(settings)

    with patch("requests.get") as mock_get:
        mock_get.return_value.json.return_value = {"data": {"expires_at": 1000}}  # Expired long ago
        ok, msg = ig_pub.check_token_expiry()
        assert ok is False
        assert "expires in" in msg.lower() or "expired" in msg.lower() or "refresh" in msg.lower()
