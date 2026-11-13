"""Unit tests for topic ranking, scoring weights, and 30-day exclusion."""

from datetime import UTC, datetime, timedelta

from nova.config import load_config
from nova.db import DatabaseManager, Topic
from nova.ranking import TopicRanker


def test_ranking_weights_and_exclusion(tmp_path):
    db_file = tmp_path / "ranking_test.db"
    db_mgr = DatabaseManager(db_file)
    settings = load_config()
    session = db_mgr.session()

    # Topic 1: Highly relevant niche keyword ("AI", "Python", "Developer")
    t1 = Topic(
        dedupe_hash="hash_ai_python",
        title="Python 3.13 AI Developer Toolkit Released",
        summary="Major speed boost for Machine Learning and LLM applications.",
        source_name="rss",
        source_url="https://python.org",
        raw_score=10.0,
        status="pending",
        created_at=datetime.now(UTC),
    )

    # Topic 2: Irrelevant niche
    t2 = Topic(
        dedupe_hash="hash_gardening",
        title="Best Spring Flowers for Balcony Gardening",
        summary="How to grow orchids easily at home.",
        source_name="rss",
        source_url="https://plants.org",
        raw_score=10.0,
        status="pending",
        created_at=datetime.now(UTC),
    )

    # Topic 3: Used 5 days ago (should be skipped by ranker)
    t3 = Topic(
        dedupe_hash="hash_used_recent",
        title="OpenAI GPT Model Architecture Deep Dive",
        summary="Technical analysis.",
        source_name="hackernews",
        source_url="https://example.com",
        raw_score=30.0,
        status="used",
        used_at=datetime.now(UTC) - timedelta(days=5),
        created_at=datetime.now(UTC) - timedelta(days=5),
    )

    session.add_all([t1, t2, t3])
    session.commit()

    ranker = TopicRanker(settings, db_mgr)
    ranked = ranker.rank_topics(limit=5)

    assert len(ranked) >= 2
    # Topic 1 should score significantly higher than Topic 2 due to niche match
    assert ranked[0].id == t1.id
    assert ranked[0].final_score > ranked[1].final_score

    # Topic 3 must not be included because it was used recently
    assert not any(t.id == t3.id for t in ranked)

    session.close()
