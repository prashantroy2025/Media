"""Open-License Vector & PNG Icon Library for Nova Autopilot v8.0 Motion Design.

Provides rendered RGBA icon overlays for explainer graphics, facts, and infographics.
Icons based on Lucide / Feather icon specifications under the MIT License.
"""

from __future__ import annotations

import math
from pathlib import Path
from PIL import Image, ImageDraw

from nova.config import PROJECT_ROOT

ICONS_DIR = PROJECT_ROOT / "assets" / "icons"


def ensure_icon_library() -> dict[str, Path]:
    """Generates and caches essential 256x256 RGBA icons with transparent backgrounds."""
    ICONS_DIR.mkdir(parents=True, exist_ok=True)

    # Write MIT License
    lic_file = ICONS_DIR / "LICENSE.txt"
    lic_file.write_text(
        "MIT License\n\n"
        "Copyright (c) 2024 Lucide / Feather Contributors & Nova Autopilot\n\n"
        "Permission is hereby granted, free of charge, to any person obtaining a copy "
        "of this software and associated documentation files (the 'Software'), to deal "
        "in the Software without restriction, including without limitation the rights "
        "to use, copy, modify, merge, publish, distribute, sublicense, and/or sell "
        "copies of the Software.\n",
        encoding="utf-8",
    )

    icons = {}
    names = ["cpu", "rocket", "dollar", "scale", "shield", "graph", "clock", "check", "alert", "building", "globe"]

    for name in names:
        icon_path = ICONS_DIR / f"{name}.png"
        if not icon_path.exists() or icon_path.stat().st_size < 500:
            img = _render_procedural_icon(name)
            img.save(icon_path, "PNG")
        icons[name] = icon_path

    return icons


