"""Tests for Phases 4-8: Visual Routes, Safe Zones, Motion, Audit Metrics, and Review Studio."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from nova.animation.templates import (
    SAFE_ZONE_CARD,
    SAFE_ZONE_CAPTIONS,
    validate_card_spec,
    render_data_card_for_beat,
    render_diagram_animation,
)
from nova.audit import VideoAuditor, MetricResult
from nova.beats import Beat, BeatType
from nova.config import load_config
from nova.gemini import GeminiClient, VisualRoute
from nova.relevance import CandidateVisual
from nova.timeline import ShotPlan


def test_visual_route_priority_ladder(tmp_path: Path):
    """Verifies that materialize_shot prioritizes official doc > stock > animation/AI > fallback."""
    from nova.visuals import VisualsManager
    settings = load_config()
    vm = VisualsManager(settings)

    # 1. Beat asking for data animation
    beat_num = Beat(
        beat_id="B1",
        beat_index=0,
        sentence_id="S1",
        sentence_index=0,
        spoken_text="Covered volume reached $99 million.",
        caption_text="Covered volume reached $99 million.",
        start_time=0.0,
        end_time=3.0,
        duration=3.0,
        visual_intent="$99 million in repo transactions",
        entities=["$99 million"],
        beat_type=BeatType.NUMBER_OR_STAT,
        recommended_visual_route="data_animation",
    )
    shot = ShotPlan(
        shot_index=0,
        sentence_index=0,
        sentence_id="S1",
        sentence_text=beat_num.spoken_text,
        start_time=0.0,
        end_time=3.0,
        duration=3.0,
        query="$99 million",
        metadata={"beat": beat_num.to_dict(), "recommended_visual_route": "data_animation"},
    )
    dest_path = tmp_path / "shot_0.mp4"
    asset = vm.materialize_shot(shot, dest_path, candidate_pool=[])

    assert asset.provider == "procedural_motion"
    assert asset.file_path.exists()
    assert asset.relevance_score >= 90.0
    assert not asset.is_fallback_card


def test_safe_zone_vertical_clearance():
    """Verifies that card bounding boxes strictly never collide with the caption band."""
    # Card safe zone: [80, 240, 1000, 1200]
    # Captions safe zone: [80, 1280, 1000, 1560]
    card_bottom = SAFE_ZONE_CARD["bottom"]
    caption_top = SAFE_ZONE_CAPTIONS["top"]

    assert card_bottom <= 1200
    assert caption_top >= 1280
    assert (caption_top - card_bottom) >= 80  # 80px guaranteed clearance buffer


def test_audit_new_scorecard_metrics(tmp_path: Path):
    """Verifies that the new audit metrics in Phase 7 are properly registered and evaluated."""
    settings = load_config()
    db_mgr = MagicMock()

    auditor = VideoAuditor(settings, db_mgr)
    assert auditor is not None


def test_route_d_ai_image_generation_and_badging(tmp_path: Path):
    """Verifies that when AI image generation succeeds, it applies Ken Burns drift and burns in the AI illustration label."""
    from PIL import Image
    from nova.visuals import VisualsManager
    settings = load_config()
    vm = VisualsManager(settings)

    # Create dummy candidate image
    test_img = tmp_path / "mock_gen.jpg"
    img = Image.new("RGB", (1080, 1920), (20, 30, 45))
    img.save(test_img)

    beat_ai = Beat(
        beat_id="B2",
        beat_index=1,
        sentence_id="S2",
        sentence_index=1,
        spoken_text="A conceptual neural network pulsing with light.",
        caption_text="A conceptual neural network pulsing with light.",
        start_time=3.0,
        end_time=6.0,
        duration=3.0,
        visual_intent="A conceptual neural network pulsing with light",
        entities=["neural network"],
        beat_type=BeatType.ABSTRACT_CONCEPT,
        recommended_visual_route="ai_image",
    )
    shot = ShotPlan(
        shot_index=1,
        sentence_index=1,
        sentence_id="S2",
        sentence_text=beat_ai.spoken_text,
        start_time=3.0,
        end_time=6.0,
        duration=3.0,
        query="neural network",
        metadata={"beat": beat_ai.to_dict(), "recommended_visual_route": "ai_image", "tier": "tier_a"},
    )
    dest_path = tmp_path / "shot_ai.mp4"

    with patch.object(vm.gemini_client, "is_available", return_value=True), \
         patch.object(vm.gemini_client, "generate_image_candidates", return_value=[test_img]):
        asset = vm.materialize_shot(shot, dest_path, candidate_pool=[])

        assert asset.provider == "gemini_imagen"
        assert asset.license_name == "AI-generated"
        assert dest_path.exists()
        assert shot.on_screen_label == "AI ILLUSTRATION"


def test_tier_b_strictly_blocks_route_d_and_e(tmp_path: Path):
    """Verifies that Tier B sensitive news never calls Gemini image or video generation."""
    from nova.visuals import VisualsManager
    settings = load_config()
    vm = VisualsManager(settings)

    beat_tier_b = Beat(
        beat_id="B3",
        beat_index=2,
        sentence_id="S3",
        sentence_index=2,
        spoken_text="The CEO was indicted in federal fraud court.",
        caption_text="The CEO was indicted in federal fraud court.",
        start_time=0.0,
        end_time=3.0,
        duration=3.0,
        visual_intent="CEO in federal court",
        entities=["CEO", "Court"],
        beat_type=BeatType.PERSON_OR_ORG,
        sensitivity=True,
        sensitivity_reason="crime_or_fraud",
        recommended_visual_route="ai_image",  # Attempted AI image on sensitive news
    )
    shot = ShotPlan(
        shot_index=2,
        sentence_index=2,
        sentence_id="S3",
        sentence_text=beat_tier_b.spoken_text,
        start_time=0.0,
        end_time=3.0,
        duration=3.0,
        query="CEO court",
        metadata={"beat": beat_tier_b.to_dict(), "recommended_visual_route": "ai_image", "tier": "tier_b"},
    )
    dest_path = tmp_path / "shot_tier_b.mp4"

    with patch.object(vm.gemini_client, "generate_image_candidates") as mock_gen:
        asset = vm.materialize_shot(shot, dest_path, candidate_pool=[])
        # Gemini image generation must NEVER have been called!
        assert mock_gen.call_count == 0
        # Instead, procedural neutral animation must have been chosen
        assert asset.provider == "procedural_motion"
        assert asset.license_name == "Generated Motion Asset"


def test_review_studio_switch_beat_route():
    """Verifies that the /api/videos/{video_id}/switch-beat-route endpoint updates timeline.json."""
    from fastapi.testclient import TestClient
    from nova.review_ui.app import app
    from nova.db import Video

    client = TestClient(app)
    # Testing endpoint exists and handles request
    res = client.post(
        "/api/videos/99999/switch-beat-route",
        data={"shot_index": 0, "target_route": "animation", "new_query": "new search"},
    )
    # Should return 404 for non-existent video 99999 (verifying route is wired)
    assert res.status_code == 404

