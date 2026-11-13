"""Unit tests for v4 and v5 upgrades:
- Duplicate sentence guard
- Fact fidelity verification (subject, action, outcome)
- Pattern library <= 4 word overlap rule
- Study notes transcript copy-guard
- Visual relevance scorer and provider gating (NASA space-only)
- Forced alignment & drift measurement
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from nova.alignment import ForcedAligner, _convert_number_words, _normalize_token
from nova.patterns.library import check_word_overlap
from nova.patterns.study_notes import evaluate_copy_guard
from nova.relevance import CandidateVisual, VisualRelevanceScorer
from nova.scriptwriter import (
    StructuredFact,
    check_duplicate_sentences,
    verify_fact_fidelity,
)

# ---------------------------------------------------------------------------
# 1. Duplicate Sentence Guard
# ---------------------------------------------------------------------------

def test_duplicate_sentence_guard_exact():
    sentences = [
        "A single teaspoon of a neutron star weighs six billion tons.",
        "A single teaspoon of a neutron star weighs six billion tons.",
        "That is roughly the weight of nine hundred pyramids.",
    ]
    ok, msg = check_duplicate_sentences(sentences)
    assert ok is False
    assert "identical" in msg.lower() or "duplicate" in msg.lower()


def test_duplicate_sentence_guard_first_six_words():
    sentences = [
        "A single teaspoon of a neutron star is remarkably heavy.",
        "A single teaspoon of a neutron star weighs six billion tons.",
        "That is roughly the weight of nine hundred pyramids.",
    ]
    ok, msg = check_duplicate_sentences(sentences)
    assert ok is False
    assert "identical opening words" in msg.lower()


def test_duplicate_sentence_guard_high_jaccard():
    sentences = [
        "Scientists discovered a massive ancient black hole orbiting far in deep space.",
        "In deep space scientists discovered a massive ancient black hole orbiting far away.",
        "Its mass exceeds twelve billion suns combined together.",
    ]
    ok, msg = check_duplicate_sentences(sentences)
    assert ok is False
    assert "near-duplicates" in msg.lower()


def test_duplicate_sentence_guard_passes_distinct():
    sentences = [
        "Why did NVIDIA completely reinvent its data center architecture?",
        "In verified tests, the new chip delivered ten times higher throughput.",
        "That changes how AI inference scales across global supercomputers.",
        "And that answers why enterprise server costs are dropping dramatically.",
    ]
    ok, msg = check_duplicate_sentences(sentences)
    assert ok is True
    assert msg == ""


# ---------------------------------------------------------------------------
# 2. Fact Fidelity (Subject, Action, Outcome)
# ---------------------------------------------------------------------------

def test_fact_fidelity_canonical_apple_case():
    fact = StructuredFact(
        id="F1",
        claim="The apple fell from the branch and spoiled on the ground.",
        subject="apple",
        action="fell",
        outcome_or_result="spoiled",
    )

    # Valid paraphrase preserving subject, action synonym, outcome synonym
    valid_sentence = "After the apple dropped from the branch, it rotted completely on the soil."
    ok, msg = verify_fact_fidelity(valid_sentence, fact)
    assert ok is True, f"Expected pass, got error: {msg}"

    # Missing subject (pear instead of apple)
    bad_subject = "After the green pear dropped from the branch, it rotted on the ground."
    ok, msg = verify_fact_fidelity(bad_subject, fact)
    assert ok is False
    assert "subject" in msg.lower()

    # Missing action (stayed instead of fell/dropped)
    bad_action = "The apple hung quietly on the tree and rotted over several months."
    ok, msg = verify_fact_fidelity(bad_action, fact)
    assert ok is False
    assert "action" in msg.lower()

    # Missing outcome (fell but didn't spoil/rot)
    bad_outcome = "The apple fell rapidly down into the green grass."
    ok, msg = verify_fact_fidelity(bad_outcome, fact)
    assert ok is False
    assert "outcome" in msg.lower()


# ---------------------------------------------------------------------------
# 3. Pattern Library Word Overlap Rule (<= 4 Consecutive Words)
# ---------------------------------------------------------------------------

def test_pattern_library_overlap_guard():
    reference_titles = [
        "How NVIDIA Built A Trillion Dollar Monopoly In Secret",
        "The Terrifying Physics Behind A Teaspoon Of Neutron Star",
    ]

    # Compliant pattern: <= 4 consecutive words
    good_formula = "How {Company} Built A Massive Empire"
    ok, culprit = check_word_overlap(good_formula, reference_titles, max_consecutive_words=4)
    assert ok is True
    assert culprit == ""

    # 5 consecutive words copied from ref: "built a trillion dollar monopoly"
    bad_formula = "Why They Built A Trillion Dollar Monopoly Fast"
    ok, culprit = check_word_overlap(bad_formula, reference_titles, max_consecutive_words=4)
    assert ok is False
    assert culprit == "built a trillion dollar monopoly"


# ---------------------------------------------------------------------------
# 4. Study Notes Copy Guard (Transcript Artifact Detection)
# ---------------------------------------------------------------------------

def test_study_notes_copy_guard_detects_caption_tags():
    raw_caption = "Today we look at something wild [Music] and then the results came in [Applause]."
    ok, reason = evaluate_copy_guard(raw_caption)
    assert ok is False
    assert "subtitle/caption artifacts" in reason.lower()


def test_study_notes_copy_guard_detects_timestamps_and_speakers():
    dialogue = """
    00:15 Speaker 1: This is why the engine failed.
    00:28 Speaker 2: We saw the pressure spike immediately.
    """
    ok, reason = evaluate_copy_guard(dialogue)
    assert ok is False
    assert "timestamp" in reason.lower() or "speaker" in reason.lower()


def test_study_notes_copy_guard_accepts_genuine_notes():
    good_notes = """
    Hook uses a direct question with a concrete number to hook the audience.
    Structure uses high-tension contrast beat followed by physical demonstration.
    Pacing stays rapid with visual cuts every 2.5 seconds.
    What to do differently: Avoid jargon in the payoff and resolve curiosity earlier.
    """
    ok, reason = evaluate_copy_guard(good_notes)
    assert ok is True
    assert reason == ""


# ---------------------------------------------------------------------------
# 5. Visual Relevance Scorer & NASA Gating
# ---------------------------------------------------------------------------

def test_visual_relevance_scorer_and_nasa_gating():
    scorer = VisualRelevanceScorer()

    # Case 1: Space candidate on space_science topic -> passes threshold (>= 40)
    space_cand = CandidateVisual(
        provider="nasa",
        asset_id="nasa_001",
        title="Hubble view of neutron star accretion disk in deep space",
        description="High resolution astronomical imaging of pulsar magnetosphere",
        tags=["neutron star", "space", "astronomy", "pulsar"],
        preview_url="https://images.nasa.gov/thumb.jpg",
        download_url="https://images.nasa.gov/test.jpg",
        media_type="image",
    )
    score = scorer.score_candidate(
        space_cand,
        main_subject="neutron star",
        action_or_state="spinning rapidly",
        queries=["neutron star space", "pulsar magnetosphere"],
        niche="space_science",
    )
    assert score >= 40.0
    assert scorer.is_acceptable(score) is True

    # Case 2: NASA candidate on business story -> strictly penalized (< 40)
    biz_queries = ["stock market floor", "traders trading desk"]
    score_nasa_on_biz = scorer.score_candidate(
        space_cand,
        main_subject="stock market trading",
        action_or_state="executing trades",
        queries=biz_queries,
        niche="business",
    )
    assert score_nasa_on_biz < 40.0
    assert scorer.is_acceptable(score_nasa_on_biz) is False

    # Case 3: Completely unrelated footage -> rejected
    unrelated_cand = CandidateVisual(
        provider="pexels",
        asset_id="pex_999",
        title="Chef cutting fresh vegetables in rustic kitchen",
        description="Cooking soup with carrots and onions",
        tags=["food", "cooking", "kitchen", "vegetables"],
        preview_url="https://pexels.com/soup_prev.jpg",
        download_url="https://pexels.com/soup.mp4",
        media_type="video",
    )
    score_unrelated = scorer.score_candidate(
        unrelated_cand,
        main_subject="quantum supercomputer chip",
        action_or_state="cooling to near absolute zero",
        queries=["quantum chip", "cryogenic laboratory"],
        niche="ai_tech",
    )
    assert score_unrelated < 40.0
    assert scorer.is_acceptable(score_unrelated) is False


# ---------------------------------------------------------------------------
# 6. Forced Alignment Token Matching & Drift Logic
# ---------------------------------------------------------------------------

def test_forced_alignment_token_normalizer():
    assert _normalize_token("Hello,") == "hello"
    assert _normalize_token("10x!!") == "10x"
    assert _convert_number_words("six") == "6"
    assert _convert_number_words("billion") == "1000000000"


def test_forced_aligner_mock_alignment():
    aligner = ForcedAligner(model_size="tiny")

    # Mock whisper output
    fake_whisper_words = [
        {"word": "Why", "start": 0.1, "end": 0.3},
        {"word": "did", "start": 0.35, "end": 0.5},
        {"word": "NVIDIA", "start": 0.55, "end": 0.95},
        {"word": "change", "start": 1.0, "end": 1.3},
        {"word": "everything", "start": 1.35, "end": 1.8},
    ]

    with patch("nova.alignment.WhisperModel") as MockWhisper:
        instance = MockWhisper.return_value
        fake_seg = MagicMock()
        fake_seg.text = "Why did NVIDIA change everything"
        fake_seg.words = [
            MagicMock(word=w["word"], start=w["start"], end=w["end"]) for w in fake_whisper_words
        ]
        fake_info = MagicMock(duration=2.0)
        instance.transcribe.return_value = ([fake_seg], fake_info)

        script_sentences = ["Why did NVIDIA change everything?"]
        result = aligner.align(Path("dummy.wav"), script_sentences, max_drift_threshold_ms=250.0)

        assert len(result.word_timings) == 5
        assert result.word_timings[0].word == "Why"
        assert result.word_timings[2].word == "NVIDIA"
        assert result.passed_sync is True
        assert result.median_drift_ms >= 0.0
