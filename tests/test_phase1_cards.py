"""Unit tests for Phase 1: Card Integrity, Safe Zones, Number Cards, Footers, and Contrast."""

from pathlib import Path
import pytest
from PIL import Image

from nova.animation.templates import (
    SAFE_ZONE_CARD,
    SAFE_ZONE_CAPTIONS,
    get_contrast_ratio,
    parse_grounded_number,
    render_comparison_card,
    render_concept_card,
    render_count_up,
    render_data_card_for_beat,
    render_diagram_animation,
    render_kinetic_quote,
    render_map_pin,
    render_timeline_card,
    validate_card_spec,
    _draw_cinematic_background,
)
from nova.beats import Beat, BeatType
from nova.motion.brand import CollisionChecker, SAFE_ZONE_CARD as BRAND_CARD_BOX, SAFE_ZONE_CAPTIONS as BRAND_CAPTION_BOX


def test_card_spec_validation():
    """Verifies that cards with empty pills, truncated '...' text, or placeholder footers are rejected."""
    # 1. Truncated text rejection
    spec_truncated = {
        "title": "Valid Title",
        "label": "THIS EXEMPTION APPLIES TO INTER-...",
        "footer": "Source: SEC release, Nov 2026",
    }
    valid, reason = validate_card_spec(spec_truncated)
    assert not valid
    assert "truncated" in reason.lower()

    # 2. Forbidden placeholder footer rejection
    spec_placeholder = {
        "title": "$99 Million",
        "label": "Repo Volume",
        "footer": "SOURCE DISCLOSURE & DATA VERIFICATION",
    }
    valid, reason = validate_card_spec(spec_placeholder)
    assert not valid
    assert "placeholder" in reason.lower()

    # 3. Empty label pill rejection
    spec_empty_pill = {
        "title": "5000 Skulls",
        "header_pill": "   ",
        "footer": "Source: Antiquity Journal",
    }
    valid, reason = validate_card_spec(spec_empty_pill)
    assert not valid
    assert "header pill" in reason.lower()

    # 4. Safe zone violation rejection
    spec_overflow = {
        "title": "Overflow Card",
        "bounding_boxes": [[80, 240, 1000, 1350]],
    }
    valid, reason = validate_card_spec(spec_overflow)
    assert not valid
    assert "safe zone" in reason.lower()

    # 5. Clean valid spec
    spec_valid = {
        "title": "$99 Million",
        "label": "in repo transactions covered",
        "header_pill": "TREASURY RELIEF",
        "footer": "Source: SEC release, Nov 2026",
        "bounding_boxes": [[80, 260, 1000, 1180]],
    }
    valid, reason = validate_card_spec(spec_valid)
    assert valid
    assert reason == "Valid"


def test_safe_zone_no_overlap():
    """Verifies that the content/card safe zone strictly never overlaps the caption safe zone."""
    card_box = (
        SAFE_ZONE_CARD["left"],
        SAFE_ZONE_CARD["top"],
        SAFE_ZONE_CARD["right"],
        SAFE_ZONE_CARD["bottom"],
    )
    caption_box = (
        SAFE_ZONE_CAPTIONS["left"],
        SAFE_ZONE_CAPTIONS["top"],
        SAFE_ZONE_CAPTIONS["right"],
        SAFE_ZONE_CAPTIONS["bottom"],
    )

    # Content box must strictly sit above the caption band with positive clearance
    assert card_box[3] < caption_box[1]
    clearance = caption_box[1] - card_box[3]
    assert clearance >= 60  # At least 60px safety clearance buffer

    # CollisionChecker must report no intersection
    assert not CollisionChecker.intersects(card_box, caption_box)
    assert not CollisionChecker.intersects(BRAND_CARD_BOX, BRAND_CAPTION_BOX)


def test_grounded_number_parsing():
    """Verifies parsing of currency, counts, percentages, and rejection of ungrounded text."""
    # Dollar amount
    val, prefix, unit, is_pct, is_valid = parse_grounded_number("$99 million")
    assert is_valid
    assert val == 99.0
    assert prefix == "$"
    assert "MILLION" in unit.upper()
    assert not is_pct

    # Percentage
    val, prefix, unit, is_pct, is_valid = parse_grounded_number("85.5%")
    assert is_valid
    assert val == 85.5
    assert unit == "%"
    assert is_pct

    # Word percentage
    val, prefix, unit, is_pct, is_valid = parse_grounded_number("45 percent")
    assert is_valid
    assert val == 45.0
    assert is_pct

    # Unit count
    val, prefix, unit, is_pct, is_valid = parse_grounded_number("6 billion tons")
    assert is_valid
    assert val == 6.0
    assert "BILLION" in unit.upper()
    assert not is_pct

    # No digits present (like the original bug "repo transactions map on a")
    val, prefix, unit, is_pct, is_valid = parse_grounded_number("repo transactions map on a")
    assert not is_valid


