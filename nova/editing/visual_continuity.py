"""Visual Continuity Intelligence Analyzer for NOVA AUTOPILOT v9.5.

Analyzes adjacent scenes to eliminate unintentional disorientation:
- Color continuity (luminance, color balance, palette harmony)
- Subject positioning (eye-trace continuity, preventing jarring focal jumps across screen)
- Camera direction (motion vector alignment, avoiding 180-degree clash)
- Lighting consistency (high-key vs low-key balance)
- Composition (framing progression: wide -> medium -> close-up)
- Visual repetition (asset deduplication and intentional callbacks)
- Narrative continuity (visual alignment with current story beats)

Preserves intentional contrast when Motivated by dramatic revelation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional, Tuple

import numpy as np
from PIL import Image

from nova.editing.techniques import ColorHarmonizer, ColorProfile
from nova.vision.subject_tracker import SubjectTracker, detect_primary_subject


@dataclass
class AdjacentContinuityPair:
    """Continuity evaluation between two sequential scenes."""
    from_index: int
    to_index: int
    from_sentence_id: str
    to_sentence_id: str
    color_continuity_score: float      # [0, 100]
    subject_eye_trace_distance: float  # [0.0, 1.41]
    camera_direction_match: bool
    lighting_delta: float              # Luminance difference [0, 255]
    framing_progression: str           # e.g., "wide_to_medium", "jump_cut_warning", "harmonious"
    repetition_detected: bool
    overall_continuity_score: float    # [0, 100]
    issues: list[str] = field(default_factory=list)
    corrective_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_index": self.from_index,
            "to_index": self.to_index,
            "from_sentence_id": self.from_sentence_id,
            "to_sentence_id": self.to_sentence_id,
            "color_continuity_score": round(self.color_continuity_score, 1),
            "subject_eye_trace_distance": round(self.subject_eye_trace_distance, 3),
            "camera_direction_match": self.camera_direction_match,
            "lighting_delta": round(self.lighting_delta, 1),
            "framing_progression": self.framing_progression,
            "repetition_detected": self.repetition_detected,
            "overall_continuity_score": round(self.overall_continuity_score, 1),
            "issues": self.issues,
            "corrective_actions": self.corrective_actions,
        }


@dataclass
class ContinuityReport:
    """Project-wide visual continuity assessment."""
    average_continuity_score: float  # [0, 100]
    total_pairs_analyzed: int
    critical_discontinuities: int
    pairs: list[AdjacentContinuityPair]
    recommendations: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "average_continuity_score": round(self.average_continuity_score, 1),
            "total_pairs_analyzed": self.total_pairs_analyzed,
            "critical_discontinuities": self.critical_discontinuities,
            "recommendations": self.recommendations,
            "pairs": [p.to_dict() for p in self.pairs],
        }


class VisualContinuityAnalyzer:
    """Evaluates visual flow, color harmony, and eye trace between adjacent scenes."""

    def __init__(self):
        self.tracker = SubjectTracker()

    def analyze_adjacent_scenes(
        self,
        scene_shots: list[Any],
        scene_images_or_previews: list[Path | Image.Image | None],
        narrative_roles: list[str] | None = None,
    ) -> ContinuityReport:
        """Evaluates visual continuity across all consecutive scene transitions."""
        n = len(scene_shots)
        if n <= 1:
            return ContinuityReport(
                average_continuity_score=100.0,
                total_pairs_analyzed=0,
                critical_discontinuities=0,
                pairs=[],
                recommendations=["Single shot timeline: visual continuity optimal."],
            )

        pairs: list[AdjacentContinuityPair] = []
        critical_count = 0

        for i in range(n - 1):
            s1 = scene_shots[i]
            s2 = scene_shots[i + 1]
            img1 = scene_images_or_previews[i] if i < len(scene_images_or_previews) else None
            img2 = scene_images_or_previews[i + 1] if (i + 1) < len(scene_images_or_previews) else None

            role1 = narrative_roles[i] if narrative_roles and i < len(narrative_roles) else ""
            role2 = narrative_roles[i + 1] if narrative_roles and (i + 1) < len(narrative_roles) else ""

            pair = self._evaluate_pair(i, s1, s2, img1, img2, role1, role2)
            if pair.overall_continuity_score < 70.0:
                critical_count += 1
            pairs.append(pair)

        avg_score = sum(p.overall_continuity_score for p in pairs) / max(1, len(pairs))
        recs = []
        if critical_count > 0:
            recs.append(f"Identified {critical_count} scene cuts with noticeable photometric or eye-trace jumps. Corrective color matching and transition smoothing recommended.")
        else:
            recs.append("Visual continuity across all scene boundaries is harmonious and professional.")

        return ContinuityReport(
            average_continuity_score=round(avg_score, 1),
            total_pairs_analyzed=len(pairs),
            critical_discontinuities=critical_count,
            pairs=pairs,
            recommendations=recs,
        )

    def _evaluate_pair(
        self,
        idx: int,
        s1: Any,
        s2: Any,
        img1_input: Path | Image.Image | None,
        img2_input: Path | Image.Image | None,
        role1: str,
        role2: str,
    ) -> AdjacentContinuityPair:
        """Evaluates two consecutive shots."""
        sid1 = getattr(s1, "sentence_id", f"S{idx+1}")
        sid2 = getattr(s2, "sentence_id", f"S{idx+2}")

        issues: list[str] = []
        corrections: list[str] = []

        # 1. Photometric and Color Profile Evaluation
        prof1 = ColorHarmonizer.extract_profile(img1_input) if img1_input else ColorProfile((128, 128, 128), 128.0, 1.0, 30.0)
        prof2 = ColorHarmonizer.extract_profile(img2_input) if img2_input else ColorProfile((128, 128, 128), 128.0, 1.0, 30.0)

        lum_delta = abs(prof1.mean_luminance - prof2.mean_luminance)
        temp_delta = abs(prof1.color_temp_ratio - prof2.color_temp_ratio)

        # Base color score out of 100
        color_score = 100.0 - min(45.0, (lum_delta / 255.0) * 80.0) - min(35.0, temp_delta * 40.0)
        color_score = max(20.0, min(100.0, color_score))

        # Check if brightness difference is extreme
        if lum_delta > 75.0 and role2 != "climax":
            issues.append(f"Severe luminance jump ({lum_delta:.1f} gray levels) between shots.")
            corrections.append("Apply ColorHarmonizer brightness compensation filter.")

        # 2. Subject Position and Eye Trace Continuity
        sub1 = self.tracker.detect_subject(img1_input) if img1_input else None
        sub2 = self.tracker.detect_subject(img2_input) if img2_input else None

        cx1, cy1 = (sub1.norm_cx, sub1.norm_cy) if sub1 else (0.5, 0.5)
        cx2, cy2 = (sub2.norm_cx, sub2.norm_cy) if sub2 else (0.5, 0.5)

        eye_dist = math.sqrt((cx2 - cx1) ** 2 + (cy2 - cy1) ** 2)

        if eye_dist > 0.55 and role2 != "climax":
            issues.append(f"Eye trace displacement high ({eye_dist:.2f} screen units). Viewer gaze forced to jump rapidly.")
            corrections.append("Reposition crop window towards focal continuity or use directional transition.")

        # 3. Camera Movement Direction
        cam1 = getattr(s1, "camera_movement", "") or getattr(s1, "framing", "")
        cam2 = getattr(s2, "camera_movement", "") or getattr(s2, "framing", "")

        dir_match = True
        if ("pan_left" in cam1 and "pan_right" in cam2) or ("pan_right" in cam1 and "pan_left" in cam2):
            dir_match = False
            issues.append("Clashing camera direction (opposite pans without neutral buffer).")
            corrections.append("Insert whip-pan or neutral progressive zoom to bridge motion vectors.")

        # 4. Framing progression
        f1 = getattr(s1, "framing", "medium_shot")
        f2 = getattr(s2, "framing", "medium_shot")
        if f1 == f2 and eye_dist < 0.12 and abs(lum_delta) < 15.0:
            framing_prog = "jump_cut_warning"
            issues.append("Nearly identical framing and subject position creates an inadvertent jump cut.")
            corrections.append("Alter crop scale by >= 20% or switch to different composition archetype.")
        else:
            framing_prog = f"{f1}_to_{f2}"

        # 5. Visual Repetition
        asset1 = str(getattr(s1, "asset_file", "") or getattr(s1, "query", ""))
        asset2 = str(getattr(s2, "asset_file", "") or getattr(s2, "query", ""))
        repetition = bool(asset1 and asset2 and asset1 == asset2)
        if repetition:
            issues.append("Identical asset reused in consecutive shots.")
            corrections.append("Replace second shot with complementary angle or motion graphic.")

        # Composite score calculation
        penalty = len(issues) * 12.0
        overall = max(25.0, min(100.0, (color_score * 0.45) + ((1.0 - min(1.0, eye_dist)) * 40.0) + (15.0 if dir_match else 0.0) - penalty * 0.3))

        return AdjacentContinuityPair(
            from_index=idx,
            to_index=idx + 1,
            from_sentence_id=sid1,
            to_sentence_id=sid2,
            color_continuity_score=color_score,
            subject_eye_trace_distance=eye_dist,
            camera_direction_match=dir_match,
            lighting_delta=lum_delta,
            framing_progression=framing_prog,
            repetition_detected=repetition,
            overall_continuity_score=overall,
            issues=issues,
            corrective_actions=corrections,
        )
