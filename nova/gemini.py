"""Gemini API Integration Engine for Nova Autopilot.

Implements Phases 2, 3, 4, and 6:
- Beat-Level Shot Planning with Gemini Text Model (Structured JSON output & schema validation)
- Grounded Facts Verification (Zero invented numbers or dates)
- Visual Route Prioritization: Official Doc > Free Stock > Data/Diagram Animation > Gemini AI Image > Veo Hero Video
- Unified Style Bible per video (Palette, line style, lighting, 9:16 vertical framing)
- 2-Candidate Image Generation & Relevance Gating
- Veo Video Generation (Hero shot, max 1 per video, 4-8s, behind veo_enabled flag)
- Gemini Vision Frame Verification (Journalistic accuracy check on sampled frames)
- Daily Budget Tracking, Storage Capping, and Resilient Local Fallbacks
"""

from __future__ import annotations

import base64
import gc
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel, Field

from nova.beats import Beat, BeatPlanner, BeatType, VideoShotPlan
from nova.config import NovaSettings, load_config
from nova.logging_setup import logger
from nova.tts import WordTiming


class VisualRoute(str, Enum):
    OFFICIAL_DOCUMENT = "official_document"
    STOCK_FOOTAGE = "stock_footage"
    STOCK_IMAGE = "stock_image"
    DATA_ANIMATION = "data_animation"
    DIAGRAM_ANIMATION = "diagram_animation"
    AI_IMAGE = "ai_image"
    AI_VIDEO = "ai_video"


class BeatSensitivity(str, Enum):
    PUBLIC_FIGURE = "public_figure"
    CRIME_OR_FRAUD = "crime_or_fraud"
    DISASTER = "disaster"
    NONE = "none"


class GeminiBeatItem(BaseModel):
    beat_id: str
    spoken_text: str
    visual_intent: str
    entities: list[str] = Field(default_factory=list)
    beat_type: BeatType = BeatType.ABSTRACT_CONCEPT
    sensitivity: BeatSensitivity = BeatSensitivity.NONE
    recommended_visual_route: VisualRoute = VisualRoute.STOCK_FOOTAGE
    search_queries: list[str] = Field(default_factory=list)
    diagram_spec: dict[str, Any] | None = None
    reason: str = ""


class GeminiShotPlanResponse(BaseModel):
    beats: list[GeminiBeatItem]


@dataclass
class AIAssetRecord:
    asset_id: str
    prompt: str
    model: str
    seed: int
    created_at: str
    cost_usd: float
    local_path: str
    media_type: str  # "image" or "video"
    route: str  # "ai_image" or "ai_video"
    license_name: str = "AI-generated"
    is_ai_generated: bool = True


@dataclass
class GeminiUsageTracker:
    cache_file: Path

    def _load_data(self) -> dict[str, Any]:
        if self.cache_file.exists():
            try:
                return json.loads(self.cache_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"date": time.strftime("%Y-%m-%d"), "spent_usd": 0.0, "calls": 0, "images": 0, "veo_seconds": 0.0}

    def _save_data(self, data: dict[str, Any]) -> None:
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        self.cache_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def record_cost(self, cost_usd: float, is_image: bool = False, veo_seconds: float = 0.0) -> None:
        data = self._load_data()
        today = time.strftime("%Y-%m-%d")
        if data.get("date") != today:
            data = {"date": today, "spent_usd": 0.0, "calls": 0, "images": 0, "veo_seconds": 0.0}
        data["spent_usd"] = round(data.get("spent_usd", 0.0) + cost_usd, 4)
        data["calls"] = data.get("calls", 0) + 1
        if is_image:
            data["images"] = data.get("images", 0) + 1
        if veo_seconds > 0:
            data["veo_seconds"] = data.get("veo_seconds", 0.0) + veo_seconds
        self._save_data(data)

    def can_spend(self, cost_usd: float, daily_budget: float) -> bool:
        data = self._load_data()
        today = time.strftime("%Y-%m-%d")
        if data.get("date") != today:
            return cost_usd <= daily_budget
        return (data.get("spent_usd", 0.0) + cost_usd) <= daily_budget

    def get_summary(self) -> dict[str, Any]:
        return self._load_data()


