"""Pattern Library for Nova Autopilot v4.0.

Stores abstract patterns (hook structures, beats, title formulas) in our own words.
Enforces the mandatory 4-word max overlap rule: no pattern text may contain more than
4 consecutive words copied from any reference title.
"""

import json
import re

from nova.config import NovaSettings
from nova.db import DatabaseManager, FormatStats, HookPattern, ReferenceVideo, StructureTemplate, TitleFormula
from nova.logging_setup import logger


def check_word_overlap(pattern_text: str, reference_titles: list[str], max_consecutive_words: int = 4) -> tuple[bool, str]:
    """Validates that pattern text does not contain more than max_consecutive_words (default 4)

    consecutive words from any reference title.
    Returns (True, "") if compliant, (False, offending_ngram) if violated.
    """
    def tokenize(text: str) -> list[str]:
        # Lowercase and strip punctuation
        clean = re.sub(r"[^\w\s]", "", text.lower())
        return clean.split()

    pattern_words = tokenize(pattern_text)
    n = max_consecutive_words + 1  # 5-word sequences are forbidden

    if len(pattern_words) < n:
        return True, ""

    pattern_ngrams = set()
    for i in range(len(pattern_words) - n + 1):
        pattern_ngrams.add(" ".join(pattern_words[i : i + n]))

    for ref_title in reference_titles:
        ref_words = tokenize(ref_title)
        if len(ref_words) < n:
            continue
        for i in range(len(ref_words) - n + 1):
            ngram = " ".join(ref_words[i : i + n])
            if ngram in pattern_ngrams:
                return False, ngram

    return True, ""


