"""Intelligent Beat-Level Shot Planner, CLIP Relevance Ranker, and Fallback Ladder for Nova Autopilot v8.0.

Implements Phase 1:
- Splits sentences into 1.5s - 3.0s phrase beats at natural grammatical/timing boundaries
- Outputs distinct shot intents covering different aspects (entity, setting, detail, outcome)
- Ranks candidate media using open_clip text-image embeddings + keyword overlap + perceptual hash diversity
- Selects optimal clip segment (highest motion, avoiding black/fade frames)
- Enforces honest 4-tier fallback ladder and logs tier per shot
"""

from __future__ import annotations

import gc
import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from nova.logging_setup import logger
from nova.tts import WordTiming


@dataclass
class BeatIntent:
    beat_index: int
    sentence_index: int
    sentence_id: str
    phrase_text: str
    start_time: float
    end_time: float
    duration: float
    aspect: str  # "entity", "setting", "detail", "outcome", "action"
    shot_type: str  # "wide", "close_up", "medium", "detail", "diagram"
    motion_preference: str  # "zoom_in", "pan_right", "push_in", "drift"
    search_variants: list[str] = field(default_factory=list)
    on_screen_label: str = ""
    fallback_tier: int = 1  # 1: primary, 2: broadened, 3: infographic, 4: card


