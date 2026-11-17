"""Comprehensive Automated Test Suite for NOVA AUTOPILOT v9.5: Narrative Arc Intelligence."""

import pytest
from nova.editing.narrative_arc import (
    ArcAnalysisResult,
    NarrativeArcAnalyzer,
    NarrativeRole,
    NarrativeSegment,
)


def test_narrative_role_identifications():
    """Verifies that all 8 canonical narrative roles are correctly recognized and assigned."""
    sentences = [
        {"id": "S1", "text": "In four billion years our sky will collide."},
        {"id": "S2", "text": "The Andromeda galaxy is currently racing toward us at 250,000 miles per hour."},
        {"id": "S3", "text": "When these two cosmic titans collide, billions of stars will dance in gravitational chaos."},
        {"id": "S4", "text": "Yet surprisingly, the physical distance between stars is so immense, almost none will ever touch."},
        {"id": "S5", "text": "Instead, vast gas clouds will collide, igniting millions of brilliant new infant suns."},
        {"id": "S6", "text": "Their central supermassive black holes will spiral together in a massive gravitational wave finale."},
        {"id": "S7", "text": "Eventually, a single giant elliptical galaxy forms, leaving behind an astonishing, quiet universe."},
    ]

    analyzer = NarrativeArcAnalyzer(niche="space_science")
    result = analyzer.analyze(sentences, total_duration=28.0)

    assert isinstance(result, ArcAnalysisResult)
    assert result.total_segments == 7
    assert len(result.segments) == 7

    # Check canonical role mapping
    assert result.segments[0].role == NarrativeRole.OPENING_HOOK
    assert result.segments[1].role == NarrativeRole.CONTEXT_ESTABLISHMENT
    assert result.segments[2].role == NarrativeRole.CURIOSITY_BUILDING
    assert result.segments[3].role == NarrativeRole.IMPORTANT_REVELATION
    assert result.segments[4].role == NarrativeRole.EMOTIONAL_PEAK
    assert result.segments[5].role == NarrativeRole.CLIMAX
    assert result.segments[6].role == NarrativeRole.FINAL_PAYOFF


def test_pacing_and_visual_intensity_ranges():
    """Verifies that visual intensity, animation intensity, and pacing weights are properly bounded."""
    sentences = [
        {"id": "S1", "text": "What if humanity lived entirely underground?"},
        {"id": "S2", "text": "Deep beneath the surface, geothermal energy powers subterranean cities."},
        {"id": "S3", "text": "The surprising truth is, volcanic pressure creates catastrophic tremors."},
        {"id": "S4", "text": "Finally, advanced seismic dampeners preserve the fragile habitat."},
    ]

    analyzer = NarrativeArcAnalyzer(niche="ai_tech")
    res = analyzer.analyze(sentences, total_duration=16.0)

    for seg in res.segments:
        assert 0.0 <= seg.visual_intensity <= 1.0
        assert 0.0 <= seg.animation_intensity <= 1.0
        assert 0.5 <= seg.pacing_weight <= 1.5
        assert 0.0 <= seg.tension_target <= 1.0
        assert len(seg.composition_style) > 0
        assert len(seg.camera_dynamics) > 0

    # Hook has high visual intensity
    assert res.segments[0].visual_intensity >= 0.80
    # Climax/revelation has elevated tension
    assert any(s.tension_target >= 0.75 for s in res.segments)


def test_empty_and_short_script_resilience():
    """Verifies safe handling of minimal or single-sentence inputs."""
    analyzer = NarrativeArcAnalyzer()
    res_empty = analyzer.analyze([])
    assert res_empty.total_segments == 0
    assert res_empty.segments == []

    res_single = analyzer.analyze([{"id": "S1", "text": "Supermassive black holes defy physics."}])
    assert res_single.total_segments == 1
    assert res_single.segments[0].role == NarrativeRole.OPENING_HOOK
