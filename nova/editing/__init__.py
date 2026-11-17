"""NOVA AUTOPILOT v9.5 Professional Editing Intelligence Suite.

Integrates:
- Narrative Arc Intelligence: Semantic role identification & pacing control
- Audio-Driven Editing: Speech dynamics, silence detection, beat tracking & sympathetic cuts
- Professional Editing Techniques: J-cuts, L-cuts, speed ramps, match cuts & color matching
- Editorial Tension Engine: Adaptive emotional tension curve & directorial modulation
- Advanced Sound Direction: Contextual cinematic SFX, atmospheric beds, sub-bass & silence
- Visual Continuity: Color continuity, eye trace tracking, framing progression & repetition checks
"""

from nova.editing.narrative_arc import (
    ArcAnalysisResult,
    NarrativeArcAnalyzer,
    NarrativeRole,
    NarrativeSegment,
)
from nova.editing.audio_intelligence import (
    AudioIntelligenceAnalyzer,
    AudioOnset,
    AudioSilence,
    BeatGrid,
    CutDecision,
    ImportantWord,
    SpeechEnergyProfile,
)
from nova.editing.tension_engine import (
    EditorialModulation,
    TensionEngine,
    TensionPoint,
    TensionState,
)
from nova.editing.techniques import (
    ColorHarmonizer,
    ColorProfile,
    ProfessionalEditingEngine,
    ProfessionalTransitionType,
    TransitionDescriptor,
)
from nova.editing.visual_continuity import (
    AdjacentContinuityPair,
    ContinuityReport,
    VisualContinuityAnalyzer,
)
from nova.editing.sound_director import (
    AdvancedSoundDirector,
    SoundCue,
)

__all__ = [
    # Narrative Arc
    "NarrativeRole",
    "NarrativeSegment",
    "ArcAnalysisResult",
    "NarrativeArcAnalyzer",
    # Audio Intelligence
    "AudioSilence",
    "AudioOnset",
    "ImportantWord",
    "SpeechEnergyProfile",
    "BeatGrid",
    "CutDecision",
    "AudioIntelligenceAnalyzer",
    # Tension Engine
    "TensionState",
    "TensionPoint",
    "EditorialModulation",
    "TensionEngine",
    # Professional Techniques
    "ProfessionalTransitionType",
    "TransitionDescriptor",
    "ColorProfile",
    "ColorHarmonizer",
    "ProfessionalEditingEngine",
    # Visual Continuity
    "AdjacentContinuityPair",
    "ContinuityReport",
    "VisualContinuityAnalyzer",
    # Advanced Sound Direction
    "SoundCue",
    "AdvancedSoundDirector",
]
