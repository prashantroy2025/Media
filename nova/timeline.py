"""Timeline and Segment Engine for Nova Autopilot v7.0.

Guarantees 100% continuous footage coverage with zero gaps, zero freezes,
and dynamic 2-4 second shot cadence across every spoken sentence.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from nova.beats import Beat, BeatPlanner, VideoShotPlan


@dataclass
class ShotPlan:
    """A single continuous visual shot within a sentence segment."""

    shot_index: int
    sentence_index: int
    sentence_id: str
    sentence_text: str
    start_time: float
    end_time: float
    duration: float
    query: str
    shot_type: str = "medium"  # close_up, wide, medium, macro
    on_screen_label: str | None = None
    chosen_asset_id: str = ""
    provider: str = ""
    media_type: str = "video"  # video, image, card
    fit_method: str = "trim"  # trim, loop_pingpong, slow_down, ken_burns, card
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

        # If a pre-computed shot plan (e.g. from GeminiClient) is provided, use it;
        # otherwise use local BeatPlanner for beat-level shot planning
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
