"""Unit tests for the Quality Gate, Flat-Frame detector, and Contact Sheet generator."""

from PIL import Image

from nova.config import load_config
from nova.db import DatabaseManager, Script, Video
from nova.quality import QualityGate


def test_flat_frame_detection(tmp_path):
    settings = load_config()
    qg = QualityGate(settings)

    # 1. Create a series of flat frames
    flat_dir = tmp_path / "flat_frames"
    flat_dir.mkdir()
    for i in range(5):
        img = Image.new("RGB", (1080, 1920), (30, 30, 30))
        img.save(flat_dir / f"frame_{i:03d}.jpg")

    flat_ratio, _ = qg._analyze_visual_frames(list(flat_dir.glob("*.jpg")), tmp_path / "cs_flat.jpg")
    assert flat_ratio == 1.0, f"Expected 100% flat frames, got {flat_ratio}"


def test_real_photo_passes_flat_check(tmp_path):
    settings = load_config()
    qg = QualityGate(settings)

    # 2. Create real-world visual frame with gradient and texture
    real_dir = tmp_path / "real_frames"
    real_dir.mkdir()
    for i in range(5):
        img = Image.new("RGB", (1080, 1920), (0, 0, 0))
        # Draw gradient/shapes
        from PIL import ImageDraw

        draw = ImageDraw.Draw(img)
        draw.rectangle([100, 100, 900, 1800], fill=(255, 200, 50))
        draw.ellipse([200, 200, 800, 800], fill=(50, 100, 255))
        img.save(real_dir / f"frame_{i:03d}.jpg")

    real_ratio, cs_path = qg._analyze_visual_frames(list(real_dir.glob("*.jpg")), tmp_path / "cs_real.jpg")
    assert real_ratio == 0.0, f"Expected 0% flat frames, got {real_ratio}"
    assert cs_path.exists()


def test_quality_gate_rules(tmp_path):
    settings = load_config()
    qg = QualityGate(settings)

    db_mgr = DatabaseManager(":memory:")
    session = db_mgr.session()

    script = Script(
        title="Valid Test Script",
        hook="A single teaspoon of a neutron star weighs six billion tons.",
        scenes_json="["
        '{"voiceover": "A single teaspoon of a neutron star weighs six billion tons on Earth.", "caption": "6 Billion Tons", "visual_query": "neutron star space", "seconds": 6.0},'
        '{"voiceover": "That is roughly the weight of nine hundred Great Pyramids stacked together on your finger.", "caption": "900 Great Pyramids", "visual_query": "pyramids giza desert", "seconds": 12.0},'
        '{"voiceover": "If you dropped it right now, it would slice right through our planet like a laser through butter.", "caption": "Slice Through Earth", "visual_query": "planet earth cosmic impact", "seconds": 10.0}'
        "]",
        facts_used_json='[{"fact": "6 billion tons", "source_url": "http://nasa.gov"}]',
    )
    session.add(script)
    session.flush()

    # Fake video path
    fake_video = tmp_path / "test_fake.mp4"
    fake_video.write_bytes(b"0" * 100)

    video = Video(
        script_id=script.id,
        video_path=str(fake_video),
        duration_seconds=22.0,
    )
    session.add(video)
    session.commit()

    # We mock _get_media_duration and _analyze_visual_frames to test the rules
    from unittest.mock import patch

    with (
        patch.object(qg, "_get_media_duration", return_value=22.0),
        patch.object(qg, "_extract_frames", return_value=[]),
        patch.object(qg, "_analyze_visual_frames", return_value=(0.0, tmp_path / "contact.jpg")),
    ):
        res = qg.evaluate(fake_video, video)
        assert res.quality_flag == "passed"
        assert res.checks["duration"]["passed"] is True
        assert res.checks["hook_length"]["passed"] is True
        assert res.checks["fact_grounding"]["passed"] is True
        assert res.checks["flat_frame_detection"]["passed"] is True
