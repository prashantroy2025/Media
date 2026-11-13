"""Thumbnail generator for vertical Shorts and Reels using Pillow and frame extraction."""

import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

from nova.captions import _get_font
from nova.config import NovaSettings
from nova.logging_setup import logger


class ThumbnailGenerator:
    def __init__(self, settings: NovaSettings):
        self.settings = settings

    def generate_thumbnail(
        self,
        video_path: Path,
        title: str,
        output_thumbnail_path: Path,
        timestamp_sec: float = 1.5,
    ) -> Path:
        """Extracts a frame from video and renders high-impact title branding via Pillow."""
        output_thumbnail_path.parent.mkdir(parents=True, exist_ok=True)
        raw_frame = output_thumbnail_path.with_name(f"{output_thumbnail_path.stem}_raw.jpg")

        # Step 1: Extract clean video frame via FFmpeg
        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            str(timestamp_sec),
            "-i",
            str(video_path.resolve()),
            "-vframes",
            "1",
            str(raw_frame.resolve()),
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not raw_frame.exists() or raw_frame.stat().st_size == 0:
            # Create a procedural background if frame extraction fails
            base_img = Image.new("RGB", (1080, 1920), (15, 23, 42))
        else:
            base_img = Image.open(raw_frame).convert("RGBA")

        # Step 2: Draw punchy thumbnail title card overlay
        overlay = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # Semi-transparent dark banner in upper-middle
        banner_y1 = 650
        banner_y2 = 1100
        draw.rectangle([0, banner_y1, 1080, banner_y2], fill=(0, 0, 0, 180))

        title_font = _get_font(self.settings, 60)
        handle_font = _get_font(self.settings, 36)

        # Word wrap title to fit 1080px width
        words = title.upper().split()
        lines = []
        cur_line = []
        for w in words:
            test_line = " ".join(cur_line + [w])
            bbox = draw.textbbox((0, 0), test_line, font=title_font)
            if (bbox[2] - bbox[0]) > 940 and cur_line:
                lines.append(" ".join(cur_line))
                cur_line = [w]
            else:
                cur_line.append(w)
        if cur_line:
            lines.append(" ".join(cur_line))

        # Draw Title Lines (Yellow with black stroke)
        y_text = banner_y1 + 50
        for line in lines[:3]:
            bbox = draw.textbbox((0, 0), line, font=title_font, stroke_width=6)
            text_w = bbox[2] - bbox[0]
            x_pos = (1080 - text_w) // 2
            draw.text(
                (x_pos, y_text),
                line,
                font=title_font,
                fill=(255, 230, 0, 255),
                stroke_width=6,
                stroke_fill=(0, 0, 0, 255),
            )
            y_text += 85

        # Draw Creator Handle
        handle = self.settings.channel.handle
        bbox_h = draw.textbbox((0, 0), handle, font=handle_font, stroke_width=3)
        h_w = bbox_h[2] - bbox_h[0]
        draw.text(
            ((1080 - h_w) // 2, y_text + 20),
            handle,
            font=handle_font,
            fill=(255, 255, 255, 230),
            stroke_width=4,
            stroke_fill=(0, 0, 0, 255),
        )

        # Composite together
        final_thumb = Image.alpha_composite(base_img.convert("RGBA"), overlay)
        final_thumb.convert("RGB").save(output_thumbnail_path, quality=95)

        if raw_frame.exists():
            raw_frame.unlink()

        logger.info(f"Generated high-impact thumbnail at {output_thumbnail_path.name}")
        return output_thumbnail_path
