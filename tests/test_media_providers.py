"""Unit & Integration Tests for Media Providers, Licensing Engine & Deduplication."""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from PIL import Image

from nova.licensing.checker import LicenseComplianceEngine
from nova.licensing.credits import CreditsCompiler
from nova.licensing.models import LicenseProof
from nova.providers.base import BaseMediaProvider, MediaCandidate
from nova.providers.cache import ProviderResponseCache
from nova.providers.hasher import compute_dhash, hamming_distance, is_near_duplicate
from nova.providers.rate_limiter import TokenBucketRateLimiter
from nova.providers.registry import ProviderRegistry
from nova.providers.router import DomainRouter


def test_rate_limiter():
    limiter = TokenBucketRateLimiter(requests_per_minute=120)
    assert limiter.acquire() is True
    assert limiter.acquire() is True


def test_response_cache(tmp_path):
    cache = ProviderResponseCache(cache_dir=tmp_path)
    assert cache.get("pixabay", "quantum physics", "video") is None

    candidates = [{"asset_id": "test_01", "provider": "pixabay", "title": "Quantum"}]
    cache.set("pixabay", "quantum physics", "video", candidates)

    cached = cache.get("pixabay", "quantum physics", "video")
    assert cached is not None
    assert cached[0]["asset_id"] == "test_01"


def test_dhash_and_near_duplicate_detection(tmp_path):
    # Create two nearly identical images
    img1 = Image.new("RGB", (100, 100), (30, 30, 30))
    p1 = tmp_path / "img1.png"
    img1.save(p1)

    img2 = Image.new("RGB", (100, 100), (32, 32, 32))
    p2 = tmp_path / "img2.png"
    img2.save(p2)

    # Create distinctly different image
    img3 = Image.new("RGB", (100, 100), (240, 20, 20))
    from PIL import ImageDraw
    draw = ImageDraw.Draw(img3)
    draw.rectangle([10, 10, 80, 80], fill=(0, 255, 0))
    p3 = tmp_path / "img3.png"
    img3.save(p3)

    h1 = compute_dhash(p1)
    h2 = compute_dhash(p2)
    h3 = compute_dhash(p3)

    assert hamming_distance(h1, h2) <= 6
    assert is_near_duplicate(h1, h2, threshold=6) is True
    assert is_near_duplicate(h1, h3, threshold=6) is False


def test_license_compliance_engine():
    engine = LicenseComplianceEngine()

    # Allowed licenses
    ok, proof, _ = engine.evaluate("CC0 1.0", "openverse", "a1", "https://openverse.org/a1")
    assert ok is True
    assert proof.is_public_domain is True
    assert proof.license_id == "cc0"

    ok, proof, _ = engine.evaluate("Pixabay Content License", "pixabay", "p1", "https://pixabay.com/p1")
    assert ok is True
    assert proof.license_id == "pixabay_license"

    ok, proof, _ = engine.evaluate("CC BY 4.0", "wikimedia_commons", "w1", "https://commons.wikimedia.org/w1")
    assert ok is True
    assert proof.attribution_required is True

    # Strictly Rejected licenses
    ok, _, reason = engine.evaluate("CC BY-SA 4.0", "wikimedia_commons", "w2", "https://commons.wikimedia.org/w2")
    assert ok is False
    assert "copyleft" in reason.lower() or "share-alike" in reason.lower()

    ok, _, reason = engine.evaluate("CC BY-NC 4.0", "openverse", "o2", "https://openverse.org/o2")
    assert ok is False
    assert "noncommercial" in reason.lower()

    ok, _, reason = engine.evaluate("CC BY-ND 3.0", "flickr", "f2", "https://flickr.com/f2")
    assert ok is False
    assert "noderivatives" in reason.lower()

    ok, _, reason = engine.evaluate("All Rights Reserved", "shutterstock", "s2", "https://shutterstock.com/s2")
    assert ok is False


