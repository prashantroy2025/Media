"""Tests for strict business & economics rules, banned phrase detection, and disclaimer enforcement."""

import json
from pathlib import Path
from unittest.mock import MagicMock

from nova.config import load_config
from nova.db import DatabaseManager, Script, Topic, Video
from nova.quality import QualityGate
from nova.scriptwriter import Scriptwriter, StructuredFact


def test_business_banned_phrases_rejected_in_scriptwriter():
    settings = load_config()
    db_mgr = DatabaseManager(":memory:")
    writer = Scriptwriter(settings, db_mgr)

    business_topic = Topic(
        title="NVIDIA Stock Surge Breakdown",
        summary="NVIDIA market cap reaches records",
        source_name="cnbc",
        source_url="https://cnbc.com",
        niche="business",
    )

    bad_script_json = """
    {
      "title": "Why You Must Buy Now",
      "hook": "Why you should buy now before NVIDIA explodes higher.",
      "hook_candidates": ["Why you should buy now before NVIDIA explodes higher."],
      "scenes": [
        {"voiceover": "This stock is guaranteed to bring massive returns so invest now.", "caption": "Invest", "visual_query": "stock trading", "seconds": 10.0},
        {"voiceover": "Top traders say easy money is coming to the moon.", "caption": "Profit", "visual_query": "money", "seconds": 10.0},
        {"voiceover": "Financial advice: get rich quick with this strategy.", "caption": "Rich", "visual_query": "skyscraper", "seconds": 10.0}
      ],
      "cta": "Buy before it is too late!",
      "hashtags": "#Business",
      "description": "Stock tips",
      "facts_used": [{"fact": "NVIDIA revenue grew in 2024", "source_url": "https://cnbc.com"}]
    }
    """

    parsed, _ = writer._validate_and_parse(bad_script_json)
    assert parsed is not None

    facts = [StructuredFact(fact="NVIDIA revenue grew in 2024", source_url="https://cnbc.com")]
    ok, err_msg = writer._verify_and_check(parsed, facts, business_topic)

    assert ok is False
    assert "Banned financial advice phrase detected" in err_msg


def test_business_quality_gate_checks():
    settings = load_config()
    gate = QualityGate(settings)

    # 1. Compliant business script
    good_script = Script(
        title="How TSMC Makes 90% of Advanced Chips",
        hook="How did TSMC quietly take over global chip manufacturing?",
        hook_candidates_json=json.dumps(["How did TSMC quietly take over global chip manufacturing?"]),
        scenes_json=json.dumps(
            [
                {
                    "voiceover": "TSMC manufactures over ninety percent of the world's most advanced microchips.",
                    "visual_query": "semiconductor cleanroom wafer",
                    "seconds": 12.0,
                },
                {
                    "voiceover": "In 2024, verified disclosures showed why their massive foundry moat remains unmatched.",
                    "visual_query": "chip fabrication machine technology",
                    "seconds": 14.0,
                },
            ]
        ),
        cta="What company should we break down next?",
        hashtags="#BusinessStories #Economics",
        description="Analysis of TSMC manufacturing moat.\n\nFor entertainment and education only. Not financial advice.",
        facts_used_json=json.dumps(
            [{"fact": "TSMC manufactures 90% of advanced chips", "source_url": "https://sec.gov"}]
        ),
        niche="business",
    )

    video_good = Video(script=good_script, script_id=1, video_path="mock.mp4", duration_seconds=26.0)
    video_good.attributions = []

    # Mock media duration and frames
    gate._get_media_duration = MagicMock(return_value=26.0)
    gate._extract_frames = MagicMock(return_value=[Path("/tmp/f1.jpg")])
    gate._analyze_visual_frames = MagicMock(return_value=(0.0, None))
    gate._cleanup_temp_dir = MagicMock()

    result_good = gate.evaluate(Path("mock.mp4"), video_good)
    assert result_good.checks["business_compliance"]["passed"] is True

    # 2. Non-compliant business script (missing mandatory disclaimer)
    bad_script = Script(
        title="Why Startup Valuations Shifted in 2024",
        hook="Why did venture valuations shift completely in 2024?",
        hook_candidates_json=json.dumps(["Why did venture valuations shift completely in 2024?"]),
        scenes_json=json.dumps(
            [
                {
                    "voiceover": "Venture capital funding slowed as interest rates remained elevated.",
                    "visual_query": "office boardroom",
                    "seconds": 12.0,
                },
                {
                    "voiceover": "In 2024, startups focused heavily on profitability and operating cash flow.",
                    "visual_query": "financial chart",
                    "seconds": 14.0,
                },
            ]
        ),
        cta="Comment below.",
        hashtags="#Startups",
        description="Overview of 2024 venture markets.",  # Missing disclaimer!
        facts_used_json=json.dumps([{"fact": "Venture funding slowed in 2024", "source_url": "https://cnbc.com"}]),
        niche="business",
    )

    video_bad = Video(script=bad_script, script_id=2, video_path="mock2.mp4", duration_seconds=26.0)
    video_bad.attributions = []

    result_bad = gate.evaluate(Path("mock2.mp4"), video_bad)
    assert result_bad.checks["business_compliance"]["passed"] is False
    assert any("missing mandatory disclaimer" in r for r in result_bad.failure_reasons)
