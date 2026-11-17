"""Backward compatibility layer bridging legacy TimelinePlan to UnifiedProject.

Guarantees 100% test suite and pipeline compatibility with v7/v8/v9 callers
while enabling bidirectional conversion to the v9.3 Unified Creative Timeline.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import math
from pathlib import Path
from typing import Any

from nova.beats import Beat, BeatPlanner, VideoShotPlan
from nova.timeline.schema import (
    LayerTransform,
    LayerType,
    Scene,
    Timecode,
    UnifiedProject,
    VideoLayer,
)


@dataclass
class ShotPlan:
    """A single continuous visual shot within a sentence segment (Legacy schema)."""

    shot_index: int
    sentence_index: int
    sentence_id: str
    sentence_text: str
    start_time: float
    end_time: float
    duration: float
    query: str
    shot_type: str = "medium"
    on_screen_label: str | None = None
    chosen_asset_id: str = ""
    provider: str = ""
    media_type: str = "video"
    fit_method: str = "trim"
    asset_file: str = ""
    normalized_shot_file: str = ""
    relevance_score: float = 100.0
    is_fallback_card: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TimelinePlan:
    """The master timeline plan mapping 0 -> audio_duration with zero gaps."""

    total_duration: float
    fps: int = 30
    shots: list[ShotPlan] = field(default_factory=list)
    script_id: int = 0
    niche: str = "ai_tech"

    def to_dict(self) -> dict[str, Any]:
        return {
            "script_id": self.script_id,
            "niche": self.niche,
            "total_duration": round(self.total_duration, 3),
            "fps": self.fps,
            "total_shots": len(self.shots),
            "longest_shot_duration": round(max((s.duration for s in self.shots), default=0.0), 3),
            "shortest_shot_duration": round(min((s.duration for s in self.shots), default=0.0), 3),
            "shots": [asdict(s) for s in self.shots],
        }

    def save_json(self, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return output_path

    def to_unified_project(self) -> UnifiedProject:
        """Converts legacy TimelinePlan into a validated UnifiedProject."""
        total_frames = Timecode.seconds_to_frames(self.total_duration, self.fps)
        scenes: list[Scene] = []

        cur_frame = 0
        for s in self.shots:
            s_frames = Timecode.seconds_to_frames(s.duration, self.fps)
            e_frame = cur_frame + s_frames

            # Map legacy media_type to layer
            layer_t = LayerType.FOOTAGE.value
            comp_type = ""
            combined_text = f"{s.query.lower()} {s.sentence_text.lower()}"
            if any(k in combined_text for k in ("starfield", "sparse star", "stars passing", "space collision", "deep space")):
                comp_type = "starfield"
                layer_t = LayerType.COMPOSITION.value
            elif s.media_type == "image":
                layer_t = LayerType.IMAGE.value
            elif s.media_type == "procedural_card":
                layer_t = LayerType.MOTION_GRAPHIC.value

            layer = VideoLayer(
                layer_id=f"layer_{s.shot_index}_0",
                name=f"Visual Asset Shot #{s.shot_index}",
                layer_type=layer_t,
                z_index=0,
                source_path=s.normalized_shot_file or s.asset_file or None,
                transform=LayerTransform(),
                clip_in_frame=0,
                clip_out_frame=s_frames,
                metadata=s.metadata,
            )

            scenes.append(
                Scene(
                    scene_id=f"scene_{s.shot_index}_{s.sentence_id}",
                    scene_index=s.shot_index,
                    name=f"Scene {s.shot_index}: {s.sentence_text[:30]}",
                    start_frame=cur_frame,
                    end_frame=e_frame,
                    duration_frames=s_frames,
                    duration_seconds=s.duration,
                    narration_text=s.sentence_text,
                    visual_intent=s.query,
                    video_layers=[layer],
                    composition_type=comp_type,
                    rendered_clip_path=s.normalized_shot_file or None,
                    status="rendered" if s.normalized_shot_file else "draft",
                    metadata={
                        "legacy_shot": asdict(s),
                        "shot_type": s.shot_type,
                        "niche": self.niche,
                    },
                )
            )
            cur_frame = e_frame

        return UnifiedProject(
            project_id=f"proj_{self.script_id}",
            title=f"Video #{self.script_id} Production Project",
            schema_version="9.3",
            fps=self.fps,
            width=1080,
            height=1920,
            duration_frames=cur_frame,
            duration_seconds=self.total_duration,
            scenes=scenes,
            metadata={"script_id": self.script_id, "niche": self.niche},
        )


class TimelineBuilder:
    """Builds a frame-accurate, gapless multi-shot timeline from sentence timings."""

    def __init__(self, target_shot_min: float = 2.0, target_shot_max: float = 3.8, fps: int = 30):
        self.target_shot_min = target_shot_min
        self.target_shot_max = target_shot_max
        self.fps = fps

    def build_timeline(
        self,
        sentence_timings: list[Any],
        total_duration: float,
        sentences_data: list[dict[str, Any]] | None = None,
        script_id: int = 0,
        niche: str = "ai_tech",
        word_timings: list[Any] | None = None,
        tier: str = "tier_a",
        shot_plan: VideoShotPlan | None = None,
    ) -> TimelinePlan:
        """Constructs a gapless sequence of semantic 1.8s - 3.8s beats covering 0 -> total_duration."""
        angle_sequence = ["wide", "close_up", "medium", "macro"]
        sentences_data = sentences_data or []

        if shot_plan is None:
            shot_plan = BeatPlanner.plan_video_beats(
                sentence_timings=sentence_timings,
                word_timings=word_timings or [],
                sentences_data=sentences_data,
                video_id=script_id,
                script_id=script_id,
                total_duration=total_duration,
                niche=niche,
                tier=tier,
            )

        shots: list[ShotPlan] = []
        for beat in shot_plan.beats:
            shot_type = angle_sequence[beat.beat_index % len(angle_sequence)]
            q = beat.search_queries[0] if beat.search_queries else beat.visual_intent
            rec_route = getattr(beat, "recommended_visual_route", "stock_footage")
            shots.append(
                ShotPlan(
                    shot_index=beat.beat_index,
                    sentence_index=beat.sentence_index,
                    sentence_id=beat.sentence_id,
                    sentence_text=beat.spoken_text,
                    start_time=beat.start_time,
                    end_time=beat.end_time,
                    duration=beat.duration,
                    query=q,
                    shot_type=shot_type,
                    on_screen_label=None,
                    metadata={
                        "beat": beat.to_dict(),
                        "recommended_visual_route": rec_route,
                        "niche": niche,
                        "tier": tier,
                    },
                )
            )

        return TimelinePlan(
            total_duration=total_duration,
            fps=self.fps,
            shots=shots,
            script_id=script_id,
            niche=niche,
        )
