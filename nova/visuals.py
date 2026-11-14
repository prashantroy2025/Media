"""Sentence-Level Visual Asset Manager for Nova Autopilot v4.0.

Provides sentence-matched video/image visuals with strict relevance scoring and provider gating:
1. Pexels Videos API (if key present)
2. Pixabay Videos API (if key present)
3. Pexels / Pixabay Photos with Ken Burns pan/zoom
4. Wikimedia Commons API (Keyless, Public Domain / CC-BY)
5. Openverse API (Keyless, Creative Commons filtered)
6. NASA Image & Video Library (Keyless, ONLY allowed for Space/Science niche with space entities)
7. Fallback Explainer Card: dynamic typography + drawn icon + Ken Burns motion (NEVER flat color)
"""

import hashlib
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from nova.config import NovaSettings
from nova.animation.templates import render_data_card_for_beat
from nova.beats import Beat, BeatPlanner, BeatType
from nova.gemini import GeminiClient, VisualRoute
from nova.logging_setup import logger
from nova.relevance import CandidateVisual, VisualRelevanceScorer
from nova.relevance_gate import RelevanceGate
from nova.timeline import ShotPlan

SPACE_KEYWORDS = {
    "space",
    "planet",
    "galaxy",
    "universe",
    "telescope",
    "star",
    "nebula",
    "black hole",
    "neutron star",
    "rocket",
    "astronaut",
    "mars",
    "jupiter",
    "saturn",
    "moon",
    "solar",
    "orbit",
    "exoplanet",
    "astronomy",
    "cosmic",
    "hubble",
    "webb",
    "nasa",
    "pulsar",
    "astrophysics",
    "interstellar",
    "voyager",
}

# Banned query placeholder strings that must never be queried
BANNED_VISUAL_PLACEHOLDERS = {
    "concrete noun",
    "main subject",
    "visible motion",
    "high speed engineering",
    "global network",
    "breakthrough summary",
    "key stat",
    "key findings",
    "environment",
    "subject in motion",
    "specific query 1",
    "specific query 2",
    "broad query 3",
    "specific footage search term",
    "search term",
    "footage",
    "specific query",
    "visual query",
}

# Abstract words that cannot serve as footage visual queries
ABSTRACT_VISUAL_WORDS = {
    "breakthrough",
    "summary",
    "global network",
    "innovation",
    "mystery",
    "truth",
    "shocking",
    "reality",
    "secret",
    "update",
    "overview",
    "fallout",
    "impact",
    "effects",
    "effect",
    "details",
    "data",
    "story",
    "history",
    "future",
    "clash",
    "crisis",
    "pressure",
    "outbursts",
    "outburst",
}

VISUAL_STOPWORDS = {
    "a",
    "an",
    "the",
    "in",
    "on",
    "at",
    "by",
    "for",
    "with",
    "about",
    "against",
    "between",
    "into",
    "through",
    "during",
    "before",
    "after",
    "above",
    "below",
    "to",
    "from",
    "up",
    "down",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "have",
    "has",
    "had",
    "it",
    "its",
    "they",
    "them",
    "their",
    "this",
    "that",
    "these",
    "those",
}


def is_valid_visual_query(query: str) -> bool:
    """Rejects placeholder strings, single characters, pure stopwords, abstract words, or raw numbers."""
    if not query:
        return False
    q_clean = re.sub(r"[^\w\s]", "", query).strip().lower()
    if len(q_clean) <= 2:
        return False
    if q_clean in VISUAL_STOPWORDS:
        return False
    if q_clean in ABSTRACT_VISUAL_WORDS:
        return False
    if any(bp in q_clean for bp in BANNED_VISUAL_PLACEHOLDERS):
        return False
    # Reject pure numbers or monetary figures (e.g., "$100 million", "100", "2024")
    tokens = q_clean.split()
    if all(tok.isdigit() or tok in {"million", "billion", "dollars", "percent", "tons"} for tok in tokens):
        return False
    return True


def generate_concrete_queries(sentence_text: str, main_subject: str = "", niche: str = "ai_tech") -> list[str]:
    """Generates 3 concrete footage variants: specific, action/context, broad setting."""
    text_lower = f"{sentence_text} {main_subject}".lower()

    if niche == "space_science":
        if any(term in text_lower for term in ["neutron star", "pulsar", "magnetar"]):
            return ["neutron star space", "star explosion cosmic", "galaxy night sky"]
        elif any(term in text_lower for term in ["black hole", "singularity", "event horizon"]):
            return ["black hole accretion disk", "deep space galaxy", "cosmic nebula"]
        elif any(term in text_lower for term in ["planet", "mars", "europa", "jupiter", "moon"]):
            return ["planet orbit space", "spacecraft planetary mission", "solar system astronomy"]
        elif any(term in text_lower for term in ["telescope", "webb", "hubble"]):
            return ["space telescope satellite", "deep space stars", "observatory night sky"]
        return ["galaxy deep space", "stars cosmic nebula", "night sky astronomy"]

    if niche == "ai_tech":
        if any(term in text_lower for term in ["chip", "blackwell", "processor", "gpu", "tsmc", "semiconductor"]):
            return ["computer microchip close up", "server room data center", "technology circuit board"]
        elif any(term in text_lower for term in ["waymo", "robotaxi", "car", "autonomous", "driving"]):
            return ["self driving car street", "autonomous vehicle city traffic", "modern highway traffic"]
        elif any(term in text_lower for term in ["deepseek", "claude", "model", "software", "code", "ai"]):
            return ["data center server room", "computer programming code screen", "technology artificial intelligence"]
        return ["technology server room", "computer microchip close up", "modern science laboratory"]

    if niche == "business":
        return ["corporate office building", "business boardroom meeting", "financial stock market chart"]

    # Fallback concrete footage queries
    clean_sub = re.sub(r"[^\w\s]", "", main_subject).strip()
    if clean_sub and is_valid_visual_query(clean_sub):
        return [f"{clean_sub} close up", f"{clean_sub} technology", "modern science laboratory"]
    return ["modern technology laboratory", "scientific experiment research", "data network close up"]


