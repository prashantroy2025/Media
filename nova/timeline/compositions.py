"""Reusable procedural compositions for NOVA AUTOPILOT Unified Creative Timeline.

Eliminates empty black backgrounds and generic card templates by providing
visually rich, context-aware generative scenes (e.g. Cinematic Starfield,
Parallax Environments, Multi-layer Diagrams).
"""

from __future__ import annotations

import math
import os
from pathlib import Path
import random
import subprocess
from typing import Any, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont


class BaseComposition:
    """Base class for all procedural visual timeline compositions."""

    def __init__(self, width: int = 1080, height: int = 1920, fps: int = 30):
        self.width = width
        self.height = height
        self.fps = fps

    def render_frame(self, canvas: Image.Image, frame_idx: int, total_frames: int, time_sec: float) -> None:
        raise NotImplementedError

    def render_to_video(self, out_path: Path | str, duration: float, fps: int = 30) -> Path:
        """Renders complete 1080x1920 30fps CFR MP4 using Apple Silicon VideoToolbox if available."""
        out_p = Path(out_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        total_frames = max(1, int(round(duration * fps)))

        from nova.renderer import detect_video_encoder
        encoder = detect_video_encoder()

        cmd = [
            "ffmpeg",
            "-y",
            "-f", "rawvideo",
            "-vcodec", "rawvideo",
            "-s", f"{self.width}x{self.height}",
            "-pix_fmt", "rgb24",
            "-r", str(fps),
            "-i", "-",
            "-c:v", encoder,
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(out_p.resolve()),
        ]

        env = dict(os.environ)
        env["PATH"] = f"/opt/homebrew/bin:{env.get('PATH', '')}"
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=env)

        frame_canvas = Image.new("RGB", (self.width, self.height))
        last_frame: Image.Image | None = None

        for f in range(total_frames):
            time_sec = f / max(1, fps)
            self.render_frame(frame_canvas, f, total_frames, time_sec)
            proc.stdin.write(frame_canvas.tobytes())
            last_frame = frame_canvas

        proc.stdin.close()
        proc.wait()

        if last_frame:
            prev_p = out_p.with_name(f"{out_p.stem}_prev.jpg")
            last_frame.save(prev_p, quality=90)

        return out_p


