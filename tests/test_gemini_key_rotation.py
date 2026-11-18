"""Unit tests for Gemini multi-key rotation, failover, cooldown, and exhaustion handling."""

import os
from unittest.mock import MagicMock, patch
import pytest

from nova.config import NovaSettings, load_config
from nova.gemini import GeminiClient, _mask_api_key, _parse_gemini_keys


def test_parse_gemini_keys_deduplication_and_formats():
    """Verifies parsing of multiple keys from comma, semicolon, newline, and lists with deduplication."""
    # Comma-separated
    keys = _parse_gemini_keys("key1, key2, key3")
    assert keys == ["key1", "key2", "key3"]

    # Semicolon and newline separated
    keys = _parse_gemini_keys("key1; key2\nkey3")
    assert keys == ["key1", "key2", "key3"]

    # Duplicates removed while preserving order
    keys = _parse_gemini_keys("key1, key2, key1, key3, key2")
    assert keys == ["key1", "key2", "key3"]

    # Multiple sources
    keys = _parse_gemini_keys("key1", ["key2", "key3"], "key4, key1")
    assert keys == ["key1", "key2", "key3", "key4"]

    # Empty inputs
    assert _parse_gemini_keys("", None, [], "   ") == []


def test_mask_api_key_security():
    """Verifies that API keys are safely masked in log messages without credential leaks."""
    assert _mask_api_key("") == "<none>"
    assert _mask_api_key("12345") == "***"

    # Synthetic mock key format (safe synthetic token avoiding secret scanner false-positives)
    mock_key = "AIza.MOCK.KEY.FOR.TESTING.ONLY.9999"
    masked = _mask_api_key(mock_key)
    assert masked == "AIza...9999"
    assert "MOCK.KEY" not in masked
    assert mock_key[4:-4] not in masked

    # Validate safe masking on environment key when present
    env_key = os.getenv("GEMINI_API_KEY", "").split(",")[0].strip()
    if env_key and len(env_key) > 8 and not env_key.startswith("your_"):
        env_masked = _mask_api_key(env_key)
        assert env_masked.startswith(env_key[:4])
        assert env_masked.endswith(env_key[-4:])
        assert env_key[4:-4] not in env_masked


def test_client_multi_key_initialization(monkeypatch):
    """Verifies that GeminiClient correctly initializes pool with multiple keys."""
    # Isolate environment from ambient credentials
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEYS", "")
    monkeypatch.setenv("GOOGLE_API_KEY", "")

    client = GeminiClient()
    client.api_keys = ["mock_key_A", "mock_key_B", "mock_key_C"]

    assert len(client.api_keys) == 3
    assert client.api_keys == ["mock_key_A", "mock_key_B", "mock_key_C"]
    assert client.is_available() is True
    assert client.api_key == "mock_key_A"


def test_client_round_robin_rotation(monkeypatch):
    """Verifies that consecutive requests rotate between available keys in round-robin fashion."""
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEYS", "")
    monkeypatch.setenv("GOOGLE_API_KEY", "")

    client = GeminiClient()
    client.api_keys = ["mock_key_1", "mock_key_2", "mock_key_3"]

    captured_urls = []

    def mock_post(url, headers=None, json=None, timeout=None):
        captured_urls.append(url)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"candidates": [{"content": {"parts": [{"text": "OK"}]}}]}
        return mock_resp

    with patch("requests.post", side_effect=mock_post):
        client._execute_request("test_endpoint", {})
        client._execute_request("test_endpoint", {})
        client._execute_request("test_endpoint", {})

    assert len(captured_urls) == 3
    assert "key=mock_key_1" in captured_urls[0]
    assert "key=mock_key_2" in captured_urls[1]
    assert "key=mock_key_3" in captured_urls[2]


def test_client_failover_on_429_quota(monkeypatch):
    """Verifies that when one key hits 429 quota, the request immediately fails over to the next key."""
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEYS", "")
    monkeypatch.setenv("GOOGLE_API_KEY", "")

    client = GeminiClient()
    client.api_keys = ["mock_key_failing", "mock_key_working"]

    call_count = 0

    def mock_post(url, headers=None, json=None, timeout=None):
        nonlocal call_count
        call_count += 1
        mock_resp = MagicMock()
        if "key=mock_key_failing" in url:
            mock_resp.status_code = 429
            mock_resp.text = "Quota exceeded for quota metric 'Generate Content API'"
            return mock_resp
        else:
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"candidates": [{"content": {"parts": [{"text": "Success from backup"}]}}]}
            return mock_resp

    with patch("requests.post", side_effect=mock_post):
        res = client._execute_request("test_endpoint", {})

    assert call_count == 2
    assert res == {"candidates": [{"content": {"parts": [{"text": "Success from backup"}]}}]}
    # Key failing must be in exhausted set
    assert "mock_key_failing" in client._exhausted_keys
    # _image_quota_exceeded must still be False because mock_key_working is available!
    assert client._image_quota_exceeded is False


def test_client_exhaustion_when_all_keys_hit_quota(monkeypatch):
    """Verifies that when ALL keys in the pool hit quota, _image_quota_exceeded is set and error raised."""
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEYS", "")
    monkeypatch.setenv("GOOGLE_API_KEY", "")

    client = GeminiClient()
    client.api_keys = ["mock_key_1", "mock_key_2"]

    def mock_post(url, headers=None, json=None, timeout=None):
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.text = "Quota exceeded for user"
        return mock_resp

    with patch("requests.post", side_effect=mock_post):
        with pytest.raises(RuntimeError) as exc_info:
            client._execute_request("test_endpoint", {})

    assert "quota exceeded" in str(exc_info.value).lower()
    assert client._image_quota_exceeded is True
    assert "mock_key_1" in client._exhausted_keys
    assert "mock_key_2" in client._exhausted_keys


def test_client_loads_gemini_api_key_from_env(monkeypatch):
    """Verifies that GeminiClient initializes keys from GEMINI_API_KEY environment variable."""
    monkeypatch.setenv("GEMINI_API_KEY", "mock_env_key_alpha,mock_env_key_beta")
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    client = GeminiClient()
    assert client.api_keys == ["mock_env_key_alpha", "mock_env_key_beta"]
    assert client.api_key == "mock_env_key_alpha"
    assert client.is_available() is True


def test_gemini_live_client_env_credentials_integration():
    """Integration test verifying client loads and respects GEMINI_API_KEY from environment.
    Skips safely when real credentials are unavailable or contain placeholders.
    """
    env_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not env_key or env_key.startswith("your_") or "placeholder" in env_key.lower():
        pytest.skip("GEMINI_API_KEY is not set or contains a placeholder; safely skipping live integration test.")

    client = GeminiClient()
    assert client.is_available() is True
    assert client.api_key is not None
    # Verify no secret is leaked in string representations
    for k in client.api_keys:
        assert k not in repr(client)
        assert k not in str(client)
