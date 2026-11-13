"""Text-to-speech engine using edge-tts with word timings, silence trimming, and pace quality gate."""

import asyncio
import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import edge_tts

from nova.config import NovaSettings
from nova.logging_setup import logger
from nova.utils.pacing import compute_wpm, count_words


@dataclass
class WordTiming:
    word: str
    start: float  # seconds
    end: float  # seconds


@dataclass
class TTSResult:
    audio_path: Path
    duration_seconds: float
    word_count: int
    wpm: float
    word_timings: list[WordTiming] = field(default_factory=list)


class TTSEngine:
    def __init__(self, settings: NovaSettings):
        self.settings = settings
        self.voice = settings.tts.voice
        self.rate = settings.tts.rate
        self.pitch = settings.tts.pitch
        self.target_wpm = getattr(settings.content, "target_wpm", 175)
        self.min_wpm = getattr(settings.content, "min_wpm", 150)
        self.max_wpm = getattr(settings.content, "max_wpm", 200)

    def synthesize(self, text: str, output_path: str | Path, retry_count: int = 0) -> TTSResult:
        """Synthesizes speech, trims dead silences, measures WPM, and recalibrates rate if necessary."""
        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)

        logger.info(
            f"Synthesizing speech with voice [cyan]{self.voice}[/cyan] (Rate: {self.rate}, {len(text)} chars)..."
        )
        try:
            result = asyncio.run(self._synthesize_edge_tts(text, out_p))
        except Exception as e:
            logger.warning(f"edge-tts synthesis failed ({e}). Attempting offline fallback 'say'...")
            result = self._synthesize_macos_say(text, out_p)

        # Pace Quality Gate: check WPM with up to 3 retries (4 attempts)
        if retry_count < 3:
            current_offset = (
                int(re.search(r"([+-]?\d+)", self.rate).group(1)) if re.search(r"([+-]?\d+)", self.rate) else 0
            )
            if result.wpm < self.min_wpm:
                delta = abs(self.target_wpm - result.wpm)
                step = max(5, min(15, int(delta * 0.4)))
                new_offset = min(35, current_offset + step)
                self.rate = f"{new_offset:+d}%"
                logger.warning(
                    f"Audio pace too slow ({result.wpm:.1f} WPM < {self.min_wpm} WPM). "
                    f"Increasing rate to {self.rate} (Retry {retry_count + 1}/3)..."
                )
                return self.synthesize(text, output_path, retry_count + 1)
            elif result.wpm > self.max_wpm:
                delta = abs(result.wpm - self.target_wpm)
                step = max(5, min(15, int(delta * 0.4)))
                new_offset = max(-25, current_offset - step)
                self.rate = f"{new_offset:+d}%"
                logger.warning(
                    f"Audio pace too fast ({result.wpm:.1f} WPM > {self.max_wpm} WPM). "
                    f"Decreasing rate to {self.rate} (Retry {retry_count + 1}/3)..."
                )
                return self.synthesize(text, output_path, retry_count + 1)
        elif result.wpm < self.min_wpm or result.wpm > self.max_wpm:
            logger.error(
                f"TTS speaking pace failed to converge after 3 retries (Final: {result.wpm:.1f} WPM, "
                f"Target range: {self.min_wpm}-{self.max_wpm} WPM)."
            )

        return result

    async def _synthesize_edge_tts(self, text: str, out_p: Path) -> TTSResult:
        communicate = edge_tts.Communicate(
            text=text,
            voice=self.voice,
            rate=self.rate,
            pitch=self.pitch,
        )

        raw_timings: list[WordTiming] = []
        raw_audio = bytearray()

        # Stream audio chunks and capture word/sentence boundary events
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                raw_audio.extend(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                offset_sec = chunk["offset"] / 10_000_000.0
                duration_sec = chunk["duration"] / 10_000_000.0
                text_word = chunk["text"]
                raw_timings.append(
                    WordTiming(
                        word=text_word,
                        start=round(offset_sec, 3),
                        end=round(offset_sec + duration_sec, 3),
                    )
                )

        temp_raw_path = out_p.with_suffix(".temp.mp3")
        with open(temp_raw_path, "wb") as f:
            f.write(raw_audio)

        # Measure original duration
        d_orig = max(0.1, self._get_duration(temp_raw_path))

        # Trim dead pauses (> 0.25s) and normalize audio loudness
        self._trim_and_normalize_audio(temp_raw_path, out_p)
        if temp_raw_path.exists():
            temp_raw_path.unlink()

        d_trimmed = self._get_duration(out_p)
        scale_ratio = d_trimmed / d_orig if d_orig > 0 else 1.0

        # Adjust word timings to match the trimmed audio duration
        adjusted_timings: list[WordTiming] = []
        if raw_timings:
            for w in raw_timings:
                adjusted_timings.append(
                    WordTiming(
                        word=w.word,
                        start=round(w.start * scale_ratio, 3),
                        end=round(w.end * scale_ratio, 3),
                    )
                )
        else:
            adjusted_timings = self._estimate_word_timings(text, d_trimmed)

        word_count = count_words(text)
        wpm = compute_wpm(text, d_trimmed)

        logger.info(
            f"TTS Complete: Duration: {d_trimmed:.2f}s (Trimmed from {d_orig:.2f}s). "
            f"Words: {word_count}, Real Pace: [bold green]{wpm:.1f} WPM[/bold green]."
        )

        return TTSResult(
            audio_path=out_p,
            duration_seconds=d_trimmed,
            word_count=word_count,
            wpm=round(wpm, 1),
            word_timings=adjusted_timings,
        )

    def _trim_and_normalize_audio(self, input_file: Path, output_file: Path):
        """Applies silenceremove to cap dead pauses at 0.25s and normalizes loudness to -14 LUFS."""
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(input_file.resolve()),
            "-af",
            (
                "silenceremove=start_periods=1:start_duration=0.02:start_threshold=-40dB:detection=peak,"
                "silenceremove=stop_periods=-1:stop_duration=0.25:stop_threshold=-40dB:detection=peak,"
                "loudnorm=I=-14:LRA=7:tp=-1.5"
            ),
            "-c:a",
            "libmp3lame",
            "-b:a",
            "192k",
            str(output_file.resolve()),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            logger.warning(f"Audio trimming failed, falling back to simple copy: {res.stderr}")
            input_file.replace(output_file)

    def _synthesize_macos_say(self, text: str, out_p: Path) -> TTSResult:
        """Offline fallback using macOS built-in say command calibrated to 180 WPM."""
        aiff_path = out_p.with_suffix(".aiff")
        cmd = ["say", "-r", "180", "-o", str(aiff_path.resolve()), text]
        subprocess.run(cmd, check=True)

        cmd_convert = [
            "ffmpeg",
            "-y",
            "-i",
            str(aiff_path.resolve()),
            "-af",
            "loudnorm=I=-14:LRA=7:tp=-1.5",
            str(out_p.resolve()),
        ]
        subprocess.run(cmd_convert, check=True)
        if aiff_path.exists():
            aiff_path.unlink()

        dur = self._get_duration(out_p)
        word_count = len(text.split())
        wpm = (word_count / dur) * 60.0 if dur > 0 else 0.0
        timings = self._estimate_word_timings(text, dur)
        return TTSResult(audio_path=out_p, duration_seconds=dur, word_count=word_count, wpm=wpm, word_timings=timings)

    def _get_duration(self, audio_path: Path) -> float:
        cmd = [
            "ffprobe",
            "-v",
            "quiet",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(audio_path.resolve()),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0 and res.stdout:
            data = json.loads(res.stdout)
            return float(data.get("format", {}).get("duration", 0.0))
        return 0.0

    def _estimate_word_timings(self, text: str, total_duration: float) -> list[WordTiming]:
        words = text.split()
        if not words:
            return []
        time_per_word = total_duration / len(words)
        timings = []
        current = 0.0
        for w in words:
            timings.append(WordTiming(word=w, start=round(current, 3), end=round(current + time_per_word, 3)))
            current += time_per_word
        return timings
