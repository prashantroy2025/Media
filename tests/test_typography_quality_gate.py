"""Tests for Intelligent Typography Layout Engine and Visual Storytelling Quality Gate (v9.3)."""

from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import pytest

from nova.typography.engine import TypographyLayoutEngine, get_system_font
from nova.timeline.compositions import DeepSpaceStarfieldComposition
from nova.creative_director import CreativeDirector
from nova.critic import VideoCritic


def test_typography_smart_wrap_preserves_all_words():
    font = get_system_font(40, bold=True)
    dummy_img = Image.new("RGB", (100, 100))
    draw = ImageDraw.Draw(dummy_img)

    long_text = "Animation zooming through sparse star systems passing safely past one another without physical impacts."
    lines = TypographyLayoutEngine.wrap_text_smart(long_text, font, max_width=400, draw=draw)

    # Reconstruct words from lines and verify 100% preservation
    reconstructed_words = " ".join(lines).split()
    original_words = long_text.split()

    assert reconstructed_words == original_words
    assert len(lines) > 1


def test_typography_fit_to_bounds_never_overflows():
    dummy_img = Image.new("RGB", (1080, 1920))
    draw = ImageDraw.Draw(dummy_img)

    headline = "STELLAR VELOCITIES EXCEED MILLIONS OF MILES PER HOUR ACROSS THE GALACTIC PLANE"
    font, lines, max_w, total_h = TypographyLayoutEngine.fit_text_to_bounds(
        text=headline,
        max_width=800,
        max_height=200,
        start_font_size=54,
        min_font_size=24,
        bold=True,
        max_lines=3,
        draw=draw,
    )

    assert max_w <= 800
    assert total_h <= 200
    # Verify all words preserved
    assert " ".join(lines).split() == headline.split()


def test_typography_boundary_validation():
    # Valid box inside margins [60, 100, 1020, 1820]
    assert TypographyLayoutEngine.validate_text_boundaries(100, 300, 980, 700) is True
    # Left edge clipped
    assert TypographyLayoutEngine.validate_text_boundaries(20, 300, 980, 700) is False
    # Right edge clipped
    assert TypographyLayoutEngine.validate_text_boundaries(100, 300, 1050, 700) is False
    # Bottom edge clipped
    assert TypographyLayoutEngine.validate_text_boundaries(100, 300, 980, 1850) is False


def test_creative_director_space_environment_routing():
    director = CreativeDirector(niche="space_science")
    sentences = [
        {
            "id": "S1",
            "text": "so immense, almost none will ever touch.",
            "role": "context",
            "visual_intent": "Animation zooming through sparse star systems passing safely past one another without physical impacts.",
        }
    ]
    decisions = director.direct_scene_plan(sentences, total_duration=2.5)
    assert len(decisions) == 1
    # Must be routed to cinematic space environment, NOT generic card or diagram
    assert decisions[0].recommended_route == "cinematic_space_environment"


def test_deep_space_starfield_composition_generates_dense_stars():
    comp = DeepSpaceStarfieldComposition(width=540, height=960, fps=15, num_stars=60, num_particles=30)
    canvas = Image.new("RGB", (540, 960))
    comp.render_frame(canvas, frame_idx=10, total_frames=30, time_sec=0.66)

    arr = np.array(canvas)
    # Verify canvas is NOT an empty black box (> 5% active colorful luminous pixels)
    luminous_pixels = np.count_nonzero(arr > 35)
    assert luminous_pixels > (540 * 960 * 0.05)


def test_critic_detects_empty_void_defect(tmp_path: Path):
    critic = VideoCritic(output_dir=tmp_path)
    # Create a synthetic empty black MP4
    empty_mp4 = tmp_path / "empty_test.mp4"
    import subprocess
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "color=c=black:s=1080x1920:d=1.5:r=30",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(empty_mp4.resolve())
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    score, defects = critic._check_composition(empty_mp4)
    # Must flag defect for dead black void!
    assert any("empty space" in d.description.lower() for d in defects)
    assert score.score < 100.0
