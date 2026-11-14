"""Unit and integration tests for Nova Autopilot safe reset and fresh-start facility."""

import hashlib
import os
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from nova.db import (
    DatabaseManager,
    HookPattern,
    Publication,
    PublishQueue,
    Script,
    StockAttribution,
    StudyNote,
    Topic,
    Video,
)
from nova.reset import (
    PipelineActiveError,
    ResetManager,
    ResetOptions,
    SecurityError,
    ServerActiveError,
)


def compute_file_hash(path: Path) -> str:
    """Computes SHA-256 hash of a file for exact integrity verification."""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            hasher.update(chunk)
    return hasher.hexdigest()


@pytest.fixture(autouse=True)
def mock_port_not_in_use():
    """Ensures test suite is hermetic even if Review Studio server is running on host port 8765."""
    with patch("nova.reset.is_port_in_use", return_value=False):
        yield


@pytest.fixture
def fake_project(tmp_path: Path) -> dict:
    """Creates a temporary miniature project containing generated data and critical setup data."""
    root = tmp_path / "mini_project"
    root.mkdir(parents=True, exist_ok=True)

    # 1. Setup Directories & Files
    config_dir = root / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    cfg_file = config_dir / "config.yaml"
    cfg_file.write_text("channel:\n  name: Test Channel\n", encoding="utf-8")
    persona_file = config_dir / "persona.md"
    persona_file.write_text("# Persona\nAnalytical and direct.\n", encoding="utf-8")

    creds_dir = root / "credentials"
    creds_dir.mkdir(parents=True, exist_ok=True)
    secret_file = creds_dir / "client_secret.json"
    secret_file.write_text('{"installed": {"client_id": "test"}}', encoding="utf-8")

    data_dir = root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    yt_token_file = data_dir / "youtube_token.json"
    yt_token_file.write_text('{"token": "secret_oauth_token"}', encoding="utf-8")

    music_dir = root / "assets" / "music"
    music_dir.mkdir(parents=True, exist_ok=True)
    track_file = music_dir / "track.mp3"
    track_file.write_bytes(b"MOCK_AUDIO_DATA")
    music_lic = music_dir / "LICENSE.txt"
    music_lic.write_text("CC-BY Audio", encoding="utf-8")

    fonts_dir = root / "assets" / "fonts"
    fonts_dir.mkdir(parents=True, exist_ok=True)
    font_file = fonts_dir / "Montserrat-ExtraBold.ttf"
    font_file.write_bytes(b"MOCK_FONT_DATA")

    prompts_dir = root / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    prompt_file = prompts_dir / "scriptwriter.md"
    prompt_file.write_text("Write high impact scripts.", encoding="utf-8")

    env_file = root / ".env"
    env_file.write_text("API_KEY=test_secret_1234\n", encoding="utf-8")

    # 2. Generated Output Files
    out_dir = root / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    mp4_file = out_dir / "nova_video_1.mp4"
    mp4_file.write_bytes(b"MOCK_MP4_VIDEO")
    thumb_file = out_dir / "thumb_1.jpg"
    thumb_file.write_bytes(b"MOCK_THUMBNAIL")
    sub_bundle = out_dir / "subs_bundle_1"
    sub_bundle.mkdir(parents=True, exist_ok=True)
    (sub_bundle / "frame_001.png").write_bytes(b"PNG")

    # Loose temp directories
    loose_qc = root / "qc_dense_None"
    loose_qc.mkdir(parents=True, exist_ok=True)
    (loose_qc / "temp.jpg").write_bytes(b"TEMP")

    # Optional cache and logs
    cache_dir = root / "assets" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "stock_sample.jpg").write_bytes(b"STOCK")

    logs_dir = data_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / "nova.log").write_text("2026-11-14 INFO test\n", encoding="utf-8")

    # 3. Database Population
    db_file = data_dir / "nova.db"
    db_mgr = DatabaseManager(db_file)
    with db_mgr.session() as s:
        # Generated rows
        t1 = Topic(dedupe_hash="h1", title="Quantum Tech", source_name="arxiv", niche="ai_tech", is_demo=False)
        t2 = Topic(dedupe_hash="h2", title="Demo Market", source_name="sec", niche="business", is_demo=True)
        s.add_all([t1, t2])
        s.flush()

        sc1 = Script(topic_id=t1.id, title="Quantum Tech", hook="Hook 1", scenes_json="[]", is_demo=False)
        sc2 = Script(topic_id=t2.id, title="Demo Market", hook="Hook 2", scenes_json="[]", is_demo=True)
        s.add_all([sc1, sc2])
        s.flush()

        v1 = Video(script_id=sc1.id, video_path=str(mp4_file), is_demo=False)
        v2 = Video(script_id=sc2.id, video_path="output/demo.mp4", is_demo=True)
        s.add_all([v1, v2])
        s.flush()

        attr = StockAttribution(video_id=v1.id, provider="pexels", asset_id="101")
        pub = Publication(video_id=v1.id, platform="youtube", status="success")
        pq = PublishQueue(video_id=v1.id, platform="youtube", scheduled_time_utc=t1.created_at)
        s.add_all([attr, pub, pq])

        # Setup rows (study notes and pattern library)
        sn = StudyNote(topic="Retention Analysis", why_worked="High contrast cuts", niche="space_science")
        hp = HookPattern(pattern_type="impossible_number", template_text="Did you know [X]?", times_used=8, avg_retention=68.5)
        s.add_all([sn, hp])
        s.commit()

    return {
        "root": root,
        "db_file": db_file,
        "db_mgr": db_mgr,
        "setup_files": [cfg_file, persona_file, secret_file, yt_token_file, track_file, music_lic, font_file, prompt_file, env_file],
        "out_dir": out_dir,
        "cache_dir": cache_dir,
        "logs_dir": logs_dir,
    }


