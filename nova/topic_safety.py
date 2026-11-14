"""Topic Safety and Compliance Engine for Nova Autopilot v8.0.

Implements Three-Tier Topic Policy:
- Tier A: Normal content (science, tech, evergreen business, routine regulatory/economic news) -> ALLOWED, standard review
- Tier B: Sensitive News Mode (regulatory charges, corporate scandals, trade/politics policy) -> ALLOWED with strict sources, neutrality <= 1.0, and mandatory human approval
- Tier C: Strictly blocked (private individuals, minors, graphic violence/sex, calls to vote/donate, unverified rumors, hate, financial/medical advice)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import spacy
import yaml

from nova.config import PROJECT_ROOT

try:
    nlp = spacy.load("en_core_web_sm")
except Exception:
    import en_core_web_sm

    nlp = en_core_web_sm.load()


def load_topic_policy_config() -> dict[str, Any]:
    """Loads topic policy rules from config/topic_policy.yaml with safe fallbacks."""
    policy_path = PROJECT_ROOT / "config" / "topic_policy.yaml"
    if policy_path.exists():
        try:
            return yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
        except Exception:
            pass
    return {}


POLICY_CONFIG = load_topic_policy_config()


@dataclass
class TopicPolicyDecision:
    """Detailed evaluation result for a topic under v8.0 topic policy."""

    tier: str  # "tier_a", "tier_b", "tier_c"
    is_allowed: bool
    requires_manual_approval: bool
    category: str
    reason: str
    named_entities: list[dict[str, str]] = field(default_factory=list)
    source_requirements_met: bool = True
    primary_sources_found: list[str] = field(default_factory=list)
    reputable_sources_found: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def tier_label(self) -> str:
        if self.tier == "tier_a":
            return "Tier A (Normal)"
        if self.tier == "tier_b":
            return "Tier B (Sensitive News Mode)"
        return "Tier C (Prohibited)"


# --- TIER C PROHIBITED PATTERNS (Run first) ---

# 1. Graphic violence, gruesome injury, suicide, mass tragedy
GRAPHIC_VIOLENCE_TERMS = {
    "murder",
    "murdered",
    "mass shooting",
    "homicide",
    "suicide",
    "massacre",
    "decapitated",
    "mutilated",
    "gruesome death",
    "fatal crash casualties",
    "deadly shooting",
    "blood bath",
    "terror attack dead",
}

# 2. Partisan election advocacy / calls to vote or donate
ELECTION_ADVOCACY_TERMS = {
    "vote for",
    "vote against",
    "cast your ballot for",
    "donate to campaign",
    "defeat at the polls",
    "sign the petition to elect",
    "boycott this company",
    "boycott these products",
    "election was stolen",
    "ballot fraud conspiracy",
}

# 3. Unverified rumors & gossip
UNVERIFIED_RUMOR_TERMS = {
    "anonymous 4chan poster",
    "unverified rumor claims",
    "reddit rumor claims",
    "wild internet conspiracy",
    "unsubstantiated gossip",
    "anonymous tipster claims",
}

# 4. Prohibited financial/medical advice
ADVICE_CLAIMS = {
    "buy this stock now",
    "sell this stock immediately",
    "guaranteed 10x profit",
    "miracle cure for cancer",
    "cures diabetes naturally",
    "get rich overnight",
}

# 5. Salacious/graphic sexual details
EXPLICIT_SEXUAL_TERMS = {
    "explicit sexual act",
    "leaked sex tape",
    "pornographic video",
    "graphic sexual assault",
    "intimate photos leaked",
}

# 6. Unsubstantiated personal attacks / accusations targeting individuals
PERSONAL_ATTACK_TERMS = {
    "reckless with the environment",
    "reckless",
    "crooked executive",
    "evil ceo",
    "unethical billionaire",
    "unsubstantiated accusation",
}


# --- TIER B SENSITIVE NEWS SIGNALS ---

LEGAL_REGULATORY_SIGNALS = {
    "charged with",
    "sec charges",
    "sec disclosure",
    "indicted",
    "indictment",
    "doj charges",
    "department of justice",
    "antitrust lawsuit",
    "sued by",
    "ftc lawsuit",
    "subpoenaed by",
    "settlement of",
    "guilty plea",
    "criminal probe",
    "regulatory action",
    "consent decree",
    "fraud scheme",
    "accounting fraud",
}

POLITICS_TRADE_SIGNALS = {
    "white house",
    "uk-eu deal",
    "uk and eu",
    "uk-eu",
    "trade deal",
    "trade agreement",
    "tariff policy",
    "executive order",
    "senate committee",
    "parliamentary vote",
    "congressional hearing",
    "diplomatic negotiations",
    "minister says",
    "mayor says",
    "prime minister",
    "bilateral agreement",
    "trump",
    "lutnick",
    "biden",
    "commerce secretary",
    "secretary of state",
    "political",
    "political fallout",
}

CORPORATE_SCANDAL_SIGNALS = {
    "whistleblower alleges",
    "misconduct allegations",
    "ethics investigation",
    "corporate scandal",
    "scandal",
    "board ousts ceo",
    "internal investigation reveals",
    "accounting irregularity",
    "probe into executive",
    "controversy",
    "executive misconduct",
}


class TopicSafetyEvaluator:
    """Evaluates topic suitability under the v8 Three-Tier Policy."""

    def __init__(self, policy: dict[str, Any] | None = None):
        self.policy = policy or load_topic_policy_config()
        self.primary_domains = set(
            self.policy.get("sources", {}).get(
                "primary_domains",
                [
                    "sec.gov",
                    "justice.gov",
                    "supremecourt.gov",
                    "courts.gov",
                    "federalreserve.gov",
                    "whitehouse.gov",
                    "gov.uk",
                    "europa.eu",
                    "nasa.gov",
                ],
            )
        )
        self.reputable_domains = set(
            self.policy.get("sources", {}).get(
                "reputable_secondary_domains",
                [
                    "reuters.com",
                    "apnews.com",
                    "bloomberg.com",
                    "ft.com",
                    "wsj.com",
                    "bbc.com",
                    "bbc.co.uk",
                    "cnbc.com",
                    "theguardian.com",
                    "nytimes.com",
                    "nature.com",
                    "science.org",
                    "arxiv.org",
                ],
            )
        )

    def extract_domain(self, url: str) -> str:
        if not url:
            return ""
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        return domain

    def evaluate(
        self,
        title: str,
        summary: str = "",
        niche: str = "ai_tech",
        source_url: str = "",
        sources_list: list[str] | None = None,
        force_allow: bool = False,
    ) -> TopicPolicyDecision:
        """Evaluates a topic using meaning, entity recognition, and tiered compliance."""
        text_corpus = f"{title}. {summary}".strip()
        text_lower = text_corpus.lower()

        doc = nlp(title)
        named_ents = [{"text": ent.text, "type": ent.label_} for ent in doc.ents]

        # Gather sources
        all_sources = list(sources_list or [])
        if source_url and source_url not in all_sources:
            all_sources.append(source_url)

        primary_found = []
        reputable_found = []
        for s in all_sources:
            dom = self.extract_domain(s)
            if any(dom == pd or dom.endswith(f".{pd}") for pd in self.primary_domains):
                primary_found.append(dom)
            elif any(dom == rd or dom.endswith(f".{rd}") for rd in self.reputable_domains):
                reputable_found.append(dom)

        # ---------------------------------------------------------------------
        # TIER C CHECKS (Strict Rejections - Run First)
        # ---------------------------------------------------------------------
        # 1. Graphic violence / tragedies
        for gv in GRAPHIC_VIOLENCE_TERMS:
            if re.search(r"\b" + re.escape(gv) + r"\b", text_lower):
                return TopicPolicyDecision(
                    tier="tier_c",
                    is_allowed=False,
                    requires_manual_approval=False,
                    category="graphic_violence",
                    reason=f"Graphic violence or tragedy detected ('{gv}')",
                    named_entities=named_ents,
                    metadata={"matched": gv},
                )

        # 2. Election advocacy / calls to vote or donate
        for ea in ELECTION_ADVOCACY_TERMS:
            if ea in text_lower:
                return TopicPolicyDecision(
                    tier="tier_c",
                    is_allowed=False,
                    requires_manual_approval=False,
                    category="election_advocacy",
                    reason=f"Political advocacy or voting instructions detected ('{ea}')",
                    named_entities=named_ents,
                    metadata={"matched": ea},
                )

        # 3. Unverified rumors & gossip
        for ur in UNVERIFIED_RUMOR_TERMS:
            if ur in text_lower:
                return TopicPolicyDecision(
                    tier="tier_c",
                    is_allowed=False,
                    requires_manual_approval=False,
                    category="unverified_rumor",
                    reason=f"Unverified rumor or anonymous gossip detected ('{ur}')",
                    named_entities=named_ents,
                    metadata={"matched": ur},
                )

        # 4. Prohibited advice claims
        for ac in ADVICE_CLAIMS:
            if ac in text_lower:
                return TopicPolicyDecision(
                    tier="tier_c",
                    is_allowed=False,
                    requires_manual_approval=False,
                    category="prohibited_advice",
                    reason=f"Prohibited financial or medical advice claim detected ('{ac}')",
                    named_entities=named_ents,
                    metadata={"matched": ac},
                )

        # 5. Salacious sexual details
        for st in EXPLICIT_SEXUAL_TERMS:
            if st in text_lower:
                return TopicPolicyDecision(
                    tier="tier_c",
                    is_allowed=False,
                    requires_manual_approval=False,
                    category="salacious_detail",
                    reason=f"Explicit sexual detail detected ('{st}')",
                    named_entities=named_ents,
                    metadata={"matched": st},
                )

        # 6. Unsubstantiated personal attacks / accusations
        for pa in PERSONAL_ATTACK_TERMS:
            if pa in text_lower:
                return TopicPolicyDecision(
                    tier="tier_c",
                    is_allowed=False,
                    requires_manual_approval=False,
                    category="personal_attack",
                    reason=f"Unsubstantiated personal accusation, reckless claim, or dispute ('{pa}')",
                    named_entities=named_ents,
                    metadata={"matched": pa},
                )

        # 7. Accusations targeting non-public private individuals
        person_names = [e["text"] for e in named_ents if e["type"] == "PERSON"]
        for p in person_names:
            # Check if this person is paired with a private accusation not in public news
            if any(term in text_lower for term in ["arrested for stealing", "accused of cheating", "fired for misconduct"]):
                # If no primary regulator release and no corporate/org entity, reject as private individual controversy
                has_org = any(e["type"] in ["ORG", "GPE", "NORP"] for e in named_ents)
                if not has_org and not primary_found:
                    return TopicPolicyDecision(
                        tier="tier_c",
                        is_allowed=False,
                        requires_manual_approval=False,
                        category="private_individual",
                        reason=f"Personal accusation targeting private individual ('{p}')",
                        named_entities=named_ents,
                        metadata={"target": p},
                    )

        # ---------------------------------------------------------------------
        # TIER B CHECKS (Sensitive News Mode - ALLOWED with Controls)
        # ---------------------------------------------------------------------
        is_legal_regulatory = any(sig in text_lower for sig in LEGAL_REGULATORY_SIGNALS)
        is_politics_trade = any(sig in text_lower for sig in POLITICS_TRADE_SIGNALS)
        is_corp_scandal = any(sig in text_lower for sig in CORPORATE_SCANDAL_SIGNALS)

        # Distinction: Routine examination priorities or standard notices are Tier A!
        is_routine_notice = (
            "examination priorities" in text_lower
            or "annual report" in text_lower
            or "open meeting agenda" in text_lower
            or "quarterly statistics" in text_lower
            or "economic indicators" in text_lower
            or "interest rate decision" in text_lower
        )

        is_tier_b = (is_legal_regulatory or is_politics_trade or is_corp_scandal) and not is_routine_notice

        if is_tier_b or force_allow:
            # Source verification check
            # Rule: At least 1 primary source OR at least 2 independent reputable sources
            has_primary = len(primary_found) >= 1
            has_two_reputable = len(reputable_found) >= 2 or (len(reputable_found) >= 1 and has_primary)
            sources_ok = has_primary or has_two_reputable or force_allow

            matched_signals = [
                s for s in (LEGAL_REGULATORY_SIGNALS | POLITICS_TRADE_SIGNALS | CORPORATE_SCANDAL_SIGNALS)
                if s in text_lower
            ]
            reason = "Sensitive News Mode: Legal, political, or corporate scandal controversy requiring verified attribution."
            if not sources_ok:
                reason = (
                    f"insufficient verified sources: Political, corporate scandal, or legal controversy "
                    f"requires 1 primary or 2 independent reputable sources (matched: {matched_signals})."
                )

            return TopicPolicyDecision(
                tier="tier_b",
                is_allowed=sources_ok,
                requires_manual_approval=True,
                category="sensitive_news",
                reason=reason,
                named_entities=named_ents,
                source_requirements_met=sources_ok,
                primary_sources_found=primary_found,
                reputable_sources_found=reputable_found,
                metadata={
                    "is_legal": is_legal_regulatory,
                    "is_politics": is_politics_trade,
                    "is_scandal": is_corp_scandal,
                    "force_allowed": force_allow,
                },
            )

        # ---------------------------------------------------------------------
        # TIER A: Normal Content (Science, Tech, Evergreen Business, Notices)
        # ---------------------------------------------------------------------
        return TopicPolicyDecision(
            tier="tier_a",
            is_allowed=True,
            requires_manual_approval=False,
            category="normal_factual",
            reason="Standard factual educational topic.",
            named_entities=named_ents,
            source_requirements_met=True,
            primary_sources_found=primary_found,
            reputable_sources_found=reputable_found,
            metadata={"routine_notice": is_routine_notice},
        )


def evaluate_topic_safety(
    title: str,
    summary: str = "",
    niche: str = "ai_tech",
    source_url: str = "",
    sources_list: list[str] | None = None,
    force_allow: bool = False,
) -> tuple[bool, str, dict[str, Any]]:
    """Backward-compatible helper function returning (is_safe, reason, metadata)."""
    evaluator = TopicSafetyEvaluator()
    decision = evaluator.evaluate(
        title=title,
        summary=summary,
        niche=niche,
        source_url=source_url,
        sources_list=sources_list,
        force_allow=force_allow,
    )
    meta = {
        "tier": decision.tier,
        "category": decision.category,
        "requires_manual_approval": decision.requires_manual_approval,
        "named_entities": decision.named_entities,
        "source_requirements_met": decision.source_requirements_met,
        "primary_sources": decision.primary_sources_found,
        "reputable_sources": decision.reputable_sources_found,
    }
    meta.update(decision.metadata)
    return decision.is_allowed, decision.reason, meta


# -----------------------------------------------------------------------------
# SENSITIVE NEWS CRITICS & VERIFICATION (Sections 15 & 16)
# -----------------------------------------------------------------------------

LOADED_LANGUAGE_DICTIONARY = {
    "evil": 3.0,
    "crooked": 2.5,
    "disgraceful": 2.5,
    "traitor": 3.0,
    "criminal scum": 3.5,
    "scumbag": 3.5,
    "villain": 2.5,
    "corrupt": 2.0,
    "disaster": 1.5,
    "shameful": 2.0,
    "heroic": 1.5,
    "saintly": 2.0,
    "destroying": 1.5,
    "idiot": 2.5,
    "fraudster": 2.0,
    "guilty as charged": 3.0,
}

ATTRIBUTION_MARKERS = [
    "according to",
    "alleged",
    "allegedly",
    "charged with",
    "prosecutors say",
    "stated in filings",
    "the agency said",
    "the company said",
    "denies the claims",
    "in a statement",
    "officials noted",
    "faces allegations",
]


def evaluate_neutrality(text: str) -> tuple[float, str, list[str]]:
    """Evaluates script neutrality on a scale of 0.0 (neutral) to 5.0 (loaded).

    Score <= 1.0 is required to pass.
    """
    text_lower = text.lower()
    flagged = []
    penalty_sum = 0.0

    for word, weight in LOADED_LANGUAGE_DICTIONARY.items():
        if re.search(r"\b" + re.escape(word) + r"\b", text_lower):
            flagged.append(word)
            penalty_sum += weight

    # Check for attribution presence
    has_attribution = any(marker in text_lower for marker in ATTRIBUTION_MARKERS)
    if not has_attribution and any(kw in text_lower for kw in ["charged", "fraud", "scandal", "lawsuit"]):
        penalty_sum += 1.5
        flagged.append("unattributed_allegations")

    score = min(5.0, penalty_sum)
    status_msg = "Passed (Neutral framing)" if score <= 1.0 else f"Failed (Loaded language: {', '.join(flagged)})"
    return score, status_msg, flagged


def evaluate_title_honesty(
    title: str,
    hook: str,
    script_sentences: list[str],
    source_excerpts: list[str],
) -> tuple[bool, str]:
    """Ensures title and hook do not make claims unsupported by the script and sources."""
    combined_script = " ".join(script_sentences).lower()
    combined_sources = " ".join(source_excerpts).lower()
    title_lower = title.lower()
    hook_lower = hook.lower()

    # Rule 1: No premature declaration of guilt
    guilt_as_fact = ["is guilty", "proved guilty", "the fraudster behind", "criminals exposed"]
    for gf in guilt_as_fact:
        if gf in title_lower or gf in hook_lower:
            return False, f"Title/hook states guilt as fact ('{gf}'). Must use 'charged' or 'alleged'."

    # Rule 2: All numbers in title/hook must appear in sources/script
    title_nums = re.findall(r"\b\d+(?:,\d+)*(?:\.\d+)?(?:\s*(?:billion|million|trillion|%))?\b", f"{title} {hook}", re.I)
    for num in title_nums:
        digits = re.findall(r"\d+", num)
        if digits and not any(d in combined_sources or d in combined_script for d in digits):
            return False, f"Title/hook contains ungrounded number '{num}' not found in sources."

    return True, "Title and hook are honest and grounded."


def check_source_freshness(published_at: datetime | str | None, max_age_hours: int = 48) -> tuple[bool, str, float]:
    """Ensures Sensitive News Mode topics are <= 48 hours old when selected."""
    if not published_at:
        return True, "Freshness date not provided; assumed current.", 0.0

    if isinstance(published_at, str):
        try:
            pub_dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        except Exception:
            return True, "Could not parse publication timestamp; accepted.", 0.0
    else:
        pub_dt = published_at

    if pub_dt.tzinfo is None:
        pub_dt = pub_dt.replace(tzinfo=UTC)

    now = datetime.now(UTC)
    age_hours = (now - pub_dt).total_seconds() / 3600.0

    if age_hours > max_age_hours:
        return False, f"Topic is stale ({age_hours:.1f} hours old, limit {max_age_hours}h)", age_hours
    return True, f"Topic is fresh ({age_hours:.1f} hours old)", age_hours
