"""Advanced Karaoke Subtitle Generator for Nova Autopilot v2.0.

Renders true word-by-word karaoke highlights in 2-4 word phrases,
centered in the lower-middle safe zone (y=1150 on 1080x1920, avoiding bottom 20% & Reels UI).
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from nova.config import NovaSettings
from nova.logging_setup import logger
from nova.tts import WordTiming


CAPTION_PRESETS = {
    "minimal_documentary": {
        "font_size": 48,
        "primary_color": (245, 245, 245, 255),
        "highlight_color": (255, 255, 255, 255),
        "outline_color": (0, 0, 0, 180),
        "outline_width": 3,
        "box_color": (15, 20, 25, 170),
        "y_pos": 1420,
        "words_per_group": 4,
    },
    "cinematic_storytelling": {
        "font_size": 52,
        "primary_color": (255, 255, 255, 255),
        "highlight_color": (247, 217, 78, 255),  # Amber gold
        "outline_color": (0, 0, 0, 220),
        "outline_width": 5,
        "box_color": None,
        "y_pos": 1380,
        "words_per_group": 3,
    },
    "high_energy_shorts": {
        "font_size": 60,
        "primary_color": (255, 255, 255, 255),
        "highlight_color": (0, 255, 255, 255),  # Cyan neon
        "outline_color": (0, 0, 0, 255),
        "outline_width": 7,
        "box_color": None,
        "y_pos": 1320,
        "words_per_group": 3,
    },
    "modern_educational": {
        "font_size": 52,
        "primary_color": (255, 255, 255, 255),
        "highlight_color": (255, 215, 0, 255),  # Bright gold
        "outline_color": (0, 0, 0, 200),
        "outline_width": 4,
        "box_color": (18, 24, 38, 190),
        "y_pos": 1380,
        "words_per_group": 3,
    },
    "bold_viral_facts": {
        "font_size": 60,
        "primary_color": (255, 255, 255, 255),
        "highlight_color": (255, 225, 0, 255),  # Electric yellow
        "outline_color": (0, 0, 0, 255),
        "outline_width": 7,
        "box_color": (10, 14, 22, 190),  # High-contrast backing pill
        "y_pos": 1350,
        "words_per_group": 3,
    },
    "dark_mystery": {
        "font_size": 50,
        "primary_color": (220, 225, 230, 255),
        "highlight_color": (0, 212, 212, 255),  # Icy cyan
        "outline_color": (0, 0, 0, 230),
        "outline_width": 5,
        "box_color": (10, 15, 20, 200),
        "y_pos": 1380,
        "words_per_group": 3,
    },
    "financial_explainer": {
        "font_size": 54,
        "primary_color": (255, 255, 255, 255),
        "highlight_color": (43, 215, 66, 255),  # Cash green
        "outline_color": (0, 0, 0, 240),
        "outline_width": 6,
        "box_color": (12, 25, 18, 180),
        "y_pos": 1380,
        "words_per_group": 3,
    },
}


def _format_ass_time(seconds: float) -> str:
    """Converts seconds into ASS timestamp format: H:MM:SS.cs"""
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centis = int(round((seconds - int(seconds)) * 100))
    if centis >= 100:
        centis = 99
    return f"{hrs}:{mins:02d}:{secs:02d}.{centis:02d}"


def _get_font(settings_or_size=None, font_size: int = 60) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Loads bundled Montserrat ExtraBold or system bold display font."""
    settings = None
    if isinstance(settings_or_size, int):
        font_size = settings_or_size
    elif settings_or_size is not None:
        settings = settings_or_size

    if settings is not None:
        try:
            font_file = settings.resolve_path(settings.video.subtitles.font_file)
            if font_file.exists():
                return ImageFont.truetype(str(font_file), font_size)
        except Exception:
            pass

    default_font = Path("assets/fonts/Montserrat-ExtraBold.ttf")
    if default_font.exists():
        try:
            return ImageFont.truetype(str(default_font.resolve()), font_size)
        except Exception:
            pass

    # System fallbacks
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Black.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for c in candidates:
        if Path(c).exists():
            try:
                return ImageFont.truetype(c, font_size)
            except Exception:
                continue
    return ImageFont.load_default()