def test_dry_run_lists_correctly(fake_project):
    """Verifies that --list inspects counts and sizes without modifying any row or file."""
    root = fake_project["root"]
    db_file = fake_project["db_file"]

    opts = ResetOptions(list_only=True, custom_project_root=root, custom_db_path=db_file)
    mgr = ResetManager(options=opts, project_root=root)

    inv = mgr.collect_inventory()
    # topics(2) + scripts(2) + videos(2) + attr(1) + pub(1) + queue(1) + weights(0) = 9 total
    assert inv.total_generated_rows == 9
    assert inv.total_files_to_clean >= 3
    assert len(inv.setup_preserved) >= 8

    # Verify no file was deleted
    assert (root / "output" / "nova_video_1.mp4").exists()

    # Verify rows still exist
    with fake_project["db_mgr"].session() as s:
        assert s.query(Video).count() == 2
        assert s.query(Topic).count() == 2


def test_backup_created_and_valid(fake_project):
    """Verifies that the SQLite backup is created via the Online Backup API and passes integrity check."""
    root = fake_project["root"]
    db_file = fake_project["db_file"]

    opts = ResetOptions(list_only=False, yes=True, custom_project_root=root, custom_db_path=db_file)
    mgr = ResetManager(options=opts, project_root=root)

    backup_path = mgr.create_database_backup()
    assert backup_path is not None
    assert backup_path.exists()
    assert backup_path.stat().st_size > 0

    # Test integrity check on the backup file
    conn = sqlite3.connect(str(backup_path))
    c = conn.cursor()
    c.execute("PRAGMA integrity_check;")
    res = c.fetchone()
    conn.close()
    assert res[0] == "ok"


def test_generated_rows_and_files_removed(fake_project):
    """Verifies that all generated rows, sequences, and output files are wiped."""
    root = fake_project["root"]
    db_file = fake_project["db_file"]

    opts = ResetOptions(list_only=False, yes=True, custom_project_root=root, custom_db_path=db_file)
    mgr = ResetManager(options=opts, project_root=root)

    report = mgr.execute_reset()
    assert report["verification"]["all_passed"] is True

    # Database checks
    with fake_project["db_mgr"].session() as s:
        assert s.query(Video).count() == 0
        assert s.query(Script).count() == 0
        assert s.query(Topic).count() == 0
        assert s.query(StockAttribution).count() == 0
        assert s.query(Publication).count() == 0
        assert s.query(PublishQueue).count() == 0

    # Output directory check
    out_dir = root / "output"
    assert out_dir.exists()
    assert len(list(out_dir.iterdir())) == 0


