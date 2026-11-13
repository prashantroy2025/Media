"""Unit tests for VisualsManager: NASA, Wikimedia Commons, Ken Burns, and designed card fallbacks."""

from unittest.mock import patch

from nova.config import load_config
from nova.visuals import VisualsManager


def test_keyless_visual_generation(tmp_path):
    """Verifies that with zero API keys, real visuals are generated via NASA/Wikimedia/Commons."""
    settings = load_config()
    vm = VisualsManager(settings)
    # Ensure keys are empty to test keyless path
    vm.pexels_key = ""
    vm.pixabay_key = ""

    dest_mp4 = tmp_path / "scene_nasa_test.mp4"
    asset = vm.get_scene_visual(
        scene_index=0,
        query="neutron star space astronomy",
        duration=2.5,
        dest_video_path=dest_mp4,
        key_stat="6 Billion Tons",
    )

    assert asset is not None
    assert dest_mp4.exists()
    assert dest_mp4.stat().st_size > 10000
    assert asset.provider in ["nasa_media", "wikimedia_commons", "openverse", "designed_card"]


def test_last_resort_designed_card_fallback(tmp_path):
    """Verifies that when all network fetches fail, it falls back to designed card (not plain color)."""
    settings = load_config()
    vm = VisualsManager(settings)
    vm.pexels_key = ""
    vm.pixabay_key = ""

    # Mock all remote fetches to return None
    with (
        patch.object(vm, "_fetch_nasa_media", return_value=None),
        patch.object(vm, "_fetch_wikimedia_commons", return_value=None),
        patch.object(vm, "_fetch_openverse_media", return_value=None),
    ):
        dest_mp4 = tmp_path / "scene_fallback_test.mp4"
        asset = vm.get_scene_visual(
            scene_index=1,
            query="unknown mysterious phenomenon",
            duration=2.0,
            dest_video_path=dest_mp4,
        )

        assert asset is not None
        assert dest_mp4.exists()
        assert asset.provider == "designed_card"
        assert asset.is_fallback_card is True
