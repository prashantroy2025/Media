"""Unit and integration tests for Unified Creative Timeline (v9.3)."""

from pathlib import Path
import pytest

from nova.timeline import (
    AudioClip,
    AudioTrack,
    AudioTrackType,
    BaseComposition,
    DeepSpaceStarfieldComposition,
    EasingType,
    Keyframe,
    KeyframeTrack,
    LayerTransform,
    LayerType,
    Scene,
    SceneRenderer,
    ShotPlan,
    Timecode,
    TimelineBuilder,
    TimelinePlan,
    UnifiedProject,
    UnifiedTimelineCompiler,
    VideoLayer,
    apply_easing,
)


def test_timecode_and_easing():
    assert Timecode.seconds_to_frames(2.5, fps=30) == 75
    assert Timecode.frames_to_seconds(75, fps=30) == 2.5
    assert Timecode.format_timecode(75, fps=30) == "00:00:02:15"

    assert apply_easing(0.0, EasingType.LINEAR) == 0.0
    assert apply_easing(1.0, EasingType.LINEAR) == 1.0
    assert 0.0 < apply_easing(0.5, EasingType.EASE_IN_OUT) < 1.0


def test_keyframe_track_interpolation():
    track = KeyframeTrack("opacity")
    track.add_keyframe(frame=0, value=0.0, easing="linear")
    track.add_keyframe(frame=30, value=1.0, easing="linear")

    assert track.evaluate(0) == 0.0
    assert track.evaluate(15) == pytest.approx(0.5, abs=0.01)
    assert track.evaluate(30) == 1.0
    assert track.evaluate(45) == 1.0  # Clamps to last


def test_layer_transform_evaluation():
    trans = LayerTransform(
        x=540.0,
        y=960.0,
        keyframes=[
            Keyframe(frame=0, property_name="x", value=100.0, easing="linear"),
            Keyframe(frame=60, property_name="x", value=700.0, easing="linear"),
        ],
    )
    eval_0 = trans.evaluate_at_frame(0)
    assert eval_0.x == 100.0

    eval_30 = trans.evaluate_at_frame(30)
    assert eval_30.x == pytest.approx(400.0, abs=1.0)


def test_unified_project_validation_and_serialization(tmp_path: Path):
    scene1 = Scene(
        scene_id="sc_0",
        scene_index=0,
        name="Intro Starfield",
        start_frame=0,
        end_frame=60,
        duration_frames=60,
        duration_seconds=2.0,
        narration_text="Zooming through sparse stars...",
        composition_type="starfield",
    )
    scene2 = Scene(
        scene_id="sc_1",
        scene_index=1,
        name="Collision Mechanics",
        start_frame=60,
        end_frame=150,
        duration_frames=90,
        duration_seconds=3.0,
        narration_text="Almost none will ever touch.",
        composition_type="starfield",
    )

    proj = UnifiedProject(
        project_id="test_proj_001",
        title="Cosmic Collision Master",
        schema_version="9.3",
        fps=30,
        duration_frames=150,
        duration_seconds=5.0,
        scenes=[scene1, scene2],
    )

    errors = proj.validate()
    assert len(errors) == 0

    # Save to JSON
    json_path = tmp_path / "project.json"
    proj.save_project(json_path)
    assert json_path.exists()

    # Restore from JSON
    restored = UnifiedProject.load_project(json_path)
    assert restored.project_id == "test_proj_001"
    assert len(restored.scenes) == 2
    assert restored.scenes[1].narration_text == "Almost none will ever touch."


def test_legacy_timeline_plan_conversion():
    shots = [
        ShotPlan(
            shot_index=0,
            sentence_index=0,
            sentence_id="S1",
            sentence_text="First sentence.",
            start_time=0.0,
            end_time=2.5,
            duration=2.5,
            query="sparse stars passing",
        ),
        ShotPlan(
            shot_index=1,
            sentence_index=1,
            sentence_id="S2",
            sentence_text="Second sentence.",
            start_time=2.5,
            end_time=5.0,
            duration=2.5,
            query="nebula clouds",
        ),
    ]
    legacy_plan = TimelinePlan(total_duration=5.0, fps=30, shots=shots, script_id=15)
    proj = legacy_plan.to_unified_project()

    assert proj.project_id == "proj_15"
    assert len(proj.scenes) == 2
    assert proj.scenes[0].composition_type == "starfield"
    assert proj.duration_frames == 150


def test_deep_space_starfield_composition_rendering(tmp_path: Path):
    comp = DeepSpaceStarfieldComposition(width=270, height=480, fps=15, num_stars=30, num_particles=15)
    out_video = tmp_path / "test_starfield.mp4"
    comp.render_to_video(out_video, duration=1.0, fps=15)

    assert out_video.exists()
    assert out_video.stat().st_size > 1000
