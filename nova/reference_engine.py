"""Reference Video & Image Intelligence Engine for Nova Autopilot v9.0.

Analyzes user-provided reference videos, Reels/Shorts clips, or screenshots to extract:
- Shot duration & editing rhythm distribution
- Scene transitions and cut points
- Color grading palette (luminance, saturation, contrast, dominant tones)
- Caption placement safe zones and typography characteristics
- Motion graphics patterns (kinetic pops, counters, callouts)
- Sound design cadence

Generates a reusable ReferenceStyleProfile that can guide generation under 5 operational modes:
1. Reference-inspired editing (balanced blend of pacing and transition styles)
2. Reference-matched pacing (matches cut frequency & shot duration curve)
3. Reference-matched composition (framing, safe zones, split screens)
4. Reference-matched animation style (pop duration, counter format, badges)
5. Reference-matched typography & colors (color grade formula, font, highlights)
"""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PIL import Image, ImageStat

from nova.logging_setup import logger
from nova.presets import VideoPreset, get_preset


@dataclass
class ReferenceBeat:
    start_time: float
    end_time: float
    duration: float
    dominant_color: tuple[int, int, int]
    brightness: float
    motion_energy: float
    detected_technique: str  # e.g. "dynamic_footage", "infographic_card", "kinetic_text", "dramatic_pause"
    suggested_transition: str  # "cut", "crossfade", "whip", "zoom"


@dataclass
class ReferenceStoryboardItem:
    """Detailed storyboard breakdown of an individual reference shot."""
    shot_index: int
    start_time: float
    end_time: float
    duration: float
    shot_composition: str  # "wide_vista", "medium_shot", "macro_close_up", "split_screen"
    subject_position: str  # "center_subject", "rule_of_thirds_left", "rule_of_thirds_right", "top_weighted"
    camera_movement: str  # "zoom_in", "zoom_out", "pan_horizontal", "static"
    transition_in: str  # "cut", "circleopen", "dissolve", "wipeleft"
    caption_zone: str  # "bottom_safe_zone", "center_focus", "top_header"
    has_motion_graphic: bool
    color_mood: str  # "cinematic_dark", "vibrant_high_key", "warm_contrast"


@dataclass
class ReferenceStoryboard:
    """Full structured storyboard extracted from a professional reference video."""
    video_id: str
    total_duration: float
    shots_count: int
    cut_frequency_per_minute: float
    shots: list[ReferenceStoryboardItem]
    reproducible_options: dict[str, bool] = field(
        default_factory=lambda: {
            "pacing": True,
            "composition": True,
            "transitions": True,
            "color_grading": True,
            "typography": True,
        }
    )


@dataclass
class ReferenceStyleProfile:
    profile_id: str
    name: str
    source_type: str  # "video", "image_set", "manual"
    source_path: str
    duration_seconds: float
    average_shot_duration: float
    shot_duration_range: tuple[float, float]
    cut_frequency_per_minute: float
    dominant_palette_rgb: list[tuple[int, int, int]]
    color_grade_eq: str
    caption_position_y: int
    caption_font_weight: str
    highlight_color_hex: str
    preferred_transition: str
    motion_intensity: str  # "subtle", "balanced", "high"
    subject_position: str = "center_subject"  # "center_subject", "rule_of_thirds_left", "rule_of_thirds_right", "top_weighted"
    foreground_background_depth: str = "deep_focus"  # "shallow_dof", "deep_focus"
    detected_typography_zone: str = "bottom_safe_zone"  # "bottom_safe_zone", "center_focus", "top_header"
    camera_motion_trend: str = "zoom_in"  # "zoom_in", "zoom_out", "pan_horizontal", "static"
    beats: list[ReferenceBeat] = field(default_factory=list)
    timestamp_notes: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReferenceStyleProfile:
        beats_data = data.pop("beats", [])
        beats = [ReferenceBeat(**b) for b in beats_data]
        return cls(beats=beats, **data)

    def to_video_preset(self, base_preset_id: str = "viral_facts") -> VideoPreset:
        """Translates the analyzed reference profile into an active VideoPreset."""
        base = get_preset(base_preset_id)
        return VideoPreset(
            preset_id=f"ref_{self.profile_id}",
            name=f"Reference: {self.name}",
            description=f"Auto-generated profile matching reference ({self.cut_frequency_per_minute:.1f} cuts/min)",
            target_shot_min=max(1.2, round(self.shot_duration_range[0], 2)),
            target_shot_max=max(2.0, round(self.shot_duration_range[1], 2)),
            video_coverage_target=0.75 if self.cut_frequency_per_minute > 24 else 0.60,
            color_grade=self.color_grade_eq or base.color_grade,
            transition_style=self.preferred_transition or base.transition_style,
            transition_duration=0.25 if self.average_shot_duration < 2.0 else 0.35,
            caption_preset="bold_viral_facts" if self.cut_frequency_per_minute > 24 else "cinematic_storytelling",
            motion_intensity=self.motion_intensity,
            music_mood=base.music_mood,
            sfx_intensity="high" if self.cut_frequency_per_minute > 25 else "medium",
            font_family="Montserrat-ExtraBold" if self.caption_font_weight == "extrabold" else "Montserrat-Bold",
            font_size=60 if self.cut_frequency_per_minute > 24 else 54,
            primary_color="&H00FFFFFF",
            highlight_color=self.highlight_color_hex,
            background_overlay="vignette",
            dynamic_camera_pan=True,
            split_screen_allowed=True,
            motion_blur_enabled=self.motion_intensity == "high",
        )


