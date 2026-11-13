"""YouTube Data API v3 publisher with resumable uploads and OAuth token management."""

import time
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from nova.config import NovaSettings
from nova.db import Script, Video
from nova.logging_setup import logger
from nova.publishers.base import BasePublisher, PublishResult
from nova.schedule_engine import ScheduleEngine

YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


class YouTubePublisher(BasePublisher):
    def __init__(self, settings: NovaSettings):
        super().__init__(name="youtube")
        self.settings = settings
        self.client_secret_path = settings.resolve_path(settings.youtube.client_secret_file)
        self.token_path = settings.resolve_path(settings.youtube.token_file)

    def get_credentials(self) -> Credentials | None:
        """Loads valid user credentials from token file or starts browser OAuth flow."""
        creds = None
        if self.token_path.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(self.token_path), YOUTUBE_SCOPES)
            except Exception as e:
                logger.warning(f"Failed to read existing YouTube token: {e}")

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                logger.info("Refreshing expired YouTube OAuth credentials...")
                try:
                    creds.refresh(Request())
                except Exception as e:
                    logger.warning(f"Token refresh failed: {e}. Re-authenticating...")
                    creds = None

            if not creds:
                if not self.client_secret_path.exists():
                    logger.error(
                        f"YouTube client secrets file not found at: {self.client_secret_path}. "
                        "Download it from Google Cloud Console > APIs & Services > Credentials."
                    )
                    return None

                logger.info("Starting local YouTube OAuth desktop flow...")
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self.client_secret_path),
                    YOUTUBE_SCOPES,
                )
                creds = flow.run_local_server(port=0)

            # Save refreshed/new token
            self.token_path.parent.mkdir(parents=True, exist_ok=True)
            self.token_path.write_text(creds.to_json(), encoding="utf-8")

        return creds

    def publish(self, video: Video, script: Script) -> PublishResult:
        """Uploads the video as a YouTube Short via resumable upload."""
        creds = self.get_credentials()
        if not creds:
            return PublishResult(
                platform="youtube",
                platform_post_id="",
                platform_url="",
                status="error",
                error_message="Missing or invalid YouTube OAuth credentials.",
            )

        video_path = Path(video.video_path)
        if not video_path.exists():
            return PublishResult(
                platform="youtube",
                platform_post_id="",
                platform_url="",
                status="error",
                error_message=f"Video file does not exist: {video_path}",
            )

        youtube = build("youtube", "v3", credentials=creds)

        # Build Title: Ensure #Shorts is included
        title = script.title
        if "#Shorts" not in title and "#shorts" not in title:
            if len(title) <= 90:
                title = f"{title} #Shorts"

        # Build Description with attribution and AI disclosure
        description = script.description
        if self.settings.youtube.synthetic_media_disclosure:
            description += "\n\n⚡ Altered or synthetic content: Visuals or narration were digitally assisted and created by @NovaPrashantroy."

        tags = [t.replace("#", "") for t in script.hashtags.split()]
        tags.extend(["Shorts", "AI", "Technology", "NovaPrashantroy"])

        body = {
            "snippet": {
                "title": title[:100],
                "description": description,
                "tags": tags[:20],
                "categoryId": self.settings.youtube.category_id,
            },
            "status": {
                "privacyStatus": self.settings.youtube.default_privacy,
                "selfDeclaredMadeForKids": self.settings.youtube.self_declared_made_for_kids,
            },
        }

        # If video has a scheduled publishing time, configure YouTube status.publishAt
        if video.scheduled_time_utc:
            publish_at_str = ScheduleEngine.build_youtube_publish_at(video.scheduled_time_utc)
            body["status"]["privacyStatus"] = "private"
            body["status"]["publishAt"] = publish_at_str
            logger.info(
                f"Configured YouTube status.publishAt to {publish_at_str} (US Eastern: {video.scheduled_time_us_eastern})"
            )

        media = MediaFileUpload(
            str(video_path.resolve()),
            mimetype="video/mp4",
            chunksize=4 * 1024 * 1024,
            resumable=True,
        )

        request = youtube.videos().insert(
            part=",".join(body.keys()),
            body=body,
            media_body=media,
        )

        logger.info(f"Uploading '{title}' to YouTube (resumable)...")
        response = None
        retry = 0
        while response is None:
            try:
                status, response = request.next_chunk()
                if status:
                    logger.info(f"YouTube upload progress: {int(status.progress() * 100)}%")
            except HttpError as e:
                if "publishAt" in str(e) or "invalidPublishAt" in str(e):
                    logger.warning(
                        f"YouTube rejected publishAt ({e}). Notice: In unverified/testing Google Cloud projects, "
                        f"scheduled publishing may be restricted until advanced channel features are verified. "
                        f"Falling back to upload with default privacy: {self.settings.youtube.default_privacy}"
                    )
                    body["status"].pop("publishAt", None)
                    body["status"]["privacyStatus"] = self.settings.youtube.default_privacy
                    request = youtube.videos().insert(
                        part=",".join(body.keys()),
                        body=body,
                        media_body=MediaFileUpload(str(video_path.resolve()), mimetype="video/mp4", resumable=True),
                    )
                    continue
                elif e.resp.status in [500, 502, 503, 504]:
                    retry += 1
                    if retry > 5:
                        raise
                    time.sleep(2**retry)
                elif "quotaExceeded" in str(e):
                    logger.error("YouTube Data API quota exceeded for today.")
                    return PublishResult(
                        platform="youtube",
                        platform_post_id="",
                        platform_url="",
                        status="error",
                        error_message="YouTube Data API daily quota exceeded.",
                    )
                else:
                    raise

        video_id = response.get("id")
        yt_url = f"https://youtube.com/shorts/{video_id}"
        logger.info(f"[bold green]Successfully uploaded YouTube Short: {yt_url}[/bold green]")

        return PublishResult(
            platform="youtube",
            platform_post_id=video_id,
            platform_url=yt_url,
            status="success",
            metadata=response,
        )
