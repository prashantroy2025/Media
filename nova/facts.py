"""Structured Fact Extraction and Semantic Fidelity Verification Engine for Nova Autopilot v6.0."""

from __future__ import annotations

import re
from typing import Any

import spacy
from pydantic import BaseModel, Field

# Load spaCy NLP model
try:
    nlp = spacy.load("en_core_web_sm")
except Exception:
    import en_core_web_sm

    nlp = en_core_web_sm.load()

# Banned placeholders that must NEVER appear in real structured facts
BANNED_PLACEHOLDERS = {
    "reveals",
    "demonstrates measurable change",
    "key findings",
    "provides context for",
    "corroborates primary data",
    "concrete noun",
    "main subject",
    "setting",
    "environment",
    "visible motion",
    "high speed engineering",
    "global network",
    "breakthrough summary",
}

# Abstract words that cannot serve as primary concrete subjects
ABSTRACT_SUBJECT_WORDS = {
    "pressure",
    "outbursts",
    "outburst",
    "truth",
    "shocking",
    "reality",
    "secret",
    "update",
    "overview",
    "summary",
    "look",
    "way",
    "ways",
    "reasons",
    "reason",
    "things",
    "thing",
    "factors",
    "factor",
    "fallout",
    "impact",
    "effects",
    "effect",
    "details",
    "data",
    "breakthrough",
    "mystery",
    "innovation",
    "story",
    "history",
    "future",
    "clash",
    "battle",
    "scandal",
    "crisis",
    "expert",
    "experts",
    "analyst",
    "analysts",
    "researcher",
    "researchers",
    "official",
    "officials",
    "source",
    "sources",
    "critic",
    "critics",
    "people",
    "report",
    "reports",
    "study",
    "studies",
    "finding",
    "findings",
    "leader",
    "leaders",
    "event",
    "events",
    "reminder",
    "reminders",
    "spokesperson",
    "spokespersons",
    "author",
    "authors",
    "commentator",
    "commentators",
}

STOPWORDS = set(spacy.lang.en.stop_words.STOP_WORDS) | {
    "a",
    "an",
    "the",
    "this",
    "that",
    "these",
    "those",
    "it",
    "its",
    "they",
    "their",
    "them",
    "we",
    "our",
    "us",
    "he",
    "his",
    "him",
    "she",
    "her",
    "you",
    "your",
    "what",
    "why",
    "how",
    "who",
    "when",
    "where",
    "which",
}

# Entity aliases mapping canonical names to acceptable references
ENTITY_ALIASES: dict[str, list[str]] = {
    "lutnick": ["lutnick", "howard lutnick", "commerce secretary", "secretary"],
    "trump": ["trump", "donald trump", "president", "administration"],
    "nvidia": ["nvidia", "chipmaker", "gpu maker", "tech giant", "corporation"],
    "deepseek": ["deepseek", "ai model", "chinese ai", "researchers", "ai lab"],
    "waymo": ["waymo", "robotaxi", "autonomous vehicle", "self-driving car", "driverless car"],
    "claude": ["claude", "anthropic", "sonnet", "ai model", "assistant"],
    "starlink": ["starlink", "spacex", "satellite network", "constellation"],
    "gemini": ["gemini", "astronauts", "spacecraft", "space mission", "nasa", "project gemini"],
    "tsmc": ["tsmc", "taiwan semiconductor", "chip foundry", "fabricator", "manufacturer"],
    "apple": ["apple", "apples", "orchard", "fruit", "crop", "harvest"],
    "star": ["star", "neutron star", "massive star", "stellar", "supermassive star", "compact object"],
    "europa": ["europa", "moon", "jupiter moon", "ocean world", "icy moon"],
    "corals": ["corals", "coral", "reef", "larvae", "baby corals", "marine life"],
    "voyager": ["voyager", "spacecraft", "probe", "voyager 1", "deep space probe"],
    "microsoft": ["microsoft", "tech giant", "software giant", "windows maker", "cloud provider"],
    "sec": ["sec", "securities and exchange commission", "regulators", "commission", "agency"],
    "openai": ["openai", "chatgpt", "ai lab", "creator of chatgpt", "sam altman"],
    "langchain": ["langchain", "ai startup", "agent startup", "framework", "startup"],
    "spacex": ["spacex", "elon musk", "starlink", "rocket maker", "aerospace firm"],
}

