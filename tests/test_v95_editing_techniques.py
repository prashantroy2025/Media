"""Comprehensive Automated Test Suite for NOVA AUTOPILOT v9.5: Editing Techniques & Tension Engine."""

from pathlib import Path
from PIL import Image
import pytest

from nova.editing.narrative_arc import NarrativeArcAnalyzer
from nova.editing.techniques import (
    ColorHarmonizer,
    ColorProfile,
    ProfessionalEditingEngine,
    ProfessionalTransitionType,
    TransitionDescriptor,
)
from nova.editing.tension_engine import (
    EditorialModulation,
    TensionEngine,
    TensionPoint,
    TensionState,
)


def test_tension_curve_dynamics():
    """Verifies adaptive tension curve construction and state classification."""
    sentences = [
        {"id": "S1", "text": "In four billion years our sky will collide."},
        {"id": "S2", "text": "The Andromeda galaxy is currently racing toward us at 250,000 miles per hour."},
        {"id": "S3", "text": "Yet surprisingly, the physical distance between stars is so immense, almost none will ever touch."},
        {"id": "S4", "text": "Their central supermassive black holes will spiral together in a massive gravitational wave finale."},
        {"id": "S5", "text": "Eventually, a single giant elliptical galaxy forms, leaving behind an astonishing, quiet universe."},
    ]

    arc = NarrativeArcAnalyzer().analyze(sentences, total_duration=20.0)
    engine = TensionEngine(min_shot_dur=1.4, max_shot_dur=4.2)
    curve = engine.build_tension_curve(arc, total_duration=20.0)

    assert len(curve) >= 5
    # Verify opening is energetic (urgent / dramatic)
    assert curve[0].tension >= 0.70
    # Verify climax peak
    climax_pts = [p for p in curve if p.sentence_id == "S4"]
    assert len(climax_pts) >= 1
    assert climax_pts[0].tension >= 0.85

    # Verify interpolation at various timestamps
    mod_calm = engine.evaluate_at(5.0, curve)
    assert isinstance(mod_calm, EditorialModulation)
    assert mod_calm.target_shot_duration > 1.8

    mod_climax = engine.evaluate_at(14.0, curve)
    assert mod_climax.tension >= 0.80
    assert mod_climax.motion_intensity >= 0.75
    assert mod_climax.camera_zoom_factor >= 1.15


def test_color_harmonizer_extraction_and_filter(tmp_path: Path):
    """Verifies photometric color profiling and FFmpeg eq adjustment computation."""
    # Create two frames with deliberate temperature/luminance differences
    f1 = tmp_path / "warm_bright.png"
    Image.new("RGB", (1080, 1920), (220, 180, 120)).save(f1)

    f2 = tmp_path / "cool_dark.png"
    Image.new("RGB", (1080, 1920), (40, 60, 110)).save(f2)

    prof1 = ColorHarmonizer.extract_profile(f1)
    prof2 = ColorHarmonizer.extract_profile(f2)

    assert prof1.mean_luminance > prof2.mean_luminance
    assert prof1.color_temp_ratio > prof2.color_temp_ratio

    filter_cmd = ColorHarmonizer.compute_matching_filter(prof1, prof2)
    assert "eq=" in filter_cmd
    assert "colorbalance=" in filter_cmd


def test_professional_transition_design():
    """Verifies J-cut, L-cut, whip pan, and dissolve selections based on narrative state."""
    engine = ProfessionalEditingEngine()

    # Revelation with high tension -> J-Cut
    t_rev = engine.design_scene_transition(
        prev_shot=None,
        curr_shot=None,
        narrative_tension=0.75,
        narrative_role="important_revelation",
    )
    assert t_rev.transition_type == ProfessionalTransitionType.J_CUT
    assert t_rev.audio_lead_seconds > 0.0

    # Conclusion -> L-Cut
    t_concl = engine.design_scene_transition(
        prev_shot=None,
        curr_shot=None,
        narrative_tension=0.45,
        narrative_role="conclusion",
    )
    assert t_concl.transition_type == ProfessionalTransitionType.L_CUT
    assert t_concl.audio_lag_seconds > 0.0

    # Extreme tension climax -> Whip pan
    t_climax = engine.design_scene_transition(
        prev_shot=None,
        curr_shot=None,
        narrative_tension=0.92,
        narrative_role="climax",
    )
    assert t_climax.transition_type == ProfessionalTransitionType.WHIP_PAN
