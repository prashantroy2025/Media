"""YouTube Data API v3 publisher with resumable uploads and OAuth token management."""

import subprocess
import time
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from rich.console import Console

from nova.config import NovaSettings
from nova.db import DatabaseManager, Script, Video
from nova.logging_setup import logger
from nova.publishers.base import BasePublisher, PublishResult
from nova.schedule_engine import ScheduleEngine

YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


class YouTubePublisher(BasePublisher):
    def __init__(self, settings: NovaSettings):
        super().__init__(name="youtube")
        self.settings = settings
        self.client_secret_path = settings.resolve_path(settings.youtube.client_secret_file)
        self.token_path = settings.resolve_path(settings.youtube.token_file)
        self.alt_token_path = settings.resolve_path("data/youtube_token.json")

    def get_credentials(self) -> Credentials | None:
        """Loads valid user credentials from token file or starts browser OAuth flow."""
        creds = None
        target_path = self.token_path if self.token_path.exists() else self.alt_token_path
        if target_path.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(target_path), YOUTUBE_SCOPES)
            except Exception as e:
                logger.warning(f"Failed to read existing YouTube token from {target_path}: {e}")

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

            # Save refreshed/new token to both configured and standard locations
            self.token_path.parent.mkdir(parents=True, exist_ok=True)
            self.token_path.write_text(creds.to_json(), encoding="utf-8")
            self.alt_token_path.parent.mkdir(parents=True, exist_ok=True)
            self.alt_token_path.write_text(creds.to_json(), encoding="utf-8")

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


def run_youtube_auth(settings: NovaSettings) -> bool:
    """Explicit CLI authentication flow for YouTube Data API v3.
    Authorizes scopes, displays authenticated channel metadata, and saves token.
    """
    console = Console()
    console.print("\n[bold cyan]🔐 YouTube Data API v3 OAuth Authentication[/bold cyan]\n")

    secret_path = settings.resolve_path(settings.youtube.client_secret_file)
    if not secret_path.exists():
        console.print(f"[bold red]❌ Client secrets file missing at:[/bold red] {secret_path}")
        console.print("Please place your downloaded OAuth client secret from Google Cloud Console at that path.")
        return False

    token_path = settings.resolve_path(settings.youtube.token_file)
    alt_token_path = settings.resolve_path("data/youtube_token.json")

    console.print(f"Loading client secrets from: [white]{secret_path}[/white]")
    console.print("Required Scopes:")
    for sc in YOUTUBE_SCOPES:
        console.print(f"  - {sc}")

    try:
        flow = InstalledAppFlow.from_client_secrets_file(
            str(secret_path),
            YOUTUBE_SCOPES,
        )
        console.print("\n[yellow]Launching local browser OAuth consent screen...[/yellow]")
        creds = flow.run_local_server(port=0, prompt="consent")

        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json(), encoding="utf-8")
        alt_token_path.parent.mkdir(parents=True, exist_ok=True)
        alt_token_path.write_text(creds.to_json(), encoding="utf-8")

        # Query channel snippet to verify API access
        youtube = build("youtube", "v3", credentials=creds)
        res = youtube.channels().list(mine=True, part="snippet,statistics").execute()
        items = res.get("items", [])

        if items:
            ch = items[0]
            title = ch.get("snippet", {}).get("title", "Unknown Channel")
            handle = ch.get("snippet", {}).get("customUrl", "")
            subs = ch.get("statistics", {}).get("subscriberCount", "Hidden")
            vids = ch.get("statistics", {}).get("videoCount", "0")

            console.print(f"\n[bold green]✓ Successfully Authenticated Channel:[/bold green] [bold white]{title}[/bold white] ({handle})")
            console.print(f"  Subscribers: {subs} | Videos Uploaded: {vids}")
            console.print(f"  Saved token to: [cyan]{token_path}[/cyan] and [cyan]{alt_token_path}[/cyan]\n")
            return True
        else:
            console.print("\n[bold green]✓ Credentials authorized successfully![/bold green] (No channel associated with this Google Account yet).")
            return True
    except Exception as e:
        console.print(f"\n[bold red]❌ OAuth authentication failed:[/bold red] {e}")
        return False


def upload_test_video(settings: NovaSettings, db_mgr: DatabaseManager) -> bool:
    """Generates a tiny 3-second black test clip and uploads to YouTube as private to verify upload access."""
    console = Console()
    console.print("\n[bold cyan]🚀 Running YouTube Private Upload Test...[/bold cyan]\n")

    pub = YouTubePublisher(settings)
    creds = pub.get_credentials()
    if not creds:
        console.print("[bold red]❌ No valid YouTube credentials. Run `python -m nova auth youtube` first.[/bold red]")
        return False

    out_dir = settings.resolve_path(settings.app.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    test_video_path = out_dir / "test_upload_probe.mp4"

    # Generate 3-second 1080x1920 test MP4 using ffmpeg lavfi
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "color=c=black:s=1080x1920:d=3.0:r=30",
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
        "-t", "3.0",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        str(test_video_path.resolve())
    ]
    res = subprocess.run(cmd, capture_output=True)
    if res.returncode != 0:
        console.print(f"[bold red]Failed to create test video clip:[/bold red] {res.stderr.decode()}")
        return False

    dummy_script = Script(
        title="Nova Autopilot Test Probe #Shorts",
        hook="Nova Autopilot private pipeline probe.",
        description="Private connectivity verification test upload by Nova Autopilot.\n[AI Assisted Production]",
        hashtags="#Shorts #Testing",
    )
    dummy_video = Video(
        video_path=str(test_video_path),
        duration_seconds=3.0,
    )

    console.print(f"Uploading private 3.0s probe clip to YouTube: [white]{dummy_video.video_path}[/white]...")
    pub_res = pub.publish(dummy_video, dummy_script)

    if pub_res.status == "success":
        vid_id = pub_res.platform_post_id
        console.print("\n[bold green]✓ Test Upload Succeeded![/bold green]")
        console.print(f"  Short URL: [cyan]{pub_res.platform_url}[/cyan]")
        console.print(f"  YouTube Studio Edit Link: [bold cyan]https://studio.youtube.com/video/{vid_id}/edit[/bold cyan]")
        console.print("  Privacy: [yellow]PRIVATE[/yellow] (Safe, not visible to public subscribers)\n")
        return True
    else:
        console.print(f"\n[bold red]❌ Upload Test Failed:[/bold red] {pub_res.error_message}")
        return False

