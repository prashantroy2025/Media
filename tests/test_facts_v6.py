"""Regression tests for v6 Structured Fact Extraction and Semantic Fidelity Verification.

Tests the 8 real topics from user terminal logs:
1. DeepSeek AI training cost reduction
2. NVIDIA Blackwell 208 billion transistors
3. Claude 3.5 Sonnet SWE-bench
4. Starlink 6.6 billion dollars revenue
5. Supermassive neutron star outbursts
6. Lutnick / Trump Commerce Secretary (subject extraction + safety flag)
7. Apple fell and rotted
8. Waymo robotaxi driverless miles
"""

from nova.facts import (
    StructuredFact,
    extract_structured_facts,
    validate_fact,
    verify_fact_fidelity,
)
from nova.topic_safety import evaluate_topic_safety


def test_fact_1_deepseek():
    title = "DeepSeek cuts AI training costs by 80 percent with new architecture"
    facts = extract_structured_facts(title)
    assert len(facts) >= 1
    f = facts[0]
    assert "deepseek" in f.subject.lower()
    assert f.action in {"cut", "reduce", "lower"}
    assert "80" in (f.number_with_unit or "")

    # Valid sentence preserving meaning
    pass_sent = "DeepSeek reduced modern AI training expenses by eighty percent."
    ok, msg = verify_fact_fidelity(pass_sent, f)
    assert ok is True, f"Failed: {msg}"

    # Vague sentence missing action/outcome
    fail_sent = "DeepSeek is an interesting AI lab located overseas."
    ok, _ = verify_fact_fidelity(fail_sent, f)
    assert ok is False


def test_fact_2_nvidia_blackwell():
    title = "Nvidia Blackwell chip packs 208 billion transistors for AI supercomputing"
    facts = extract_structured_facts(title)
    assert len(facts) >= 1
    f = facts[0]
    assert any(term in f.subject.lower() for term in ["nvidia", "blackwell", "chip"])
    assert f.action in {"pack", "feature", "contain", "combine"}
    assert "208 billion" in (f.number_with_unit or "")

    pass_sent = "The new Blackwell processor features over 208 billion transistors."
    ok, msg = verify_fact_fidelity(pass_sent, f)
    assert ok is True, f"Failed: {msg}"

    fail_sent = "Nvidia designs powerful graphics cards for video gamers."
    ok, _ = verify_fact_fidelity(fail_sent, f)
    assert ok is False


def test_fact_3_claude_swebench():
    title = "Claude 3.5 Sonnet resolves 49 percent of SWE-bench engineering issues"
    facts = extract_structured_facts(title)
    assert len(facts) >= 1
    f = facts[0]
    assert any(term in f.subject.lower() for term in ["claude", "sonnet"])
    assert f.action in {"resolve", "solve", "fix"}
    assert "49 percent" in (f.number_with_unit or "") or "49" in (f.number_with_unit or "")

    pass_sent = "Anthropic's Claude solved forty-nine percent of difficult software engineering bugs."
    ok, msg = verify_fact_fidelity(pass_sent, f)
    assert ok is True, f"Failed: {msg}"

    fail_sent = "Claude is a conversational chatbot created by Anthropic."
    ok, _ = verify_fact_fidelity(fail_sent, f)
    assert ok is False


def test_fact_4_starlink_revenue():
    title = "Starlink generated 6.6 billion dollars in revenue as SpaceX expands constellation"
    facts = extract_structured_facts(title)
    assert len(facts) >= 1
    f = facts[0]
    assert "starlink" in f.subject.lower()
    assert f.action in {"generate", "earn", "record", "reach", "hit"}
    assert "6.6 billion" in (f.number_with_unit or "")

    pass_sent = "SpaceX's Starlink earned 6.6 billion dollars from global satellite internet."
    ok, msg = verify_fact_fidelity(pass_sent, f)
    assert ok is True, f"Failed: {msg}"

    fail_sent = "Starlink dishes connect rural customers to the internet."
    ok, _ = verify_fact_fidelity(fail_sent, f)
    assert ok is False


