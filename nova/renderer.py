"""FFmpeg subprocess assembly engine with hardware acceleration (VideoToolbox) and robust subtitle overlay."""

import json
import subprocess
from pathlib import Path
from typing import Any

from nova.config import NovaSettings
from nova.logging_setup import logger


def detect_video_encoder() -> str:
    """Detects if Apple Silicon h264_videotoolbox is available in FFmpeg build."""
    try:
        cmd = ["ffmpeg", "-encoders"]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        if "h264_videotoolbox" in res.stdout:
            return "h264_videotoolbox"
    except Exception:
        pass
    return "libx264"


def has_ffmpeg_filter(filter_name: str) -> bool:
    """Checks whether a specific filter is compiled into FFmpeg."""
    try:
        cmd = ["ffmpeg", "-filters"]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        for line in res.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1] == filter_name:
                return True
    except Exception:
        pass
    return False


def get_stream_probe(file_path: Path) -> dict[str, Any]:
    """Extracts duration, nb_frames, codec, and fps for video and audio streams."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "stream=index,codec_type,codec_name,duration,nb_frames,r_frame_rate,avg_frame_rate,pix_fmt",
        "-show_entries",
        "format=duration,size,bit_rate",
        "-of",
        "json",
        str(file_path.resolve()),
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return json.loads(res.stdout)
    except Exception:
        return {}


class VideoRenderer:
    def __init__(self, settings: NovaSettings):
        self.settings = settings
        self.encoder = detect_video_encoder() if settings.video.codec == "auto" else settings.video.codec
        self.supports_ass = has_ffmpeg_filter("ass")
        self.supports_drawtext = has_ffmpeg_filter("drawtext")
        logger.info(
            f"VideoRenderer initialized: Encoder=[bold green]{self.encoder}[/bold green], "
            f"libass={'[green]YES[/green]' if self.supports_ass else '[yellow]NO (using overlay engine)[/yellow]'}"
        )

    def assemble_video(
        self,
        scene_video_paths: list[Path],
        audio_path: Path,
        subtitle_path: Path | None,
        output_video_path: Path,
        total_duration: float,
        subtitle_overlay_concat_path: Path | None = None,
        subtitle_stream_path: Path | None = None,
        motion_overlay_stream_path: Path | None = None,
        timeline_plan: Any | None = None,
        apply_color_grade: bool = True,
    ) -> Path:
        """Assembles normalized shot clips, mixes master audio, burns in subtitles, and produces final MP4."""
        output_video_path.parent.mkdir(parents=True, exist_ok=True)
        temp_concat_path = output_video_path.with_name(f"{output_video_path.stem}_visuals.mp4")
        render_log_path = output_video_path.with_name("render_log.json")
        commands_log: list[dict[str, Any]] = []

        # Step 1: Concatenate scene video clips using concat demuxer (lossless & instant)
        self._concat_shots_demuxer(scene_video_paths, temp_concat_path, commands_log)

        # Step 2: Configure encoder
        encoder_args = ["-c:v", self.encoder]
        if self.encoder == "libx264":
            encoder_args.extend(["-preset", "fast", "-crf", "22", "-profile:v", "high"])
        elif self.encoder == "h264_videotoolbox":
            encoder_args.extend(["-b:v", self.settings.video.bitrate, "-profile:v", "high"])

        # Determine exact target duration from audio to ensure video stream duration == audio duration within 0.05s
        from nova.visuals import get_media_duration

        true_audio_dur = get_media_duration(audio_path)
        target_dur = round(true_audio_dur, 3) if true_audio_dur > 0.5 else round(total_duration, 3)

        # Step 3: Composite final video + audio + subtitles + motion design
        grade_prefix = (
            "[0:v]eq=contrast=1.06:brightness=0.01:saturation=1.08,unsharp=3:3:0.4,vignette=PI/5[graded];"
            if apply_color_grade
            else "[0:v]copy[graded];"
        )

        has_subtitles = subtitle_stream_path and subtitle_stream_path.exists()
        has_motion = motion_overlay_stream_path and motion_overlay_stream_path.exists()

        if has_subtitles and has_motion:
            filter_complex = f"{grade_prefix}[graded][2:v]overlay=0:0[with_motion];[with_motion][1:v]overlay=0:0,scale=out_color_matrix=bt709:out_range=tv,format=yuv420p[outv]"
            cmd = [
                "ffmpeg",
                "-y",
                "-i",
                str(temp_concat_path.resolve()),
                "-i",
                str(subtitle_stream_path.resolve()),
                "-i",
                str(motion_overlay_stream_path.resolve()),
                "-i",
                str(audio_path.resolve()),
                "-filter_complex",
                filter_complex,
                "-map",
                "[outv]",
                "-map",
                "3:a",
                *encoder_args,
                "-af",
                f"apad=whole_dur={target_dur}",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-pix_fmt",
                "yuv420p",
                "-color_range",
                "tv",
                "-color_range",
                "tv",
                "-r",
                "30",
                "-fps_mode",
                "cfr",
                "-t",
                str(target_dur),
                "-movflags",
                "+faststart",
                str(output_video_path.resolve()),
            ]
        elif has_subtitles:
            filter_complex = f"{grade_prefix}[graded][1:v]overlay=0:0,scale=out_color_matrix=bt709:out_range=tv,format=yuv420p[outv]"
            cmd = [
                "ffmpeg",
                "-y",
                "-i",
                str(temp_concat_path.resolve()),
                "-i",
                str(subtitle_stream_path.resolve()),
                "-i",
                str(audio_path.resolve()),
                "-filter_complex",
                filter_complex,
                "-map",
                "[outv]",
                "-map",
                "2:a",
                *encoder_args,
                "-af",
                f"apad=whole_dur={target_dur}",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-pix_fmt",
                "yuv420p",
                "-color_range",
                "tv",
                "-r",
                "30",
                "-fps_mode",
                "cfr",
                "-t",
                str(target_dur),
                "-movflags",
                "+faststart",
                str(output_video_path.resolve()),
            ]
        # Mode 2: Legacy PNG concat demuxer (if passed)
        elif subtitle_overlay_concat_path and subtitle_overlay_concat_path.exists():
            cmd = [
                "ffmpeg",
                "-y",
                "-i",
                str(temp_concat_path.resolve()),
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(subtitle_overlay_concat_path.resolve()),
                "-i",
                str(audio_path.resolve()),
                "-filter_complex",
                "[0:v][1:v]overlay=0:0:eof_action=pass[outv]",
                "-map",
                "[outv]",
                "-map",
                "2:a",
                *encoder_args,
                "-af",
                f"apad=whole_dur={target_dur}",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-pix_fmt",
                "yuv420p",
                "-color_range",
                "tv",
                "-r",
                "30",
                "-fps_mode",
                "cfr",
                "-t",
                str(target_dur),
                "-movflags",
                "+faststart",
                str(output_video_path.resolve()),
            ]
        # Mode 3: Native libass filter if compiled
        elif self.supports_ass and subtitle_path and subtitle_path.exists():
            clean_sub_path = str(subtitle_path.resolve()).replace("\\", "/").replace(":", "\\:")
            vf = f"ass='{clean_sub_path}'"
            if self.supports_drawtext and self.settings.video.watermark_text:
                wm = self.settings.video.watermark_text
                vf += f",drawtext=text='{wm}':x=w-tw-40:y=80:fontsize=32:fontcolor=white@0.7:box=1:boxcolor=black@0.4:boxborderw=8"

            cmd = [
                "ffmpeg",
                "-y",
                "-i",
                str(temp_concat_path.resolve()),
                "-i",
                str(audio_path.resolve()),
                "-vf",
                vf,
                *encoder_args,
                "-af",
                f"apad=whole_dur={target_dur}",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-pix_fmt",
                "yuv420p",
                "-color_range",
                "tv",
                "-r",
                "30",
                "-fps_mode",
                "cfr",
                "-t",
                str(target_dur),
                "-movflags",
                "+faststart",
                str(output_video_path.resolve()),
            ]
        # Mode 4: Audio mix only
        else:
            cmd = [
                "ffmpeg",
                "-y",
                "-i",
                str(temp_concat_path.resolve()),
                "-i",
                str(audio_path.resolve()),
                *encoder_args,
                "-af",
                f"apad=whole_dur={target_dur}",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-pix_fmt",
                "yuv420p",
                "-color_range",
                "tv",
                "-r",
                "30",
                "-fps_mode",
                "cfr",
                "-t",
                str(target_dur),
                "-movflags",
                "+faststart",
                str(output_video_path.resolve()),
            ]

        logger.info(f"Rendering final MP4 to {output_video_path.name} ({total_duration:.1f}s)...")
        res = subprocess.run(cmd, capture_output=True, text=True)
        commands_log.append(
            {
                "stage": "final_composite",
                "command": " ".join(cmd),
                "returncode": res.returncode,
                "stderr": res.stderr[-1000:] if res.stderr else "",
            }
        )

        if res.returncode != 0:
            logger.warning(f"Hardware encoder failed, falling back to libx264: {res.stderr[:300]}")
            cmd_fallback = list(cmd)
            if "h264_videotoolbox" in cmd_fallback:
                idx = cmd_fallback.index("h264_videotoolbox")
                cmd_fallback[idx] = "libx264"
                res_fb = subprocess.run(cmd_fallback, capture_output=True, text=True)
                commands_log.append(
                    {
                        "stage": "final_composite_fallback",
                        "command": " ".join(cmd_fallback),
                        "returncode": res_fb.returncode,
                        "stderr": res_fb.stderr[-1000:] if res_fb.stderr else "",
                    }
                )
                if res_fb.returncode != 0:
                    raise RuntimeError(f"FFmpeg rendering failed: {res_fb.stderr}")
            else:
                raise RuntimeError(f"FFmpeg rendering failed: {res.stderr}")

        # Clean up temporary visuals master file
        if temp_concat_path.exists():
            temp_concat_path.unlink()

        # Step 4: Validate output integrity and save render log
        probe_info = get_stream_probe(output_video_path)
        log_payload = {
            "output_video": str(output_video_path),
            "total_duration_target": round(total_duration, 3),
            "commands": commands_log,
            "probe": probe_info,
        }
        render_log_path.write_text(json.dumps(log_payload, indent=2), encoding="utf-8")

        logger.info(f"[bold green]Video successfully rendered at: {output_video_path}[/bold green]")
        return output_video_path

    def _concat_shots_demuxer(self, video_paths: list[Path], output_path: Path, commands_log: list[dict]):
        """Concatenates normalized shot clips using FFmpeg concat demuxer (lossless stream copy)."""
        if not video_paths:
            raise ValueError("No video paths provided for concatenation.")

        if len(video_paths) == 1:
            cmd = [
                "ffmpeg",
                "-y",
                "-i",
                str(video_paths[0].resolve()),
                "-c",
                "copy",
                str(output_path.resolve()),
            ]
            res = subprocess.run(cmd, capture_output=True, text=True)
            commands_log.append({"stage": "single_shot_copy", "command": " ".join(cmd), "returncode": res.returncode})
            if res.returncode != 0:
                raise RuntimeError(f"FFmpeg single shot copy failed: {res.stderr}")
            return

        # Write concat list file
        concat_txt = output_path.with_name(f"{output_path.stem}_concat.txt")
        lines = [f"file '{p.resolve()}'" for p in video_paths]
        concat_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")

        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_txt.resolve()),
            "-c",
            "copy",
            str(output_path.resolve()),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        commands_log.append(
            {
                "stage": "concat_demuxer",
                "command": " ".join(cmd),
                "returncode": res.returncode,
                "stderr": res.stderr[-500:] if res.stderr else "",
            }
        )

        if res.returncode != 0:
            # Fallback to filter concat if stream copy fails
            logger.warning(f"Concat demuxer failed ({res.stderr[:200]}), falling back to filter concat.")
            self._concat_videos_filter(video_paths, output_path, commands_log)

        if concat_txt.exists():
            concat_txt.unlink()

    def _concat_videos_filter(self, video_paths: list[Path], output_path: Path, commands_log: list[dict]):
        """Fallback concatenation using concat filter."""
        cmd = ["ffmpeg", "-y"]
        filter_parts = []
        for idx, p in enumerate(video_paths):
            cmd.extend(["-i", str(p.resolve())])
            filter_parts.append(f"[{idx}:v]setsar=1[v{idx}]")

        concat_inputs = "".join(f"[v{idx}]" for idx in range(len(video_paths)))
        filter_complex = f"{'; '.join(filter_parts)}; {concat_inputs}concat=n={len(video_paths)}:v=1:a=0[outv]"

        cmd.extend(
            [
                "-filter_complex",
                filter_complex,
                "-map",
                "[outv]",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-pix_fmt",
                "yuv420p",
                "-color_range",
                "tv",
                "-r",
                "30",
                "-fps_mode",
                "cfr",
                str(output_path.resolve()),
            ]
        )
        res = subprocess.run(cmd, capture_output=True, text=True)
        commands_log.append({"stage": "filter_concat_fallback", "command": " ".join(cmd), "returncode": res.returncode})
        if res.returncode != 0:
            raise RuntimeError(f"FFmpeg filter concat failed: {res.stderr}")
