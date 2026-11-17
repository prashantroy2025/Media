"""Advanced 2.5D Parallax Engine for Nova Autopilot v9.2.

Transforms high-impact still images into dynamic 3D-perspective shots using:
- Monocular depth estimation via MiDaS ONNX (CoreML accelerated on Apple Silicon).
- Foreground/background segmentation with feathered alpha masks.
- Navier-Stokes background inpainting to heal occluded edges.
- Multi-plane perspective camera simulation (differential zoom and horizontal/vertical drift).
- Hardware-accelerated H.264 rendering to 1080x1920 30fps CFR MP4.
"""

from __future__ import annotations

import math
import subprocess
import time
from pathlib import Path
from typing import Literal

import cv2
import numpy as np
from PIL import Image

from nova.logging_setup import logger

MODEL_PATH = Path(__file__).resolve().parent.parent.parent / "models" / "midas_small.onnx"


class Parallax25DEngine:
    """Core 2.5D parallax depth animator."""

    def __init__(self, model_path: Path | None = None):
        self.model_path = model_path or MODEL_PATH
        self._session = None
        self._init_session()

    def _init_session(self):
        """Initializes ONNX runtime session with Apple Silicon CoreML acceleration."""
        if self.model_path.exists():
            try:
                import onnxruntime as ort
                self._session = ort.InferenceSession(
                    str(self.model_path),
                    providers=["CoreMLExecutionProvider", "CPUExecutionProvider"],
                )
                logger.info(f"Parallax25D Engine: Loaded MiDaS model with CoreML acceleration.")
            except Exception as e:
                logger.warning(f"Could not initialize MiDaS ONNX session: {e}. Using bilateral depth fallback.")
                self._session = None

    def estimate_depth(self, img: np.ndarray) -> np.ndarray:
        """Estimates normalized depth map [0, 255] where 255 = nearest foreground."""
        h, w = img.shape[:2]
        if self._session is not None:
            try:
                rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                resized = cv2.resize(rgb, (256, 256), interpolation=cv2.INTER_CUBIC)
                mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
                std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
                blob = ((resized / 255.0 - mean) / std).astype(np.float32)
                blob = np.transpose(blob, (2, 0, 1))[np.newaxis, :]

                in_name = self._session.get_inputs()[0].name
                out_name = self._session.get_outputs()[0].name
                depth_raw = self._session.run([out_name], {in_name: blob})[0].squeeze()

                depth_resized = cv2.resize(depth_raw, (w, h), interpolation=cv2.INTER_CUBIC)
                depth_norm = cv2.normalize(depth_resized, None, 0, 255, cv2.NORM_MINMAX, cv2.CV_8U)
                return depth_norm
            except Exception as e:
                logger.warning(f"ONNX depth estimation failed: {e}; using heuristic depth.")

        # Fallback: Saliency-guided bilateral edge depth map
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blur = cv2.bilateralFilter(gray, 9, 75, 75)
        # Center-weighted gradient ramp
        y_indices, x_indices = np.indices((h, w))
        dist_from_center = np.sqrt(((x_indices - w / 2) / (w / 2)) ** 2 + ((y_indices - h / 2) / (h / 2)) ** 2)
        dist_norm = np.clip(1.0 - dist_from_center * 0.5, 0.0, 1.0)
        heuristic_depth = (blur.astype(np.float32) * 0.5 + dist_norm * 127.0).astype(np.uint8)
        return cv2.normalize(heuristic_depth, None, 0, 255, cv2.NORM_MINMAX, cv2.CV_8U)

    def separate_layers(self, img: np.ndarray, depth_map: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Splits image into (foreground_rgba, background_bgr, fg_mask).
        
        Applies Navier-Stokes inpainting to heal occluded background regions.
        """
        h, w = img.shape[:2]
        # Depth threshold for foreground: top 35% closest
        fg_thresh = np.percentile(depth_map, 62)
        _, raw_mask = cv2.threshold(depth_map, fg_thresh, 255, cv2.THRESH_BINARY)

        # Smooth and feather the foreground mask
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
        mask_clean = cv2.morphologyEx(raw_mask, cv2.MORPH_CLOSE, kernel)
        mask_feathered = cv2.GaussianBlur(mask_clean, (21, 21), 0)

        # Generate 4-channel RGBA foreground
        b, g, r = cv2.split(img)
        fg_rgba = cv2.merge([b, g, r, mask_feathered])

        # Generate in-painted background (heal behind foreground)
        inpaint_mask = cv2.dilate(mask_clean, kernel, iterations=3)
        # Downsample for fast inpainting, then upscale
        small_img = cv2.resize(img, (w // 2, h // 2))
        small_mask = cv2.resize(inpaint_mask, (w // 2, h // 2))
        small_bg = cv2.inpaint(small_img, small_mask, 5, cv2.INPAINT_TELEA)
        bg_inpainted = cv2.resize(small_bg, (w, h), interpolation=cv2.INTER_LINEAR)

        return fg_rgba, bg_inpainted, mask_feathered

    def render_parallax_video(
        self,
        image_path: Path,
        output_path: Path,
        duration: float = 3.5,
        fps: int = 30,
        motion_style: Literal["push_in", "pull_out", "lateral_drift"] = "push_in",
    ) -> Path:
        """Renders 2.5D multi-plane parallax camera movement directly to 1080x1920 MP4."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        img = cv2.imread(str(image_path.resolve()))
        if img is None:
            raise ValueError(f"Could not read image: {image_path}")

        orig_h, orig_w = img.shape[:2]

        # Fit image to 1080x1920 canvas before parallax
        target_w, target_h = 1080, 1920
        scale = max(target_w / orig_w, target_h / orig_h)
        scaled_w = int(round(orig_w * scale))
        scaled_h = int(round(orig_h * scale))
        fitted = cv2.resize(img, (scaled_w, scaled_h), interpolation=cv2.INTER_CUBIC)

        # Center crop to 1080x1920
        x0 = (scaled_w - target_w) // 2
        y0 = (scaled_h - target_h) // 2
        canvas = fitted[y0 : y0 + target_h, x0 : x0 + target_w]

        # 1. Compute depth map
        depth = self.estimate_depth(canvas)

        # 2. Separate into layers with inpainting
        fg_rgba, bg_bgr, fg_mask = self.separate_layers(canvas, depth)

        total_frames = max(1, int(round(duration * fps)))

        # Launch FFmpeg pipe with h264_videotoolbox hardware encoder
        encoder = "h264_videotoolbox" if Path("/opt/homebrew/bin/ffmpeg").exists() else "libx264"
        cmd = [
            "/opt/homebrew/bin/ffmpeg" if Path("/opt/homebrew/bin/ffmpeg").exists() else "ffmpeg",
            "-y",
            "-f", "rawvideo",
            "-vcodec", "rawvideo",
            "-s", f"{target_w}x{target_h}",
            "-pix_fmt", "bgr24",
            "-r", str(fps),
            "-i", "-",
            "-t", str(duration),
            "-c:v", encoder,
            "-b:v", "9000k" if encoder == "h264_videotoolbox" else "crf=20",
            "-pix_fmt", "yuv420p",
            "-an",
            str(output_path.resolve()),
        ]

        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        try:
            for f in range(total_frames):
                prog = f / max(1, total_frames - 1)  # 0.0 -> 1.0

                if motion_style == "push_in":
                    # Foreground zooms faster (1.00 -> 1.08), Background zooms subtler (1.02 -> 1.04)
                    s_fg = 1.00 + 0.08 * prog
                    s_bg = 1.02 + 0.03 * prog
                    dx_fg, dy_fg = 0.0, -15.0 * prog
                    dx_bg, dy_bg = 0.0, -5.0 * prog
                elif motion_style == "pull_out":
                    s_fg = 1.08 - 0.08 * prog
                    s_bg = 1.04 - 0.03 * prog
                    dx_fg, dy_fg = 0.0, 15.0 * prog
                    dx_bg, dy_bg = 0.0, 5.0 * prog
                else:  # lateral_drift
                    s_fg = 1.04
                    s_bg = 1.02
                    dx_fg = 25.0 * (prog - 0.5)
                    dy_fg = 0.0
                    dx_bg = -12.0 * (prog - 0.5)  # Counter parallax
                    dy_bg = 0.0

                # Transform Background
                M_bg = cv2.getRotationMatrix2D((target_w / 2, target_h / 2), 0, s_bg)
                M_bg[0, 2] += dx_bg
                M_bg[1, 2] += dy_bg
                warped_bg = cv2.warpAffine(bg_bgr, M_bg, (target_w, target_h), borderMode=cv2.BORDER_REFLECT)

                # Transform Foreground
                M_fg = cv2.getRotationMatrix2D((target_w / 2, target_h / 2), 0, s_fg)
                M_fg[0, 2] += dx_fg
                M_fg[1, 2] += dy_fg
                warped_fg = cv2.warpAffine(fg_rgba, M_fg, (target_w, target_h), borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))

                # Composite Alpha
                fg_rgb = warped_fg[:, :, :3]
                alpha = (warped_fg[:, :, 3] / 255.0)[:, :, np.newaxis]
                composite = (fg_rgb * alpha + warped_bg * (1.0 - alpha)).astype(np.uint8)

                proc.stdin.write(composite.tobytes())

            proc.stdin.close()
            proc.wait()
            logger.info(f"Rendered 2.5D Parallax Shot ({motion_style}, {duration}s) -> {output_path.name}")
            return output_path
        except Exception as e:
            if proc.stdin:
                proc.stdin.close()
            proc.terminate()
            raise RuntimeError(f"Parallax rendering failed: {e}")


_parallax_engine_instance = None

def get_parallax_engine() -> Parallax25DEngine:
    global _parallax_engine_instance
    if _parallax_engine_instance is None:
        _parallax_engine_instance = Parallax25DEngine()
    return _parallax_engine_instance

def render_25d_parallax(
    image_path: Path,
    output_path: Path,
    duration: float = 3.5,
    fps: int = 30,
    motion_style: str = "push_in",
) -> Path:
    engine = get_parallax_engine()
    return engine.render_parallax_video(image_path, output_path, duration=duration, fps=fps, motion_style=motion_style)
