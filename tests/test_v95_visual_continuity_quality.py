"""Comprehensive Automated Test Suite for NOVA AUTOPILOT v9.5: Visual Continuity & Refined Quality Gate."""

import subprocess
from pathlib import Path
from PIL import Image, ImageDraw
import pytest

from nova.config import load_config
from nova.db import DatabaseManager, Script, Video
from nova.editing.visual_continuity import (
    AdjacentContinuityPair,
    ContinuityReport,
    VisualContinuityAnalyzer,
)
from nova.quality import QualityGate


def test_visual_continuity_analyzer(tmp_path: Path):
    """Verifies adjacent scene evaluation for color, eye-trace, and camera direction."""
    # Create two frames: Shot 1 subject on left, Shot 2 subject on center-right
    img1 = tmp_path / "shot_0_prev.jpg"
    im1 = Image.new("RGB", (1080, 1920), (20, 30, 60))
    d1 = ImageDraw.Draw(im1)
    d1.ellipse([150, 400, 350, 600], fill=(240, 200, 100))
    im1.save(img1)

    img2 = tmp_path / "shot_1_prev.jpg"
    im2 = Image.new("RGB", (1080, 1920), (25, 35, 65))
    d2 = ImageDraw.Draw(im2)
    d2.ellipse([550, 450, 750, 650], fill=(240, 200, 100))
    im2.save(img2)

    class DummyShot:
        def __init__(self, sid, cam):
            self.sentence_id = sid
            self.camera_movement = cam
            self.framing = "medium_shot"

    shots = [DummyShot("S1", "zoom_in"), DummyShot("S2", "zoom_in")]
    analyzer = VisualContinuityAnalyzer()
    report = analyzer.analyze_adjacent_scenes(shots, [img1, img2], ["opening_hook", "context_establishment"])

    assert isinstance(report, ContinuityReport)
    assert report.total_pairs_analyzed == 1
    pair = report.pairs[0]
    assert 0.0 <= pair.overall_continuity_score <= 100.0
    assert pair.camera_direction_match is True
    assert pair.color_continuity_score >= 80.0


def test_quality_gate_differentiates_intentional_darkness(tmp_path: Path):
    """Verifies Phase 7: Intentional darkness (space/stars/typography) does not trigger false black failures."""
    import os, shutil
    ff = "/opt/homebrew/bin/ffmpeg" if os.path.exists("/opt/homebrew/bin/ffmpeg") else (shutil.which("ffmpeg") or "ffmpeg")
    settings = load_config()
    qg = QualityGate(settings)

    # 1. Create a Pillow image with typography/star element in subtitle safe zone
    typo_img = tmp_path / "typo_card.png"
    im = Image.new("RGBA", (800, 200), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle([50, 50, 750, 150], fill=(255, 255, 255, 255))
    im.save(typo_img)

    # 2. Synthetic 1.5s video with deep space black background + overlaid typography element
    test_video = tmp_path / "space_intentional_dark.mp4"
    cmd = [
        ff, "-y",
        "-f", "lavfi", "-i", "color=c=black:s=1080x1920:r=30:d=1.5",
        "-i", str(typo_img.resolve()),
        "-filter_complex", "[0:v][1:v]overlay=(W-w)/2:1300[outv]",
        "-map", "[outv]",
        "-c:v", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p",
        str(test_video.resolve()),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Check black and freeze
    passed, val, reason = qg._check_black_and_freeze(test_video)
    assert passed is True, f"Intentional darkness with typography falsely failed: {reason}"
    assert "creative-verified" in val or "Freeze" in val


def test_rendered_frame_animation_motion_check(tmp_path: Path):
    """Verifies Phase 7: Quality gate inspects actual inter-frame rendered motion."""
    import os, shutil
    ff = "/opt/homebrew/bin/ffmpeg" if os.path.exists("/opt/homebrew/bin/ffmpeg") else (shutil.which("ffmpeg") or "ffmpeg")
    settings = load_config()
    qg = QualityGate(settings)

    # Video with moving box via overlay animation
    test_anim_video = tmp_path / "actual_anim_motion.mp4"
    cmd = [
        ff, "-y",
        "-f", "lavfi", "-i", "color=c=black:s=1080x1920:r=30:d=1.5",
        "-f", "lavfi", "-i", "color=c=red:s=400x400:r=30:d=1.5",
        "-filter_complex", "[0:v][1:v]overlay=x='100+600*t':y=500[outv]",
        "-map", "[outv]",
        "-c:v", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p",
        str(test_anim_video.resolve()),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    passed, motion_energy, msg = qg._check_actual_rendered_animation_quality(test_anim_video, duration=1.5)
    assert passed is True
    assert motion_energy >= 0.3
