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


def test_env_example_is_sanitized():
    """Verifies that .env.example contains zero real secrets and only descriptive placeholders."""
    from nova.config import PROJECT_ROOT

    example_path = PROJECT_ROOT / ".env.example"
    assert example_path.exists(), ".env.example must exist in project root"

    with open(example_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            assert "=" in line, f"Malformed line in .env.example: {line}"
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip()

            # Ensure no API key or token looks like a real credential
            if key in ["NASA_API_KEY"]:
                assert val == "DEMO_KEY" or "your_" in val
            elif "KEY" in key or "TOKEN" in key or "SECRET" in key:
                if val.startswith("./") or "/" in val:
                    # File path placeholder
                    assert "client_secret" in val or "service-account" in val or "youtube_token" in val
                else:
                    assert "your_" in val, f"Key {key} in .env.example must have 'your_' placeholder, got: {val}"


def test_gemini_missing_credentials_error(monkeypatch):
    """Verifies that missing Gemini credentials raise a clear and helpful error."""
    import pytest
    from nova.gemini import GeminiClient

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    settings = load_config()
    settings.gemini.api_key = None
    settings.llm.gemini.api_key = None

    client = GeminiClient(settings)
    assert not client.is_available()

    with pytest.raises(RuntimeError) as exc_info:
        client._execute_request("models/gemini-3.8-flash:generateContent", {})
    assert "GEMINI_API_KEY" in str(exc_info.value)


def test_gemini_google_api_key_fallback(monkeypatch):
    """Verifies that GOOGLE_API_KEY is used when GEMINI_API_KEY is unset."""
    from nova.gemini import GeminiClient

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "test_google_key_fallback_12345")

    settings = load_config()
    client = GeminiClient(settings)
    assert client.api_key == "test_google_key_fallback_12345"
    assert client.is_available()
