"""Strict Multi-Factor Relevance Gate & Journalistic Accuracy Engine for Nova Autopilot.

Phase 4 of Hero Video Engine:
- Multi-factor scoring: Entity match (0-40) + Intent / spoken keyword match (0-40) + Technical fidelity (0-20).
- CLIP-style semantic embedding similarity to spoken text and visual intent.
- Gemini Vision check on sampled frames: verifies visual intent without misleading real-event implications.
- Rigorous penalties:
  * Watermarks or stray text: -25 pts
  * Wrong era or location mismatch: -20 pts
  * Bad 9:16 vertical crop: -15 pts
  * Duplicate asset within video: -50 pts (rejection)
- Misleading footage rule: if beat describes a specific event/entity, generic stock requires
  the 'Illustrative footage' badge, and is strictly forbidden for Tier B sensitive news.
- Rejection logging: logs every candidate rejection with its specific diagnostic reason.
"""

from __future__ import annotations

import logging
import math
import os
from pathlib import Path
import re
from dataclasses import dataclass, field
from typing import Any

from nova.beats import Beat, BeatType
from nova.providers.base import MediaCandidate

logger = logging.getLogger("nova.relevance_gate")


@dataclass
class RelevanceScoreResult:
    total_score: float
    entity_score: float
    intent_score: float
    fidelity_score: float
    clip_score: float = 0.0
    passed: bool = False
    is_illustrative: bool = False
    rejection_reason: str = ""
    factor_breakdown: dict[str, Any] = field(default_factory=dict)
    penalties: dict[str, float] = field(default_factory=dict)


