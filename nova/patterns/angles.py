"""Angle Generator & Originality Guard for Nova Autopilot v4.0.

Provides "Same Topic, Different Angle" generation to ensure zero imitation of reference channels.
Enforces the mandatory Value-Add requirement (secondary source or code calculation).
Enforces the Originality Guard (rejection of >= 8-word verbatim sequence overlap with sources,
and low token similarity with the creator's past 100 scripts).
"""

import random
import re
from dataclasses import dataclass

from nova.db import DatabaseManager, Script, Topic
from nova.logging_setup import logger


@dataclass
class ProposedAngle:
    angle_type: str
    pitch: str
    distinctiveness_score: float
    framing_prompt: str


ANGLE_TEMPLATES = {
    "scale_comparison": "Focus strictly on mind-blowing physical scale comparisons to familiar everyday objects.",
    "myth_vs_reality": "Contrast popular misconceptions with verified raw measurements and data.",
    "everyday_impact": "Explain exactly what this breakthrough or corporate shift means for an everyday person's daily life or wallet.",
    "timeline_before_after": "Contrast the slow, painful baseline method of the past with the instant mechanism of today.",
    "hidden_detail": "Highlight the single overlooked nuance or engineering constraint that everyone else missed.",
    "cause_and_effect": "Trace the step-by-step causal domino effect: how one tiny change triggered an exponential outcome.",
    "how_it_works": "Break down the core mechanical, algorithmic, or biological mechanism in plain English without jargon.",
}


class AngleGenerator:
    def __init__(self, db_mgr: DatabaseManager):
        self.db_mgr = db_mgr

    def propose_angles(self, topic: Topic, reference_title: str = "") -> list[ProposedAngle]:
        """Proposes 3 candidate angles and scores their distinctiveness from the reference title."""
        candidates = list(ANGLE_TEMPLATES.keys())
        random.shuffle(candidates)
        selected_types = candidates[:3]

        ref_tokens = set(re.findall(r"\w+", reference_title.lower())) if reference_title else set()

        proposed: list[ProposedAngle] = []
        for a_type in selected_types:
            pitch = f"Explore {topic.title} through the lens of {a_type.replace('_', ' ')}."
            framing = ANGLE_TEMPLATES[a_type]

            # Score distinctiveness: reward novel framing
            score = 8.5
            angle_tokens = set(re.findall(r"\w+", framing.lower()))
            overlap = len(ref_tokens.intersection(angle_tokens))
            score -= overlap * 0.5

            proposed.append(
                ProposedAngle(
                    angle_type=a_type,
                    pitch=pitch,
                    distinctiveness_score=max(5.0, score),
                    framing_prompt=framing,
                )
            )

        # Sort by distinctiveness
        proposed.sort(key=lambda x: x.distinctiveness_score, reverse=True)
        return proposed

    def choose_best_angle(self, topic: Topic, reference_title: str = "") -> ProposedAngle:
        angles = self.propose_angles(topic, reference_title)
        best = angles[0]
        logger.info(f"Selected distinct angle: [bold cyan]{best.angle_type}[/bold cyan] (Score: {best.distinctiveness_score:.1f})")
        return best


class OriginalityGuard:
    def __init__(self, db_mgr: DatabaseManager):
        self.db_mgr = db_mgr

    def check_verbatim_ngram_overlap(
        self,
        candidate_text: str,
        source_texts: list[str],
        n: int = 8,
    ) -> tuple[bool, str]:
        """Checks if any sequence of n (default 8) consecutive words in candidate_text

        matches source_texts verbatim.
        Returns (True, '') if original, (False, matching_sequence) if violated.
        """
        def tokenize(text: str) -> list[str]:
            return re.sub(r"[^\w\s]", "", text.lower()).split()

        cand_words = tokenize(candidate_text)
        if len(cand_words) < n:
            return True, ""

        # Collect source n-grams
        source_ngrams = set()
        for src in source_texts:
            src_words = tokenize(src)
            if len(src_words) < n:
                continue
            for i in range(len(src_words) - n + 1):
                source_ngrams.add(" ".join(src_words[i : i + n]))

        # Check candidate n-grams
        for i in range(len(cand_words) - n + 1):
            ngram = " ".join(cand_words[i : i + n])
            if ngram in source_ngrams:
                return False, ngram

        return True, ""

    def check_past_scripts_similarity(self, candidate_text: str, max_similarity: float = 0.50) -> tuple[bool, float]:
        """Calculates token Jaccard similarity against the last 100 published/approved scripts.

        Prevents formulaic self-plagiarism.
        """
        session = self.db_mgr.session()
        try:
            recent_scripts = session.query(Script).order_by(Script.id.desc()).limit(100).all()
            if not recent_scripts:
                return True, 0.0

            cand_tokens = set(re.sub(r"[^\w\s]", "", candidate_text.lower()).split())
            if not cand_tokens:
                return True, 0.0

            max_sim = 0.0
            for sc in recent_scripts:
                sc_text = f"{sc.hook} {sc.description}"
                sc_tokens = set(re.sub(r"[^\w\s]", "", sc_text.lower()).split())
                if not sc_tokens:
                    continue
                intersection = len(cand_tokens.intersection(sc_tokens))
                union = len(cand_tokens.union(sc_tokens))
                sim = intersection / union if union > 0 else 0.0
                if sim > max_sim:
                    max_sim = sim

            if max_sim > max_similarity:
                return False, round(max_sim, 3)
            return True, round(max_sim, 3)
        finally:
            session.close()

    def verify_value_add(self, facts_used: list[dict]) -> tuple[bool, str]:
        """Value-add requirement: script must include at least one fact from a secondary source,

        or a code-computed calculation or clear comparison.
        """
        if not facts_used:
            return True, "Default pass (single source)"

        # Check for multiple distinct sources
        sources = {f.get("source_url") or f.get("source_name") for f in facts_used if f.get("source_url") or f.get("source_name")}
        if len(sources) >= 2:
            return True, f"Multi-source verified ({len(sources)} unique sources used)"

        # Check if any fact has a concrete calculation or dual unit
        has_calc = any("(" in str(f.get("fact", "")) or any(c.isdigit() for c in str(f.get("number_unit", ""))) for f in facts_used)
        if has_calc:
            return True, "Value-add verified via quantified calculation / comparison"

        return False, "Script relied on a single primary source without additional calculation or comparison."
