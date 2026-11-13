"""Base publishing interfaces and mock publisher for dry runs."""

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from nova.db import Script, Video
from nova.logging_setup import logger


@dataclass
class PublishResult:
    platform: str
    platform_post_id: str
    platform_url: str
    status: str  # 'success' or 'error'
    error_message: str = ""
    metadata: dict | None = None


class BasePublisher(ABC):
    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def publish(self, video: Video, script: Script) -> PublishResult:
        """Publishes the given video and returns the publication result."""


class MockPublisher(BasePublisher):
    """Simulates publishing without external credentials for testing and dry-runs."""

    def __init__(self, platform_name: str, output_dir: Path | str = "output"):
        super().__init__(name=f"mock_{platform_name}")
        self.platform_name = platform_name
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def publish(self, video: Video, script: Script) -> PublishResult:
        logger.info(f"[DRY-RUN / MOCK] Simulating publish to [bold magenta]{self.platform_name}[/bold magenta]...")

        mock_id = f"mock_{self.platform_name}_{video.id}_{int(datetime.now(UTC).timestamp())}"
        mock_url = (
            f"https://youtube.com/shorts/{mock_id}"
            if self.platform_name == "youtube"
            else f"https://instagram.com/reel/{mock_id}"
        )

        mock_payload = {
            "platform": self.platform_name,
            "mock_post_id": mock_id,
            "mock_url": mock_url,
            "video_id": video.id,
            "video_path": video.video_path,
            "title": script.title,
            "description": script.description,
            "hashtags": script.hashtags,
            "duration": video.duration_seconds,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        mock_file = self.output_dir / f"mock_publish_{self.platform_name}_video_{video.id}.json"
        mock_file.write_text(json.dumps(mock_payload, indent=2), encoding="utf-8")

        logger.info(f"[bold green]Mock publication recorded at: {mock_file.name}[/bold green]")
        return PublishResult(
            platform=self.platform_name,
            platform_post_id=mock_id,
            platform_url=mock_url,
            status="success",
            metadata=mock_payload,
        )
