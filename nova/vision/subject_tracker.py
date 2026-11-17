"""Subject-Aware Visual Intelligence and Camera Tracking for Nova Autopilot v9.2.

Provides:
- Face detection and skin-tone clustering in YCbCr color space.
- Gradient and color saliency detection for objects, celestial bodies, and documents.
- Composition-aware vertical (9:16) framing avoiding caption zones.
- Intelligent zoom and pan targeting that follows the subject instead of blind center-zooming.
- Pure Pillow + NumPy implementation with zero dylib conflicts.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
from PIL import Image

from nova.logging_setup import logger


@dataclass
class SubjectBBox:
    """Represents a detected focal subject in an image or video frame."""
    x: int
    y: int
    w: int
    h: int
    norm_cx: float  # Normalized center X [0.0, 1.0]
    norm_cy: float  # Normalized center Y [0.0, 1.0]
    confidence: float
    subject_type: Literal["face", "salient_object", "celestial_body", "text_region", "center_fallback"]
    aspect_ratio: float = 1.0


class SubjectTracker:
    """Intelligent subject detection and composition framing engine (pure NumPy + Pillow)."""

    def detect_subject(self, image_input: Image.Image | Path | str | np.ndarray) -> SubjectBBox:
        """Detects the primary subject in an image using multi-stage visual heuristics."""
        if isinstance(image_input, (str, Path)):
            p = Path(image_input)
            if not p.exists():
                return SubjectBBox(0, 0, 100, 100, 0.5, 0.5, 0.0, "center_fallback")
            try:
                img = Image.open(p).convert("RGB")
            except Exception:
                return SubjectBBox(0, 0, 100, 100, 0.5, 0.5, 0.0, "center_fallback")
        elif isinstance(image_input, Image.Image):
            img = image_input.convert("RGB")
        elif isinstance(image_input, np.ndarray):
            img = Image.fromarray(image_input.astype(np.uint8)).convert("RGB")
        else:
            return SubjectBBox(0, 0, 100, 100, 0.5, 0.5, 0.0, "center_fallback")

        w, h = img.size
        if w <= 0 or h <= 0:
            return SubjectBBox(0, 0, 100, 100, 0.5, 0.5, 0.0, "center_fallback")

        arr = np.array(img, dtype=np.float32)

        # 1. Skin tone clustering in YCbCr color space for human faces
        face_bbox = self._detect_face_skin(img, arr, w, h)
        if face_bbox:
            return face_bbox

        # 2. Compute visual saliency (Sobel gradient energy + Color saturation)
        salient_bbox = self._detect_saliency(arr, w, h)
        if salient_bbox:
            return salient_bbox

        # 3. Fallback to center
        return SubjectBBox(
            x=int(w * 0.25),
            y=int(h * 0.25),
            w=int(w * 0.5),
            h=int(h * 0.5),
            norm_cx=0.5,
            norm_cy=0.45,
            confidence=0.5,
            subject_type="center_fallback",
        )

    def _detect_face_skin(self, img: Image.Image, arr: np.ndarray, w: int, h: int) -> SubjectBBox | None:
        """Lightweight face detection using YCbCr skin tone clustering."""
        try:
            ycbcr = np.array(img.convert("YCbCr"), dtype=np.float32)
            cb = ycbcr[:, :, 1]
            cr = ycbcr[:, :, 2]
            skin_mask = (cb >= 77) & (cb <= 127) & (cr >= 133) & (cr <= 173)
            skin_pixels = np.count_nonzero(skin_mask)
            total_pixels = w * h

            if skin_pixels > (total_pixels * 0.03):
                y_idx, x_idx = np.where(skin_mask)
                cx = float(np.mean(x_idx))
                cy = float(np.mean(y_idx))
                min_x, max_x = int(np.percentile(x_idx, 5)), int(np.percentile(x_idx, 95))
                min_y, max_y = int(np.percentile(y_idx, 5)), int(np.percentile(y_idx, 95))
                bw = max(10, max_x - min_x)
                bh = max(10, max_y - min_y)

                return SubjectBBox(
                    x=min_x,
                    y=min_y,
                    w=bw,
                    h=bh,
                    norm_cx=round(max(0.15, min(0.85, cx / w)), 3),
                    norm_cy=round(max(0.15, min(0.65, cy / h)), 3),
                    confidence=0.82,
                    subject_type="face",
                    aspect_ratio=round(bw / bh, 2),
                )
        except Exception:
            pass
        return None

    def _detect_saliency(self, arr: np.ndarray, w: int, h: int) -> SubjectBBox | None:
        """Calculates visual saliency using luminance gradient magnitude and color saturation."""
        try:
            gray = 0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]
            gy, gx = np.gradient(gray)
            grad = np.sqrt(gx**2 + gy**2)
            grad_max = np.max(grad)
            grad_norm = grad / (grad_max + 1e-5)

            max_c = np.max(arr, axis=2)
            min_c = np.min(arr, axis=2)
            sat = (max_c - min_c) / (max_c + 1e-5)

            S = 0.6 * grad_norm + 0.4 * sat
            total_mass = float(np.sum(S))

            if total_mass > 0:
                y_idx, x_idx = np.indices((h, w))
                cx = float(np.sum(x_idx * S) / total_mass)
                cy = float(np.sum(y_idx * S) / total_mass)

                norm_cx = max(0.15, min(0.85, cx / w))
                norm_cy = max(0.15, min(0.65, cy / h))

                mean_lum = float(np.mean(gray))
                subtype = "celestial_body" if mean_lum < 55 else "salient_object"

                return SubjectBBox(
                    x=int(cx - w * 0.15),
                    y=int(cy - h * 0.15),
                    w=int(w * 0.3),
                    h=int(h * 0.3),
                    norm_cx=round(norm_cx, 3),
                    norm_cy=round(norm_cy, 3),
                    confidence=0.88,
                    subject_type=subtype,
                )
        except Exception:
            pass
        return None

    def compute_crop_window(
        self,
        orig_w: int,
        orig_h: int,
        target_aspect: float = 9.0 / 16.0,
        subject: SubjectBBox | None = None,
    ) -> tuple[int, int, int, int]:
        """Calculates 9:16 crop box (x, y, crop_w, crop_h) centered on the detected subject."""
        current_aspect = orig_w / orig_h
        if current_aspect > target_aspect:
            crop_h = orig_h
            crop_w = int(round(crop_h * target_aspect))
            center_x = int(orig_w * (subject.norm_cx if subject else 0.5))
            x1 = center_x - crop_w // 2
            x1 = max(0, min(orig_w - crop_w, x1))
            y1 = 0
        else:
            crop_w = orig_w
            crop_h = int(round(crop_w / target_aspect))
            center_y = int(orig_h * (subject.norm_cy if subject else 0.45))
            y1 = center_y - crop_h // 2
            y1 = max(0, min(orig_h - crop_h, y1))
            x1 = 0
        return x1, y1, crop_w, crop_h

    def generate_subject_zoompan_expr(
        self,
        image_path: Path,
        target_duration: float,
        fps: int = 30,
        zoom_factor: float = 1.12,
        direction: str = "zoom_in",
    ) -> str:
        """Builds an intelligent FFmpeg zoompan filter string tracking the subject center."""
        subject = self.detect_subject(image_path)
        total_frames = max(1, int(round(target_duration * fps)))
        zoom_step = round((zoom_factor - 1.0) / max(1, total_frames), 6)

        anchor_x = max(0.2, min(0.8, subject.norm_cx))
        anchor_y = max(0.2, min(0.65, subject.norm_cy))

        if direction == "zoom_out":
            z_expr = f"if(lte(zoom,1.0),{zoom_factor},max(1.001,zoom-{zoom_step}))"
            x_expr = f"min(max(0,iw*{anchor_x}-(iw/zoom*{anchor_x})),iw-iw/zoom)"
            y_expr = f"min(max(0,ih*{anchor_y}-(ih/zoom*{anchor_y})),ih-ih/zoom)"
        elif direction == "pan_to_subject":
            z_expr = f"{zoom_factor}"
            x_expr = f"min(max(0,(iw/2*(1-on/{total_frames}))+(iw*{anchor_x}*(on/{total_frames}))-(iw/zoom/2)),iw-iw/zoom)"
            y_expr = f"min(max(0,(ih/2*(1-on/{total_frames}))+(ih*{anchor_y}*(on/{total_frames}))-(ih/zoom/2)),ih-ih/zoom)"
        elif direction == "pan_right":
            z_expr = "1.08"
            x_expr = f"min(max(0,(on/{total_frames})*(iw-iw/zoom)),iw-iw/zoom)"
            y_expr = f"min(max(0,ih*{anchor_y}-(ih/zoom*{anchor_y})),ih-ih/zoom)"
        elif direction == "pan_left":
            z_expr = "1.08"
            x_expr = f"min(max(0,(1-(on/{total_frames}))*(iw-iw/zoom)),iw-iw/zoom)"
            y_expr = f"min(max(0,ih*{anchor_y}-(ih/zoom*{anchor_y})),ih-ih/zoom)"
        else:  # zoom_in (default)
            z_expr = f"min(zoom+{zoom_step},{zoom_factor})"
            x_expr = f"min(max(0,iw*{anchor_x}-(iw/zoom*{anchor_x})),iw-iw/zoom)"
            y_expr = f"min(max(0,ih*{anchor_y}-(ih/zoom*{anchor_y})),ih-ih/zoom)"

        filter_expr = f"zoompan=z='{z_expr}':d={total_frames}:x='{x_expr}':y='{y_expr}':s=1080x1920:fps={fps}"
        logger.info(
            f"Subject-Aware Zoompan targeting {subject.subject_type} at ({subject.norm_cx:.2f}, {subject.norm_cy:.2f}) "
            f"mode={direction}, zoom={zoom_factor}"
        )
        return filter_expr


_tracker_instance = SubjectTracker()

def detect_primary_subject(image_input: Image.Image | Path | str | np.ndarray) -> SubjectBBox:
    return _tracker_instance.detect_subject(image_input)

def compute_crop_window(orig_w: int, orig_h: int, target_aspect: float = 9.0 / 16.0, subject: SubjectBBox | None = None):
    return _tracker_instance.compute_crop_window(orig_w, orig_h, target_aspect, subject)

def generate_subject_zoompan_expr(image_path: Path, target_duration: float, fps: int = 30, zoom_factor: float = 1.12, direction: str = "zoom_in") -> str:
    return _tracker_instance.generate_subject_zoompan_expr(image_path, target_duration, fps, zoom_factor, direction)
