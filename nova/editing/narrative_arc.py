"""Narrative Arc Intelligence Analyzer for NOVA AUTOPILOT v9.5.

Evaluates narrative progression, pacing cadence, and dramatic structure across narration segments.
Automatically identifies:
- Opening hook
- Context establishment
- Curiosity building
- Important revelations
- Emotional peaks
- Climax
- Conclusion
- Final payoff

Assigns each segment a narrative role, visual intensity, pacing weight, composition guidance,
animation intensity, camera dynamics, and tension target.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, List, Optional


class NarrativeRole(str, Enum):
    """The 8 canonical narrative roles in professional video editing."""
    OPENING_HOOK = "opening_hook"
    CONTEXT_ESTABLISHMENT = "context_establishment"
    CURIOSITY_BUILDING = "curiosity_building"
    IMPORTANT_REVELATION = "important_revelation"
    EMOTIONAL_PEAK = "emotional_peak"
    CLIMAX = "climax"
    CONCLUSION = "conclusion"
    FINAL_PAYOFF = "final_payoff"


@dataclass
class NarrativeSegment:
    """Directorial and editorial intelligence profile for a single narration beat."""
    index: int
    sentence_id: str
    spoken_text: str
    role: NarrativeRole
    visual_intensity: float  # [0.0, 1.0]
    pacing_weight: float     # Multiplier on base shot duration (e.g. 0.8 = tighter, 1.25 = expansive)
    composition_style: str   # Recommended visual composition
    animation_intensity: float  # [0.0, 1.0]
    camera_dynamics: str     # Camera movement style
    sound_accent: str | None # Recommended SFX accent
    tension_target: float    # Desired emotional tension [0.0, 1.0]
    justification: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "sentence_id": self.sentence_id,
            "spoken_text": self.spoken_text,
            "role": self.role.value,
            "visual_intensity": round(self.visual_intensity, 3),
            "pacing_weight": round(self.pacing_weight, 3),
            "composition_style": self.composition_style,
            "animation_intensity": round(self.animation_intensity, 3),
            "camera_dynamics": self.camera_dynamics,
            "sound_accent": self.sound_accent,
            "tension_target": round(self.tension_target, 3),
            "justification": self.justification,
        }


@dataclass
class ArcAnalysisResult:
    """Complete narrative analysis for a video project."""
    segments: list[NarrativeSegment]
    dominant_arc_type: str  # e.g., "revelation_driven", "suspense_build", "epic_spectacle"
    peak_segment_index: int
    average_intensity: float
    total_segments: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "dominant_arc_type": self.dominant_arc_type,
            "peak_segment_index": self.peak_segment_index,
            "average_intensity": round(self.average_intensity, 3),
            "total_segments": self.total_segments,
            "segments": [s.to_dict() for s in self.segments],
        }


# Lexical dictionaries for semantic detection
REVELATION_MARKERS = [
    "surprisingly", "in reality", "the truth is", "turns out", "secret",
    "yet", "however", "almost none", "never touch", "actually", "hidden",
    "unseen", "contrary", "instead", "nobody expected", "myth", "real reason",
    "astonishingly", "mind-blowing", "we were wrong"
]

CURIOSITY_MARKERS = [
    "why", "how", "what if", "imagine", "could it be", "behind the scenes",
    "unknown", "?", "puzzle", "mystery", "wonder", "clue", "curious",
    "unexplained", "strange", "bizarre", "what happens"
]

EMOTIONAL_PEAK_MARKERS = [
    "astounding", "breathtaking", "brilliant", "awe", "terrifying", "epic",
    "miracle", "monumental", "heart", "unbelievable", "overwhelming", "gorgeous",
    "wonder", "shivers", "profound", "jaw-dropping", "immense"
]

CLIMAX_MARKERS = [
    "titan", "collision", "collide", "supermassive", "chaos", "explod",
    "finale", "climax", "cataclysm", "unleash", "gravitational wave", "strike",
    "maximum", "shatters", "collapse", "apocalyptic", "epic peak", "unprecedented"
]

CONCLUSION_MARKERS = [
    "eventually", "in the end", "as a result", "leaving behind", "quiet",
    "after all", "now", "settles", "ultimately", "today", "looking back",
    "the aftermath", "finally"
]

PAYOFF_MARKERS = [
    "remember", "the next time you", "look up", "lesson", "question remains",
    "leaving behind an astonishing", "payoff", "takeaway", "wonder of our universe",
    "and that is why", "that is how", "subscribe", "forever changed"
]


class NarrativeArcAnalyzer:
    """Intelligent narrative arc and dramatic structure parser."""

    def __init__(self, niche: str = "space_science"):
        self.niche = niche

    def analyze(
        self,
        sentences: list[dict[str, Any]],
        total_duration: float = 30.0,
        title: str = "",
    ) -> ArcAnalysisResult:
        """Analyzes a sequence of narration sentences and constructs the narrative arc."""
        n = len(sentences)
        if n == 0:
            return ArcAnalysisResult(
                segments=[],
                dominant_arc_type="linear",
                peak_segment_index=0,
                average_intensity=0.5,
                total_segments=0,
            )

        segments: list[NarrativeSegment] = []

        # Step 1: Assign roles through combined positional heuristics + semantic markers
        for i, s in enumerate(sentences):
            text = s.get("text", "") or s.get("voiceover", "")
            sid = s.get("id") or s.get("sentence_id") or f"S{i+1}"
            lower_text = text.lower()
            rel_pos = i / max(1, n - 1)  # 0.0 at start, 1.0 at end

            # Determine role
            role: NarrativeRole
            justification: str

            if i == 0:
                role = NarrativeRole.OPENING_HOOK
                justification = "First statement establishes the high-retention narrative hook."
            elif i == n - 1 and n > 2:
                role = NarrativeRole.FINAL_PAYOFF
                justification = "Final statement delivers the memorable takeaway and emotional closure."
            elif i == n - 2 and n > 3:
                # Penultimate segment: evaluate if it's climax or conclusion
                if any(m in lower_text for m in CLIMAX_MARKERS) or "wave finale" in lower_text:
                    role = NarrativeRole.CLIMAX
                    justification = "Penultimate segment features peak dramatic energy and conflict resolution."
                else:
                    role = NarrativeRole.CONCLUSION
                    justification = "Penultimate statement summarizes preceding revelations and leads into payoff."
            else:
                # Middle segments (1 to n-2)
                # Score against markers
                rev_score = sum(1 for m in REVELATION_MARKERS if m in lower_text)
                cur_score = sum(1 for m in CURIOSITY_MARKERS if m in lower_text)
                emo_score = sum(1 for m in EMOTIONAL_PEAK_MARKERS if m in lower_text)
                climax_score = sum(1 for m in CLIMAX_MARKERS if m in lower_text)
                concl_score = sum(1 for m in CONCLUSION_MARKERS if m in lower_text)

                # Check revelation markers
                explicit_rev = any(w in lower_text for w in ["surprisingly", "in reality", "the truth is", "almost none", "never touch", "actually"])

                # Positional preference
                if i == 1:
                    # Immediately after hook: context establishment
                    role = NarrativeRole.CONTEXT_ESTABLISHMENT
                    justification = "Establishes physical parameters, location, and situational context."
                elif i == 2 and n >= 6 and rev_score == 0 and climax_score == 0:
                    role = NarrativeRole.CURIOSITY_BUILDING
                    justification = "Progresses the premise, builds intrigue and leads into core revelation."
                # Check revelation first if explicit surprise/reality markers exist
                elif explicit_rev:
                    role = NarrativeRole.IMPORTANT_REVELATION
                    justification = f"Introduces counter-intuitive or crucial revelation ({[m for m in REVELATION_MARKERS if m in lower_text]})."
                elif emo_score >= 1 or any(w in lower_text for w in ["brilliant", "astounding", "millions of", "igniting"]):
                    role = NarrativeRole.EMOTIONAL_PEAK
                    justification = f"Evokes high awe or sensory resonance ({[m for m in EMOTIONAL_PEAK_MARKERS if m in lower_text]})."
                elif rev_score >= 1 or "yet" in lower_text:
                    role = NarrativeRole.IMPORTANT_REVELATION
                    justification = f"Introduces counter-intuitive or crucial revelation ({[m for m in REVELATION_MARKERS if m in lower_text]})."
                elif concl_score >= 1 or rel_pos >= 0.75:
                    role = NarrativeRole.CONCLUSION
                    justification = "Transitional bridge resolving narrative conflict."
                elif rel_pos < 0.5:
                    role = NarrativeRole.CURIOSITY_BUILDING
                    justification = "Progresses the mystery and builds anticipation."
                else:
                    role = NarrativeRole.EMOTIONAL_PEAK
                    justification = "Elevates narrative weight in the middle-late arc."

            # Map role to directorial and pacing parameters
            params = self._derive_parameters(role, lower_text, i, n)

            segments.append(
                NarrativeSegment(
                    index=i,
                    sentence_id=sid,
                    spoken_text=text,
                    role=role,
                    visual_intensity=params["visual_intensity"],
                    pacing_weight=params["pacing_weight"],
                    composition_style=params["composition_style"],
                    animation_intensity=params["animation_intensity"],
                    camera_dynamics=params["camera_dynamics"],
                    sound_accent=params["sound_accent"],
                    tension_target=params["tension_target"],
                    justification=justification,
                )
            )

        # Step 2: Ensure arc completeness (guarantee at least one climax and revelation if n >= 5)
        if n >= 5:
            has_revelation = any(s.role == NarrativeRole.IMPORTANT_REVELATION for s in segments)
            has_climax = any(s.role == NarrativeRole.CLIMAX for s in segments)

            if not has_climax:
                # Pick the segment with highest intensity between 50% and 85% of duration
                climax_candidates = [s for s in segments if 0.4 <= s.index / max(1, n - 1) <= 0.85]
                if climax_candidates:
                    chosen = max(climax_candidates, key=lambda s: s.visual_intensity)
                    chosen.role = NarrativeRole.CLIMAX
                    chosen.visual_intensity = 0.95
                    chosen.tension_target = 0.95
                    chosen.pacing_weight = 0.80
                    chosen.animation_intensity = 1.00
                    chosen.sound_accent = "sub_impact"
                    chosen.justification = "Designated narrative climax based on mid-arc dramatic peak."

            if not has_revelation:
                # Pick an early-middle candidate
                rev_candidates = [s for s in segments if 0.25 <= s.index / max(1, n - 1) <= 0.65 and s.role != NarrativeRole.CLIMAX]
                if rev_candidates:
                    chosen = rev_candidates[0]
                    chosen.role = NarrativeRole.IMPORTANT_REVELATION
                    chosen.visual_intensity = 0.82
                    chosen.tension_target = 0.78
                    chosen.pacing_weight = 1.05
                    chosen.animation_intensity = 0.75
                    chosen.sound_accent = "riser"
                    chosen.justification = "Designated core revelation turning point."

        # Compute summary metrics
        peak_idx = max(range(len(segments)), key=lambda idx: segments[idx].visual_intensity)
        avg_intensity = sum(s.visual_intensity for s in segments) / max(1, len(segments))

        # Classify dominant arc
        if any(s.role == NarrativeRole.IMPORTANT_REVELATION and s.visual_intensity > 0.85 for s in segments):
            arc_type = "revelation_driven"
        elif any(s.role == NarrativeRole.CLIMAX and s.visual_intensity > 0.90 for s in segments):
            arc_type = "epic_spectacle"
        else:
            arc_type = "suspense_build"

        return ArcAnalysisResult(
            segments=segments,
            dominant_arc_type=arc_type,
            peak_segment_index=peak_idx,
            average_intensity=avg_intensity,
            total_segments=len(segments),
        )

    def _derive_parameters(
        self,
        role: NarrativeRole,
        lower_text: str,
        index: int,
        total: int,
    ) -> dict[str, Any]:
        """Maps a narrative role to concrete visual, temporal, and acoustic properties."""
        has_stats = any(c in lower_text for c in ["%", "percent", "billion", "million", "thousand", "miles per hour", "years"])
        has_comparison = any(w in lower_text for w in ["instead", "almost none", "versus", "touch", "compare"])

        if role == NarrativeRole.OPENING_HOOK:
            return {
                "visual_intensity": 0.88,
                "pacing_weight": 0.85,
                "composition_style": "hero_macro_vista",
                "animation_intensity": 0.80,
                "camera_dynamics": "whip_zoom_in",
                "sound_accent": "impact_cinematic",
                "tension_target": 0.80,
            }
        elif role == NarrativeRole.CONTEXT_ESTABLISHMENT:
            comp = "isometric_stats" if has_stats else "wide_vista_route"
            return {
                "visual_intensity": 0.42,
                "pacing_weight": 1.15,
                "composition_style": comp,
                "animation_intensity": 0.40,
                "camera_dynamics": "lateral_drift",
                "sound_accent": "ambient_texture",
                "tension_target": 0.35,
            }
        elif role == NarrativeRole.CURIOSITY_BUILDING:
            return {
                "visual_intensity": 0.62,
                "pacing_weight": 0.95,
                "composition_style": "split_screen_comparison" if has_comparison else "cinematic_focus",
                "animation_intensity": 0.60,
                "camera_dynamics": "progressive_zoom",
                "sound_accent": "whoosh",
                "tension_target": 0.55,
            }
        elif role == NarrativeRole.IMPORTANT_REVELATION:
            comp = "forensic_inspection" if "spoon" in lower_text or "atom" in lower_text else ("split_screen_comparison" if has_comparison else "kinetic_typography")
            return {
                "visual_intensity": 0.84,
                "pacing_weight": 1.10,  # Deliberate hold to let revelation sink in
                "composition_style": comp,
                "animation_intensity": 0.75,
                "camera_dynamics": "snap_zoom_hold",
                "sound_accent": "low_freq_impact",
                "tension_target": 0.82,
            }
        elif role == NarrativeRole.EMOTIONAL_PEAK:
            return {
                "visual_intensity": 0.90,
                "pacing_weight": 0.90,
                "composition_style": "deep_space_starfield",
                "animation_intensity": 0.85,
                "camera_dynamics": "expansive_zoom_out",
                "sound_accent": "riser",
                "tension_target": 0.88,
            }
        elif role == NarrativeRole.CLIMAX:
            return {
                "visual_intensity": 0.98,
                "pacing_weight": 0.78,  # Punchy, accelerated cut
                "composition_style": "kinetic_high_energy",
                "animation_intensity": 1.00,
                "camera_dynamics": "kinetic_shake_push",
                "sound_accent": "cinematic_sub_impact",
                "tension_target": 0.96,
            }
        elif role == NarrativeRole.CONCLUSION:
            return {
                "visual_intensity": 0.48,
                "pacing_weight": 1.20,  # Settling, reflective pacing
                "composition_style": "wide_vista_dissolve",
                "animation_intensity": 0.40,
                "camera_dynamics": "settling_drift",
                "sound_accent": "ambient_texture",
                "tension_target": 0.40,
            }
        else:  # FINAL_PAYOFF
            return {
                "visual_intensity": 0.72,
                "pacing_weight": 1.10,
                "composition_style": "hero_lingering_payoff",
                "animation_intensity": 0.60,
                "camera_dynamics": "slow_pull_back",
                "sound_accent": "cinematic_accent",
                "tension_target": 0.65,
            }