def test_credits_compiler(tmp_path):
    proofs = [
        LicenseProof(
            provider="pixabay",
            asset_id="px_123",
            license_id="pixabay_license",
            license_name="Pixabay Content License",
            license_url="https://pixabay.com/service/license-summary/",
            landing_page_url="https://pixabay.com/videos/123",
            creator_name="Jane Doe",
            attribution_required=False,
            attribution_text="Video by Jane Doe from Pixabay",
        ),
        LicenseProof(
            provider="nasa_library",
            asset_id="nasa_456",
            license_id="pd_usgov",
            license_name="US Government Work (Public Domain)",
            license_url="https://www.usa.gov/government-works",
            landing_page_url="https://images.nasa.gov/details/456",
            creator_name="NASA / JPL",
            attribution_required=True,
            attribution_text="Media courtesy of NASA / JPL",
            is_public_domain=True,
        ),
    ]

    c_file, desc_text = CreditsCompiler.compile_credits(video_id=999, license_proofs=proofs, output_dir=tmp_path)
    assert c_file.exists()
    assert "Jane Doe" in desc_text
    assert "NASA / JPL" in desc_text


def test_domain_router():
    router = DomainRouter()
    assert router.detect_domain("mars rover exploration", niche="space_science") == "space"
    assert router.detect_domain("microchip silicon semiconductor", niche="ai_tech") == "tech"
    assert router.detect_domain("stock exchange inflation wall street", niche="business") == "business"

    space_provs = router.get_providers_for_domain("space")
    assert "nasa_library" in space_provs


def test_circuit_breaker():
    class DummyProvider(BaseMediaProvider):
        def test_connection(self):
            return True, "ok"

        def _do_search(self, query, media_type, orientation, min_resolution, limit):
            raise ConnectionError("Mock network drop")

    dummy = DummyProvider(provider_id="dummy", name="Dummy")
    assert dummy.is_circuit_open is False

    # Perform searches that fail
    res1 = dummy.search("test")
    assert res1 == []
    res2 = dummy.search("test")
    assert res2 == []

    # Trip breaker
    dummy.record_failure()
    assert dummy.is_circuit_open is True

    # Circuit open should bypass search immediately
    res3 = dummy.search("test")
    assert res3 == []


def test_sec_gov_provider(monkeypatch):
    from nova.providers.sec_gov import SecGovProvider
    sec = SecGovProvider()

    # Mock tickers
    fake_tickers = {
        "nvda": {"cik": "0001045810", "ticker": "NVDA", "title": "NVIDIA CORP"},
        "nvidia corp": {"cik": "0001045810", "ticker": "NVDA", "title": "NVIDIA CORP"},
    }
    monkeypatch.setattr(sec, "_ensure_tickers", lambda: fake_tickers)

    cands = sec.search(query="Nvidia corporate earnings", media_type="image", limit=2)
    assert len(cands) >= 1
    assert cands[0].provider == "sec_gov"
    assert "NVDA" in cands[0].title
    assert cands[0].license_proof.is_public_domain is True


def test_provider_registry_search_beat(monkeypatch):
    registry = ProviderRegistry()
    # Mock search_all to return deterministic candidates
    mock_candidate = MediaCandidate(
        provider="pixabay",
        asset_id="mock_1",
        media_type="video",
        title="Nvidia cleanroom microchip",
        description="Semiconductor wafer",
        tags=["microchip", "semiconductor"],
        width=1920,
        height=1080,
        duration=5.0,
        preview_url="https://example.com/p.jpg",
        download_url="https://example.com/v.mp4",
        author="Mock Creator",
        landing_page_url="https://example.com/1",
        license_proof=None,
    )
    monkeypatch.setattr(registry, "search_all", lambda **kwargs: [mock_candidate])

    results = registry.search_beat(
        queries=["nvidia blackwell", "semiconductor cleanroom", "microchip tech"],
        media_type="video",
        niche="ai_tech",
    )
    assert len(results) == 1
    assert results[0].asset_id == "mock_1"