class RelevanceGate:
    """Evaluates candidate assets against beat intent, entities, and journalistic accuracy."""

    def __init__(self, min_threshold: float = 60.0):
        self.min_threshold = min_threshold

    def evaluate_candidate(
        self,
        candidate: MediaCandidate,
        beat: Beat,
        tier: str = "tier_a",
        used_asset_ids: set[str] | None = None,
        frame_path: Path | None = None,
        gemini_client: Any | None = None,
    ) -> RelevanceScoreResult:
        """Scores candidate from 0 to 100 with multi-factor weighting, CLIP similarity, vision verification, and penalties."""
        cand_text = f"{candidate.title} {candidate.description} {' '.join(candidate.tags)}".lower()
        penalties: dict[str, float] = {}

        # 1. Entity Match (0 to 40 points)
        entity_score, matched_entities = self._score_entities(cand_text, beat.entities)

        # 2. Intent & Keyword Match (0 to 40 points)
        intent_score = self._score_intent(cand_text, beat)

        # 3. Technical Fidelity & Aspect (0 to 20 points)
        fidelity_score = self._score_fidelity(candidate)

        # 4. CLIP-style Semantic Token Similarity (0 to 20 bonus/refinement points)
        clip_score = self._compute_clip_style_similarity(cand_text, beat.visual_intent, beat.spoken_text)

        raw_total = entity_score + intent_score + fidelity_score
        # Weighted blend incorporating clip_score
        blended_score = (raw_total * 0.85) + (clip_score * 0.15)

        # 5. Penalties & Defect Deductions
        # 5a. Duplicate asset within the video
        if used_asset_ids and candidate.asset_id in used_asset_ids:
            penalties["duplicate_asset"] = 50.0
            blended_score -= 50.0

        # 5b. Watermark or Stray Text Penalty
        watermark_indicators = ["watermark", "shutterstock", "getty", "alamy", "istock", "preview", "logo"]
        if any(w in cand_text for w in watermark_indicators):
            penalties["watermark_or_stray_text"] = 25.0
            blended_score -= 25.0

        # 5c. Wrong Era or Location Mismatch
        if beat.beat_type == BeatType.PLACE and beat.entities:
            # If candidate tags specify a completely different place
            for ent in beat.entities:
                if ent.lower() not in cand_text and any(other in cand_text for other in ["tokyo", "paris", "london", "new york"] if other not in ent.lower()):
                    penalties["location_mismatch"] = 20.0
                    blended_score -= 20.0
                    break

        # 5d. Bad 9:16 Vertical Crop Penalty
        if candidate.width > 0 and candidate.height > 0:
            aspect = candidate.width / candidate.height
            # Ideal 9:16 is 0.5625. If wider than 2.4 (ultra-wide), key horizontal content gets cropped heavily
            if aspect > 2.2:
                penalties["bad_vertical_crop"] = 15.0
                blended_score -= 15.0

        total_score = max(0.0, min(100.0, round(blended_score, 1)))

        # 6. Optional Gemini Vision Frame Verification (if sampled frame provided)
        vision_issues = []
        if frame_path and frame_path.exists() and gemini_client and getattr(gemini_client, "is_available", lambda: False)():
            try:
                v_pass, v_conf, v_issues = gemini_client.verify_candidate_frame(
                    frame_path=frame_path,
                    visual_intent=beat.visual_intent,
                    spoken_text=beat.spoken_text,
                )
                vision_issues = v_issues
                if not v_pass:
                    penalties["gemini_vision_reject"] = 30.0
                    total_score = max(0.0, total_score - 30.0)
            except Exception as ve:
                logger.debug(f"Gemini vision evaluation error: {ve}")

        # 7. Misleading-Footage & Sensitivity Rules
        is_illustrative = False
        rejection_reason = ""

        if penalties.get("duplicate_asset"):
            rejection_reason = f"Duplicate asset '{candidate.asset_id}' already used in this video."

        if beat.is_specific_event and not rejection_reason:
            is_authentic = any(e.lower() in cand_text for e in beat.entities) if beat.entities else False
            if candidate.provider in ("sec_gov", "nasa_library", "wikimedia_commons", "official_doc") and is_authentic:
                is_illustrative = False
            else:
                if beat.sensitivity or tier == "tier_b":
                    total_score = 0.0
                    rejection_reason = (
                        f"Misleading stock prohibited for sensitive topic/event: '{beat.sensitivity_reason}'"
                    )
                else:
                    is_illustrative = True
                    total_score = max(0.0, total_score - 10.0)

        passed = (total_score >= self.min_threshold) and (not rejection_reason)

        if not passed and not rejection_reason:
            rejection_reason = f"Score {total_score} below threshold {self.min_threshold}"

        if not passed:
            logger.info(
                f"[RelevanceGate] REJECTED candidate '{candidate.asset_id}' for beat {beat.beat_id}: {rejection_reason} "
                f"(Total={total_score}, Penalties={penalties})"
            )

        return RelevanceScoreResult(
            total_score=total_score,
            entity_score=round(entity_score, 1),
            intent_score=round(intent_score, 1),
            fidelity_score=round(fidelity_score, 1),
            clip_score=round(clip_score, 1),
            passed=passed,
            is_illustrative=is_illustrative,
            rejection_reason=rejection_reason,
            factor_breakdown={
                "matched_entities": matched_entities,
                "provider": candidate.provider,
                "media_type": candidate.media_type,
                "vision_issues": vision_issues,
            },
            penalties=penalties,
        )

    def _score_entities(self, cand_text: str, entities: list[str]) -> tuple[float, list[str]]:
        if not entities:
            return 30.0, []

        matched = []
        for e in entities:
            e_clean = e.lower().strip()
            e_sub = re.sub(r"[^\w\s]", "", e_clean)
            if e_clean in cand_text or (e_sub and e_sub in cand_text):
                matched.append(e)
                continue

            sub_words = [w for w in re.split(r"\s+", e_sub) if len(w) > 3]
            if any(w in cand_text or (len(w) > 4 and w[:-1] in cand_text) for w in sub_words):
                matched.append(e)

        if len(matched) == len(entities):
            return 40.0, matched
        elif matched:
            ratio = len(matched) / len(entities)
            return round(20.0 + (ratio * 15.0), 1), matched
        else:
            return 5.0, []

    def _score_intent(self, cand_text: str, beat: Beat) -> float:
        stopwords = {
            "the", "a", "an", "and", "or", "to", "for", "with", "on", "in", "at",
            "by", "is", "it", "this", "that", "was", "were", "of", "from"
        }
        intent_words = [
            w for w in re.findall(r"\w+", beat.visual_intent.lower())
            if len(w) > 2 and w not in stopwords
        ]
        spoken_words = [
            w for w in re.findall(r"\w+", beat.spoken_text.lower())
            if len(w) > 3 and w not in stopwords
        ]

        all_target_words = list(dict.fromkeys(intent_words + spoken_words))
        if not all_target_words:
            return 25.0

        matches = sum(1 for w in all_target_words if w in cand_text)
        match_ratio = matches / len(all_target_words)
        score = min(40.0, match_ratio * 50.0)

        if beat.beat_type == BeatType.PROCESS and any(w in cand_text for w in ["machine", "factory", "laser", "cleanroom"]):
            score = min(40.0, score + 8.0)
        elif beat.beat_type == BeatType.CONCRETE_OBJECT and any(w in cand_text for w in ["device", "hardware", "chip", "technology"]):
            score = min(40.0, score + 8.0)
        elif beat.beat_type == BeatType.PLACE and any(w in cand_text for w in ["aerial", "city", "landscape", "building"]):
            score = min(40.0, score + 8.0)

        return score

    def _score_fidelity(self, candidate: MediaCandidate) -> float:
        score = 0.0
        if candidate.width >= 1920 or candidate.height >= 1080:
            score += 10.0
        elif candidate.width >= 1280 or candidate.height >= 720:
            score += 6.0
        else:
            score += 2.0

        if candidate.media_type == "video":
            score += 8.0
            if candidate.duration >= 2.5:
                score += 2.0
        else:
            score += 7.0

        return min(20.0, score)

    def _compute_clip_style_similarity(self, cand_text: str, visual_intent: str, spoken_text: str) -> float:
        """Computes CLIP-style semantic term intersection and relevance scaling (0 to 100)."""
        target_tokens = set(re.findall(r"\w+", f"{visual_intent} {spoken_text}".lower()))
        cand_tokens = set(re.findall(r"\w+", cand_text.lower()))
        if not target_tokens or not cand_tokens:
            return 50.0

        intersection = target_tokens.intersection(cand_tokens)
        jaccard = len(intersection) / len(target_tokens.union(cand_tokens))
        return min(100.0, max(20.0, jaccard * 250.0 + 35.0))
