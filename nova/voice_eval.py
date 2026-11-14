"""Voice Evaluation and Comparison Engine for Nova Autopilot v8.0.

Benchmarks the current default edge-tts voice against alternative voices and native
offline TTS, measuring synthesis speed, WPM, and Whisper round-trip WER.
Generates 3 comparison audio samples in output/voice_samples/ with an HTML comparison player.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
from pathlib import Path

import av
from faster_whisper import WhisperModel

# Compatibility shim
_orig_av_open = av.open


def _safe_av_open(*args, **kwargs):
    kwargs.pop("metadata_errors", None)
    return _orig_av_open(*args, **kwargs)


av.open = _safe_av_open

import edge_tts

from nova.audit import compute_wer
from nova.config import PROJECT_ROOT

VOICE_DIR = PROJECT_ROOT / "output" / "voice_samples"

BENCHMARK_SCRIPT = (
    "In 2026, researchers confirmed that artificial intelligence microchips consume over eighty percent "
    "less power when running compressed algorithms. According to federal regulatory filings, "
    "TSMC manufactures over ninety percent of these advanced processors."
)


async def synthesize_edge_voice(text: str, voice: str, out_path: Path) -> float:
    t0 = time.time()
    communicate = edge_tts.Communicate(text, voice, rate="+5%", pitch="+0Hz")
    await communicate.save(str(out_path))
    return time.time() - t0


def synthesize_macos_say(text: str, out_path: Path) -> float:
    t0 = time.time()
    aiff_path = out_path.with_suffix(".aiff")
    subprocess.run(["say", "-v", "Alex", "-o", str(aiff_path), text], check=True)
    # Convert to MP3
    ffmpeg_bin = "/opt/homebrew/bin/ffmpeg" if os.path.exists("/opt/homebrew/bin/ffmpeg") else "ffmpeg"
    subprocess.run([ffmpeg_bin, "-y", "-i", str(aiff_path), str(out_path)], check=True, capture_output=True)
    if aiff_path.exists():
        aiff_path.unlink()
    return time.time() - t0


def run_voice_evaluation() -> dict[str, Any]:
    """Generates 3 voice samples and produces a comparative evaluation report."""
    VOICE_DIR.mkdir(parents=True, exist_ok=True)

    whisper_model = WhisperModel("tiny", device="cpu", compute_type="int8")

    voices = [
        {"id": "christopher", "name": "en-US-ChristopherNeural (Current Default)", "type": "edge_tts", "voice": "en-US-ChristopherNeural"},
        {"id": "guy", "name": "en-US-GuyNeural (Newsroom Alternative)", "type": "edge_tts", "voice": "en-US-GuyNeural"},
        {"id": "local_alex", "name": "Native Local macOS (Alex / Offline Fallback)", "type": "local", "voice": "Alex"},
    ]

    results = []

    for v in voices:
        file_path = VOICE_DIR / f"voice_sample_{v['id']}.mp3"
        latency = 0.0

        if v["type"] == "edge_tts":
            try:
                latency = asyncio.run(synthesize_edge_voice(BENCHMARK_SCRIPT, v["voice"], file_path))
            except Exception:
                # Fallback to local if offline
                latency = synthesize_macos_say(BENCHMARK_SCRIPT, file_path)
        else:
            latency = synthesize_macos_say(BENCHMARK_SCRIPT, file_path)

        # Transcribe with Whisper to evaluate intelligibility
        segments, _ = whisper_model.transcribe(str(file_path))
        transcribed_text = " ".join(s.text for s in segments)
        wer = compute_wer(BENCHMARK_SCRIPT, transcribed_text)

        # Compute duration
        ffprobe_bin = "/opt/homebrew/bin/ffprobe" if os.path.exists("/opt/homebrew/bin/ffprobe") else "ffprobe"
        res = subprocess.run([ffprobe_bin, "-v", "error", "-show_entries", "format=duration", "-of", "json", str(file_path)], capture_output=True, text=True)
        dur = 15.0
        try:
            dur = float(json.loads(res.stdout)["format"]["duration"])
        except Exception:
            pass

        wpm = (len(BENCHMARK_SCRIPT.split()) / (dur / 60.0)) if dur > 0 else 0.0

        results.append({
            "id": v["id"],
            "name": v["name"],
            "file": file_path.name,
            "latency": round(latency, 2),
            "duration": round(dur, 2),
            "wpm": round(wpm, 1),
            "wer": round(wer * 100, 1),
            "transcription": transcribed_text.strip(),
        })

    del whisper_model

    # Build comparison HTML
    html_path = VOICE_DIR / "voice_comparison.html"
    rows_html = ""
    for r in results:
        rows_html += f"""
        <div class="voice-card">
            <h3>{r['name']}</h3>
            <p><strong>Latency:</strong> {r['latency']}s &bull; <strong>Duration:</strong> {r['duration']}s &bull; <strong>Pace:</strong> {r['wpm']} WPM &bull; <strong>WER:</strong> {r['wer']}%</p>
            <audio controls src="{r['file']}" style="width: 100%; margin: 8px 0;"></audio>
            <p style="font-size: 13px; color: #94a3b8;"><strong>Whisper Transcription:</strong> <em>"{r['transcription']}"</em></p>
        </div>
        """

    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Nova Voice Evaluation & Listening Benchmark</title>
    <style>
        body {{ font-family: -apple-system, sans-serif; background: #0f172a; color: #f8fafc; padding: 24px; }}
        .container {{ max-width: 900px; margin: 0 auto; background: #1e293b; border-radius: 12px; padding: 24px; }}
        h1 {{ color: #38bdf8; margin-top: 0; }}
        .voice-card {{ background: #0f172a; border-radius: 8px; padding: 18px; margin-bottom: 16px; border: 1px solid #334155; }}
        .script-box {{ background: #334155; padding: 12px; border-radius: 6px; font-style: italic; margin-bottom: 20px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Nova Autopilot v8.0 Voice Benchmark Suite</h1>
        <div class="script-box">Benchmark Script: "{BENCHMARK_SCRIPT}"</div>
        {rows_html}
        <p style="color: #94a3b8; font-size: 13px;">Default voice remains <strong>en-US-ChristopherNeural</strong> until user preference is selected.</p>
    </div>
</body>
</html>
"""
    html_path.write_text(html_content, encoding="utf-8")
    return {"results": results, "html_path": str(html_path)}


if __name__ == "__main__":
    res = run_voice_evaluation()
    print("Voice evaluation complete:", res["html_path"])
    for r in res["results"]:
        print(f"  {r['name']}: {r['wpm']} WPM, WER {r['wer']}%, {r['latency']}s")
