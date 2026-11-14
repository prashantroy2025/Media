"""Verification script: Full reset and fresh-start dry-run in a temporary project copy.
Proves that reset clears all generated data, restores autoincrement to 1, preserves setup files,
and that the real project database is 100% untouched.
"""

import hashlib
import os
import shutil
import sqlite3
import subprocess
from pathlib import Path

REAL_PROJECT_ROOT = Path("/Users/prashantroy/Desktop/MEDIA/nova-autopilot").resolve()
TEMP_PROJECT_ROOT = Path("/tmp/nova_reset_verification_sandbox").resolve()
VENV_PYTHON = REAL_PROJECT_ROOT / ".venv" / "bin" / "python"


def compute_file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def main():
    print("=== STEP 1: Verify Real Project Safety ===")
    real_db_path = REAL_PROJECT_ROOT / "data" / "nova.db"
    assert real_db_path.exists(), f"Real database missing at {real_db_path}"
    real_db_hash_before = compute_file_sha256(real_db_path)
    print(f"Real database SHA256 before: {real_db_hash_before}")

    # Inspect real DB row counts
    conn = sqlite3.connect(real_db_path)
    cur = conn.cursor()
    generated_counts_before = {}
    for table in ["topics", "scripts", "videos", "stock_attributions", "publications", "publish_queue"]:
        cur.execute(f"SELECT count(*) FROM {table}")
        generated_counts_before[table] = cur.fetchone()[0]
    conn.close()
    print(f"Real DB generated counts: {generated_counts_before}")
    total_generated_rows = sum(generated_counts_before.values())
    assert total_generated_rows > 0, "Real DB has no generated rows to test reset with!"

    print(f"\n=== STEP 2: Creating Temporary Project Copy in {TEMP_PROJECT_ROOT} ===")
    if TEMP_PROJECT_ROOT.exists():
        shutil.rmtree(TEMP_PROJECT_ROOT)
    TEMP_PROJECT_ROOT.mkdir(parents=True, exist_ok=True)

    # Copy necessary directories
    dirs_to_copy = ["nova", "config", "prompts", "scripts"]
    for d in dirs_to_copy:
        src = REAL_PROJECT_ROOT / d
        if src.exists():
            shutil.copytree(src, TEMP_PROJECT_ROOT / d)

    # Copy assets (exclude big cache to be fast, but keep fonts, music, sfx)
    (TEMP_PROJECT_ROOT / "assets").mkdir()
    for sub in ["fonts", "music", "sfx"]:
        src = REAL_PROJECT_ROOT / "assets" / sub
        if src.exists():
            shutil.copytree(src, TEMP_PROJECT_ROOT / "assets" / sub)

    # Copy data/nova.db into temp project
    (TEMP_PROJECT_ROOT / "data").mkdir()
    shutil.copy2(real_db_path, TEMP_PROJECT_ROOT / "data" / "nova.db")

    # Copy setup files: .env, credentials if exist
    for f in [".env", "data/youtube_token.json", "credentials"]:
        src = REAL_PROJECT_ROOT / f
        if src.is_dir():
            shutil.copytree(src, TEMP_PROJECT_ROOT / f)
        elif src.is_file():
            shutil.copy2(src, TEMP_PROJECT_ROOT / f)

    # Create dummy files in temp output/
    temp_output = TEMP_PROJECT_ROOT / "output"
    temp_output.mkdir(exist_ok=True)
    (temp_output / "video_87.mp4").write_text("dummy video 87")
    (temp_output / "video_88.mp4").write_text("dummy video 88")
    (temp_output / "thumb_87.jpg").write_text("dummy thumb")
    dummy_subs_dir = temp_output / "subs_bundle_87"
    dummy_subs_dir.mkdir()
    (dummy_subs_dir / "word_001.png").write_text("dummy png")

    # Record hashes of setup files in temp copy
    setup_hashes_before = {}
    for p in [
        TEMP_PROJECT_ROOT / "config" / "config.yaml",
        TEMP_PROJECT_ROOT / "config" / "persona.md",
        TEMP_PROJECT_ROOT / "prompts" / "script_system.md",
    ]:
        if p.exists():
            setup_hashes_before[str(p.relative_to(TEMP_PROJECT_ROOT))] = compute_file_sha256(p)
    print(f"Recorded hashes for {len(setup_hashes_before)} setup files in temp directory.")

    print("\n=== STEP 3: Run 'python -m nova reset --yes' in Temporary Copy ===")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(TEMP_PROJECT_ROOT)
    # Ensure it uses the temp project's root
    proc = subprocess.run(
        [str(VENV_PYTHON), "-m", "nova", "reset", "--yes"],
        cwd=str(TEMP_PROJECT_ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    print("STDOUT:\n", proc.stdout)
    if proc.stderr:
        print("STDERR:\n", proc.stderr)
    assert proc.returncode == 0, f"Reset command failed with code {proc.returncode}"

    print("\n=== STEP 4: Verify Post-Reset State in Temporary Copy ===")
    # 4a. Check backup file
    backups_dir = TEMP_PROJECT_ROOT / "data" / "backups"
    assert backups_dir.exists(), "Backups directory was not created!"
    backup_files = list(backups_dir.glob("nova_*.db"))
    assert len(backup_files) >= 1, "No backup .db file found in temp backups!"
    latest_backup = sorted(backup_files)[-1]
    print(f"Verified backup exists at: {latest_backup} (Size: {latest_backup.stat().st_size} bytes)")

    # Verify backup integrity by reading table counts
    conn_b = sqlite3.connect(latest_backup)
    cur_b = conn_b.cursor()
    for table, expected_cnt in generated_counts_before.items():
        cur_b.execute(f"SELECT count(*) FROM {table}")
        actual_cnt = cur_b.fetchone()[0]
        assert actual_cnt == expected_cnt, f"Backup table {table} has {actual_cnt} rows, expected {expected_cnt}"
    conn_b.close()
    print("✓ Backup integrity confirmed: all pre-reset data is preserved in the backup file.")

    # 4b. Check reset database
    temp_db_path = TEMP_PROJECT_ROOT / "data" / "nova.db"
    conn_r = sqlite3.connect(temp_db_path)
    cur_r = conn_r.cursor()
    for table in ["topics", "scripts", "videos", "stock_attributions", "publications", "publish_queue", "niche_weights_learned"]:
        cur_r.execute(f"SELECT count(*) FROM {table}")
        cnt = cur_r.fetchone()[0]
        assert cnt == 0, f"Table {table} still has {cnt} rows after reset!"
        print(f"✓ Table {table}: 0 rows")

    # Check setup tables
    cur_r.execute("SELECT count(*) FROM study_notes")
    study_cnt = cur_r.fetchone()[0]
    assert study_cnt > 0, "study_notes was wiped!"
    print(f"✓ Table study_notes: {study_cnt} rows (preserved)")

    # Check sqlite_sequence if it exists
    cur_r.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sqlite_sequence'")
    if cur_r.fetchone():
        cur_r.execute("SELECT name, seq FROM sqlite_sequence")
        seq_rows = cur_r.fetchall()
        print(f"sqlite_sequence rows: {seq_rows}")
        for name, seq in seq_rows:
            if name in ["topics", "scripts", "videos", "stock_attributions", "publications", "publish_queue"]:
                assert False, f"Table {name} still has sqlite_sequence={seq}"
    print("✓ Autoincrement sequence counters for generated tables reset to 0.")
    conn_r.close()

    # 4c. Check output directory
    output_files = list(temp_output.glob("**/*"))
    assert len([f for f in output_files if f.is_file()]) == 0, f"Output directory still has files: {output_files}"
    print("✓ Output directory is clean (all generated files removed).")

    # 4d. Check setup file hashes
    for rel_path, old_hash in setup_hashes_before.items():
        new_hash = compute_file_sha256(TEMP_PROJECT_ROOT / rel_path)
        assert new_hash == old_hash, f"Setup file {rel_path} was modified during reset!"
    print(f"✓ All {len(setup_hashes_before)} setup files remained bit-for-bit identical.")

    print("\n=== STEP 5: Test Fresh Dry-Run in Reset Project Copy ===")
    env["NOVA_MOCK_LLM"] = "1"
    proc_dry = subprocess.run(
        [str(VENV_PYTHON), "-m", "nova", "dry-run", "--count", "1"],
        cwd=str(TEMP_PROJECT_ROOT),
        capture_output=True,
        text=True,
        env=env,
        timeout=180,
    )
    print("DRY-RUN STDOUT (truncated):\n", proc_dry.stdout[-1500:] if len(proc_dry.stdout) > 1500 else proc_dry.stdout)
    if proc_dry.stderr:
        print("DRY-RUN STDERR:\n", proc_dry.stderr[-500:])
    assert proc_dry.returncode == 0, f"Dry-run failed with code {proc_dry.returncode}"

    # Verify new records have ID = 1 and is_demo = 1
    conn_fresh = sqlite3.connect(temp_db_path)
    cur_f = conn_fresh.cursor()
    cur_f.execute("SELECT id, is_demo, title FROM topics")
    topics = cur_f.fetchall()
    print("Fresh topics:", topics)
    assert len(topics) >= 1
    assert topics[0][0] == 1, f"Expected topic ID 1, got {topics[0][0]}"
    assert topics[0][1] == 1, f"Expected topic is_demo=1, got {topics[0][1]}"

    cur_f.execute("SELECT id, is_demo, title FROM scripts")
    scripts = cur_f.fetchall()
    print("Fresh scripts:", scripts)
    assert len(scripts) >= 1
    assert scripts[0][0] == 1, f"Expected script ID 1, got {scripts[0][0]}"
    assert scripts[0][1] == 1, f"Expected script is_demo=1, got {scripts[0][1]}"

    cur_f.execute("SELECT id, is_demo, video_path FROM videos")
    videos = cur_f.fetchall()
    print("Fresh videos:", videos)
    assert len(videos) == 1
    assert videos[0][0] == 1, f"Expected video ID 1, got {videos[0][0]}"
    assert videos[0][1] == 1, f"Expected video is_demo=1, got {videos[0][1]}"

    cur_f.execute("SELECT count(*) FROM publish_queue")
    queue_cnt = cur_f.fetchone()[0]
    assert queue_cnt == 0, f"Dry-run queued item to publish_queue! count={queue_cnt}"
    print("✓ Publish queue remains 0 (dry-run did not schedule or queue anything for publishing).")
    conn_fresh.close()

    print("\n=== STEP 6: Confirm Real Project Was 100% Untouched ===")
    real_db_hash_after = compute_file_sha256(real_db_path)
    print(f"Real database SHA256 after:  {real_db_hash_after}")
    assert real_db_hash_before == real_db_hash_after, "CRITICAL ERROR: Real database was modified!"
    print("✓ Verified: Real database hash is IDENTICAL. 0 real rows were modified or removed.")

    # Clean up temp sandbox
    shutil.rmtree(TEMP_PROJECT_ROOT)
    print("\n✓ Cleaned up temporary test directory.")
    print("==================================================================")
    print("ALL TESTS PASSED: Safe Reset & Fresh-Start Fully Verified!")
    print("==================================================================")


if __name__ == "__main__":
    main()
