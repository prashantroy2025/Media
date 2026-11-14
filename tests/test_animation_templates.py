"""Tests for Procedural Data-Driven Animation Templates."""

from pathlib import Path
import pytest
from nova.animation.templates import (
    render_comparison_card,
    render_count_up,
    render_data_card_for_beat,
    render_kinetic_quote,
    render_map_pin,
    render_timeline_card,
)
from nova.beats import Beat, BeatType


def test_render_count_up(tmp_path: Path):
    out_mp4 = tmp_path / "test_count_up.mp4"
    # Render short 1.0 second test clip
    render_count_up(
        number_str="$130 Million",
        label="Nvidia Blackwell Revenue",
        duration=1.0,
        out_path=out_mp4,
        fps=15,
    )

    assert out_mp4.exists()
    assert out_mp4.stat().st_size > 1000

    # Check companion preview thumbnail
    prev_jpg = out_mp4.with_name("test_count_up_prev.jpg")
    assert prev_jpg.exists()
    assert prev_jpg.stat().st_size > 500


def test_render_data_card_for_beat(tmp_path: Path):
    beat = Beat(
        beat_id="B1_1",
        beat_index=0,
        sentence_id="S1",
        sentence_index=0,
        spoken_text="Efficiency jumped by 85 percent.",
        caption_text="Efficiency jumped by 85 percent.",
        start_time=0.0,
        end_time=1.5,
        duration=1.5,
        visual_intent="85% Efficiency Jump",
        entities=["85%"],
        beat_type=BeatType.NUMBER_OR_STAT,
    )

    out_mp4 = tmp_path / "beat_card.mp4"
    render_data_card_for_beat(beat, duration=1.0, out_path=out_mp4, fps=15)
    assert out_mp4.exists()
    assert out_mp4.stat().st_size > 1000
