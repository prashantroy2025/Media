"""Professional Motion Design Studio for NOVA AUTOPILOT (v9.4).

Provides 10 reusable, narrative-driven animated procedural compositions:
1. Isometric3DBarChartComposition: 3D-perspective statistical bar visualizer with depth extrusion facets.
2. FinancialTrendChartComposition: Cinematic financial / compute growth chart with glowing gradient area fill.
3. GeographicMapRouteComposition: Tactical map radar locator with geodesic trajectory arc and telemetry HUD.
4. HistoricalTimelineComposition: Chronological milestone timeline with glowing axis, dates, and frosted cards.
5. ScientificSchematicComposition: Quantum / atomic / orbital scientific diagram with electron shells and core flares.
6. ForensicInspectionLoupeComposition: High-tech focal magnifier with targeting reticle and evidence bracket.
7. SplitScreenComparisonComposition: Dynamic dual-realm comparison with animated seam reveal and differential bar.
8. KineticTypographyComposition: Staggered kinetic typography with mask reveals and spring overshoot.
9. CyberneticInterfaceComposition: Holographic telemetry terminal HUD with live hex stream and spectrum analyzer.
10. DeepSpaceStarfieldComposition: Re-exported from compositions module for unified registry access.

All compositions inherit BaseComposition, conform to 1080x1920 30fps vertical video, enforce platform
safe zones, eliminate dead black voids, and dynamically format text via TypographyLayoutEngine.
"""

from __future__ import annotations

import math
import os
from pathlib import Path
import random
import subprocess
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from nova.motion.brand import BRAND_PALETTES, FontManager, NichePalette
from nova.motion.easing import ease_out_cubic, ease_out_expo, lerp, spring_overshoot
from nova.timeline.compositions import BaseComposition, DeepSpaceStarfieldComposition
from nova.typography.engine import TypographyLayoutEngine

font_mgr = FontManager()


def _draw_ambient_backdrop(
    canvas: Image.Image,
    top_color: Tuple[int, int, int] = (26, 38, 68),
    bottom_color: Tuple[int, int, int] = (20, 26, 48),
    spotlight: Optional[Tuple[int, int, int, Tuple[int, int, int, int]]] = None,
) -> None:
    """Fills canvas with an atmospheric vertical gradient and optional soft luminous spotlight."""
    w, h = canvas.size
    # Vertical gradient via linear interpolation
    y_coords = np.linspace(0, 1, h)[:, None]
    top_arr = np.array(top_color, dtype=np.float32)
    bottom_arr = np.array(bottom_color, dtype=np.float32)
    gradient = (top_arr * (1.0 - y_coords) + bottom_arr * y_coords).astype(np.uint8)
    # Broadcast across width
    grad_img = Image.fromarray(np.repeat(gradient[:, np.newaxis, :], w, axis=1), mode="RGB")
    canvas.paste(grad_img, (0, 0))

    if spotlight:
        sx, sy, sr, scol = spotlight
        draw = ImageDraw.Draw(canvas, "RGBA")
        for step in range(sr, 0, -30):
            alpha = int(scol[3] * (step / sr))
            draw.ellipse(
                [sx - step, sy - step, sx + step, sy + step],
                fill=(scol[0], scol[1], scol[2], alpha),
            )


# ==============================================================================
# 1. Isometric 3D Bar Chart Composition
# ==============================================================================

