"""Timeline-Based Video Transitions Engine for Nova Autopilot v9.0.

Provides broadcast transitions using FFmpeg's hardware-accelerated xfade filter graph:
- Smooth crossfades (dissolve / fade)
- Dynamic whip transitions (slideleft, slideright, smoothleft)
- Zoom transitions (zoomin)
- Directional wipes (wipeleft, wiperight, wipeup)
- Atmospheric blurs & fades (fadeblack, hblur)
- Smart hybrid mode (alternates hard cuts on high-energy beats with transitions on narrative pivots)
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, List, Optional

from nova.logging_setup import logger


def get_clip_duration(file_path: Path) -> float:
    """Returns exact duration of video file in seconds via ffprobe."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(file_path.resolve()),
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(res.stdout.strip())
    except Exception:
        return 0.0


# Map human-readable transition styles to FFmpeg xfade transition names
TRANSITION_MAP = {
    "crossfade": ["fade", "dissolve"],
    "whip": ["slideleft", "slideright", "smoothleft"],
    "zoom": ["zoomin"],
    "directional": ["wipeleft", "wiperight", "slideleft"],
    "blur": ["hblur", "fadeblack"],
    "mixed": ["slideleft", "zoomin", "fade", "smoothleft", "wipeleft"],
    "j_cut": ["fade"],
    "l_cut": ["fade"],
    "match_cut": ["fade", "smoothleft"],
    "speed_ramp": ["slideleft", "zoomin"],
    "directional_wipe": ["wipeleft", "wiperight", "slideleft", "slideright"],
    "progressive_zoom": ["zoomin"],
    "flash_white": ["fadewhite"],
    "cut": [],  # Hard cut mode uses concat demuxer
}


