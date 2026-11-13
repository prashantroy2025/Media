"""Unit tests for NicheScheduler and NicheLearningLoop."""

from datetime import UTC, datetime

from nova.config import NovaSettings
from nova.db import DatabaseManager, Script
from nova.niches import NicheLearningLoop, NicheScheduler


def test_no_more_than_two_consecutive(tmp_path):
    db_file = tmp_path / "test_niche.db"
    db_mgr = DatabaseManager(db_file)
    settings = NovaSettings()
    scheduler = NicheScheduler(settings, db_mgr)

    session = db_mgr.session()
    # Add 2 consecutive 'ai_tech' scripts
    session.add(Script(title="AI 1", hook="Hook 1", scenes_json="[]", niche="ai_tech"))
    session.add(Script(title="AI 2", hook="Hook 2", scenes_json="[]", niche="ai_tech"))
    session.commit()
    session.close()

    # Next niche MUST NOT be 'ai_tech'
    for _ in range(5):
        next_niche = scheduler.select_next_niche()
        assert next_niche != "ai_tech", f"Disqualified niche 'ai_tech' was selected: {next_niche}"


def test_simulation_100_picks_hits_mix_and_no_triple_repeats(tmp_path):
    db_file = tmp_path / "test_sim.db"
    db_mgr = DatabaseManager(db_file)
    settings = NovaSettings()
    scheduler = NicheScheduler(settings, db_mgr)

    picks = []
    session = db_mgr.session()

    for i in range(100):
        niche = scheduler.select_next_niche()
        picks.append(niche)
        # Record into db
        s = Script(
            title=f"Title {i}",
            hook=f"Hook {i}",
            scenes_json="[]",
            niche=niche,
            created_at=datetime.now(UTC),
        )
        session.add(s)
        session.commit()

    session.close()

    # Verify no 3 consecutive identical niches
    for idx in range(len(picks) - 2):
        assert not (picks[idx] == picks[idx + 1] == picks[idx + 2]), f"Found 3 consecutive {picks[idx]} at index {idx}"

    # Verify target distribution (Target: 50% ai_tech, 25% business, 25% space_science)
    ai_count = picks.count("ai_tech")
    biz_count = picks.count("business")
    space_count = picks.count("space_science")

    # Within reasonable tolerance for 100 picks
    assert 40 <= ai_count <= 60, f"AI count {ai_count} outside expected range [40, 60]"
    assert 18 <= biz_count <= 32, f"Business count {biz_count} outside expected range [18, 32]"
    assert 18 <= space_count <= 32, f"Space count {space_count} outside expected range [18, 32]"


def test_learning_loop_guardrails(tmp_path):
    db_file = tmp_path / "test_guardrails.db"
    db_mgr = DatabaseManager(db_file)
    settings = NovaSettings()
    loop = NicheLearningLoop(settings, db_mgr)

    # 1. With 0 videos, should return defaults
    w = loop.evaluate_and_adjust_weights()
    assert w["ai_tech"] == 0.50
    assert w["business"] == 0.25
    assert w["space_science"] == 0.25

    # 2. Reset weights
    reset_w = loop.reset_weights()
    assert reset_w["ai_tech"] == 0.50
    assert reset_w["business"] == 0.25
    assert reset_w["space_science"] == 0.25
