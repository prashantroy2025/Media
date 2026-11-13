"""Task scheduler for running daily automated studio pipelines."""

import time
from datetime import UTC, datetime
from pathlib import Path

from nova.config import NovaSettings
from nova.db import DatabaseManager
from nova.logging_setup import logger
from nova.pipeline import PipelineRunner


class NovaScheduler:
    def __init__(self, settings: NovaSettings, db_mgr: DatabaseManager):
        self.settings = settings
        self.db_mgr = db_mgr

    def run_daily_loop(self, run_hour_utc: int = 4):
        """Simple in-app daemon scheduler that executes daily at the specified UTC hour."""
        logger.info(f"Starting in-app scheduler (daily trigger targeted for {run_hour_utc:02d}:00 UTC)...")
        pipeline = PipelineRunner(self.settings, self.db_mgr)

        while True:
            now = datetime.now(UTC)
            if now.hour == run_hour_utc and now.minute == 0:
                logger.info(f"Triggering scheduled daily run at {now.isoformat()}...")
                try:
                    pipeline.run_full()
                except Exception as e:
                    logger.error(f"Scheduled pipeline run encountered an error: {e}", exc_info=True)
                time.sleep(70)  # Sleep past current minute
            time.sleep(30)


def generate_launchd_plist(
    settings: NovaSettings,
    hour: int = 10,
    minute: int = 0,
    output_path: Path | None = None,
) -> Path:
    """Generates a macOS launchd agent plist file for automatic daily execution."""
    project_root = settings.resolve_path(".")
    venv_python = project_root / ".venv" / "bin" / "python"
    log_file = project_root / "data" / "logs" / "launchd_nova.log"

    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.nova.autopilot.daily</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/caffeinate</string>
        <string>-i</string>
        <string>{venv_python.resolve()}</string>
        <string>-m</string>
        <string>nova</string>
        <string>run</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{project_root.resolve()}</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>{hour}</integer>
        <key>Minute</key>
        <integer>{minute}</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>{log_file.resolve()}</string>
    <key>StandardErrorPath</key>
    <string>{log_file.resolve()}</string>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
"""
    dest = output_path or project_root / "scripts" / "com.nova.autopilot.daily.plist"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(plist_content, encoding="utf-8")
    return dest