def test_fact_5_neutron_star_outbursts():
    title = "Outbursts from a likely supermassive neutron star shed light on cosmic mysteries"
    facts = extract_structured_facts(title)
    assert len(facts) >= 1
    f = facts[0]
    # Subject must NOT be the abstract noun "Outbursts"
    assert f.subject.lower() != "outbursts"
    assert any(term in f.subject.lower() for term in ["neutron star", "star", "supermassive"])
    assert "shed" in f.action or "erupt" in f.action or "light" in f.action

    pass_sent = "Sudden flares from a supermassive neutron star illuminated key physics behind magnetars."
    ok, msg = verify_fact_fidelity(pass_sent, f)
    assert ok is True, f"Failed: {msg}"

    fail_sent = "Astronomers enjoy looking at night sky constellations through telescopes."
    ok, _ = verify_fact_fidelity(fail_sent, f)
    assert ok is False


def test_fact_6_lutnick_trump_safety_and_extraction():
    title = "Pressure grows on Trump's Commerce Secretary Lutnick in fallout from Nvidia scandal"
    # First, topic safety must reject this topic
    safe, reason, _ = evaluate_topic_safety(title, niche="business")
    assert safe is False
    assert any(term in reason.lower() for term in ["political", "scandal", "lutnick", "trump"])

    # Second, fact extractor must NOT pick "Pressure" as the subject
    facts = extract_structured_facts(title)
    if facts:
        f = facts[0]
        assert f.subject.lower() != "pressure"
        assert any(term in f.subject.lower() for term in ["lutnick", "secretary", "commerce"])


def test_fact_7_apple_fell_and_rotted():
    fact = StructuredFact(
        id="F1",
        claim="The apple fell from the branch and rotted in the orchard.",
        subject="apple",
        action="fell",
        outcome="rotted",
    )
    is_valid, _ = validate_fact(fact)
    assert is_valid is True

    # Valid paraphrase preserving subject, action synonym, outcome synonym
    pass_sent = "After the apple dropped from the branch, it spoiled completely on the grass."
    ok, msg = verify_fact_fidelity(pass_sent, fact)
    assert ok is True, f"Failed: {msg}"

    # Missing outcome
    missing_outcome = "The green apple fell gently through the autumn air."
    ok, msg = verify_fact_fidelity(missing_outcome, fact)
    assert ok is False
    assert "outcome" in msg.lower()

    # Missing action
    missing_action = "The apple rotted while hanging from the branch."
    ok, msg = verify_fact_fidelity(missing_action, fact)
    assert ok is False
    assert "action" in msg.lower()

    # Missing subject
    missing_subj = "The pear dropped from the branch and spoiled on the soil."
    ok, msg = verify_fact_fidelity(missing_subj, fact)
    assert ok is False
    assert "subject" in msg.lower()


def test_fact_8_waymo_robotaxis():
    title = "Waymo robotaxis drove 50 million driverless miles across major cities"
    facts = extract_structured_facts(title)
    assert len(facts) >= 1
    f = facts[0]
    assert any(term in f.subject.lower() for term in ["waymo", "robotaxi", "robotaxis"])
    assert f.action in {"drive", "drove", "log", "complete"}
    assert "50 million" in (f.number_with_unit or "")

    pass_sent = "Autonomous Waymo vehicles logged fifty million driverless miles without safety incidents."
    ok, msg = verify_fact_fidelity(pass_sent, f)
    assert ok is True, f"Failed: {msg}"

    fail_sent = "Self-driving cars are equipped with lidar sensors on the roof."
    ok, _ = verify_fact_fidelity(fail_sent, f)
    assert ok is False


def test_fact_9_microsoft_outage():
    title = "Microsoft 'deeply sorry' for global outage after almost 24 hours of disruption"
    summary = "Experts say the event is a stark reminder of cloud vulnerability."
    facts = extract_structured_facts(title, summary)
    assert len(facts) >= 1
    f = facts[0]
    assert "microsoft" in f.subject.lower()
    assert f.action in {"disrupt", "apologize", "halt"}
    # Subject must NOT be 'Experts'
    assert not any(f.subject.lower() == "experts" for f in facts)

    pass_sent = "Microsoft suffered a global outage that disrupted computer systems worldwide."
    ok, msg = verify_fact_fidelity(pass_sent, f)
    assert ok is True, f"Failed: {msg}"


def test_fact_10_jensen_huang_safety():
    title = "Jensen Huang was reckless with the environment, too"
    safe, reason, flags = evaluate_topic_safety(title)
    assert safe is False
    assert any(term in reason.lower() for term in ["scandal", "reckless", "accusation", "dispute"])
