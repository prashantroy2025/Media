"""Unit tests for Sensitive News Mode and Three-Tier Topic Policy (Nova Autopilot v8.0 Sections 13-19)."""

from datetime import UTC, datetime, timedelta

import pytest

from nova.topic_safety import (
    TopicPolicyDecision,
    TopicSafetyEvaluator,
    check_source_freshness,
    evaluate_neutrality,
    evaluate_title_honesty,
    evaluate_topic_safety,
)


def test_section_17_case_1_sec_fraud_scheme():
    """Case 1: SEC Disclosure of $130M fraud scheme must classify as Tier B Allowed with primary source."""
    title = "SEC Disclosure: Two Entities Charged in $130 Million Fraud Scheme"
    summary = "The Securities and Exchange Commission charged two investment entities with running an unauthorized offering."
    source = "https://www.sec.gov/newsroom/press-releases/2026-1"

    evaluator = TopicSafetyEvaluator()
    decision = evaluator.evaluate(title=title, summary=summary, source_url=source)

    assert decision.tier == "tier_b"
    assert decision.is_allowed is True
    assert decision.requires_manual_approval is True
    assert decision.source_requirements_met is True
    assert "sec.gov" in decision.primary_sources_found


def test_section_17_case_2_sec_examination_priorities():
    """Case 2: Routine regulatory examination priorities must classify as Tier A (Normal Allowed)."""
    title = "SEC Disclosure: SEC Announces Fiscal Year 2027 Examination Priorities"
    summary = "The Division of Examinations today announced its fiscal year 2027 priorities focused on risk assessment."
    source = "https://www.sec.gov/newsroom/press-releases/2026-2"

    evaluator = TopicSafetyEvaluator()
    decision = evaluator.evaluate(title=title, summary=summary, source_url=source)

    assert decision.tier == "tier_a"
    assert decision.is_allowed is True
    assert decision.requires_manual_approval is False


def test_section_17_case_3_nvidia_white_house_scandal():
    """Case 3: Public corporate controversy allowed as Tier B when backed by 2 independent reputable sources."""
    title = "How a sex scandal at Nvidia is putting pressure on the White House"
    summary = "Lawmakers are questioning trade advisory appointments following internal misconduct disclosures."
    sources = [
        "https://www.reuters.com/business/tech/sample-scandal-report",
        "https://www.bloomberg.com/news/articles/2026-sample",
    ]

    evaluator = TopicSafetyEvaluator()
    decision = evaluator.evaluate(title=title, summary=summary, sources_list=sources)

    assert decision.tier == "tier_b"
    assert decision.is_allowed is True
    assert decision.requires_manual_approval is True
    assert decision.source_requirements_met is True
    assert len(decision.reputable_sources_found) >= 2


def test_section_17_case_3_nvidia_scandal_rejected_without_sources():
    """Case 3 Variant: Same story without reputable sources must be rejected from publishing."""
    title = "How a sex scandal at Nvidia is putting pressure on the White House"
    evaluator = TopicSafetyEvaluator()
    decision = evaluator.evaluate(title=title, summary="")

    assert decision.tier == "tier_b"
    assert decision.is_allowed is False
    assert decision.source_requirements_met is False
    assert "insufficient verified sources" in decision.reason.lower()


def test_section_17_case_4_burnham_uk_eu_deal():
    """Case 4: Trade diplomacy policy story allowed as Tier B when backed by government primary or reputable news."""
    title = "Burnham says 'win-win' deal can be agreed between UK and EU"
    summary = "Manchester Mayor Andy Burnham told an economic summit that bilateral agreements are achievable."
    sources = [
        "https://feeds.bbci.co.uk/news/world/rss.xml",
        "https://www.gov.uk/government/news/sample-trade-dialogue",
    ]

    evaluator = TopicSafetyEvaluator()
    decision = evaluator.evaluate(title=title, summary=summary, sources_list=sources)

    assert decision.tier == "tier_b"
    assert decision.is_allowed is True
    assert decision.requires_manual_approval is True
    assert decision.source_requirements_met is True


def test_tier_c_hard_prohibitions():
    """Tier C topics must be strictly blocked regardless of sources."""
    evaluator = TopicSafetyEvaluator()

    # 1. Election advocacy
    d_vote = evaluator.evaluate("Vote for Senator Smith in the upcoming general election")
    assert d_vote.tier == "tier_c"
    assert d_vote.is_allowed is False

    # 2. Unverified rumors
    d_rumor = evaluator.evaluate("Anonymous 4chan poster claims secret AI backdoor inside Apple devices")
    assert d_rumor.tier == "tier_c"
    assert d_rumor.is_allowed is False

    # 3. Personal attack
    d_attack = evaluator.evaluate("Jensen Huang was reckless with the environment, too")
    assert d_attack.tier == "tier_c"
    assert d_attack.is_allowed is False

    # 4. Prohibited financial advice
    d_advice = evaluator.evaluate("Buy this crypto token now for guaranteed 10x profit")
    assert d_advice.tier == "tier_c"
    assert d_advice.is_allowed is False

    # 5. Graphic violence
    d_violence = evaluator.evaluate("Mass shooting leaves 12 dead in city center supermarket")
    assert d_violence.tier == "tier_c"
    assert d_violence.is_allowed is False


def test_neutrality_critic():
    """Script neutrality critic scores text and detects loaded language."""
    neutral_script = (
        "The Securities and Exchange Commission filed civil charges against two corporate entities. "
        "According to the agency's complaint in federal court, the firms raised funds without required registration. "
        "The defendants have not commented publicly and allegations remain unproven in court."
    )
    score_ok, status_msg, loaded_found = evaluate_neutrality(neutral_script)
    assert score_ok <= 1.0
    assert len(loaded_found) == 0
    assert "Passed" in status_msg

    biased_script = (
        "This crooked and evil company executed a disgraceful scam to rob regular investors. "
        "The villain CEO should be in prison right now. Vote for candidates who fight this corruption!"
    )
    score_bad, status_bad, loaded_bad = evaluate_neutrality(biased_script)
    assert score_bad > 1.0
    assert any(term in loaded_bad for term in ["crooked", "evil", "disgraceful", "villain"])


def test_title_honesty_critic():
    """Title honesty ensures title matches script claims and doesn't promise what isn't delivered."""
    title = "SEC Charges Investment Firm with Registration Violations"
    hook = "Federal regulators filed charges against an investment firm today."
    sentences = [
        "The SEC announced today that it filed charges against an investment firm alleging registration violations.",
        "According to court documents, the firm operated without proper licensure.",
    ]
    sources = [
        "The Securities and Exchange Commission today announced charges against an investment company.",
    ]
    ok, reason = evaluate_title_honesty(title, hook, sentences, sources)
    assert ok is True
    assert "honest and grounded" in reason.lower()


def test_source_freshness():
    """Sources must be fresh (<= 48 hours for topic selection)."""
    now = datetime.now(UTC)
    fresh_date = now - timedelta(hours=12)
    old_date = now - timedelta(hours=72)

    is_fresh, msg, age_h = check_source_freshness(fresh_date, max_age_hours=48)
    assert is_fresh is True
    assert 11.0 <= age_h <= 13.0

    is_old, msg_old, age_old = check_source_freshness(old_date, max_age_hours=48)
    assert is_old is False
    assert age_old > 48.0
