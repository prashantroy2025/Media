"""Direct export alias for Editorial Tension Engine (Nova Autopilot v9.5)."""

from nova.editing.tension_engine import (
    EditorialModulation,
    TensionEngine,
    TensionPoint,
    TensionState,
)

__all__ = [
    "TensionState",
    "TensionPoint",
    "EditorialModulation",
    "TensionEngine",
]
