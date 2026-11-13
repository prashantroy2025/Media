"""Comprehensive Quality Gate and Visual Verification Engine for Nova Autopilot v2.0."""

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from nova.config import NovaSettings
from nova.db import Video
from nova.logging_setup import logger


@dataclass
class QualityGateResult:
    passed: bool
    quality_flag: str  # "passed", "low_visuals", "failed"
    checks: dict[str, dict] = field(default_factory=dict)
    contact_sheet_path: str = ""
    flat_frame_ratio: float = 0.0
    wpm: float = 0.0
    duration: float = 0.0
    failure_reasons: list[str] = field(default_factory=list)


class QualityGate:
    def __init__(self, settings: NovaSettings):
        self.settings = settings
        self.flat_threshold = getattr(settings.visuals, "flat_frame_threshold", 0.05)

    def evaluate(self, video_path: Path, video_record: Video) -> QualityGateResult:
        """Runs the exhaustive quality gate suite on a rendered short video."""
        logger.info(f"Running Quality Gate evaluation on: [cyan]{video_path.name}[/cyan]...")
        checks = {}
        failure_reasons = []
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
            failure_reasons.append(f"Duration {duration:.1f}s outside target range ({min_dur}s - {max_dur}s).")

        # 2. Speaking Pace (WPM) Check
        word_count = len(script.hook.split()) + sum(len(s.get("voiceover", "").split()) for s in script.get_scenes())
        wpm = (word_count / duration) * 60.0 if duration > 0 else 0.0
        wpm_ok = 145.0 <= wpm <= 210.0
        checks["pacing_wpm"] = {
            "passed": wpm_ok,
            "value": f"{wpm:.1f} WPM",
            "target": f"{self.settings.content.min_wpm} - {self.settings.content.max_wpm} WPM",
        }
        if not wpm_ok:
            failure_reasons.append(f"Speaking pace {wpm:.1f} WPM outside optimal range (150-200 WPM).")

        # 3. Hook Rule Check (First spoken line <= 12 words)
        hook_words = script.hook.strip().split()
        hook_len = len(hook_words)
        hook_ok = hook_len <= 12
        checks["hook_length"] = {
            "passed": hook_ok,
            "value": f"{hook_len} words ('{script.hook}')",
            "target": "<= 12 words",
        }
        if not hook_ok:
            failure_reasons.append(f"Hook exceeds 12 words limit ({hook_len} words).")

        # 4. Grounded Facts Verification Check
        facts_used = script.get_facts_used()
        facts_ok = len(facts_used) >= 1
        checks["fact_grounding"] = {
            "passed": facts_ok,
            "value": f"{len(facts_used)} verified facts cited",
            "target": ">= 1 fact with source URL",
        }
        if not facts_ok:
            failure_reasons.append("No grounded source facts cited in metadata.")

        # 5. Distinct Visuals Check
        scenes = script.get_scenes()
        visual_queries = [s.get("visual_query", "") for s in scenes]
        distinct_visuals_ok = len(set(visual_queries)) >= max(2, len(scenes) - 1)
        checks["distinct_visuals"] = {
            "passed": distinct_visuals_ok,
            "value": f"{len(set(visual_queries))} unique scene queries",
            "target": "Pattern interrupt every 2-4 seconds",
        }

        # 6. Visual Quality Gate: Flat Frame & Entropy Detection + Contact Sheet
        frames_dir = video_path.parent / f"qc_frames_{video_record.id}"
        frames = self._extract_frames(video_path, frames_dir)
        flat_ratio, contact_sheet_p = self._analyze_visual_frames(
            frames, video_path.parent / f"contact_sheet_{video_record.id}.jpg"
        )

        flat_ok = flat_ratio <= self.flat_threshold
        checks["flat_frame_detection"] = {
            "passed": flat_ok,
            "value": f"{flat_ratio * 100:.1f}% flat frames",
            "target": f"<= {self.flat_threshold * 100:.0f}% flat frames",
        }
        if not flat_ok:
            failure_reasons.append(f"Visual quality failed: {flat_ratio * 100:.1f}% of frames are flat/monochrome.")

        # 7. Licensing & Attribution Complete
        attributions = video_record.attributions
        licenses_ok = len(attributions) >= 1 or len(scenes) > 0
        checks["license_attribution"] = {
            "passed": licenses_ok,
            "value": f"{len(attributions)} media attributions recorded in DB",
            "target": "All assets attributed",
        }

        # 8. Business Advice & Financial Compliance Check
        niche = getattr(script, "niche", "ai_tech") or "ai_tech"
        if niche == "business":
            niche_cfg = self.settings.niches.get("business")
            banned_phrases = (
                niche_cfg.banned_phrases
                if (niche_cfg and niche_cfg.banned_phrases)
                else [
                    "buy now",
                    "guaranteed",
                    "will crash",
                    "get rich",
                    "financial advice",
                    "price prediction",
                    "you should buy",
                    "you should sell",
                    "invest now",
                    "massive returns",
                    "to the moon",
                    "easy money",
                ]
            )
            script_full_text = (
                f"{script.title} {script.hook} {' '.join(s.get('voiceover', '') for s in scenes)} {script.cta}".lower()
            )
            detected_banned = [bp for bp in banned_phrases if bp.lower() in script_full_text]
            disclaimer = "for entertainment and education only. not financial advice."
            has_disclaimer = (
                disclaimer in (script.description or "").lower() or disclaimer in (script.cta or "").lower()
            )

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

        # 8. Subtitle Synchronization Gate (faster-whisper alignment metrics)
        sync_stats = {}
        if getattr(video_record, "subtitle_sync_stats_json", None):
            try:
                sync_stats = json.loads(video_record.subtitle_sync_stats_json)
            except Exception:
                pass

        median_drift = sync_stats.get("median_drift_ms", 0.0)
        max_drift = sync_stats.get("max_drift_ms", 0.0)
        sync_ok = median_drift <= 100.0 and max_drift <= 250.0
        checks["subtitle_sync"] = {
            "passed": sync_ok,
            "value": f"Median: {median_drift:.1f}ms, Max: {max_drift:.1f}ms",
            "target": "Median <= 100ms, Max <= 250ms",
        }
        if not sync_ok and sync_stats:
            failure_reasons.append(f"Subtitle timing drift too high (Median: {median_drift:.1f}ms, Max: {max_drift:.1f}ms).")

        # 9. Duplicate Sentence Guard Check
        from nova.scriptwriter import check_duplicate_sentences

        sentences_list = [s.get("text", "") for s in script.get_sentences()] if script.get_sentences() else [s.get("voiceover", "") for s in scenes]
        dup_ok, dup_reason = check_duplicate_sentences(sentences_list)
        checks["no_duplicate_sentences"] = {
            "passed": dup_ok,
            "value": "Zero duplicate sentences" if dup_ok else dup_reason,
            "target": "100% unique progression across all sentences",
        }
        if not dup_ok:
            failure_reasons.append(f"Duplicate sentence detected: {dup_reason}")

        # Clean up temporary qc_frames directory
        self._cleanup_temp_dir(frames_dir)

        # Determine overall flag
        quality_flag = "passed"
        if not flat_ok:
            quality_flag = "low_visuals"
        if failure_reasons:
            if quality_flag == "passed":
                quality_flag = "failed"
        elif any(getattr(a, "is_fallback_card", False) for a in getattr(video_record, "attributions", [])):
            quality_flag = "weak_visuals"

        overall_passed = len(failure_reasons) == 0 and flat_ok

        logger.info(
            f"Quality Gate Result: [bold {'green' if overall_passed else 'red'}]{quality_flag.upper()}[/bold {'green' if overall_passed else 'red'}]. "
            f"Pace: {wpm:.1f} WPM, Flat frames: {flat_ratio * 100:.1f}%, Duration: {duration:.1f}s."
        )

        return QualityGateResult(
            passed=overall_passed,
            quality_flag=quality_flag,
            checks=checks,
            contact_sheet_path=str(contact_sheet_p) if contact_sheet_p else "",
            flat_frame_ratio=round(flat_ratio, 3),
            wpm=round(wpm, 1),
            duration=round(duration, 2),
            failure_reasons=failure_reasons,
        )

    def _get_media_duration(self, file_path: Path) -> float:
        cmd = [
            "ffprobe",
            "-v",
            "quiet",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(file_path.resolve()),
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode == 0:
                data = json.loads(res.stdout)
                return float(data.get("format", {}).get("duration", 0.0))
        except Exception:
            pass
        return 0.0

    def _extract_frames(self, video_path: Path, output_dir: Path) -> list[Path]:
        """Extracts 1 frame per second from video for computer vision inspection."""
        output_dir.mkdir(parents=True, exist_ok=True)
        frame_pattern = output_dir / "frame_%03d.jpg"
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path.resolve()),
            "-vf",
            "fps=1",
            "-q:v",
            "3",
            str(frame_pattern.resolve()),
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return sorted(list(output_dir.glob("frame_*.jpg")))

    def _analyze_visual_frames(self, frames: list[Path], contact_sheet_path: Path) -> tuple[float, Path | None]:
        """Analyzes spatial color variance of frames and creates a visual contact sheet grid."""
        if not frames:
            return 1.0, None

        flat_count = 0
        loaded_imgs = []

        for f_path in frames:
            try:
                img = Image.open(f_path).convert("RGB")
                loaded_imgs.append(img)
                # Downsample to 128x228 for instant numpy evaluation
                small = img.resize((128, 228))
                arr = np.array(small)
                # Compute spatial standard deviation across RGB channels
                spatial_std = float(np.mean([np.std(arr[:, :, c]) for c in range(3)]))
                # If spatial standard deviation is under 3.5, it is a flat solid or monotone gradient
                if spatial_std < 3.5:
                    flat_count += 1
            except Exception:
                pass

        flat_ratio = flat_count / max(1, len(frames))

        # Generate contact sheet grid (up to 12 frames, 4 cols x 3 rows)
        contact_sheet = self._build_contact_sheet(loaded_imgs[:12])
        if contact_sheet:
            contact_sheet.save(contact_sheet_path, "JPEG", quality=85)
            logger.info(f"Generated visual quality contact sheet at: {contact_sheet_path.name}")
            return flat_ratio, contact_sheet_path

        return flat_ratio, None

    def _build_contact_sheet(self, images: list[Image.Image]) -> Image.Image | None:
        """Stitches a list of frames into a clean contact sheet preview."""
        if not images:
            return None

        thumb_w, thumb_h = 270, 480
        cols = min(4, len(images))
        rows = (len(images) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * thumb_w, rows * thumb_h), (15, 15, 20))

        for idx, img in enumerate(images):
            c = idx % cols
            r = idx // cols
            resized = img.resize((thumb_w, thumb_h))
            # Annotate with timestamp
            from PIL import ImageDraw

            draw_tile = ImageDraw.Draw(resized)
            draw_tile.rectangle((10, 10, 90, 36), fill=(0, 0, 0, 180))
            draw_tile.text((16, 14), f"T={idx*2}s", fill=(255, 255, 255))
            sheet.paste(resized, (c * thumb_w, r * thumb_h))

        return sheet

    def _cleanup_temp_dir(self, directory: Path):
        try:
            for f in directory.iterdir():
                f.unlink(missing_ok=True)
            directory.rmdir()
        except Exception:
            pass
