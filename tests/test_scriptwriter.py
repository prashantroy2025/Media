"""Unit tests for Scriptwriter JSON validation, hook scoring, retries, and fact verification."""

from nova.config import load_config
from nova.db import DatabaseManager, Topic
from nova.scriptwriter import Scriptwriter, StructuredFact, _score_hook


def test_schema_parsing_valid():
    valid_json = """
    {
      "title": "A Teaspoon Weighs 6 Billion Tons",
      "hook": "A single teaspoon of a neutron star weighs six billion tons.",
      "hook_candidates": [
        "A single teaspoon of a neutron star weighs six billion tons.",
        "Could you lift a teaspoon of pure star matter?",
        "Why does one spoon of star material crush Earth?",
        "The heaviest teaspoon in the entire universe.",
        "Imagine lifting nine hundred pyramids on your finger."
      ],
      "scenes": [
        {
          "voiceover": "A single teaspoon of a neutron star weighs six billion tons.",
          "caption": "6 Billion Tons",
          "visual_query": "neutron star accretion disk space",
          "seconds": 6.0,
          "key_stat": "6 Billion Tons"
        },
        {
          "voiceover": "That is roughly the weight of nine hundred Great Pyramids stacked together.",
          "caption": "900 Great Pyramids",
          "visual_query": "great pyramids giza desert aerial",
          "seconds": 10.0,
          "key_stat": "900 Pyramids"
        },
        {
          "voiceover": "If you dropped it, it would slice right through our planet like a laser.",
          "caption": "Laser Through Earth",
          "visual_query": "planet earth cosmic impact physics",
          "seconds": 8.0
        }
      ],
      "cta": "Would you survive near this star? Tell me in the comments.",
      "hashtags": "#Shorts #Science #Space #MindBlowing",
      "description": "Neutron star density breakdown.\nSource: https://science.nasa.gov\n[AI Assisted Production]",
      "facts_used": [
        {"fact": "A teaspoon weighs 6 billion tons", "number_unit": "6 billion tons", "source_url": "https://science.nasa.gov"}
      ]
    }
    """
    settings = load_config()
    writer = Scriptwriter(settings, DatabaseManager(":memory:"))
    parsed, err = writer._validate_and_parse(valid_json)

    assert parsed is not None
    assert err == ""
    assert "Teaspoon" in parsed.title
    assert len(parsed.scenes) == 3

    # Test Verification
    topic = Topic(title="Neutron Star Density", summary="Weighs 6 billion tons", source_name="nasa", source_url="url")
    facts = [
        StructuredFact(
            fact="A single teaspoon of a neutron star weighs six billion tons.",
            number_unit="6 billion tons",
            source_url="url",
        )
    ]
    ok, msg = writer._verify_and_check(parsed, facts, topic)
    assert ok is True
    assert msg == "OK"


def test_hook_rubric_scoring():
    # <= 12 words with number and shock word should score high
    hook_good = "A single teaspoon of a neutron star weighs six billion tons."
    # > 12 words should be penalized
    hook_long = "Did you ever wonder in your entire life why stars in deep space can be so very heavy?"

    score_good = _score_hook(hook_good)
    score_long = _score_hook(hook_long)

    assert score_good > score_long
    assert len(hook_good.split()) <= 12


