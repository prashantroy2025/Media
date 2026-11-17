"""Professional Creator Presets for Nova Autopilot v9.0.

Provides 10 distinct video editing profiles controlling:
- Pacing & shot durations
- Visual selection strategy (video-first vs archival)
- Typography and caption behavior
- Broadcast color grading formulas
- Transitions & motion graphics frequency
- Sound design and music mood
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class VideoPreset:
    preset_id: str
    name: str
    description: str
    target_shot_min: float
    target_shot_max: float
    video_coverage_target: float  # e.g., 0.70 for 70% video footage
    color_grade: str              # FFmpeg video filter chain
    transition_style: str         # "cut", "crossfade", "whip", "zoom", "directional", "mixed"
    transition_duration: float    # Duration of transition in seconds (e.g. 0.3)
    caption_preset: str           # Preset style for captions
    motion_intensity: str         # "subtle", "balanced", "high"
    music_mood: str               # "upbeat", "epic", "mystery", "curious"
    sfx_intensity: str            # "low", "medium", "high"
    font_family: str              # Font name
    font_size: int
    primary_color: str            # Hex or RGBA for text
    highlight_color: str          # Hex or RGBA for active keyword / karaoke
    background_overlay: str       # "none", "vignette", "film_grain", "scanlines"
    dynamic_camera_pan: bool = True
    split_screen_allowed: bool = True
    motion_blur_enabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# 10 CREATOR PRESETS
# ---------------------------------------------------------------------------

PRESETS: dict[str, VideoPreset] = {
    "viral_facts": VideoPreset(
        preset_id="viral_facts",
        name="Viral Facts",
        description="High-energy, fast-paced editing with bold center-screen captions, frequent pops and punchy whooshes.",
        target_shot_min=1.4,
        target_shot_max=2.4,
        video_coverage_target=0.75,
        color_grade="eq=contrast=1.12:brightness=0.02:saturation=1.20,unsharp=5:5:0.6,vignette=PI/6",
        transition_style="whip",
        transition_duration=0.25,
        caption_preset="bold_viral_facts",
        motion_intensity="high",
        music_mood="upbeat",
        sfx_intensity="high",
        font_family="Montserrat-ExtraBold",
        font_size=62,
        primary_color="&H00FFFFFF",
        highlight_color="&H0000FFFF",  # Vivid yellow
        background_overlay="vignette",
        dynamic_camera_pan=True,
        split_screen_allowed=True,
        motion_blur_enabled=True,
    ),
    "documentary": VideoPreset(
        preset_id="documentary",
        name="Documentary",
        description="Authoritative, measured pacing with clean lower-third typography and archival elegance.",
        target_shot_min=2.4,
        target_shot_max=3.8,
        video_coverage_target=0.60,
        color_grade="eq=contrast=1.04:brightness=0.0:saturation=1.02,unsharp=3:3:0.3,colorbalance=rs=0.02:gs=0.0:bs=-0.02",
        transition_style="crossfade",
        transition_duration=0.4,
        caption_preset="minimal_documentary",
        motion_intensity="subtle",
        music_mood="curious",
        sfx_intensity="low",
        font_family="Montserrat-Bold",
        font_size=52,
        primary_color="&H00F5F5F5",
        highlight_color="&H00E0E0E0",  # Soft highlight
        background_overlay="none",
        dynamic_camera_pan=True,
        split_screen_allowed=False,
        motion_blur_enabled=False,
    ),
    "cinematic_storytelling": VideoPreset(
        preset_id="cinematic_storytelling",
        name="Cinematic Storytelling",
        description="Immersive narrative pacing, dramatic lighting, smooth zooms and cinematic sound design.",
        target_shot_min=2.0,
        target_shot_max=3.4,
        video_coverage_target=0.70,
        color_grade="eq=contrast=1.10:brightness=-0.01:saturation=1.10,colorbalance=rs=0.05:gs=0.0:bs=-0.04,unsharp=3:3:0.4,vignette=PI/4",
        transition_style="zoom",
        transition_duration=0.35,
        caption_preset="cinematic_storytelling",
        motion_intensity="balanced",
        music_mood="epic",
        sfx_intensity="medium",
        font_family="Montserrat-Bold",
        font_size=56,
        primary_color="&H00FFFFFF",
        highlight_color="&H004ED9F7",  # Gold amber
        background_overlay="vignette",
        dynamic_camera_pan=True,
        split_screen_allowed=True,
        motion_blur_enabled=True,
    ),
    "dark_mystery": VideoPreset(
        preset_id="dark_mystery",
        name="Dark Mystery",
        description="Atmospheric suspense, desaturated teal-and-shadow tones, slow push-ins and ominous audio hits.",
        target_shot_min=2.2,
        target_shot_max=3.8,
        video_coverage_target=0.65,
        color_grade="eq=contrast=1.18:brightness=-0.04:saturation=0.88,colorbalance=rs=-0.05:gs=0.02:bs=0.08,vignette=PI/3.5,unsharp=5:5:0.5",
        transition_style="crossfade",
        transition_duration=0.45,
        caption_preset="dark_mystery",
        motion_intensity="subtle",
        music_mood="mystery",
        sfx_intensity="medium",
        font_family="Montserrat-Bold",
        font_size=54,
        primary_color="&H00E0E0E0",
        highlight_color="&H00D47800",  # Cold electric cyan
        background_overlay="vignette",
        dynamic_camera_pan=True,
        split_screen_allowed=False,
        motion_blur_enabled=False,
    ),
    "financial_education": VideoPreset(
        preset_id="financial_education",
        name="Financial Education",
        description="Sharp data visualizations, animated counter metrics, emerald green emphasis and structured cards.",
        target_shot_min=1.8,
        target_shot_max=3.0,
        video_coverage_target=0.65,
        color_grade="eq=contrast=1.08:brightness=0.01:saturation=1.06,unsharp=3:3:0.4",
        transition_style="whip",
        transition_duration=0.25,
        caption_preset="financial_explainer",
        motion_intensity="high",
        music_mood="mystery",
        sfx_intensity="medium",
        font_family="Montserrat-ExtraBold",
        font_size=56,
        primary_color="&H00FFFFFF",
        highlight_color="&H0042D72B",  # Emerald cash green
        background_overlay="none",
        dynamic_camera_pan=True,
        split_screen_allowed=True,
        motion_blur_enabled=False,
    ),
    "investigative_journalism": VideoPreset(
        preset_id="investigative_journalism",
        name="Investigative Journalism",
        description="Document analysis, evidence callouts, timeline markers, source attribution pills and newsroom pacing.",
        target_shot_min=1.9,
        target_shot_max=3.2,
        video_coverage_target=0.60,
        color_grade="eq=contrast=1.06:brightness=0.0:saturation=0.98,unsharp=4:4:0.5",
        transition_style="directional",
        transition_duration=0.25,
        caption_preset="minimal_documentary",
        motion_intensity="balanced",
        music_mood="mystery",
        sfx_intensity="medium",
        font_family="Montserrat-Bold",
        font_size=52,
        primary_color="&H00FFFFFF",
        highlight_color="&H0000A5FF",  # Alert orange
        background_overlay="none",
        dynamic_camera_pan=True,
        split_screen_allowed=True,
        motion_blur_enabled=False,
    ),
    "historical_explainer": VideoPreset(
        preset_id="historical_explainer",
        name="Historical Explainer",
        description="Archival footage, 2.5D parallax Ken Burns on historical portraits, timeline progression and warm grading.",
        target_shot_min=2.4,
        target_shot_max=4.0,
        video_coverage_target=0.55,
        color_grade="eq=contrast=1.05:brightness=0.01:saturation=0.92,colorbalance=rs=0.06:gs=0.01:bs=-0.04,unsharp=3:3:0.3,vignette=PI/5",
        transition_style="crossfade",
        transition_duration=0.45,
        caption_preset="minimal_documentary",
        motion_intensity="subtle",
        music_mood="epic",
        sfx_intensity="low",
        font_family="Montserrat-Bold",
        font_size=52,
        primary_color="&H00FAF0E6",  # Linen warm white
        highlight_color="&H0050C878",
        background_overlay="film_grain",
        dynamic_camera_pan=True,
        split_screen_allowed=False,
        motion_blur_enabled=False,
    ),
    "technology": VideoPreset(
        preset_id="technology",
        name="Technology",
        description="Futuristic aesthetic, cool cyber accents, blueprint diagrams, code overlays and high-tech synths.",
        target_shot_min=1.6,
        target_shot_max=2.8,
        video_coverage_target=0.75,
        color_grade="eq=contrast=1.14:brightness=0.01:saturation=1.12,colorbalance=rs=-0.04:gs=0.01:bs=0.06,unsharp=5:5:0.5",
        transition_style="whip",
        transition_duration=0.25,
        caption_preset="high_energy_shorts",
        motion_intensity="high",
        music_mood="upbeat",
        sfx_intensity="high",
        font_family="Montserrat-ExtraBold",
        font_size=58,
        primary_color="&H00FFFFFF",
        highlight_color="&H00FFFF00",  # Cyan neon
        background_overlay="none",
        dynamic_camera_pan=True,
        split_screen_allowed=True,
        motion_blur_enabled=True,
    ),
    "news_explainer": VideoPreset(
        preset_id="news_explainer",
        name="News Explainer",
        description="Punchy newsroom clarity, verified source badges, rapid pattern interrupts and urgent informational cadence.",
        target_shot_min=1.7,
        target_shot_max=2.8,
        video_coverage_target=0.70,
        color_grade="eq=contrast=1.08:brightness=0.01:saturation=1.08,unsharp=3:3:0.4",
        transition_style="directional",
        transition_duration=0.25,
        caption_preset="modern_educational",
        motion_intensity="balanced",
        music_mood="upbeat",
        sfx_intensity="medium",
        font_family="Montserrat-Bold",
        font_size=54,
        primary_color="&H00FFFFFF",
        highlight_color="&H0000C8FF",  # Gold yellow
        background_overlay="none",
        dynamic_camera_pan=True,
        split_screen_allowed=True,
        motion_blur_enabled=False,
    ),
    "high_energy_educational": VideoPreset(
        preset_id="high_energy_educational",
        name="High-Energy Educational",
        description="Fast-paced TikTok/Reels style with maximal retention, kinetic word reveals, scale pop and energetic sound design.",
        target_shot_min=1.3,
        target_shot_max=2.2,
        video_coverage_target=0.75,
        color_grade="eq=contrast=1.15:brightness=0.02:saturation=1.22,unsharp=5:5:0.6,vignette=PI/6",
        transition_style="mixed",
        transition_duration=0.25,
        caption_preset="high_energy_shorts",
        motion_intensity="high",
        music_mood="upbeat",
        sfx_intensity="high",
        font_family="Montserrat-ExtraBold",
        font_size=62,
        primary_color="&H00FFFFFF",
        highlight_color="&H0000FFFF",  # Neon yellow
        background_overlay="vignette",
        dynamic_camera_pan=True,
        split_screen_allowed=True,
        motion_blur_enabled=True,
    ),
}


def get_preset(preset_id: str | None) -> VideoPreset:
    """Returns a preset by ID, falling back to 'viral_facts' if not found."""
    if not preset_id:
        return PRESETS["viral_facts"]
    normalized = preset_id.strip().lower().replace(" ", "_").replace("-", "_")
    return PRESETS.get(normalized, PRESETS["viral_facts"])


def list_presets() -> list[dict[str, Any]]:
    """Returns list of all available preset metadata for UI/CLI selectors."""
    return [p.to_dict() for p in PRESETS.values()]


def select_preset_for_topic(niche: str, title: str = "", summary: str = "") -> VideoPreset:
    """Intelligently infers the best preset based on niche and textual semantics."""
    combined = (title + " " + summary).lower()

    if any(k in combined for k in ("ancient", "century", "history", "historical", "war", "pyramid", "empire", "archaeology", "rome", "dynasty")):
        return PRESETS["historical_explainer"]

    if any(k in combined for k in ("scam", "fraud", "investigation", "whistleblower", "exposed", "lawsuit", "court", "antitrust", "corrupt")):
        return PRESETS["investigative_journalism"]

    if any(k in combined for k in ("billion", "trillion", "dollar", "stock", "market", "revenue", "profit", "bank", "economy")):
        return PRESETS["financial_education"]

    if any(k in combined for k in ("mystery", "bizarre", "unexplained", "dark", "creepy", "deep ocean", "abyss")):
        return PRESETS["dark_mystery"]

    if niche == "ai_tech":
        if any(k in combined for k in ("algorithm", "neural", "gpu", "chip", "robot", "quantum", "breakthrough")):
            return PRESETS["technology"]
        return PRESETS["viral_facts"]

    if niche == "space_science":
        if any(k in combined for k in ("black hole", "galaxy", "neutron star", "supernova", "cosmic")):
            return PRESETS["cinematic_storytelling"]
        return PRESETS["documentary"]

    if niche == "business":
        return PRESETS["financial_education"]

    return PRESETS["viral_facts"]
