"""Configuration loader and schema validation for Nova Autopilot v2.0."""

import os
from pathlib import Path
import re
from typing import Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Load environment variables from .env in project root, with fallback to cwd
_env_path = PROJECT_ROOT / ".env"
if _env_path.exists():
    load_dotenv(dotenv_path=_env_path, override=False)
load_dotenv(override=False)

# Ensure standard macOS Homebrew and local binary paths are in PATH
for extra_path in ["/opt/homebrew/bin", "/usr/local/bin"]:
    if extra_path not in os.environ.get("PATH", ""):
        os.environ["PATH"] = f"{extra_path}:{os.environ.get('PATH', '')}"


class AppConfig(BaseModel):
    name: str = "Nova Autopilot"
    version: str = "2.0.0"
    db_path: str = "data/nova.db"
    output_dir: str = "output"
    cache_dir: str = "assets/cache"
    logs_dir: str = "data/logs"


class ContentConfig(BaseModel):
    language: Literal["en", "hinglish"] = "en"
    strategy: str = "shock_facts_and_science"
    target_wpm: int = 175
    min_wpm: int = 150
    max_wpm: int = 200
    format_mix: list[str] = Field(
        default_factory=lambda: [
            "mind-blowing fact",
            "breaking science/tech news",
            "myth vs reality",
            "scale comparison",
            "before/after",
        ]
    )
    banned_topics: list[str] = Field(
        default_factory=lambda: [
            "medical advice",
            "financial advice",
            "guaranteed profit",
            "conspiracy theories",
            "unverified rumors",
            "politics",
            "hate speech",
        ]
    )


class ChannelConfig(BaseModel):
    name: str = "PRASHANT ROY"
    handle: str = "@NovaPrashantroy"
    niche_keywords: list[str] = Field(
        default_factory=lambda: [
            "Science",
            "Space",
            "Physics",
            "Shocking Facts",
            "Technology",
            "AI",
            "Quantum",
            "Astronomy",
        ]
    )
    region: str = "US"
    language: str = "English"


class CollectorSourceConfig(BaseModel):
    enabled: bool = True
    weight: float = 1.0


class CollectorsConfig(BaseModel):
    wikipedia: CollectorSourceConfig = Field(default_factory=lambda: CollectorSourceConfig(enabled=True, weight=1.2))
    nasa: CollectorSourceConfig = Field(default_factory=lambda: CollectorSourceConfig(enabled=True, weight=1.3))
    science_news: CollectorSourceConfig = Field(default_factory=lambda: CollectorSourceConfig(enabled=True, weight=1.1))
    reddit_ideas: CollectorSourceConfig = Field(default_factory=lambda: CollectorSourceConfig(enabled=True, weight=1.0))
    google_trends: CollectorSourceConfig = Field(
        default_factory=lambda: CollectorSourceConfig(enabled=True, weight=0.9)
    )
    hackernews: CollectorSourceConfig = Field(default_factory=lambda: CollectorSourceConfig(enabled=True, weight=0.8))


class PublishingConfig(BaseModel):
    publish_mode: Literal["review", "auto"] = "review"
    daily_cap: int = 2
    min_gap_hours: int = 4
    platforms: dict = Field(default_factory=lambda: {"youtube": True, "instagram": False})


class YouTubeConfig(BaseModel):
    default_privacy: Literal["private", "unlisted", "public"] = "private"
    category_id: str = "28"
    self_declared_made_for_kids: bool = False
    synthetic_media_disclosure: bool = True
    client_secret_file: str = "credentials/client_secret.json"
    token_file: str = "data/tokens/youtube_token.json"


class InstagramConfig(BaseModel):
    account_type: str = "CREATOR"
    disclosure_line: str = "⚡ Shocking facts & science breakdown by @NovaPrashantroy"
    video_hosting: Literal["quick_tunnel", "s3"] = "quick_tunnel"
    access_token: str | None = None
    business_account_id: str | None = None


class OllamaConfig(BaseModel):
    host: str = "http://127.0.0.1:11434"
    model: str = "llama3.2:3b"
    alternative_model: str = "qwen2.5:3b"
    timeout_seconds: int = 90
    keep_alive: int = 0


