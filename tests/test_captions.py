"""Unit tests for subtitle timing, ASS format compliance, and styling."""

from nova.captions import CaptionGenerator, _format_ass_time
from nova.config import load_config
from nova.tts import WordTiming


def test_ass_time_conversion():
    assert _format_ass_time(0.0) == "0:00:00.00"
    assert _format_ass_time(4.25) == "0:00:04.25"
    assert _format_ass_time(65.12) == "0:01:05.12"
    assert _format_ass_time(3665.50) == "1:01:05.50"


def test_caption_file_creation(tmp_path):
    settings = load_config()
    captioner = CaptionGenerator(settings)

    words = [
        WordTiming(word="Bhai", start=0.0, end=0.4),
        WordTiming(word="suno!", start=0.4, end=0.8),
        WordTiming(word="Crazy", start=0.8, end=1.2),
        WordTiming(word="AI", start=1.2, end=1.5),
        WordTiming(word="update", start=1.5, end=2.0),
        WordTiming(word="aaya", start=2.0, end=2.4),
        WordTiming(word="hai.", start=2.4, end=2.8),
    ]

    out_file = tmp_path / "subtitles_test.ass"
    res_path = captioner.create_ass_file(words, out_file)

    assert res_path.exists()
    content = res_path.read_text(encoding="utf-8")

    assert "[Script Info]" in content
    assert "PlayResX: 1080" in content
    assert "PlayResY: 1920" in content
    assert "[V4+ Styles]" in content
    assert "[Events]" in content
    assert "Dialogue: 0," in content
    # Check that word highlight tag is present
    assert "\\c&H0000FFFF&" in content
