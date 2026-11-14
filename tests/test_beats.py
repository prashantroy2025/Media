"""Tests for Beat-Level Shot Planning, Entity Extraction, and Intent Architecture."""

from pathlib import Path
import pytest
from nova.beats import Beat, BeatPlanner, BeatType, VideoShotPlan
from nova.tts import WordTiming


def test_extract_entities():
    text = "Nvidia Blackwell chips cost over $30,000 each, while TSMC in Taiwan handles 90% of global advanced semiconductor manufacturing."
    entities = BeatPlanner.extract_entities(text)

    # Check currency
    assert any("$30,000" in e for e in entities)
    # Check percentage
    assert any("90%" in e for e in entities)
    # Check multi-word capitalized
    assert "Nvidia Blackwell" in entities
    # Check acronyms
    assert "TSMC" in entities
    # Check domain terms
    assert "Semiconductor" in entities or "Nvidia" in entities


def test_classify_beat_types():
    # Number or Stat
    assert BeatPlanner.classify_beat_type("Market cap reached $3 trillion.", ["$3 trillion"]) == BeatType.NUMBER_OR_STAT
    assert BeatPlanner.classify_beat_type("Efficiency improved by 45%.", ["45%"]) == BeatType.NUMBER_OR_STAT

    # Comparison
    assert BeatPlanner.classify_beat_type("Blackwell is 4x faster compared to Hopper.", []) == BeatType.COMPARISON

    # Timeline
    assert BeatPlanner.classify_beat_type("In 2024, AI datacenters consumed unprecedented power.", []) == BeatType.TIMELINE

    # Quote
    assert BeatPlanner.classify_beat_type('Jensen Huang said "Computing has changed forever."', []) == BeatType.QUOTE

    # Place
    assert BeatPlanner.classify_beat_type("Deep underground in Taiwan, cleanrooms operate 24/7.", []) == BeatType.PLACE

    # Person or Org
    assert BeatPlanner.classify_beat_type("The SEC launched an investigation into the firm.", []) == BeatType.PERSON_OR_ORG

    # Process
    assert BeatPlanner.classify_beat_type("Lasers slice through the silicon wafer with nanometer precision.", []) == BeatType.PROCESS

    # Concrete Object
    assert BeatPlanner.classify_beat_type("Each microchip contains billions of microscopic transistors.", []) == BeatType.CONCRETE_OBJECT


def test_check_sensitivity():
    # Innocent tech
    sens, reason = BeatPlanner.check_sensitivity("Nvidia released a new graphic card architecture.", [])
    assert not sens
    assert reason == ""

    # Sensitive keyword: fraud / charged
    sens, reason = BeatPlanner.check_sensitivity("Executives were charged with accounting fraud and money laundering.", [])
    assert sens
    assert "fraud" in reason or "charged" in reason

    # Tier B sensitive topic override
    sens, reason = BeatPlanner.check_sensitivity("A legal hearing took place today.", [], tier="tier_b")
    assert sens
    assert "Tier B" in reason


def test_generate_query_variants():
    queries = BeatPlanner.generate_query_variants(
        phrase="TSMC fabricates silicon wafers in high tech cleanrooms",
        main_subject="semiconductor fabrication",
        entities=["TSMC", "Silicon Wafer"],
        b_type=BeatType.PROCESS,
        raw_queries=["semiconductor cleanroom"],
        niche="ai_tech",
    )
    assert len(queries) >= 3
    assert len(queries) <= 6
    assert any("tsmc" in q.lower() for q in queries)


def test_plan_video_beats_continuity():
    class MockSentence:
        def __init__(self, sid, text, start, end):
            self.sentence_id = sid
            self.text = text
            self.start_time = start
            self.end_time = end

    sentences = [
        MockSentence("S1", "Nvidia just unveiled the Blackwell chip.", 0.0, 3.2),
        MockSentence("S2", "It delivers four times faster training speeds and consumes significantly less electricity.", 3.2, 7.8),
        MockSentence("S3", "TSMC manufactures every wafer in specialized Taiwan cleanrooms.", 7.8, 12.0),
    ]

    # Generate synthetic word timings
    words = []
    # S1 words
    s1_words = ["Nvidia", "just", "unveiled", "the", "Blackwell", "chip."]
    t = 0.0
    for w in s1_words:
        words.append(WordTiming(word=w, start=round(t, 2), end=round(t + 0.5, 2)))
        t += 0.53

    # S2 words (long sentence that should split)
    s2_words = ["It", "delivers", "four", "times", "faster", "training", "speeds,", "and", "consumes", "significantly", "less", "electricity."]
    t = 3.2
    for w in s2_words:
        words.append(WordTiming(word=w, start=round(t, 2), end=round(t + 0.35, 2)))
        t += 0.38

    # S3 words
    s3_words = ["TSMC", "manufactures", "every", "wafer", "in", "specialized", "Taiwan", "cleanrooms."]
    t = 7.8
    for w in s3_words:
        words.append(WordTiming(word=w, start=round(t, 2), end=round(t + 0.5, 2)))
        t += 0.52

    plan = BeatPlanner.plan_video_beats(
        sentence_timings=sentences,
        word_timings=words,
        video_id=101,
        script_id=202,
        total_duration=12.0,
        niche="ai_tech",
        tier="tier_a",
    )

    assert plan.video_id == 101
    assert len(plan.beats) >= 3

    # Continuity check: beats must start at 0.0, end at total_duration, and be strictly gapless
    assert plan.beats[0].start_time == 0.0
    assert abs(plan.beats[-1].end_time - 12.0) < 0.05

    for i in range(len(plan.beats) - 1):
        assert abs(plan.beats[i].end_time - plan.beats[i + 1].start_time) < 1e-3
        assert plan.beats[i].duration > 0


def test_shot_plan_json_roundtrip(tmp_path: Path):
    beat = Beat(
        beat_id="B1_1",
        beat_index=0,
        sentence_id="S1",
        sentence_index=0,
        spoken_text="Testing beat serialization.",
        caption_text="Testing beat serialization.",
        start_time=0.0,
        end_time=3.5,
        duration=3.5,
        visual_intent="A test visual",
        entities=["Testing"],
        beat_type=BeatType.ABSTRACT_CONCEPT,
    )
    plan = VideoShotPlan(video_id=99, script_id=199, total_duration=3.5, beats=[beat])

    out_file = tmp_path / "shot_plan_99.json"
    plan.save_json(out_file)
    assert out_file.exists()

    loaded = VideoShotPlan.load_json(out_file)
    assert loaded.video_id == 99
    assert len(loaded.beats) == 1
    assert loaded.beats[0].beat_id == "B1_1"
    assert loaded.beats[0].beat_type == BeatType.ABSTRACT_CONCEPT
