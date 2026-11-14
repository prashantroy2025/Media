"""Unit tests for Phase 2 & Phase 3: Gemini Shot Planner, Schema Validation, Visual Routes, and Cost Caps."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from nova.beats import Beat, BeatPlanner, BeatType, VideoShotPlan
from nova.config import load_config
from nova.gemini import (
    GeminiBeatItem,
    GeminiClient,
    GeminiShotPlanResponse,
    GeminiUsageTracker,
    VisualRoute,
    BeatSensitivity,
)
from nova.tts import WordTiming


def test_gemini_schema_validation():
    """Verifies that valid JSON correctly parses into GeminiShotPlanResponse and rejects invalid schemas."""
    valid_data = {
        "beats": [
            {
                "beat_id": "B1_1",
                "spoken_text": "Scientists discovered a 5,000-year-old skull.",
                "visual_intent": "Ancient excavated skull in archaeological dig site",
                "entities": ["5,000-year-old", "Ancient Egypt"],
                "beat_type": "concrete_object",
                "sensitivity": "none",
                "recommended_visual_route": "stock_footage",
                "search_queries": ["archaeology ancient skull egypt", "excavation dig site"],
                "reason": "Clear concrete artifact suitable for museum stock footage",
            }
        ]
    }
    resp = GeminiShotPlanResponse(**valid_data)
    assert len(resp.beats) == 1
    assert resp.beats[0].beat_type == BeatType.CONCRETE_OBJECT
    assert resp.beats[0].recommended_visual_route == VisualRoute.STOCK_FOOTAGE

    # Invalid beat_type must fail validation
    invalid_data = {
        "beats": [
            {
                "beat_id": "B1_1",
                "spoken_text": "Sample",
                "visual_intent": "Sample",
                "beat_type": "invalid_unknown_type",
                "recommended_visual_route": "stock_footage",
            }
        ]
    }
    with pytest.raises(Exception):
        GeminiShotPlanResponse(**invalid_data)


def test_grounded_numbers_verification():
    """Verifies that hallucinated statistics not present in facts are strictly rejected."""
    client = GeminiClient()
    facts = ["The SEC proposed new disclosure rules for fiscal year 2026.", "Covered volume reached $130 million."]

    # Valid beat: 130 million is grounded
    valid_beat = GeminiBeatItem(
        beat_id="B1_1",
        spoken_text="Transactions totaled $130 million.",
        visual_intent="Financial report showing 130 million",
        entities=["$130 million", "SEC"],
        beat_type=BeatType.NUMBER_OR_STAT,
        recommended_visual_route=VisualRoute.DATA_ANIMATION,
    )
    assert client._verify_grounded_numbers([valid_beat], facts) is True

    # Hallucinated beat: 99 billion is NOT in facts
    hallucinated_beat = GeminiBeatItem(
        beat_id="B1_2",
        spoken_text="A massive 99 billion was exempt.",
        visual_intent="Chart with 99 billion",
        entities=["99 billion"],
        beat_type=BeatType.NUMBER_OR_STAT,
        recommended_visual_route=VisualRoute.DATA_ANIMATION,
    )
    assert client._verify_grounded_numbers([hallucinated_beat], facts) is False


def test_planner_fallback_on_api_failure():
    """Verifies that when Gemini API is unavailable, the planner falls back to the local rule-based planner."""
    client = GeminiClient()
    client.enabled = True
    client.api_key = "test_fake_key"

    sentences = [
        {"text": "The Treasury Department just gave broker-dealers a major break.", "start_time": 0.0, "end_time": 3.34, "script_id": 1},
        {"text": "This exemption applies to inter-affiliate and non-U.S. repo transactions.", "start_time": 3.34, "end_time": 6.8, "script_id": 1},
    ]
    words = [
        WordTiming(word="The", start=0.0, end=0.4),
        WordTiming(word="Treasury", start=0.4, end=0.9),
        WordTiming(word="Department", start=0.9, end=1.5),
        WordTiming(word="break.", start=1.5, end=3.34),
        WordTiming(word="This", start=3.34, end=3.8),
        WordTiming(word="exemption", start=3.8, end=4.5),
        WordTiming(word="transactions.", start=4.5, end=6.8),
    ]

    # Mock API call failure
    with patch.object(client, "_execute_request", side_effect=RuntimeError("API Quota Exceeded")):
        plan = client.plan_shot_beats(
            sentences=sentences,
            word_timings=words,
            facts_used=[{"claim": "SEC exemptive relief release 2026"}],
            total_duration=6.8,
            niche="business",
            tier="tier_a",
        )

        assert isinstance(plan, VideoShotPlan)
        assert len(plan.beats) >= 2
        # All beats must be gapless
        assert plan.beats[0].start_time == 0.0
        assert abs(plan.beats[-1].end_time - 6.8) < 0.01


def test_tier_b_restrictions_override_ai():
    """Verifies that Tier B sensitive news topics strictly forbid AI images and AI videos."""
    client = GeminiClient()
    client.enabled = True
    client.api_key = "test_fake_key"

    sentences = [{"text": "Executives were charged in a $130 million fraud scheme.", "start_time": 0.0, "end_time": 4.0, "script_id": 2}]
    words = [WordTiming(word="Executives", start=0.0, end=1.0), WordTiming(word="scheme.", start=1.0, end=4.0)]

    mock_gemini_json = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": json.dumps({
                                "beats": [
                                    {
                                        "beat_id": "B1_1",
                                        "spoken_text": "Executives were charged in a $130 million fraud scheme.",
                                        "visual_intent": "Defendants walking in courtroom",
                                        "entities": ["Executives", "Court"],
                                        "beat_type": "person_or_org",
                                        "sensitivity": "crime_or_fraud",
                                        "recommended_visual_route": "ai_image",  # Attempted AI image on sensitive news!
                                        "search_queries": ["court trial"],
                                        "reason": "Courtroom illustration",
                                    }
                                ]
                            })
                        }
                    ]
                }
            }
        ]
    }

    with patch.object(client, "_execute_request", return_value=mock_gemini_json):
        plan = client.plan_shot_beats(
            sentences=sentences,
            word_timings=words,
            facts_used=[{"claim": "Charges filed in 130 million fraud case"}],
            total_duration=4.0,
            niche="business",
            tier="tier_b",  # Tier B news topic
        )

        beat = plan.beats[0]
        # Must be overridden away from ai_image
        assert getattr(beat, "recommended_visual_route", "") != VisualRoute.AI_IMAGE.value
        assert beat.sensitivity is True


def test_budget_and_cost_cap_enforcement(tmp_path: Path):
    """Verifies that daily spend limits are enforced and stop costly generations when cap reached."""
    tracker_file = tmp_path / "gemini_usage.json"
    tracker = GeminiUsageTracker(tracker_file)

    # Initial check under budget
    assert tracker.can_spend(0.05, daily_budget=1.0) is True

    # Spend $0.98
    tracker.record_cost(0.98)
    # Attempting to spend $0.05 more would exceed $1.00 budget
    assert tracker.can_spend(0.05, daily_budget=1.0) is False

    summary = tracker.get_summary()
    assert summary["spent_usd"] == 0.98
    assert summary["calls"] == 1


def test_style_bible_consistency():
    """Verifies that every niche produces a clear, distinct 9:16 style bible."""
    client = GeminiClient()
    ai_bible = client.get_style_bible("ai_tech")
    space_bible = client.get_style_bible("space_science")
    biz_bible = client.get_style_bible("business")

    assert "9:16" in ai_bible and "cyan" in ai_bible.lower()
    assert "9:16" in space_bible and "cosmic" in space_bible.lower()
    assert "9:16" in biz_bible and "emerald" in biz_bible.lower()
