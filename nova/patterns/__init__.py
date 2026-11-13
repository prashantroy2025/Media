"""Pattern extraction, viral reference tracking, study notes, and angle generation for Nova Autopilot."""

from nova.patterns.angles import AngleGenerator, OriginalityGuard, ProposedAngle
from nova.patterns.library import PatternLibrary, check_word_overlap
from nova.patterns.study_notes import StudyNotesManager, evaluate_copy_guard
from nova.patterns.tracker import ReferenceChannelTracker, parse_iso_duration

__all__ = [
    "AngleGenerator",
    "OriginalityGuard",
    "PatternLibrary",
    "ProposedAngle",
    "ReferenceChannelTracker",
    "StudyNotesManager",
    "check_word_overlap",
    "evaluate_copy_guard",
    "parse_iso_duration",
]