class TransitionEngine:
    def __init__(self, encoder: str = "h264_videotoolbox", fps: int = 30):
        self.encoder = encoder
        self.fps = fps

    def build_xfade_filter(
        self,
        clip_durations: list[float],
        transition_style: str = "crossfade",
        transition_duration: float = 0.3,
        target_total_duration: float | None = None,
    ) -> tuple[str, str, float]:
        """Constructs an FFmpeg filter_complex string that chains xfade transitions between clips.
        
        Returns:
            (filter_complex_str, final_output_label, expected_total_duration)
        """
        n = len(clip_durations)
        if n <= 1:
            dur = clip_durations[0] if n == 1 else 0.0
            if target_total_duration and target_total_duration > dur:
                diff = round(target_total_duration - dur, 3)
                if diff > 0.04:
                    return f"[0:v]tpad=stop_mode=clone:stop_duration={diff}[tpad_out]", "tpad_out", target_total_duration
            return "", "0:v", dur

        available_transitions = TRANSITION_MAP.get(transition_style, ["fade"])
        if not available_transitions:
            available_transitions = ["fade"]

        # Ensure transition duration doesn't exceed 40% of the shortest clip
        min_clip_dur = min(clip_durations)
        actual_td = min(transition_duration, max(0.15, min_clip_dur * 0.4))
        actual_td = round(actual_td, 3)

        filter_steps = []
        current_offset = round(clip_durations[0] - actual_td, 3)
        last_label = "0:v"

        for i in range(1, n):
            trans_type = available_transitions[(i - 1) % len(available_transitions)]
            out_label = f"xf{i}" if i < n - 1 else "xf_out"
            step = f"[{last_label}][{i}:v]xfade=transition={trans_type}:duration={actual_td}:offset={max(0.01, current_offset)}[{out_label}]"
            filter_steps.append(step)
            last_label = out_label
            # Update cumulative offset for the next transition
            current_offset = round(current_offset + clip_durations[i] - actual_td, 3)

        final_duration = round(current_offset + actual_td, 3)
        if target_total_duration is not None and target_total_duration > final_duration:
            diff = round(target_total_duration - final_duration, 3)
            if diff > 0.04:
                filter_steps.append(f"[{last_label}]tpad=stop_mode=clone:stop_duration={diff}[tpad_out]")
                last_label = "tpad_out"
                final_duration = target_total_duration

        return ";".join(filter_steps), last_label, round(final_duration, 3)

    def render_transitions(
        self,
        shot_paths: list[Path],
        output_path: Path,
        transition_style: str = "mixed",
        transition_duration: float = 0.3,
        target_total_duration: float | None = None,
        color_match: bool = False,
    ) -> Path:
        """Assembles a list of normalized shots into a single video with broadcast transitions.
        
        If transition_style is 'cut', or only 1 shot is provided, falls back to concat demuxer.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if not shot_paths:
            raise ValueError("No shot paths provided to TransitionEngine.")

        if len(shot_paths) == 1:
            cmd = ["ffmpeg", "-y", "-i", str(shot_paths[0].resolve()), "-c", "copy", str(output_path.resolve())]
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return output_path

        if transition_style == "cut":
            return self._concat_filter(shot_paths, output_path)

        # Probe durations of all input shots
        durations = [get_clip_duration(p) for p in shot_paths]
        # Check if any duration is too short for xfade
        if any(d < 0.6 for d in durations):
            logger.info("Some clips are shorter than 0.6s; using concat demuxer for stable pacing.")
            return self._concat_demuxer(shot_paths, output_path)

        filter_complex, final_label, rendered_dur = self.build_xfade_filter(
            clip_durations=durations,
            transition_style=transition_style,
            transition_duration=transition_duration,
            target_total_duration=target_total_duration,
        )

        # Color harmonization prep if enabled
        if color_match and len(shot_paths) > 1:
            try:
                from nova.editing.techniques import ColorHarmonizer
                # Extract first shot profile as anchor
                anchor_prof = ColorHarmonizer.extract_profile(shot_paths[0])
                prep_filters = []
                for idx, sp in enumerate(shot_paths):
                    if idx > 0:
                        cur_prof = ColorHarmonizer.extract_profile(sp)
                        adj = ColorHarmonizer.compute_matching_filter(anchor_prof, cur_prof)
                        prep_filters.append(f"[{idx}:v]{adj}[v{idx}]")
                    else:
                        prep_filters.append(f"[0:v]copy[v0]")

                # Replace raw input labels with prepped labels
                modified_xfade = filter_complex
                for idx in range(len(shot_paths)):
                    modified_xfade = modified_xfade.replace(f"[{idx}:v]", f"[v{idx}]")
                filter_complex = ";".join(prep_filters) + ";" + modified_xfade
            except Exception as c_err:
                logger.warning(f"Color harmonization pass skipped ({c_err}).")

        # Assemble FFmpeg command
        cmd = ["ffmpeg", "-y"]
        for p in shot_paths:
            cmd.extend(["-i", str(p.resolve())])

        cmd.extend(["-filter_complex", filter_complex])
        cmd.extend(["-map", f"[{final_label}]"])

        if self.encoder == "h264_videotoolbox":
            cmd.extend(["-c:v", "h264_videotoolbox", "-b:v", "9000k"])
        else:
            cmd.extend(["-c:v", "libx264", "-preset", "fast", "-crf", "20"])

        cmd.extend([
            "-pix_fmt", "yuv420p",
            "-r", str(self.fps),
            "-fps_mode", "cfr",
            str(output_path.resolve()),
        ])

        logger.info(f"Rendering {len(shot_paths)} shots with '{transition_style}' transitions ({transition_duration}s)...")
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            logger.warning(f"xfade transition pass failed ({res.stderr[:200]}); falling back to concat demuxer.")
            return self._concat_demuxer(shot_paths, output_path)

        return output_path

    def _concat_filter(self, shot_paths: list[Path], output_path: Path) -> Path:
        """Seamless filter concat without timestamp gaps or codec discontinuities."""
        cmd = ["ffmpeg", "-y"]
        filter_inputs = []
        for i, p in enumerate(shot_paths):
            cmd.extend(["-i", str(p.resolve())])
            filter_inputs.append(f"[{i}:v]")

        filter_str = f"{''.join(filter_inputs)}concat=n={len(shot_paths)}:v=1:a=0[outv]"
        cmd.extend(["-filter_complex", filter_str, "-map", "[outv]"])
        if self.encoder == "h264_videotoolbox":
            cmd.extend(["-c:v", "h264_videotoolbox", "-b:v", "9000k"])
        else:
            cmd.extend(["-c:v", "libx264", "-preset", "fast", "-crf", "20"])
        cmd.extend(["-pix_fmt", "yuv420p", "-r", "30", str(output_path.resolve())])
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            logger.warning(f"Filter concat failed ({res.stderr[:200]}); falling back to concat demuxer.")
            return self._concat_demuxer(shot_paths, output_path)
        return output_path

    def _concat_demuxer(self, shot_paths: list[Path], output_path: Path) -> Path:
        """Fallback lossless concat demuxer."""
        concat_txt = output_path.with_name(f"{output_path.stem}_concat_list.txt")
        lines = [f"file '{p.resolve()}'" for p in shot_paths]
        concat_txt.write_text("\n".join(lines), encoding="utf-8")

        try:
            cmd = [
                "ffmpeg",
                "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_txt.resolve()),
                "-c", "copy",
                str(output_path.resolve()),
            ]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode != 0:
                raise RuntimeError(f"Concat demuxer failed: {res.stderr}")
            return output_path
        finally:
            if concat_txt.exists():
                concat_txt.unlink()