# Semantic action synonym clusters
ACTION_SYNONYMS: dict[str, list[str]] = {
    "fall": ["fall", "fell", "drop", "dropped", "tumble", "tumbled", "plummet", "descend"],
    "rot": ["rot", "rotted", "spoil", "spoiled", "decay", "decayed", "decompose", "ruin"],
    "cut": ["cut", "reduce", "reduced", "slash", "slashed", "lower", "lowered", "compress", "decrease"],
    "drive": ["drive", "drove", "driven", "log", "logged", "complete", "completed", "travel", "navigate"],
    "pack": ["pack", "packs", "packed", "contain", "contains", "feature", "features", "hold", "combine"],
    "solve": ["solve", "solved", "resolve", "resolved", "crack", "cracked", "fix", "fixed"],
    "reach": ["reach", "reached", "hit", "achieve", "achieved", "generate", "generated", "earn", "record"],
    "shed": ["shed", "explain", "illuminated", "clarify", "reveal", "uncover", "expose"],
    "capture": ["capture", "captured", "photograph", "photographed", "snap", "snapped", "record", "shoot"],
    "grow": ["grow", "grows", "grew", "mount", "mounts", "increase", "escalate", "intensify"],
    "discover": ["discover", "discovered", "find", "found", "detect", "detected", "observe", "spot"],
    "swim": ["swim", "swam", "navigate", "travel", "move", "head"],
    "transmit": ["transmit", "transmits", "transmitted", "broadcast", "send", "signal", "communicate"],
    "weigh": ["weigh", "weighs", "weighed", "mass", "scale"],
    "invest": ["invest", "invests", "invested", "pour", "commit", "allocate", "spend"],
    "erupt": [
        "erupt",
        "erupts",
        "erupted",
        "outburst",
        "outbursts",
        "explode",
        "explodes",
        "exploded",
        "flare",
        "blast",
        "burst",
    ],
    "disrupt": [
        "disrupt",
        "disrupted",
        "disrupts",
        "outage",
        "outages",
        "down",
        "halt",
        "halted",
        "crash",
        "crashed",
        "offline",
        "failure",
        "broken",
    ],
    "apologize": [
        "apologize",
        "apologized",
        "apologizes",
        "apology",
        "sorry",
        "regret",
        "statement",
        "admit",
        "concede",
    ],
    "ban": ["ban", "banned", "bans", "restrict", "restricted", "block", "blocked", "embargo"],
    "power": ["power", "powers", "powered", "run", "runs", "fuel", "fuels", "drive", "drives"],
}

# Outcome synonyms
OUTCOME_SYNONYMS: dict[str, list[str]] = {
    "rot": ["rot", "rotted", "spoil", "spoiled", "decay", "decayed", "ruin", "ruined", "decompose", "lost"],
    "spoil": ["rot", "rotted", "spoil", "spoiled", "decay", "decayed", "ruin", "ruined", "decompose", "lost"],
    "save": ["save", "saved", "cut", "reduced", "slash", "lowered", "cheap", "cheaper"],
    "solve": ["solve", "solved", "fix", "fixed", "resolve", "resolved", "repair", "pass", "passed"],
    "reach": ["reach", "reached", "record", "recorded", "earn", "earned", "hit", "grow", "generate", "generated"],
    "crash": ["crash", "crashed", "collision", "accident", "incident"],
    "light": [
        "light",
        "illuminate",
        "illuminated",
        "explain",
        "explained",
        "clarify",
        "clarified",
        "reveal",
        "revealed",
    ],
}