def test_setup_files_and_tables_untouched_hashes(fake_project):
    """Verifies that all setup files maintain identical SHA-256 hashes and setup tables remain intact."""
    root = fake_project["root"]
    db_file = fake_project["db_file"]
    setup_files = fake_project["setup_files"]

    hashes_before = {f: compute_file_hash(f) for f in setup_files}

    opts = ResetOptions(list_only=False, yes=True, custom_project_root=root, custom_db_path=db_file)
    mgr = ResetManager(options=opts, project_root=root)
    mgr.execute_reset()

    hashes_after = {f: compute_file_hash(f) for f in setup_files}
    assert hashes_before == hashes_after, "Setup files were altered during reset!"

    # Verify setup database tables
    with fake_project["db_mgr"].session() as s:
        assert s.query(StudyNote).count() == 1
        note = s.query(StudyNote).first()
        assert note.topic == "Retention Analysis"

        # Verify hook pattern template preserved but stats reset
        pattern = s.query(HookPattern).first()
        assert pattern.template_text == "Did you know [X]?"
        assert pattern.times_used == 0
        assert pattern.avg_retention == 0.0


def test_autoincrement_reset(fake_project):
    """Verifies that autoincrement sequence counters are reset so new records start at ID 1."""
    root = fake_project["root"]
    db_file = fake_project["db_file"]

    opts = ResetOptions(list_only=False, yes=True, custom_project_root=root, custom_db_path=db_file)
    mgr = ResetManager(options=opts, project_root=root)
    mgr.execute_reset()

    with fake_project["db_mgr"].session() as s:
        fresh_topic = Topic(
            dedupe_hash="fresh_hash_1",
            title="Fresh Start Topic",
            source_name="arxiv",
            niche="ai_tech",
        )
        s.add(fresh_topic)
        s.commit()
        assert fresh_topic.id == 1, f"Expected fresh topic ID to be 1, got {fresh_topic.id}"


def test_paths_outside_project_refused(fake_project):
    """Verifies that SecurityError is raised if an operation targets paths outside project or forbidden roots."""
    root = fake_project["root"]
    db_file = fake_project["db_file"]

    mgr = ResetManager(project_root=root, options=ResetOptions(custom_project_root=root, custom_db_path=db_file))

    with pytest.raises(SecurityError):
        mgr.validate_safe_path_for_removal(Path("/etc/passwd"))

    with pytest.raises(SecurityError):
        mgr.validate_safe_path_for_removal(Path.home())

    with pytest.raises(SecurityError):
        mgr.validate_safe_path_for_removal(root)

    with pytest.raises(SecurityError):
        mgr.validate_safe_path_for_removal(root / "config" / "config.yaml")


def test_symlink_escape_refused(fake_project, tmp_path):
    """Verifies that symlinks pointing outside the project root are rejected with SecurityError."""
    root = fake_project["root"]
    outside_file = tmp_path / "outside_secret.txt"
    outside_file.write_text("SENSITIVE_OUTSIDE_DATA", encoding="utf-8")

    escape_symlink = root / "output" / "escape_link.mp4"
    escape_symlink.symlink_to(outside_file)

    mgr = ResetManager(project_root=root, options=ResetOptions(custom_project_root=root))

    with pytest.raises(SecurityError):
        mgr.validate_safe_path_for_removal(escape_symlink)

    # Confirm outside file was not deleted
    assert outside_file.exists()


def test_server_active_refuses_reset(fake_project):
    """Verifies that reset refuses to run if the review studio server is listening on port 8765."""
    root = fake_project["root"]
    mgr = ResetManager(project_root=root, options=ResetOptions(custom_project_root=root))

    with patch("nova.reset.is_port_in_use", return_value=True):
        with pytest.raises(ServerActiveError):
            mgr.pre_checks()


