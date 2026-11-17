"""Direct export alias for Narrative Arc Analyzer (Nova Autopilot v9.5)."""

from nova.editing.narrative_arc import (
    ArcAnalysisResult,
    NarrativeArcAnalyzer,
    NarrativeRole,
    NarrativeSegment,
)

__all__ = [
    "NarrativeRole",
    "NarrativeSegment",
    "ArcAnalysisResult",
    "NarrativeArcAnalyzer",
]
