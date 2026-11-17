"""Intelligent Creative Director Decision Layer for Nova Autopilot v9.2.

Operates prior to visual acquisition and rendering to make narrative-grounded directorial decisions:
- Selects optimal visual execution route (stock_video, parallax_25d, motion_graphic, multi_layer_still).
- Determines framing scale (macro_close_up, medium_shot, wide_vista) based on narrative concepts.
- Calibrates shot duration and pacing cadence to avoid frantic cuts.
- Positions captions dynamically away from detected subject focal zones.
- Selects broadcast transitions aligned with dramatic narrative turns.
- Designates high-impact sound design accents (whoosh, deep_impact, sub_riser).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from nova.logging_setup import logger
from nova.presets import VideoPreset


@dataclass
class DirectorialDecision:
    """Creative direction for an individual narration beat."""
    beat_index: int
    sentence_id: str
    spoken_text: str
    visual_intent: str
    recommended_route: Literal["stock_video", "parallax_25d", "motion_graphic", "multi_layer_still", "cinematic_space_environment"]
    framing: Literal["macro_close_up", "medium_shot", "wide_vista"]
    camera_movement: Literal["zoom_in", "zoom_out", "pan_to_subject", "lateral_drift", "push_in"]
    transition_in: Literal["cut", "circleopen", "dissolve", "wipeleft", "fade"]
    caption_position_y: int  # Y pixel coordinate for subtitle baseline
    sound_effect: str | None  # "whoosh_cinematic", "sub_impact", "high_tech_beep", None
    justification: str
    narrative_role: str = "context_establishment"
    visual_intensity: float = 0.5
    pacing_weight: float = 1.0
    tension_state: str = "curious"
    composition_style: str = ""
    animation_intensity: float = 0.5
    editorial_technique: str = "cut"
    color_match: bool = True


class CreativeDirector:
    """Pre-rendering aesthetic and storytelling orchestration engine."""

    def __init__(self, preset: VideoPreset | None = None, niche: str = "space_science"):
        self.preset = preset
        self.niche = niche

    def direct_scene_plan(
        self,
        sentences: list[dict[str, Any]],
        total_duration: float,
        reference_storyboard: Any | None = None,
    ) -> list[DirectorialDecision]:
        """Translates raw script sentences into an intelligent directorial execution plan."""
        from nova.editing.narrative_arc import NarrativeArcAnalyzer
        from nova.editing.tension_engine import TensionEngine
        from nova.editing.techniques import ProfessionalEditingEngine

        arc_analyzer = NarrativeArcAnalyzer(niche=self.niche)
        arc = arc_analyzer.analyze(sentences, total_duration=total_duration)
        tension_engine = TensionEngine()
        tension_curve = tension_engine.build_tension_curve(arc, total_duration=total_duration)
        editing_engine = ProfessionalEditingEngine()

        decisions: list[DirectorialDecision] = []
        n_beats = len(sentences)

        last_route = None
        consecutive_same_route = 0
        parallax_budget = 2  # Limit 2.5D parallax to 1-2 hero moments per video for maximum impact

        for idx, s in enumerate(sentences):
            text = s.get("text", "")
            lower_text = text.lower()
            v_intent = s.get("visual_intent", {})
            intent_text = v_intent.get("main_subject", "") if isinstance(v_intent, dict) else str(v_intent)

            # Retrieve v9.5 narrative arc & tension attributes
            seg = arc.segments[idx] if idx < len(arc.segments) else None
            role = seg.role.value if seg else s.get("role", "context")
            t_eval = (idx + 0.5) * (total_duration / max(1, n_beats))
            mod = tension_engine.evaluate_at(t_eval, tension_curve)

            # 1. Determine Framing based on concepts
            if any(k in lower_text for k in ["spoon", "tiny", "atom", "nuclei", "microchip", "cell", "crystal", "needle", "hand"]):
                framing = "macro_close_up"
            elif any(k in lower_text for k in ["sky", "galaxy", "universe", "cosmos", "ocean", "landscape", "earth", "horizon"]):
                framing = "wide_vista"
            else:
                framing = "medium_shot"

            # 2. Determine Visual Route
            is_space_env = any(k in lower_text or k in intent_text.lower() for k in [
                "sparse star", "stars pass", "empty space", "immense", "never touch", "almost none",
                "star systems", "galaxy collision", "deep space", "light-years", "stars will"
            ])

            # Detect quantitative stats / comparisons -> Motion Graphic
            has_percent = "%" in text or "percent" in lower_text
            has_comparison = any(k in lower_text for k in ["compare", "versus", "against", "assume"])
            has_complex_metric = any(k in lower_text for k in ["billion", "trillion", "million", "miles per hour", "speed"])

            if is_space_env:
                route = "cinematic_space_environment"
                justification = "Cosmic distance and stellar passage communicated via multi-depth perspective starfield."
            elif (has_percent or has_comparison or (has_complex_metric and idx > 0)) and last_route != "motion_graphic":
                route = "motion_graphic"
                justification = "Complex quantitative statistic or comparison communicates best via kinetic infographic."
            # Hero portrait or singular artifact -> 2.5D Parallax
            elif (
                parallax_budget > 0
                and idx in (0, n_beats - 2)
                and any(k in lower_text for k in ["spoon", "person", "researcher", "telescope", "star", "artifact", "pyramid", "hand"])
                and last_route != "parallax_25d"
            ):
                route = "parallax_25d"
                parallax_budget -= 1
                justification = "Hero subject benefits from 2.5D depth separation and parallax camera push."
            # High action / cosmic movement -> Stock Video
            elif any(k in lower_text for k in ["collide", "racing", "spinning", "flying", "exploding", "streaming", "drift", "spiral", "flowing"]):
                route = "stock_video"
                justification = "Dynamic physical motion best represented by authentic moving video footage."
            else:
                # Video-first preference, alternating with multi-layer Ken Burns
                if last_route == "stock_video" and consecutive_same_route >= 2:
                    route = "multi_layer_still"
                    justification = "Visual cadence pacing: alternating moving footage with a focused multi-layer Ken Burns shot."
                else:
                    route = "stock_video"
                    justification = "Standard high-retention video-first coverage."

            # Update route tracking
            if route == last_route:
                consecutive_same_route += 1
            else:
                consecutive_same_route = 1
            last_route = route

            # 3. Transition Selection matching dramatic shift
            if idx == 0:
                trans = "cut"
            elif role in ("turn", "twist"):
                trans = "circleopen"
            elif role == "climax":
                trans = "wipeleft"
            elif role == "resolution":
                trans = "dissolve"
            else:
                trans = "fade" if idx % 2 == 0 else "dissolve"

            # 4. Sound Effect Selection
            sfx = None
            if idx == 0:
                sfx = "whoosh_cinematic"
            elif role in ("turn", "climax"):
                sfx = "sub_impact"
            elif route == "motion_graphic":
                sfx = "high_tech_beep"

            # 5. Caption Placement: Default to bottom safe-zone (1380), lift if macro close-up
            cap_y = 1380 if framing != "macro_close_up" else 1340

            # 6. Camera Movement
            if route == "parallax_25d":
                cam_move = "push_in"
            elif framing == "wide_vista":
                cam_move = "zoom_in"
            elif framing == "macro_close_up":
                cam_move = "zoom_out"
            else:
                cam_move = "pan_to_subject"

            decisions.append(
                DirectorialDecision(
                    beat_index=idx,
                    sentence_id=s.get("id", f"S{idx+1}"),
                    spoken_text=text,
                    visual_intent=intent_text,
                    recommended_route=route,
                    framing=framing,
                    camera_movement=cam_move,
                    transition_in=trans,
                    caption_position_y=cap_y,
                    sound_effect=sfx,
                    justification=justification,
                    narrative_role=role,
                    visual_intensity=seg.visual_intensity if seg else 0.5,
                    pacing_weight=seg.pacing_weight if seg else 1.0,
                    tension_state=mod.state.value,
                    composition_style=seg.composition_style if seg else "",
                    animation_intensity=seg.animation_intensity if seg else 0.5,
                    editorial_technique="j_cut" if role in ("important_revelation", "curiosity_building") else "cut",
                    color_match=True,
                )
            )

        logger.info(f"CreativeDirector orchestrated {len(decisions)} directorial decisions (routes: {[d.recommended_route for d in decisions]})")
        return decisions