class Isometric3DBarChartComposition(BaseComposition):
    """3D-perspective statistical bar visualizer with extruded facets and metric count-ups."""

    def __init__(
        self,
        width: int = 1080,
        height: int = 1920,
        fps: int = 30,
        title: str = "GLOBAL COMPUTE CAPACITY",
        categories: Optional[List[str]] = None,
        values: Optional[List[float]] = None,
        unit: str = "%",
        niche: str = "ai_tech",
    ):
        super().__init__(width, height, fps)
        self.title = title
        self.categories = categories or ["2022", "2024", "2026 (EST)"]
        self.values = values or [100.0, 340.0, 850.0]
        self.unit = unit
        self.palette = BRAND_PALETTES.get(niche, BRAND_PALETTES["ai_tech"])
        self._init_particles()

    def _init_particles(self) -> None:
        rng = random.Random(101)
        self.particles = [
            {
                "x": rng.uniform(80, self.width - 80),
                "y": rng.uniform(200, 1200),
                "speed_y": rng.uniform(-0.6, -0.2),
                "radius": rng.uniform(1.5, 3.5),
                "alpha": rng.uniform(60, 160),
            }
            for _ in range(40)
        ]

    def render_frame(self, canvas: Image.Image, frame_idx: int, total_frames: int, time_sec: float) -> None:
        _draw_ambient_backdrop(
            canvas,
            top_color=(28, 42, 75),
            bottom_color=(20, 28, 52),
            spotlight=(540, 700, 520, (30, 75, 140, 95)),
        )
        draw = ImageDraw.Draw(canvas, "RGBA")
        t_norm = min(1.0, time_sec / max(0.1, (total_frames / self.fps) * 0.75))

        # Title Card with Safe Margin Check
        font_title = font_mgr.get_font(34, bold=True)
        wrapped_title = TypographyLayoutEngine.wrap_text_smart(self.title.upper(), font_title, 880)
        ty = 280
        for line in wrapped_title[:2]:
            draw.text((100, ty), line, font=font_title, fill=(240, 245, 255, 230))
            ty += 42

        # Subtitle badge
        font_badge = font_mgr.get_font(18, bold=True)
        draw.rounded_rectangle([100, ty + 10, 360, ty + 46], radius=8, fill=(30, 41, 59, 210), outline=(56, 189, 248, 160), width=1)
        draw.text((118, ty + 18), "VERIFIED STATISTICAL METRIC", font=font_badge, fill=(56, 189, 248, 220))

        # 3D Grid Floor lines
        floor_y = 1050
        for gy in range(floor_y, floor_y + 120, 30):
            draw.line([(120, gy), (960, gy)], fill=(51, 65, 85, 80), width=1)

        # Draw 3D Isometric Extruded Pillars
        n_bars = len(self.values)
        max_val = max(self.values) if self.values else 100.0
        bar_w = int(680 / (n_bars * 1.8))
        gap = int((740 - (n_bars * bar_w)) / max(1, n_bars - 1))
        iso_dx = 28  # 3D isometric horizontal slant
        iso_dy = 18  # 3D isometric vertical slant

        colors = [
            ((56, 189, 248), (14, 165, 233)),  # Cyan
            ((129, 140, 248), (99, 102, 241)), # Indigo
            ((52, 211, 153), (16, 185, 129)),  # Emerald
        ]

        for i, (val, cat) in enumerate(zip(self.values, self.categories)):
            delay = i * 0.15
            bar_t = max(0.0, min(1.0, (time_sec - delay) / 0.8))
            eased_h = spring_overshoot(bar_t, overshoot=1.08)
            norm_val = val / max_val
            bar_h = int(norm_val * 420 * eased_h)

            bx = 180 + i * (bar_w + gap)
            by = floor_y - bar_h

            main_col, dark_col = colors[i % len(colors)]

            # Pillar Front Facet
            draw.rectangle(
                [bx, by, bx + bar_w, floor_y],
                fill=(main_col[0], main_col[1], main_col[2], 220),
                outline=(255, 255, 255, 140),
                width=1,
            )

            # Pillar Right Side Facet (Shadowed 3D Extrusion)
            right_poly = [
                (bx + bar_w, by),
                (bx + bar_w + iso_dx, by - iso_dy),
                (bx + bar_w + iso_dx, floor_y - iso_dy),
                (bx + bar_w, floor_y),
            ]
            draw.polygon(right_poly, fill=(dark_col[0] // 2, dark_col[1] // 2, dark_col[2] // 2, 240), outline=(255, 255, 255, 80))

            # Pillar Top Diamond Facet
            top_poly = [
                (bx, by),
                (bx + iso_dx, by - iso_dy),
                (bx + bar_w + iso_dx, by - iso_dy),
                (bx + bar_w, by),
            ]
            draw.polygon(top_poly, fill=(255, 255, 255, 210))

            # Count-up Value readout above pillar
            cur_num = val * min(1.0, eased_h)
            num_str = f"+{int(cur_num)}{self.unit}" if self.unit == "%" else f"{cur_num:.1f}{self.unit}"
            font_num = font_mgr.get_font(26, bold=True)
            draw.text((bx - 8, by - iso_dy - 40), num_str, font=font_num, fill=(255, 255, 255, 245))

            # Category Label below floor
            font_cat = font_mgr.get_font(20, bold=False)
            draw.text((bx + 4, floor_y + 16), cat, font=font_cat, fill=(148, 163, 184, 220))

        # Floating ambient dust
        for p in self.particles:
            py = int((p["y"] + time_sec * p["speed_y"] * 60) % 1000 + 200)
            draw.ellipse([p["x"] - p["radius"], py - p["radius"], p["x"] + p["radius"], py + p["radius"]], fill=(180, 220, 255, int(p["alpha"])))


# ==============================================================================
# 2. Financial Trend Chart Composition
# ==============================================================================

class FinancialTrendChartComposition(BaseComposition):
    """Cinematic financial/market curve with glowing area gradient, leading beacon, and delta HUD."""

    def __init__(
        self,
        width: int = 1080,
        height: int = 1920,
        fps: int = 30,
        metric_title: str = "GLOBAL ADOPTION CURVE",
        delta_label: str = "+340% SURGE",
        data_points: Optional[List[float]] = None,
        niche: str = "business",
    ):
        super().__init__(width, height, fps)
        self.metric_title = metric_title
        self.delta_label = delta_label
        self.data_points = data_points or [12.0, 18.0, 16.0, 28.0, 42.0, 39.0, 68.0, 94.0, 142.0]
        self.palette = BRAND_PALETTES.get(niche, BRAND_PALETTES["business"])

    def render_frame(self, canvas: Image.Image, frame_idx: int, total_frames: int, time_sec: float) -> None:
        _draw_ambient_backdrop(
            canvas,
            top_color=(22, 40, 60),
            bottom_color=(18, 28, 48),
            spotlight=(600, 650, 480, (16, 185, 129, 75)),
        )
        draw = ImageDraw.Draw(canvas, "RGBA")
        x1, y1, x2, y2 = 100, 340, 980, 1080
        w, h = x2 - x1, y2 - y1

        # Title Card
        font_title = font_mgr.get_font(32, bold=True)
        draw.text((x1 + 20, y1 + 10), self.metric_title.upper(), font=font_title, fill=(240, 245, 255, 235))

        # Horizontal Gridlines & Stamps
        stamps = ["$10K", "$50K", "$100K", "$250K"]
        for i, st in enumerate(reversed(stamps)):
            gy = y1 + 80 + int((h - 140) * (i / 3.0))
            draw.line([(x1 + 20, gy), (x2 - 20, gy)], fill=(51, 65, 85, 75), width=1)
            font_st = font_mgr.get_font(16, bold=False)
            draw.text((x1 + 24, gy - 20), st, font=font_st, fill=(100, 116, 139, 180))

        # Build smooth curve coordinates
        pts = self.data_points
        max_p = max(pts)
        min_p = min(pts)
        rng_p = max(1.0, max_p - min_p)

        curve_coords = []
        for i, val in enumerate(pts):
            cx = x1 + 40 + int((w - 80) * (i / (len(pts) - 1)))
            norm_v = (val - min_p) / rng_p
            cy = y2 - 40 - int((h - 160) * norm_v)
            curve_coords.append((cx, cy))

        # Progressive animation reveal
        prog = min(1.0, time_sec / max(0.1, (total_frames / self.fps) * 0.8))
        eased_prog = ease_out_cubic(prog)
        active_len = max(2, int(len(curve_coords) * eased_prog))
        visible_pts = curve_coords[:active_len]

        if len(visible_pts) > 1:
            # Translucent fill beneath curve
            poly = [(x1 + 40, y2 - 40)] + visible_pts + [(visible_pts[-1][0], y2 - 40)]
            draw.polygon(poly, fill=(16, 185, 129, 35))

            # Main Glowing Line
            draw.line(visible_pts, fill=(16, 185, 129, 255), width=6)
            draw.line(visible_pts, fill=(255, 255, 255, 180), width=2)

            # Leading Marker with Pulsing Halo
            lx, ly = visible_pts[-1]
            pulse = 1.0 + 0.25 * math.sin(time_sec * 8.0)
            draw.ellipse([lx - 12 * pulse, ly - 12 * pulse, lx + 12 * pulse, ly + 12 * pulse], fill=(52, 211, 153, 240))
            draw.ellipse([lx - 22 * pulse, ly - 22 * pulse, lx + 22 * pulse, ly + 22 * pulse], outline=(16, 185, 129, 140), width=2)

            # Delta Badge anchored to leading marker
            if prog > 0.25:
                font_badge = font_mgr.get_font(26, bold=True)
                bx = min(x2 - 280, max(x1 + 40, lx - 110))
                by = max(y1 + 80, ly - 70)
                draw.rounded_rectangle([bx, by, bx + 220, by + 52], radius=14, fill=(15, 23, 42, 240), outline=(16, 185, 129, 220), width=2)
                draw.text((bx + 18, by + 12), self.delta_label, font=font_badge, fill=(52, 211, 153, 255))


# ==============================================================================
# 3. Geographic Map Route Composition
# ==============================================================================

class GeographicMapRouteComposition(BaseComposition):
    """Tactical map radar locator with geodesic trajectory arc and telemetry HUD."""

    def __init__(
        self,
        width: int = 1080,
        height: int = 1920,
        fps: int = 30,
        origin_name: str = "GENEVA (CERN)",
        dest_name: str = "TOKYO (KEK)",
        telemetry: str = "TRANSIT: 9,820 KM // 12.4 MS",
        niche: str = "space_science",
    ):
        super().__init__(width, height, fps)
        self.origin_name = origin_name
        self.dest_name = dest_name
        self.telemetry = telemetry
        self.palette = BRAND_PALETTES.get(niche, BRAND_PALETTES["space_science"])

    def render_frame(self, canvas: Image.Image, frame_idx: int, total_frames: int, time_sec: float) -> None:
        _draw_ambient_backdrop(
            canvas,
            top_color=(24, 34, 62),
            bottom_color=(18, 25, 48),
            spotlight=(540, 750, 500, (56, 189, 248, 75)),
        )
        draw = ImageDraw.Draw(canvas, "RGBA")

        # Map Matrix Grid (tactical dot matrix)
        for gx in range(120, 960, 60):
            for gy in range(400, 1100, 60):
                draw.ellipse([gx - 1, gy - 1, gx + 1, gy + 1], fill=(51, 65, 85, 70))

        # Origin & Destination Coordinates
        ox, oy = 260, 820
        dx, dy = 820, 620

        # Radar Sweep on Origin
        sweep_angle = time_sec * 3.5
        sweep_r = 110
        sx = int(ox + sweep_r * math.cos(sweep_angle))
        sy = int(oy + sweep_r * math.sin(sweep_angle))
        draw.line([(ox, oy), (sx, sy)], fill=(56, 189, 248, 120), width=2)
        for r in [40, 80, 110]:
            draw.ellipse([ox - r, oy - r, ox + r, oy + r], outline=(56, 189, 248, 60), width=1)

        # Geodesic Parabolic Trajectory Arc
        prog = min(1.0, time_sec / max(0.1, (total_frames / self.fps) * 0.8))
        eased_p = ease_out_cubic(prog)
        num_arc_pts = 60
        active_pts = max(2, int(num_arc_pts * eased_p))
        arc = []
        for i in range(active_pts):
            t = i / (num_arc_pts - 1)
            # Quadratic bezier arc with elevation hump
            ax = (1 - t) * ox + t * dx
            ay = (1 - t) * oy + t * dy - math.sin(t * math.pi) * 220
            arc.append((int(ax), int(ay)))

        if len(arc) > 1:
            draw.line(arc, fill=(56, 189, 248, 220), width=4)
            # Trajectory particle trail
            head_x, head_y = arc[-1]
            draw.ellipse([head_x - 8, head_y - 8, head_x + 8, head_y + 8], fill=(255, 255, 255, 255))
            draw.ellipse([head_x - 16, head_y - 16, head_x + 16, head_y + 16], outline=(56, 189, 248, 180), width=2)

        # Origin Beacon & Label
        draw.ellipse([ox - 10, oy - 10, ox + 10, oy + 10], fill=(239, 68, 68, 255))
        font_loc = font_mgr.get_font(22, bold=True)
        draw.text((ox - 40, oy + 24), self.origin_name, font=font_loc, fill=(248, 250, 252, 230))

        # Destination Reticle & Label
        draw.ellipse([dx - 10, dy - 10, dx + 10, dy + 10], fill=(52, 211, 153, 255))
        draw.text((dx - 60, dy + 24), self.dest_name, font=font_loc, fill=(52, 211, 153, 240))

        # Bottom Telemetry HUD Box
        hud_box = [160, 1140, 920, 1220]
        draw.rounded_rectangle(hud_box, radius=16, fill=(15, 23, 42, 220), outline=(56, 189, 248, 180), width=2)
        font_telem = font_mgr.get_font(20, bold=True)
        draw.text((hud_box[0] + 32, hud_box[1] + 26), self.telemetry, font=font_telem, fill=(56, 189, 248, 230))


# ==============================================================================
# 4. Historical Timeline Composition
# ==============================================================================

class HistoricalTimelineComposition(BaseComposition):
    """Chronological milestone timeline with glowing axis, dates, and expanding cards."""

    def __init__(
        self,
        width: int = 1080,
        height: int = 1920,
        fps: int = 30,
        title: str = "CHRONOLOGY OF DISCOVERY",
        milestones: Optional[List[Tuple[str, str]]] = None,
        niche: str = "space_science",
    ):
        super().__init__(width, height, fps)
        self.title = title
        self.milestones = milestones or [
            ("1965", "CMBR DETECTED"),
            ("1998", "ACCELERATING EXPANSION"),
            ("2024", "JAMES WEBB DEEP FIELD"),
        ]
        self.palette = BRAND_PALETTES.get(niche, BRAND_PALETTES["space_science"])

    def render_frame(self, canvas: Image.Image, frame_idx: int, total_frames: int, time_sec: float) -> None:
        _draw_ambient_backdrop(
            canvas,
            top_color=(32, 28, 64),
            bottom_color=(22, 20, 48),
            spotlight=(340, 750, 480, (129, 140, 248, 80)),
        )
        draw = ImageDraw.Draw(canvas, "RGBA")

        # Header Title
        font_title = font_mgr.get_font(32, bold=True)
        draw.text((120, 280), self.title.upper(), font=font_title, fill=(240, 245, 255, 240))

        # Vertical Timeline Spine
        spine_x = 240
        spine_y1, spine_y2 = 380, 1150
        draw.line([(spine_x, spine_y1), (spine_x, spine_y2)], fill=(51, 65, 85, 120), width=4)

        # Active scrubber progression
        prog = min(1.0, time_sec / max(0.1, (total_frames / self.fps) * 0.85))
        eased_prog = ease_out_cubic(prog)
        scrub_y = int(spine_y1 + (spine_y2 - spine_y1) * eased_prog)
        draw.line([(spine_x, spine_y1), (spine_x, scrub_y)], fill=(129, 140, 248, 255), width=4)

        # Laser Scrubber Head
        draw.ellipse([spine_x - 10, scrub_y - 10, spine_x + 10, scrub_y + 10], fill=(255, 255, 255, 255))
        draw.ellipse([spine_x - 18, scrub_y - 18, spine_x + 18, scrub_y + 18], outline=(129, 140, 248, 180), width=2)

        # Milestone Nodes
        n_m = len(self.milestones)
        for i, (year, label) in enumerate(self.milestones):
            ny = spine_y1 + int((spine_y2 - spine_y1) * (i / max(1, n_m - 1)))
            is_active = scrub_y >= ny

            node_col = (129, 140, 248) if is_active else (71, 85, 105)
            draw.ellipse([spine_x - 14, ny - 14, spine_x + 14, ny + 14], fill=(node_col[0], node_col[1], node_col[2], 240), outline=(255, 255, 255, 180), width=2)

            if is_active:
                # Milestone Frosted Card
                card_x1 = spine_x + 40
                card_y1 = ny - 38
                card_x2 = 940
                card_y2 = ny + 50
                draw.rounded_rectangle([card_x1, card_y1, card_x2, card_y2], radius=14, fill=(15, 23, 42, 220), outline=(129, 140, 248, 160), width=2)

                font_year = font_mgr.get_font(24, bold=True)
                draw.text((card_x1 + 24, card_y1 + 14), year, font=font_year, fill=(253, 224, 71, 255))
                font_label = font_mgr.get_font(20, bold=False)
                draw.text((card_x1 + 110, card_y1 + 18), label, font=font_label, fill=(240, 245, 255, 230))


# ==============================================================================
# 5. Scientific Schematic Composition
# ==============================================================================

class ScientificSchematicComposition(BaseComposition):
    """Quantum/astrophysical orbital schematic with rotating electron shells and coronal core."""

    def __init__(
        self,
        width: int = 1080,
        height: int = 1920,
        fps: int = 30,
        core_title: str = "ATOMIC NUCLEUS",
        callout_label: str = "VALENCE ELECTRON ORBIT",
        niche: str = "space_science",
    ):
        super().__init__(width, height, fps)
        self.core_title = core_title
        self.callout_label = callout_label
        self.palette = BRAND_PALETTES.get(niche, BRAND_PALETTES["space_science"])

    def render_frame(self, canvas: Image.Image, frame_idx: int, total_frames: int, time_sec: float) -> None:
        _draw_ambient_backdrop(
            canvas,
            top_color=(28, 34, 68),
            bottom_color=(20, 26, 50),
            spotlight=(540, 750, 520, (56, 189, 248, 85)),
        )
        draw = ImageDraw.Draw(canvas, "RGBA")
        cx, cy = 540, 750

        # Title
        font_title = font_mgr.get_font(30, bold=True)
        draw.text((120, 280), "QUANTUM ENERGY SCHEMATIC", font=font_title, fill=(240, 245, 255, 230))

        # Concentric Orbital Shells (Tilted Ellipses)
        angles = [0.0, math.pi / 3.0, 2.0 * math.pi / 3.0]
        rx, ry = 360, 140

        for idx, base_rot in enumerate(angles):
            # Rotating particles along elliptical path
            shell_speed = (idx + 1) * 2.2
            p_angle = time_sec * shell_speed
            # 2D rotated ellipse points
            pts = []
            for deg in range(0, 360, 10):
                rad = math.radians(deg)
                x0 = rx * math.cos(rad)
                y0 = ry * math.sin(rad)
                xr = cx + int(x0 * math.cos(base_rot) - y0 * math.sin(base_rot))
                yr = cy + int(x0 * math.sin(base_rot) + y0 * math.cos(base_rot))
                pts.append((xr, yr))
            draw.polygon(pts, outline=(56, 189, 248, 60), fill=(0, 0, 0, 0))

            # Orbiting electron
            ex0 = rx * math.cos(p_angle)
            ey0 = ry * math.sin(p_angle)
            ex = cx + int(ex0 * math.cos(base_rot) - ey0 * math.sin(base_rot))
            ey = cy + int(ex0 * math.sin(base_rot) + ey0 * math.cos(base_rot))
            draw.ellipse([ex - 10, ey - 10, ex + 10, ey + 10], fill=(56, 189, 248, 255))
            draw.ellipse([ex - 18, ey - 18, ex + 18, ey + 18], outline=(255, 255, 255, 180), width=2)

        # Central Coronal Nucleus
        for r_c, alpha in [(80, 25), (55, 50), (35, 180), (20, 255)]:
            draw.ellipse([cx - r_c, cy - r_c, cx + r_c, cy + r_c], fill=(236, 72, 153, alpha))

        # Core Label
        font_core = font_mgr.get_font(22, bold=True)
        draw.text((cx - 80, cy + 100), self.core_title, font=font_core, fill=(240, 245, 255, 240))

        # Callout Annotation with leader line
        lx1, ly1 = cx + 220, cy - 140
        draw.line([(cx + 120, cy - 80), (lx1, ly1), (lx1 + 180, ly1)], fill=(56, 189, 248, 200), width=2)
        font_call = font_mgr.get_font(18, bold=False)
        draw.text((lx1 + 10, ly1 - 28), self.callout_label, font=font_call, fill=(56, 189, 248, 220))


# ==============================================================================
# 6. Forensic Inspection Loupe Composition
# ==============================================================================

class ForensicInspectionLoupeComposition(BaseComposition):
    """High-tech focal magnifier with targeting reticle and evidence bracket."""

    def __init__(
        self,
        width: int = 1080,
        height: int = 1920,
        fps: int = 30,
        evidence_tag: str = "ANOMALOUS DATA POINT",
        confidence: str = "CONFIDENCE: 99.8%",
        niche: str = "ai_tech",
    ):
        super().__init__(width, height, fps)
        self.evidence_tag = evidence_tag
        self.confidence = confidence
        self.palette = BRAND_PALETTES.get(niche, BRAND_PALETTES["ai_tech"])

    def render_frame(self, canvas: Image.Image, frame_idx: int, total_frames: int, time_sec: float) -> None:
        _draw_ambient_backdrop(
            canvas,
            top_color=(25, 35, 62),
            bottom_color=(19, 25, 46),
            spotlight=(540, 750, 420, (56, 189, 248, 95)),
        )
        draw = ImageDraw.Draw(canvas, "RGBA")
        cx, cy = 540, 750
        r_loupe = 260

        # Circular Loupe Outer Rim with Compass Degree Ticks
        draw.ellipse([cx - r_loupe, cy - r_loupe, cx + r_loupe, cy + r_loupe], outline=(56, 189, 248, 220), width=3)
        draw.ellipse([cx - r_loupe - 14, cy - r_loupe - 14, cx + r_loupe + 14, cy + r_loupe + 14], outline=(51, 65, 85, 120), width=1)

        rot = time_sec * 0.4
        for deg in range(0, 360, 15):
            rad = math.radians(deg) + rot
            tick_len = 12 if deg % 45 == 0 else 6
            t_x1 = int(cx + (r_loupe - tick_len) * math.cos(rad))
            t_y1 = int(cy + (r_loupe - tick_len) * math.sin(rad))
            t_x2 = int(cx + r_loupe * math.cos(rad))
            t_y2 = int(cy + r_loupe * math.sin(rad))
            draw.line([(t_x1, t_y1), (t_x2, t_y2)], fill=(56, 189, 248, 180), width=1)

        # Crosshair Targeting Reticle
        ch_len = 40
        draw.line([(cx - ch_len, cy), (cx + ch_len, cy)], fill=(255, 255, 255, 200), width=2)
        draw.line([(cx, cy - ch_len), (cx, cy + ch_len)], fill=(255, 255, 255, 200), width=2)

        # Sweeping Laser Scanline
        scan_y = cy - r_loupe + int((2 * r_loupe) * ((time_sec * 0.6) % 1.0))
        draw.line([(cx - r_loupe + 30, scan_y), (cx + r_loupe - 30, scan_y)], fill=(0, 242, 254, 180), width=2)

        # Target Brackets (Animated Spring Lock-in)
        in_t = min(1.0, time_sec / 0.5)
        d = int(70 * spring_overshoot(in_t, overshoot=1.1))
        b_len = 30
        for sx, sy in [(-1, -1), (1, -1), (-1, 1), (1, 1)]:
            corner_x = cx + sx * d
            corner_y = cy + sy * d
            draw.line([(corner_x, corner_y), (corner_x - sx * b_len, corner_y)], fill=(239, 68, 68, 240), width=3)
            draw.line([(corner_x, corner_y), (corner_x, corner_y - sy * b_len)], fill=(239, 68, 68, 240), width=3)

        # Evidentiary HUD Tag
        pill_w, pill_h = 560, 90
        px = cx - pill_w // 2
        py = cy + r_loupe + 40
        draw.rounded_rectangle([px, py, px + pill_w, py + pill_h], radius=16, fill=(15, 23, 42, 230), outline=(56, 189, 248, 180), width=2)
        font_ev = font_mgr.get_font(24, bold=True)
        draw.text((px + 30, py + 16), self.evidence_tag, font=font_ev, fill=(240, 245, 255, 240))
        font_conf = font_mgr.get_font(18, bold=False)
        draw.text((px + 30, py + 52), self.confidence, font=font_conf, fill=(52, 211, 153, 230))


# ==============================================================================
# 7. Split Screen Comparison Composition
# ==============================================================================

class SplitScreenComparisonComposition(BaseComposition):
    """Dynamic dual-realm comparison with animated seam reveal and differential bar."""

    def __init__(
        self,
        width: int = 1080,
        height: int = 1920,
        fps: int = 30,
        left_title: str = "THEORETICAL MODEL",
        right_title: str = "OBSERVED REALITY",
        delta_metric: str = "+42% HIGHER EFFICIENCY",
        niche: str = "ai_tech",
    ):
        super().__init__(width, height, fps)
        self.left_title = left_title
        self.right_title = right_title
        self.delta_metric = delta_metric
        self.palette = BRAND_PALETTES.get(niche, BRAND_PALETTES["ai_tech"])

    def render_frame(self, canvas: Image.Image, frame_idx: int, total_frames: int, time_sec: float) -> None:
        _draw_ambient_backdrop(
            canvas,
            top_color=(28, 35, 60),
            bottom_color=(20, 26, 48),
        )
        draw = ImageDraw.Draw(canvas, "RGBA")
        cx = 540

        # Reveal progress of the dividing seam
        prog = min(1.0, time_sec / max(0.1, (total_frames / self.fps) * 0.7))
        eased_p = ease_out_cubic(prog)
        seam_h = int(1920 * eased_p)

        # Left Realm (Deep Crimson Accent)
        draw.rectangle([0, 240, cx, 1200], fill=(239, 68, 68, 20))
        # Right Realm (Emerald Green Accent)
        draw.rectangle([cx, 240, 1080, 1200], fill=(16, 185, 129, 25))

        # Glowing Divider Seam
        draw.line([(cx, 200), (cx, seam_h)], fill=(255, 255, 255, 220), width=4)
        draw.line([(cx - 2, 200), (cx - 2, seam_h)], fill=(56, 189, 248, 140), width=1)
        draw.line([(cx + 2, 200), (cx + 2, seam_h)], fill=(56, 189, 248, 140), width=1)

        # Left Comparison Card
        lx1, ly1, lx2, ly2 = 80, 480, 500, 780
        draw.rounded_rectangle([lx1, ly1, lx2, ly2], radius=16, fill=(15, 23, 42, 230), outline=(239, 68, 68, 180), width=2)
        font_card = font_mgr.get_font(22, bold=True)
        wrapped_l = TypographyLayoutEngine.wrap_text_smart(self.left_title, font_card, 380)
        for idx, line in enumerate(wrapped_l[:3]):
            draw.text((lx1 + 24, ly1 + 28 + idx * 36), line, font=font_card, fill=(248, 113, 113, 240))

        # Right Comparison Card
        rx1, ry1, rx2, ry2 = 580, 480, 1000, 780
        draw.rounded_rectangle([rx1, ry1, rx2, ry2], radius=16, fill=(15, 23, 42, 230), outline=(16, 185, 129, 180), width=2)
        wrapped_r = TypographyLayoutEngine.wrap_text_smart(self.right_title, font_card, 380)
        for idx, line in enumerate(wrapped_r[:3]):
            draw.text((rx1 + 24, ry1 + 28 + idx * 36), line, font=font_card, fill=(52, 211, 153, 240))

        # Differential Percentage Gauge at Bottom
        if prog > 0.4:
            gauge_w = int(720 * ((prog - 0.4) / 0.6))
            gx1 = 180
            gy = 880
            draw.rounded_rectangle([gx1, gy, gx1 + 720, gy + 32], radius=16, fill=(30, 41, 59, 200))
            draw.rounded_rectangle([gx1, gy, gx1 + gauge_w, gy + 32], radius=16, fill=(52, 211, 153, 240))
            font_gauge = font_mgr.get_font(24, bold=True)
            draw.text((gx1 + 180, gy + 50), self.delta_metric, font=font_gauge, fill=(255, 255, 255, 240))


# ==============================================================================
# 8. Kinetic Typography Composition
# ==============================================================================

class KineticTypographyComposition(BaseComposition):
    """Staggered kinetic typography with mask reveals, spring overshoot, and glowing wipes."""

    def __init__(
        self,
        width: int = 1080,
        height: int = 1920,
        fps: int = 30,
        headline: str = "THE UNIVERSE DOES NOT CARE",
        punchline: str = "WHAT WE BELIEVE",
        niche: str = "space_science",
    ):
        super().__init__(width, height, fps)
        self.headline = headline
        self.punchline = punchline
        self.palette = BRAND_PALETTES.get(niche, BRAND_PALETTES["space_science"])

    def render_frame(self, canvas: Image.Image, frame_idx: int, total_frames: int, time_sec: float) -> None:
        _draw_ambient_backdrop(
            canvas,
            top_color=(30, 36, 65),
            bottom_color=(22, 26, 48),
            spotlight=(540, 720, 480, (129, 140, 248, 85)),
        )
        draw = ImageDraw.Draw(canvas, "RGBA")

        # Staggered entry for headline words
        words = self.headline.split()
        font_head = font_mgr.get_font(42, bold=True)

        start_y = 520
        cur_y = start_y
        for idx, word in enumerate(words):
            word_delay = idx * 0.12
            word_t = max(0.0, min(1.0, (time_sec - word_delay) / 0.4))
            eased_w = spring_overshoot(word_t, overshoot=1.12)

            alpha = int(255 * min(1.0, word_t * 2.0))
            # Slide up from boundary
            y_offset = int((1.0 - eased_w) * 60)
            draw.text((120, cur_y + y_offset), word, font=font_head, fill=(240, 245, 255, alpha))
            cur_y += 62

        # Punchline with glowing outline & active spring pop
        punch_delay = len(words) * 0.12 + 0.1
        punch_t = max(0.0, min(1.0, (time_sec - punch_delay) / 0.5))
        if punch_t > 0.0:
            eased_p = spring_overshoot(punch_t, overshoot=1.18)
            font_punch = font_mgr.get_font(52, bold=True)
            punch_box = [100, cur_y + 20, 980, cur_y + 110]
            draw.rounded_rectangle(punch_box, radius=18, fill=(15, 23, 42, 230), outline=(253, 224, 71, 230), width=3)
            draw.text((140, cur_y + 36), self.punchline, font=font_punch, fill=(253, 224, 71, 255))

            # Underline accent wipe
            wipe_w = int(840 * min(1.0, punch_t * 1.4))
            draw.line([(120, cur_y + 130), (120 + wipe_w, cur_y + 130)], fill=(56, 189, 248, 240), width=4)


# ==============================================================================
# 9. Cybernetic Interface Composition
# ==============================================================================

class CyberneticInterfaceComposition(BaseComposition):
    """Holographic telemetry terminal HUD with live hex stream and spectrum analyzer."""

    def __init__(
        self,
        width: int = 1080,
        height: int = 1920,
        fps: int = 30,
        system_name: str = "NEURAL COMPUTE CLUSTER",
        status: str = "TELEMETRY: OPTIMAL // 2.4 PFLOPS",
        niche: str = "ai_tech",
    ):
        super().__init__(width, height, fps)
        self.system_name = system_name
        self.status = status
        self.palette = BRAND_PALETTES.get(niche, BRAND_PALETTES["ai_tech"])

    def render_frame(self, canvas: Image.Image, frame_idx: int, total_frames: int, time_sec: float) -> None:
        _draw_ambient_backdrop(
            canvas,
            top_color=(24, 38, 62),
            bottom_color=(18, 26, 46),
            spotlight=(540, 700, 500, (0, 242, 254, 80)),
        )
        draw = ImageDraw.Draw(canvas, "RGBA")

        # Terminal Outer Bezel
        box = [90, 320, 990, 1140]
        draw.rounded_rectangle(box, radius=20, fill=(11, 19, 34, 230), outline=(56, 189, 248, 160), width=2)

        # Header Bar
        draw.rounded_rectangle([box[0], box[1], box[2], box[1] + 64], radius=20, fill=(15, 23, 42, 255))
        font_head = font_mgr.get_font(22, bold=True)
        draw.text((box[0] + 32, box[1] + 18), self.system_name, font=font_head, fill=(240, 245, 255, 240))
        # Status indicator dot
        draw.ellipse([box[2] - 48, box[1] + 24, box[2] - 32, box[1] + 40], fill=(52, 211, 153, 255))

        # Audio / Spectrum Analyzer Bars
        n_bars = 24
        bar_w = 26
        gap = 8
        sx = box[0] + 40
        base_y = box[3] - 80
        for i in range(n_bars):
            # Dynamic waveform oscillation
            osc = math.sin(time_sec * 6.0 + i * 0.4) * 0.5 + 0.5
            bar_h = int(30 + osc * 160)
            bx = sx + i * (bar_w + gap)
            draw.rectangle([bx, base_y - bar_h, bx + bar_w, base_y], fill=(0, 242, 254, 200), outline=(255, 255, 255, 120))

        # Circular Radial Gauge
        gx, gy = box[0] + 220, box[1] + 240
        gr = 100
        draw.ellipse([gx - gr, gy - gr, gx + gr, gy + gr], outline=(51, 65, 85, 120), width=4)
        gauge_sweep = (time_sec * 120) % 360
        draw.arc([gx - gr, gy - gr, gx + gr, gy + gr], start=0, end=int(gauge_sweep), fill=(52, 211, 153, 240), width=6)
        font_pct = font_mgr.get_font(28, bold=True)
        pct_val = int((gauge_sweep / 360.0) * 100)
        draw.text((gx - 32, gy - 16), f"{pct_val}%", font=font_pct, fill=(240, 245, 255, 240))

        # Simulated Live Hex Stream
        hex_lines = [
            "0x7F4A  MOV EAX, [RSP+0x18]",
            "0x7F52  SHL RAX, 0x03",
            "0x7F58  VADDPS YMM0, YMM1, YMM2",
            "0x7F62  STREAM_SYNC_OK",
        ]
        font_hex = font_mgr.get_font(18, bold=False)
        hx = box[0] + 400
        hy = box[1] + 160
        for idx, line in enumerate(hex_lines):
            draw.text((hx, hy + idx * 36), line, font=font_hex, fill=(148, 163, 184, 210))

        # Status Footer Pill
        font_stat = font_mgr.get_font(20, bold=True)
        draw.text((box[0] + 32, box[3] - 46), self.status, font=font_stat, fill=(52, 211, 153, 230))


# ==============================================================================
# 10. Motion Design Studio Registry & Semantic Router
# ==============================================================================

class MotionDesignStudio:
    """Unified Registry and Semantic Router for all professional motion compositions."""

    _REGISTRY: Dict[str, Any] = {
        "isometric_stats": Isometric3DBarChartComposition,
        "financial_trend": FinancialTrendChartComposition,
        "geo_map": GeographicMapRouteComposition,
        "historical_timeline": HistoricalTimelineComposition,
        "scientific_schematic": ScientificSchematicComposition,
        "inspection_loupe": ForensicInspectionLoupeComposition,
        "split_screen_comparison": SplitScreenComparisonComposition,
        "kinetic_typography": KineticTypographyComposition,
        "cybernetic_interface": CyberneticInterfaceComposition,
        "starfield": DeepSpaceStarfieldComposition,
        "cinematic_space_environment": DeepSpaceStarfieldComposition,
    }

    @classmethod
    def list_compositions(cls) -> List[str]:
        """Returns names of all registered procedural compositions."""
        return list(cls._REGISTRY.keys())

    @classmethod
    def create_composition(cls, comp_type: str, **kwargs: Any) -> BaseComposition:
        """Instantiates a composition by name with keyword arguments."""
        norm_type = comp_type.lower().strip()
        comp_cls = cls._REGISTRY.get(norm_type)
        if not comp_cls:
            # Fallback to kinetic typography
            comp_cls = KineticTypographyComposition
        return comp_cls(**kwargs)

    @classmethod
    def infer_composition_from_narration(
        cls,
        text: str,
        intent: str = "",
        niche: str = "general",
    ) -> BaseComposition:
        """Analyzes narration semantics and returns the optimal procedural composition."""
        lower = f"{text} {intent}".lower()

        # 1. Space & Cosmic distances -> Starfield
        if any(k in lower for k in ["sparse star", "never touch", "almost none", "empty space", "light-years", "milky way", "andromeda"]):
            return DeepSpaceStarfieldComposition(niche=niche)

        # 2. Geography / Observatories / Maps / Locations -> Geographic Map
        if any(k in lower for k in ["observatory", "telescope", "across the globe", "location", "geographic", "coordinates", "transit:"]):
            return GeographicMapRouteComposition(niche=niche)

        # 3. Quantum / Physics / Atomic / Molecules -> Scientific Schematic
        if any(k in lower for k in ["atom", "quantum", "electron", "nucleus", "orbiting the", "valence", "magnetic field"]):
            return ScientificSchematicComposition(niche=niche)

        # 4. Evidence / Investigation / Forensic / Anomaly -> Inspection Loupe
        if any(k in lower for k in ["evidence", "proof", "revealed", "inspection", "anomaly", "microscopic", "under closer"]):
            return ForensicInspectionLoupeComposition(niche=niche)

        # 5. Chronology / Milestones / Years -> Historical Timeline
        if any(k in lower for k in ["history", "timeline", "decade", "century", "first observed in", "milestone", "chronology"]):
            return HistoricalTimelineComposition(niche=niche)

        # 6. Comparison / Theory vs Reality -> Split Screen
        if any(k in lower for k in ["theory versus", "versus", "theory vs", "observed reality", "contrary to", "in contrast"]):
            return SplitScreenComparisonComposition(niche=niche)

        # 7. Financial / Market / Valuation Surges -> Financial Trend
        if any(k in lower for k in ["revenue", "financial", "all-time high", "valuation", "stock", "billion dollar", "market surge"]):
            return FinancialTrendChartComposition(niche=niche)

        # 8. Computing / AI / Neural Networks / Cyber -> Cybernetic Interface
        if any(k in lower for k in ["neural", "supercomputer", "data stream", "cyber", "telemetry:", "pflops", "algorithm"]):
            return CyberneticInterfaceComposition(niche=niche)

        # 9. Statistics / Percentage comparisons / Isometric Bars -> Isometric Stats
        if any(k in lower for k in ["percent", "%", "statistical", "metric", "capacity expanded", "double", "triple"]):
            return Isometric3DBarChartComposition(niche=niche)

        # 10. Default High-Impact Kinetic Typography
        return KineticTypographyComposition(niche=niche)