class PatternLibrary:
    def __init__(self, settings: NovaSettings, db_mgr: DatabaseManager):
        self.settings = settings
        self.db_mgr = db_mgr
        self.seed_defaults()

    def seed_defaults(self):
        """Initializes default abstract patterns if database is empty."""
        session = self.db_mgr.session()
        try:
            # Seed Hook Patterns
            if session.query(HookPattern).count() == 0:
                default_hooks = [
                    HookPattern(
                        pattern_type="impossible_number",
                        template_text="[Surprising Number] [Familiar Object] is actually enough to [Unexpected Outcome].",
                        example_text="A single teaspoon of neutron star weighs six billion tons.",
                    ),
                    HookPattern(
                        pattern_type="contradiction",
                        template_text="Everything you were taught about [Subject] is completely backwards.",
                        example_text="Everything you were taught about computer memory is completely backwards.",
                    ),
                    HookPattern(
                        pattern_type="direct_question",
                        template_text="Why did [Institution or Entity] quietly spend [Large Sum] on [Surprising Asset]?",
                        example_text="Why did Nvidia quietly spend billions on custom networking silicon?",
                    ),
                    HookPattern(
                        pattern_type="scale_comparison",
                        template_text="That single [Component] is larger than [Massive Landmark].",
                        example_text="That single rocket booster is taller than a 25-story building.",
                    ),
                    HookPattern(
                        pattern_type="myth_bust",
                        template_text="Scientists just proved that [Common Belief] is an absolute myth.",
                        example_text="Scientists just proved that sitting too close to screens does not ruin your eyes.",
                    ),
                ]
                session.add_all(default_hooks)

            # Seed Structure Templates
            if session.query(StructureTemplate).count() == 0:
                default_structures = [
                    StructureTemplate(
                        name="high_tension_escalation",
                        beats_json=json.dumps([
                            {"beat_id": "B1", "role": "hook", "purpose": "Stop scroll with shocking metric", "bridge_to_next": "cause->effect"},
                            {"beat_id": "B2", "role": "context", "purpose": "Anchor timeline and baseline state", "bridge_to_next": "escalation"},
                            {"beat_id": "B3", "role": "escalation", "purpose": "Reveal the unexpected mechanism", "bridge_to_next": "but here's the catch"},
                            {"beat_id": "B4", "role": "payoff", "purpose": "Explicitly answer the opening hook question", "bridge_to_next": "loop-back"},
                            {"beat_id": "B5", "role": "loop_back", "purpose": "Seamless closing loop to first line", "bridge_to_next": "none"},
                        ]),
                        target_duration_range="25-35s",
                        target_sentence_count=5,
                    ),
                    StructureTemplate(
                        name="myth_busting_chain",
                        beats_json=json.dumps([
                            {"beat_id": "B1", "role": "hook", "purpose": "State the common misconception", "bridge_to_next": "contrast"},
                            {"beat_id": "B2", "role": "twist", "purpose": "Present the newly uncovered data", "bridge_to_next": "example"},
                            {"beat_id": "B3", "role": "escalation", "purpose": "Show the real-world consequence", "bridge_to_next": "answer-to-question"},
                            {"beat_id": "B4", "role": "payoff", "purpose": "Provide the true principle", "bridge_to_next": "loop-back"},
                            {"beat_id": "B5", "role": "close", "purpose": "Invite comment debate", "bridge_to_next": "none"},
                        ]),
                        target_duration_range="20-30s",
                        target_sentence_count=4,
                    ),
                ]
                session.add_all(default_structures)

            # Seed Title Formulas
            if session.query(TitleFormula).count() == 0:
                default_titles = [
                    TitleFormula(
                        formula_type="how_mechanism",
                        structure_pattern="How [Entity] [Action With Surprising Adverb] in [Year]",
                        example_abstract="How Engineers Cut Model Compute by 80% in 2026",
                    ),
                    TitleFormula(
                        formula_type="curiosity_question",
                        structure_pattern="Why [Familiar Thing] Actually [Counterintuitive Verb]",
                        example_abstract="Why Liquid Ocean Planets Never Freeze Solid",
                    ),
                    TitleFormula(
                        formula_type="financial_breakdown",
                        structure_pattern="The Real Reason [Company] Lost [Dollar Amount] Overnight",
                        example_abstract="The Real Reason Tech Giants Pivoted to Nuclear Power",
                    ),
                ]
                session.add_all(default_titles)

            # Seed Format Stats
            if session.query(FormatStats).count() == 0:
                default_stats = [
                    FormatStats(niche="ai_tech", ideal_duration_range="25-32s", ideal_wpm=175.0, cut_frequency=2.5, hashtag_count=4),
                    FormatStats(niche="business", ideal_duration_range="28-35s", ideal_wpm=165.0, cut_frequency=3.0, hashtag_count=4),
                    FormatStats(niche="space_science", ideal_duration_range="22-30s", ideal_wpm=170.0, cut_frequency=2.8, hashtag_count=5),
                ]
                session.add_all(default_stats)

            session.commit()
        finally:
            session.close()

    def get_hook_patterns(self) -> list[HookPattern]:
        session = self.db_mgr.session()
        try:
            return session.query(HookPattern).all()
        finally:
            session.close()

    def get_structure_template(self, name: str = "high_tension_escalation") -> StructureTemplate | None:
        session = self.db_mgr.session()
        try:
            return session.query(StructureTemplate).filter(StructureTemplate.name == name).first()
        finally:
            session.close()

    def extract_pattern_from_outlier(self, outlier: ReferenceVideo) -> tuple[HookPattern | None, str]:
        """Abstracts title structure without copying words. Enforces the <= 4-word overlap rule."""
        title = outlier.title
        # Detect structure
        has_number = any(c.isdigit() for c in title)
        is_question = "?" in title or any(title.lower().startswith(w) for w in ["why", "how", "what", "who"])

        if is_question and has_number:
            pattern_type = "quantitative_question"
            template = "Why did [Entity] reach [Number] before anyone noticed?"
        elif is_question:
            pattern_type = "mechanism_inquiry"
            template = "Why [System] behaves completely differently under [Condition]."
        elif has_number:
            pattern_type = "scale_metric"
            template = "The exact reason [Entity] generated [Number] in [Timeframe]."
        else:
            pattern_type = "paradox"
            template = "How [Simple Action] triggered a massive shift across [Domain]."

        # Validate against reference title
        is_valid, violation = check_word_overlap(template, [title], max_consecutive_words=4)
        if not is_valid:
            logger.warning(f"Pattern abstraction violated 4-word rule on '{violation}'. Reverting to safe default.")
            template = "[Surprising Observation] reveals how [Subject] actually operates."

        session = self.db_mgr.session()
        try:
            existing = session.query(HookPattern).filter(HookPattern.template_text == template).first()
            if not existing:
                new_pat = HookPattern(
                    pattern_type=pattern_type,
                    template_text=template,
                    example_text=f"Abstracted from outlier #{outlier.id}",
                )
                session.add(new_pat)
                session.commit()
                session.refresh(new_pat)
                return new_pat, template
            return existing, template
        finally:
            session.close()
