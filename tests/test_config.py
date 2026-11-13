"""Unit tests for configuration loading and validation."""

from nova.config import load_config


def test_default_config_loading():
    settings = load_config()
    assert settings.app.name == "Nova Autopilot"
    assert settings.content.language == "en"
    assert settings.channel.language == "English"
    assert settings.publishing.publish_mode in ["review", "auto"]
    assert settings.video.width == 1080
    assert settings.video.height == 1920
    assert settings.video.min_duration_seconds >= 20
    assert settings.video.max_duration_seconds <= 45


def test_path_resolution():
    settings = load_config()
    resolved = settings.resolve_path("data/nova.db")
    assert resolved.name == "nova.db"
    assert resolved.is_absolute()
