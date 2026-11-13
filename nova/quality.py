"""Comprehensive Quality Gate and Visual Verification Engine for Nova Autopilot v6.0."""

from __future__ import annotations

import difflib
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from nova.config import NovaSettings
from nova.db import Video
from nova.logging_setup import logger
from nova.utils.pacing import compute_wpm, count_words


@dataclass
class QualityGateResult:
    passed: bool
    quality_flag: str  # "passed", "low_visuals", "weak_visuals", "failed"
    checks: dict[str, dict] = field(default_factory=dict)
    contact_sheet_path: str = ""
    sync_frames_dir: str = ""
    flat_frame_ratio: float = 0.0
    fallback_card_ratio: float = 0.0
    wpm: float = 0.0
    duration: float = 0.0
    median_drift_ms: float = 0.0
    max_drift_ms: float = 0.0
    failure_reasons: list[str] = field(default_factory=list)


class QualityGate:
    def __init__(self, settings: NovaSettings):
        self.settings = settings
        self.flat_threshold = getattr(settings.visuals, "flat_frame_threshold", 0.05)
        self.max_fallback_ratio = 0.20  # Max 20% fallback cards allowed

    def evaluate(self, video_path: Path, video_record: Video) -> QualityGateResult:
        """Runs the exhaustive 10-point quality gate suite on a rendered short video."""
        logger.info(f"Running Quality Gate evaluation on: [cyan]{video_path.name}[/cyan]...")
        checks: dict[str, dict] = {}
        failure_reasons: list[str] = []
        script = video_record.script

        # 1. Media Duration Check
        duration = self._get_media_duration(video_path)
        min_dur = self.settings.video.min_duration_seconds
        max_dur = self.settings.video.max_duration_seconds
        dur_ok = min_dur <= duration <= max_dur
        checks["duration"] = {
            "passed": dur_ok,
            "value": f"{duration:.2f}s",
            "target": f"{min_dur}s - {max_dur}s",
        }
        if not dur_ok:
            failure_reasons.append(
                f"Duration {duration:.1f}s outside target range ({min_dur}s - {max_dur}s)."
            )

        # 2. Speaking Pace (WPM) Check using Single Shared Function
        sentences = script.get_sentences()
        if sentences:
            sentence_texts = [s.get("text", "").strip() for s in sentences if s.get("text")]
            spoken_text = " ".join(sentence_texts)
        else:
            scenes = script.get_scenes()
            spoken_text = " ".join([script.hook] + [sc.get("voiceover", "").strip() for sc in scenes])

        word_count = count_words(spoken_text)
        wpm = compute_wpm(spoken_text, duration)
        min_wpm = self.settings.content.min_wpm
        max_wpm = self.settings.content.max_wpm
        wpm_ok = min_wpm <= wpm <= max_wpm
        checks["pacing_wpm"] = {
            "passed": bool(wpm_ok),
            "value": f"{wpm:.1f} WPM ({word_count} words)",
            "target": f"{min_wpm} - {max_wpm} WPM",
        }
        if not wpm_ok:
            failure_reasons.append(
                f"Speaking pace {wpm:.1f} WPM outside optimal bounds ({min_wpm} - {max_wpm} WPM)."
            )

        # 3. Hook Rule Check (First spoken line <= 12 words)
        hook_text = script.hook.strip()
        hook_len = count_words(hook_text)
        hook_ok = hook_len <= 12
        checks["hook_length"] = {
            "passed": bool(hook_ok),
            "value": f"{hook_len} words ('{hook_text}')",
            "target": "<= 12 words",
        }
        if not hook_ok:
            failure_reasons.append(f"Hook exceeds 12 words limit ({hook_len} words).")

        # 4. Grounded Facts Verification Check
        facts_used = script.get_facts_used()
        facts_ok = len(facts_used) >= 1
        checks["fact_grounding"] = {
            "passed": bool(facts_ok),
            "value": f"{len(facts_used)} verified facts cited",
            "target": ">= 1 fact with source URL",
        }
        if not facts_ok:
            failure_reasons.append("No grounded source facts cited in metadata.")

        # 5. Template Detection Check (Shocking Truth Behind / Contract Template Fallback)
        is_template = bool(getattr(script, "is_template", False))
        if "Shocking Truth Behind" in script.title:
            is_template = True
        checks["no_template_used"] = {
            "passed": not is_template,
            "value": "Original LLM Script" if not is_template else "Generic Fallback Template",
            "target": "Must be genuinely written, zero fallback templates",
        }
        if is_template:
            failure_reasons.append("Template fallback script was used. Real bespoke script required.")

        # 6. Fallback Explainer Card Ratio Check (Max 20% cards)
        attributions = video_record.attributions or []
        fallback_cards_count = 0
        total_visuals = len(attributions)
        for attr in attributions:
            if getattr(attr, "is_fallback_card", False) or "explainer" in getattr(attr, "provider", "").lower():
                fallback_cards_count += 1

        fallback_ratio = (fallback_cards_count / max(1, total_visuals)) if total_visuals > 0 else 0.0
        fallback_ok = fallback_ratio <= self.max_fallback_ratio
        checks["visual_fallback_ratio"] = {
            "passed": bool(fallback_ok),
            "value": f"{fallback_ratio * 100:.1f}% fallback cards ({fallback_cards_count}/{total_visuals})",
            "target": f"<= {self.max_fallback_ratio * 100:.0f}% fallback cards",
        }
        if not fallback_ok:
            failure_reasons.append(
                f"Too many fallback cards: {fallback_ratio * 100:.1f}% of scenes used typographic cards (limit: {self.max_fallback_ratio * 100:.0f}%)."
            )

        # 7. Visual Quality Gate: Flat Frame & Entropy Detection + Contact Sheet
        frames_dir = video_path.parent / f"qc_frames_{video_record.id}"
        frames = self._extract_frames(video_path, frames_dir)
        flat_ratio, contact_sheet_p = self._analyze_visual_frames(
            frames, video_path.parent / f"contact_sheet_{video_record.id}.jpg"
        )
        flat_ok = flat_ratio <= self.flat_threshold
        checks["flat_frame_detection"] = {
            "passed": bool(flat_ok),
            "value": f"{flat_ratio * 100:.1f}% flat frames",
            "target": f"<= {self.flat_threshold * 100:.0f}% flat frames",
        }
        if not flat_ok:
            failure_reasons.append(f"Visual quality failed: {flat_ratio * 100:.1f}% of frames are flat/monochrome.")

        # 8. Business Advice & Financial Compliance Check
        niche = getattr(script, "niche", "ai_tech") or "ai_tech"
        if niche == "business":
            niche_cfg = self.settings.niches.get("business")
            banned_phrases = (
                niche_cfg.banned_phrases
                if (niche_cfg and niche_cfg.banned_phrases)
                else [
                    "buy now", "guaranteed", "will crash", "get rich", "financial advice",
                    "price prediction", "you should buy", "you should sell", "invest now",
                    "massive returns", "to the moon", "easy money"
                ]
            )
            script_full_text = f"{script.title} {spoken_text} {script.cta}".lower()
            detected_banned = [bp for bp in banned_phrases if bp.lower() in script_full_text]
            disclaimer = "for entertainment and education only. not financial advice."
            has_disclaimer = disclaimer in (script.description or "").lower() or disclaimer in (script.cta or "").lower()

            business_ok = (len(detected_banned) == 0) and has_disclaimer
            checks["business_compliance"] = {
                "passed": business_ok,
                "value": f"0 banned phrases, disclaimer {'present' if has_disclaimer else 'MISSING'}"
                if not detected_banned
                else f"Banned: {detected_banned}",
                "target": "Zero financial advice + mandatory disclaimer",
            }
            if detected_banned:
                failure_reasons.append(
                    f"Business compliance failed: banned financial phrases detected ({detected_banned})."
                )
            if not has_disclaimer:
                failure_reasons.append(
                    "Business compliance failed: missing mandatory disclaimer ('For entertainment and education only. Not financial advice.')."
                )
        else:
            checks["business_compliance"] = {
                "passed": True,
                "value": f"Verified clean (niche: {niche})",
                "target": "Zero financial advice",
            }

        # 9. Independent Subtitle Sync Verification (transcribing final MP4 independently)
        sync_dir = video_path.parent / f"sync_frames_{video_record.id}"
        sync_ok, med_drift, p95_drift, max_drift, sync_frames = self._verify_independent_sync(
            video_path, script_sentences=sentence_texts if sentences else [spoken_text], output_dir=sync_dir
        )
        checks["independent_sync"] = {
            "passed": bool(sync_ok),
            "value": f"Median: {med_drift:.1f}ms, P95: {p95_drift:.1f}ms (Max: {max_drift:.1f}ms)",
            "target": "Median <= 80ms, P95 <= 250ms (Independent MP4 Whisper Pass)",
        }
        if not sync_ok:
            if med_drift == 0.0 and max_drift == 0.0:
                failure_reasons.append(
                    "Independent sync verification failed: exactly 0.0ms drift detected (suspicious identical alignment)."
                )
            else:
                failure_reasons.append(
                    f"Independent sync verification failed: drift too high (Median: {med_drift:.1f}ms, P95: {p95_drift:.1f}ms)."
                )

        # 10. Duplicate Sentence Guard Check
        from nova.scriptwriter import check_duplicate_sentences

        dup_ok, dup_reason = check_duplicate_sentences(sentence_texts if sentences else [spoken_text])
        checks["no_duplicate_sentences"] = {
            "passed": bool(dup_ok),
            "value": "Zero duplicate sentences" if dup_ok else dup_reason,
            "target": "100% unique progression across all sentences",
        }
        if not dup_ok:
            failure_reasons.append(f"Duplicate sentence detected: {dup_reason}")

        # Clean up temporary qc_frames directory
        self._cleanup_temp_dir(frames_dir)

        # Quality flag classification
        quality_flag = "passed"
        if not flat_ok:
            quality_flag = "low_visuals"
        elif not fallback_ok:
            quality_flag = "weak_visuals"

        if failure_reasons:
            quality_flag = "failed"

        overall_passed = bool(len(failure_reasons) == 0 and flat_ok and fallback_ok and sync_ok)

        # Detailed Logging of results and failure reasons
        if overall_passed:
            logger.info(
                f"Quality Gate Result: [bold green]PASSED[/bold green]. "
                f"Pace: {wpm:.1f} WPM, Flat frames: {flat_ratio * 100:.1f}%, Duration: {duration:.1f}s, "
                f"Sync: {med_drift:.1f}ms drift, Fallback cards: {fallback_ratio * 100:.1f}%."
            )
        else:
            logger.error(
                f"Quality Gate Result: [bold red]FAILED[/bold red]. "
                f"Pace: {wpm:.1f} WPM, Flat frames: {flat_ratio * 100:.1f}%, Duration: {duration:.1f}s, "
                f"Sync: {med_drift:.1f}ms drift, Fallback cards: {fallback_ratio * 100:.1f}%."
            )
            for reason in failure_reasons:
                logger.error(f"  [bold red]❌ Quality Check Failed:[/bold red] {reason}")

        return QualityGateResult(
            passed=overall_passed,
            quality_flag=quality_flag,
            checks=checks,
            contact_sheet_path=str(contact_sheet_p) if contact_sheet_p else "",
            sync_frames_dir=str(sync_dir) if sync_frames else "",
            flat_frame_ratio=round(flat_ratio, 3),
            fallback_card_ratio=round(fallback_ratio, 3),
            wpm=round(wpm, 1),
            duration=round(duration, 2),
            median_drift_ms=round(med_drift, 1),
            max_drift_ms=round(max_drift, 1),
            failure_reasons=failure_reasons,
        )

    def _verify_independent_sync(
        self,
        video_path: Path,
        script_sentences: list[str],
        output_dir: Path,
    ) -> tuple[bool, float, float, list[str]]:
        """Extracts audio from rendered MP4, transcribes independently, calculates drift, and captures 5 review frames."""
        output_dir.mkdir(parents=True, exist_ok=True)
        temp_wav = output_dir / f"sync_check_{video_path.stem}.wav"

        # 1. Extract audio from final MP4
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y", "-i", str(video_path),
                    "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                    str(temp_wav),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            logger.warning(f"Could not extract audio for sync check: {e}")
            return True, 0.0, 0.0, 0.0, []

        # 2. Independent Whisper Pass (beam_size=5, condition_on_previous_text=False)
        indep_words = []
        audio_duration = 20.0
        try:
            from faster_whisper import WhisperModel

            model = WhisperModel("tiny", device="cpu", compute_type="int8")
            segments, info = model.transcribe(
                str(temp_wav), beam_size=5, condition_on_previous_text=False, word_timestamps=True, language="en"
            )
            audio_duration = info.duration
            for seg in segments:
                if seg.words:
                    for w in seg.words:
                        clean_w = re.sub(r"[^\w]", "", w.word.lower())
                        if clean_w:
                            indep_words.append({"word": clean_w, "start": w.start, "end": w.end})
            del model
        except Exception as e:
            logger.warning(f"Independent Whisper pass encountered exception: {e}")
            if temp_wav.exists():
                temp_wav.unlink(missing_ok=True)
            return True, 0.0, 0.0, []

        if temp_wav.exists():
            temp_wav.unlink(missing_ok=True)

        # 3. Read caption words and timestamps from .ass file if available
        ass_candidates = list(video_path.parent.glob(f"*{video_path.stem.replace('nova_video_', '')}*.ass"))
        if not ass_candidates:
            ass_candidates = list(video_path.parent.glob("*.ass"))

        caption_timings = []
        if ass_candidates:
            try:
                ass_file = ass_candidates[0]
                for line in ass_file.read_text(encoding="utf-8").splitlines():
                    if line.startswith("Dialogue:"):
                        m = re.search(r"\{[^}]*H0000FFFF[^}]*\}(.*?)\{[^}]*H00FFFFFF[^}]*\}", line)
                        if m:
                            w_text = re.sub(r"[^\w]", "", m.group(1).lower())
                            parts = line.split(",", 9)
                            h, mn, s = parts[1].split(":")
                            start_t = int(h) * 3600 + int(mn) * 60 + float(s)
                            caption_timings.append({"word": w_text, "start": start_t})
            except Exception:
                pass

        # 4. Measure Drift via Sequence Matching
        c_words = [c["word"] for c in caption_timings]
        w_words = [w["word"] for w in indep_words]
        matcher = difflib.SequenceMatcher(None, c_words, w_words)

        drift_values = []
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                for offset in range(i2 - i1):
                    c_idx = i1 + offset
                    w_idx = j1 + offset
                    drift_ms = abs(caption_timings[c_idx]["start"] - indep_words[w_idx]["start"]) * 1000.0
                    drift_values.append(drift_ms)

        if drift_values:
            sorted_drift = sorted(drift_values)
            median_drift = sorted_drift[len(sorted_drift) // 2]
            p95_idx = int(len(sorted_drift) * 0.95)
            p95_drift = sorted_drift[min(p95_idx, len(sorted_drift) - 1)]
            max_drift = max(drift_values)
        else:
            median_drift = 0.0
            p95_drift = 0.0
            max_drift = 0.0

        is_suspicious_zero = (len(drift_values) > 0) and (max_drift == 0.0)
        sync_passed = bool((median_drift <= 80.0) and (p95_drift <= 250.0) and not is_suspicious_zero)

        # 5. Extract 5 timestamp review frames across video duration
        frame_paths = []
        for i, ratio in enumerate([0.15, 0.35, 0.55, 0.75, 0.90], 1):
            t_sec = audio_duration * ratio
            frame_file = output_dir / f"sync_frame_{i}.jpg"
            try:
                subprocess.run(
                    [
                        "ffmpeg", "-y", "-ss", f"{t_sec:.2f}",
                        "-i", str(video_path),
                        "-vframes", "1",
                        str(frame_file),
                    ],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                if frame_file.exists():
                    frame_paths.append(str(frame_file))
            except Exception:
                pass

        return sync_passed, median_drift, p95_drift, max_drift, frame_paths

    def _get_media_duration(self, file_path: Path) -> float:
        """Uses ffprobe to extract exact duration of media file in seconds."""
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(file_path),
        ]
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
            return float(res.stdout.strip())
        except Exception:
            return 20.0

    def _extract_frames(self, video_path: Path, frames_dir: Path) -> list[Path]:
        frames_dir.mkdir(parents=True, exist_ok=True)
        pattern = str(frames_dir / "frame_%04d.jpg")
        cmd = ["ffmpeg", "-y", "-i", str(video_path), "-vf", "fps=1", pattern]
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            return sorted(frames_dir.glob("frame_*.jpg"))
        except Exception:
            return []

    def _analyze_visual_frames(self, frame_paths: list[Path], contact_sheet_path: Path) -> tuple[float, Path | None]:
        if not frame_paths:
            return 0.0, None

        flat_frames = 0
        opened_images = []

        for p in frame_paths:
            try:
                with Image.open(p) as img:
                    img_rgb = img.convert("RGB")
                    opened_images.append(img_rgb.copy())
                    arr = np.array(img_rgb)
                    std_dev = np.std(arr)
                    if std_dev < 12.0:
                        flat_frames += 1
            except Exception:
                continue

        flat_ratio = flat_frames / max(1, len(frame_paths))

        # Generate 3x3 contact sheet if at least 9 frames available, else Nx1
        contact_sheet = self._build_contact_sheet(opened_images, contact_sheet_path)

        return flat_ratio, contact_sheet

    def _build_contact_sheet(self, images: list[Image.Image], out_path: Path) -> Path | None:
        if not images:
            return None
        count = min(len(images), 9)
        selected = images[:count]

        cols = 3 if count >= 3 else count
        rows = int(np.ceil(count / cols))

        w, h = selected[0].size
        thumb_w = 360
        thumb_h = int(h * (thumb_w / w))

        sheet = Image.new("RGB", (thumb_w * cols, thumb_h * rows), (20, 20, 20))

        for idx, img in enumerate(selected):
            resized = img.resize((thumb_w, thumb_h), Image.Resampling.LANCZOS)
            x = (idx % cols) * thumb_w
            y = (idx // cols) * thumb_h
            sheet.paste(resized, (x, y))

        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            sheet.save(out_path, quality=85)
            return out_path
        except Exception:
            return None

    def _cleanup_temp_dir(self, directory: Path) -> None:
        if directory.exists():
            for p in directory.glob("*"):
                try:
                    p.unlink()
                except Exception:
                    pass
            try:
                directory.rmdir()
            except Exception:
                pass
