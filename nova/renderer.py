"""FFmpeg subprocess assembly engine with hardware acceleration (VideoToolbox) and robust subtitle overlay."""

import subprocess
from pathlib import Path

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
    ) -> Path:
        """Assembles scene clips, mixes master audio, burns in subtitles/watermark, and produces final MP4."""
        output_video_path.parent.mkdir(parents=True, exist_ok=True)
        temp_concat_path = output_video_path.with_name(f"{output_video_path.stem}_visuals.mp4")

        # Step 1: Concatenate scene video clips
        self._concat_videos(scene_video_paths, temp_concat_path)

        encoder_args = ["-c:v", self.encoder]
        if self.encoder == "libx264":
            encoder_args.extend(["-preset", "fast", "-crf", "22"])
        elif self.encoder == "h264_videotoolbox":
            encoder_args.extend(["-b:v", self.settings.video.bitrate])

        # Decide subtitle burning method:
        # Case A: Subtitle overlay stream (bulletproof and hardware accelerated)
        if subtitle_overlay_concat_path and subtitle_overlay_concat_path.exists():
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
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-pix_fmt",
                "yuv420p",
                "-t",
                str(total_duration),
                "-movflags",
                "+faststart",
                str(output_video_path.resolve()),
            ]
        # Case B: Native libass filter if compiled
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
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-pix_fmt",
                "yuv420p",
                "-t",
                str(total_duration),
                "-movflags",
                "+faststart",
                str(output_video_path.resolve()),
            ]
        # Case C: Clean video without subtitle burn-in
        else:
            cmd = [
                "ffmpeg",
                "-y",
                "-i",
                str(temp_concat_path.resolve()),
                "-i",
                str(audio_path.resolve()),
                *encoder_args,
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-pix_fmt",
                "yuv420p",
                "-t",
                str(total_duration),
                "-movflags",
                "+faststart",
                str(output_video_path.resolve()),
            ]

        logger.info(f"Rendering final MP4 to {output_video_path.name} ({total_duration:.1f}s)...")
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            logger.error(f"FFmpeg assembly failed: {res.stderr}")
            raise RuntimeError(f"FFmpeg rendering failed: {res.stderr}")

        # Clean up temporary visuals file
        if temp_concat_path.exists():
            temp_concat_path.unlink()

        logger.info(f"[bold green]Video successfully rendered at: {output_video_path}[/bold green]")
        return output_video_path

    def _concat_videos(self, video_paths: list[Path], output_path: Path):
        """Concatenates multiple video clips using FFmpeg concat filter for rock-solid PTS synchronization."""
        if not video_paths:
            raise ValueError("No video paths provided for concatenation.")
        if len(video_paths) == 1:
            cmd = [
                "ffmpeg",
                "-y",
                "-i",
                str(video_paths[0].resolve()),
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-pix_fmt",
                "yuv420p",
                str(output_path.resolve()),
            ]
            subprocess.run(cmd, check=True)
            return

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
                str(output_path.resolve()),
            ]
        )
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"FFmpeg concat failed: {res.stderr}")
