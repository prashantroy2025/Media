"""Background music selection, volume ducking, sound effects, and starter pack fetcher."""

import csv
import random
import re
import subprocess
import wave
from pathlib import Path

import numpy as np
import requests

from nova.config import NovaSettings
from nova.logging_setup import logger

MOOD_SUBFOLDERS = ["epic", "mystery", "curious", "upbeat"]


class MusicManager:
    def __init__(self, settings: NovaSettings):
        self.settings = settings
        self.music_dir = settings.resolve_path("assets/music")
        self.music_dir.mkdir(parents=True, exist_ok=True)
        self.sfx_dir = settings.resolve_path("assets/sfx")
        self.sfx_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_sfx()

    def get_track(self, mood: str | None = None) -> tuple[Path | None, dict]:
        """Finds an available royalty-free audio track by mood, returning path and attribution metadata."""
        valid_extensions = {".mp3", ".wav", ".aac", ".m4a"}
        candidate_dirs = []

        if mood and (self.music_dir / mood).exists():
            candidate_dirs.append(self.music_dir / mood)
        for m in MOOD_SUBFOLDERS:
            p = self.music_dir / m
            if p.exists() and p not in candidate_dirs:
                candidate_dirs.append(p)
        candidate_dirs.append(self.music_dir)

        tracks = []
        for d in candidate_dirs:
            for f in d.iterdir():
                if f.is_file() and f.suffix.lower() in valid_extensions and not f.name.startswith("."):
                    tracks.append(f)

        if not tracks:
            logger.warning(
                "No royalty-free music files found in assets/music/. "
                "Producing voice-only video. Run 'python -m nova fetch-music' to download a starter pack!"
            )
            return None, {}

        chosen = random.choice(tracks)
        attribution = self._lookup_attribution(chosen)
        return chosen, attribution

    def _lookup_attribution(self, track_file: Path) -> dict:
        """Reads LICENSES.csv if present to find author and license."""
        csv_file = self.music_dir / "LICENSES.csv"
        if not csv_file.exists():
            return {"title": track_file.stem, "license": "Royalty-Free"}

        try:
            with open(csv_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get("filename") in str(track_file) or row.get("title") in track_file.stem:
                        return row
        except Exception:
            pass
        return {"title": track_file.stem, "license": "Royalty-Free"}

    def _ensure_sfx(self):
        """Synthesizes high-impact whoosh and sub-drop sound effects via numpy if missing."""
        whoosh_p = self.sfx_dir / "whoosh.wav"
        impact_p = self.sfx_dir / "impact.wav"
        sample_rate = 44100

        if not whoosh_p.exists():
            dur = 0.35
            t = np.linspace(0, dur, int(sample_rate * dur), False)
            noise = np.random.normal(0, 1, len(t))
            sweep = 200 + 2000 * np.sin(np.pi * t / dur)
            phase = 2 * np.pi * np.cumsum(sweep) / sample_rate
            mod = np.sin(phase)
            env = np.sin(np.pi * t / dur) ** 2
            data = (noise * 0.6 + mod * 0.4) * env
            self._save_wav(whoosh_p, data, sample_rate)

        if not impact_p.exists():
            dur = 0.45
            t_i = np.linspace(0, dur, int(sample_rate * dur), False)
            freq_drop = 40 + 140 * np.exp(-12 * t_i)
            phase_i = 2 * np.pi * np.cumsum(freq_drop) / sample_rate
            sub = np.sin(phase_i)
            env_i = np.exp(-6 * t_i)
            click = np.random.normal(0, 1, len(t_i)) * np.exp(-80 * t_i)
            data_i = (sub * 0.8 + click * 0.2) * env_i
            self._save_wav(impact_p, data_i, sample_rate)

    def _save_wav(self, path: Path, data: np.ndarray, sample_rate: int):
        max_val = np.max(np.abs(data))
        if max_val > 0:
            data = (data / max_val) * 0.9
        int_data = (data * 32767).astype(np.int16)
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(int_data.tobytes())

    def mix_audio(
        self,
        voice_path: Path,
        output_audio_path: Path,
        total_duration: float,
        mood: str | None = None,
        sfx_timestamps: list[float] | None = None,
    ) -> tuple[Path, dict]:
        """Mixes voice-over with background music, ducking, fade-out, and sound effects."""
        track, attr = self.get_track(mood)
        output_audio_path.parent.mkdir(parents=True, exist_ok=True)

        if not track:
            # Voice-only copy
            logger.info("Proceeding with voice-only track (no background music).")
            cmd = [
                "ffmpeg",
                "-y",
                "-i",
                str(voice_path.resolve()),
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-ar",
                "44100",
                str(output_audio_path.resolve()),
            ]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            return output_audio_path, attr

        logger.info(f"Mixing background track '[cyan]{track.name}[/cyan]' with voice ducking (12%)...")
        bg_vol = self.settings.music.default_volume
        fade_time = self.settings.music.fade_out_seconds
        fade_start = max(0.0, total_duration - fade_time)

        # Loop background music, scale volume, apply fade-out at end, mix with voice
        filter_complex = (
            f"[1:a]aloop=loop=-1:size=2e+09,volume={bg_vol},"
            f"afade=t=out:st={fade_start}:d={fade_time}[bg];"
            f"[0:a][bg]amix=inputs=2:duration=first:dropout_transition=2[outa]"
        )

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(voice_path.resolve()),
            "-i",
            str(track.resolve()),
            "-filter_complex",
            filter_complex,
            "-map",
            "[outa]",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-t",
            str(total_duration),
            str(output_audio_path.resolve()),
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return output_audio_path, attr

    def fetch_music_starter_pack(self) -> int:
        """Downloads a starter pack of CC0/CC-BY ambient music from Openverse/Wikimedia into mood folders."""
        logger.info("Fetching starter pack of royalty-free ambient music from Openverse / Wikimedia...")
        headers = {"User-Agent": "NovaAutopilot/2.0 (contact: info@novastudio.local)"}
        licenses = []
        count = 0

        # Curated CC0 / Public Domain background tracks
        curated_tracks = [
            (
                "epic",
                "Cinematic Space Ambient",
                "https://upload.wikimedia.org/wikipedia/commons/4/4e/Apollo_11_Moonwalk_ambient.ogg",
                "Public Domain",
                "NASA / Wikimedia Commons",
            ),
            (
                "curious",
                "Acoustic Curiosity",
                "https://upload.wikimedia.org/wikipedia/commons/e/ec/Short_ambient_loop.ogg",
                "CC0 1.0 Universal",
                "Wikimedia Contributor",
            ),
        ]

        for mood, title, url, license_str, creator in curated_tracks:
            mood_dir = self.music_dir / mood
            mood_dir.mkdir(parents=True, exist_ok=True)
            safe_name = title.lower().replace(" ", "_")
            dest = mood_dir / f"{safe_name}.mp3"

            try:
                r = requests.get(url, headers=headers, stream=True, timeout=15)
                if r.status_code == 200:
                    temp_ogg = mood_dir / f"{safe_name}.temp.ogg"
                    with open(temp_ogg, "wb") as f:
                        for chunk in r.iter_content(chunk_size=16384):
                            f.write(chunk)
                    # Convert to MP3
                    cmd = ["ffmpeg", "-y", "-i", str(temp_ogg), "-c:a", "libmp3lame", "-b:a", "192k", str(dest)]
                    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    temp_ogg.unlink(missing_ok=True)
                    count += 1
                    licenses.append(
                        {
                            "filename": str(dest.relative_to(self.music_dir)),
                            "mood": mood,
                            "title": title,
                            "artist": creator,
                            "license": license_str,
                            "source_url": url,
                        }
                    )
                    logger.info(f"Downloaded starter track for mood '{mood}': {dest.name}")
            except Exception as e:
                logger.debug(f"Failed to fetch curated track {title}: {e}")

        # Try Openverse for any remaining moods
        for mood in MOOD_SUBFOLDERS:
            mood_dir = self.music_dir / mood
            mood_dir.mkdir(parents=True, exist_ok=True)
            if any(mood_dir.iterdir()):
                continue

            try:
                api_url = f"https://api.openverse.org/v1/audio/?q={mood}&license_type=all-cc&page_size=3"
                res = requests.get(api_url, headers=headers, timeout=12)
                if res.status_code == 200:
                    results = res.json().get("results", [])
                    for item in results:
                        audio_url = item.get("url")
                        t_title = item.get("title", f"{mood}_track")
                        lic = item.get("license", "CC").upper()
                        if audio_url and lic.lower() in ["cc0", "pdm", "by"]:
                            safe_t = re.sub(r"[^\w\s-]", "", t_title)[:25].strip() or "track"
                            dest_mp3 = mood_dir / f"{safe_t}.mp3"
                            ar = requests.get(audio_url, headers=headers, stream=True, timeout=12)
                            if ar.status_code == 200:
                                with open(dest_mp3, "wb") as f:
                                    for c in ar.iter_content(chunk_size=16384):
                                        f.write(c)
                                count += 1
                                licenses.append(
                                    {
                                        "filename": str(dest_mp3.relative_to(self.music_dir)),
                                        "mood": mood,
                                        "title": t_title,
                                        "artist": item.get("creator", "Openverse Artist"),
                                        "license": lic,
                                        "source_url": item.get("foreign_landing_url", audio_url),
                                    }
                                )
                                logger.info(f"Downloaded Openverse track for mood '{mood}': {dest_mp3.name}")
                                break
            except Exception as e:
                logger.debug(f"Openverse starter music fetch failed for '{mood}': {e}")

        if licenses:
            csv_path = self.music_dir / "LICENSES.csv"
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["filename", "mood", "title", "artist", "license", "source_url"])
                writer.writeheader()
                writer.writerows(licenses)
            logger.info(f"[bold green]Saved LICENSES.csv with {len(licenses)} track credits.[/bold green]")

        return count
