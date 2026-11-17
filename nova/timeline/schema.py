"""Unified Creative Timeline Schema for NOVA AUTOPILOT v9.3.

Supports:
- Frame-accurate timing (30fps default, timecode conversions).
- Multi-layer video tracks (z-index, transform, blend mode, opacity).
- Multi-track audio (voiceover, ducked background music, SFX accents).
- Keyframe animation tracks (linear, ease-in, ease-out, ease-in-out, cubic, bezier).
- Non-destructive independent scene editing and scene-level rendering.
- Reusable compositions (starfield, 2.5D parallax, motion graphics).
- Validated serialization, persistence, and restoration.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import json
import math
from pathlib import Path
from typing import Any, Union


class Timecode:
    """Frame-accurate conversions between frames and seconds."""

    @staticmethod
    def frames_to_seconds(frame: int, fps: int = 30) -> float:
        return round(frame / max(1, fps), 4)

    @staticmethod
    def seconds_to_frames(seconds: float, fps: int = 30) -> int:
        return int(round(seconds * fps))

    @staticmethod
    def format_timecode(frame: int, fps: int = 30) -> str:
        """Formats frames into SMPTE-like HH:MM:SS:FF."""
        total_seconds = frame / max(1, fps)
        hrs = int(total_seconds // 3600)
        mins = int((total_seconds % 3600) // 60)
        secs = int(total_seconds % 60)
        rem_frames = frame % fps
        return f"{hrs:02d}:{mins:02d}:{secs:02d}:{rem_frames:02d}"


class EasingType(str, Enum):
    LINEAR = "linear"
    EASE_IN = "ease_in"
    EASE_OUT = "ease_out"
    EASE_IN_OUT = "ease_in_out"
    EASE_OUT_CUBIC = "ease_out_cubic"
    BEZIER = "bezier"


def apply_easing(t: float, easing: str | EasingType) -> float:
    """Maps t in [0.0, 1.0] through the selected easing curve."""
    t = max(0.0, min(1.0, float(t)))
    easing_str = easing.value if isinstance(easing, EasingType) else str(easing).lower()

    if easing_str == "linear":
        return t
    elif easing_str == "ease_in":
        return t * t
    elif easing_str == "ease_out":
        return t * (2.0 - t)
    elif easing_str == "ease_in_out":
        return 0.5 * (1.0 - math.cos(t * math.pi))
    elif easing_str == "ease_out_cubic":
        return 1.0 - math.pow(1.0 - t, 3)
    elif easing_str == "bezier":
        # Standard smooth cubic bezier approximation
        return t * t * (3.0 - 2.0 * t)
    return t


@dataclass
class Keyframe:
    """A single keyframe at a specific frame index."""

    frame: int
    property_name: str
    value: Union[float, tuple[float, ...], list[float], str]
    easing: str = EasingType.EASE_IN_OUT.value
    time_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame": self.frame,
            "property_name": self.property_name,
            "value": self.value,
            "easing": self.easing,
            "time_seconds": round(self.time_seconds, 4),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Keyframe:
        return cls(
            frame=int(d["frame"]),
            property_name=str(d["property_name"]),
            value=d["value"],
            easing=str(d.get("easing", EasingType.EASE_IN_OUT.value)),
            time_seconds=float(d.get("time_seconds", 0.0)),
        )


@dataclass
class KeyframeTrack:
    """Manages an ordered sequence of keyframes and interpolates values."""

    property_name: str
    keyframes: list[Keyframe] = field(default_factory=list)

    def add_keyframe(self, frame: int, value: Any, easing: str = "ease_in_out", fps: int = 30) -> None:
        kf = Keyframe(
            frame=frame,
            property_name=self.property_name,
            value=value,
            easing=easing,
            time_seconds=Timecode.frames_to_seconds(frame, fps),
        )
        self.keyframes.append(kf)
        self.keyframes.sort(key=lambda k: k.frame)

    def evaluate(self, frame: int, default: Any = 0.0) -> Any:
        if not self.keyframes:
            return default
        if len(self.keyframes) == 1 or frame <= self.keyframes[0].frame:
            return self.keyframes[0].value
        if frame >= self.keyframes[-1].frame:
            return self.keyframes[-1].value

        for i in range(len(self.keyframes) - 1):
            k1 = self.keyframes[i]
            k2 = self.keyframes[i + 1]
            if k1.frame <= frame <= k2.frame:
                span = k2.frame - k1.frame
                if span <= 0:
                    return k2.value
                t = (frame - k1.frame) / span
                eased_t = apply_easing(t, k2.easing)

                v1, v2 = k1.value, k2.value
                if isinstance(v1, (int, float)) and isinstance(v2, (int, float)):
                    return v1 + (v2 - v1) * eased_t
                elif isinstance(v1, (list, tuple)) and isinstance(v2, (list, tuple)):
                    return [
                        v1[j] + (v2[j] - v1[j]) * eased_t
                        for j in range(min(len(v1), len(v2)))
                    ]
                return v1 if eased_t < 0.5 else v2

        return default


@dataclass
class LayerTransform:
    """2D spatial and optical transform for a layer with keyframe tracks."""

    x: float = 540.0
    y: float = 960.0
    scale_x: float = 1.0
    scale_y: float = 1.0
    rotation: float = 0.0
    opacity: float = 1.0
    anchor_x: float = 0.5
    anchor_y: float = 0.5
    keyframes: list[Keyframe] = field(default_factory=list)

    def evaluate_at_frame(self, frame: int) -> LayerTransform:
        if not self.keyframes:
            return self

        tracks: dict[str, KeyframeTrack] = {}
        for kf in self.keyframes:
            if kf.property_name not in tracks:
                tracks[kf.property_name] = KeyframeTrack(kf.property_name)
            tracks[kf.property_name].keyframes.append(kf)

        for track in tracks.values():
            track.keyframes.sort(key=lambda k: k.frame)

        eval_x = tracks["x"].evaluate(frame, self.x) if "x" in tracks else self.x
        eval_y = tracks["y"].evaluate(frame, self.y) if "y" in tracks else self.y
        eval_sx = tracks["scale_x"].evaluate(frame, self.scale_x) if "scale_x" in tracks else self.scale_x
        eval_sy = tracks["scale_y"].evaluate(frame, self.scale_y) if "scale_y" in tracks else self.scale_y
        eval_rot = tracks["rotation"].evaluate(frame, self.rotation) if "rotation" in tracks else self.rotation
        eval_op = tracks["opacity"].evaluate(frame, self.opacity) if "opacity" in tracks else self.opacity

        return LayerTransform(
            x=float(eval_x),
            y=float(eval_y),
            scale_x=float(eval_sx),
            scale_y=float(eval_sy),
            rotation=float(eval_rot),
            opacity=float(eval_op),
            anchor_x=self.anchor_x,
            anchor_y=self.anchor_y,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "x": self.x,
            "y": self.y,
            "scale_x": self.scale_x,
            "scale_y": self.scale_y,
            "rotation": self.rotation,
            "opacity": self.opacity,
            "anchor_x": self.anchor_x,
            "anchor_y": self.anchor_y,
            "keyframes": [kf.to_dict() for kf in self.keyframes],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> LayerTransform:
        return cls(
            x=float(d.get("x", 540.0)),
            y=float(d.get("y", 960.0)),
            scale_x=float(d.get("scale_x", 1.0)),
            scale_y=float(d.get("scale_y", 1.0)),
            rotation=float(d.get("rotation", 0.0)),
            opacity=float(d.get("opacity", 1.0)),
            anchor_x=float(d.get("anchor_x", 0.5)),
            anchor_y=float(d.get("anchor_y", 0.5)),
            keyframes=[Keyframe.from_dict(k) for k in d.get("keyframes", [])],
        )


class BlendMode(str, Enum):
    NORMAL = "normal"
    SCREEN = "screen"
    MULTIPLY = "multiply"
    ADD = "add"
    OVERLAY = "overlay"


class LayerType(str, Enum):
    FOOTAGE = "footage"
    IMAGE = "image"
    PARALLAX_25D = "parallax_25d"
    COMPOSITION = "composition"
    MOTION_GRAPHIC = "motion_graphic"
    PARTICLE = "particle"
    SOLID = "solid"
    TEXT = "text"
    OVERLAY = "overlay"


@dataclass
class VideoLayer:
    """A single visual layer within a multi-layer scene composition."""

    layer_id: str
    name: str
    layer_type: str = LayerType.FOOTAGE.value
    z_index: int = 0
    source_path: str | None = None
    opacity: float = 1.0
    blend_mode: str = BlendMode.NORMAL.value
    transform: LayerTransform = field(default_factory=LayerTransform)
    clip_in_frame: int = 0
    clip_out_frame: int = 0
    visible: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "layer_id": self.layer_id,
            "name": self.name,
            "layer_type": self.layer_type,
            "z_index": self.z_index,
            "source_path": self.source_path,
            "opacity": self.opacity,
            "blend_mode": self.blend_mode,
            "transform": self.transform.to_dict(),
            "clip_in_frame": self.clip_in_frame,
            "clip_out_frame": self.clip_out_frame,
            "visible": self.visible,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> VideoLayer:
        return cls(
            layer_id=str(d["layer_id"]),
            name=str(d["name"]),
            layer_type=str(d.get("layer_type", LayerType.FOOTAGE.value)),
            z_index=int(d.get("z_index", 0)),
            source_path=d.get("source_path"),
            opacity=float(d.get("opacity", 1.0)),
            blend_mode=str(d.get("blend_mode", BlendMode.NORMAL.value)),
            transform=LayerTransform.from_dict(d.get("transform", {})),
            clip_in_frame=int(d.get("clip_in_frame", 0)),
            clip_out_frame=int(d.get("clip_out_frame", 0)),
            visible=bool(d.get("visible", True)),
            metadata=d.get("metadata", {}),
        )


class AudioTrackType(str, Enum):
    VOICE = "voice"
    MUSIC = "music"
    SFX = "sfx"
    AMBIENT = "ambient"


@dataclass
class AudioClip:
    """An audio segment placed on an audio track."""

    clip_id: str
    name: str
    source_path: str
    start_frame: int
    duration_frames: int
    volume: float = 1.0
    volume_keyframes: list[Keyframe] = field(default_factory=list)
    ducking_profile: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "clip_id": self.clip_id,
            "name": self.name,
            "source_path": self.source_path,
            "start_frame": self.start_frame,
            "duration_frames": self.duration_frames,
            "volume": self.volume,
            "volume_keyframes": [kf.to_dict() for kf in self.volume_keyframes],
            "ducking_profile": self.ducking_profile,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AudioClip:
        return cls(
            clip_id=str(d["clip_id"]),
            name=str(d["name"]),
            source_path=str(d["source_path"]),
            start_frame=int(d["start_frame"]),
            duration_frames=int(d["duration_frames"]),
            volume=float(d.get("volume", 1.0)),
            volume_keyframes=[Keyframe.from_dict(k) for k in d.get("volume_keyframes", [])],
            ducking_profile=d.get("ducking_profile"),
        )


@dataclass
class AudioTrack:
    """A master audio track containing sequential or layered clips."""

    track_id: str
    name: str
    track_type: str = AudioTrackType.VOICE.value
    volume: float = 1.0
    muted: bool = False
    clips: list[AudioClip] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "track_id": self.track_id,
            "name": self.name,
            "track_type": self.track_type,
            "volume": self.volume,
            "muted": self.muted,
            "clips": [c.to_dict() for c in self.clips],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AudioTrack:
        return cls(
            track_id=str(d["track_id"]),
            name=str(d["name"]),
            track_type=str(d.get("track_type", AudioTrackType.VOICE.value)),
            volume=float(d.get("volume", 1.0)),
            muted=bool(d.get("muted", False)),
            clips=[AudioClip.from_dict(c) for c in d.get("clips", [])],
        )


@dataclass
class Scene:
    """An independent, frame-accurate scene in the Unified Timeline."""

    scene_id: str
    scene_index: int
    name: str
    start_frame: int
    end_frame: int
    duration_frames: int
    duration_seconds: float
    narration_text: str = ""
    visual_intent: str = ""
    video_layers: list[VideoLayer] = field(default_factory=list)
    audio_clips: list[AudioClip] = field(default_factory=list)
    transition_in: dict[str, Any] = field(default_factory=dict)
    transition_out: dict[str, Any] = field(default_factory=dict)
    composition_type: str = ""
    composition_params: dict[str, Any] = field(default_factory=dict)
    rendered_clip_path: str | None = None
    status: str = "draft"  # "draft", "rendered", "locked"
    narrative_role: str = ""
    visual_intensity: float = 0.5
    tension_state: str = "curious"
    camera_dynamics: str = "pan_to_subject"
    color_grading_filter: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def set_transition_in(self, trans: Any) -> None:
        """Sets transition in with a dict or TransitionDescriptor."""
        if hasattr(trans, "to_dict"):
            self.transition_in = trans.to_dict()
        elif isinstance(trans, dict):
            self.transition_in = trans
        elif isinstance(trans, str):
            self.transition_in = {"type": trans, "duration": 0.3}

    def set_transition_out(self, trans: Any) -> None:
        """Sets transition out with a dict or TransitionDescriptor."""
        if hasattr(trans, "to_dict"):
            self.transition_out = trans.to_dict()
        elif isinstance(trans, dict):
            self.transition_out = trans
        elif isinstance(trans, str):
            self.transition_out = {"type": trans, "duration": 0.3}

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "scene_index": self.scene_index,
            "name": self.name,
            "start_frame": self.start_frame,
            "end_frame": self.end_frame,
            "duration_frames": self.duration_frames,
            "duration_seconds": round(self.duration_seconds, 3),
            "narration_text": self.narration_text,
            "visual_intent": self.visual_intent,
            "video_layers": [l.to_dict() for l in self.video_layers],
            "audio_clips": [c.to_dict() for c in self.audio_clips],
            "transition_in": self.transition_in,
            "transition_out": self.transition_out,
            "composition_type": self.composition_type,
            "composition_params": self.composition_params,
            "rendered_clip_path": self.rendered_clip_path,
            "status": self.status,
            "narrative_role": self.narrative_role,
            "visual_intensity": round(self.visual_intensity, 3),
            "tension_state": self.tension_state,
            "camera_dynamics": self.camera_dynamics,
            "color_grading_filter": self.color_grading_filter,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Scene:
        return cls(
            scene_id=str(d["scene_id"]),
            scene_index=int(d["scene_index"]),
            name=str(d["name"]),
            start_frame=int(d["start_frame"]),
            end_frame=int(d["end_frame"]),
            duration_frames=int(d["duration_frames"]),
            duration_seconds=float(d.get("duration_seconds", 0.0)),
            narration_text=str(d.get("narration_text", "")),
            visual_intent=str(d.get("visual_intent", "")),
            video_layers=[VideoLayer.from_dict(l) for l in d.get("video_layers", [])],
            audio_clips=[AudioClip.from_dict(c) for c in d.get("audio_clips", [])],
            transition_in=d.get("transition_in", {}),
            transition_out=d.get("transition_out", {}),
            composition_type=str(d.get("composition_type", "")),
            composition_params=d.get("composition_params", {}),
            rendered_clip_path=d.get("rendered_clip_path"),
            status=str(d.get("status", "draft")),
            narrative_role=str(d.get("narrative_role", "")),
            visual_intensity=float(d.get("visual_intensity", 0.5)),
            tension_state=str(d.get("tension_state", "curious")),
            camera_dynamics=str(d.get("camera_dynamics", "pan_to_subject")),
            color_grading_filter=d.get("color_grading_filter"),
            metadata=d.get("metadata", {}),
        )


@dataclass
class UnifiedProject:
    """The master validated Project Schema for NOVA AUTOPILOT v9.3."""

    project_id: str
    title: str
    schema_version: str = "9.3"
    fps: int = 30
    width: int = 1080
    height: int = 1920
    duration_frames: int = 0
    duration_seconds: float = 0.0
    scenes: list[Scene] = field(default_factory=list)
    audio_tracks: list[AudioTrack] = field(default_factory=list)
    global_overlays: list[VideoLayer] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> list[str]:
        """Validates project integrity against timeline schema rules."""
        errors: list[str] = []
        if self.width <= 0 or self.height <= 0:
            errors.append(f"Invalid dimensions: {self.width}x{self.height}")
        if self.fps <= 0:
            errors.append(f"Invalid FPS: {self.fps}")

        cur_frame = 0
        for i, sc in enumerate(self.scenes):
            if sc.start_frame != cur_frame:
                errors.append(
                    f"Scene #{sc.scene_index} timing discontinuity: expected start frame {cur_frame}, got {sc.start_frame}"
                )
            if sc.end_frame <= sc.start_frame:
                errors.append(f"Scene #{sc.scene_index} has non-positive duration ({sc.start_frame} -> {sc.end_frame})")
            cur_frame = sc.end_frame

        if cur_frame != self.duration_frames:
            errors.append(
                f"Project duration mismatch: scenes sum to {cur_frame} frames, project duration is {self.duration_frames}"
            )

        return errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "title": self.title,
            "schema_version": self.schema_version,
            "fps": self.fps,
            "width": self.width,
            "height": self.height,
            "duration_frames": self.duration_frames,
            "duration_seconds": round(self.duration_seconds, 3),
            "scenes_count": len(self.scenes),
            "scenes": [s.to_dict() for s in self.scenes],
            "audio_tracks": [t.to_dict() for t in self.audio_tracks],
            "global_overlays": [o.to_dict() for o in self.global_overlays],
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> UnifiedProject:
        proj = cls(
            project_id=str(d["project_id"]),
            title=str(d.get("title", "Untitled Project")),
            schema_version=str(d.get("schema_version", "9.3")),
            fps=int(d.get("fps", 30)),
            width=int(d.get("width", 1080)),
            height=int(d.get("height", 1920)),
            duration_frames=int(d.get("duration_frames", 0)),
            duration_seconds=float(d.get("duration_seconds", 0.0)),
            scenes=[Scene.from_dict(s) for s in d.get("scenes", [])],
            audio_tracks=[AudioTrack.from_dict(t) for t in d.get("audio_tracks", [])],
            global_overlays=[VideoLayer.from_dict(o) for o in d.get("global_overlays", [])],
            metadata=d.get("metadata", {}),
        )
        val_errs = proj.validate()
        if val_errs:
            # Auto-align project duration if only duration_frames was unset
            if len(val_errs) == 1 and "Project duration mismatch" in val_errs[0]:
                calc_frames = sum(s.duration_frames for s in proj.scenes)
                proj.duration_frames = calc_frames
                proj.duration_seconds = Timecode.frames_to_seconds(calc_frames, proj.fps)
        return proj

    def save_project(self, path: Path | str) -> Path:
        """Persists the validated timeline project to disk as JSON."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return p

    @classmethod
    def load_project(cls, path: Path | str) -> UnifiedProject:
        """Restores a project from disk and validates its schema."""
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Project file not found: {p}")
        data = json.loads(p.read_text(encoding="utf-8"))
        return cls.from_dict(data)
