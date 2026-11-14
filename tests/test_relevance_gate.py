"""Tests for Multi-Factor Relevance Gate & Misleading Footage Rule."""

import pytest
from nova.beats import Beat, BeatType
from nova.providers.base import MediaCandidate
from nova.relevance_gate import RelevanceGate


def test_relevance_gate_high_match():
    gate = RelevanceGate(min_threshold=60.0)
    beat = Beat(
        beat_id="B1_1",
        beat_index=0,
        sentence_id="S1",
        sentence_index=0,
        spoken_text="TSMC manufactures Nvidia Blackwell microchips in high-tech cleanrooms.",
        caption_text="TSMC manufactures Nvidia Blackwell microchips in high-tech cleanrooms.",
        start_time=0.0,
        end_time=3.5,
        duration=3.5,
        visual_intent="TSMC semiconductor cleanroom fabrication",
        entities=["TSMC", "Nvidia Blackwell"],
        beat_type=BeatType.PROCESS,
    )

    candidate = MediaCandidate(
        provider="pixabay",
        asset_id="chip_vid_1",
        title="Nvidia Blackwell TSMC semiconductor cleanroom",
        description="Engineers in cleanroom suits inspecting advanced microchips",
        tags=["tsmc", "semiconductor", "cleanroom", "nvidia blackwell", "chip"],
        media_type="video",
        width=1920,
        height=1080,
        duration=5.0,
        preview_url="https://example.com/p.jpg",
        download_url="https://example.com/v.mp4",
    )

    result = gate.evaluate_candidate(candidate, beat)
    assert result.passed is True
    assert result.total_score >= 80.0
    assert result.entity_score == 40.0
    assert result.rejection_reason == ""


def test_relevance_gate_rejects_irrelevant_footage():
    gate = RelevanceGate(min_threshold=60.0)
    beat = Beat(
        beat_id="B1_1",
        beat_index=0,
        sentence_id="S1",
        sentence_index=0,
        spoken_text="TSMC manufactures Nvidia Blackwell microchips in cleanrooms.",
        caption_text="TSMC manufactures Nvidia Blackwell microchips in cleanrooms.",
        start_time=0.0,
        end_time=3.5,
        duration=3.5,
        visual_intent="TSMC semiconductor cleanroom fabrication",
        entities=["TSMC", "Nvidia Blackwell"],
        beat_type=BeatType.PROCESS,
    )

    candidate = MediaCandidate(
        provider="pexels",
        asset_id="coffee_1",
        title="Barista pouring coffee in modern cafe",
        description="Coffee shop morning routine latte art",
        tags=["coffee", "cafe", "latte", "morning"],
        media_type="video",
        width=1920,
        height=1080,
        duration=4.0,
        preview_url="https://example.com/p.jpg",
        download_url="https://example.com/v.mp4",
    )

    result = gate.evaluate_candidate(candidate, beat)
    assert result.passed is False
    assert result.total_score < 60.0
    assert "below threshold" in result.rejection_reason


def test_relevance_gate_misleading_stock_sensitive_rejected():
    gate = RelevanceGate(min_threshold=60.0)
    beat = Beat(
        beat_id="B2_1",
        beat_index=1,
        sentence_id="S2",
        sentence_index=1,
        spoken_text="Federal prosecutors charged the CEO with securities fraud.",
        caption_text="Federal prosecutors charged the CEO with securities fraud.",
        start_time=3.5,
        end_time=7.0,
        duration=3.5,
        visual_intent="Federal court indictment",
        entities=["CEO", "Securities Fraud"],
        beat_type=BeatType.PERSON_OR_ORG,
        sensitivity=True,
        sensitivity_reason="Contains sensitive keyword: 'fraud'",
        is_specific_event=True,
    )

    # Generic actor in handcuffs
    candidate = MediaCandidate(
        provider="pixabay",
        asset_id="actor_handcuffs",
        title="Arrested man in handcuffs walking down corridor",
        description="Crime arrest actor model handcuffed",
        tags=["arrest", "crime", "handcuffs", "prisoner"],
        media_type="video",
        width=1920,
        height=1080,
        duration=3.5,
        preview_url="https://example.com/p.jpg",
        download_url="https://example.com/v.mp4",
    )

    result = gate.evaluate_candidate(candidate, beat, tier="tier_b")
    assert result.passed is False
    assert result.total_score == 0.0
    assert "Misleading stock prohibited" in result.rejection_reason


def test_relevance_gate_illustrative_badging():
    gate = RelevanceGate(min_threshold=50.0)
    beat = Beat(
        beat_id="B3_1",
        beat_index=2,
        sentence_id="S3",
        sentence_index=2,
        spoken_text="In 2024, AI datacenters consumed unprecedented electrical power.",
        caption_text="In 2024, AI datacenters consumed unprecedented electrical power.",
        start_time=7.0,
        end_time=10.5,
        duration=3.5,
        visual_intent="AI datacenter server racks with glowing lights",
        entities=["AI datacenters", "2024"],
        beat_type=BeatType.ABSTRACT_CONCEPT,
        sensitivity=False,
        is_specific_event=True,
    )

    # Stock datacenter footage
    candidate = MediaCandidate(
        provider="pexels",
        asset_id="datacenter_stock",
        title="Modern server room with flashing LED indicators",
        description="High tech cloud datacenter interior server racks",
        tags=["datacenter", "server", "technology", "network", "cloud"],
        media_type="video",
        width=1920,
        height=1080,
        duration=5.0,
        preview_url="https://example.com/p.jpg",
        download_url="https://example.com/v.mp4",
    )

    result = gate.evaluate_candidate(candidate, beat, tier="tier_a")
    assert result.passed is True
    assert result.is_illustrative is True
