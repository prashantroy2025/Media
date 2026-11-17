"""Independent Scene Renderer for NOVA AUTOPILOT Unified Creative Timeline.

Renders individual scenes non-destructively to 1080x1920 30fps CFR MP4 clips.
Allows single-scene replacement, regeneration, and previewing without
requiring a full project re-render.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import subprocess
from typing import Any

from PIL import Image, ImageDraw

from nova.renderer import detect_video_encoder
from nova.timeline.schema import LayerType, Scene, VideoLayer
from nova.timeline.compositions import DeepSpaceStarfieldComposition

logger = logging.getLogger("nova.timeline.scene_renderer")


class SceneRenderer:
    """Renders a single Scene independently and deterministically."""

    def __init__(self, output_dir: Path | str = "output"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.encoder = detect_video_encoder()

    def render_scene(self, scene: Scene, dest_path: Path | str | None = None, fps: int = 30) -> Path:
        """Renders the scene to an MP4 video clip."""
        if dest_path is None:
            dest_path = self.output_dir / f"scene_{scene.scene_index}_{scene.scene_id}.mp4"
        out_p = Path(dest_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)

        duration = max(0.5, scene.duration_seconds if scene.duration_seconds > 0 else (scene.duration_frames / max(1, fps)))
        logger.info(
            f"Rendering independent Scene #{scene.scene_index} ('{scene.name}', duration={duration:.2f}s, comp='{scene.composition_type}')..."
        )

        # 1. Procedural Composition Delegations via MotionDesignStudio
        if scene.composition_type and scene.composition_type not in ("none", "footage", "image"):
            from nova.timeline.motion_studio import MotionDesignStudio
            if scene.composition_type in MotionDesignStudio.list_compositions():
                comp = MotionDesignStudio.create_composition(scene.composition_type, width=1080, height=1920, fps=fps)
                comp.render_to_video(out_p, duration=duration, fps=fps)
                scene.rendered_clip_path = str(out_p)
                scene.status = "rendered"
                return out_p
            elif scene.composition_type in ("starfield", "cinematic_space", "deep_space"):
                comp = DeepSpaceStarfieldComposition(width=1080, height=1920, fps=fps)
                comp.render_to_video(out_p, duration=duration, fps=fps)
                scene.rendered_clip_path = str(out_p)
                scene.status = "rendered"
                return out_p

        # 2. Multi-Layer Video Compositing or Footage Layer Passthrough
        if scene.video_layers:
            # Sort layers by z_index
            sorted_layers = sorted(scene.video_layers, key=lambda l: l.z_index)

            # Check if primary layer is an existing valid video clip
            primary = sorted_layers[0]
            if primary.source_path and Path(primary.source_path).exists():
                src_path = Path(primary.source_path)
                if src_path.suffix.lower() in (".mp4", ".mov", ".mkv"):
                    # Passthrough / normalize clip to exact scene duration
                    cmd = [
                        "ffmpeg",
                        "-y",
                        "-i", str(src_path.resolve()),
                        "-t", f"{duration:.3f}",
                        "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1",
                        "-r", str(fps),
                        "-c:v", self.encoder,
                        "-pix_fmt", "yuv420p",
                        "-an",
                        str(out_p.resolve()),
                    ]
                    env = dict(os.environ)
                    env["PATH"] = f"/opt/homebrew/bin:{env.get('PATH', '')}"
                    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True, env=env)
                    scene.rendered_clip_path = str(out_p)
                    scene.status = "rendered"
                    return out_p

                elif src_path.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
                    # Still image Ken Burns or Parallax
                    from nova.visuals import fit_image_shot
                    fit_image_shot(src_path, out_p, duration, direction="zoom_in", fps=fps)
                    scene.rendered_clip_path = str(out_p)
                    scene.status = "rendered"
                    return out_p

        # 3. Fallback: Infer narrative-driven procedural composition via MotionDesignStudio
        logger.info(f"Scene #{scene.scene_index} had no active video layers. Rendering dynamic procedural composition fallback.")
        from nova.timeline.motion_studio import MotionDesignStudio
        comp = MotionDesignStudio.infer_composition_from_narration(scene.narration_text or "")
        comp.render_to_video(out_p, duration=duration, fps=fps)
        scene.rendered_clip_path = str(out_p)
        scene.status = "rendered"
        return out_p
