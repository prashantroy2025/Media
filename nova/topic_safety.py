"""Topic Safety and Compliance Filter Engine for Nova Autopilot v6.0."""

from __future__ import annotations

import re
from typing import Any

import spacy

try:
    nlp = spacy.load("en_core_web_sm")
except Exception:
    import en_core_web_sm
    nlp = en_core_web_sm.load()

# Political figures, institutions, and partisan election keywords
POLITICAL_KEYWORDS = {
    "trump", "donald trump", "biden", "joe biden", "harris", "kamala harris",
    "vance", "jd vance", "obama", "desantis", "newsom", "schumer", "mcconnell",
    "pelosi", "lutnick", "howard lutnick", "gaetz", "hegseth", "rfk", "robert f kennedy",
    "republican", "republicans", "democrat", "democrats", "gop", "dnc",
    "white house", "capitol hill", "congress", "senate hearing", "senate", "senator", "senators",
    "election", "elections", "presidential campaign", "ballot", "voting",
    "impeachment", "partisan", "super pac", "political fallout"
}

# Legal accusations, criminal investigations, and scandal terms targeting named individuals
LEGAL_SCANDAL_KEYWORDS = {
    "indicted", "indictment", "arrested", "arrest", "subpoena", "subpoenaed",
    "lawsuit", "sued for", "prosecutor", "prosecution", "department of justice",
    "doj investigation", "scandal fallout", "accused of fraud", "criminal charges",
    "anti-competitive practices", "ethics violation", "bribery", "corruption investigation",
    "fraud", "hearing", "accuses", "accused", "reckless", "negligent", "allegations",
    "misconduct", "fraudulent"
}

# Crime, violence, tragedies, and fatalities
VIOLENCE_TRAGEDY_KEYWORDS = {
    "murder", "murdered", "shooting", "shooter", "mass shooting", "homicide",
    "suicide", "massacre", "terrorist", "terrorism", "hostage", "fatal crash",
    "plane crash death", "deadly collapse", "casualties", "fatality", "fatalities",
    "killed", "kill", "killing", "dead", "death", "deaths", "tragic", "tragedy", "fatal"
}

# Prohibited speculative financial and medical advice claims
ADVICE_CLAIMS_KEYWORDS = {
    "buy this stock", "sell this stock", "stock pick", "guaranteed profit",
    "guaranteed return", "10x your money", "get rich quick", "financial advice",
    "price target", "miracle cure", "cures cancer", "prevent disease naturally"
}

# Opinion and outrage clickbait markers
OPINION_MARKERS = {
    "opinion:", "editorial:", "column:", "why you should be outraged",
    "why everyone is furious", "the internet is slamming"
}


class TopicSafetyEvaluator:
    """Evaluates topic safety against strict editorial guidelines."""

    def __init__(self):
        pass

    def evaluate(self, title: str, summary: str = "", niche: str = "ai_tech") -> tuple[bool, str, dict[str, Any]]:
        """Evaluates whether a topic is safe to produce into an educational factual short.

        Returns (is_safe, reason, metadata).
        """
        combined_text = f"{title}. {summary}".strip()
        text_lower = combined_text.lower()

        # 1. Opinion / Outrage check
        for om in OPINION_MARKERS:
            if om in text_lower:
                return False, f"Opinion/outrage framing detected ('{om}')", {"category": "opinion"}

        # 2. Violence & Tragedy check
        for vk in VIOLENCE_TRAGEDY_KEYWORDS:
            if re.search(r"\b" + re.escape(vk) + r"\b", text_lower):
                return False, f"Violence or tragedy content detected ('{vk}')", {"category": "violence_tragedy"}

        # 3. Financial & Medical Advice claims
        for ak in ADVICE_CLAIMS_KEYWORDS:
            if re.search(r"\b" + re.escape(ak) + r"\b", text_lower):
                return False, f"Prohibited advice or speculative claim detected ('{ak}')", {"category": "advice_claim"}

        # 4. Political figures & Partisan scandals
        doc = nlp(title)
        ents = {e.text.lower(): e.label_ for e in doc.ents}

        # Check keyword matches
        matched_political = [pk for pk in POLITICAL_KEYWORDS if re.search(r"\b" + re.escape(pk) + r"\b", text_lower)]
        matched_legal = [lk for lk in LEGAL_SCANDAL_KEYWORDS if re.search(r"\b" + re.escape(lk) + r"\b", text_lower)]

        if matched_political:
            # If political figure combined with scandal/fallout/hearing/investigation -> HARD REJECT
            if matched_legal or any(w in text_lower for w in ["scandal", "fallout", "accused", "hearing", "pressure grows", "investigation"]):
                return (
                    False,
                    f"Political scandal or controversy involving named figure ({matched_political[0]})",
                    {"category": "political_scandal", "figures": matched_political, "legal": matched_legal},
                )
            # Named politicians on our channel are barred from news shorts
            return (
                False,
                f"Topic focuses on politician or partisan politics ('{matched_political[0]}')",
                {"category": "politician", "figures": matched_political},
            )

        if matched_legal:
            return (
                False,
                f"Topic focuses on active legal dispute or scandal ('{matched_legal[0]}')",
                {"category": "legal_scandal", "terms": matched_legal},
            )

        # 5. Entity check: PERSON entity with legal/accusation vocabulary
        person_ents = [text for text, label in ents.items() if label == "PERSON"]
        if person_ents:
            accusation_words = [
                "scandal", "accused", "fired", "investigated", "probe", "lawsuit", "fallout",
                "reckless", "negligent", "blamed", "blame", "corrupt", "misled", "fraud", "allegations"
            ]
            if any(aw in text_lower for aw in accusation_words):
                return (
                    False,
                    f"Accusation or controversy targeting named individual ('{person_ents[0]}')",
                    {"category": "personal_accusation", "person": person_ents[0]},
                )

        return True, "Safe factual topic", {"category": "clean"}


def evaluate_topic_safety(title: str, summary: str = "", niche: str = "ai_tech") -> tuple[bool, str, dict[str, Any]]:
    """Helper functional wrapper for TopicSafetyEvaluator."""
    evaluator = TopicSafetyEvaluator()
    return evaluator.evaluate(title, summary, niche)
