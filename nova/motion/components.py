"""Reusable Motion Design Animation Components for Nova Autopilot v8.0.

Renders 30 fps memory-safe frame overlays using Pillow with supersampling and mathematical easing:
- KineticTextPop: Spring-overshoot word scale with underline wipe
- AnimatedCounter: Number counting up with unit formatting and source badge
- ComparisonVisual: Dual comparison bars with percentage fill
- TimelineWipe: Milestone timeline with connected glowing nodes
- CalloutHighlight: Expanding radar pulse circle and pointing arrow
- LowerThirdSourceTag: Verified source pill
- ProgressBar: Thin neon progress bar
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Tuple

from PIL import Image, ImageDraw, ImageFilter

from nova.motion.brand import BRAND_PALETTES, FontManager, NichePalette
from nova.motion.easing import ease_out_cubic, ease_out_expo, lerp, spring_overshoot

font_mgr = FontManager()


class MotionComponent:
    """Base class for timed motion overlay components."""

    def render_frame(self, canvas: Image.Image, t_rel: float, niche: str = "ai_tech") -> None:
        """Renders the component onto canvas in-place at relative time t_rel (seconds)."""
        raise NotImplementedError


class KineticTextPop(MotionComponent):
    """Large animated keyword with scale spring overshoot and underline wipe."""

    def __init__(
        self,
        text: str,
        start_time: float,
        duration: float = 1.4,
        center_pos: Tuple[int, int] = (540, 680),
        font_size: int = 76,
    ):
        self.text = text.upper()
        self.start_time = start_time
        self.duration = duration
        self.center_pos = center_pos
        self.font_size = font_size

    def render_frame(self, canvas: Image.Image, t_rel: float, niche: str = "ai_tech") -> None:
        if t_rel < self.start_time or t_rel > (self.start_time + self.duration):
            return

        progress = (t_rel - self.start_time) / self.duration
        palette = BRAND_PALETTES.get(niche, BRAND_PALETTES["ai_tech"])

        # Spring scale for first 0.35s
        scale_t = min(1.0, (t_rel - self.start_time) / 0.35)
        scale = spring_overshoot(scale_t, overshoot=1.14)

        # Fade out in last 0.25s
        fade_alpha = 1.0
        if progress > 0.8:
            fade_alpha = max(0.0, 1.0 - (progress - 0.8) / 0.2)

        # Underline wipe progress [0.0 -> 1.0] across 0.4s
        underline_t = min(1.0, max(0.0, (t_rel - self.start_time - 0.1) / 0.4))
        underline_pct = ease_out_cubic(underline_t)

        effective_font_size = max(12, int(self.font_size * scale))
        font = font_mgr.get_font(effective_font_size, bold=True)

        # Measure text
        dummy_draw = ImageDraw.Draw(canvas)
        bbox = dummy_draw.textbbox((0, 0), self.text, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]

        cx, cy = self.center_pos
        x = cx - w // 2
        y = cy - h // 2

        # Draw drop shadow
        alpha_int = int(255 * fade_alpha)
        shadow_color = (0, 0, 0, int(180 * fade_alpha))
        dummy_draw.text((x + 4, y + 4), self.text, font=font, fill=shadow_color)

        # Draw text
        text_color = (*palette.text_light, alpha_int)
        dummy_draw.text((x, y), self.text, font=font, fill=text_color)

        # Draw glowing underline wipe
        if underline_pct > 0.0:
            line_y = y + h + 16
            line_width = int((w + 40) * underline_pct)
            line_x1 = cx - (w + 40) // 2
            line_x2 = line_x1 + line_width
            line_color = (*palette.primary, alpha_int)
            dummy_draw.line([(line_x1, line_y), (line_x2, line_y)], fill=line_color, width=10)


class AnimatedCounter(MotionComponent):
    """Counts up from 0 to target value with unit formatting and source badge."""

    def __init__(
        self,
        target_value: float,
        unit: str,
        label: str,
        source: str,
        start_time: float,
        duration: float = 2.0,
        center_pos: Tuple[int, int] = (540, 780),
    ):
        self.target_value = target_value
        self.unit = unit
        self.label = label.upper()
        self.source = source
        self.start_time = start_time
        self.duration = duration
        self.center_pos = center_pos

    def render_frame(self, canvas: Image.Image, t_rel: float, niche: str = "ai_tech") -> None:
        if t_rel < self.start_time or t_rel > (self.start_time + self.duration):
            return

        progress = (t_rel - self.start_time) / self.duration
        palette = BRAND_PALETTES.get(niche, BRAND_PALETTES["ai_tech"])

        # Count up during first 0.6s
        count_t = min(1.0, (t_rel - self.start_time) / 0.6)
        current_val = self.target_value * ease_out_cubic(count_t)

        fade_alpha = 1.0
        if progress > 0.85:
            fade_alpha = max(0.0, 1.0 - (progress - 0.85) / 0.15)
        alpha_int = int(255 * fade_alpha)

        # Format number nicely
        if current_val >= 1e9:
            display_num = f"{current_val / 1e9:.1f}B"
        elif current_val >= 1e6:
            display_num = f"{current_val / 1e6:.1f}M"
        elif current_val >= 1000:
            display_num = f"{current_val / 1000:.1f}K"
        elif current_val.is_integer():
            display_num = f"{int(current_val)}"
        else:
            display_num = f"{current_val:.1f}"

        display_text = f"{display_num} {self.unit}".strip()

        num_font = font_mgr.get_font(96, bold=True)
        lbl_font = font_mgr.get_font(34, bold=False)
        src_font = font_mgr.get_font(26, bold=False)

        draw = ImageDraw.Draw(canvas)
        cx, cy = self.center_pos

        # Measure
        n_bbox = draw.textbbox((0, 0), display_text, font=num_font)
        nw = n_bbox[2] - n_bbox[0]

        # Container Pill Box
        pad_x = 44
        box_w = max(nw + pad_x * 2, 540)
        box_h = 240
        x1 = cx - box_w // 2
        y1 = cy - box_h // 2
        x2 = cx + box_w // 2
        y2 = cy + box_h // 2

        # Draw dark translucent glass card
        card_bg = (15, 23, 42, int(220 * fade_alpha))
        draw.rounded_rectangle([x1, y1, x2, y2], radius=24, fill=card_bg, outline=(*palette.primary, int(150 * fade_alpha)), width=4)

        # Label
        l_bbox = draw.textbbox((0, 0), self.label, font=lbl_font)
        draw.text((cx - (l_bbox[2] - l_bbox[0]) // 2, y1 + 24), self.label, font=lbl_font, fill=(*palette.accent, alpha_int))

        # Main Number
        draw.text((cx - nw // 2, y1 + 72), display_text, font=num_font, fill=(*palette.primary, alpha_int))

        # Source Badge
        if self.source:
            src_text = f"Verified: {self.source}"
            s_bbox = draw.textbbox((0, 0), src_text, font=src_font)
            draw.text((cx - (s_bbox[2] - s_bbox[0]) // 2, y1 + 185), src_text, font=src_font, fill=(148, 163, 184, alpha_int))


class ComparisonVisual(MotionComponent):
    """Dual horizontal comparison bars for scale and ratio facts."""

    def __init__(
        self,
        label_a: str,
        val_a: float,
        label_b: str,
        val_b: float,
        unit: str,
        start_time: float,
        duration: float = 2.4,
        center_pos: Tuple[int, int] = (540, 800),
    ):
        self.label_a = label_a
        self.val_a = val_a
        self.label_b = label_b
        self.val_b = val_b
        self.unit = unit
        self.start_time = start_time
        self.duration = duration
        self.center_pos = center_pos

    def render_frame(self, canvas: Image.Image, t_rel: float, niche: str = "ai_tech") -> None:
        if t_rel < self.start_time or t_rel > (self.start_time + self.duration):
            return

        progress = (t_rel - self.start_time) / self.duration
        palette = BRAND_PALETTES.get(niche, BRAND_PALETTES["ai_tech"])

        fill_t = min(1.0, (t_rel - self.start_time) / 0.7)
        fill_eased = ease_out_cubic(fill_t)

        fade_alpha = 1.0 if progress <= 0.85 else max(0.0, (1.0 - progress) / 0.15)
        alpha_int = int(255 * fade_alpha)

        cx, cy = self.center_pos
        w = 840
        h = 280
        x1, y1 = cx - w // 2, cy - h // 2
        x2, y2 = cx + w // 2, cy + h // 2

        draw = ImageDraw.Draw(canvas)
        draw.rounded_rectangle([x1, y1, x2, y2], radius=24, fill=(15, 23, 42, int(220 * fade_alpha)), outline=(*palette.primary, int(140 * fade_alpha)), width=4)

        max_val = max(self.val_a, self.val_b, 1.0)
        pct_a = (self.val_a / max_val) * fill_eased
        pct_b = (self.val_b / max_val) * fill_eased

        font_lbl = font_mgr.get_font(32, bold=True)
        bar_max_w = w - 120

        # Bar A
        draw.text((x1 + 40, y1 + 30), f"{self.label_a}: {self.val_a:.0f}{self.unit}", font=font_lbl, fill=(*palette.primary, alpha_int))
        draw.rounded_rectangle([x1 + 40, y1 + 75, x1 + 40 + bar_max_w, y1 + 105], radius=10, fill=(30, 41, 59, alpha_int))
        draw.rounded_rectangle([x1 + 40, y1 + 75, x1 + 40 + int(bar_max_w * pct_a), y1 + 105], radius=10, fill=(*palette.primary, alpha_int))

        # Bar B
        draw.text((x1 + 40, y1 + 145), f"{self.label_b}: {self.val_b:.0f}{self.unit}", font=font_lbl, fill=(*palette.accent, alpha_int))
        draw.rounded_rectangle([x1 + 40, y1 + 190, x1 + 40 + bar_max_w, y1 + 220], radius=10, fill=(30, 41, 59, alpha_int))
        draw.rounded_rectangle([x1 + 40, y1 + 190, x1 + 40 + int(bar_max_w * pct_b), y1 + 220], radius=10, fill=(*palette.accent, alpha_int))


class LowerThirdSourceTag(MotionComponent):
    """Subtle verified source pill at lower-left safe area."""

    def __init__(self, source_text: str, start_time: float, duration: float = 3.0):
        self.source_text = source_text
        self.start_time = start_time
        self.duration = duration

    def render_frame(self, canvas: Image.Image, t_rel: float, niche: str = "ai_tech") -> None:
        if t_rel < self.start_time or t_rel > (self.start_time + self.duration):
            return

        progress = (t_rel - self.start_time) / self.duration
        fade = 1.0 if progress < 0.85 else max(0.0, (1.0 - progress) / 0.15)
        alpha = int(255 * fade)

        draw = ImageDraw.Draw(canvas)
        font = font_mgr.get_font(26, bold=False)

        text = f"Source: {self.source_text}"
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]

        x1, y1 = 80, 1570
        x2, y2 = x1 + tw + 36, y1 + 48

        draw.rounded_rectangle([x1, y1, x2, y2], radius=14, fill=(15, 23, 42, int(210 * fade)), outline=(56, 189, 248, int(140 * fade)), width=2)
        draw.text((x1 + 18, y1 + 10), text, font=font, fill=(226, 232, 240, alpha))


class ProgressBar(MotionComponent):
    """Thin 6px subtle brand-colored video progress bar at the very bottom."""

    def __init__(self, total_duration: float):
        self.total_duration = max(1.0, total_duration)

    def render_frame(self, canvas: Image.Image, t_rel: float, niche: str = "ai_tech") -> None:
        pct = max(0.0, min(1.0, t_rel / self.total_duration))
        palette = BRAND_PALETTES.get(niche, BRAND_PALETTES["ai_tech"])

        draw = ImageDraw.Draw(canvas)
        y = 1912
        bar_w = int(1080 * pct)

        # Background track
        draw.line([(0, y), (1080, y)], fill=(30, 41, 59, 150), width=6)
        # Active progress
        if bar_w > 0:
            draw.line([(0, y), (bar_w, y)], fill=(*palette.primary, 240), width=6)


class FirstFrameHookCard(MotionComponent):
    """Dramatic hook card displayed across frame 0 to 0.4s to guarantee strong immediate hook visuals."""

    def __init__(self, hook_text: str, duration: float = 0.6):
        self.hook_text = hook_text.upper()
        self.duration = duration

    def render_frame(self, canvas: Image.Image, t_rel: float, niche: str = "ai_tech") -> None:
        if t_rel > self.duration:
            return

        progress = t_rel / self.duration
        fade = 1.0 if progress < 0.6 else max(0.0, (1.0 - progress) / 0.4)
        alpha = int(255 * fade)

        draw = ImageDraw.Draw(canvas)
        font = font_mgr.get_font(68, bold=True)
        palette = BRAND_PALETTES.get(niche, BRAND_PALETTES["ai_tech"])

        # Word wrap hook text into 2-3 lines
        words = self.hook_text.split()
        lines = []
        curr = []
        for w in words:
            curr.append(w)
            if len(" ".join(curr)) > 18:
                lines.append(" ".join(curr))
                curr = []
        if curr:
            lines.append(" ".join(curr))

        cy = 550
        line_h = 84
        start_y = cy - (len(lines) * line_h) // 2

        # Draw subtle backdrop panel
        draw.rectangle([0, start_y - 40, 1080, start_y + len(lines) * line_h + 40], fill=(11, 15, 25, int(180 * fade)))

        for i, line in enumerate(lines):
            bbox = draw.textbbox((0, 0), line, font=font)
            lw = bbox[2] - bbox[0]
            lx = (1080 - lw) // 2
            ly = start_y + i * line_h
            # Drop shadow
            draw.text((lx + 4, ly + 4), line, font=font, fill=(0, 0, 0, int(200 * fade)))
            # Text
            draw.text((lx, ly), line, font=font, fill=(*palette.accent, alpha))


class InfographicCard(MotionComponent):
    """Modern glassmorphic infographic badge with key stat, title, and verified icon."""

    def __init__(
        self,
        title: str,
        stat_value: str,
        subtitle: str = "",
        start_time: float = 0.0,
        duration: float = 2.4,
        y_pos: int = 420,
    ):
        self.title = title.upper()
        self.stat_value = stat_value
        self.subtitle = subtitle
        self.start_time = start_time
        self.duration = duration
        self.y_pos = y_pos

    def render_frame(self, canvas: Image.Image, t_rel: float, niche: str = "ai_tech") -> None:
        if t_rel < self.start_time or t_rel > (self.start_time + self.duration):
            return

        progress = (t_rel - self.start_time) / self.duration
        fade = 1.0 if progress < 0.8 else max(0.0, 1.0 - (progress - 0.8) / 0.2)
        alpha = int(255 * fade)

        palette = BRAND_PALETTES.get(niche, BRAND_PALETTES["ai_tech"])
        draw = ImageDraw.Draw(canvas)

        card_w, card_h = 880, 240
        x1 = (1080 - card_w) // 2
        y1 = self.y_pos
        x2 = x1 + card_w
        y2 = y1 + card_h

        # Draw glassmorphic background
        draw.rounded_rectangle([x1, y1, x2, y2], radius=24, fill=(15, 23, 42, int(210 * fade)))
        draw.rounded_rectangle([x1, y1, x2, y2], radius=24, outline=(*palette.primary, int(180 * fade)), width=3)

        # Title
        f_title = font_mgr.get_font(28, bold=True)
        draw.text((x1 + 40, y1 + 32), self.title, font=f_title, fill=(*palette.primary, alpha))

        # Big Stat Value
        f_val = font_mgr.get_font(68, bold=True)
        draw.text((x1 + 40, y1 + 76), self.stat_value, font=f_val, fill=(255, 255, 255, alpha))

        # Subtitle
        if self.subtitle:
            f_sub = font_mgr.get_font(26, bold=False)
            draw.text((x1 + 40, y1 + 164), self.subtitle, font=f_sub, fill=(148, 163, 184, alpha))


class LocationMarker(MotionComponent):
    """Expanding radar pulse and location pin for geographic & astronomical events."""

    def __init__(
        self,
        location_name: str,
        start_time: float = 0.0,
        duration: float = 2.2,
        center_pos: tuple[int, int] = (540, 520),
    ):
        self.location_name = location_name.upper()
        self.start_time = start_time
        self.duration = duration
        self.center_pos = center_pos

    def render_frame(self, canvas: Image.Image, t_rel: float, niche: str = "ai_tech") -> None:
        if t_rel < self.start_time or t_rel > (self.start_time + self.duration):
            return

        progress = (t_rel - self.start_time) / self.duration
        fade = 1.0 if progress < 0.8 else max(0.0, 1.0 - (progress - 0.8) / 0.2)
        alpha = int(255 * fade)

        cx, cy = self.center_pos
        palette = BRAND_PALETTES.get(niche, BRAND_PALETTES["ai_tech"])
        draw = ImageDraw.Draw(canvas)

        # Expanding radar pulse
        pulse_r = int(20 + 70 * (progress % 0.5) / 0.5)
        pulse_alpha = int(max(0, 180 * (1.0 - (progress % 0.5) / 0.5)) * fade)
        draw.ellipse([cx - pulse_r, cy - pulse_r, cx + pulse_r, cy + pulse_r], outline=(*palette.accent, pulse_alpha), width=3)

        # Center core dot
        draw.ellipse([cx - 12, cy - 12, cx + 12, cy + 12], fill=(*palette.accent, alpha))

        # Location name badge
        f_name = font_mgr.get_font(32, bold=True)
        bbox = draw.textbbox((0, 0), self.location_name, font=f_name)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]

        bx1 = cx - tw // 2 - 20
        by1 = cy + 32
        bx2 = cx + tw // 2 + 20
        by2 = by1 + th + 18

        draw.rounded_rectangle([bx1, by1, bx2, by2], radius=12, fill=(11, 15, 25, int(220 * fade)))
        draw.rounded_rectangle([bx1, by1, bx2, by2], radius=12, outline=(*palette.primary, int(150 * fade)), width=2)
        draw.text((cx - tw // 2, by1 + 8), self.location_name, font=f_name, fill=(255, 255, 255, alpha))