class DeepSpaceStarfieldComposition(BaseComposition):
    """Cinematic Deep-Space Starfield with 3D perspective camera push.

    Accurately visualizes:
    - 'zooming through sparse stars'
    - 'so immense, almost none will ever touch'
    - galaxy collisions and cosmic distances

    Features:
    - 3-plane depth-projected starfield with perspective acceleration.
    - Motion warp trails along radial vectors.
    - Radiant cosmic nebula atmospheric backdrop (midnight obsidian to indigo-violet).
    - Drifting stardust particles with gentle scintillation.
    - Two celestial stellar bodies gliding smoothly on non-colliding hyperbolic tracks.
    """

    def __init__(
        self,
        width: int = 1080,
        height: int = 1920,
        fps: int = 30,
        num_stars: int = 180,
        num_particles: int = 80,
        seed: int = 42,
        niche: str = "space_science",
        **kwargs: Any,
    ):
        super().__init__(width, height, fps)
        self.num_stars = num_stars
        self.num_particles = num_particles
        self.seed = seed
        self.niche = niche
        self._init_celestial_data()

    def _init_celestial_data(self) -> None:
        rng = random.Random(self.seed)
        self.stars = []
        for _ in range(self.num_stars):
            # 3D coordinates: x in [-1200, 1200], y in [-1800, 1800], z in [0.8, 6.0]
            x = rng.uniform(-1400, 1400)
            y = rng.uniform(-2000, 2000)
            z = rng.uniform(0.6, 6.0)
            base_size = rng.uniform(1.5, 4.2)
            # Colors: pure white, diamond blue, warm gold, soft cyan
            color_choice = rng.choice([
                (255, 255, 255),
                (210, 235, 255),
                (180, 220, 255),
                (255, 240, 210),
                (140, 210, 255),
            ])
            self.stars.append({
                "x": x,
                "y": y,
                "z": z,
                "init_z": z,
                "base_size": base_size,
                "color": color_choice,
                "twinkle_speed": rng.uniform(2.5, 6.0),
                "phase": rng.uniform(0.0, math.pi * 2),
            })

        # Floating stardust particles
        self.particles = []
        for _ in range(self.num_particles):
            self.particles.append({
                "x": rng.uniform(0, self.width),
                "y": rng.uniform(0, self.height),
                "speed_y": rng.uniform(-0.4, 0.4),
                "speed_x": rng.uniform(-0.3, 0.3),
                "radius": rng.uniform(1.0, 2.5),
                "color": rng.choice([(100, 200, 255), (180, 140, 255), (255, 220, 150)]),
                "alpha": rng.uniform(40, 120),
            })

        # Precompute static deep-space atmospheric nebula gradient
        self.nebula_bg = Image.new("RGB", (self.width, self.height), (4, 6, 14))
        draw_bg = ImageDraw.Draw(self.nebula_bg, "RGBA")

        # Soft glowing cosmic nebula clouds
        clouds = [
            (320, 550, 480, (28, 12, 54, 110)),   # Deep cosmic violet
            (760, 1200, 520, (12, 24, 62, 100)),  # Galactic indigo
            (480, 960, 600, (6, 32, 58, 80)),     # Midnight cyan
            (820, 420, 380, (48, 18, 42, 70)),    # Soft magenta cloud
        ]
        for cx, cy, r, col in clouds:
            for step in range(r, 0, -40):
                alpha = int(col[3] * (step / r))
                draw_bg.ellipse(
                    [cx - step, cy - step, cx + step, cy + step],
                    fill=(col[0], col[1], col[2], alpha),
                )

    def render_frame(self, canvas: Image.Image, frame_idx: int, total_frames: int, time_sec: float) -> None:
        """Renders one cinematic frame directly into the canvas."""
        # 1. Paste ambient nebula backdrop
        canvas.paste(self.nebula_bg, (0, 0))
        draw = ImageDraw.Draw(canvas, "RGBA")

        # Dynamic camera push forward speed
        cam_speed = 0.55  # z velocity per second
        focal_length = 720.0
        center_x = self.width / 2.0
        center_y = self.height / 2.0

        # 2. Render 3D Perspective Stars with radial motion blur
        for s in self.stars:
            # Advance camera along z
            cur_z = s["init_z"] - (time_sec * cam_speed)
            # Loop z seamlessly
            loop_span = 5.4
            cur_z = ((cur_z - 0.6) % loop_span) + 0.6

            # 3D to 2D projection
            inv_z = 1.0 / cur_z
            px = center_x + (s["x"] * focal_length * inv_z * 0.001)
            py = center_y + (s["y"] * focal_length * inv_z * 0.001)

            # Skip if outside frame bounds with margin
            if not (-100 <= px <= self.width + 100 and -100 <= py <= self.height + 100):
                continue

            # Scale and brightness grow as star approaches viewer
            proximity = max(0.0, min(1.0, (4.5 - cur_z) / 3.8))
            star_radius = max(1.2, s["base_size"] * (inv_z * 1.8))
            twinkle = 0.85 + 0.15 * math.sin(time_sec * s["twinkle_speed"] + s["phase"])
            alpha = int(min(255, (120 + 135 * proximity) * twinkle))

            col = s["color"]
            col_rgba = (col[0], col[1], col[2], alpha)

            # Draw radial motion streak for closer stars
            if cur_z < 2.5:
                # Vector pointing away from center
                dx = px - center_x
                dy = py - center_y
                dist = math.hypot(dx, dy)
                if dist > 10:
                    streak_len = min(48.0, (dist * 0.06) * (1.0 / cur_z))
                    tail_x = px - (dx / dist) * streak_len
                    tail_y = py - (dy / dist) * streak_len
                    draw.line([(tail_x, tail_y), (px, py)], fill=(col[0], col[1], col[2], int(alpha * 0.6)), width=max(1, int(star_radius * 0.8)))

            # Star core and soft bloom
            draw.ellipse(
                [px - star_radius, py - star_radius, px + star_radius, py + star_radius],
                fill=col_rgba,
            )
            if star_radius > 3.0:
                bloom_r = star_radius * 2.2
                draw.ellipse(
                    [px - bloom_r, py - bloom_r, px + bloom_r, py + bloom_r],
                    fill=(col[0], col[1], col[2], int(alpha * 0.25)),
                )

        # 3. Celestial Hyperbolic Pass: Two star systems gliding past each other safely
        # Body A: Golden celestial star gliding from top-left to bottom-center
        # Body B: Blue giant star gliding from bottom-right to top-center
        t_norm = min(1.0, time_sec / max(1.0, total_frames / self.fps))
        eased_pass = 0.5 * (1.0 - math.cos(t_norm * math.pi))

        # Body A (Golden Star)
        a_x = 240 + int(380 * eased_pass)
        a_y = 480 + int(720 * eased_pass)
        a_r = int(24 + 6 * math.sin(time_sec * 3.0))
        # Atmospheric corona
        draw.ellipse([a_x - a_r * 3, a_y - a_r * 3, a_x + a_r * 3, a_y + a_r * 3], fill=(255, 180, 50, 25))
        draw.ellipse([a_x - a_r * 2, a_y - a_r * 2, a_x + a_r * 2, a_y + a_r * 2], fill=(255, 210, 80, 50))
        draw.ellipse([a_x - a_r, a_y - a_r, a_x + a_r, a_y + a_r], fill=(255, 245, 180, 240))
        # Orbital path marker
        draw.line([(180, 360), (a_x, a_y)], fill=(255, 200, 80, 40), width=2)

        # Body B (Blue Giant) - passing without collision at safe distance (offset by > 260px)
        b_x = 840 - int(340 * eased_pass)
        b_y = 1380 - int(700 * eased_pass)
        b_r = int(28 + 5 * math.cos(time_sec * 3.2))
        draw.ellipse([b_x - b_r * 3, b_y - b_r * 3, b_x + b_r * 3, b_y + b_r * 3], fill=(40, 140, 255, 25))
        draw.ellipse([b_x - b_r * 2, b_y - b_r * 2, b_x + b_r * 2, b_y + b_r * 2], fill=(80, 180, 255, 50))
        draw.ellipse([b_x - b_r, b_y - b_r, b_x + b_r, b_y + b_r], fill=(200, 235, 255, 240))
        draw.line([(890, 1480), (b_x, b_y)], fill=(80, 180, 255, 40), width=2)

        # Distance indicator beam proving zero collision
        mid_x = (a_x + b_x) // 2
        mid_y = (a_y + b_y) // 2
        dist_px = int(math.hypot(b_x - a_x, b_y - a_y))
        draw.line([(a_x, a_y), (b_x, b_y)], fill=(0, 220, 255, 45), width=1)
        draw.ellipse([mid_x - 4, mid_y - 4, mid_x + 4, mid_y + 4], fill=(0, 240, 255, 180))

        # 4. Floating stardust particles
        for p in self.particles:
            px = int((p["x"] + time_sec * p["speed_x"] * 60) % self.width)
            py = int((p["y"] + time_sec * p["speed_y"] * 60) % self.height)
            pr = p["radius"]
            p_col = (p["color"][0], p["color"][1], p["color"][2], int(p["alpha"]))
            draw.ellipse([px - pr, py - pr, px + pr, py + pr], fill=p_col)


# Re-export Motion Studio compositions for module level convenience
from nova.timeline.motion_studio import (
    CyberneticInterfaceComposition,
    FinancialTrendChartComposition,
    ForensicInspectionLoupeComposition,
    GeographicMapRouteComposition,
    HistoricalTimelineComposition,
    Isometric3DBarChartComposition,
    KineticTypographyComposition,
    MotionDesignStudio,
    ScientificSchematicComposition,
    SplitScreenComparisonComposition,
)