def test_fact_grounding_rejects_hallucinated_numbers():
    bad_facts_json = """
    {
      "title": "Black Hole Discovery",
      "hook": "Scientists found a black hole moving at 9999999 miles per hour.",
      "hook_candidates": ["Scientists found a black hole moving at 9999999 miles per hour."],
      "scenes": [
        {"voiceover": "A black hole is flying at 9999999 miles per hour towards us.", "caption": "Danger", "visual_query": "black hole", "seconds": 10.0},
        {"voiceover": "It has 888888 solar masses destroying everything in its path.", "caption": "Massive", "visual_query": "stars", "seconds": 10.0},
        {"voiceover": "This will happen in 777777 days.", "caption": "Countdown", "visual_query": "space", "seconds": 10.0}
      ],
      "cta": "Comment your thoughts below.",
      "hashtags": "#Space",
      "description": "Black hole breakdown",
      "facts_used": [{"fact": "Real fact about a 5 solar mass star", "source_url": "http://nasa.gov"}]
    }
    """
    settings = load_config()
    writer = Scriptwriter(settings, DatabaseManager(":memory:"))
    parsed, _ = writer._validate_and_parse(bad_facts_json)
    assert parsed is not None

    topic = Topic(title="Black hole", summary="Summary", source_name="src", source_url="url")
    facts = [
        StructuredFact(
            fact="A black hole was discovered with 5 solar masses.", number_unit="5 solar masses", source_url="url"
        )
    ]

    ok, msg = writer._verify_and_check(parsed, facts, topic)
    assert ok is False
    assert "unsupported numbers" in msg.lower()


def test_banned_topics_rejection():
    bad_json = """
    {
      "title": "Guaranteed profit in cryptocurrency",
      "hook": "Here is how to get guaranteed profit today.",
      "hook_candidates": ["Here is how to get guaranteed profit today."],
      "scenes": [
        {"voiceover": "Use this robot for guaranteed profit and financial advice.", "caption": "Free Cash", "visual_query": "money", "seconds": 10.0},
        {"voiceover": "You will make millions with financial advice.", "caption": "Cash", "visual_query": "money", "seconds": 10.0},
        {"voiceover": "Follow me for more financial advice.", "caption": "Profit", "visual_query": "money", "seconds": 10.0}
      ],
      "cta": "Join now!",
      "hashtags": "#Crypto",
      "description": "Trading bots",
      "facts_used": [{"fact": "crypto", "source_url": "http://bad.com"}]
    }
    """
    settings = load_config()
    writer = Scriptwriter(settings, DatabaseManager(":memory:"))
    parsed, _ = writer._validate_and_parse(bad_json)
    assert parsed is not None

    topic = Topic(title="Bad", summary="Bad", source_name="src", source_url="url")
    facts = [StructuredFact(fact="Crypto", source_url="url")]
    ok, msg = writer._verify_and_check(parsed, facts, topic)
    assert ok is False
    assert "banned topic" in msg.lower()


def test_fallback_template():
    settings = load_config()
    writer = Scriptwriter(settings, DatabaseManager(":memory:"))
    topic = Topic(
        title="Neutron Star Superdense Physics",
        summary="A single teaspoon weighs six billion tons on Earth.",
        source_name="nasa",
        source_url="https://science.nasa.gov",
    )
    facts = [
        StructuredFact(
            fact="A single teaspoon weighs six billion tons.",
            number_unit="6 billion tons",
            source_url="https://science.nasa.gov",
        )
    ]
    fallback = writer._fallback_template(topic, facts)
    assert fallback is not None
    assert fallback.is_template is True
    assert "Neutron Star" in fallback.title or "Shocking" in fallback.title
    assert len(fallback.scenes) >= 3
    assert len(fallback.hook.split()) <= 12
    assert fallback.facts_used[0].source_url == "https://science.nasa.gov"


def test_generation_failure_raises_error_no_template():
    import pytest

    from nova.scriptwriter import ScriptGenerationFailedError

    settings = load_config()
    writer = Scriptwriter(settings, DatabaseManager(":memory:"))
    # Force _call_llm to return empty or garbage
    writer._call_llm = lambda *args, **kwargs: "invalid json string"

    topic = Topic(
        title="Valid Science Topic",
        summary="A single teaspoon of a neutron star weighs six billion tons.",
        source_name="nasa",
        source_url="https://science.nasa.gov",
    )
    with pytest.raises(ScriptGenerationFailedError) as exc_info:
        writer.generate_script(topic, num_candidates=1)
    assert "refusing to ship generic template" in str(exc_info.value).lower()