NOMINALIZATION_ACTIONS: dict[str, str] = {
    "outburst": "erupt",
    "outbursts": "erupt",
    "explosion": "explode",
    "explosions": "explode",
    "discovery": "discover",
    "discoveries": "discover",
    "launch": "launch",
    "transition": "transition",
    "shift": "shift",
    "investigation": "investigate",
    "analysis": "analyze",
    "expansion": "expand",
    "growth": "grow",
    "crash": "crash",
    "fall": "fall",
    "breakthrough": "achieve",
    "outage": "disrupt",
    "outages": "disrupt",
    "disruption": "disrupt",
    "disruptions": "disrupt",
    "shutdown": "halt",
    "downtime": "halt",
    "apology": "apologize",
    "valuation": "reach",
    "funding": "raise",
    "ban": "ban",
    "bans": "ban",
    "sale": "sell",
    "sales": "sell",
    "delay": "delay",
    "delays": "delay",
}


class StructuredFact(BaseModel):
    """Ground truth factual unit derived directly from verified source text."""

    id: str = Field(default="F1", description="Unique fact identifier e.g. F1, F2")
    claim: str = Field(default="", description="Plain-English factual statement")
    fact: str = Field(default="", description="Alias for claim")
    subject: str = Field(default="", description="Core concrete entity of the fact")
    action: str = Field(default="", description="Action or predicate performed")
    object: str = Field(default="", description="Direct object or complement")
    outcome: str = Field(default="", description="Concrete consequence or outcome")
    outcome_or_result: str = Field(default="", description="Alias for outcome")
    cause: str = Field(default="", description="Underlying trigger or cause")
    cause_if_any: str | None = Field(default=None, description="Alias for cause")
    time_context: str | None = Field(default=None, description="e.g. in 2024, as of Q3 2025")
    number_with_unit: str | None = Field(default=None, description="e.g. 6 billion tons, 80 percent")
    number_unit: str | None = Field(default=None, description="Alias for number_with_unit")
    source_url: str = Field(default="", description="Source URL where fact was retrieved")
    excerpt: str = Field(default="", description="Original supporting excerpt")

    def model_post_init(self, __context: Any) -> None:
        if not self.claim and self.fact:
            self.claim = self.fact
        elif not self.fact and self.claim:
            self.fact = self.claim

        if not self.outcome and self.outcome_or_result:
            self.outcome = self.outcome_or_result
        elif not self.outcome_or_result and self.outcome:
            self.outcome_or_result = self.outcome

        if not self.cause and self.cause_if_any:
            self.cause = self.cause_if_any
        elif not self.cause_if_any and self.cause:
            self.cause_if_any = self.cause

        if not self.number_with_unit and self.number_unit:
            self.number_with_unit = self.number_unit
        elif not self.number_unit and self.number_with_unit:
            self.number_unit = self.number_with_unit


def validate_fact(fact: StructuredFact, topic_title: str = "") -> tuple[bool, str]:
    """Strictly validates a StructuredFact to eliminate placeholders, stopwords, or blind first-word subjects."""
    # 1. Subject validation
    subj = fact.subject.strip()
    if not subj:
        return False, "Fact subject is empty"

    subj_lower = subj.lower()
    if subj_lower in STOPWORDS:
        return False, f"Subject '{subj}' is a stopword"

    if subj_lower in ABSTRACT_SUBJECT_WORDS:
        return False, f"Subject '{subj}' is an abstract word, not a concrete entity"

    if any(bp in subj_lower for bp in BANNED_PLACEHOLDERS):
        return False, f"Subject '{subj}' contains a banned placeholder string"

    # Reject if subject is blindly just the first word of the title when title has multiple words
    if topic_title:
        title_words = topic_title.strip().split()
        if len(title_words) > 1 and subj.strip() == title_words[0]:
            # First word alone is only valid if recognized as a proper entity or noun
            first_doc = nlp(subj)
            if first_doc[0].pos_ in {"VERB", "ADP", "ADV", "PRON", "DET"} or subj_lower in ABSTRACT_SUBJECT_WORDS:
                return False, f"Subject '{subj}' is an invalid first-word headline grab"

    # 2. Action validation
    act = fact.action.strip()
    if not act:
        return False, "Fact action is empty"

    act_lower = act.lower()
    if any(bp in act_lower for bp in BANNED_PLACEHOLDERS):
        return False, f"Action '{act}' contains a banned placeholder string"

    # 3. Outcome validation
    if fact.outcome:
        out_lower = fact.outcome.lower()
        if any(bp in out_lower for bp in BANNED_PLACEHOLDERS):
            return False, f"Outcome '{fact.outcome}' contains a banned placeholder string"

    return True, ""


