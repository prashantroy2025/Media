"""NOVA AUTOPILOT Unified Creative Timeline Module (v9.3).

Exports:
- UnifiedProject, Scene, VideoLayer, LayerTransform, Keyframe, KeyframeTrack, Timecode
- AudioTrack, AudioClip, AudioTrackType, LayerType, BlendMode, EasingType
- SceneRenderer, UnifiedTimelineCompiler
- BaseComposition, DeepSpaceStarfieldComposition
- ShotPlan, TimelinePlan, TimelineBuilder (Legacy compatibility bridge)
"""

from nova.timeline.schema import (
    AudioClip,
    AudioTrack,
    AudioTrackType,
    BlendMode,
    EasingType,
    Keyframe,
    KeyframeTrack,
    LayerTransform,
    LayerType,
    Scene,
    Timecode,
    UnifiedProject,
    VideoLayer,
    apply_easing,
)
from nova.timeline.compositions import (
    BaseComposition,
    DeepSpaceStarfieldComposition,
)
from nova.timeline.motion_studio import (
    CyberneticInterfaceComposition,
    FinancialTrendChartComposition,
    ForensicInspectionLoupeComposition,
    GeographicMapRouteComposition,
    HistoricalTimelineComposition,
    Isometric3DBarChartComposition,
    KineticTypographyComposition,
    MotionDesignStudio,
    ScientificSchematicComposition,
    SplitScreenComparisonComposition,
)
from nova.timeline.scene_renderer import (
    SceneRenderer,
)
from nova.timeline.compiler import (
    UnifiedTimelineCompiler,
)
from nova.timeline.compat import (
    ShotPlan,
    TimelineBuilder,
    TimelinePlan,
)
from nova.editing.techniques import (
    ColorHarmonizer,
    ColorProfile,
    ProfessionalEditingEngine,
    ProfessionalTransitionType,
    TransitionDescriptor,
)

__all__ = [
    "AudioClip",
    "AudioTrack",
    "AudioTrackType",
    "BaseComposition",
    "BlendMode",
    "TransitionDescriptor",
    "ProfessionalTransitionType",
    "ColorHarmonizer",
    "ColorProfile",
    "ProfessionalEditingEngine",
    "CyberneticInterfaceComposition",
    "DeepSpaceStarfieldComposition",
    "EasingType",
    "FinancialTrendChartComposition",
    "ForensicInspectionLoupeComposition",
    "GeographicMapRouteComposition",
    "HistoricalTimelineComposition",
    "Isometric3DBarChartComposition",
    "Keyframe",
    "KeyframeTrack",
    "KineticTypographyComposition",
    "LayerTransform",
    "LayerType",
    "MotionDesignStudio",
    "Scene",
    "SceneRenderer",
    "ScientificSchematicComposition",
    "ShotPlan",
    "SplitScreenComparisonComposition",
    "Timecode",
    "TimelineBuilder",
    "TimelinePlan",
    "UnifiedProject",
    "UnifiedTimelineCompiler",
    "VideoLayer",
    "apply_easing",
]