def test_pipeline_locked_refuses_reset(fake_project):
    """Verifies that reset refuses to run if an active pipeline lock file is present."""
    root = fake_project["root"]
    lock_file = root / "data" / "pipeline.lock"
    lock_file.write_text(str(os.getpid()), encoding="utf-8")

    mgr = ResetManager(project_root=root, options=ResetOptions(custom_project_root=root))

    with pytest.raises(PipelineActiveError):
        mgr.pre_checks()


def test_trash_fallback_pending(fake_project, monkeypatch):
    """Verifies that when Trash is unavailable, files fall back to data/trash_pending/ and are not deleted."""
    root = fake_project["root"]
    db_file = fake_project["db_file"]

    # Mock user trash to non-existent to trigger trash_pending fallback
    monkeypatch.setattr(Path, "home", lambda: root / "fake_home_no_trash")

    opts = ResetOptions(list_only=False, yes=True, permanent=False, custom_project_root=root, custom_db_path=db_file)
    mgr = ResetManager(options=opts, project_root=root)

    test_file = root / "output" / "fallback_test.mp4"
    test_file.write_bytes(b"DATA")

    result = mgr.trash_path(test_file)
    assert result == "trash_pending"

    # Verify file was safely moved to data/trash_pending
    pending_files = list((root / "data" / "trash_pending").glob("fallback_test.mp4_*"))
    assert len(pending_files) == 1
    assert pending_files[0].read_bytes() == b"DATA"


def test_transaction_rollback_on_interruption(fake_project):
    """Verifies that if an exception occurs during table deletion, transaction rolls back cleanly."""
    root = fake_project["root"]
    db_file = fake_project["db_file"]

    # Install a trigger in the database that aborts on deleting from topics
    conn = sqlite3.connect(str(db_file))
    conn.execute(
        "CREATE TRIGGER abort_topic_deletion BEFORE DELETE ON topics "
        "BEGIN SELECT RAISE(ABORT, 'Simulated database interruption during deletion'); END;"
    )
    conn.commit()
    conn.close()

    opts = ResetOptions(list_only=False, yes=True, custom_project_root=root, custom_db_path=db_file)
    mgr = ResetManager(options=opts, project_root=root)

    with pytest.raises(sqlite3.IntegrityError, match="Simulated database interruption"):
        mgr.execute_reset()

    # Verify transaction rollback: topics, scripts, and videos still intact
    with fake_project["db_mgr"].session() as s:
        assert s.query(Topic).count() == 2
        assert s.query(Script).count() == 2
        assert s.query(Video).count() == 2
        assert s.query(Topic).count() == 2
        assert s.query(Video).count() == 2


def test_only_demo_flag(fake_project):
    """Verifies that --only-demo deletes only records marked with is_demo=1."""
    root = fake_project["root"]
    db_file = fake_project["db_file"]

    opts = ResetOptions(list_only=False, yes=True, only_demo=True, custom_project_root=root, custom_db_path=db_file)
    mgr = ResetManager(options=opts, project_root=root)
    mgr.execute_reset()

    with fake_project["db_mgr"].session() as s:
        # Non-demo topic and video survive
        topics = s.query(Topic).all()
        assert len(topics) == 1
        assert topics[0].title == "Quantum Tech"
        assert topics[0].is_demo is False

        videos = s.query(Video).all()
        assert len(videos) == 1
        assert videos[0].is_demo is False


def test_keep_learning_flag(fake_project):
    """Verifies that --keep-learning preserves hook pattern retention stats."""
    root = fake_project["root"]
    db_file = fake_project["db_file"]

    opts = ResetOptions(
        list_only=False,
        yes=True,
        keep_learning=True,
        custom_project_root=root,
        custom_db_path=db_file,
    )
    mgr = ResetManager(options=opts, project_root=root)
    mgr.execute_reset()

    with fake_project["db_mgr"].session() as s:
        pattern = s.query(HookPattern).first()
        assert pattern.times_used == 8
        assert pattern.avg_retention == 68.5