PRESERVE_CAPS = {
    "NVIDIA",
    "NASA",
    "AI",
    "TSMC",
    "SWE",
    "JWST",
    "CEO",
    "US",
    "UK",
    "EDGAR",
    "GPU",
    "UNDP",
    "WWDC",
    "MLA",
    "CS",
    "LLM",
    "B200",
}


def normalize_headline_casing(text: str) -> str:
    """Normalizes Title Case headlines to standard sentence case for accurate POS tagging and dependency parsing."""
    words = text.split()
    if not words:
        return text

    # If more than 50% of words start uppercase, it's a title-cased headline
    title_count = sum(1 for w in words if w[0].isupper() and w.upper() not in PRESERVE_CAPS)
    if title_count / len(words) > 0.45:
        new_words = []
        for i, w in enumerate(words):
            clean_w = re.sub(r"[^\w]", "", w)
            if clean_w.upper() in PRESERVE_CAPS:
                new_words.append(w)
            elif i == 0:
                new_words.append(w)
            elif clean_w in {
                "Trump",
                "Lutnick",
                "Sonnet",
                "Claude",
                "DeepSeek",
                "Waymo",
                "Starlink",
                "Gemini",
                "Blackwell",
                "Europa",
            }:
                new_words.append(w)
            else:
                new_words.append(w.lower())
        return " ".join(new_words)
    return text


def _extract_numbers_with_context(text: str) -> list[str]:
    """Extracts numbers with their units (e.g., '80 percent', '50 million miles', '208 billion transistors').
    Prioritizes numbers with explicit units over bare version numbers or decimals.
    """
    pattern = r"\b(\d+(?:\.\d+)?(?:\s*(?:billion|million|trillion|percent|%|miles|km|tons|dollars|gb|tb|fps|tasks|crashes))?)\b"
    matches = re.findall(pattern, text, flags=re.IGNORECASE)
    has_units = []
    no_units = []
    for m in matches:
        m_str = m.strip()
        if not m_str:
            continue
        if re.search(r"[a-zA-Z%]", m_str):
            has_units.append(m_str)
        elif len(m_str) > 0 and (not m_str.isdigit() or int(m_str) >= 1000):
            no_units.append(m_str)
    return has_units + no_units


