"""Visual Relevance & Semantic Scorer for Nova Autopilot v4.0.

Computes semantic and keyword overlap between candidate visual metadata and the sentence's
structured visual intent (main_subject, action_or_state, and 3 concrete search queries).
Enforces a strict minimum relevance threshold (default 40.0/100). Any candidate below threshold
is strictly rejected.
"""

import re
from dataclasses import dataclass

from nova.logging_setup import logger


@dataclass
class CandidateVisual:
    provider: str
    asset_id: str
    title: str
    description: str
    tags: list[str]
    preview_url: str
    download_url: str
    media_type: str  # 'video' or 'image'
    creator_name: str = ""
    creator_url: str = ""
    license_name: str = ""
    asset_url: str = ""


class VisualRelevanceScorer:
    def __init__(self, min_threshold: float = 40.0):
        self.min_threshold = min_threshold

    def score_candidate(
        self,
        candidate: CandidateVisual,
        main_subject: str,
        action_or_state: str,
        queries: list[str],
        niche: str = "ai_tech",
    ) -> float:
        """Scores candidate relevance from 0.0 to 100.0 based on:

        1. Exact and stemmed match with main_subject (weight: 40%)
        2. Overlap with query variants (weight: 35%)
        3. Match with action_or_state (weight: 15%)
        4. Domain compatibility penalty (e.g. space visual for business = -50%)
        """

        def tokenize(text: str) -> set[str]:
            stopwords = {"the", "a", "an", "of", "in", "and", "or", "to", "for", "with", "on", "at", "by", "from"}
            words = re.findall(r"\w+", text.lower())
            return {w for w in words if len(w) > 2 and w not in stopwords}

        cand_text = f"{candidate.title} {candidate.description} {' '.join(candidate.tags)}".lower()
        cand_tokens = tokenize(cand_text)

        if not cand_tokens:
            return 0.0

        # Domain mismatch penalty: NASA or astronomical imagery on business/fintech topics
        space_entities = {
            "planet",
            "galaxy",
            "nebula",
            "mars",
            "jupiter",
            "saturn",
            "moon",
            "solar",
            "orbit",
            "telescope",
            "astronaut",
            "crater",
            "star",
            "hubble",
            "spacecraft",
            "apollo",
            "pulsar",
        }
        if niche in ["business", "ai_tech"]:
            space_matches = cand_tokens.intersection(space_entities)
            if space_matches and candidate.provider == "nasa":
                logger.debug(
                    f"Rejecting candidate '{candidate.title}' due to space domain mismatch for niche '{niche}'"
                )
                return 0.0

        # 1. Subject match (40 pts)
        subj_tokens = tokenize(main_subject)
        subj_score = 0.0
        if subj_tokens:
            overlap = subj_tokens.intersection(cand_tokens)
            subj_score = (len(overlap) / len(subj_tokens)) * 40.0
            # Full exact phrase bonus
            if main_subject.lower() in cand_text:
                subj_score = 40.0

        # 2. Query variants overlap (35 pts)
        all_query_tokens = set()
        for q in queries:
            all_query_tokens.update(tokenize(q))

        query_score = 0.0
        if all_query_tokens:
            q_overlap = all_query_tokens.intersection(cand_tokens)
            query_score = min(35.0, (len(q_overlap) / len(all_query_tokens)) * 35.0 * 1.5)
            # Bonus if any query is a complete substring
            for q in queries:
                if len(q.strip()) > 4 and q.lower() in cand_text:
                    query_score = 35.0
                    break

        # 3. Action / State match (15 pts)
        action_score = 0.0
        action_tokens = tokenize(action_or_state)
        if action_tokens:
            a_overlap = action_tokens.intersection(cand_tokens)
            action_score = (len(a_overlap) / len(action_tokens)) * 15.0

        # 4. Media type preference (videos get +10 pts bonus for motion)
        media_bonus = 10.0 if candidate.media_type == "video" else 5.0

        total_score = min(100.0, subj_score + query_score + action_score + media_bonus)
        return round(total_score, 1)

    def is_acceptable(self, score: float) -> bool:
        return score >= self.min_threshold