class GroqConfig(BaseModel):
    model: str = "qwen/qwen3.8-27b"
    timeout_seconds: int = 30
    api_key: str | None = None


class GeminiConfig(BaseModel):
    enabled: bool = True
    model: str = "gemini-3.5-flash-lite"
    text_model: str = "gemini-3.5-flash-lite"
    image_model: str = "imagen-3.0-generate-002"
    veo_enabled: bool = False
    max_images_per_video: int = 4
    max_veo_seconds_per_video: int = 8
    daily_budget: float = 5.0
    timeout_seconds: int = 30
    api_key: str | None = None
    api_keys: list[str] = Field(default_factory=list)


class HuggingFaceConfig(BaseModel):
    model: str = "Qwen/Qwen2.5-3B-Instruct"
    timeout_seconds: int = 45
    api_token: str | None = None


class LLMConfig(BaseModel):
    provider: Literal["ollama", "groq", "gemini", "huggingface"] = "ollama"
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    groq: GroqConfig = Field(default_factory=GroqConfig)
    gemini: GeminiConfig = Field(default_factory=GeminiConfig)
    huggingface: HuggingFaceConfig = Field(default_factory=HuggingFaceConfig)


class TTSConfig(BaseModel):
    provider: Literal["edge-tts", "say"] = "edge-tts"
    voice: str = "en-US-ChristopherNeural"
    alternative_voices: list[str] = Field(
        default_factory=lambda: [
            "en-US-GuyNeural",
            "en-GB-RyanNeural",
            "en-US-AriaNeural",
        ]
    )
    rate: str = "+5%"
    pitch: str = "+0Hz"
    cap_sentence_pause_seconds: float = 0.25
    offline_fallback: str = "say"


class SubtitleConfig(BaseModel):
    font_name: str = "Montserrat-ExtraBold"
    font_file: str = "assets/fonts/Montserrat-ExtraBold.ttf"
    words_per_group: int = 3
    safe_margin_y: int = 1380
    primary_color: str = "&H00FFFFFF"
    highlight_color: str = "&H0000FFFF"
    outline_color: str = "&H00000000"
    outline_width: int = 5


class VideoConfig(BaseModel):
    width: int = 1080
    height: int = 1920
    fps: int = 30
    target_duration_seconds: int = 30
    min_duration_seconds: int = 20
    max_duration_seconds: int = 40
    codec: str = "auto"
    bitrate: str = "9000k"
    watermark_text: str = "@NovaPrashantroy"
    subtitles: SubtitleConfig = Field(default_factory=SubtitleConfig)


class MusicConfig(BaseModel):
    default_volume: float = 0.12
    ducking_volume: float = 0.05
    fade_out_seconds: float = 2.0
    sfx_enabled: bool = True


class VisualsConfig(BaseModel):
    image_gen_enabled: bool = False
    min_match_score: float = 60.0
    illustrative_badge: bool = True
    max_ken_burns_zoom: float = 1.15
    providers_order: list[str] = Field(
        default_factory=lambda: [
            "pexels_video",
            "pixabay_video",
            "nasa_media",
            "wikimedia_commons",
            "openverse",
            "stock_photo_kenburns",
        ]
    )
    stock_providers: list[str] = Field(default_factory=lambda: ["pexels", "pixabay"])
    ken_burns_zoom_speed: float = 1.05
    flat_frame_threshold: float = 0.05


class AnimationConfig(BaseModel):
    enabled: bool = True
    intensity: str = "low"
    fps: int = 30


class AudienceConfig(BaseModel):
    primary_regions: list[str] = Field(default_factory=lambda: ["US", "GB", "CA", "AU"])
    spelling: str = "en-US"
    units: str = "imperial_with_metric"
    currency: str = "USD"


class NicheConfig(BaseModel):
    weight: float = 0.33
    enabled: bool = True
    name: str = "General"
    keywords: list[str] = Field(default_factory=list)
    banned_topics: list[str] = Field(default_factory=list)
    banned_phrases: list[str] = Field(default_factory=list)
    persona_tweaks: str = ""
    visual_query_hints: list[str] = Field(default_factory=list)
    hashtag_pool: list[str] = Field(default_factory=list)
    music_mood: str = "curious"


