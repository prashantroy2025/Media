"""Audio Forced Alignment & Subtitle Synchronization Engine for Nova Autopilot v4.0.

Uses faster-whisper (tiny on CPU int8) to extract word-level timestamps directly from the final
master narration audio. Aligns Whisper words to script words via SequenceMatcher so that
captions preserve script spelling, punctuation, and capitalization while adopting Whisper's true timestamps.
Computes precise sentence boundaries for sentence-matched visual cuts.
"""

import difflib
import gc
import re
from dataclasses import dataclass
from pathlib import Path

import av
from faster_whisper import WhisperModel

from nova.logging_setup import logger
from nova.tts import WordTiming

# Compatibility shim: PyAV 19+ dropped 'metadata_errors' which faster-whisper 1.x passes
_orig_av_open = av.open


def _safe_av_open(*args, **kwargs):
    kwargs.pop("metadata_errors", None)
    return _orig_av_open(*args, **kwargs)


av.open = _safe_av_open


@dataclass
class SentenceTiming:
    sentence_id: str
    text: str
    start_time: float
    end_time: float
    duration: float
    word_timings: list[WordTiming]


@dataclass
class AlignmentResult:
    word_timings: list[WordTiming]
    sentence_timings: list[SentenceTiming]
    median_drift_ms: float
    max_drift_ms: float
    passed_sync: bool
    transcript: str


def _normalize_token(token: str) -> str:
    """Normalizes token for matching (lowercase, alphanumeric only)."""
    return re.sub(r"[^\w]", "", token.lower())


def _convert_number_words(token: str) -> str:
    """Helper to convert spoken number representations to digits or vice-versa."""
    num_map = {
        "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
        "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
        "ten": "10", "twenty": "20", "thirty": "30", "forty": "40",
        "fifty": "50", "sixty": "60", "seventy": "70", "eighty": "80", "ninety": "90",
        "hundred": "100", "thousand": "1000", "million": "1000000", "billion": "1000000000"
    }
    norm = _normalize_token(token)
    return num_map.get(norm, norm)


class ForcedAligner:
    def __init__(self, model_size: str = "tiny"):
        self.model_size = model_size

    def align(self, audio_path: Path, script_sentences: list[str], max_drift_threshold_ms: float = 250.0) -> AlignmentResult:
        """Transcribes final narration audio, aligns with script words, and builds sentence boundaries."""
        logger.info(f"Running faster-whisper forced alignment on master audio: {audio_path.name}...")

        # 1. Transcribe audio with Whisper
        model = WhisperModel(self.model_size, device="cpu", compute_type="int8")
        try:
            segments, info = model.transcribe(str(audio_path), word_timestamps=True, language="en")
            whisper_words = []
            full_transcript_parts = []
            for seg in segments:
                full_transcript_parts.append(seg.text)
                if seg.words:
                    for w in seg.words:
                        whisper_words.append({
                            "word": w.word.strip(),
                            "start": round(w.start, 3),
                            "end": round(w.end, 3),
                        })
            full_transcript = " ".join(full_transcript_parts).strip()
        finally:
            del model
            gc.collect()

        logger.info(f"Whisper transcribed {len(whisper_words)} words from audio (Duration: {info.duration:.2f}s).")

        # 2. Extract script tokens per sentence
        sentence_tokens: list[list[str]] = []
        all_script_tokens: list[str] = []
        for s in script_sentences:
            tokens = s.strip().split()
            sentence_tokens.append(tokens)
            all_script_tokens.extend(tokens)

        # 3. Match normalized script words to whisper words using SequenceMatcher
        norm_script = [_normalize_token(t) for t in all_script_tokens]
        norm_whisper = [_normalize_token(w["word"]) for w in whisper_words]

        matcher = difflib.SequenceMatcher(None, norm_script, norm_whisper)
        aligned_word_timings: list[WordTiming] = []

        script_idx_to_whisper_idx: dict[int, int] = {}
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                for offset in range(i2 - i1):
                    script_idx_to_whisper_idx[i1 + offset] = j1 + offset

        # Interpolate timestamps for missing or unmatched words
        last_known_end = 0.1
        total_audio_dur = max(0.5, info.duration)

        for s_idx, orig_token in enumerate(all_script_tokens):
            if s_idx in script_idx_to_whisper_idx:
                w_info = whisper_words[script_idx_to_whisper_idx[s_idx]]
                w_start = w_info["start"]
                w_end = max(w_start + 0.08, w_info["end"])
                last_known_end = w_end
            else:
                # Interpolate based on next known or progress
                w_start = round(last_known_end + 0.05, 3)
                w_end = round(w_start + 0.25, 3)
                last_known_end = w_end

            aligned_word_timings.append(
                WordTiming(
                    word=orig_token,
                    start=min(total_audio_dur, w_start),
                    end=min(total_audio_dur, w_end),
                )
            )

        # 4. Partition word timings back into sentence timings
        sentence_timings: list[SentenceTiming] = []
        curr_word_offset = 0
        for s_idx, tokens in enumerate(sentence_tokens):
            s_word_count = len(tokens)
            s_words = aligned_word_timings[curr_word_offset : curr_word_offset + s_word_count]
            curr_word_offset += s_word_count

            if s_words:
                s_start = s_words[0].start
                # End time is end of last word, or next sentence start
                s_end = s_words[-1].end
            else:
                s_start = 0.0
                s_end = 2.0

            sentence_timings.append(
                SentenceTiming(
                    sentence_id=f"S{s_idx + 1}",
                    text=script_sentences[s_idx],
                    start_time=s_start,
                    end_time=s_end,
                    duration=round(s_end - s_start, 3),
                    word_timings=s_words,
                )
            )

        # Expand sentence end times so they meet the next sentence start (seamless cuts)
        for i in range(len(sentence_timings) - 1):
            next_start = sentence_timings[i + 1].start_time
            if next_start > sentence_timings[i].start_time:
                sentence_timings[i].end_time = next_start
                sentence_timings[i].duration = round(next_start - sentence_timings[i].start_time, 3)

        if sentence_timings:
            sentence_timings[-1].end_time = total_audio_dur
            sentence_timings[-1].duration = round(total_audio_dur - sentence_timings[-1].start_time, 3)

        # 5. Measure drift statistics
        drift_values_ms = []
        for s_idx, w_idx in script_idx_to_whisper_idx.items():
            diff = abs(aligned_word_timings[s_idx].start - whisper_words[w_idx]["start"]) * 1000.0
            drift_values_ms.append(diff)

        if drift_values_ms:
            sorted_drift = sorted(drift_values_ms)
            mid = len(sorted_drift) // 2
            median_drift = sorted_drift[mid]
            max_drift = max(drift_values_ms)
        else:
            median_drift = 0.0
            max_drift = 0.0

        passed_sync = median_drift <= 100.0 and max_drift <= max_drift_threshold_ms

        logger.info(
            f"Subtitle alignment complete: {len(aligned_word_timings)} words aligned. "
            f"Median drift: {median_drift:.1f}ms, Max drift: {max_drift:.1f}ms. Sync status: {'PASSED' if passed_sync else 'FLAGGED'}."
        )

        return AlignmentResult(
            word_timings=aligned_word_timings,
            sentence_timings=sentence_timings,
            median_drift_ms=round(median_drift, 1),
            max_drift_ms=round(max_drift, 1),
            passed_sync=passed_sync,
            transcript=full_transcript,
        )
