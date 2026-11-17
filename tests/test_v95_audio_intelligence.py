"""Comprehensive Automated Test Suite for NOVA AUTOPILOT v9.5: Audio-Driven Editing."""

import subprocess
import wave
from pathlib import Path
import numpy as np
import pytest

from nova.editing.audio_intelligence import (
    AudioIntelligenceAnalyzer,
    AudioOnset,
    AudioSilence,
    BeatGrid,
    CutDecision,
    ImportantWord,
    SpeechEnergyProfile,
)


@pytest.fixture
def synthetic_audio_files(tmp_path: Path):
    """Generates synthetic narration speech and rhythmic music WAV files for testing."""
    sr = 16000
    
    # 1. Narration speech with deliberate silences
    # 0.0 - 1.5s speech, 1.5 - 2.0s silence, 2.0 - 3.5s speech, 3.5 - 4.0s silence
    voice_wav = tmp_path / "test_synth_voice.wav"
    t1 = np.linspace(0, 1.5, int(sr * 1.5), False)
    speech1 = np.sin(2 * np.pi * 300 * t1) * 0.4
    silence1 = np.zeros(int(sr * 0.5), dtype=np.float32)
    t2 = np.linspace(0, 1.5, int(sr * 1.5), False)
    speech2 = np.sin(2 * np.pi * 320 * t2) * 0.5
    silence2 = np.zeros(int(sr * 0.5), dtype=np.float32)
    full_voice = np.concatenate([speech1, silence1, speech2, silence2])

    with wave.open(str(voice_wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes((full_voice * 32767).astype(np.int16).tobytes())

    # 2. Rhythmic music: 120 BPM (0.5s beat interval)
    music_wav = tmp_path / "test_synth_music.wav"
    dur_m = 4.0
    t_m = np.linspace(0, dur_m, int(sr * dur_m), False)
    music_data = np.zeros(len(t_m), dtype=np.float32)
    # Add clicks/beats at every 0.5s
    for b_idx in range(8):
        b_sample = int(b_idx * 0.5 * sr)
        click_len = min(int(0.04 * sr), len(t_m) - b_sample)
        t_c = np.linspace(0, 0.04, click_len, False)
        music_data[b_sample : b_sample + click_len] += np.sin(2 * np.pi * 80 * t_c) * 0.7

    with wave.open(str(music_wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes((music_data * 32767).astype(np.int16).tobytes())

    return voice_wav, music_wav


def test_narration_analysis_energy_and_silences(synthetic_audio_files):
    voice_wav, _ = synthetic_audio_files
    analyzer = AudioIntelligenceAnalyzer(sample_rate=16000)

    class DummyWord:
        def __init__(self, w, st, et):
            self.word = w
            self.start = st
            self.end = et

    words = [
        DummyWord("billion", 0.2, 0.6),
        DummyWord("collide", 2.2, 2.7),
    ]

    profile = analyzer.analyze_narration(voice_wav, word_timings=words)

    assert isinstance(profile, SpeechEnergyProfile)
    assert profile.mean_energy > 0.01
    assert profile.peak_energy > 0.1
    assert len(profile.times) == len(profile.rms_energy)

    # Verify detected silences match the 1.5-2.0s and 3.5-4.0s windows
    assert len(profile.silences) >= 1
    found_mid_silence = any(1.4 <= s.start_time <= 1.7 and s.duration >= 0.25 for s in profile.silences)
    assert found_mid_silence, f"Failed to detect speech silence around 1.5s: {profile.silences}"

    # Verify important word detection
    assert len(profile.important_words) >= 1
    imp_text = [w.word for w in profile.important_words]
    assert "billion" in imp_text or "collide" in imp_text


def test_music_beat_detection(synthetic_audio_files):
    _, music_wav = synthetic_audio_files
    analyzer = AudioIntelligenceAnalyzer(sample_rate=16000)

    grid = analyzer.analyze_music(music_wav)
    assert isinstance(grid, BeatGrid)
    assert 60.0 <= grid.bpm <= 180.0
    assert len(grid.beat_times) >= 4
    assert len(grid.downbeats) >= 1
    assert 0.0 <= grid.confidence <= 1.0


def test_sympathetic_editorial_cuts_rule(synthetic_audio_files):
    """Verifies: 'Never force every cut to align with a musical beat.'
    
    Cuts near natural silences snap to sympathetic music beats with pre-roll,
    while cuts that would disrupt speech remain at nominal sentence boundaries.
    """
    voice_wav, music_wav = synthetic_audio_files
    analyzer = AudioIntelligenceAnalyzer(sample_rate=16000)

    profile = analyzer.analyze_narration(voice_wav)
    grid = analyzer.analyze_music(music_wav)

    # Nominal cut #0 is at 1.75s (inside the 1.5-2.0s silence window, near 2.0s beat)
    # Nominal cut #1 is at 2.6s (active speech, no silence)
    nom_cuts = [1.75, 2.6]
    decisions = analyzer.find_editorial_cuts(nom_cuts, profile, grid, tolerance_sec=0.25)

    assert len(decisions) == 2
    # Cut #0 should be in or snapped to the natural silence window
    assert 1.4 <= decisions[0].actual_cut_time <= 2.1
    # Cut #1 should not be forced into an unnatural cut that clashes with active speech
    assert abs(decisions[1].actual_cut_time - 2.6) < 0.2