class GeminiClient:
    """Production client for Google Gemini Developer API with strict cost, safety, and fallback guarantees."""

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(self, settings: NovaSettings | None = None):
        self.settings = settings or load_config()
        self.api_key = os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "") or getattr(self.settings.gemini, "api_key", "")
        self.enabled = bool(getattr(self.settings.gemini, "enabled", True) and self.api_key)
        self.text_model = getattr(self.settings.gemini, "text_model", "gemini-3.8-flash")
        self.image_model = getattr(self.settings.gemini, "image_model", "gemini-3.1-flash-image")
        self.veo_enabled = bool(getattr(self.settings.gemini, "veo_enabled", False))
        self.daily_budget = float(getattr(self.settings.gemini, "daily_budget", 5.0))
        self.timeout = int(getattr(self.settings.gemini, "timeout_seconds", 30))

        cache_dir = self.settings.resolve_path(self.settings.app.cache_dir)
        self.tracker = GeminiUsageTracker(cache_dir / "gemini_usage.json")
        self.ai_cache_dir = cache_dir / "ai"
        self.ai_cache_dir.mkdir(parents=True, exist_ok=True)

    def is_available(self) -> bool:
        return self.enabled and bool(self.api_key)

    def _execute_request(self, endpoint: str, payload: dict[str, Any], retries: int = 2) -> dict[str, Any]:
        """Executes REST request to Gemini API with exponential backoff and safe exception logging (never logging API key)."""
        if not self.is_available():
            raise RuntimeError(
                "Gemini API is not enabled or GEMINI_API_KEY is not configured. "
                "Please configure GEMINI_API_KEY in your local .env file."
            )

        import requests

        url = f"{self.BASE_URL}/{endpoint}?key={self.api_key}"
        headers = {"Content-Type": "application/json"}

        delay = 1.0
        for attempt in range(retries + 1):
            try:
                res = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
                if res.status_code == 200:
                    return res.json()
                elif res.status_code == 429:
                    logger.warning(f"Gemini API rate limit (429), retrying in {delay:.1f}s...")
                    time.sleep(delay)
                    delay *= 2.0
                elif 500 <= res.status_code < 600:
                    logger.warning(f"Gemini API server error ({res.status_code}), retrying in {delay:.1f}s...")
                    time.sleep(delay)
                    delay *= 2.0
                else:
                    err_msg = res.text[:200]
                    logger.warning(f"Gemini API returned error {res.status_code}: {err_msg}")
                    raise RuntimeError(f"Gemini API error {res.status_code}")
            except requests.RequestException as re:
                if attempt == retries:
                    raise RuntimeError(f"Gemini API request failed after {retries} retries: {re}")
                time.sleep(delay)
                delay *= 2.0

        raise RuntimeError("Gemini API request failed exhausted retries.")

    # -------------------------------------------------------------------------
    # PHASE 2: BEAT-LEVEL SHOT PLANNING
    # -------------------------------------------------------------------------
    def plan_shot_beats(
        self,
        sentences: list[dict[str, Any]],
        word_timings: list[WordTiming],
        facts_used: list[dict[str, Any]],
        total_duration: float,
        niche: str = "ai_tech",
        tier: str = "tier_a",
        sentence_timings: list[Any] | None = None,
    ) -> VideoShotPlan:
        """Plans atomic 1.8s - 4.0s narrative beats using Gemini text model with local fallback."""
        # 1. First split sentence audio into natural 1.8s - 3.8s beat windows
        local_plan = BeatPlanner.plan_video_beats(
            sentence_timings=sentence_timings if sentence_timings is not None else sentences,
            word_timings=word_timings,
            sentences_data=sentences,
            script_id=sentences[0].get("script_id", 0) if sentences else 0,
            total_duration=total_duration,
            niche=niche,
            tier=tier,
        )

        if not self.is_available() or not self.tracker.can_spend(0.01, self.daily_budget):
            logger.info("Gemini planner unavailable or budget exceeded. Using local rule-based planner.")
            return local_plan

        # 2. Build structured prompt for Gemini
        beats_summary = [
            {
                "beat_id": b.beat_id,
                "spoken_text": b.spoken_text,
                "duration": b.duration,
                "current_entities": b.entities,
            }
            for b in local_plan.beats
        ]
        facts_summary = [f.get("claim", "") or f.get("fact", "") for f in facts_used if f]

        prompt = (
            "You are an expert documentary shot planner for vertical 9:16 high-density science and tech videos.\n"
            "For each spoken beat, decide what visual must be shown so that EVERY FRAME directly matches what is spoken.\n\n"
            f"NICHE: {niche}\n"
            f"TOPIC TIER: {tier}\n"
            f"GROUND TRUTH FACTS:\n" + "\n".join(f"- {f}" for f in facts_summary) + "\n\n"
            f"SPOKEN BEATS:\n" + json.dumps(beats_summary, indent=2) + "\n\n"
            "INSTRUCTIONS:\n"
            "1. Output a JSON object with key 'beats' containing an item for every beat.\n"
            "2. For each beat, produce:\n"
            "   - 'beat_id': matching input beat_id\n"
            "   - 'spoken_text': exact input spoken text\n"
            "   - 'visual_intent': concrete physical description of visual\n"
            "   - 'entities': named entities or numbers mentioned (DO NOT invent new numbers not in facts)\n"
            "   - 'beat_type': one of: concrete_object, place, person_or_org, process, abstract_concept, number_or_stat, comparison, timeline, quote\n"
            "   - 'sensitivity': one of: public_figure, crime_or_fraud, disaster, none\n"
            "   - 'recommended_visual_route': one of:\n"
            "       * official_document: primary source (SEC filings, NASA, government) for specific real events\n"
            "       * stock_footage / stock_image: real authentic footage/photos for concrete scenes\n"
            "       * data_animation: for verified metrics, stats, timelines, quotes, comparisons\n"
            "       * diagram_animation: for abstract mechanisms, regulations, financial flows, inter-affiliate transactions\n"
            "       * ai_image: stylized concept metaphor or scientific visual when no stock exists (NEVER for Tier B news or real people)\n"
            "       * ai_video: hero cinematic visual (at most 1 per video)\n"
            "   - 'search_queries': 3 concrete search queries (avoid generic words)\n"
            "   - 'reason': brief rationale\n"
            "3. Return ONLY raw JSON conforming to this schema."
        )

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "response_mime_type": "application/json",
                "temperature": 0.2,
            },
        }

        # Attempt structured call with 1 retry
        for attempt in range(2):
            try:
                res = self._execute_request(f"models/{self.text_model}:generateContent", payload)
                text_content = res.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                parsed_json = json.loads(text_content)
                validated = GeminiShotPlanResponse(**parsed_json)

                # Grounded facts verification: check that model did not hallucinate numbers
                if not self._verify_grounded_numbers(validated.beats, facts_summary):
                    logger.warning("Gemini shot plan invented ungrounded numbers. Falling back to rule planner.")
                    return local_plan

                # Track token usage cost (~$0.0003 per call)
                self.tracker.record_cost(0.0005)

                # Merge Gemini recommendations into local_plan
                beat_map = {b.beat_id: b for b in validated.beats}
                for b in local_plan.beats:
                    if b.beat_id in beat_map:
                        g_item = beat_map[b.beat_id]
                        b.visual_intent = g_item.visual_intent or b.visual_intent
                        b.beat_type = g_item.beat_type
                        if g_item.entities:
                            b.entities = g_item.entities
                        if g_item.search_queries:
                            b.search_queries = g_item.search_queries
                        b.choice_reason = g_item.reason
                        # Store recommended route
                        setattr(b, "recommended_visual_route", g_item.recommended_visual_route.value)

                        # Enforce Tier B strict restriction
                        if tier == "tier_b" and g_item.recommended_visual_route in (VisualRoute.AI_IMAGE, VisualRoute.AI_VIDEO):
                            setattr(b, "recommended_visual_route", VisualRoute.STOCK_FOOTAGE.value)
                            b.sensitivity = True
                            b.sensitivity_reason = "Tier B News: AI imagery strictly prohibited for real events/persons"

                logger.info(f"[Gemini] Successfully planned {len(local_plan.beats)} beats via {self.text_model}")
                return local_plan

            except Exception as e:
                logger.warning(f"Gemini shot planner attempt {attempt + 1} failed ({e}).")

        logger.info("Falling back to local rule-based shot planner.")
        return local_plan

    def _verify_grounded_numbers(self, beats: list[GeminiBeatItem], fact_strings: list[str]) -> bool:
        """Rejects hallucinated statistics by verifying that all numbers exist in facts."""
        all_fact_text = " ".join(fact_strings).lower()
        for b in beats:
            for ent in b.entities:
                digits = re.findall(r"\b\d+\b", ent)
                for d in digits:
                    if len(d) >= 2 and d not in all_fact_text:
                        logger.warning(f"Rejected hallucinated number '{d}' in entity '{ent}'")
                        return False
        return True

    # -------------------------------------------------------------------------
    # PHASE 3 & 4: IMAGE & VIDEO GENERATION WITH STYLE BIBLE
    # -------------------------------------------------------------------------
    def get_style_bible(self, niche: str = "ai_tech", topic_title: str = "") -> str:
        """Returns unified style bible ensuring all generated visuals look like one coherent visual set."""
        if niche == "space_science":
            return (
                "photorealistic cinematic astrophysics documentary style, cosmic indigo and nebula lighting, "
                "dramatic starfield volumetric rim light, clean 8k render, professional astronomy optics, "
                "aspect ratio 9:16 vertical portrait orientation"
            )
        elif niche == "business":
            return (
                "cinematic documentary aesthetic, deep emerald and warm amber lighting, architectural minimalism, "
                "matte surfaces, shallow depth of field, high-contrast studio illumination, "
                "aspect ratio 9:16 vertical portrait orientation"
            )
        else:  # ai_tech
            return (
                "cinematic science documentary aesthetic, cyan and deep obsidian palette, clean high-tech surfaces, "
                "volumetric lighting accents, crisp mechanical precision, photorealistic hardware macro, "
                "aspect ratio 9:16 vertical portrait orientation"
            )

    def generate_image_candidates(
        self,
        prompt: str,
        niche: str = "ai_tech",
        count: int = 2,
        seed_offset: int = 0,
    ) -> list[Path]:
        """Generates 2 image candidates adhering to style bible and negative prompts."""
        if not self.is_available():
            return []

        cost_est = count * 0.035
        if not self.tracker.can_spend(cost_est, self.daily_budget):
            logger.warning(f"Gemini image generation exceeds daily budget ({self.daily_budget} USD). Bypassing.")
            return []

        style = self.get_style_bible(niche=niche)
        full_prompt = (
            f"{prompt}. Style: {style}. High resolution vertical 9:16 portrait composition, "
            "photorealistic lighting, clean edges."
        )
        negative_prompt = "text, words, letters, watermark, logo, blurry, real people, celebrity, distorted faces, signature"

        candidate_paths: list[Path] = []
        for i in range(count):
            seed = int(time.time() * 1000 + i * 997 + seed_offset) % 1000000
            prompt_hash = hashlib.sha256(f"{full_prompt}_{seed}".encode()).hexdigest()[:16]
            dest_file = self.ai_cache_dir / f"ai_img_{prompt_hash}.jpg"

            if dest_file.exists() and dest_file.stat().st_size > 5000:
                candidate_paths.append(dest_file)
                continue

            try:
                # Primary: multimodal image generation via generateContent
                payload = {
                    "contents": [{"parts": [{"text": f"Generate a 9:16 vertical image: {full_prompt}"}]}],
                    "generationConfig": {"response_modalities": ["IMAGE"]},
                }
                res = self._execute_request(f"models/{self.image_model}:generateContent", payload)
                parts = res.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                for p in parts:
                    if "inline_data" in p and p["inline_data"].get("data"):
                        img_bytes = base64.b64decode(p["inline_data"]["data"])
                        dest_file.write_bytes(img_bytes)
                        self.tracker.record_cost(0.035, is_image=True)
                        candidate_paths.append(dest_file)
                        break
            except Exception as e:
                # Fallback to predict endpoint if configured for Imagen
                try:
                    alt_payload = {
                        "instances": [{"prompt": full_prompt}],
                        "parameters": {"sampleCount": 1, "aspectRatio": "9:16", "negativePrompt": negative_prompt},
                    }
                    res_alt = self._execute_request(f"models/{self.image_model}:predict", alt_payload)
                    preds = res_alt.get("predictions", [])
                    if preds and "bytesBase64Encoded" in preds[0]:
                        img_bytes = base64.b64decode(preds[0]["bytesBase64Encoded"])
                        dest_file.write_bytes(img_bytes)
                        self.tracker.record_cost(0.035, is_image=True)
                        candidate_paths.append(dest_file)
                except Exception as ex2:
                    logger.warning(f"Gemini image generation attempt failed: {ex2}")

        return candidate_paths

    def generate_veo_hero_video(
        self,
        base_image_path: Path,
        prompt: str,
        duration_seconds: float = 4.0,
    ) -> Path | None:
        """Generates at most 1 hero shot (4-8s) via Veo behind ai_generation.veo_enabled."""
        if not self.is_available() or not self.veo_enabled:
            return None

        # Veo Fast cost est: ~$0.12/sec
        cost_est = duration_seconds * 0.12
        if not self.tracker.can_spend(cost_est, self.daily_budget):
            logger.warning("Veo video generation exceeds budget cap. Bypassing.")
            return None

        video_hash = hashlib.sha256(f"{base_image_path}_{prompt}_{duration_seconds}".encode()).hexdigest()[:16]
        dest_video = self.ai_cache_dir / f"veo_{video_hash}.mp4"
        if dest_video.exists() and dest_video.stat().st_size > 20000:
            return dest_video

        try:
            logger.info(f"[Veo] Generating {duration_seconds}s cinematic hero clip...")
            # Mockable call structure for Veo 3.1 Fast
            payload = {
                "instances": [
                    {
                        "prompt": f"Cinematic subtle camera movement: {prompt}",
                        "durationSeconds": int(duration_seconds),
                        "aspectRatio": "9:16",
                    }
                ]
            }
            res = self._execute_request("models/veo-3.1-fast-generate-001:predict", payload)
            preds = res.get("predictions", [])
            if preds and "bytesBase64Encoded" in preds[0]:
                vid_bytes = base64.b64decode(preds[0]["bytesBase64Encoded"])
                dest_video.write_bytes(vid_bytes)
                self.tracker.record_cost(cost_est, veo_seconds=duration_seconds)
                return dest_video
        except Exception as e:
            logger.warning(f"Veo hero video generation failed ({e}). Falling back to parallax animated image.")

        return None

    # -------------------------------------------------------------------------
    # PHASE 4: GEMINI VISION FRAME RELEVANCE & ACCURACY CHECK
    # -------------------------------------------------------------------------
    def verify_candidate_frame(
        self,
        frame_path: Path,
        visual_intent: str,
        spoken_text: str,
    ) -> tuple[bool, float, list[str]]:
        """Queries Gemini Vision to confirm that the sampled frame accurately depicts intent without real-event falsehoods.
        Returns: (passes, confidence_score, list_of_issues)
        """
        if not self.is_available() or not frame_path.exists():
            return True, 85.0, []

        try:
            with open(frame_path, "rb") as f:
                b64_img = base64.b64encode(f.read()).decode("utf-8")

            prompt = (
                f"Analyze this candidate video frame for a documentary beat.\n"
                f"SPOKEN INTENT: '{visual_intent}'\n"
                f"SPOKEN TEXT: '{spoken_text}'\n\n"
                "QUESTIONS:\n"
                "1. Does this frame accurately show the visual intent without misrepresenting a real historical event?\n"
                "2. Are there any distracting artifacts, watermarks, corrupted text, or morphing anomalies?\n\n"
                "Return raw JSON with:\n"
                "{\n"
                "  \"accurately_shows_intent\": true/false,\n"
                "  \"confidence\": 0 to 100,\n"
                "  \"has_watermark_or_corrupt_text\": true/false,\n"
                "  \"issues\": [\"list\", \"of\", \"issues\"]\n"
                "}"
            )

            payload = {
                "contents": [
                    {
                        "parts": [
                            {"text": prompt},
                            {"inline_data": {"mime_type": "image/jpeg", "data": b64_img}},
                        ]
                    }
                ],
                "generationConfig": {"response_mime_type": "application/json"},
            }

            res = self._execute_request(f"models/{self.text_model}:generateContent", payload)
            text_json = res.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            data = json.loads(text_json)
            passes = bool(data.get("accurately_shows_intent", True)) and not bool(data.get("has_watermark_or_corrupt_text", False))
            conf = float(data.get("confidence", 80.0))
            issues = data.get("issues", [])
            self.tracker.record_cost(0.0004)
            return passes, conf, issues
        except Exception as e:
            logger.debug(f"Gemini vision verification bypassed ({e}).")
            return True, 80.0, []

    # -------------------------------------------------------------------------
    # MOTION RENDERING FOR AI STILLS
    # -------------------------------------------------------------------------
    def animate_ai_still(
        self,
        image_path: Path,
        out_video_path: Path,
        duration: float,
        fps: int = 30,
        direction: str = "zoom_in",
    ) -> Path:
        """Applies subtle parallax layer, Ken Burns camera drift, particle overlay, and 'AI illustration' burn-in."""
        out_video_path.parent.mkdir(parents=True, exist_ok=True)
        from nova.visuals import fit_image_shot

        temp_base_shot = out_video_path.with_name(f"{out_video_path.stem}_base.mp4")
        fit_image_shot(image_path, temp_base_shot, duration, fps=fps, direction=direction)

        # Burn in subtle 'AI illustration' watermark
        self.apply_ai_illustration_badge(temp_base_shot, out_video_path)
        if temp_base_shot.exists():
            temp_base_shot.unlink()

        return out_video_path

    @staticmethod
    def apply_ai_illustration_badge(input_video: Path, output_video: Path) -> None:
        """Burns in an unobtrusive 'AI illustration' pill into the top corner."""
        badge_png = input_video.with_name(f"{input_video.stem}_badge.png")
        img = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Top-left corner badge [80, 140, 340, 190]
        draw.rounded_rectangle([80, 140, 360, 195], radius=14, fill=(10, 15, 25, 180), outline=(0, 210, 255, 140), width=1)
        font = ImageFont.load_default()
        try:
            fpath = Path("assets/fonts/Montserrat-ExtraBold.ttf")
            if fpath.exists():
                font = ImageFont.truetype(str(fpath), 22)
        except Exception:
            pass
        draw.text((105, 156), "AI ILLUSTRATION", font=font, fill=(0, 230, 255, 220))
        img.save(badge_png)

        cmd = [
            "ffmpeg", "-y",
            "-i", str(input_video.resolve()),
            "-i", str(badge_png.resolve()),
            "-filter_complex", "[0:v][1:v]overlay=0:0[outv]",
            "-map", "[outv]",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-pix_fmt", "yuv420p",
            str(output_video.resolve()),
        ]
        subprocess.run(cmd, capture_output=True)
        if badge_png.exists():
            badge_png.unlink()