class ScheduleWindow(BaseModel):
    start: str = "12:00"
    end: str = "13:00"


class ScheduleConfig(BaseModel):
    audience_timezones: list[str] = Field(default_factory=lambda: ["America/New_York"])
    windows: list[ScheduleWindow] = Field(
        default_factory=lambda: [
            ScheduleWindow(start="12:00", end="13:00"),
            ScheduleWindow(start="18:00", end="21:00"),
        ]
    )
    enabled_platforms: dict[str, bool] = Field(default_factory=lambda: {"youtube": True, "instagram": True})


def _default_niches() -> dict[str, NicheConfig]:
    return {
        "ai_tech": NicheConfig(
            weight=0.50,
            enabled=True,
            name="AI & Technology",
            keywords=[
                "AI",
                "Artificial Intelligence",
                "Machine Learning",
                "LLM",
                "DeepSeek",
                "OpenAI",
                "Anthropic",
                "GPU",
                "NVIDIA",
                "Neural Network",
                "Robotics",
                "Algorithm",
            ],
            banned_topics=["crypto hype", "get rich with AI", "unsubstantiated AGI doomerism"],
            persona_tweaks="Explain what happened, why it matters, and provide one concrete comparison. No hype words like 'revolutionary' or 'game-changing'.",
            visual_query_hints=[
                "server room",
                "neural network code",
                "robotics laboratory",
                "semiconductor chip wafer",
            ],
            hashtag_pool=["#Shorts", "#ArtificialIntelligence", "#TechNews", "#MachineLearning", "#Coding"],
            music_mood="upbeat",
        ),
        "business": NicheConfig(
            weight=0.25,
            enabled=True,
            name="Business & Economics",
            keywords=[
                "economy",
                "billion",
                "revenue",
                "valuation",
                "market",
                "startup",
                "CEO",
                "antitrust",
                "monopoly",
                "supply chain",
                "inflation",
                "cost",
            ],
            banned_topics=["stock trading tips", "crypto shilling", "get rich quick"],
            banned_phrases=[
                "buy now",
                "guaranteed",
                "will crash",
                "get rich",
                "financial advice",
                "price prediction",
                "you should buy",
                "you should sell",
                "invest now",
                "massive returns",
                "to the moon",
                "easy money",
            ],
            persona_tweaks="Tell business stories and explain mechanisms (how a company makes money, why something costs so much). Never give financial advice. All numbers must carry time context.",
            visual_query_hints=[
                "stock market floor",
                "cargo shipping container port",
                "corporate skyscraper",
                "manufacturing line",
            ],
            hashtag_pool=["#Shorts", "#BusinessStories", "#Economics", "#Startups", "#MoneyExplained"],
            music_mood="mystery",
        ),
        "space_science": NicheConfig(
            weight=0.25,
            enabled=True,
            name="Space & Science",
            keywords=[
                "NASA",
                "astronomy",
                "physics",
                "universe",
                "galaxy",
                "telescope",
                "quantum",
                "black hole",
                "light speed",
                "neutron star",
                "planet",
                "exoplanet",
            ],
            banned_topics=["astrology", "flat earth", "ancient aliens"],
            persona_tweaks="Emphasize scale and wow comparisons. Double-check units with code conversions.",
            visual_query_hints=[
                "deep space telescope",
                "nebula galaxy",
                "astronomy observatory",
                "quantum physics lab",
            ],
            hashtag_pool=["#Shorts", "#Space", "#Science", "#Astronomy", "#MindBlowing"],
            music_mood="epic",
        ),
    }


class ReferenceChannelConfig(BaseModel):
    name: str
    channel_id: str | None = None
    handle: str | None = None
    niche: str = "ai_tech"
    note: str = ""


class ResearchConfig(BaseModel):
    max_daily_quota_units: int = 500
    outlier_threshold: float = 3.0
    reference_channels: list[ReferenceChannelConfig] = Field(default_factory=list)


