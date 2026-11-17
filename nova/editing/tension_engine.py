"""Editorial Tension Engine for NOVA AUTOPILOT v9.5.

Constructs an adaptive, non-linear tension curve across the video timeline:
- Determines when the video should feel:
  * Calm (reflective, grounding, expansive)
  * Curious (inquisitive, building intrigue)
  * Suspenseful (tightening anticipation, held breath)
  * Urgent (fast-paced, high information velocity)
  * Dramatic (heavy narrative weight, powerful impact)
  * Surprising (sudden spike, unexpected turn)
  * Conclusive (satisfying resolution, final release)

Directly influences:
- Shot duration
- Motion intensity
- Music intensity (ducking depth, presence)
- Sound effects (sub drops, risers, impacts, silence)
- Typography (scale, tracking, pop speed)
- Camera movement (zoom velocity, drift)
- Transition selection (dissolve vs cut vs whip vs speed ramp)

Avoids artificial constant high intensity through dynamic breathing room and contrast.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, List, Optional, Tuple

from nova.editing.narrative_arc import ArcAnalysisResult, NarrativeRole, NarrativeSegment


class TensionState(str, Enum):
    """The 7 editorial emotional tension states."""
    CALM = "calm"
    CURIOUS = "curious"
    SUSPENSEFUL = "suspenseful"
    URGENT = "urgent"
    DRAMATIC = "dramatic"
    SURPRISING = "surprising"
    CONCLUSIVE = "conclusive"


@dataclass
class TensionPoint:
    """Tension coordinate at a specific timestamp."""
    time_sec: float
    tension: float  # [0.0, 1.0]
    state: TensionState
    sentence_id: str = ""
    role: str = ""


@dataclass
class EditorialModulation:
    """Directorial parameter recommendations derived from current tension."""
    time_sec: float
    tension: float
    state: TensionState
    target_shot_duration: float   # Recommended duration in seconds
    motion_intensity: float       # [0.2, 1.0]
    music_ducking_volume: float   # [0.08, 0.28]
    sfx_intensity: str            # "minimal", "subtle", "dynamic", "maximum"
    sfx_recommended: list[str]    # Recommended SFX cues
    typography_scale: float       # Multiplier on caption font size [0.95, 1.25]
    camera_zoom_factor: float     # Ken Burns / camera zoom factor [1.04, 1.25]
    recommended_transition: str   # "dissolve", "cut", "whip", "speed_ramp", "snap_punch"


class TensionEngine:
    """Calculates adaptive tension curves and modulates directorial decisions."""

    def __init__(self, min_shot_dur: float = 1.4, max_shot_dur: float = 4.2):
        self.min_shot_dur = min_shot_dur
        self.max_shot_dur = max_shot_dur

    def build_tension_curve(
        self,
        arc: ArcAnalysisResult,
        total_duration: float,
        sentence_timings: list[Any] | None = None,
    ) -> list[TensionPoint]:
        """Constructs an ordered sequence of anchor tension points across the video."""
        n_segments = len(arc.segments)
        if n_segments == 0:
            return [
                TensionPoint(0.0, 0.5, TensionState.CURIOUS),
                TensionPoint(total_duration, 0.5, TensionState.CONCLUSIVE),
            ]

        # Calculate timestamps for each segment
        raw_points: list[tuple[float, float, str, str]] = []

        if sentence_timings and len(sentence_timings) == n_segments:
            for s, st in zip(arc.segments, sentence_timings):
                mid_t = (getattr(st, "start_time", 0.0) + getattr(st, "end_time", 0.0)) / 2.0
                raw_points.append((mid_t, s.tension_target, s.sentence_id, s.role.value))
        else:
            # Distribute proportionally
            step = total_duration / max(1, n_segments)
            for i, s in enumerate(arc.segments):
                mid_t = (i + 0.5) * step
                raw_points.append((mid_t, s.tension_target, s.sentence_id, s.role.value))

        # Anchor boundaries
        start_t = 0.0
        start_tension = arc.segments[0].tension_target
        end_t = total_duration
        end_tension = arc.segments[-1].tension_target

        points: list[TensionPoint] = []
        # Opening point
        p_start_state = self._classify_state(start_tension)
        points.append(
            TensionPoint(
                time_sec=start_t,
                tension=start_tension,
                state=p_start_state,
                sentence_id=arc.segments[0].sentence_id,
                role=arc.segments[0].role.value,
            )
        )

        prev_t = 0.0
        prev_val = start_tension
        for t, val, sid, role_str in raw_points:
            # Check for sudden surprising spikes
            if (val - prev_val) >= 0.35 and t > 2.0:
                state = TensionState.SURPRISING
            elif role_str in ("conclusion", "final_payoff"):
                state = TensionState.CONCLUSIVE
            else:
                state = self._classify_state(val)

            points.append(TensionPoint(time_sec=round(t, 3), tension=round(val, 3), state=state, sentence_id=sid, role=role_str))
            prev_t = t
            prev_val = val

        # Closing point
        points.append(
            TensionPoint(
                time_sec=round(end_t, 3),
                tension=round(end_tension, 3),
                state=TensionState.CONCLUSIVE,
                sentence_id=arc.segments[-1].sentence_id,
                role=arc.segments[-1].role.value,
            )
        )

        return points

    def evaluate_at(self, t: float, curve_points: list[TensionPoint]) -> EditorialModulation:
        """Evaluates continuous tension at time t and computes editorial modulation."""
        if not curve_points:
            return self._derive_modulation(t, 0.5, TensionState.CURIOUS)

        if t <= curve_points[0].time_sec:
            pt = curve_points[0]
            return self._derive_modulation(t, pt.tension, pt.state)

        if t >= curve_points[-1].time_sec:
            pt = curve_points[-1]
            return self._derive_modulation(t, pt.tension, pt.state)

        # Smooth Hermite / Cosine interpolation between surrounding points
        for i in range(len(curve_points) - 1):
            p1 = curve_points[i]
            p2 = curve_points[i + 1]
            if p1.time_sec <= t <= p2.time_sec:
                span = p2.time_sec - p1.time_sec
                if span <= 1e-4:
                    return self._derive_modulation(t, p2.tension, p2.state)
                # Normalized alpha
                alpha = (t - p1.time_sec) / span
                # Smooth cosine curve
                eased = 0.5 * (1.0 - math.cos(alpha * math.pi))
                cur_tension = p1.tension + (p2.tension - p1.tension) * eased

                # State classification
                if p2.state == TensionState.SURPRISING and alpha > 0.7:
                    cur_state = TensionState.SURPRISING
                elif p2.state == TensionState.CONCLUSIVE and alpha > 0.5:
                    cur_state = TensionState.CONCLUSIVE
                else:
                    cur_state = self._classify_state(cur_tension)

                return self._derive_modulation(t, cur_tension, cur_state)

        return self._derive_modulation(t, 0.5, TensionState.CURIOUS)

    def _classify_state(self, tension: float) -> TensionState:
        """Categorizes scalar tension into one of the 7 editorial states."""
        if tension < 0.28:
            return TensionState.CALM
        elif tension < 0.48:
            return TensionState.CURIOUS
        elif tension < 0.68:
            return TensionState.SUSPENSEFUL
        elif tension < 0.82:
            return TensionState.URGENT
        else:
            return TensionState.DRAMATIC

    def _derive_modulation(self, t: float, tension: float, state: TensionState) -> EditorialModulation:
        """Calculates specific editorial parameters from tension value and state."""
        clamped_t = max(0.0, min(1.0, tension))

        # 1. Shot Duration: Inversely proportional to tension
        shot_dur = self.max_shot_dur - clamped_t * (self.max_shot_dur - self.min_shot_dur)
        if state == TensionState.DRAMATIC:
            # Dramatic shots hold slightly longer for emotional weight
            shot_dur = max(2.2, shot_dur * 1.25)
        elif state == TensionState.SURPRISING:
            # Sudden fast cut
            shot_dur = self.min_shot_dur

        # 2. Motion Intensity [0.25, 1.0]
        motion_int = 0.25 + 0.75 * clamped_t

        # 3. Music Ducking Volume: Higher tension allows music to punch through more
        # In calm dialogue: 0.10. In dramatic climax: 0.24.
        music_vol = 0.09 + (0.16 * clamped_t)

        # 4. SFX Selection & Intensity
        if clamped_t >= 0.85:
            sfx_int = "maximum"
            sfx_rec = ["cinematic_impact", "sub_drop_40hz", "riser"]
        elif clamped_t >= 0.65:
            sfx_int = "dynamic"
            sfx_rec = ["whoosh_whip", "sub_impact", "high_tech_pop"]
        elif clamped_t >= 0.40:
            sfx_int = "subtle"
            sfx_rec = ["ambient_texture", "soft_whoosh"]
        else:
            sfx_int = "minimal"
            sfx_rec = ["ambient_bed"]

        # 5. Typography Scale [0.95, 1.25]
        typo_scale = 1.0 + (0.22 * (clamped_t - 0.5))

        # 6. Camera Zoom Factor [1.04, 1.22]
        cam_zoom = 1.05 + (0.16 * clamped_t)

        # 7. Transition Selection
        if state == TensionState.SURPRISING:
            trans = "cut"
        elif clamped_t >= 0.82:
            trans = "whip"
        elif clamped_t >= 0.65:
            trans = "slideleft"
        elif clamped_t <= 0.35 or state == TensionState.CONCLUSIVE:
            trans = "dissolve"
        else:
            trans = "cut"

        return EditorialModulation(
            time_sec=round(t, 3),
            tension=round(clamped_t, 3),
            state=state,
            target_shot_duration=round(shot_dur, 2),
            motion_intensity=round(motion_int, 3),
            music_ducking_volume=round(music_vol, 3),
            sfx_intensity=sfx_int,
            sfx_recommended=sfx_rec,
            typography_scale=round(typo_scale, 3),
            camera_zoom_factor=round(cam_zoom, 3),
            recommended_transition=trans,
        )
