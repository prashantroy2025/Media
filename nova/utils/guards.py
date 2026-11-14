"""System Health Watchdog, Memory & Disk Space Guards, and macOS Notifications for Nova Autopilot v8.0."""

from __future__ import annotations

import os
import resource
import shutil
import sqlite3
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from nova.config import PROJECT_ROOT
from nova.logging_setup import logger


def get_current_rss_mb() -> float:
    """Returns current process Resident Set Size (RSS) in megabytes."""
    usage = resource.getrusage(resource.RUSAGE_SELF)
    # On macOS, ru_maxrss is in bytes; on Linux, in kilobytes
    if os.uname().sysname == "Darwin":
        return usage.ru_maxrss / (1024.0 * 1024.0)
    return usage.ru_maxrss / 1024.0


def check_system_guards(min_disk_gb: float = 2.0, max_rss_mb: float = 5500.0) -> None:
    """Verifies that disk space is sufficient and process memory stays within 8 GB hardware envelope."""
    # 1. Disk check
    total, used, free = shutil.disk_usage(PROJECT_ROOT)
    free_gb = free / (1024.0**3)
    if free_gb < min_disk_gb:
        raise RuntimeError(
            f"Insufficient disk space: {free_gb:.2f} GB free, but at least {min_disk_gb:.1f} GB is required. "
            f"Please clean up disk before running pipeline."
        )

    # 2. Memory check
    rss_mb = get_current_rss_mb()
    if rss_mb > max_rss_mb:
        logger.warning(
            f"[bold red]Memory Watchdog Alert:[/bold red] Process RSS is {rss_mb:.1f} MB (Ceiling: {max_rss_mb:.1f} MB). "
            f"Triggering garbage collection..."
        )
        import gc
        gc.collect()


def send_macos_notification(title: str, message: str) -> None:
    """Displays native macOS desktop banner notification."""
    try:
        clean_title = title.replace('"', '\\"')
        clean_msg = message.replace('"', '\\"')
        script = f'display notification "{clean_msg}" with title "{clean_title}"'
        subprocess.run(["osascript", "-e", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def perform_rolling_backup(db_path: Path, max_backups: int = 7) -> Path | None:
    """Performs daily SQLite online backup and prunes old backups keeping the most recent 7."""
    if not db_path.exists():
        return None

    backups_dir = db_path.parent / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    backup_file = backups_dir / f"nova_backup_{timestamp}.db"

    try:
        source_conn = sqlite3.connect(str(db_path))
        dest_conn = sqlite3.connect(str(backup_file))
        with dest_conn:
            source_conn.backup(dest_conn)
        dest_conn.close()
        source_conn.close()

        # Prune older backups
        existing = sorted(backups_dir.glob("nova_backup_*.db"))
        if len(existing) > max_backups:
            to_remove = existing[:-max_backups]
            for old in to_remove:
                try:
                    old.unlink()
                except Exception:
                    pass

        return backup_file
    except Exception as e:
        logger.warning(f"Automatic rolling database backup failed: {e}")
        return None