class CaptionGenerator:
    def __init__(self, settings: NovaSettings):
        self.settings = settings
        self.words_per_group = getattr(settings.video.subtitles, "words_per_group", 3)
        self.safe_margin_y = getattr(settings.video.subtitles, "safe_margin_y", 1150)

    def create_ass_file(
        self,
        word_timings: list[WordTiming],
        output_ass_path: Path,
    ) -> Path:
        """Generates a high-impact .ass subtitle file with karaoke timing."""
        output_ass_path.parent.mkdir(parents=True, exist_ok=True)
        sub_cfg = self.settings.video.subtitles

        font_name = sub_cfg.font_name
        font_size = 56
        margin_v = 1920 - self.safe_margin_y - 80

        header = f"""[Script Info]
Title: Nova Autopilot Dynamic Karaoke Subtitles
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.601
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,6,2,2,60,60,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        dialogue_lines = []
        for i in range(0, len(word_timings), self.words_per_group):
            chunk = word_timings[i : i + self.words_per_group]
            if not chunk:
                continue

            # Produce a dialogue event for each active word in the chunk (karaoke)
            for active_idx, active_word in enumerate(chunk):
                start_str = _format_ass_time(active_word.start)
                end_str = _format_ass_time(active_word.end)

                text_tokens = []
                for idx, w in enumerate(chunk):
                    clean_w = w.word.strip().upper()
                    if idx == active_idx:
                        text_tokens.append(f"{{\\c&H0000FFFF&}}{clean_w}{{\\c&H00FFFFFF&}}")
                    else:
                        text_tokens.append(clean_w)

                line = f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{' '.join(text_tokens)}"
                dialogue_lines.append(line)

        full_ass_content = header + "\n".join(dialogue_lines) + "\n"
        output_ass_path.write_text(full_ass_content, encoding="utf-8")
        logger.info(f"Generated .ass karaoke subtitles with {len(dialogue_lines)} events at {output_ass_path.name}")
        return output_ass_path

    def create_overlay_bundle(
        self,
        word_timings: list[WordTiming],
        total_duration: float,
        output_dir: Path,
        watermark_text: str = "@NovaPrashantroy",
    ) -> Path:
        """Renders transparent PNG karaoke subtitle cards with real-time active word highlights."""
        output_dir.mkdir(parents=True, exist_ok=True)
        font = _get_font(self.settings, 58)
        watermark_font = _get_font(self.settings, 32)

        # Base template (watermark only)
        blank_img = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
        draw_b = ImageDraw.Draw(blank_img)
        if watermark_text:
            draw_b.text(
                (740, 80),
                watermark_text,
                font=watermark_font,
                fill=(255, 255, 255, 200),
                stroke_width=3,
                stroke_fill=(0, 0, 0, 255),
            )
        blank_path = output_dir / "sub_blank.png"
        blank_img.save(blank_path)

        # Group words into 2-4 word phrases
        chunks = []
        for i in range(0, len(word_timings), self.words_per_group):
            c = word_timings[i : i + self.words_per_group]
            if c:
                chunks.append(c)

        concat_lines = []
        current_time = 0.0
        frame_counter = 0

        for chunk in chunks:
            words = [w.word.strip().upper() for w in chunk]
            full_phrase = " ".join(words)

            # Precalculate width for center positioning
            dummy_draw = ImageDraw.Draw(blank_img)
            bbox = dummy_draw.textbbox((0, 0), full_phrase, font=font, stroke_width=7)
            total_w = bbox[2] - bbox[0]
            start_x = max(60, (1080 - total_w) // 2)
            y_pos = self.safe_margin_y

            # Render an image frame for EACH active word in the phrase
            for active_idx, active_word in enumerate(chunk):
                start = max(current_time, active_word.start)
                end = max(start + 0.15, active_word.end)

                # Blank gap before word if needed
                if start > current_time:
                    gap = round(start - current_time, 3)
                    if gap > 0.04:
                        concat_lines.append(f"file '{blank_path.name}'\nduration {gap}")

                sub_img = blank_img.copy()
                draw = ImageDraw.Draw(sub_img)

                cur_x = start_x
                for idx, w in enumerate(words):
                    # Active word in bright vivid yellow, other words in crisp white
                    is_active = idx == active_idx
                    fill_color = (255, 215, 0, 255) if is_active else (255, 255, 255, 255)

                    draw.text(
                        (cur_x, y_pos),
                        w,
                        font=font,
                        fill=fill_color,
                        stroke_width=7,
                        stroke_fill=(0, 0, 0, 255),
                    )
                    w_box = draw.textbbox((0, 0), w + " ", font=font, stroke_width=7)
                    cur_x += w_box[2] - w_box[0]

                frame_path = output_dir / f"karaoke_{frame_counter:04d}.png"
                sub_img.save(frame_path)
                frame_counter += 1

                dur = round(end - start, 3)
                concat_lines.append(f"file '{frame_path.name}'\nduration {dur}")
                current_time = end

        # Pad remaining video duration with blank
        if current_time < total_duration:
            rem = round(total_duration - current_time, 3)
            if rem > 0:
                concat_lines.append(f"file '{blank_path.name}'\nduration {rem}")

        # Final required line in FFmpeg concat demuxer
        concat_lines.append(f"file '{blank_path.name}'\n")

        concat_file = output_dir / "subs_concat.txt"
        concat_file.write_text("\n".join(concat_lines), encoding="utf-8")
        logger.info(f"Generated karaoke overlay bundle with {frame_counter} word highlight frames at {output_dir.name}")
        return concat_file

    def create_caption_stream(
        self,
        word_timings: list[WordTiming],
        total_duration: float,
        output_mov_path: Path,
        fps: int = 30,
        watermark_text: str = "@NovaPrashantroy",
        caption_preset: str = "bold_viral_facts",
    ) -> Path:
        """Renders a single continuous transparent RGBA video stream with karaoke word highlights.

        This replaces hundreds of individual PNGs in concat demuxers with a single .mov alpha track.
        """
        import subprocess

        output_mov_path.parent.mkdir(parents=True, exist_ok=True)
        preset_cfg = CAPTION_PRESETS.get(caption_preset, CAPTION_PRESETS["bold_viral_facts"])

        f_size = preset_cfg.get("font_size", 58)
        font = _get_font(self.settings, f_size)
        watermark_font = _get_font(self.settings, 32)
        primary_col = preset_cfg.get("primary_color", (255, 255, 255, 255))
        highlight_col = preset_cfg.get("highlight_color", (255, 215, 0, 255))
        outline_col = preset_cfg.get("outline_color", (0, 0, 0, 255))
        outline_w = preset_cfg.get("outline_width", 7)
        box_col = preset_cfg.get("box_color")
        y_pos = preset_cfg.get("y_pos", self.safe_margin_y)
        words_per_group = preset_cfg.get("words_per_group", self.words_per_group)

        # Base transparent background with watermark
        blank_img = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
        draw_b = ImageDraw.Draw(blank_img)
        if watermark_text:
            draw_b.text(
                (740, 80),
                watermark_text,
                font=watermark_font,
                fill=(255, 255, 255, 200),
                stroke_width=3,
                stroke_fill=(0, 0, 0, 255),
            )
        blank_bytes = blank_img.tobytes()

        # Group words into chunks
        chunks = []
        for i in range(0, len(word_timings), words_per_group):
            c = word_timings[i : i + words_per_group]
            if c:
                chunks.append(c)

        # Pre-render state images for each (chunk_index, active_word_index)
        rendered_states: dict[tuple[int, int], bytes] = {}
        for c_idx, chunk in enumerate(chunks):
            words = [w.word.strip().upper() for w in chunk]
            full_phrase = " ".join(words)
            dummy_draw = ImageDraw.Draw(blank_img)
            bbox = dummy_draw.textbbox((0, 0), full_phrase, font=font, stroke_width=outline_w)
            total_w = bbox[2] - bbox[0]
            phrase_h = bbox[3] - bbox[1]
            start_x = max(60, (1080 - total_w) // 2)

            for active_idx in range(len(chunk)):
                sub_img = blank_img.copy()
                draw = ImageDraw.Draw(sub_img)

                # Draw pill box background if preset specifies it
                if box_col:
                    draw.rounded_rectangle(
                        [start_x - 24, y_pos - 12, start_x + total_w + 24, y_pos + phrase_h + 16],
                        radius=16,
                        fill=box_col,
                    )

                cur_x = start_x
                for idx, w in enumerate(words):
                    is_active = idx == active_idx
                    fill_color = highlight_col if is_active else primary_col
                    draw.text(
                        (cur_x, y_pos),
                        w,
                        font=font,
                        fill=fill_color,
                        stroke_width=outline_w,
                        stroke_fill=outline_col,
                    )
                    w_box = draw.textbbox((0, 0), w + " ", font=font, stroke_width=outline_w)
                    cur_x += w_box[2] - w_box[0]
                rendered_states[(c_idx, active_idx)] = sub_img.tobytes()

        total_frames = max(1, int(round(total_duration * fps)))

        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "rawvideo",
            "-vcodec",
            "rawvideo",
            "-s",
            "1080x1920",
            "-pix_fmt",
            "rgba",
            "-r",
            str(fps),
            "-i",
            "-",
            "-c:v",
            "png",
            "-pix_fmt",
            "rgba",
            "-t",
            str(round(total_duration, 3)),
            str(output_mov_path.resolve()),
        ]

        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

        for f_idx in range(total_frames):
            t = f_idx / fps
            frame_bytes = blank_bytes

            for c_idx, chunk in enumerate(chunks):
                chunk_start = chunk[0].start
                chunk_end = max(chunk_start + 0.2, chunk[-1].end)
                if chunk_start <= t <= chunk_end:
                    for active_idx, w in enumerate(chunk):
                        w_end = max(w.start + 0.1, w.end)
                        if w.start <= t <= w_end or (active_idx == len(chunk) - 1 and t > w.start):
                            frame_bytes = rendered_states.get((c_idx, active_idx), blank_bytes)
                            break
                    break

            proc.stdin.write(frame_bytes)

        proc.stdin.close()
        stderr_bytes = proc.stderr.read() if proc.stderr else b""
        proc.wait()
        if proc.returncode != 0:
            logger.error(f"Failed to generate transparent caption stream: {stderr_bytes.decode()}")
            raise RuntimeError(f"FFmpeg caption stream failed: {stderr_bytes.decode()[:300]}")

        logger.info(f"Generated single transparent caption stream ({total_frames} frames) at {output_mov_path.name}")
        return output_mov_path