def get_media_duration(file_path: Path) -> float:
    """Uses ffprobe to extract exact duration of media file in seconds."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(file_path),
    ]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return float(res.stdout.strip())
    except Exception:
        return 3.0


def fit_video_shot(input_video: Path, output_video: Path, target_duration: float, fps: int = 30) -> None:
    """Normalizes stock video to 1080x1920, 30fps CFR, exact target duration."""
    output_video.parent.mkdir(parents=True, exist_ok=True)
    src_duration = get_media_duration(input_video)
    t_dur = round(target_duration, 3)

    if src_duration >= t_dur:
        offset = max(0.0, (src_duration - t_dur) / 3.0)
        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            f"{offset:.2f}",
            "-i",
            str(input_video.resolve()),
            "-vf",
            "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,format=yuv420p",
            "-t",
            str(t_dur),
            "-r",
            str(fps),
            "-fps_mode",
            "cfr",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(output_video.resolve()),
        ]
    elif src_duration >= 0.75 * t_dur and src_duration > 0.5:
        speed_factor = t_dur / src_duration
        filter_chain = f"setpts={speed_factor:.4f}*PTS,scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,format=yuv420p"
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(input_video.resolve()),
            "-vf",
            filter_chain,
            "-t",
            str(t_dur),
            "-r",
            str(fps),
            "-fps_mode",
            "cfr",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(output_video.resolve()),
        ]
    else:
        filter_chain = (
            f"[0:v]reverse[r];[0:v][r]concat=n=2:v=1[pp];[pp]loop=loop=-1:size=300,setpts=N/({fps}*TB),"
            f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,format=yuv420p[outv]"
        )
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(input_video.resolve()),
            "-filter_complex",
            filter_chain,
            "-map",
            "[outv]",
            "-t",
            str(t_dur),
            "-r",
            str(fps),
            "-fps_mode",
            "cfr",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(output_video.resolve()),
        ]

    res = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
    if res.returncode != 0:
        logger.error(f"fit_video_shot failed: {res.stderr}")
        raise RuntimeError(f"FFmpeg video fitting failed: {res.stderr}")


def fit_image_shot(
    image_path: Path,
    output_video: Path,
    target_duration: float,
    fps: int = 30,
    direction: str = "zoom_in",
) -> None:
    """Applies cinematic Ken Burns zoom/pan with varying direction to a still image, normalized to 1080x1920 30fps CFR."""
    output_video.parent.mkdir(parents=True, exist_ok=True)
    t_dur = round(target_duration, 3)
    total_frames = max(1, int(round(t_dur * fps)))

    # Ensure source image is clean decodeable RGB JPEG before feeding to ffmpeg
    clean_image_path = None
    try:
        with Image.open(image_path) as img:
            rgb_img = img.convert("RGB")
            clean_image_path = output_video.with_suffix(".sanitized.jpg")
            rgb_img.save(clean_image_path, "JPEG", quality=95)
        source_input = clean_image_path
    except Exception as e:
        logger.warning(f"PIL pre-sanitization failed for {image_path}: {e}")
        source_input = image_path

    try:
        if direction == "zoom_out":
            zoom_expr = f"zoompan=z=\x27if(lte(zoom,1.0),1.15,max(1.001,zoom-0.0008))\x27:d={total_frames}:x=\x27iw/2-(iw/zoom/2)\x27:y=\x27ih/2-(ih/zoom/2)\x27:s=1080x1920:fps={fps}"
        elif direction == "pan_right":
            zoom_expr = f"zoompan=z=1.12:d={total_frames}:x=\x27(on/{total_frames})*(iw-iw/zoom)\x27:y=\x27ih/2-(ih/zoom/2)\x27:s=1080x1920:fps={fps}"
        elif direction == "pan_left":
            zoom_expr = f"zoompan=z=1.12:d={total_frames}:x=\x27(1-(on/{total_frames}))*(iw-iw/zoom)\x27:y=\x27ih/2-(ih/zoom/2)\x27:s=1080x1920:fps={fps}"
        else:  # zoom_in default
            zoom_expr = f"zoompan=z=\x27min(zoom+0.0008,1.15)\x27:d={total_frames}:x=\x27iw/2-(iw/zoom/2)\x27:y=\x27ih/2-(ih/zoom/2)\x27:s=1080x1920:fps={fps}"

        filter_chain = f"scale=1080x1920:force_original_aspect_ratio=increase,crop=1080:1920,{zoom_expr},setsar=1,format=yuv420p"

        cmd = [
            "ffmpeg",
            "-y",
            "-loop",
            "1",
            "-i",
            str(source_input.resolve()),
            "-vf",
            filter_chain,
            "-t",
            str(t_dur),
            "-r",
            str(fps),
            "-fps_mode",
            "cfr",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(output_video.resolve()),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
        if res.returncode != 0:
            logger.error(f"fit_image_shot failed: {res.stderr}")
            raise RuntimeError(f"FFmpeg image Ken Burns failed: {res.stderr}")
    finally:
        if clean_image_path and clean_image_path.exists():
            try:
                clean_image_path.unlink()
            except Exception:
                pass


@dataclass
class VisualAsset:
    file_path: Path
    provider: str
    asset_id: str
    creator_name: str
    creator_url: str
    license_name: str
    asset_url: str
    relevance_score: float = 100.0
    preview_path: str = ""
    is_fallback_card: bool = False
    diagnostic_info: dict[str, Any] = field(default_factory=dict)
    license_proof: Any = None


class VisualsManager:
    def __init__(self, settings: NovaSettings):
        self.settings = settings
        self.cache_dir = settings.resolve_path(settings.app.cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.pexels_key = os.getenv("PEXELS_API_KEY", "")
        self.pixabay_key = os.getenv("PIXABAY_API_KEY", "")
        self.used_asset_ids: set[str] = set()
        self.scorer = VisualRelevanceScorer(min_threshold=40.0)

        # Multi-provider infrastructure & local library
        from nova.providers.registry import ProviderRegistry
        from nova.library.searcher import MediaLibrarySearcher
        self.registry = ProviderRegistry()
        self.library_searcher = MediaLibrarySearcher()
        self.gemini_client = GeminiClient(settings)
        self.ai_hero_video_generated = False

    def get_sentence_visual(
        self,
        sentence_index: int,
        main_subject: str,
        action_or_state: str,
        queries: list[str],
        duration: float,
        dest_video_path: Path,
        niche: str = "ai_tech",
        on_screen_label: str | None = None,
    ) -> VisualAsset:
        """Retrieves or synthesizes a 1080x1920 video clip strictly matching the spoken sentence."""
        dest_video_path.parent.mkdir(parents=True, exist_ok=True)
        clean_queries = self._clean_queries(queries, main_subject, niche=niche)

        # 1. Collect candidates across providers with diagnostic tracking
        candidates: list[CandidateVisual] = []
        providers_called: list[str] = []
        candidate_counts: dict[str, int] = {}

        # Check Pexels Video (Priority if key configured)
        if self.pexels_key:
            providers_called.append("pexels")
            p_cands = []
            for q in clean_queries[:2]:
                cands = self._search_pexels_videos(q)
                p_cands.extend(cands)
            candidate_counts["pexels"] = len(p_cands)
            candidates.extend(p_cands)

        # Check Pixabay Video (Priority if key configured)
        if self.pixabay_key:
            providers_called.append("pixabay")
            px_cands = []
            for q in clean_queries[:2]:
                cands = self._search_pixabay_videos(q)
                px_cands.extend(cands)
            candidate_counts["pixabay"] = len(px_cands)
            candidates.extend(px_cands)

        # Check Wikimedia Commons (Keyless, General)
        providers_called.append("wikimedia")
        w_cands = []
        for q in clean_queries[:2]:
            cands = self._fetch_wikimedia_commons(q)
            if cands:
                w_cands.extend(cands)
        candidate_counts["wikimedia"] = len(w_cands)
        candidates.extend(w_cands)

        # Check Openverse (Keyless, General - tight timeout)
        providers_called.append("openverse")
        ov_cands = []
        for q in clean_queries[:1]:
            cands = self._fetch_openverse_media(q)
            if cands:
                ov_cands.extend(cands)
        candidate_counts["openverse"] = len(ov_cands)
        candidates.extend(ov_cands)

        # Check NASA ONLY IF Space/Science and query contains space entity
        is_space_query = any(any(kw in q.lower() for kw in SPACE_KEYWORDS) for q in clean_queries)
        if niche == "space_science" and is_space_query:
            providers_called.append("nasa")
            n_cands = []
            for q in clean_queries[:2]:
                cands = self._fetch_nasa_media(q)
                if cands:
                    n_cands.extend(cands)
            candidate_counts["nasa"] = len(n_cands)
            candidates.extend(n_cands)
        else:
            logger.debug(f"NASA provider strictly bypassed for non-space query/niche: '{niche}'")

        # 2. Score candidates with VisualRelevanceScorer
        scored_candidates: list[tuple[float, CandidateVisual]] = []
        for cand in candidates:
            if cand.asset_id in self.used_asset_ids:
                continue
            score = self.scorer.score_candidate(cand, main_subject, action_or_state, clean_queries, niche)
            if self.scorer.is_acceptable(score):
                scored_candidates.append((score, cand))

        # Sort by score descending
        scored_candidates.sort(key=lambda x: x[0], reverse=True)
        best_score = scored_candidates[0][0] if scored_candidates else 0.0

        diagnostic_info = {
            "sentence_index": sentence_index,
            "queries_tried": clean_queries,
            "providers_called": providers_called,
            "candidate_counts": candidate_counts,
            "candidates_evaluated": len(candidates),
            "best_score": round(best_score, 1),
            "selected_provider": scored_candidates[0][1].provider if scored_candidates else "designed_card",
            "is_fallback_card": not bool(scored_candidates),
        }

        # 3. If acceptable candidate found, download and assemble
        if scored_candidates:
            best_score, best_cand = scored_candidates[0]
            logger.info(
                f"Sentence {sentence_index} matched '{best_cand.title[:36]}' from [cyan]{best_cand.provider}[/cyan] "
                f"(Score: {best_score:.1f}/100 | Candidates: {len(candidates)} across {providers_called})"
            )
            asset = self._materialize_candidate(best_cand, best_score, duration, dest_video_path)
            if asset:
                self.used_asset_ids.add(best_cand.asset_id)
                asset.diagnostic_info = diagnostic_info
                if on_screen_label:
                    self._apply_on_screen_label(dest_video_path, on_screen_label)
                return asset

        # 4. Fallback ladder: Designed Explainer Card with Ken Burns motion
        logger.warning(
            f"No candidate met relevance threshold for sentence {sentence_index} ('{main_subject}'). "
            f"Queries tried: {clean_queries} | Evaluated {len(candidates)} candidates. Generating designed explainer card."
        )
        card_asset = self._generate_explainer_card(
            sentence_index, main_subject, action_or_state, duration, dest_video_path, on_screen_label
        )
        card_asset.diagnostic_info = diagnostic_info
        return card_asset

    def get_scene_visual(
        self,
        scene_index: int,
        query: str,
        duration: float,
        dest_video_path: Path,
        key_stat: str | None = None,
        niche: str = "ai_tech",
    ) -> VisualAsset:
        """Backward-compatible wrapper for scene views."""
        return self.get_sentence_visual(
            sentence_index=scene_index,
            main_subject=query,
            action_or_state="active motion",
            queries=[query],
            duration=duration,
            dest_video_path=dest_video_path,
            niche=niche,
            on_screen_label=key_stat,
        )

    def _clean_queries(self, queries: list[str], main_subject: str, niche: str = "ai_tech") -> list[str]:
        cleaned = []
        for q in queries:
            c = re.sub(r"[^\w\s]", "", q).strip()
            if is_valid_visual_query(c) and c not in cleaned:
                cleaned.append(c)
        if main_subject and is_valid_visual_query(main_subject) and main_subject not in cleaned:
            cleaned.append(re.sub(r"[^\w\s]", "", main_subject).strip())
        if not cleaned:
            cleaned = generate_concrete_queries(main_subject, main_subject, niche=niche)
        return cleaned

    def _materialize_candidate(
        self,
        candidate: CandidateVisual,
        score: float,
        duration: float,
        dest_path: Path,
    ) -> VisualAsset | None:
        try:
            ext = ".mp4" if candidate.media_type == "video" else ".jpg"
            cache_file = self._download_to_cache(candidate.download_url, ext)
            if candidate.media_type == "video":
                self._transcode_to_916(cache_file, dest_path, duration)
            else:
                self._apply_ken_burns(cache_file, dest_path, duration)

            preview_file = dest_path.with_name(f"{dest_path.stem}_prev.jpg")
            self._extract_preview(dest_path, preview_file)

            return VisualAsset(
                file_path=dest_path,
                provider=candidate.provider,
                asset_id=candidate.asset_id,
                creator_name=candidate.creator_name,
                creator_url=candidate.creator_url,
                license_name=candidate.license_name,
                asset_url=candidate.asset_url,
                relevance_score=score,
                preview_path=str(preview_file),
            )
        except Exception as e:
            logger.warning(f"Failed to materialize candidate '{candidate.asset_id}': {e}")
            return None

    def _search_pexels_videos(self, query: str) -> list[CandidateVisual]:
        headers = {"Authorization": self.pexels_key}
        params = {"query": query, "orientation": "portrait", "per_page": 5}
        results = []
        try:
            res = requests.get("https://api.pexels.com/videos/search", headers=headers, params=params, timeout=5)
            if res.status_code == 200:
                for v in res.json().get("videos", []):
                    files = sorted(v.get("video_files", []), key=lambda x: x.get("width", 0), reverse=True)
                    if files and files[0].get("link"):
                        results.append(
                            CandidateVisual(
                                provider="pexels",
                                asset_id=f"pexels_{v.get('id')}",
                                title=f"Pexels Video: {query}",
                                description=f"Stock video uploaded by {v.get('user', {}).get('name')}",
                                tags=[query],
                                preview_url=v.get("image", ""),
                                download_url=files[0]["link"],
                                media_type="video",
                                creator_name=v.get("user", {}).get("name", "Pexels Creator"),
                                creator_url=v.get("user", {}).get("url", "https://pexels.com"),
                                license_name="Pexels License (Free to use)",
                                asset_url=v.get("url", ""),
                            )
                        )
        except Exception:
            pass
        return results

    def _search_pixabay_videos(self, query: str) -> list[CandidateVisual]:
        params = {"key": self.pixabay_key, "q": query, "video_type": "all", "per_page": 5}
        results = []
        try:
            res = requests.get("https://pixabay.com/api/videos/", params=params, timeout=5)
            if res.status_code == 200:
                for hit in res.json().get("hits", []):
                    videos = hit.get("videos", {})
                    v_info = videos.get("large") or videos.get("medium") or videos.get("small")
                    if v_info and v_info.get("url"):
                        results.append(
                            CandidateVisual(
                                provider="pixabay",
                                asset_id=f"pixabay_{hit.get('id')}",
                                title=hit.get("tags", f"Pixabay Video: {query}"),
                                description=f"Pixabay video by {hit.get('user')}",
                                tags=[t.strip() for t in hit.get("tags", "").split(",")],
                                preview_url=hit.get("userImageURL", ""),
                                download_url=v_info["url"],
                                media_type="video",
                                creator_name=hit.get("user", "Pixabay Creator"),
                                creator_url=f"https://pixabay.com/users/{hit.get('user')}-{hit.get('user_id')}/",
                                license_name="Pixabay Content License",
                                asset_url=hit.get("pageURL", ""),
                            )
                        )
        except Exception:
            pass
        return results

    def _search_wikimedia_commons(self, query: str) -> list[CandidateVisual]:
        url = "https://commons.wikimedia.org/w/api.php"
        params = {
            "action": "query",
            "generator": "search",
            "gsrsearch": query,
            "gsrnamespace": "6",
            "gsrlimit": 6,
            "prop": "imageinfo",
            "iiprop": "url|extmetadata|size",
            "format": "json",
        }
        headers = {"User-Agent": "NovaStudio/4.0 (contact: support@novastudio.ai)"}
        results = []
        try:
            res = requests.get(url, params=params, headers=headers, timeout=(3.0, 4.0))
            if res.status_code == 200:
                pages = res.json().get("query", {}).get("pages", {})
                for page in pages.values():
                    ii_list = page.get("imageinfo", [])
                    if not ii_list:
                        continue
                    ii = ii_list[0]
                    img_url = ii.get("url")
                    if not img_url:
                        continue
                    # Exclude non-standard raster formats (e.g. PDF, TIF, DJVU, SVG, WebM)
                    url_lower = img_url.lower()
                    if any(
                        bad_ext in url_lower
                        for bad_ext in [".pdf", ".djvu", ".tif", ".tiff", ".svg", ".webm", ".ogg", ".ogv"]
                    ):
                        continue
                    # Exclude tiny thumbnails
                    width = ii.get("width", 0)
                    height = ii.get("height", 0)
                    if width > 0 and height > 0 and (width < 400 or height < 400):
                        continue
                    meta = ii.get("extmetadata", {})
                    desc = meta.get("ImageDescription", {}).get("value", "")
                    clean_desc = re.sub(r"<[^>]+>", "", desc)[:150]
                    artist = meta.get("Artist", {}).get("value", "Wikimedia Contributor")
                    clean_artist = re.sub(r"<[^>]+>", "", artist)
                    license_short = meta.get("LicenseShortName", {}).get("value", "CC / Public Domain")
                    title = page.get("title", f"Wikimedia Image: {query}").replace("File:", "")
                    results.append(
                        CandidateVisual(
                            provider="wikimedia",
                            asset_id=f"wiki_{page.get('pageid')}",
                            title=title,
                            description=clean_desc,
                            tags=[query],
                            preview_url=img_url,
                            download_url=img_url,
                            media_type="image",
                            creator_name=clean_artist,
                            creator_url="https://commons.wikimedia.org",
                            license_name=license_short,
                            asset_url=ii.get("descriptionurl", img_url),
                        )
                    )
        except Exception as e:
            logger.debug(f"Wikimedia search failed for '{query}': {e}")
        return results

    def _search_openverse(self, query: str) -> list[CandidateVisual]:
        url = "https://api.openverse.org/v1/images/"
        params = {"q": query, "page_size": 4, "license_type": "commercial"}
        headers = {"User-Agent": "NovaStudio/4.0 (contact: support@novastudio.ai)"}
        results = []
        try:
            res = requests.get(url, params=params, headers=headers, timeout=(2.0, 3.0))
            if res.status_code == 200:
                for hit in res.json().get("results", []):
                    img_url = hit.get("url")
                    if not img_url:
                        continue
                    results.append(
                        CandidateVisual(
                            provider="openverse",
                            asset_id=f"openverse_{hit.get('id')}",
                            title=hit.get("title", f"Openverse Image: {query}"),
                            description=hit.get("title", ""),
                            tags=[t.get("name", "") for t in hit.get("tags", [])],
                            preview_url=hit.get("thumbnail", img_url),
                            download_url=img_url,
                            media_type="image",
                            creator_name=hit.get("creator", "Openverse Contributor"),
                            creator_url=hit.get("creator_url", "https://openverse.org"),
                            license_name=f"CC {hit.get('license', 'BY')}".upper(),
                            asset_url=hit.get("foreign_landing_url", img_url),
                        )
                    )
        except Exception as e:
            logger.debug(f"Openverse search failed for '{query}': {e}")
        return results

    def _search_nasa_media(self, query: str) -> list[CandidateVisual]:
        url = "https://images-api.nasa.gov/search"
        params = {"q": query, "media_type": "image", "page_size": 5}
        results = []
        try:
            res = requests.get(url, params=params, timeout=(3.0, 4.0))
            if res.status_code == 200:
                items = res.json().get("collection", {}).get("items", [])
                for it in items:
                    data = it.get("data", [{}])[0]
                    nasa_id = data.get("nasa_id", "")
                    title = data.get("title", f"NASA Space Image: {query}")
                    desc = data.get("description", "")[:200]
                    keywords = data.get("keywords", [])
                    links = it.get("links", [{}])
                    thumb = links[0].get("href", "") if links else ""
                    if not thumb:
                        continue
                    orig_url = thumb.replace("~thumb", "~orig")
                    results.append(
                        CandidateVisual(
                            provider="nasa",
                            asset_id=f"nasa_{nasa_id}",
                            title=title,
                            description=desc,
                            tags=keywords,
                            preview_url=thumb,
                            download_url=orig_url,
                            media_type="image",
                            creator_name="NASA / JPL",
                            creator_url="https://images.nasa.gov",
                            license_name="Public Domain (NASA)",
                            asset_url=f"https://images.nasa.gov/details-{nasa_id}",
                        )
                    )
        except Exception as e:
            logger.debug(f"NASA search failed for '{query}': {e}")
        return results

    def diag_visuals(self, query: str, niche: str = "ai_tech") -> dict[str, Any]:
        """Runs live diagnosis of visual query across all providers and prints a Rich formatted table."""
        from rich.console import Console
        from rich.table import Table

        console = Console()
        console.print(
            f"\n[bold cyan]🔍 Diagnosing Visual Footage Pipeline for: '[bold white]{query}[/bold white]' (Niche: {niche})[/bold cyan]\n"
        )

        valid_q = is_valid_visual_query(query)
        if not valid_q:
            console.print(
                f"[bold red]❌ Query Validation Failed:[/bold red] '{query}' is rejected as a placeholder, stopword, or abstract term."
            )
            concrete = generate_concrete_queries(query, query, niche=niche)
            console.print(f"[bold green]✓ Recommended Concrete Replacements:[/bold green] {concrete}\n")

        results: dict[str, Any] = {}
        providers_to_test = [
            ("Pexels Video", "pexels", bool(self.pexels_key), lambda: self._search_pexels_videos(query)),
            ("Pixabay Video", "pixabay", bool(self.pixabay_key), lambda: self._search_pixabay_videos(query)),
            ("Wikimedia Commons (Keyless)", "wikimedia", True, lambda: self._search_wikimedia_commons(query)),
            ("Openverse (Keyless)", "openverse", True, lambda: self._search_openverse(query)),
            ("NASA Image Library (Keyless)", "nasa", niche == "space_science", lambda: self._search_nasa_media(query)),
        ]

        table = Table(title=f"Visual Provider Search Diagnostic: '{query}'", show_lines=True)
        table.add_column("Provider", style="bold white", width=28)
        table.add_column("Status / Config", justify="center", width=16)
        table.add_column("Candidates", justify="right", width=12)
        table.add_column("Top Candidate Title", style="dim", width=36)
        table.add_column("Relevance Score", justify="center", width=16)
        table.add_column("Threshold Gate", justify="center", width=14)

        for display_name, prov_id, enabled, fetch_fn in providers_to_test:
            if not enabled:
                reason = "No API key" if prov_id in ["pexels", "pixabay"] else f"Bypassed (niche={niche})"
                table.add_row(display_name, "[yellow]BYPASSED[/yellow]", "0", reason, "-", "[yellow]SKIP[/yellow]")
                results[prov_id] = {"enabled": False, "count": 0, "status": reason}
                continue

            try:
                cands = fetch_fn()
                count = len(cands)
                if count == 0:
                    table.add_row(
                        display_name,
                        "[bold red]EMPTY[/bold red]",
                        "0",
                        "Zero results returned",
                        "0.0/100",
                        "[red]FAIL[/red]",
                    )
                    results[prov_id] = {"enabled": True, "count": 0, "status": "zero_results"}
                else:
                    top_cand = cands[0]
                    score = self.scorer.score_candidate(top_cand, query, "active motion", [query], niche)
                    passes = self.scorer.is_acceptable(score)
                    gate_badge = "[bold green]PASS[/bold green]" if passes else "[bold red]REJECTED[/bold red]"
                    table.add_row(
                        display_name,
                        "[bold green]OK[/bold green]",
                        str(count),
                        top_cand.title[:34],
                        f"{score:.1f}/100",
                        gate_badge,
                    )
                    results[prov_id] = {
                        "enabled": True,
                        "count": count,
                        "top_title": top_cand.title,
                        "top_score": score,
                        "passed_gate": passes,
                    }
            except Exception as e:
                table.add_row(
                    display_name, "[bold red]ERROR[/bold red]", "0", str(e)[:34], "0.0/100", "[red]ERROR[/red]"
                )
                results[prov_id] = {"enabled": True, "count": 0, "error": str(e)}

        console.print(table)
        return results

    def _search_nasa_media(self, query: str) -> list[CandidateVisual]:
        url = "https://images-api.nasa.gov/search"
        params = {"q": query, "media_type": "image", "page_size": 5}
        results = []
        try:
            res = requests.get(url, params=params, timeout=5)
            if res.status_code == 200:
                items = res.json().get("collection", {}).get("items", [])
                for it in items:
                    data = it.get("data", [{}])[0]
                    nasa_id = data.get("nasa_id", "")
                    title = data.get("title", f"NASA Space Image: {query}")
                    desc = data.get("description", "")[:200]
                    keywords = data.get("keywords", [])
                    links = it.get("links", [{}])
                    thumb = links[0].get("href", "") if links else ""
                    if not thumb:
                        continue
                    orig_url = thumb.replace("~thumb", "~orig")
                    results.append(
                        CandidateVisual(
                            provider="nasa",
                            asset_id=f"nasa_{nasa_id}",
                            title=title,
                            description=desc,
                            tags=keywords,
                            preview_url=thumb,
                            download_url=orig_url,
                            media_type="image",
                            creator_name="NASA / JPL",
                            creator_url="https://images.nasa.gov",
                            license_name="Public Domain (NASA)",
                            asset_url=f"https://images.nasa.gov/details-{nasa_id}",
                        )
                    )
        except Exception:
            pass
        return results

    def _fetch_nasa_media(self, query: str) -> list[CandidateVisual]:
        return self._search_nasa_media(query)

    def _fetch_wikimedia_commons(self, query: str) -> list[CandidateVisual]:
        return self._search_wikimedia_commons(query)

    def _fetch_openverse_media(self, query: str) -> list[CandidateVisual]:
        return self._search_openverse(query)

    def _download_to_cache(self, url: str, ext: str = ".jpg") -> Path:
        if os.path.exists(url) or url.startswith("/"):
            local_p = Path(url)
            if local_p.exists() and local_p.is_file():
                return local_p
        clean_ext = ".mp4" if "mp4" in ext.lower() else ".jpg"
        h = hashlib.sha256(url.encode()).hexdigest()[:16]
        cache_file = self.cache_dir / f"asset_{h}{clean_ext}"
        if cache_file.exists() and cache_file.stat().st_size > 1024:
            return cache_file
        headers = {
            "User-Agent": "NovaAutopilot/8.0 (https://github.com/nova-autopilot; contact: admin@novastudio.ai)",
            "Accept": "*/*",
        }
        max_bytes = 25 * 1024 * 1024  # 25 MB max to prevent long network pauses
        with requests.get(url, headers=headers, stream=True, timeout=8) as r:
            r.raise_for_status()
            c_len = r.headers.get("content-length")
            if c_len and int(c_len) > max_bytes:
                raise ValueError(f"Asset exceeds maximum 25MB download limit ({int(c_len)/(1024*1024):.1f}MB)")

            bytes_written = 0
            with open(cache_file, "wb") as f:
                for chunk in r.iter_content(chunk_size=32768):
                    bytes_written += len(chunk)
                    if bytes_written > max_bytes:
                        raise ValueError(f"Asset exceeded 25MB stream cap ({bytes_written/(1024*1024):.1f}MB)")
                    f.write(chunk)

        # Validate that the downloaded image is actually a valid decodeable image (not PDF, HTML, or corrupt bitstream)
        if clean_ext == ".jpg":
            try:
                with Image.open(cache_file) as im:
                    rgb = im.convert("RGB")
                    temp_clean = cache_file.with_suffix(".tmp.jpg")
                    rgb.save(temp_clean, "JPEG", quality=95)
                temp_clean.replace(cache_file)
            except Exception as e:
                if cache_file.exists():
                    cache_file.unlink()
                raise ValueError(f"Downloaded asset from {url} is not a valid decodeable image: {e}")
        elif clean_ext == ".mp4":
            dur = get_media_duration(cache_file)
            if dur <= 0.1:
                if cache_file.exists():
                    cache_file.unlink()
                raise ValueError(f"Downloaded video from {url} is corrupt or 0 duration.")

        return cache_file

    def _transcode_to_916(self, input_video: Path, output_video: Path, duration: float):
        fit_video_shot(input_video, output_video, duration, fps=30)

    def _apply_ken_burns(self, image_path: Path, output_video: Path, duration: float):
        fit_image_shot(image_path, output_video, duration, fps=self.settings.video.fps)

    def _extract_preview(self, video_path: Path, out_thumb: Path):
        cmd = ["ffmpeg", "-y", "-ss", "0.5", "-i", str(video_path.resolve()), "-vframes", "1", str(out_thumb.resolve())]
        subprocess.run(cmd, capture_output=True)

    def _apply_illustrative_badge(self, video_path: Path) -> None:
        """Overlays a clean, subtle 'ILLUSTRATIVE FOOTAGE' badge on the top-left corner."""
        badge_png = video_path.with_name(f"{video_path.stem}_ill_badge.png")
        temp_out = video_path.with_name(f"{video_path.stem}_ill_badged.mp4")

        img = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        pill_box = [60, 120, 420, 175]
        draw.rounded_rectangle(pill_box, radius=12, fill=(10, 15, 25, 190), outline=(200, 220, 240, 120), width=1)

        font = ImageFont.load_default()
        try:
            font_file = self.settings.resolve_path(self.settings.video.subtitles.font_file)
            if font_file.exists():
                font = ImageFont.truetype(str(font_file), 24)
        except Exception:
            pass

        draw.text((80, 136), "ILLUSTRATIVE FOOTAGE", font=font, fill=(220, 230, 245, 220))
        img.save(badge_png)

        cmd = [
            "ffmpeg",
            "-y",
            "-i", str(video_path.resolve()),
            "-i", str(badge_png.resolve()),
            "-filter_complex", "[0:v][1:v]overlay=0:0[outv]",
            "-map", "[outv]",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-an", str(temp_out.resolve()),
        ]
        res = subprocess.run(cmd, capture_output=True)
        if res.returncode == 0:
            temp_out.replace(video_path)
        if badge_png.exists():
            badge_png.unlink()

    def _apply_on_screen_label(self, video_path: Path, label: str):
        if not label or len(label) < 2:
            return
        badge_png = video_path.with_name(f"{video_path.stem}_label.png")
        temp_out = video_path.with_name(f"{video_path.stem}_labeled.mp4")

        img = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        font = ImageFont.load_default()
        try:
            font_file = self.settings.resolve_path(self.settings.video.subtitles.font_file)
            if font_file.exists():
                font = ImageFont.truetype(str(font_file), 52)
        except Exception:
            pass

        text = label.upper()
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        card_w = text_w + 60
        card_h = text_h + 30
        card_x = (1080 - card_w) // 2
        card_y = 480

        draw.rounded_rectangle(
            (card_x, card_y, card_x + card_w, card_y + card_h),
            radius=16,
            fill=(20, 20, 30, 210),
            outline=(255, 215, 0, 220),
            width=3,
        )
        draw.text((card_x + 30, card_y + 12), text, font=font, fill=(255, 255, 255, 255))
        img.save(badge_png)

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path.resolve()),
            "-i",
            str(badge_png.resolve()),
            "-filter_complex",
            "[0:v][1:v]overlay=0:0[outv]",
            "-map",
            "[outv]",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(temp_out.resolve()),
        ]
        res = subprocess.run(cmd, capture_output=True)
        if res.returncode == 0:
            temp_out.replace(video_path)
        if badge_png.exists():
            badge_png.unlink()

    def _generate_fallback_card(
        self,
        index: int,
        subject: str,
        action: str,
        duration: float,
        dest_video_path: Path,
        label: str | None = None,
        shot_index: int = 0,
    ) -> VisualAsset:
        """Generates premium typography title card with blurred image background and subtle Ken Burns drift."""
        dest_video_path.parent.mkdir(parents=True, exist_ok=True)

        bg_image = None
        cached_images = list(self.cache_dir.glob("*.jpg")) + list(self.cache_dir.glob("*.jpeg"))
        if cached_images:
            pick_file = cached_images[(index + shot_index) % len(cached_images)]
            try:
                with Image.open(pick_file) as c_img:
                    bg_image = (
                        c_img.convert("RGB")
                        .resize((1080, 1920), Image.Resampling.LANCZOS)
                        .filter(ImageFilter.GaussianBlur(radius=28))
                    )
            except Exception:
                bg_image = None

        if bg_image is None:
            bg_image = Image.new("RGB", (1080, 1920), (12, 16, 26))
            d_bg = ImageDraw.Draw(bg_image)
            for y in range(1920):
                factor = y / 1920.0
                r = int(10 + factor * 8)
                g = int(14 + factor * 12)
                b = int(22 + factor * 20)
                d_bg.line([(0, y), (1080, y)], fill=(r, g, b))

        vignette = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
        v_draw = ImageDraw.Draw(vignette)
        v_draw.rectangle([0, 0, 1080, 1920], fill=(5, 8, 15, 140))
        v_draw.rounded_rectangle([60, 680, 1020, 1240], radius=24, fill=(10, 15, 25, 200))
        v_draw.line([(100, 680), (980, 680)], fill=(0, 210, 255, 230), width=4)
        v_draw.line([(100, 1240), (980, 1240)], fill=(0, 210, 255, 180), width=2)

        bg_rgba = bg_image.convert("RGBA")
        composite = Image.alpha_composite(bg_rgba, vignette).convert("RGB")
        draw = ImageDraw.Draw(composite)

        font_display = ImageFont.load_default()
        font_sub = ImageFont.load_default()
        try:
            font_file = self.settings.resolve_path(self.settings.video.subtitles.font_file)
            if font_file.exists():
                font_display = ImageFont.truetype(str(font_file), 64)
                font_sub = ImageFont.truetype(str(font_file), 36)
        except Exception:
            pass

        display_text = (label or subject).upper()
        if len(display_text) > 22:
            words = display_text.split()
            mid = len(words) // 2
            display_lines = [" ".join(words[:mid]), " ".join(words[mid:])]
        else:
            display_lines = [display_text]

        cur_y = 820 - (len(display_lines) - 1) * 40
        for line in display_lines:
            bbox = draw.textbbox((0, 0), line, font=font_display)
            tw = bbox[2] - bbox[0]
            tx = (1080 - tw) // 2
            draw.text(
                (tx + 3, cur_y + 3), line, font=font_display, fill=(0, 0, 0), stroke_width=4, stroke_fill=(0, 0, 0)
            )
            draw.text((tx, cur_y), line, font=font_display, fill=(255, 255, 255), stroke_width=2, stroke_fill=(0, 0, 0))
            cur_y += 75

        sub_text = action.capitalize() if action and action != "active motion" else "KEY INSIGHT"
        bbox_s = draw.textbbox((0, 0), sub_text, font=font_sub)
        tws = bbox_s[2] - bbox_s[0]
        txs = (1080 - tws) // 2
        draw.text((txs, 1120), sub_text, font=font_sub, fill=(0, 210, 255), stroke_width=2, stroke_fill=(0, 0, 0))

        temp_png = dest_video_path.with_suffix(".card.png")
        composite.save(temp_png)

        directions = ["zoom_in", "zoom_out", "pan_right", "pan_left"]
        direction = directions[shot_index % len(directions)]
        fit_image_shot(temp_png, dest_video_path, duration, direction=direction)
        if temp_png.exists():
            temp_png.unlink()

        preview_file = dest_video_path.with_name(f"{dest_video_path.stem}_prev.jpg")
        self._extract_preview(dest_video_path, preview_file)

        return VisualAsset(
            file_path=dest_video_path,
            provider="designed_card",
            asset_id=f"card_{index}_{shot_index}",
            creator_name="Nova Studio Procedural",
            creator_url="",
            license_name="Generated Explainer Card",
            asset_url="",
            relevance_score=50.0,
            preview_path=str(preview_file),
            is_fallback_card=True,
        )

    def _generate_explainer_card(
        self,
        index: int,
        subject: str,
        action: str,
        duration: float,
        dest_video_path: Path,
        label: str | None = None,
    ) -> VisualAsset:
        """Alias for backward compatibility."""
        return self._generate_fallback_card(index, subject, action, duration, dest_video_path, label=label)

    def get_candidate_pool(
        self,
        queries: list[str],
        niche: str = "ai_tech",
        main_subject: str = "",
    ) -> list[CandidateVisual]:
        """Retrieves a diverse pool of candidate visuals across providers for the given queries and niche."""
        clean_queries = self._clean_queries(queries, main_subject, niche=niche)
        all_cands: list[CandidateVisual] = []
        seen_ids: set[str] = set()

        for q in clean_queries:
            # 1. Search local library first (instant, offline)
            try:
                for c in self.library_searcher.search(query=q, niche=niche, limit=3):
                    if c.asset_id not in seen_ids:
                        seen_ids.add(c.asset_id)
                        all_cands.append(c)
            except Exception as le:
                logger.debug(f"Library search error: {le}")

            # 2. Query multi-provider registry (parallel dispatch)
            try:
                for c in self.registry.search_all(query=q, niche=niche, media_type="all", total_limit=8):
                    if c.asset_id not in seen_ids:
                        seen_ids.add(c.asset_id)
                        all_cands.append(c)
            except Exception as re:
                logger.debug(f"Registry multi-provider search error: {re}")

            # 3. Direct provider search fallbacks if pool is small
            if len(all_cands) < 3 and self.pixabay_key:
                for c in self._search_pixabay_videos(q):
                    if c.asset_id not in seen_ids:
                        seen_ids.add(c.asset_id)
                        all_cands.append(c)

        scored = []
        for c in all_cands:
            score = self.scorer.score_candidate(c, main_subject, "active motion", clean_queries, niche)
            if self.scorer.is_acceptable(score):
                scored.append((score, c))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in scored]

    def _materialize_stock_candidate(
        self,
        cand: CandidateVisual,
        score: float,
        is_illustrative: bool,
        shot: ShotPlan,
        dest_shot_path: Path,
        direction: str,
        used_set: set[str],
    ) -> VisualAsset | None:
        try:
            ext = ".mp4" if cand.media_type == "video" else ".jpg"
            cache_file = self._download_to_cache(cand.download_url, ext)

            if cand.media_type == "video":
                fit_video_shot(cache_file, dest_shot_path, shot.duration, fps=30)
                shot.fit_method = "video_fit"
            else:
                fit_image_shot(cache_file, dest_shot_path, shot.duration, fps=30, direction=direction)
                shot.fit_method = f"ken_burns_{direction}"

            if is_illustrative:
                self._apply_illustrative_badge(dest_shot_path)
                shot.on_screen_label = "ILLUSTRATIVE FOOTAGE"
            elif shot.on_screen_label:
                self._apply_on_screen_label(dest_shot_path, shot.on_screen_label)

            preview_file = dest_shot_path.with_name(f"{dest_shot_path.stem}_prev.jpg")
            self._extract_preview(dest_shot_path, preview_file)

            used_set.add(cand.asset_id)
            shot.chosen_asset_id = cand.asset_id
            shot.provider = cand.provider
            shot.media_type = cand.media_type
            shot.asset_file = str(cache_file)
            shot.normalized_shot_file = str(dest_shot_path)
            shot.relevance_score = score
            shot.is_fallback_card = False

            # Index into local library catalog for future offline reuse
            try:
                from nova.library.catalog import MediaLibraryCatalog
                MediaLibraryCatalog().add_asset(cand, cache_file, niche=getattr(shot, "niche", "general"))
            except Exception:
                pass

            return VisualAsset(
                file_path=dest_shot_path,
                provider=cand.provider,
                asset_id=cand.asset_id,
                creator_name=getattr(cand, "creator_name", ""),
                creator_url=getattr(cand, "creator_url", ""),
                license_name=getattr(cand, "license_name", ""),
                asset_url=getattr(cand, "asset_url", ""),
                relevance_score=shot.relevance_score,
                preview_path=str(preview_file),
                is_fallback_card=False,
                license_proof=getattr(cand, "license_proof", None),
            )
        except Exception as e:
            logger.warning(f"Failed to materialize candidate '{cand.asset_id}': {e}")
            used_set.add(cand.asset_id)
            return None

    def materialize_shot(
        self,
        shot: ShotPlan,
        dest_shot_path: Path,
        candidate_pool: list[CandidateVisual],
        used_asset_ids: set[str] | None = None,
    ) -> VisualAsset:
        """Materializes a single frame-accurate normalized shot (1080x1920, 30fps CFR) using Phase 3 priority ladder."""
        dest_shot_path.parent.mkdir(parents=True, exist_ok=True)
        used_set = used_asset_ids if used_asset_ids is not None else self.used_asset_ids

        # 1. Extract or construct semantic Beat
        beat_data = shot.metadata.get("beat") if getattr(shot, "metadata", None) else None
        if beat_data:
            beat = Beat.from_dict(beat_data)
        else:
            entities = BeatPlanner.extract_entities(shot.sentence_text)
            b_type = BeatPlanner.classify_beat_type(shot.sentence_text, entities)
            sens, reason = BeatPlanner.check_sensitivity(shot.sentence_text, entities)
            beat = Beat(
                beat_id=f"B{shot.shot_index + 1}",
                beat_index=shot.shot_index,
                sentence_id=shot.sentence_id,
                sentence_index=shot.sentence_index,
                spoken_text=shot.sentence_text,
                caption_text=shot.sentence_text,
                start_time=shot.start_time,
                end_time=shot.end_time,
                duration=shot.duration,
                visual_intent=shot.query,
                entities=entities,
                beat_type=b_type,
                sensitivity=sens,
                sensitivity_reason=reason,
                search_queries=[shot.query],
                is_specific_event=bool(sens or "20" in shot.sentence_text),
            )

        niche = shot.metadata.get("niche", "ai_tech")
        tier = shot.metadata.get("tier", "tier_a")
        rec_route = getattr(beat, "recommended_visual_route", "") or shot.metadata.get("recommended_visual_route", "")
        force_animation = shot.metadata.get("force_animation", False) or getattr(shot, "force_animation", False)
        direction = ["zoom_in", "zoom_out", "pan_right", "pan_left"][shot.shot_index % 4]

        # Explicit force animation override (from review UI or flag)
        if force_animation:
            logger.info(f"Shot #{shot.shot_index + 1} has force_animation enabled. Rendering procedural animation.")
            render_data_card_for_beat(beat, duration=shot.duration, out_path=dest_shot_path, fps=30)
            preview_file = dest_shot_path.with_name(f"{dest_shot_path.stem}_prev.jpg")
            shot.chosen_asset_id = f"motion_{beat.beat_id}"
            shot.provider = "procedural_motion"
            shot.media_type = "procedural_card"
            shot.fit_method = f"procedural_{beat.beat_type.value}"
            shot.asset_file = str(dest_shot_path)
            shot.normalized_shot_file = str(dest_shot_path)
            shot.relevance_score = 95.0
            shot.is_fallback_card = False
            return VisualAsset(
                file_path=dest_shot_path,
                provider="procedural_motion",
                asset_id=f"motion_{beat.beat_id}",
                creator_name="Nova Procedural Engine",
                creator_url="",
                license_name="Generated Motion Asset",
                asset_url="",
                relevance_score=95.0,
                preview_path=str(preview_file),
                is_fallback_card=False,
            )

        # 2. Score candidate pool against RelevanceGate
        gate = RelevanceGate(min_threshold=float(getattr(getattr(self.settings, "visual", None), "min_match_score", 55.0)))
        passing_candidates: list[tuple[float, bool, CandidateVisual]] = []

        for cand in candidate_pool:
            if cand.asset_id in used_set:
                continue
            from nova.providers.base import MediaCandidate
            m_cand = cand if isinstance(cand, MediaCandidate) else MediaCandidate(
                provider=cand.provider,
                asset_id=cand.asset_id,
                title=cand.title,
                description=cand.description,
                tags=cand.tags,
                preview_url=cand.preview_url,
                download_url=cand.download_url,
                media_type=cand.media_type,
                author=getattr(cand, "creator_name", ""),
                creator_url=getattr(cand, "creator_url", ""),
                landing_page_url=getattr(cand, "asset_url", ""),
                license_proof=getattr(cand, "license_proof", None),
            )
            res = gate.evaluate_candidate(m_cand, beat)
            if res.passed:
                passing_candidates.append((res.total_score, res.is_illustrative, cand))

        passing_candidates.sort(key=lambda x: x[0], reverse=True)

        # PHASE 3 ROUTE A: Official or primary source asset (NASA, government/filing)
        if rec_route == "official_document" or (beat.is_specific_event and niche == "space_science"):
            official_cands = [c for c in passing_candidates if c[2].provider in ("nasa", "wikimedia") and c[0] >= 65.0]
            if official_cands:
                score, is_illustrative, cand = official_cands[0]
                asset = self._materialize_stock_candidate(cand, score, is_illustrative, shot, dest_shot_path, direction, used_set)
                if asset:
                    return asset

        # PHASE 3 ROUTE B: Free licensed stock video or image from existing providers
        if rec_route in ("stock_footage", "stock_image", ""):
            for score, is_illustrative, cand in passing_candidates:
                asset = self._materialize_stock_candidate(cand, score, is_illustrative, shot, dest_shot_path, direction, used_set)
                if asset:
                    return asset

        # PHASE 3 ROUTE C: Data and diagram animation rendered by our own templates
        # (for numbers/stats, comparisons, timelines, process flows, or node-and-arrow diagrams)
        if rec_route in ("data_animation", "diagram_animation") or beat.beat_type in (
            BeatType.NUMBER_OR_STAT,
            BeatType.COMPARISON,
            BeatType.TIMELINE,
        ):
            logger.info(
                f"[Route C] Rendering procedural data/diagram animation for beat {beat.beat_id} ({beat.beat_type.value})."
            )
            render_data_card_for_beat(beat, duration=shot.duration, out_path=dest_shot_path, fps=30)
            preview_file = dest_shot_path.with_name(f"{dest_shot_path.stem}_prev.jpg")
            shot.chosen_asset_id = f"motion_{beat.beat_id}"
            shot.provider = "procedural_motion"
            shot.media_type = "procedural_card"
            shot.fit_method = f"procedural_{beat.beat_type.value}"
            shot.asset_file = str(dest_shot_path)
            shot.normalized_shot_file = str(dest_shot_path)
            shot.relevance_score = 92.0
            shot.is_fallback_card = False
            return VisualAsset(
                file_path=dest_shot_path,
                provider="procedural_motion",
                asset_id=f"motion_{beat.beat_id}",
                creator_name="Nova Procedural Engine",
                creator_url="",
                license_name="Generated Motion Asset",
                asset_url="",
                relevance_score=92.0,
                preview_path=str(preview_file),
                is_fallback_card=False,
            )

        # PHASE 3 ROUTE D: Gemini image generation for beats needing specific illustration
        # Check strict safety: NEVER use AI for Tier B sensitive news, named real people, crime/fraud
        is_sensitive = (tier == "tier_b") or (beat.sensitivity is True) or any(
            w in shot.sentence_text.lower() for w in ["fraud", "charged", "guilty", "indicted", "arrested", "alleged", "prosecutor"]
        )
        ai_allowed = (
            not is_sensitive
            and getattr(self.settings.gemini, "enabled", True)
            and not getattr(self.settings, "no_ai", False)
            and self.gemini_client.is_available()
            and self.gemini_client.tracker.can_spend(0.07, self.gemini_client.daily_budget)
        )

        if ai_allowed:
            try:
                logger.info(f"[Route D] Requesting 2 Gemini image candidates for beat {beat.beat_id} ('{beat.visual_intent[:36]}')...")
                ai_cands = self.gemini_client.generate_image_candidates(
                    prompt=beat.visual_intent, niche=niche, count=2, seed_offset=shot.shot_index
                )
                ai_scored = []
                for cand_path in ai_cands:
                    from nova.providers.base import MediaCandidate
                    m_cand = MediaCandidate(
                        provider="gemini_imagen",
                        asset_id=f"ai_{cand_path.stem}",
                        title=f"AI Illustration: {beat.visual_intent[:40]}",
                        description=beat.visual_intent,
                        tags=[niche, "ai_generated", "illustration"],
                        preview_url=str(cand_path),
                        download_url=str(cand_path),
                        media_type="image",
                        author="Google Gemini",
                        creator_url="https://ai.google.dev",
                        landing_page_url="https://ai.google.dev",
                        license_proof=None,
                    )
                    res = gate.evaluate_candidate(m_cand, beat)
                    if res.passed:
                        ai_scored.append((res.total_score, cand_path))

                if ai_scored:
                    ai_scored.sort(key=lambda x: x[0], reverse=True)
                    best_score, best_img = ai_scored[0]

                    # PHASE 3 ROUTE E: Veo Hero Video (max 1 per video, 4-8s, behind veo_enabled)
                    if (
                        rec_route == "ai_video"
                        and self.gemini_client.veo_enabled
                        and not self.ai_hero_video_generated
                        and 4.0 <= shot.duration <= 8.0
                    ):
                        veo_file = self.gemini_client.generate_veo_hero_video(
                            best_img, prompt=beat.visual_intent, duration_seconds=shot.duration
                        )
                        if veo_file and veo_file.exists():
                            self.ai_hero_video_generated = True
                            fit_video_shot(veo_file, dest_shot_path, shot.duration, fps=30)
                            GeminiClient.apply_ai_illustration_badge(dest_shot_path, dest_shot_path)
                            preview_file = dest_shot_path.with_name(f"{dest_shot_path.stem}_prev.jpg")
                            self._extract_preview(dest_shot_path, preview_file)

                            shot.chosen_asset_id = f"veo_{veo_file.stem}"
                            shot.provider = "gemini_veo"
                            shot.media_type = "video"
                            shot.fit_method = "veo_motion"
                            shot.asset_file = str(veo_file)
                            shot.normalized_shot_file = str(dest_shot_path)
                            shot.relevance_score = best_score
                            shot.is_fallback_card = False
                            shot.on_screen_label = "AI ILLUSTRATION"
                            shot.metadata["is_ai_generated"] = True
                            shot.metadata["needs_synthetic_disclosure"] = True

                            return VisualAsset(
                                file_path=dest_shot_path,
                                provider="gemini_veo",
                                asset_id=f"veo_{veo_file.stem}",
                                creator_name="Google Gemini Veo",
                                creator_url="https://ai.google.dev",
                                license_name="AI-generated",
                                asset_url="https://ai.google.dev",
                                relevance_score=best_score,
                                preview_path=str(preview_file),
                                is_fallback_card=False,
                            )

                    # Animate AI still with Ken Burns drift, particle overlay, and AI illustration badge
                    self.gemini_client.animate_ai_still(
                        best_img, dest_shot_path, duration=shot.duration, fps=30, direction=direction
                    )
                    preview_file = dest_shot_path.with_name(f"{dest_shot_path.stem}_prev.jpg")
                    self._extract_preview(dest_shot_path, preview_file)

                    shot.chosen_asset_id = f"ai_{best_img.stem}"
                    shot.provider = "gemini_imagen"
                    shot.media_type = "image"
                    shot.fit_method = f"ai_animated_{direction}"
                    shot.asset_file = str(best_img)
                    shot.normalized_shot_file = str(dest_shot_path)
                    shot.relevance_score = best_score
                    shot.is_fallback_card = False
                    shot.on_screen_label = "AI ILLUSTRATION"
                    shot.metadata["is_ai_generated"] = True
                    shot.metadata["needs_synthetic_disclosure"] = True

                    return VisualAsset(
                        file_path=dest_shot_path,
                        provider="gemini_imagen",
                        asset_id=f"ai_{best_img.stem}",
                        creator_name="Google Gemini",
                        creator_url="https://ai.google.dev",
                        license_name="AI-generated",
                        asset_url="https://ai.google.dev",
                        relevance_score=best_score,
                        preview_path=str(preview_file),
                        is_fallback_card=False,
                    )
            except Exception as ai_e:
                logger.warning(f"Route D AI generation encountered error ({ai_e}), falling back to procedural animation.")

        # Guaranteed Safe Fallback: Route C Procedural Animation
        logger.info(
            f"[Route C Fallback] Rendering procedural data/diagram animation for beat {beat.beat_id} ({beat.beat_type.value})."
        )
        render_data_card_for_beat(beat, duration=shot.duration, out_path=dest_shot_path, fps=30)
        preview_file = dest_shot_path.with_name(f"{dest_shot_path.stem}_prev.jpg")

        shot.chosen_asset_id = f"motion_{beat.beat_id}"
        shot.provider = "procedural_motion"
        shot.media_type = "procedural_card"
        shot.fit_method = f"procedural_{beat.beat_type.value}"
        shot.asset_file = str(dest_shot_path)
        shot.normalized_shot_file = str(dest_shot_path)
        shot.relevance_score = 92.0
        shot.is_fallback_card = False

        return VisualAsset(
            file_path=dest_shot_path,
            provider="procedural_motion",
            asset_id=f"motion_{beat.beat_id}",
            creator_name="Nova Procedural Engine",
            creator_url="",
            license_name="Generated Motion Asset",
            asset_url="",
            relevance_score=92.0,
            preview_path=str(preview_file),
            is_fallback_card=False,
        )

    def generate_alignment_report(
        self,
        script_id: int,
        sentences: list[dict],
        assets: list[VisualAsset],
        sync_stats: dict,
        output_html_path: Path,
    ) -> Path:
        """Generates comprehensive alignment_report.html showing sentence-visual matching and sync metrics."""
        output_html_path.parent.mkdir(parents=True, exist_ok=True)
        rows_html = []
        for i, (sent, asset) in enumerate(zip(sentences, assets, strict=False)):
            text = sent.get("text", "")
            role = sent.get("role", "")
            duration = sent.get("duration", 0.0)
            score = getattr(asset, "relevance_score", 100.0)
            badge_class = "pass" if score >= 40.0 else "fail"
            prov = asset.provider.upper()
            lic = asset.license_name

            thumb_tag = (
                f"<img src='{asset.preview_path}' width='90' style='border-radius:6px;'>"
                if asset.preview_path
                else "<span>Card</span>"
            )

            rows_html.append(f"""
            <tr>
              <td><strong>S{i + 1}</strong> ({role})</td>
              <td>{text}</td>
              <td>{duration:.2f}s</td>
              <td>{thumb_tag}</td>
              <td><span class='badge {badge_class}'>{score:.1f}/100</span></td>
              <td>{prov}</td>
              <td><small>{lic}</small></td>
            </tr>
            """)

        html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Nova Autopilot - Visual & Subtitle Alignment Report</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f141c; color: #f0f3f6; margin: 40px; }}
    h1 {{ color: #00d2ff; }}
    .stats-card {{ background: #1a2230; padding: 20px; border-radius: 10px; margin-bottom: 24px; display: flex; gap: 30px; }}
    .stat-item {{ font-size: 1.1em; }}
    .stat-val {{ font-weight: bold; color: #00ffcc; font-size: 1.3em; }}
    table {{ width: 100%; border-collapse: collapse; background: #161d28; border-radius: 8px; overflow: hidden; }}
    th, td {{ padding: 14px 18px; text-align: left; border-bottom: 1px solid #232d3d; }}
    th {{ background: #1f293a; color: #9daec2; }}
    .badge {{ padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 0.85em; }}
    .badge.pass {{ background: #1b4731; color: #4ade80; }}
    .badge.fail {{ background: #542222; color: #f87171; }}
  </style>
</head>
<body>
  <h1>🎬 Alignment & Subtitle Synchronization Report</h1>
  <div class="stats-card">
    <div class="stat-item">Script ID: <span class="stat-val">#{script_id}</span></div>
    <div class="stat-item">Median Subtitle Drift: <span class="stat-val">{sync_stats.get("median_drift_ms", 0):.1f} ms</span></div>
    <div class="stat-item">Max Word Drift: <span class="stat-val">{sync_stats.get("max_drift_ms", 0):.1f} ms</span></div>
    <div class="stat-item">Sync Gate: <span class="stat-val">{"PASSED" if sync_stats.get("passed_sync") else "FLAGGED"}</span></div>
  </div>
  <table>
    <thead>
      <tr>
        <th>ID & Role</th>
        <th>Spoken Sentence</th>
        <th>Duration</th>
        <th>Visual</th>
        <th>Relevance</th>
        <th>Provider</th>
        <th>Attribution / License</th>
      </tr>
    </thead>
    <tbody>
      {"".join(rows_html)}
    </tbody>
  </table>
</body>
</html>"""
        output_html_path.write_text(html_content, encoding="utf-8")
        logger.info(f"Generated alignment report at: {output_html_path.name}")
        return output_html_path
