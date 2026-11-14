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
    assert asset.provider in ["nasa_media", "wikimedia", "wikimedia_commons", "openverse", "designed_card"]


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


def test_visual_query_validation_and_cleaning():
    from nova.visuals import generate_concrete_queries, is_valid_visual_query

    # Banned placeholders must be rejected
    assert is_valid_visual_query("concrete noun") is False
    assert is_valid_visual_query("main subject") is False
    assert is_valid_visual_query("visible motion") is False
    assert is_valid_visual_query("high speed engineering") is False
    assert is_valid_visual_query("global network") is False
    assert is_valid_visual_query("breakthrough summary") is False

    # Stopwords and short letters rejected
    assert is_valid_visual_query("A") is False
    assert is_valid_visual_query("the") is False
    assert is_valid_visual_query("in") is False

    # Pure dollar amounts / numbers rejected
    assert is_valid_visual_query("$100 million") is False
    assert is_valid_visual_query("100") is False

    # Abstract words rejected
    assert is_valid_visual_query("breakthrough") is False
    assert is_valid_visual_query("mystery") is False
    assert is_valid_visual_query("pressure") is False
    assert is_valid_visual_query("outbursts") is False

    # Valid physical queries must pass
    assert is_valid_visual_query("neutron star") is True
    assert is_valid_visual_query("server room") is True
    assert is_valid_visual_query("microchip") is True
    assert is_valid_visual_query("apple orchard") is True

    # Concrete query generation produces 3 concrete variants
    space_cands = generate_concrete_queries("A likely supermassive neutron star", "neutron star", niche="space_science")
    assert len(space_cands) == 3
    assert any("neutron star" in q for q in space_cands)
    assert not any(is_valid_visual_query(q) is False for q in space_cands)

    tech_cands = generate_concrete_queries(
        "Blackwell chip features 208 billion transistors", "microchip", niche="ai_tech"
    )
    assert len(tech_cands) == 3
    assert any("chip" in q for q in tech_cands)
    assert not any(is_valid_visual_query(q) is False for q in tech_cands)


def test_materialize_shot_hero_video_procedural_animation(tmp_path):
    """Verifies that when candidates fail relevance gate, procedural data animation is generated instead of flat cards."""
    settings = load_config()
    vm = VisualsManager(settings)

    from nova.timeline import ShotPlan

    shot = ShotPlan(
        shot_index=0,
        sentence_index=0,
        sentence_id="S1",
        sentence_text="TSMC manufactures Nvidia Blackwell microchips in cleanrooms.",
        start_time=0.0,
        end_time=2.0,
        duration=2.0,
        query="tsmc cleanroom microchip",
    )

    dest_shot = tmp_path / "shot_0.mp4"
    # Pass an empty candidate pool (or irrelevant candidates)
    asset = vm.materialize_shot(
        shot=shot,
        dest_shot_path=dest_shot,
        candidate_pool=[],
        used_asset_ids=set(),
    )

    assert asset is not None
    assert dest_shot.exists()
    assert dest_shot.stat().st_size > 1000
    assert asset.provider == "procedural_motion"
    assert asset.is_fallback_card is False
    assert shot.relevance_score >= 90.0

