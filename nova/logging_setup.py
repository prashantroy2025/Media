"""Centralized structured logging setup for Nova Autopilot."""

import logging
from pathlib import Path

from rich.logging import RichHandler


def setup_logging(logs_dir: Path | str = "data/logs", log_level: int = logging.INFO) -> logging.Logger:
    """Configures application-wide logging with file and rich console handlers."""
    log_path = Path(logs_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    log_file = log_path / "nova.log"

    root_logger = logging.getLogger("nova")
    root_logger.setLevel(log_level)

    # Avoid duplicate handlers if called multiple times
    if root_logger.handlers:
        return root_logger

    # Console Handler (Rich)
    console_handler = RichHandler(
        rich_tracebacks=True,
        markup=True,
        show_time=True,
        show_path=False,
    )
    console_handler.setLevel(log_level)

    # File Handler
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_format = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(name)s:%(funcName)s:%(lineno)d] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_format)

    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    return root_logger


logger = logging.getLogger("nova")
