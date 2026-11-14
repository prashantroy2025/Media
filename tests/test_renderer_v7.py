"""Unit and Fixture Tests for Nova Autopilot v7.0 Renderer, Timeline, and Quality Gate."""

import subprocess
from pathlib import Path

from PIL import Image

from nova.config import load_config
from nova.quality import QualityGate
from nova.timeline import TimelineBuilder
from nova.visuals import fit_image_shot, fit_video_shot


def test_timeline_builder_gapless():
    """Verifies that the timeline builder creates gapless shots covering 0 -> total_duration with 2-4s cadence."""
    builder = TimelineBuilder(target_shot_min=2.0, target_shot_max=3.8, fps=30)

    class DummyTiming:
        def __init__(self, sentence_id, text, start, end):
            self.sentence_id = sentence_id
            self.text = text
            self.start = start
            self.end = end
            self.duration = end - start

    timings = [
        DummyTiming("S1", "Quantum computing is evolving rapidly.", 0.0, 4.5),
        DummyTiming("S2", "Engineers just achieved unprecedented coherence.", 4.5, 9.2),
        DummyTiming("S3", "This changes cryptographic security forever.", 9.2, 14.0),
    ]
    sentences_data = [
        {"visual_intent": {"queries": ["quantum chip", "laboratory research"], "main_subject": "quantum computer"}},
        {"visual_intent": {"queries": ["laser physics", "cryogenic chamber"], "main_subject": "physics"}},
        {"visual_intent": {"queries": ["cryptography data", "server room"], "main_subject": "server"}},
    ]

    plan = builder.build_timeline(
        sentence_timings=timings,
        total_duration=14.0,
        sentences_data=sentences_data,
        script_id=1,
        niche="ai_tech",
    )

    assert len(plan.shots) >= 4
    assert plan.shots[0].start_time == 0.0
    assert plan.shots[-1].end_time == 14.0

    # Gapless check
    for i in range(len(plan.shots) - 1):
        assert abs(plan.shots[i].end_time - plan.shots[i + 1].start_time) < 0.001

    # Cadence check
    for s in plan.shots:
        assert s.duration >= 1.5
        assert s.duration <= 4.0


def test_fit_video_shot_pingpong(tmp_path):
    """Verifies that a short video clip is cleanly ping-pong looped to the exact target duration and CFR frames."""
    src_clip = tmp_path / "short_clip.mp4"
    out_clip = tmp_path / "normalized_shot.mp4"

    # Create 1.0s clip
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=1.0:size=640x360:rate=30",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(src_clip),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    target_dur = 3.2
    fit_video_shot(src_clip, out_clip, target_duration=target_dur, fps=30)

    assert out_clip.exists()

    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=nb_frames,duration,avg_frame_rate,r_frame_rate",
            "-of",
            "json",
            str(out_clip),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    import json

    data = json.loads(probe.stdout)
    stream = data["streams"][0]
    expected_frames = int(round(target_dur * 30))
    nb_frames = int(stream["nb_frames"])

    assert abs(nb_frames - expected_frames) <= 1
    assert abs(float(stream["duration"]) - target_dur) < 0.05


def test_fit_image_shot_ken_burns(tmp_path):
    """Verifies still image Ken Burns zoom with CFR 30fps and exact duration."""
    img_path = tmp_path / "still.jpg"
    out_mp4 = tmp_path / "kb_shot.mp4"

    img = Image.new("RGB", (1200, 800), color=(70, 130, 180))
    img.save(img_path)

    target_dur = 2.5
    fit_image_shot(img_path, out_mp4, target_duration=target_dur, fps=30, direction="zoom_out")

    assert out_mp4.exists()

    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=nb_frames,duration",
            "-of",
            "json",
            str(out_mp4),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    import json

    data = json.loads(probe.stdout)
    stream = data["streams"][0]
    expected_frames = int(round(target_dur * 30))
    assert abs(int(stream["nb_frames"]) - expected_frames) <= 1


def test_quality_gate_fixtures(tmp_path):
    """Tests Quality Gate against known-bad (empty card) and known-good (rich video) fixtures."""
    settings = load_config()
    gate = QualityGate(settings)

    # Fixture 1: Known bad (flat dark blue card video)
    bad_mp4 = tmp_path / "bad_card_video.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x0e121c:size=1080x1920:duration=3.0:rate=30",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(bad_mp4),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    dense_dir = tmp_path / "dense_bad"
    cs_path = tmp_path / "cs_bad.jpg"
    passed, card_ratio, max_consec, _ = gate._check_content_coverage(bad_mp4, dense_dir, cs_path)

    assert not passed
    assert card_ratio > 0.50

    # Fixture 2: Known good (rich dynamic multi-color visual test source)
    good_mp4 = tmp_path / "good_footage_video.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=duration=3.0:size=1080x1920:rate=30",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(good_mp4),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    dense_dir_good = tmp_path / "dense_good"
    cs_path_good = tmp_path / "cs_good.jpg"
    passed_good, card_ratio_good, _, _ = gate._check_content_coverage(good_mp4, dense_dir_good, cs_path_good)

    assert passed_good
    assert card_ratio_good <= 0.10


def test_review_ui_http_range_requests():
    """Verifies that the Review UI media endpoint correctly handles HTTP 206 Partial Content Range requests."""
    from fastapi.testclient import TestClient

    from nova.review_ui.app import app

    client = TestClient(app)

    # Test Range request on existing media file if available
    media_files = list(Path("output").glob("*.mp4"))
    if media_files:
        test_file = media_files[0]
        # Test relative path
        rel = test_file.name
        res = client.get(f"/media/output/{rel}", headers={"Range": "bytes=0-1000"})
        assert res.status_code == 206
        assert "Content-Range" in res.headers
        assert res.headers["Accept-Ranges"] == "bytes"

    # Test Favicon endpoint
    res_fav = client.get("/favicon.ico")
    assert res_fav.status_code in [200, 204]
