"""Pytest configuration ensuring nova package is in sys.path and tests isolate their database."""

import os
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Ensure tests default to an isolated test database, never the production database
os.environ.setdefault("NOVA_DB_PATH", "data/test.db")