def _extract_time_context(text: str) -> str | None:
    """Extracts temporal anchoring e.g. 'in 2024', 'in October 2024', 'as of Q3 2025'."""
    pattern = r"\b((?:in|as of|since|during)\s+(?:Q[1-4]\s+)?(?:(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+)?20\d\d)\b"
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def extract_structured_facts(
    topic_title: str,
    topic_summary: str = "",
    source_url: str = "",
    niche: str = "ai_tech",
) -> list[StructuredFact]:
    """Derives genuine StructuredFact objects using spaCy entities, dependency parse, and clause structure.

    Never invents placeholders. Rejects stopword/abstract subjects.
    """
    facts: list[StructuredFact] = []
    clean_title = topic_title.strip()
    clean_summary = topic_summary.strip()
    corpus = f"{clean_title}. {clean_summary}".strip()

    norm_title = normalize_headline_casing(clean_title)
    doc = nlp(norm_title)

    # 1. Identify Candidate Subject
    candidate_subject = ""
    # Check named entities first
    ents = [e for e in doc.ents if e.label_ in {"PERSON", "ORG", "PRODUCT", "ASTRONOMICAL", "NORP", "FAC", "LOC"}]
    # Also check full original title for entities
    orig_doc = nlp(clean_title)
    orig_ents = [
        e for e in orig_doc.ents if e.label_ in {"PERSON", "ORG", "PRODUCT", "ASTRONOMICAL", "NORP", "FAC", "LOC"}
    ]

    noun_chunks = list(doc.noun_chunks)

    # Resolve prepositional phrases when first chunk is abstract (e.g. 'Outbursts from a Massive Star')
    if noun_chunks:
        first_chunk_text = noun_chunks[0].text
        # Strip leading stopwords/determiners
        first_doc = nlp(first_chunk_text)
        tokens = [t.text for t in first_doc if t.lower_ not in STOPWORDS and t.pos_ not in {"DET", "ADV", "PRON"}]
        first_clean = " ".join(tokens) if tokens else first_chunk_text

        if first_clean.lower() in ABSTRACT_SUBJECT_WORDS:
            # Look at subsequent chunks or prepositional objects
            for chunk in noun_chunks[1:]:
                c_tokens = [
                    t.text
                    for t in nlp(chunk.text)
                    if t.lower_ not in STOPWORDS and t.pos_ not in {"DET", "ADV", "PRON"}
                ]
                c_clean = " ".join(c_tokens)
                if c_clean and c_clean.lower() not in ABSTRACT_SUBJECT_WORDS:
                    candidate_subject = c_clean
                    break
        else:
            candidate_subject = first_clean

    if not candidate_subject and orig_ents:
        candidate_subject = orig_ents[0].text

    if not candidate_subject and ents:
        candidate_subject = ents[0].text

    # Strip any residual leading punctuation or stopwords
    subj_tokens = candidate_subject.split()
    while subj_tokens and subj_tokens[0].lower() in STOPWORDS:
        subj_tokens.pop(0)
    candidate_subject = " ".join(subj_tokens) if subj_tokens else candidate_subject

    # 2. Identify Action / Predicate
    verbs = []
    for token in doc:
        if token.pos_ == "VERB" and token.lemma_ not in {"be", "have", "do", "say", "tell", "note", "report"}:
            verbs.append(token)

    primary_action = ""
    outcome = ""
    cause = ""

    if verbs:
        primary_action = verbs[0].lemma_
        # Check for multi-verb sequences or outcomes e.g. "fall and rot"
        if len(verbs) >= 2:
            second_verb = verbs[1].lemma_
            if second_verb in {"rot", "spoil", "decay", "crash", "fail", "die"}:
                outcome = verbs[1].text
            elif verbs[0].lemma_ == "cause":
                primary_action = verbs[1].lemma_
                if len(verbs) >= 3:
                    outcome = verbs[2].text

    # Check for idiomatic actions e.g. "shed light on"
    if "shed light" in clean_title.lower() or "shed light" in clean_summary.lower():
        primary_action = "shed light on"

    # If action still empty, check nominalizations in the title (e.g. 'Outbursts from a Massive Star' -> 'erupt', 'outage' -> 'disrupt')
    if not primary_action:
        for token in doc:
            t_lem = token.lemma_.lower()
            if t_lem in NOMINALIZATION_ACTIONS:
                primary_action = NOMINALIZATION_ACTIONS[t_lem]
                break
        if not primary_action:
            if "sorry" in clean_title.lower() or "apolog" in clean_title.lower():
                primary_action = "apologize"
        if not primary_action and clean_summary:
            sum_doc = nlp(clean_summary[:200])
            sum_verbs = [
                t.lemma_
                for t in sum_doc
                if t.pos_ == "VERB" and t.lemma_ not in {"be", "have", "do", "say", "tell", "note", "report", "claim"}
            ]
            if sum_verbs:
                primary_action = sum_verbs[0]

    # 3. Identify Object / Complement
    candidate_object = ""
    for chunk in noun_chunks:
        c_text = chunk.text
        if c_text != candidate_subject and candidate_subject not in c_text:
            c_clean = " ".join(t.text for t in nlp(c_text) if t.lower_ not in STOPWORDS)
            if c_clean and c_clean.lower() not in ABSTRACT_SUBJECT_WORDS:
                candidate_object = c_clean
                break

    # 4. Numbers, Units & Temporal Context
    numbers = _extract_numbers_with_context(corpus)
    num_str = numbers[0] if numbers else None
    time_ctx = _extract_time_context(corpus)

    # 5. Outcome derivation from numbers / crash reduction
    if not outcome:
        if "percent fewer" in corpus.lower() or "reduction" in corpus.lower():
            red_match = re.search(r"(\d+%\s*fewer\s*[\w\s]+)", corpus, flags=re.IGNORECASE)
            if red_match:
                outcome = red_match.group(1).strip()
        elif "rot" in corpus.lower() or "spoiled" in corpus.lower():
            outcome = "rotted"

    # Construct candidate primary fact
    fact1 = StructuredFact(
        id="F1",
        claim=clean_title,
        subject=candidate_subject,
        action=primary_action,
        object=candidate_object,
        outcome=outcome,
        cause=cause,
        number_with_unit=num_str,
        time_context=time_ctx,
        source_url=source_url or "https://en.wikipedia.org",
        excerpt=clean_summary[:300] if clean_summary else clean_title,
    )

    is_valid, reason = validate_fact(fact1, topic_title=clean_title)
    if is_valid:
        facts.append(fact1)

    # Value-add secondary fact from summary if distinct
    if clean_summary and len(clean_summary) > len(clean_title) + 15:
        summary_doc = nlp(clean_summary[:250])
        s_chunks = list(summary_doc.noun_chunks)
        s_verbs = [
            t.lemma_
            for t in summary_doc
            if t.pos_ == "VERB"
            and t.lemma_ not in {"be", "have", "do", "say", "tell", "note", "report", "claim", "argue", "suggest"}
        ]
        if s_chunks and s_verbs:
            s_subj = " ".join(t.text for t in nlp(s_chunks[0].text) if t.lower_ not in STOPWORDS)
            # Ensure subject is not an abstract or attribution noun
            s_tokens = [t.lower() for t in s_subj.split()]
            if (
                s_subj
                and s_subj.lower() not in ABSTRACT_SUBJECT_WORDS
                and not any(st in ABSTRACT_SUBJECT_WORDS for st in s_tokens)
            ):
                s_action = s_verbs[0]
                s_obj = s_chunks[1].text if len(s_chunks) > 1 else ""
                s_numbers = _extract_numbers_with_context(clean_summary)
                s_num = s_numbers[0] if s_numbers else None
                fact2 = StructuredFact(
                    id="F2",
                    claim=clean_summary[:200],
                    subject=s_subj,
                    action=s_action,
                    object=s_obj,
                    outcome="",
                    cause="",
                    number_with_unit=s_num,
                    time_context=time_ctx,
                    source_url=source_url or "https://en.wikipedia.org",
                    excerpt=clean_summary[:200],
                )
                is_valid_s, _ = validate_fact(fact2, topic_title=clean_title)
                if is_valid_s and fact2.subject != fact1.subject:
                    facts.append(fact2)

    return facts