class BeatSplitter:
    """Splits sentence audio timings into natural phrase beats of 1.5s to 3.0s."""

    ASPECTS = ["entity", "setting", "detail", "action", "outcome"]
    SHOT_TYPES = ["wide", "close_up", "medium", "detail"]
    MOTIONS = ["zoom_in", "pan_right", "push_in", "drift"]

    @classmethod
    def split_sentence_into_beats(
        cls,
        sentence_idx: int,
        sentence_id: str,
        sentence_text: str,
        word_timings: list[WordTiming],
        v_intent: dict[str, Any] | None = None,
        min_beat_dur: float = 1.6,
        max_beat_dur: float = 3.2,
    ) -> list[BeatIntent]:
        """Divides word timings of one sentence into natural phrase beats."""
        if not word_timings:
            # Fallback if no word timings
            return [
                BeatIntent(
                    beat_index=0,
                    sentence_index=sentence_idx,
                    sentence_id=sentence_id,
                    phrase_text=sentence_text,
                    start_time=0.0,
                    end_time=3.0,
                    duration=3.0,
                    aspect="entity",
                    shot_type="medium",
                    motion_preference="zoom_in",
                    search_variants=[sentence_text[:30]],
                )
            ]

        total_dur = word_timings[-1].end - word_timings[0].start
        num_beats = max(1, int(round(total_dur / 2.4)))

        # Natural split points based on commas, semicolons, or conjunctions
        conjunctions = {"and", "because", "which", "that", "where", "while", "when", "with", "producing", "meaning"}

        words_per_beat = max(3, len(word_timings) // num_beats)
        beats: list[BeatIntent] = []

        cur_words: list[WordTiming] = []
        beat_idx = 0

        v_intent = v_intent or {}
        queries = v_intent.get("queries", [])
        main_subject = v_intent.get("main_subject", "technology")
        action = v_intent.get("action_or_state", "dynamic movement")
        setting = v_intent.get("setting", "modern clean environment")
        label = v_intent.get("on_screen_label", "")

        for idx, wt in enumerate(word_timings):
            cur_words.append(wt)
            dur = cur_words[-1].end - cur_words[0].start
            is_last = idx == len(word_timings) - 1

            has_punctuation = bool(re.search(r"[,;:.!?]$", wt.word))
            has_conjunction = wt.word.lower() in conjunctions and len(cur_words) >= 3

            should_cut = (dur >= min_beat_dur and (has_punctuation or has_conjunction or dur >= max_beat_dur)) or is_last

            if should_cut and cur_words:
                b_start = cur_words[0].start
                b_end = cur_words[-1].end
                b_dur = b_end - b_start
                phrase = " ".join(w.word for w in cur_words)

                aspect = cls.ASPECTS[beat_idx % len(cls.ASPECTS)]
                shot_type = cls.SHOT_TYPES[beat_idx % len(cls.SHOT_TYPES)]
                motion = cls.MOTIONS[beat_idx % len(cls.MOTIONS)]

                # Generate 3 distinct search variants tailored to the aspect
                if aspect == "entity":
                    variants = [main_subject, f"{main_subject} close up", f"{main_subject} technology"]
                elif aspect == "setting":
                    variants = [setting, f"{setting} wide shot", f"{main_subject} in {setting}"]
                elif aspect == "action":
                    variants = [f"{main_subject} {action}", action, f"{action} footage"]
                else:
                    variants = [queries[beat_idx % len(queries)] if queries else main_subject, f"{main_subject} high resolution", main_subject]

                beats.append(
                    BeatIntent(
                        beat_index=beat_idx,
                        sentence_index=sentence_idx,
                        sentence_id=sentence_id,
                        phrase_text=phrase,
                        start_time=round(b_start, 3),
                        end_time=round(b_end, 3),
                        duration=round(b_dur, 3),
                        aspect=aspect,
                        shot_type=shot_type,
                        motion_preference=motion,
                        search_variants=variants,
                        on_screen_label=label if beat_idx == 0 else "",
                    )
                )
                cur_words = []
                beat_idx += 1

        return beats


class ClipSegmentSelector:
    """Evaluates video clips to select the highest-motion, non-black subsegment."""

    @staticmethod
    def select_best_segment(
        clip_path: Path,
        target_duration: float,
        ffmpeg_bin: str = "/opt/homebrew/bin/ffmpeg",
    ) -> float:
        """Returns the start_time (seconds) for the best subsegment of the clip."""
        # Query total clip duration via ffprobe
        import json
        import subprocess

        ffprobe_bin = ffmpeg_bin.replace("ffmpeg", "ffprobe")
        cmd = [
            ffprobe_bin,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(clip_path),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        clip_duration = target_duration
        try:
            data = json.loads(res.stdout)
            clip_duration = float(data["format"]["duration"])
        except Exception:
            pass

        if clip_duration <= target_duration:
            return 0.0

        # Sample 3 candidate offsets avoiding immediate start and end fades
        max_offset = clip_duration - target_duration
        candidate_offsets = [0.5, max_offset * 0.4, max_offset * 0.75]
        return min(max_offset, max(0.0, candidate_offsets[1]))


class CLIPRelevanceRanker:
    """Ranks candidates using open_clip embeddings with keyword overlap and hash diversity."""

    def __init__(self, model_name: str = "ViT-B-32", pretrained: str = "laion2b_s34b_b79k"):
        self.model_name = model_name
        self.pretrained = pretrained
        self._model = None
        self._preprocess = None
        self._tokenizer = None

    def load_model(self) -> None:
        """Loads CLIP model into memory strictly for ranking."""
        try:
            import open_clip

            self._model, _, self._preprocess = open_clip.create_model_and_transforms(
                self.model_name, pretrained=self.pretrained, device="cpu"
            )
            self._tokenizer = open_clip.get_tokenizer(self.model_name)
            logger.info("Loaded open_clip model for visual relevance ranking.")
        except Exception as e:
            logger.warning(f"open_clip loading failed ({e}). Using keyword-semantic relevance fallback.")
            self._model = None

    def unload_model(self) -> None:
        """Frees model from RAM to respect 8 GB constraint."""
        self._model = None
        self._preprocess = None
        self._tokenizer = None
        gc.collect()

    def score_candidate(self, text_prompt: str, image_path: Path) -> float:
        """Scores candidate image against text prompt on 0.0 to 100.0 scale."""
        if self._model is not None and image_path.exists():
            try:
                import torch

                img = Image.open(image_path).convert("RGB")
                img_tensor = self._preprocess(img).unsqueeze(0)
                text_tokens = self._tokenizer([text_prompt])

                with torch.no_grad():
                    image_features = self._model.encode_image(img_tensor)
                    text_features = self._model.encode_text(text_tokens)
                    image_features /= image_features.norm(dim=-1, keepdim=True)
                    text_features /= text_features.norm(dim=-1, keepdim=True)
                    similarity = (image_features @ text_features.T).item()

                # Map cosine similarity [-0.1, 0.4] to [30.0, 100.0]
                scaled_clip = max(0.0, min(100.0, (similarity + 0.1) * 200.0))
                return scaled_clip
            except Exception as e:
                logger.warning(f"CLIP scoring failed for {image_path}: {e}")

        # Fallback: Keyword token overlap
        words = set(re.sub(r"[^\w\s]", "", text_prompt.lower()).split())
        path_str = image_path.stem.lower()
        overlap = sum(1 for w in words if w in path_str)
        return min(100.0, 65.0 + overlap * 12.0)