class NovaSettings(BaseModel):
    app: AppConfig = Field(default_factory=AppConfig)
    content: ContentConfig = Field(default_factory=ContentConfig)
    audience: AudienceConfig = Field(default_factory=AudienceConfig)
    niches: dict[str, NicheConfig] = Field(default_factory=_default_niches)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    research: ResearchConfig = Field(default_factory=ResearchConfig)
    channel: ChannelConfig = Field(default_factory=ChannelConfig)
    collectors: CollectorsConfig = Field(default_factory=CollectorsConfig)
    publishing: PublishingConfig = Field(default_factory=PublishingConfig)
    youtube: YouTubeConfig = Field(default_factory=YouTubeConfig)
    instagram: InstagramConfig = Field(default_factory=InstagramConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    video: VideoConfig = Field(default_factory=VideoConfig)
    music: MusicConfig = Field(default_factory=MusicConfig)
    visuals: VisualsConfig = Field(default_factory=VisualsConfig)
    animation: AnimationConfig = Field(default_factory=AnimationConfig)
    gemini: GeminiConfig = Field(default_factory=GeminiConfig)

    def resolve_path(self, rel_or_abs: str | Path) -> Path:
        """Resolves relative paths to the project root directory."""
        p = Path(rel_or_abs)
        if p.is_absolute():
            return p
        return PROJECT_ROOT / p


def load_config(config_path: str | Path | None = None) -> NovaSettings:
    """Loads YAML configuration, overlays environment variables, and returns validated settings."""
    if config_path is None:
        target = PROJECT_ROOT / "config" / "config.yaml"
    else:
        target = Path(config_path)

    raw_data = {}
    if target.exists():
        with open(target, "r", encoding="utf-8") as f:
            raw_data = yaml.safe_load(f) or {}

    settings = NovaSettings(**raw_data)

    # Resolve and validate GOOGLE_APPLICATION_CREDENTIALS if present
    gac = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if gac:
        gac_p = Path(gac)
        if not gac_p.is_absolute():
            abs_p = PROJECT_ROOT / gac_p
            if abs_p.exists():
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(abs_p)

    # Inject environment variables
    if os.getenv("NOVA_DB_PATH"):
        settings.app.db_path = os.getenv("NOVA_DB_PATH")
    if os.getenv("CONTENT_LANGUAGE"):
        settings.content.language = os.getenv("CONTENT_LANGUAGE")  # type: ignore
    if os.getenv("OLLAMA_HOST"):
        settings.llm.ollama.host = os.getenv("OLLAMA_HOST")
    if os.getenv("GROQ_API_KEY"):
        settings.llm.groq.api_key = os.getenv("GROQ_API_KEY")
    gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEYS") or os.getenv("GOOGLE_API_KEY")
    if gemini_key:
        settings.llm.gemini.api_key = gemini_key
        settings.gemini.api_key = gemini_key
        parsed_keys = [k.strip().strip("\"'") for k in re.split(r"[,;\n\r\t]+", gemini_key.strip()) if k.strip()]
        settings.gemini.api_keys = parsed_keys
        settings.llm.gemini.api_keys = parsed_keys
    else:
        settings.gemini.api_keys = []
        settings.llm.gemini.api_keys = []
    if os.getenv("HF_TOKEN"):
        settings.llm.huggingface.api_token = os.getenv("HF_TOKEN")
    if os.getenv("INSTAGRAM_ACCESS_TOKEN"):
        settings.instagram.access_token = os.getenv("INSTAGRAM_ACCESS_TOKEN")
    if os.getenv("INSTAGRAM_BUSINESS_ACCOUNT_ID"):
        settings.instagram.business_account_id = os.getenv("INSTAGRAM_BUSINESS_ACCOUNT_ID")
    if os.getenv("YOUTUBE_CLIENT_SECRET_FILE"):
        settings.youtube.client_secret_file = os.getenv("YOUTUBE_CLIENT_SECRET_FILE")
    if os.getenv("YOUTUBE_TOKEN_FILE"):
        settings.youtube.token_file = os.getenv("YOUTUBE_TOKEN_FILE")

    return settings
