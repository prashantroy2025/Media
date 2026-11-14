"""Brand Kit, Color Palettes, Safe Zones, and Layout Collision Checker for Nova Autopilot v8.0."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Tuple

from PIL import ImageFont

from nova.config import PROJECT_ROOT


@dataclass
class NichePalette:
    name: str
    primary: Tuple[int, int, int]
    secondary: Tuple[int, int, int]
    accent: Tuple[int, int, int]
    background_dark: Tuple[int, int, int]
    text_light: Tuple[int, int, int] = (255, 255, 255)
    shadow_color: Tuple[int, int, int, int] = (0, 0, 0, 180)


BRAND_PALETTES = {
    "ai_tech": NichePalette(
        name="AI & Technology",
        primary=(0, 242, 254),       # #00F2FE Electric Cyan
        secondary=(79, 172, 254),    # #4FACFE Neon Blue
        accent=(252, 211, 77),       # #FCD34D Neon Gold
        background_dark=(11, 15, 25), # Deep Obsidian
    ),
    "business": NichePalette(
        name="Business & Economics",
        primary=(16, 185, 129),      # #10B981 Emerald Mint
        secondary=(245, 158, 11),    # #F59E0B Rich Amber
        accent=(56, 189, 248),       # Sky Blue
        background_dark=(15, 23, 42), # Dark Slate Navy
    ),
    "space_science": NichePalette(
        name="Space & Science",
        primary=(129, 140, 248),     # #818CF8 Cosmic Indigo
        secondary=(236, 72, 153),    # #EC4899 Nebula Pink
        accent=(253, 224, 71),       # #FDE047 Starlight Amber
        background_dark=(3, 7, 18),   # Void Black
    ),
}

# 1080x1920 Portrait 9:16 Platform Safe Zones
SAFE_ZONE_CARD = (80, 240, 1000, 1200)       # (x1, y1, x2, y2) Content, charts, illustrations
SAFE_ZONE_CAPTIONS = (80, 1280, 1000, 1560)  # (x1, y1, x2, y2) Fixed lower caption band

SAFE_ZONE = {
    "top": 240,
    "bottom": 1560,
    "left": 80,
    "right": 1000,
    "width": 920,
    "height": 1320,
}

# Dedicated Vertical Layout Channels (Prevents collisions by design)
CHANNELS = {
    "hook_card": (260, 580),
    "kinetic_pop": (480, 850),
    "infographic_counter": (260, 1180),
    "karaoke_captions": (1280, 1560),
    "source_pill": (1580, 1640),
    "progress_bar": (1900, 1908),
}


class FontManager:
    """Manages licensed typography for motion overlays."""

    def __init__(self):
        self.fonts_dir = PROJECT_ROOT / "assets" / "fonts"
        self.primary_font_path = self.fonts_dir / "Montserrat-ExtraBold.ttf"
        self.secondary_font_path = self.fonts_dir / "Montserrat-Variable.ttf"

    def get_font(self, size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
        p = self.primary_font_path if bold else self.secondary_font_path
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size)
            except Exception:
                pass
        return ImageFont.load_default()


class CollisionChecker:
    """Detects bounding box collisions between active visual components."""

    @staticmethod
    def intersects(box_a: Tuple[int, int, int, int], box_b: Tuple[int, int, int, int]) -> bool:
        """Returns True if box_a (x1, y1, x2, y2) overlaps box_b."""
        ax1, ay1, ax2, ay2 = box_a
        bx1, by1, bx2, by2 = box_b
        return not (ax2 < bx1 or ax1 > bx2 or ay2 < by1 or ay1 > by2)

    @classmethod
    def resolve_overlap(
        cls,
        active_boxes: list[Tuple[int, int, int, int]],
        candidate_box: Tuple[int, int, int, int],
        shift_step_y: int = -50,
    ) -> Tuple[int, int, int, int]:
        """Shifts candidate box vertically upwards until it clears existing bounding boxes."""
        cx1, cy1, cx2, cy2 = candidate_box
        h = cy2 - cy1
        current_y1 = cy1
        current_y2 = cy2

        attempts = 0
        while attempts < 10:
            collides = False
            for b in active_boxes:
                if cls.intersects((cx1, current_y1, cx2, current_y2), b):
                    collides = True
                    break
            if not collides:
                return (cx1, current_y1, cx2, current_y2)

            current_y1 += shift_step_y
            current_y2 += shift_step_y
            attempts += 1

        return candidate_box
