"""Next-Generation Advanced Motion Graphics Components for Nova Autopilot v9.2.

Provides reusable, narrative-driven animated compositions:
- ScientificOrbitDiagram: Multi-body orbital mechanics with spacetime curvature ripples.
- FinancialGrowthChart: Dynamic neon trend curve with glowing marker and percentage HUD.
- GeoMapRadarMarker: Pulsing radar sweep, coordinate HUD, and geographic beacon.
- EvidenceInspectionLoupe: Forensic focal magnifier with targeting reticle and evidence bracket.
- DynamicSplitScreen: Animated comparison divider with dual thematic badges.
"""

from __future__ import annotations

import math
from typing import Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from nova.motion.brand import BRAND_PALETTES, FontManager
from nova.motion.components import MotionComponent
from nova.motion.easing import ease_out_cubic, ease_out_expo, lerp, spring_overshoot

font_mgr = FontManager()


class ScientificOrbitDiagram(MotionComponent):
    """Orbital mechanics visualizer with gravitational spacetime ripples and orbiting particles."""

    def __init__(
        self,
        center_title: str = "BLACK HOLE",
        orbiting_label: str = "ORBITAL JET",
        start_time: float = 0.0,
        duration: float = 3.0,
        center_pos: Tuple[int, int] = (540, 800),
    ):
        self.center_title = center_title
        self.orbiting_label = orbiting_label
        self.start_time = start_time
        self.duration = duration
        self.center_pos = center_pos

    def render_frame(self, canvas: Image.Image, t_rel: float, niche: str = "space_science") -> None:
        if t_rel < self.start_time or t_rel > (self.start_time + self.duration):
            return

        prog = (t_rel - self.start_time) / self.duration
        cx, cy = self.center_pos
        draw = ImageDraw.Draw(canvas, "RGBA")

        # Entrance scale
        in_t = min(1.0, (t_rel - self.start_time) / 0.4)
        scale = spring_overshoot(in_t, overshoot=1.1)

        # Spacetime gravitational ripples (expanding concentric circles)
        ripple_radius = (int((prog * 360) % 240) + 60) * scale
        draw.ellipse(
            [cx - ripple_radius, cy - ripple_radius * 0.45, cx + ripple_radius, cy + ripple_radius * 0.45],
            outline=(56, 189, 248, int(max(0, 180 * (1.0 - ripple_radius / 300)))),
            width=2,
        )

        # Elliptical Orbit Track
        rx, ry = int(280 * scale), int(120 * scale)
        draw.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], outline=(148, 163, 184, 80), width=2)

        # Central Gravitational Core
        core_r = int(48 * scale)
        # Corona glow
        for r_glow, alpha in [(core_r + 20, 40), (core_r + 10, 80), (core_r, 220)]:
            draw.ellipse(
                [cx - r_glow, cy - r_glow, cx + r_glow, cy + r_glow],
                fill=(245, 158, 11, alpha),
            )
        draw.ellipse([cx - core_r // 2, cy - core_r // 2, cx + core_r // 2, cy + core_r // 2], fill=(15, 23, 42, 255))

        # Orbiting Body position (elliptical angle based on time)
        angle = (t_rel - self.start_time) * 3.2  # rad/s
        ox = int(cx + rx * math.cos(angle))
        oy = int(cy + ry * math.sin(angle))

        # Orbiting particle & trail
        p_r = int(14 * scale)
        draw.ellipse([ox - p_r, oy - p_r, ox + p_r, oy + p_r], fill=(56, 189, 248, 255))
        # Halo
        draw.ellipse([ox - p_r - 6, oy - p_r - 6, ox + p_r + 6, oy + p_r + 6], outline=(255, 255, 255, 180), width=2)

        # HUD Labels
        font_main = font_mgr.get_font(26, bold=True)
        draw.text((cx - 80, cy + 90), self.center_title, font=font_main, fill=(255, 255, 255, 230))
        font_sub = font_mgr.get_font(20, bold=False)
        draw.text((ox + 18, oy - 10), self.orbiting_label, font=font_sub, fill=(56, 189, 248, 220))


class FinancialGrowthChart(MotionComponent):
    """Animated neon trend curve with glowing marker, grid lines, and percentage badge."""

    def __init__(
        self,
        headline: str = "GLOBAL COMPUTE CAPACITY",
        final_value: str = "+340% SURGE",
        start_time: float = 0.0,
        duration: float = 3.0,
        box: Tuple[int, int, int, int] = (140, 600, 940, 1050),
    ):
        self.headline = headline
        self.final_value = final_value
        self.start_time = start_time
        self.duration = duration
        self.box = box

    def render_frame(self, canvas: Image.Image, t_rel: float, niche: str = "business") -> None:
        if t_rel < self.start_time or t_rel > (self.start_time + self.duration):
            return

        prog = (t_rel - self.start_time) / self.duration
        draw = ImageDraw.Draw(canvas, "RGBA")
        x1, y1, x2, y2 = self.box
        w = x2 - x1
        h = y2 - y1

        # Background frosted card
        draw.rounded_rectangle([x1, y1, x2, y2], radius=24, fill=(15, 23, 42, 210), outline=(51, 65, 85, 180), width=2)

        # Header Title
        font_head = font_mgr.get_font(24, bold=True)
        draw.text((x1 + 32, y1 + 28), self.headline.upper(), font=font_head, fill=(148, 163, 184, 220))

        # Horizontal Gridlines
        for i in range(1, 4):
            gy = y1 + 80 + int((h - 120) * (i / 4.0))
            draw.line([(x1 + 32, gy), (x2 - 32, gy)], fill=(51, 65, 85, 90), width=1)

        # Draw animated curve points up to current progress
        num_pts = 40
        active_pts = max(2, int(num_pts * min(1.0, prog * 1.3)))
        curve_pts = []
        for i in range(active_pts):
            pt_prog = i / float(num_pts - 1)
            px = x1 + 40 + int((w - 80) * pt_prog)
            # Exponential growth curve with subtle noise
            val = math.pow(pt_prog, 1.8) * 0.85 + math.sin(pt_prog * 8.0) * 0.04
            py = y2 - 40 - int((h - 140) * val)
            curve_pts.append((px, py))

        if len(curve_pts) > 1:
            draw.line(curve_pts, fill=(16, 185, 129, 255), width=5)
            # Glowing Lead Point
            lx, ly = curve_pts[-1]
            draw.ellipse([lx - 10, ly - 10, lx + 10, ly + 10], fill=(52, 211, 153, 255))
            draw.ellipse([lx - 18, ly - 18, lx + 18, ly + 18], outline=(16, 185, 129, 140), width=3)

            # Value Badge
            if prog > 0.3:
                font_val = font_mgr.get_font(28, bold=True)
                draw.rounded_rectangle([lx - 90, ly - 56, lx + 90, ly - 16], radius=12, fill=(16, 185, 129, 240))
                draw.text((lx - 75, ly - 52), self.final_value, font=font_val, fill=(255, 255, 255, 255))


class GeoMapRadarMarker(MotionComponent):
    """Pulsing tactical radar locator with coordinate readout and geographic target reticle."""

    def __init__(
        self,
        location_name: str = "MAUNA KEA OBSERVATORY",
        coordinates: str = "19.8206° N, 155.4681° W",
        start_time: float = 0.0,
        duration: float = 2.8,
        center_pos: Tuple[int, int] = (540, 850),
    ):
        self.location_name = location_name
        self.coordinates = coordinates
        self.start_time = start_time
        self.duration = duration
        self.center_pos = center_pos

    def render_frame(self, canvas: Image.Image, t_rel: float, niche: str = "space_science") -> None:
        if t_rel < self.start_time or t_rel > (self.start_time + self.duration):
            return

        prog = (t_rel - self.start_time) / self.duration
        cx, cy = self.center_pos
        draw = ImageDraw.Draw(canvas, "RGBA")

        # Rotating Radar Sweep
        angle = (t_rel - self.start_time) * 4.0  # rad/s
        sweep_r = 160
        sx = int(cx + sweep_r * math.cos(angle))
        sy = int(cy + sweep_r * math.sin(angle))
        draw.line([(cx, cy), (sx, sy)], fill=(56, 189, 248, 160), width=3)

        # Concentric Radar Rings
        for r_rad in [60, 110, 160]:
            draw.ellipse([cx - r_rad, cy - r_rad, cx + r_rad, cy + r_rad], outline=(56, 189, 248, 80), width=1)

        # Pulsing Beacon Center
        pulse = (math.sin(t_rel * 8.0) + 1.0) * 0.5
        pr = int(12 + pulse * 6)
        draw.ellipse([cx - pr, cy - pr, cx + pr, cy + pr], fill=(239, 68, 68, 255))
        draw.ellipse([cx - pr - 8, cy - pr - 8, cx + pr + 8, cy + pr + 8], outline=(239, 68, 68, 140), width=2)

        # Target Reticle Brackets
        ret_len = 24
        d = 40
        draw.line([(cx - d, cy - d), (cx - d + ret_len, cy - d)], fill=(255, 255, 255, 200), width=2)
        draw.line([(cx - d, cy - d), (cx - d, cy - d + ret_len)], fill=(255, 255, 255, 200), width=2)
        draw.line([(cx + d, cy + d), (cx + d - ret_len, cy + d)], fill=(255, 255, 255, 200), width=2)
        draw.line([(cx + d, cy + d), (cx + d, cy + d - ret_len)], fill=(255, 255, 255, 200), width=2)

        # Location Info Pill
        font_loc = font_mgr.get_font(26, bold=True)
        font_coord = font_mgr.get_font(18, bold=False)
        pill_w, pill_h = 420, 72
        px = cx - pill_w // 2
        py = cy + 190
        draw.rounded_rectangle([px, py, px + pill_w, py + pill_h], radius=16, fill=(15, 23, 42, 220), outline=(56, 189, 248, 180), width=2)
        draw.text((px + 24, py + 12), self.location_name, font=font_loc, fill=(248, 250, 252, 240))
        draw.text((px + 24, py + 42), self.coordinates, font=font_coord, fill=(148, 163, 184, 200))


class DynamicSplitScreen(MotionComponent):
    """Vertical comparison divider with dual thematic labels and animated divider line."""

    def __init__(
        self,
        left_label: str = "THEORY",
        right_label: str = "VERIFIED REALITY",
        start_time: float = 0.0,
        duration: float = 2.5,
    ):
        self.left_label = left_label
        self.right_label = right_label
        self.start_time = start_time
        self.duration = duration

    def render_frame(self, canvas: Image.Image, t_rel: float, niche: str = "ai_tech") -> None:
        if t_rel < self.start_time or t_rel > (self.start_time + self.duration):
            return

        prog = (t_rel - self.start_time) / self.duration
        draw = ImageDraw.Draw(canvas, "RGBA")
        cx = 540  # Center vertical divider

        # Animated divider reveal
        div_h = int(1920 * min(1.0, prog * 2.0))
        draw.line([(cx, 0), (cx, div_h)], fill=(255, 255, 255, 200), width=4)
        draw.line([(cx - 2, 0), (cx - 2, div_h)], fill=(56, 189, 248, 120), width=1)
        draw.line([(cx + 2, 0), (cx + 2, div_h)], fill=(56, 189, 248, 120), width=1)

        # Badges
        if prog > 0.2:
            font = font_mgr.get_font(24, bold=True)
            # Left Badge
            draw.rounded_rectangle([80, 500, 460, 560], radius=12, fill=(15, 23, 42, 210), outline=(239, 68, 68, 180), width=2)
            draw.text((110, 516), self.left_label, font=font, fill=(248, 113, 113, 240))

            # Right Badge
            draw.rounded_rectangle([620, 500, 1000, 560], radius=12, fill=(15, 23, 42, 210), outline=(16, 185, 129, 180), width=2)
            draw.text((640, 516), self.right_label, font=font, fill=(52, 211, 153, 240))