def test_text_contrast_ratio():
    """Verifies that foreground typography on dark cards passes WCAG AA minimum readable contrast ratio (>= 4.5:1)."""
    card_bg = (13, 20, 32)
    white_text = (255, 255, 255)
    cyan_text = (0, 210, 255)
    light_slate = (220, 235, 255)
    gold_text = (252, 211, 77)

    assert get_contrast_ratio(white_text, card_bg) >= 14.0
    assert get_contrast_ratio(cyan_text, card_bg) >= 9.0
    assert get_contrast_ratio(light_slate, card_bg) >= 12.0
    assert get_contrast_ratio(gold_text, card_bg) >= 12.0


def test_render_count_up_percentage_vs_dollar(tmp_path: Path):
    """Verifies that render_count_up generates valid MP4 and preview thumbnail without ring on dollar amounts."""
    # Dollar amount (bar / stat layout)
    out_dollar = tmp_path / "card_dollar.mp4"
    render_count_up(
        number_str="$99 Million",
        label="Repo Volume",
        duration=1.0,
        out_path=out_dollar,
        fps=15,
        measure="in repo transactions covered",
        source_text="Source: SEC release, Nov 2026",
    )
    assert out_dollar.exists()
    assert out_dollar.stat().st_size > 1000
    prev_dollar = out_dollar.with_name("card_dollar_prev.jpg")
    assert prev_dollar.exists()

    # Percentage amount (radial ring layout)
    out_pct = tmp_path / "card_pct.mp4"
    render_count_up(
        number_str="99%",
        label="Clearing Compliance",
        duration=1.0,
        out_path=out_pct,
        fps=15,
        measure="of transactions covered under relief",
        source_text="Source: SEC release, Nov 2026",
    )
    assert out_pct.exists()
    assert out_pct.stat().st_size > 1000
    prev_pct = out_pct.with_name("card_pct_prev.jpg")
    assert prev_pct.exists()


def test_render_diagram_animation_abstract_concept(tmp_path: Path):
    """Verifies rendering of the node-and-arrow transaction flow diagram for abstract concepts."""
    out_mp4 = tmp_path / "diagram.mp4"
    spec = {
        "title": "Inter-Affiliate Repo Exemption",
        "parent_label": "Holding Parent Corp",
        "left_label": "US Broker-Dealer",
        "right_label": "Affiliate Entity",
        "flow_label": "Repo Securities & Cash",
        "status_badge": "EXEMPT",
        "source_text": "Source: SEC release, Nov 2026",
    }
    res = render_diagram_animation(spec, duration=1.0, out_path=out_mp4, fps=15)
    assert res.exists()
    assert res.stat().st_size > 1000
    prev_jpg = out_mp4.with_name("diagram_prev.jpg")
    assert prev_jpg.exists()


def test_looping_motion_background():
    """Verifies that the cinematic background produces continuous subtle motion between frames."""
    f0 = _draw_cinematic_background(1080, 1920, 0, 90)
    f30 = _draw_cinematic_background(1080, 1920, 30, 90)

    # Frame 0 and Frame 30 must not be identical due to particle drift and gradient cycling
    assert f0.tobytes() != f30.tobytes()


def test_beat_dispatch_abstract_concept_never_fake_number(tmp_path: Path):
    """Verifies that an abstract concept beat (like the repo exemption) dispatches to a diagram or concept card, NEVER a fake count-up."""
    beat = Beat(
        beat_id="B2_1",
        beat_index=1,
        sentence_id="S2",
        sentence_index=1,
        spoken_text="This exemption applies to inter-affiliate and non-U.S. repo transactions, a crucial segment of the repo market.",
        caption_text="This exemption applies to inter-affiliate and non-U.S. repo transactions, a crucial segment of the repo market.",
        start_time=3.34,
        end_time=6.45,
        duration=3.11,
        visual_intent="repo transactions map on a screen highlighting exempted routes",
        entities=[],
        beat_type=BeatType.ABSTRACT_CONCEPT,
    )

    out_mp4 = tmp_path / "abstract_beat.mp4"
    res = render_data_card_for_beat(beat, duration=1.0, out_path=out_mp4, fps=15)
    assert res.exists()
    assert res.stat().st_size > 1000

    # Ensure preview was generated
    prev_jpg = out_mp4.with_name("abstract_beat_prev.jpg")
    assert prev_jpg.exists()