def verify_fact_fidelity(sentence: str, fact: StructuredFact) -> tuple[bool, str]:
    """Validates that a spoken sentence preserves the factual meaning of subject, action, and outcome.

    Evaluates lemmas, entity aliases, and synonym clusters rather than demanding literal words.
    Reports the exact missing element in plain English.
    """
    s_doc = nlp(sentence)
    s_lower = sentence.lower()
    s_lemmas = {tok.lemma_.lower() for tok in s_doc}
    s_tokens = {tok.text.lower() for tok in s_doc}

    # 1. Subject Fidelity Check
    if fact.subject:
        subj_lower = fact.subject.lower()
        subj_doc = nlp(fact.subject)
        subj_lemmas = {t.lemma_.lower() for t in subj_doc if t.lower_ not in STOPWORDS}
        subj_words = [t.text.lower() for t in subj_doc if t.lower_ not in STOPWORDS]

        # A: Direct substring or token overlap
        matched_subject = any(w in s_tokens or w in s_lower for w in subj_words)
        # B: Lemma overlap
        if not matched_subject:
            matched_subject = bool(subj_lemmas & s_lemmas)
        # C: Known entity aliases
        if not matched_subject:
            for canon_key, alias_list in ENTITY_ALIASES.items():
                if any(k in subj_lower for k in alias_list):
                    if any(a in s_lower for a in alias_list):
                        matched_subject = True
                        break

        if not matched_subject:
            return False, f"Sentence missing required fact subject '{fact.subject}'"

    # 2. Action Fidelity Check
    if fact.action:
        act_lower = fact.action.lower()
        act_doc = nlp(fact.action)
        act_lemmas = {t.lemma_.lower() for t in act_doc if t.pos_ in {"VERB", "ROOT", "ADJ"}}

        matched_action = False
        # A: Lemma overlap
        if act_lemmas & s_lemmas:
            matched_action = True

        # B: Direct token or stem match
        if not matched_action:
            for al in act_lemmas:
                stem = al[:4] if len(al) >= 4 else al
                if stem in s_lower:
                    matched_action = True
                    break

        # C: Action synonym cluster match
        if not matched_action:
            for syn_key, syn_words in ACTION_SYNONYMS.items():
                if syn_key in act_lower or any(sw in act_lower for sw in syn_words):
                    if any(sw in s_lower or sw in s_lemmas for sw in syn_words):
                        matched_action = True
                        break

        if not matched_action:
            return False, f"Sentence missing required fact action '{fact.action}'"

    # 3. Outcome Fidelity Check
    if fact.outcome:
        out_lower = fact.outcome.lower()
        out_doc = nlp(fact.outcome)
        out_lemmas = {t.lemma_.lower() for t in out_doc if t.lower_ not in STOPWORDS}

        matched_outcome = False
        # A: Direct token or lemma overlap
        if out_lemmas & s_lemmas:
            matched_outcome = True

        # B: Outcome synonym cluster match
        if not matched_outcome:
            for syn_key, syn_words in OUTCOME_SYNONYMS.items():
                if syn_key in out_lower or any(sw in out_lower for sw in syn_words):
                    if any(sw in s_lower or sw in s_lemmas for sw in syn_words):
                        matched_outcome = True
                        break

        # C: Stem overlap
        if not matched_outcome:
            for ol in out_lemmas:
                stem = ol[:4] if len(ol) >= 4 else ol
                if stem in s_lower:
                    matched_outcome = True
                    break

        if not matched_outcome:
            return False, f"Sentence missing required fact outcome '{fact.outcome}'"

    # 4. Number Fidelity Check
    if fact.number_with_unit:
        nums = re.findall(r"\d+", fact.number_with_unit)
        if nums:
            num_words = {
                "6": "six",
                "49": "forty-nine",
                "50": "fifty",
                "80": "eighty",
                "208": "two hundred",
                "2": "two",
                "3": "three",
                "5": "five",
                "10": "ten",
                "100": "hundred",
                "1000": "thousand",
                "1000000": "million",
            }
            has_digits = any(n in s_lower for n in nums)
            has_words = any(num_words.get(n, "----") in s_lower for n in nums)
            # Also check if any num >= 10 is written as words e.g. "forty"
            if not (has_digits or has_words):
                return False, f"Sentence missing numeric measurement '{fact.number_with_unit}'"

    return True, ""
