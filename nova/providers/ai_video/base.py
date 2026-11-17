"""Abstract Base Class for AI Video Generation Providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional


class AIVideoJobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class AIVideoJob:
    job_id: str
    provider: str
    prompt: str
    status: AIVideoJobStatus
    duration_seconds: float
    aspect_ratio: str = "9:16"
    input_image_path: Optional[str] = None
    output_video_path: Optional[str] = None
    cost_usd: float = 0.0
    error_message: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseAIVideoProvider(ABC):
    """Abstract interface for text-to-video and image-to-video services."""

    def __init__(self, api_key: str | None = None, timeout_seconds: int = 60):
        self.api_key = api_key or ""
        self.timeout_seconds = timeout_seconds

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """Unique provider identifier (e.g. 'google_veo', 'runway', 'luma', 'kling')."""
        pass

    @abstractmethod
    def is_configured(self) -> bool:
        """Returns True if the required API credentials are set."""
        pass

    @abstractmethod
    def generate_video_from_text(
        self,
        prompt: str,
        duration_seconds: float = 4.0,
        aspect_ratio: str = "9:16",
        dest_path: Path | None = None,
    ) -> AIVideoJob:
        """Submits and awaits a text-to-video generation job."""
        pass

    @abstractmethod
    def generate_video_from_image(
        self,
        image_path: Path,
        prompt: str = "",
        duration_seconds: float = 4.0,
        aspect_ratio: str = "9:16",
        dest_path: Path | None = None,
    ) -> AIVideoJob:
        """Submits and awaits an image-to-video (motion conditioning) job."""
        pass
