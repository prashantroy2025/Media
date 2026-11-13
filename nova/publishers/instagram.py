"""Instagram Graph API publisher for Reels with temporary Cloudflare tunnel hosting."""

import os
import re
import subprocess
import threading
import time
from datetime import UTC, datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

import requests

from nova.config import NovaSettings
from nova.db import Script, Video
from nova.logging_setup import logger
from nova.publishers.base import BasePublisher, PublishResult


class FileServerThread:
    """Spins up a lightweight background HTTP server serving a single directory."""

    def __init__(self, directory: Path, port: int = 0):
        self.directory = directory

        def make_handler(*args):
            return SimpleHTTPRequestHandler(*args, directory=str(directory))

        self.server = HTTPServer(("127.0.0.1", port), make_handler)
        self.port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


class InstagramPublisher(BasePublisher):
    def __init__(self, settings: NovaSettings):
        super().__init__(name="instagram")
        self.settings = settings
        self.access_token = settings.instagram.access_token or os.getenv("INSTAGRAM_ACCESS_TOKEN")
        self.account_id = settings.instagram.business_account_id or os.getenv("INSTAGRAM_BUSINESS_ACCOUNT_ID")
        self.graph_version = "v19.0"

    def check_token_expiry(self) -> tuple[bool, str]:
        """Checks if long-lived token is valid and reports expiry days."""
        if not self.access_token:
            return False, "INSTAGRAM_ACCESS_TOKEN not set."
        url = f"https://graph.facebook.com/{self.graph_version}/debug_token"
        params = {"input_token": self.access_token, "access_token": self.access_token}
        try:
            r = requests.get(url, params=params, timeout=10)
            data = r.json().get("data", {})
            expires_at = data.get("expires_at", 0)
            if expires_at == 0:
                return True, "Never expires or page token"
            exp_date = datetime.fromtimestamp(expires_at, tz=UTC)
            days_left = (exp_date - datetime.now(UTC)).total_seconds() / 86400.0
            if days_left <= 7:
                return False, f"Token expires in {days_left:.1f} days! Needs refresh."
            return True, f"Valid ({days_left:.1f} days remaining)"
        except Exception as e:
            return False, f"Failed to check token expiry: {e}"

    def refresh_long_lived_token(self, client_id: str, client_secret: str) -> str | None:
        """Refreshes a 60-day Instagram long-lived user token."""
        url = "https://graph.facebook.com/v19.0/oauth/access_token"
        params = {
            "grant_type": "fb_exchange_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "fb_exchange_token": self.access_token,
        }
        res = requests.get(url, params=params, timeout=15)
        if res.status_code == 200:
            new_token = res.json().get("access_token")
            self.access_token = new_token
            return new_token
        return None

    def publish(self, video: Video, script: Script) -> PublishResult:
        if not self.access_token or not self.account_id:
            return PublishResult(
                platform="instagram",
                platform_post_id="",
                platform_url="",
                status="error",
                error_message="Instagram access token or account ID is not configured.",
            )

        video_path = Path(video.video_path)
        if not video_path.exists():
            return PublishResult(
                platform="instagram",
                platform_post_id="",
                platform_url="",
                status="error",
                error_message=f"Video file does not exist: {video_path}",
            )

        # Temporary public URL exposure via Cloudflare tunnel
        public_url, cleanup_fn = self._expose_video_temporarily(video_path)
        if not public_url:
            return PublishResult(
                platform="instagram",
                platform_post_id="",
                platform_url="",
                status="error",
                error_message="Failed to expose temporary public video URL via Cloudflare tunnel.",
            )

        try:
            # Format Caption with AI disclosure
            caption = f"{script.title}\n\n{script.description}\n\n{self.settings.instagram.disclosure_line}\n\n{script.hashtags}"

            # Step 1: Create media container for Reels
            create_url = f"https://graph.facebook.com/{self.graph_version}/{self.account_id}/media"
            create_payload = {
                "media_type": "REELS",
                "video_url": public_url,
                "caption": caption,
                "share_to_feed": "true",
                "access_token": self.access_token,
            }

            logger.info("Initiating Instagram Reel media container...")
            res = requests.post(create_url, data=create_payload, timeout=20)
            if res.status_code != 200:
                return PublishResult(
                    platform="instagram",
                    platform_post_id="",
                    platform_url="",
                    status="error",
                    error_message=f"Instagram media container creation failed: {res.text}",
                )

            creation_id = res.json().get("id")

            # Step 2: Poll container status until FINISHED
            status_url = f"https://graph.facebook.com/{self.graph_version}/{creation_id}"
            max_poll_sec = 180
            poll_interval = 5
            elapsed = 0
            container_ready = False

            while elapsed < max_poll_sec:
                time.sleep(poll_interval)
                elapsed += poll_interval
                poll_res = requests.get(
                    status_url,
                    params={"fields": "status_code,status", "access_token": self.access_token},
                    timeout=10,
                )
                if poll_res.status_code != 200:
                    continue

                status_code = poll_res.json().get("status_code")
                logger.info(f"Instagram container {creation_id} status: {status_code}")
                if status_code == "FINISHED":
                    container_ready = True
                    break
                elif status_code in ["ERROR", "EXPIRED"]:
                    return PublishResult(
                        platform="instagram",
                        platform_post_id="",
                        platform_url="",
                        status="error",
                        error_message=f"Instagram processing error: {poll_res.text}",
                    )

            if not container_ready:
                return PublishResult(
                    platform="instagram",
                    platform_post_id="",
                    platform_url="",
                    status="error",
                    error_message="Instagram video processing timed out.",
                )

            # Step 3: Publish container
            publish_url = f"https://graph.facebook.com/{self.graph_version}/{self.account_id}/media_publish"
            publish_res = requests.post(
                publish_url,
                data={"creation_id": creation_id, "access_token": self.access_token},
                timeout=20,
            )
            if publish_res.status_code != 200:
                return PublishResult(
                    platform="instagram",
                    platform_post_id="",
                    platform_url="",
                    status="error",
                    error_message=f"Instagram publish failed: {publish_res.text}",
                )

            media_id = publish_res.json().get("id")
            reel_url = f"https://www.instagram.com/reel/{media_id}/"
            logger.info(f"[bold green]Successfully published Instagram Reel: {reel_url}[/bold green]")

            return PublishResult(
                platform="instagram",
                platform_post_id=media_id,
                platform_url=reel_url,
                status="success",
                metadata=publish_res.json(),
            )
        finally:
            cleanup_fn()

    def _expose_video_temporarily(self, video_path: Path) -> tuple[str | None, callable]:
        """Starts a temporary local file server and exposes it with cloudflared quick tunnel."""
        server = FileServerThread(video_path.parent)
        server.start()

        tunnel_proc = None
        tunnel_url = None

        try:
            # Start cloudflared quick tunnel
            cmd = ["cloudflared", "tunnel", "--url", f"http://127.0.0.1:{server.port}"]
            tunnel_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )

            # Read tunnel URL from stdout/stderr (e.g. https://xxx.trycloudflare.com)
            start_time = time.time()
            while time.time() - start_time < 20:
                line = tunnel_proc.stdout.readline()
                if not line:
                    continue
                match = re.search(r"https://[a-zA-Z0-9\-]+\.trycloudflare\.com", line)
                if match:
                    tunnel_url = f"{match.group(0)}/{video_path.name}"
                    logger.info(f"Cloudflare quick tunnel active: {tunnel_url}")
                    break
        except Exception as e:
            logger.warning(f"cloudflared tunnel could not be started: {e}")

        def cleanup():
            if tunnel_proc:
                tunnel_proc.terminate()
            server.stop()

        return tunnel_url, cleanup
