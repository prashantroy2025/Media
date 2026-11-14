"""Topic ranking and surprise scoring engine for Nova Autopilot v2.0."""

import math
import re
from datetime import UTC, datetime, timedelta

from nova.config import NovaSettings
from nova.db import DatabaseManager, Publication, Topic
from nova.logging_setup import logger
from nova.topic_safety import evaluate_topic_safety

SHOCK_WORDS = {
    "billion",
    "million",
    "trillion",
    "speed",
    "light",
    "space",
    "star",
    "planet",
    "gravity",
    "black hole",
    "laser",
    "slice",
    "weigh",
    "pyramids",
    "earth",
    "sun",
    "discovered",
    "secret",
    "never",
    "impossible",
    "fastest",
    "heaviest",
    "largest",
    "tiny",
    "deadly",
    "dna",
    "brain",
    "quantum",
}


def _token_jaccard(title_a: str, title_b: str) -> float:
    """Computes Jaccard similarity over word tokens to detect near-duplicates."""
    tokens_a = set(re.findall(r"\w+", title_a.lower()))
    tokens_b = set(re.findall(r"\w+", title_b.lower()))
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


class TopicRanker:
    def __init__(self, settings: NovaSettings, db_mgr: DatabaseManager):
        self.settings = settings
        self.db_mgr = db_mgr

    def get_todays_format(self) -> str:
        """Picks content format based on day of week for dynamic weekly programming."""
        formats = self.settings.content.format_mix
        idx = datetime.now(UTC).weekday() % len(formats)
        return formats[idx]

    def rank_topics(self, limit: int = 5, target_niche: str | None = None) -> list[Topic]:
        """Scores candidate topics on surprise value, freshness, and 60-day novelty.

        If target_niche is specified, prioritizes candidate topics belonging to that niche.
        """
        session = self.db_mgr.session()
        try:
            sixty_days_ago = datetime.now(UTC) - timedelta(days=60)

            # Query topics used in the last 60 days to enforce deduplication
            recently_used = (
                session.query(Topic)
                .filter(
                    Topic.status == "used",
                    Topic.used_at >= sixty_days_ago,
                )
                .all()
            )
            used_titles = [t.title for t in recently_used]

            # Query candidates
            query = session.query(Topic).filter(
                Topic.status != "used",
                (Topic.used_at.is_(None)) | (Topic.used_at < sixty_days_ago),
            )
            candidate_topics: list[Topic] = query.all()

            if target_niche:
                niche_candidates = [t for t in candidate_topics if t.niche == target_niche]
                if niche_candidates:
                    candidate_topics = niche_candidates
                else:
                    logger.info(f"No candidate topics found specifically for target niche '{target_niche}'.")
                    return []

            if not candidate_topics:
                logger.info("No candidate topics available to rank.")
                return []

            # Get niche-specific keywords if target_niche is given
            keywords = [kw.lower() for kw in self.settings.channel.niche_keywords]
            if target_niche and target_niche in self.settings.niches:
                niche_cfg = self.settings.niches[target_niche]
                if niche_cfg.keywords:
                    keywords = [kw.lower() for kw in niche_cfg.keywords]

            high_performing_keywords = self._get_high_performing_keywords(session)
            now = datetime.now(UTC)

            eligible_topics: list[Topic] = []

            for topic in candidate_topics:
                # 0. Three-Tier Topic Safety Policy (Tier A, Tier B Sensitive News, Tier C Prohibited)
                is_safe, safety_reason, meta = evaluate_topic_safety(
                    topic.title,
                    topic.summary or "",
                    topic.niche or "ai_tech",
                    source_url=topic.source_url or "",
                )
                topic.tier = meta.get("tier", "tier_a")
                topic.requires_manual_approval = meta.get("requires_manual_approval", False)
                topic.safety_status = meta.get("tier", "tier_a")
                topic.safety_reason = safety_reason

                if not is_safe:
                    logger.info(f"Skipping prohibited topic '{topic.title[:60]}...': {safety_reason}")
                    topic.status = "unsafe_skipped"
                    continue

                # 1. 60-day Near-Duplicate Filter (Jaccard > 0.45)
                is_duplicate = False
                for u_title in used_titles:
                    if _token_jaccard(topic.title, u_title) > 0.45:
                        is_duplicate = True
                        break
                if is_duplicate:
                    topic.status = "skipped"
                    continue

                # 2. Surprise Value Scoring (1 to 10 scale * factor)
                text_corpus = f"{topic.title} {topic.summary}".lower()
                shock_matches = sum(1 for sw in SHOCK_WORDS if sw in text_corpus)
                surprise_score = min(35.0, shock_matches * 7.0)

                # 3. Niche relevance score
                niche_match_count = sum(1 for kw in keywords if re.search(r"\b" + re.escape(kw) + r"\b", text_corpus))
                niche_score = min(30.0, niche_match_count * 10.0)

                # Niche alignment boost if target_niche is specified
                target_niche_boost = 0.0
                if target_niche:
                    if topic.niche == target_niche:
                        target_niche_boost = 40.0
                    elif topic.niche is None and niche_match_count > 0:
                        target_niche_boost = 15.0
                    else:
                        target_niche_boost = -20.0  # de-prioritize mismatched niche

                # 4. Freshness score (high within 7 days, evergreen bonus for science)
                created = topic.created_at
                if created.tzinfo is None:
                    created = created.replace(tzinfo=UTC)
                age_days = max(0.1, (now - created).total_seconds() / 86400.0)
                if age_days <= 7:
                    freshness_score = 25.0 * math.exp(-age_days / 7.0)
                else:
                    # Evergreen bonus if high science or shock score
                    freshness_score = 10.0 if surprise_score > 14.0 else 2.0

                # 5. Raw score & past performance boost
                source_score = min(topic.raw_score, 25.0)
                perf_boost = 0.0
                for kw in high_performing_keywords:
                    if kw in text_corpus:
                        perf_boost += 8.0

                final_score = (
                    surprise_score + niche_score + target_niche_boost + freshness_score + source_score + perf_boost
                )
                topic.final_score = round(final_score, 2)
                topic.status = "ranked"
                eligible_topics.append(topic)

            session.commit()

            ranked = sorted(eligible_topics, key=lambda t: t.final_score, reverse=True)
            top_ranked = ranked[:limit]

            if top_ranked:
                today_fmt = self.get_todays_format()
                logger.info(
                    f"Ranked {len(eligible_topics)} eligible topics for format '[bold magenta]{today_fmt}[/bold magenta]' "
                    f"(target niche: {target_niche or 'any'}). "
                    f"Top topic: '{top_ranked[0].title}' (Score: {top_ranked[0].final_score}, Niche: {top_ranked[0].niche})"
                )
            return top_ranked
        except Exception as e:
            session.rollback()
            logger.error(f"Error during topic ranking: {e}", exc_info=True)
            raise
        finally:
            session.close()

    def _get_high_performing_keywords(self, session) -> list[str]:
        try:
            pubs = session.query(Publication).filter(Publication.views > 100).all()
            tokens = []
            for p in pubs:
                if p.video and p.video.script:
                    title_words = re.findall(r"\w+", p.video.script.title.lower())
                    tokens.extend([w for w in title_words if len(w) > 3])
            return list(set(tokens))
        except Exception:
            return []