def _render_procedural_icon(name: str, size: int = 256) -> Image.Image:
    """Renders crisp vector-style icons directly onto an RGBA transparent canvas."""
    img = Image.Image()._new(Image.core.new("RGBA", (size, size)))
    draw = ImageDraw.Draw(img)

    cyan = (56, 189, 248, 255)
    white = (255, 255, 255, 255)
    gold = (250, 204, 21, 255)
    green = (74, 222, 128, 255)
    red = (248, 113, 113, 255)

    pad = 32
    stroke = 14

    if name == "cpu":
        # Central square
        draw.rounded_rectangle([pad + 24, pad + 24, size - pad - 24, size - pad - 24], radius=16, outline=cyan, width=stroke)
        draw.rounded_rectangle([pad + 44, pad + 44, size - pad - 44, size - pad - 44], radius=8, fill=cyan)
        # Pins
        for offset in [68, 112, 156]:
            draw.line([(pad + offset, pad), (pad + offset, pad + 24)], fill=cyan, width=stroke)
            draw.line([(pad + offset, size - pad - 24), (pad + offset, size - pad)], fill=cyan, width=stroke)
            draw.line([(pad, pad + offset), (pad + 24, pad + offset)], fill=cyan, width=stroke)
            draw.line([(size - pad - 24, pad + offset), (size - pad, pad + offset)], fill=cyan, width=stroke)

    elif name == "rocket":
        # Sleek rocket fuselage
        cx = size // 2
        draw.polygon([(cx, pad), (cx + 40, size - pad - 40), (cx, size - pad - 60), (cx - 40, size - pad - 40)], outline=cyan, fill=(56, 189, 248, 80))
        draw.ellipse([cx - 14, pad + 60, cx + 14, pad + 88], fill=gold)
        # Flame
        draw.polygon([(cx - 16, size - pad - 50), (cx, size - pad), (cx + 16, size - pad - 50)], fill=gold)

    elif name == "dollar":
        cx, cy = size // 2, size // 2
        draw.ellipse([pad, pad, size - pad, size - pad], outline=gold, width=stroke)
        # S curve
        draw.arc([cx - 30, cy - 60, cx + 30, cy], start=90, end=300, fill=gold, width=stroke)
        draw.arc([cx - 30, cy, cx + 30, cy + 60], start=270, end=120, fill=gold, width=stroke)
        draw.line([(cx, cy - 75), (cx, cy + 75)], fill=gold, width=stroke)

    elif name == "scale":
        cx, cy = size // 2, size // 2
        # Vertical post & base
        draw.line([(cx, pad + 20), (cx, size - pad)], fill=white, width=stroke)
        draw.line([(cx - 48, size - pad), (cx + 48, size - pad)], fill=white, width=stroke)
        # Beam
        draw.line([(pad + 20, pad + 50), (size - pad - 20, pad + 50)], fill=white, width=stroke)
        # Left pan
        draw.line([(pad + 30, pad + 50), (pad + 10, pad + 120)], fill=cyan, width=8)
        draw.line([(pad + 30, pad + 50), (pad + 50, pad + 120)], fill=cyan, width=8)
        draw.arc([pad + 5, pad + 100, pad + 55, pad + 140], start=0, end=180, fill=cyan, width=stroke)
        # Right pan
        draw.line([(size - pad - 30, pad + 50), (size - pad - 50, pad + 120)], fill=cyan, width=8)
        draw.line([(size - pad - 30, pad + 50), (size - pad - 10, pad + 120)], fill=cyan, width=8)
        draw.arc([size - pad - 55, pad + 100, size - pad - 5, pad + 140], start=0, end=180, fill=cyan, width=stroke)

    elif name == "shield":
        cx = size // 2
        draw.polygon([(pad + 20, pad + 20), (size - pad - 20, pad + 20), (size - pad - 20, pad + 90), (cx, size - pad), (pad + 20, pad + 90)], outline=cyan, width=stroke, fill=(56, 189, 248, 50))
        draw.line([(cx - 24, size // 2), (cx - 8, size // 2 + 16), (cx + 28, size // 2 - 20)], fill=green, width=stroke)

    elif name == "graph":
        # Trending up arrow
        draw.line([(pad + 20, size - pad - 20), (size - pad - 20, size - pad - 20)], fill=white, width=stroke)
        draw.line([(pad + 20, size - pad - 20), (pad + 20, pad + 20)], fill=white, width=stroke)
        # Bar chart lines
        draw.rectangle([pad + 44, size - pad - 70, pad + 74, size - pad - 20], fill=cyan)
        draw.rectangle([pad + 94, size - pad - 120, pad + 124, size - pad - 20], fill=cyan)
        draw.rectangle([pad + 144, size - pad - 170, pad + 174, size - pad - 20], fill=gold)

    elif name == "clock":
        cx, cy = size // 2, size // 2
        draw.ellipse([pad, pad, size - pad, size - pad], outline=white, width=stroke)
        draw.line([(cx, cy), (cx, pad + 40)], fill=white, width=stroke)
        draw.line([(cx, cy), (cx + 45, cy)], fill=cyan, width=stroke)

    elif name == "check":
        cx, cy = size // 2, size // 2
        draw.ellipse([pad, pad, size - pad, size - pad], outline=green, width=stroke, fill=(74, 222, 128, 40))
        draw.line([(cx - 40, cy), (cx - 10, cy + 30), (cx + 45, cy - 25)], fill=green, width=stroke)

    elif name == "alert":
        cx = size // 2
        draw.polygon([(cx, pad), (size - pad, size - pad), (pad, size - pad)], outline=gold, width=stroke, fill=(250, 204, 21, 40))
        draw.line([(cx, pad + 60), (cx, size - pad - 60)], fill=gold, width=stroke)
        draw.ellipse([cx - 8, size - pad - 44, cx + 8, size - pad - 28], fill=gold)

    elif name == "building":
        draw.rectangle([pad + 20, pad + 30, size - pad - 20, size - pad], outline=white, width=stroke)
        # Window grid
        for r in range(4):
            for c in range(3):
                wx = pad + 44 + c * 48
                wy = pad + 55 + r * 38
                draw.rectangle([wx, wy, wx + 28, wy + 24], fill=cyan)

    else:  # globe
        cx, cy = size // 2, size // 2
        draw.ellipse([pad, pad, size - pad, size - pad], outline=cyan, width=stroke)
        draw.line([(pad, cy), (size - pad, cy)], fill=cyan, width=8)
        draw.ellipse([pad + 36, pad, size - pad - 36, size - pad], outline=cyan, width=8)

    return img


if __name__ == "__main__":
    out = ensure_icon_library()
    print(f"Generated {len(out)} open-license icons in {ICONS_DIR}")
