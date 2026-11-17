"""Unit tests for Gemini multi-key rotation, failover, cooldown, and exhaustion handling."""

import json
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
    assert _mask_api_key("AIzaSyD-Fn5RskFA4RgtvAfS_-MP8VM0_45YVUc") == "AIza...YVUc"
    assert "Fn5RskFA4RgtvAfS" not in _mask_api_key("AIzaSyD-Fn5RskFA4RgtvAfS_-MP8VM0_45YVUc")


def test_client_multi_key_initialization():
    """Verifies that GeminiClient correctly initializes pool with multiple keys."""
    client = GeminiClient()
    client.api_keys = ["key_A", "key_B", "key_C"]

    assert len(client.api_keys) == 3
    assert client.api_keys == ["key_A", "key_B", "key_C"]
    assert client.is_available() is True
    assert client.api_key == "key_A"


def test_client_round_robin_rotation():
    """Verifies that consecutive requests rotate between available keys in round-robin fashion."""
    client = GeminiClient()
    client.api_keys = ["key_1", "key_2", "key_3"]

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
    assert "key=key_1" in captured_urls[0]
    assert "key=key_2" in captured_urls[1]
    assert "key=key_3" in captured_urls[2]


def test_client_failover_on_429_quota():
    """Verifies that when one key hits 429 quota, the request immediately fails over to the next key."""
    client = GeminiClient()
    client.api_keys = ["key_failing", "key_working"]

    call_count = 0

    def mock_post(url, headers=None, json=None, timeout=None):
        nonlocal call_count
        call_count += 1
        mock_resp = MagicMock()
        if "key=key_failing" in url:
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
    assert "key_failing" in client._exhausted_keys
    # _image_quota_exceeded must still be False because key_working is available!
    assert client._image_quota_exceeded is False


def test_client_exhaustion_when_all_keys_hit_quota():
    """Verifies that when ALL keys in the pool hit quota, _image_quota_exceeded is set and error raised."""
    client = GeminiClient()
    client.api_keys = ["key_1", "key_2"]

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
    assert "key_1" in client._exhausted_keys
    assert "key_2" in client._exhausted_keys