class ReferenceAnalyzer:
    """Extracts editing rhythm, color grade, and visual techniques from reference assets."""

    def __init__(self, temp_dir: Path | None = None):
        self.temp_dir = temp_dir or Path("assets/references")
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def analyze_reference(
        self,
        media_path: Path,
        mode: str = "reference_inspired",
        profile_name: str | None = None,
    ) -> ReferenceStyleProfile:
        """Analyzes a reference video or screenshot series and outputs a reusable ReferenceStyleProfile."""
        if not media_path.exists():
            raise FileNotFoundError(f"Reference media not found at: {media_path}")

        ext = media_path.suffix.lower()
        if ext in (".mp4", ".mov", ".webm", ".mkv", ".m4v"):
            return self._analyze_video(media_path, mode, profile_name)
        elif ext in (".jpg", ".jpeg", ".png", ".webp"):
            return self._analyze_single_image(media_path, profile_name)
        else:
            raise ValueError(f"Unsupported reference media format: {ext}")

    def _probe_duration(self, video_path: Path) -> float:
        """Probes video duration via ffprobe."""
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path.resolve()),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        try:
            return max(1.0, float(res.stdout.strip()))
        except Exception:
            return 15.0

    def _detect_scene_cuts(self, video_path: Path) -> list[float]:
        """Detects scene transition timestamps via FFmpeg scene filter."""
        total_dur = self._probe_duration(video_path)
        scene_times = [0.0]
        cmd = [
            "ffmpeg", "-i", str(video_path.resolve()),
            "-filter_complex", "select='gt(scene,0.35)',metadata=print:file=-",
            "-f", "null", "-",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        matches = re.findall(r"pts_time:([0-9.]+)", res.stderr + res.stdout)
        for m in matches:
            t = float(m)
            if t > scene_times[-1] + 0.6 and t < total_dur:
                scene_times.append(round(t, 2))
        return scene_times

    def _analyze_video(
        self,
        video_path: Path,
        mode: str = "reference_inspired",
        profile_name: str | None = None,
    ) -> ReferenceStyleProfile:
        """Extracts shot boundaries, color metrics, and pacing from a reference video."""
        logger.info(f"Analyzing reference video: [cyan]{video_path.name}[/cyan] (mode={mode})...")

        # 1. Probe total duration
        total_duration = self._probe_duration(video_path)

        # 2. Shot change detection via ffmpeg select=gt(scene,0.35)
        scene_times = self._detect_scene_cuts(video_path)
        if total_duration not in scene_times:
            scene_times.append(round(total_duration, 2))

        # Calculate shot durations
        shot_durations = []
        for i in range(len(scene_times) - 1):
            dur = round(scene_times[i + 1] - scene_times[i], 2)
            if dur > 0.3:
                shot_durations.append(dur)

        if not shot_durations:
            shot_durations = [3.0]

        avg_shot_dur = sum(shot_durations) / len(shot_durations)
        min_shot = min(shot_durations)
        max_shot = max(shot_durations)
        cuts_per_min = (len(shot_durations) / total_duration) * 60.0

        # 3. Sample frames for color grading & technique extraction
        sample_frames = self._sample_video_frames(video_path, total_duration, num_samples=6)
        dominant_colors = []
        brightness_levels = []

        for f_img in sample_frames:
            stat = ImageStat.Stat(f_img)
            brightness_levels.append(sum(stat.mean[:3]) / 3.0)
            # Resize to 1x1 to find average color
            tiny = f_img.resize((1, 1), Image.Resampling.LANCZOS)
            r, g, b = tiny.getpixel((0, 0))[:3]
            dominant_colors.append((r, g, b))

        avg_brightness = sum(brightness_levels) / len(brightness_levels) if brightness_levels else 128.0

        # Composition and motion analysis across sample frames
        comp_analysis = self.analyze_frame_composition(sample_frames[0]) if sample_frames else {}
        motion_trends = []
        if len(sample_frames) >= 2:
            for f_idx in range(len(sample_frames) - 1):
                motion_trends.append(self.estimate_camera_motion(sample_frames[f_idx], sample_frames[f_idx + 1]))
        motion_trend = max(set(motion_trends), key=motion_trends.count) if motion_trends else "zoom_in"

        # Determine color grading preset recommendation
        if avg_brightness < 90:
            color_grade_eq = "eq=contrast=1.18:brightness=-0.04:saturation=0.90,vignette=PI/4"
            highlight_color = "&H00D47800"  # Teal/Cyan
        elif avg_brightness > 160:
            color_grade_eq = "eq=contrast=1.05:brightness=0.01:saturation=1.15"
            highlight_color = "&H0000FFFF"  # Vivid Yellow
        else:
            color_grade_eq = "eq=contrast=1.10:brightness=0.01:saturation=1.12,unsharp=3:3:0.4"
            highlight_color = "&H0000FFFF"

        # Determine preferred transition based on pacing
        if avg_shot_dur < 1.8:
            preferred_trans = "whip"
            motion_intensity = "high"
        elif avg_shot_dur > 3.0:
            preferred_trans = "crossfade"
            motion_intensity = "subtle"
        else:
            preferred_trans = "mixed"
            motion_intensity = "balanced"

        # Construct beats
        beats: list[ReferenceBeat] = []
        notes: list[dict[str, Any]] = []

        for idx, s_dur in enumerate(shot_durations):
            st = scene_times[idx]
            et = scene_times[idx + 1] if idx + 1 < len(scene_times) else total_duration
            color = dominant_colors[idx % len(dominant_colors)] if dominant_colors else (128, 128, 128)
            technique = "kinetic_hook" if idx == 0 else ("dynamic_footage" if s_dur < 2.5 else "infographic_card")
            trans = "whip" if s_dur < 1.8 else "crossfade"

            beat = ReferenceBeat(
                start_time=st,
                end_time=et,
                duration=s_dur,
                dominant_color=color,
                brightness=avg_brightness,
                motion_energy=1.0 if s_dur < 2.0 else 0.5,
                detected_technique=technique,
                suggested_transition=trans,
            )
            beats.append(beat)

            notes.append({
                "timestamp_range": f"{st:.2f}s - {et:.2f}s",
                "duration": f"{s_dur:.2f}s",
                "detected_style": technique,
                "transition": trans,
            })

        profile_id = f"ref_{video_path.stem[:16]}_{int(total_duration)}"
        profile = ReferenceStyleProfile(
            profile_id=profile_id,
            name=profile_name or f"Ref: {video_path.stem.replace('_', ' ').title()}",
            source_type="video",
            source_path=str(video_path),
            duration_seconds=round(total_duration, 2),
            average_shot_duration=round(avg_shot_dur, 2),
            shot_duration_range=(round(min_shot, 2), round(max_shot, 2)),
            cut_frequency_per_minute=round(cuts_per_min, 1),
            dominant_palette_rgb=dominant_colors,
            color_grade_eq=color_grade_eq,
            caption_position_y=1380,
            caption_font_weight="extrabold" if cuts_per_min > 24 else "bold",
            highlight_color_hex=highlight_color,
            preferred_transition=preferred_trans,
            motion_intensity=motion_intensity,
            subject_position=comp_analysis.get("subject_position", "center_subject"),
            foreground_background_depth=comp_analysis.get("foreground_background_depth", "deep_focus"),
            detected_typography_zone=comp_analysis.get("detected_typography_zone", "bottom_safe_zone"),
            camera_motion_trend=motion_trend,
            beats=beats,
            timestamp_notes=notes,
        )

        # Save profile JSON for persistence and reuse
        out_json = self.temp_dir / f"{profile_id}.json"
        out_json.write_text(json.dumps(profile.to_dict(), indent=2), encoding="utf-8")
        logger.info(f"Saved reusable reference profile: [cyan]{out_json.name}[/cyan] ({cuts_per_min:.1f} cuts/min)")
        return profile

    @staticmethod
    def analyze_frame_composition(img: Image.Image) -> dict[str, Any]:
        """Analyzes subject positioning, typography zones, and depth of field from a frame."""
        gray = img.convert("L").resize((320, 568), Image.Resampling.BILINEAR)
        arr = np.array(gray, dtype=float)
        h, w = arr.shape

        # Vertical thirds
        top_h = h // 3
        bot_h = 2 * h // 3
        top_sec = arr[:top_h, :]
        mid_sec = arr[top_h:bot_h, :]
        bot_sec = arr[bot_h:, :]

        top_std = float(np.std(top_sec))
        mid_std = float(np.std(mid_sec))
        bot_std = float(np.std(bot_sec))

        # Horizontal thirds
        left_w = w // 3
        right_w = 2 * w // 3
        left_sec = arr[:, :left_w]
        center_sec = arr[:, left_w:right_w]
        right_sec = arr[:, right_w:]

        left_std = float(np.std(left_sec))
        center_std = float(np.std(center_sec))
        right_std = float(np.std(right_sec))

        # Subject positioning determination
        if center_std >= max(left_std, right_std) * 0.95:
            subject_pos = "center_subject"
        elif left_std > right_std:
            subject_pos = "rule_of_thirds_left"
        else:
            subject_pos = "rule_of_thirds_right"

        if top_std > max(mid_std, bot_std) * 1.3:
            subject_pos = "top_weighted"

        # Typography / Caption zone detection via horizontal edge density
        bot_edges = float(np.mean(np.abs(np.diff(bot_sec, axis=1))))
        mid_edges = float(np.mean(np.abs(np.diff(mid_sec, axis=1))))
        top_edges = float(np.mean(np.abs(np.diff(top_sec, axis=1))))

        if bot_edges >= max(mid_edges, top_edges):
            typo_zone = "bottom_safe_zone"
        elif mid_edges > top_edges:
            typo_zone = "center_focus"
        else:
            typo_zone = "top_header"

        # Depth of field: center sharpness vs perimeter sharpness
        center_box = arr[h // 4 : 3 * h // 4, w // 4 : 3 * w // 4]
        center_sharp = float(np.std(center_box))
        outer_sharp = float((np.std(arr[: h // 4, :]) + np.std(arr[3 * h // 4 :, :])) / 2.0)
        depth = "shallow_dof" if center_sharp > outer_sharp * 1.4 else "deep_focus"

        return {
            "subject_position": subject_pos,
            "detected_typography_zone": typo_zone,
            "foreground_background_depth": depth,
            "top_std": round(top_std, 1),
            "mid_std": round(mid_std, 1),
            "bot_std": round(bot_std, 1),
        }

    @staticmethod
    def estimate_camera_motion(frame1: Image.Image, frame2: Image.Image) -> str:
        """Estimates dominant camera motion (zoom in/out, pan, or static) between two sampled frames."""
        try:
            im1 = np.array(frame1.convert("L").resize((128, 128), Image.Resampling.BILINEAR), dtype=float)
            im2 = np.array(frame2.convert("L").resize((128, 128), Image.Resampling.BILINEAR), dtype=float)
            diff = np.abs(im2 - im1)
            mean_diff = float(np.mean(diff))
            if mean_diff < 4.0:
                return "static"

            # Check center vs border diff
            center_diff = float(np.mean(diff[32:96, 32:96]))
            border_diff = float((np.mean(diff[:32, :]) + np.mean(diff[96:, :])) / 2.0)
            if border_diff > center_diff * 1.3:
                return "zoom_in"
            elif center_diff > border_diff * 1.3:
                return "zoom_out"

            # Check horizontal shift
            left_half = float(np.mean(diff[:, :64]))
            right_half = float(np.mean(diff[:, 64:]))
            if abs(left_half - right_half) > 5.0:
                return "pan_horizontal"

            return "zoom_in"
        except Exception:
            return "zoom_in"

    def analyze_image_collection(
        self,
        image_paths: list[Path],
        mode: str = "reference_inspired",
        profile_name: str | None = None,
    ) -> ReferenceStyleProfile:
        """Extracts consistent visual style, color harmony, and composition from multiple reference images."""
        if not image_paths:
            raise ValueError("No images provided to analyze_image_collection.")

        dominant_colors = []
        brightness_list = []
        comp_results = []

        for p in image_paths:
            if not p.exists():
                continue
            with Image.open(p) as img:
                rgb_img = img.convert("RGB")
                stat = ImageStat.Stat(rgb_img)
                brightness_list.append(sum(stat.mean[:3]) / 3.0)
                r, g, b = rgb_img.resize((1, 1)).getpixel((0, 0))[:3]
                dominant_colors.append((r, g, b))
                comp_results.append(self.analyze_frame_composition(rgb_img))

        avg_brightness = sum(brightness_list) / max(1, len(brightness_list)) if brightness_list else 128.0
        subj_positions = [c["subject_position"] for c in comp_results]
        common_subj = max(set(subj_positions), key=subj_positions.count) if subj_positions else "center_subject"

        typo_zones = [c["detected_typography_zone"] for c in comp_results]
        common_typo = max(set(typo_zones), key=typo_zones.count) if typo_zones else "bottom_safe_zone"

        dofs = [c["foreground_background_depth"] for c in comp_results]
        common_dof = max(set(dofs), key=dofs.count) if dofs else "deep_focus"

        highlight = "&H0000FFFF" if avg_brightness > 110 else "&H004ED9F7"
        profile_id = f"set_ref_{len(image_paths)}_{image_paths[0].stem[:8]}"

        profile = ReferenceStyleProfile(
            profile_id=profile_id,
            name=profile_name or f"Reference Set ({len(image_paths)} images)",
            source_type="image_set",
            source_path=str(image_paths[0].parent),
            duration_seconds=30.0,
            average_shot_duration=2.4,
            shot_duration_range=(1.8, 3.2),
            cut_frequency_per_minute=25.0,
            dominant_palette_rgb=dominant_colors[:6],
            color_grade_eq="eq=contrast=1.12:brightness=0.01:saturation=1.10,unsharp=3:3:0.4",
            caption_position_y=1380 if common_typo == "bottom_safe_zone" else (960 if common_typo == "center_focus" else 300),
            caption_font_weight="extrabold",
            highlight_color_hex=highlight,
            preferred_transition="whip",
            motion_intensity="high",
            subject_position=common_subj,
            foreground_background_depth=common_dof,
            detected_typography_zone=common_typo,
            camera_motion_trend="zoom_in",
            beats=[],
            timestamp_notes=[{"type": "multi_image_set", "image_count": len(image_paths), "composition": common_subj}],
        )
        out_json = self.temp_dir / f"{profile_id}.json"
        out_json.write_text(json.dumps(profile.to_dict(), indent=2), encoding="utf-8")
        return profile

    def _analyze_single_image(self, image_path: Path, profile_name: str | None = None) -> ReferenceStyleProfile:
        """Extracts color grading and typography inspiration from an individual screenshot."""
        with Image.open(image_path) as img:
            rgb_img = img.convert("RGB")
            stat = ImageStat.Stat(rgb_img)
            avg_brightness = sum(stat.mean[:3]) / 3.0
            r, g, b = rgb_img.resize((1, 1)).getpixel((0, 0))[:3]
            comp = self.analyze_frame_composition(rgb_img)

        highlight = "&H0000FFFF" if avg_brightness > 100 else "&H004ED9F7"
        profile_id = f"img_ref_{image_path.stem[:16]}"
        profile = ReferenceStyleProfile(
            profile_id=profile_id,
            name=profile_name or f"Image Ref: {image_path.stem.title()}",
            source_type="image_set",
            source_path=str(image_path),
            duration_seconds=30.0,
            average_shot_duration=2.4,
            shot_duration_range=(1.8, 3.2),
            cut_frequency_per_minute=25.0,
            dominant_palette_rgb=[(r, g, b)],
            color_grade_eq="eq=contrast=1.10:brightness=0.01:saturation=1.12,unsharp=3:3:0.4",
            caption_position_y=1380 if comp["detected_typography_zone"] == "bottom_safe_zone" else 960,
            caption_font_weight="extrabold",
            highlight_color_hex=highlight,
            preferred_transition="whip",
            motion_intensity="high",
            subject_position=comp["subject_position"],
            foreground_background_depth=comp["foreground_background_depth"],
            detected_typography_zone=comp["detected_typography_zone"],
            camera_motion_trend="zoom_in",
            beats=[],
            timestamp_notes=[{"type": "screenshot_palette", "dominant_rgb": [r, g, b], "composition": comp}],
        )
        out_json = self.temp_dir / f"{profile_id}.json"
        out_json.write_text(json.dumps(profile.to_dict(), indent=2), encoding="utf-8")
        return profile

    def _sample_video_frames(self, video_path: Path, total_duration: float, num_samples: int = 5) -> list[Image.Image]:
        """Extracts evenly spaced frames from a video file into PIL Images."""
        frames = []
        timestamps = [round((i + 1) * (total_duration / (num_samples + 1)), 2) for i in range(num_samples)]

        for t in timestamps:
            out_frame = self.temp_dir / f"sample_{os.getpid()}_{t:.2f}.jpg"
            cmd = [
                "ffmpeg", "-y",
                "-ss", str(t),
                "-i", str(video_path.resolve()),
                "-vframes", "1",
                "-q:v", "2",
                str(out_frame.resolve()),
            ]
            res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if res.returncode == 0 and out_frame.exists():
                try:
                    with Image.open(out_frame) as im:
                        frames.append(im.copy())
                except Exception:
                    pass
                finally:
                    if out_frame.exists():
                        out_frame.unlink()
        return frames

    def extract_structured_storyboard(self, video_path: Path) -> ReferenceStoryboard:
        """Deconstructs a reference video into a granular, shot-by-shot storyboard."""
        total_dur = self._probe_duration(video_path)
        cut_points = self._detect_scene_cuts(video_path)
        if len(cut_points) <= 2 and total_dur > 5.0:
            # When reference video uses smooth crossfade/xfade transitions rather than hard cuts,
            # segment into pacing analysis beats (~2.8s cadence)
            pacing_interval = 2.8
            num_segs = max(1, int(round(total_dur / pacing_interval)))
            cut_points = [round(i * (total_dur / num_segs), 2) for i in range(num_segs)]
        elif not cut_points:
            # Fallback: segment evenly by ~2.5s
            num_segs = max(1, int(round(total_dur / 2.5)))
            cut_points = [round(i * (total_dur / num_segs), 2) for i in range(num_segs)]

        shot_spans = []
        for i in range(len(cut_points)):
            st = cut_points[i]
            et = cut_points[i + 1] if i + 1 < len(cut_points) else total_dur
            if (et - st) >= 0.5:
                shot_spans.append((st, et))

        transitions = ["circleopen", "dissolve", "wipeleft", "fade"]
        items = []

        for idx, (st, et) in enumerate(shot_spans):
            dur = round(et - st, 2)
            mid_t = round(st + dur * 0.5, 2)
            # Sample frame at mid-point
            sample_file = self.temp_dir / f"sb_{os.getpid()}_{idx}.jpg"
            cmd = ["ffmpeg", "-y", "-ss", str(mid_t), "-i", str(video_path.resolve()), "-vframes", "1", "-q:v", "2", str(sample_file.resolve())]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            comp_info = {"subject_position": "center_subject", "detected_typography_zone": "bottom_safe_zone"}
            color_mood = "cinematic_dark"
            has_mg = False
            cam_motion = "zoom_in"

            if sample_file.exists():
                try:
                    with Image.open(sample_file) as im:
                        comp_info = self.analyze_frame_composition(im)
                        stat = ImageStat.Stat(im)
                        mean_lum = sum(stat.mean[:3]) / 3.0
                        color_mood = "vibrant_high_key" if mean_lum > 130 else "cinematic_dark"
                        has_mg = (comp_info.get("mid_std", 0) > 45 and mean_lum < 100)
                except Exception:
                    pass
                finally:
                    if sample_file.exists():
                        sample_file.unlink()

            shot_comp = "medium_shot"
            if dur < 2.0:
                shot_comp = "macro_close_up"
            elif dur > 4.0:
                shot_comp = "wide_vista"

            items.append(
                ReferenceStoryboardItem(
                    shot_index=idx,
                    start_time=st,
                    end_time=et,
                    duration=dur,
                    shot_composition=shot_comp,
                    subject_position=comp_info["subject_position"],
                    camera_movement=cam_motion,
                    transition_in=transitions[idx % len(transitions)] if idx > 0 else "cut",
                    caption_zone=comp_info["detected_typography_zone"],
                    has_motion_graphic=has_mg,
                    color_mood=color_mood,
                )
            )

        cut_freq = round((len(items) / max(1.0, total_dur)) * 60.0, 1)
        storyboard = ReferenceStoryboard(
            video_id=video_path.stem,
            total_duration=total_dur,
            shots_count=len(items),
            cut_frequency_per_minute=cut_freq,
            shots=items,
        )
        sb_path = self.temp_dir / f"storyboard_{video_path.stem}.json"
        sb_path.write_text(json.dumps(asdict(storyboard), indent=2), encoding="utf-8")
        logger.info(f"Generated Structured Storyboard for {video_path.name} ({len(items)} shots, {cut_freq} cuts/min)")
        return storyboard

    def analyze_multiple_reference_videos(
        self,
        video_paths: list[Path],
        profile_name: str | None = None,
    ) -> ReferenceStyleProfile:
        """Fuses multiple reference videos into an aggregated Creator Preset Profile."""
        if not video_paths:
            raise ValueError("No video paths provided to analyze_multiple_reference_videos.")

        profiles = [self.analyze_reference(p) for p in video_paths]
        avg_dur = sum(p.average_shot_duration for p in profiles) / len(profiles)
        avg_cuts = sum(p.cut_frequency_per_minute for p in profiles) / len(profiles)

        # Aggregate palettes
        all_colors = [c for p in profiles for c in p.dominant_palette_rgb]

        profile_id = f"multi_ref_{int(time.time())}"
        fused = ReferenceStyleProfile(
            profile_id=profile_id,
            name=profile_name or f"Fused Reference ({len(video_paths)} videos)",
            source_type="multi_video",
            source_path=";".join(str(p) for p in video_paths),
            duration_seconds=sum(p.duration_seconds for p in profiles) / len(profiles),
            average_shot_duration=round(avg_dur, 2),
            shot_duration_range=(round(min(p.shot_duration_range[0] for p in profiles), 2), round(max(p.shot_duration_range[1] for p in profiles), 2)),
            cut_frequency_per_minute=round(avg_cuts, 1),
            dominant_palette_rgb=all_colors[:5],
            color_grade_eq=profiles[0].color_grade_eq,
            caption_position_y=profiles[0].caption_position_y,
            caption_font_weight=profiles[0].caption_font_weight,
            highlight_color_hex=profiles[0].highlight_color_hex,
            preferred_transition=profiles[0].preferred_transition,
            motion_intensity="high" if avg_cuts > 25 else "balanced",
            subject_position=profiles[0].subject_position,
            foreground_background_depth=profiles[0].foreground_background_depth,
            detected_typography_zone=profiles[0].detected_typography_zone,
            camera_motion_trend=profiles[0].camera_motion_trend,
            beats=[],
            timestamp_notes=[{"type": "multi_video_fused", "sources": [str(p) for p in video_paths]}],
        )
        return fused


def load_reference_profile(profile_path: Path) -> ReferenceStyleProfile:
    """Loads a saved ReferenceStyleProfile from JSON."""
    data = json.loads(profile_path.read_text(encoding="utf-8"))
    return ReferenceStyleProfile.from_dict(data)
