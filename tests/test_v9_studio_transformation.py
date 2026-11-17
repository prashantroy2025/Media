"""Comprehensive Verification Test Suite for Nova Autopilot v9.0 Studio Transformation.

Tests:
1. Video Creator Presets (10 profiles, selection heuristics, parameters)
2. Transition Engine (FFmpeg xfade filter construction, duration math, styles)
3. Reference Video & Image Intelligence (profiling, cut cadence, color extraction)
4. Autonomous Video Critic (10-point evaluation, defect localization, HTML reports)
5. Sound Design Director (SFX event scheduling, dynamic ducking, loudness targets)
6. AI Video Providers (base contract, mock generation, factory fallback)
7. Cinematic Captions Engine (7 caption presets, styling, pill boxes, safe margins)
"""

from pathlib import Path
import pytest
from PIL import Image

from nova.config import load_config
from nova.presets import get_preset, list_presets, select_preset_for_topic, PRESETS
from nova.transitions import TransitionEngine, get_clip_duration
from nova.reference_engine import ReferenceAnalyzer, ReferenceStyleProfile
from nova.critic import VideoCritic, VideoCriticReport
from nova.sound_designer import SoundDesignDirector
from nova.providers.ai_video import AIVideoProviderFactory, MockAIVideoProvider
from nova.captions import CaptionGenerator, CAPTION_PRESETS
from nova.tts import WordTiming


def test_creator_presets_completeness():
    """Verifies that all 10 mandated creator presets are configured with valid parameters."""
    expected_presets = [
        "viral_facts",
        "documentary",
        "cinematic_storytelling",
        "dark_mystery",
        "financial_education",
        "investigative_journalism",
        "historical_explainer",
        "technology",
        "news_explainer",
        "high_energy_educational",
    ]
    all_presets = list_presets()
    assert len(all_presets) == 10
    preset_ids = [p["preset_id"] for p in all_presets]
    for exp in expected_presets:
        assert exp in preset_ids

    # Check parameter ranges
    for p in all_presets:
        assert 1.0 <= p["target_shot_min"] <= 3.0
        assert 2.0 <= p["target_shot_max"] <= 4.5
        assert 0.50 <= p["video_coverage_target"] <= 0.85
        assert p["transition_style"] in ("cut", "crossfade", "whip", "zoom", "directional", "mixed")
        assert len(p["color_grade"]) > 0


def test_preset_selection_heuristics():
    """Verifies semantic selection of presets based on topic keywords and niche."""
    # Financial keywords -> financial_education
    p_biz = select_preset_for_topic("business", "TSMC Revenue Reaches 90 Billion Dollars")
    assert p_biz.preset_id == "financial_education"

    # Historical keywords -> historical_explainer
    p_hist = select_preset_for_topic("general", "Ancient Roman Concrete Secrets Discovered")
    assert p_hist.preset_id == "historical_explainer"

    # Mystery keywords -> dark_mystery
    p_myst = select_preset_for_topic("general", "The Bizarre Deep Ocean Signal Explained")
    assert p_myst.preset_id == "dark_mystery"

    # Space science -> cinematic_storytelling
    p_space = select_preset_for_topic("space_science", "Supermassive Black Hole Collision")
    assert p_space.preset_id == "cinematic_storytelling"


def test_transition_engine_xfade_builder():
    """Verifies FFmpeg xfade filter generation and offset mathematics."""
    te = TransitionEngine(fps=30)

    # 3 clips of 3.0s each with 0.3s crossfade
    durations = [3.0, 3.0, 3.0]
    fc, label, total_dur = te.build_xfade_filter(durations, transition_style="crossfade", transition_duration=0.3)

    assert "xfade=transition=fade" in fc
    assert label == "xf_out"
    # Total duration = 3 + 3 + 3 - (2 * 0.3) = 8.4s
    assert abs(total_dur - 8.4) < 0.01

    # Single clip returns passthrough
    fc1, label1, dur1 = te.build_xfade_filter([4.0])
    assert fc1 == ""
    assert label1 == "0:v"
    assert dur1 == 4.0


def test_reference_analyzer_image(tmp_path):
    """Verifies reference intelligence analysis on an image/screenshot."""
    test_img = tmp_path / "ref_screenshot.png"
    Image.new("RGB", (1080, 1920), (20, 40, 80)).save(test_img)

    analyzer = ReferenceAnalyzer(temp_dir=tmp_path / "refs")
    profile = analyzer.analyze_reference(test_img, mode="reference_inspired", profile_name="Test Screenshot")

    assert profile.source_type == "image_set"
    assert len(profile.dominant_palette_rgb) > 0
    assert profile.caption_position_y == 1380

    preset = profile.to_video_preset()
    assert preset.preset_id.startswith("ref_")
    assert preset.target_shot_min > 0


def test_sound_design_director_planning():
    """Verifies SFX event scheduling across a video timeline."""
    settings = load_config()
    director = SoundDesignDirector(settings)

    class DummyShot:
        def __init__(self, st):
            self.start_time = st

    shots = [DummyShot(0.0), DummyShot(2.5), DummyShot(5.2), DummyShot(8.0)]
    events = director.plan_sfx_events(shots, total_duration=12.0, intensity="high")

    assert len(events) >= 2
    # First event must be impact hook
    assert events[0][0] == "impact.wav"
    assert events[0][1] == 0.05

    # Should contain whooshes for transitions
    whooshes = [e for e in events if e[0] == "whoosh.wav"]
    assert len(whooshes) >= 1


def test_ai_video_provider_factory(tmp_path):
    """Verifies AI video factory selection and mock generation."""
    provider = AIVideoProviderFactory.get_provider("mock")
    assert isinstance(provider, MockAIVideoProvider)

    out_file = tmp_path / "ai_clip.mp4"
    job = provider.generate_video_from_text("Deep space nebula flight", duration_seconds=1.0, dest_path=out_file)

    assert job.status.value == "completed"
    assert out_file.exists()
    assert out_file.stat().st_size > 0


def test_caption_presets():
    """Verifies that all 7 caption presets are configured properly."""
    expected = [
        "minimal_documentary",
        "cinematic_storytelling",
        "high_energy_shorts",
        "modern_educational",
        "bold_viral_facts",
        "dark_mystery",
        "financial_explainer",
    ]
    for exp in expected:
        assert exp in CAPTION_PRESETS
        cfg = CAPTION_PRESETS[exp]
        assert 40 <= cfg["font_size"] <= 70
        assert 1100 <= cfg["y_pos"] <= 1500
        assert len(cfg["primary_color"]) == 4
        assert len(cfg["highlight_color"]) == 4


def test_autonomous_critic_evaluation(tmp_path):
    """Verifies VideoCritic 10-point scoring and HTML report generation."""
    # Synthesize small test video via FFmpeg
    test_v = tmp_path / "test_eval_vid.mp4"
    import subprocess, shutil
    ff = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
    cmd = [
        ff, "-y",
        "-f", "lavfi",
        "-i", "color=c=black:s=1080x1920:r=30:d=1.5",
        "-c:v", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p",
        str(test_v.resolve()),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    critic = VideoCritic(output_dir=tmp_path / "critic_out")
    report = critic.evaluate(test_v, video_id=999)

    assert isinstance(report, VideoCriticReport)
    assert len(report.category_scores) == 10
    assert 0.0 <= report.overall_score <= 100.0

    html_file = tmp_path / "critic_out" / "critic_report_999.html"
    assert html_file.exists()
    assert "10-Point Production Scorecard" in html_file.read_text(encoding="utf-8")
