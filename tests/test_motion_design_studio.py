"""Automated tests for NOVA AUTOPILOT v9.4: Professional Motion Design Studio."""

from pathlib import Path
from PIL import Image
import pytest

from nova.timeline import (
    BaseComposition,
    CyberneticInterfaceComposition,
    DeepSpaceStarfieldComposition,
    FinancialTrendChartComposition,
    ForensicInspectionLoupeComposition,
    GeographicMapRouteComposition,
    HistoricalTimelineComposition,
    Isometric3DBarChartComposition,
    KineticTypographyComposition,
    MotionDesignStudio,
    ScientificSchematicComposition,
    SplitScreenComparisonComposition,
)


def test_motion_studio_registry_completeness():
    comps = MotionDesignStudio.list_compositions()
    assert "isometric_stats" in comps
    assert "financial_trend" in comps
    assert "geo_map" in comps
    assert "historical_timeline" in comps
    assert "scientific_schematic" in comps
    assert "inspection_loupe" in comps
    assert "split_screen_comparison" in comps
    assert "kinetic_typography" in comps
    assert "cybernetic_interface" in comps
    assert "starfield" in comps


def test_motion_studio_semantic_inference():
    # Financial trend
    c_fin = MotionDesignStudio.infer_composition_from_narration(
        text="The tech sector saw an unprecedented compute surge, with revenue skyrocketing.",
        intent="Market valuation surge",
    )
    assert isinstance(c_fin, FinancialTrendChartComposition)

    # Isometric stats
    c_stat = MotionDesignStudio.infer_composition_from_narration(
        text="Global model capacity expanded by 340 percent over traditional baselines.",
        intent="Statistical metric",
    )
    assert isinstance(c_stat, Isometric3DBarChartComposition)

    # Historical timeline
    c_time = MotionDesignStudio.infer_composition_from_narration(
        text="From its first observed origin in 1965 to modern deep-field discoveries.",
        intent="Historical milestones",
    )
    assert isinstance(c_time, HistoricalTimelineComposition)

    # Geographic route
    c_geo = MotionDesignStudio.infer_composition_from_narration(
        text="High-altitude detectors at Mauna Kea Observatory relayed pulses across the globe.",
        intent="Geographic station",
    )
    assert isinstance(c_geo, GeographicMapRouteComposition)

    # Scientific schematic
    c_sci = MotionDesignStudio.infer_composition_from_narration(
        text="Electrons orbiting the dense atomic nucleus emit quantized photons.",
        intent="Quantum atomic model",
    )
    assert isinstance(c_sci, ScientificSchematicComposition)

    # Forensic inspection
    c_ev = MotionDesignStudio.infer_composition_from_narration(
        text="Forensic inspection revealed an anomalous microscopic signature.",
        intent="Evidence anomaly",
    )
    assert isinstance(c_ev, ForensicInspectionLoupeComposition)

    # Split screen comparison
    c_split = MotionDesignStudio.infer_composition_from_narration(
        text="Theoretical simulations predicted uniform decay, but observed reality differed.",
        intent="Theory versus reality",
    )
    assert isinstance(c_split, SplitScreenComparisonComposition)

    # Cybernetic interface
    c_cyber = MotionDesignStudio.infer_composition_from_narration(
        text="The neural supercomputer streamed telemetry across petabyte data pipelines.",
        intent="AI neural compute cluster",
    )
    assert isinstance(c_cyber, CyberneticInterfaceComposition)

    # Space & starfield
    c_space = MotionDesignStudio.infer_composition_from_narration(
        text="Stars are so immense, almost none will ever touch in the galactic collision.",
        intent="Cosmic passage",
    )
    assert isinstance(c_space, DeepSpaceStarfieldComposition)


def test_composition_frame_rendering():
    canvas = Image.new("RGB", (1080, 1920), (0, 0, 0))

    # Test all 9 motion compositions render into canvas without exceptions
    compositions: list[BaseComposition] = [
        Isometric3DBarChartComposition(),
        FinancialTrendChartComposition(),
        GeographicMapRouteComposition(),
        HistoricalTimelineComposition(),
        ScientificSchematicComposition(),
        ForensicInspectionLoupeComposition(),
        SplitScreenComparisonComposition(),
        KineticTypographyComposition(),
        CyberneticInterfaceComposition(),
    ]

    for comp in compositions:
        comp.render_frame(canvas, frame_idx=15, total_frames=45, time_sec=0.5)
        # Verify canvas is not a pure black blank
        extrema = canvas.getextrema()
        # Ensure red channel has content > 0
        assert extrema[0][1] > 20, f"Component {comp.__class__.__name__} rendered a blank black canvas."


def test_composition_video_export(tmp_path: Path):
    # Test fast 1.0s video export for 3 distinct composition types
    comp_types = [
        ("stats", Isometric3DBarChartComposition(width=270, height=480, fps=15)),
        ("financial", FinancialTrendChartComposition(width=270, height=480, fps=15)),
        ("schematic", ScientificSchematicComposition(width=270, height=480, fps=15)),
    ]

    for name, comp in comp_types:
        out_vid = tmp_path / f"test_{name}.mp4"
        comp.render_to_video(out_vid, duration=1.0, fps=15)

        assert out_vid.exists(), f"Video file {out_vid} was not created."
        assert out_vid.stat().st_size > 1000, f"Video file {out_vid} is too small."

        prev_img = out_vid.with_name(f"test_{name}_prev.jpg")
        assert prev_img.exists(), f"Preview thumbnail {prev_img} was not created."
        assert prev_img.stat().st_size > 500, f"Preview thumbnail {prev_img} is too small."


def test_scene_renderer_with_motion_studio_compositions(tmp_path: Path):
    from nova.timeline import Scene, SceneRenderer

    renderer = SceneRenderer(output_dir=tmp_path)
    scene = Scene(
        scene_id="sc_motion_test",
        scene_index=0,
        name="Financial Surge Scene",
        start_frame=0,
        end_frame=30,
        duration_frames=30,
        duration_seconds=1.0,
        narration_text="Market valuation surged by 340 percent.",
        composition_type="financial_trend",
    )

    rendered_path = renderer.render_scene(scene, fps=15)
    assert Path(rendered_path).exists()
    assert Path(rendered_path).stat().st_size > 1000
    assert scene.status == "rendered"


def test_render_data_card_for_beat_motion_studio_integration(tmp_path: Path):
    from nova.animation.templates import render_data_card_for_beat
    from nova.beats import Beat, BeatType

    beat = Beat(
        beat_id="B_MOTION_1",
        beat_index=0,
        sentence_id="S1",
        sentence_index=0,
        spoken_text="Global compute capacity expanded by 340 percent over traditional baselines.",
        caption_text="Global compute capacity expanded by 340 percent.",
        start_time=0.0,
        end_time=1.0,
        duration=1.0,
        visual_intent="340% capacity expanded metric",
        entities=[],
        beat_type=BeatType.NUMBER_OR_STAT,
    )

    out_mp4 = tmp_path / "beat_motion.mp4"
    render_data_card_for_beat(beat, duration=1.0, out_path=out_mp4, fps=15)

    assert out_mp4.exists()
    assert out_mp4.stat().st_size > 1000
