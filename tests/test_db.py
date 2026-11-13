"""Unit tests for database models, migrations, and deduplication logic."""

from nova.collectors.base import RawTopic
from nova.db import DatabaseManager, Script, Topic


def test_database_initialization(tmp_path):
    db_file = tmp_path / "test_nova.db"
    db_mgr = DatabaseManager(db_file)
    session = db_mgr.session()

    # Create Topic
    topic = Topic(
        dedupe_hash="test_hash_123",
        title="AI Agents Revolution 2026",
        summary="Autonomous coding agents in Python.",
        source_name="hackernews",
        source_url="https://news.ycombinator.com/item?id=123",
        region="IN",
        raw_score=25.0,
        final_score=40.0,
        status="pending",
    )
    session.add(topic)
    session.commit()

    retrieved = session.query(Topic).filter(Topic.dedupe_hash == "test_hash_123").first()
    assert retrieved is not None
    assert retrieved.title == "AI Agents Revolution 2026"
    assert retrieved.status == "pending"

    # Create Script linked to Topic
    script = Script(
        topic_id=retrieved.id,
        title="AI Agents Changed Everything!",
        hook="Bhai suno! Coding completely change ho chuki hai.",
        scenes_json='[{"voiceover": "Intro line", "caption": "Coding AI", "visual_query": "code", "seconds": 5.0}]',
        cta="Follow @NovaPrashantroy!",
        hashtags="#AI #Tech",
        description="Full breakdown",
        facts_used_json='[{"fact": "AI writes code", "source_url": "https://example.com"}]',
    )
    session.add(script)
    session.commit()

    assert len(retrieved.scripts) == 1
    assert retrieved.scripts[0].get_scenes()[0]["caption"] == "Coding AI"
    assert retrieved.scripts[0].get_facts_used()[0]["fact"] == "AI writes code"

    session.close()


def test_dedupe_hash_consistency():
    t1 = RawTopic(
        title="  Breakthrough in Quantum Computing Announced!  ",
        summary="Summary 1",
        source_name="source_a",
        source_url="https://a.com",
    )
    t2 = RawTopic(
        title="breakthrough in quantum computing announced",
        summary="Summary 2",
        source_name="source_b",
        source_url="https://b.com",
    )
    assert t1.dedupe_hash == t2.dedupe_hash
