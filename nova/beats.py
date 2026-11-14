"""Beat-Level Shot Planning, Entity Extraction, and Intent Architecture for Nova Autopilot.

Splits voiceover sentences into natural 1.8s - 4.0s idea beats based on Whisper word-level
timestamps. Extracts concrete entities, classifies beat types, detects sensitivity (crime/person/disaster),
generates 3-6 prioritized query variants per beat, and maintains the complete beat shot plan.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from nova.logging_setup import logger
from nova.tts import WordTiming


class BeatType(str, Enum):
    CONCRETE_OBJECT = "concrete_object"
    PLACE = "place"
    PERSON_OR_ORG = "person_or_org"
    PROCESS = "process"
    ABSTRACT_CONCEPT = "abstract_concept"
    NUMBER_OR_STAT = "number_or_stat"
    COMPARISON = "comparison"
    TIMELINE = "timeline"
    QUOTE = "quote"


@dataclass
class Beat:
    """A single atomic visual-narrative beat corresponding to a 1.8s - 4.0s spoken phrase."""

    beat_id: str  # e.g. "B1_1", "B1_2"
    beat_index: int  # Global sequential index 0, 1, 2...
    sentence_id: str  # e.g. "S1"
    sentence_index: int
    spoken_text: str  # Spoken words in this beat
    caption_text: str  # Clean formatted text
    start_time: float  # Exact start seconds from Whisper
    end_time: float  # Exact end seconds from Whisper
    duration: float  # Beat duration in seconds
    visual_intent: str  # Concrete description of what must be shown
    entities: list[str]  # Named entities, numbers, places, objects
    beat_type: BeatType  # One of the 9 classified beat types
    sensitivity: bool = False  # True if crime, accusation, real person, disaster
    sensitivity_reason: str = ""  # Reason for sensitivity classification
    search_queries: list[str] = field(default_factory=list)  # 3-6 query variants
    is_specific_event: bool = False  # Specific historic or real claim
    recommended_visual_route: str = "stock_footage"  # official_document, stock_footage, data_animation, diagram_animation, ai_image, ai_video

    # Asset Selection Record
    chosen_asset_id: str = ""
    chosen_asset_url: str = ""
    chosen_asset_path: str = ""
    provider: str = ""
    media_type: str = "video"  # "video", "image", "animation", "card"
    license_id: str = ""
    license_name: str = ""
    match_score: float = 0.0
    choice_reason: str = ""
    is_illustrative: bool = False  # If generic stock, requires "Illustrative footage" badge
    render_method: str = "video_fit"  # "video_fit", "ken_burns", "count_up_chart", etc.
    alternatives: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["beat_type"] = self.beat_type.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Beat":
        cdata = dict(data)
        if "beat_type" in cdata and isinstance(cdata["beat_type"], str):
            cdata["beat_type"] = BeatType(cdata["beat_type"])
        return cls(**cdata)


@dataclass
class VideoShotPlan:
    """Complete beat-level shot plan for a video."""

    video_id: int
    script_id: int
    total_duration: float
    fps: int = 30
    beats: list[Beat] = field(default_factory=list)
    niche: str = "ai_tech"
    tier: str = "tier_a"

    def to_dict(self) -> dict[str, Any]:
        return {
            "video_id": self.video_id,
            "script_id": self.script_id,
            "total_duration": round(self.total_duration, 3),
            "fps": self.fps,
            "niche": self.niche,
            "tier": self.tier,
            "total_beats": len(self.beats),
            "beats": [b.to_dict() for b in self.beats],
        }

    def save_json(self, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return output_path

    @classmethod
    def load_json(cls, json_path: Path) -> "VideoShotPlan":
        data = json.loads(json_path.read_text(encoding="utf-8"))
        beats = [Beat.from_dict(b) for b in data.get("beats", [])]
        return cls(
            video_id=data.get("video_id", 0),
            script_id=data.get("script_id", 0),
            total_duration=data.get("total_duration", 0.0),
            fps=data.get("fps", 30),
            beats=beats,
            niche=data.get("niche", "ai_tech"),
            tier=data.get("tier", "tier_a"),
        )


class BeatPlanner:
    """Extracts semantic beats, entities, and search queries from sentence and word timings."""

    SENSITIVE_KEYWORDS = {
        "fraud", "crime", "charged", "scheme", "scandal", "investigation", "lawsuit",
        "arrest", "indictment", "bribe", "guilty", "allegation", "crash", "disaster",
        "explosion", "fatality", "killed", "died", "tragedy", "collapse"
    }

    COMPARISON_WORDS = {
        "compared to", "vs", "versus", "unlike", "more than", "less than",
        "greater than", "instead of", "ratio", "double", "triple", "fraction"
    }

    TIMELINE_WORDS = {
        "in 20", "in 19", "decade", "century", "years ago", "earlier", "later",
        "afterwards", "eventually", "timeline", "history", "originally"
    }

    QUOTE_WORDS = {
        "said", "stated", "claimed", "warned", "admitted", "tweeted", "wrote",
        "argued", "announced", "testified"
    }

    @classmethod
    def plan_video_beats(
        cls,
        sentence_timings: list[Any],
        word_timings: list[WordTiming],
        sentences_data: list[dict[str, Any]] | None = None,
        video_id: int = 0,
        script_id: int = 0,
        total_duration: float = 30.0,
        niche: str = "ai_tech",
        tier: str = "tier_a",
    ) -> VideoShotPlan:
        """Constructs a gapless sequence of 1.8s - 4.0s beats covering the entire video."""
        sentences_data = sentences_data or []
        beats: list[Beat] = []
        global_beat_index = 0

        # Build sentence word groupings
        for s_idx, st in enumerate(sentence_timings):
            if isinstance(st, dict):
                s_text = st.get("text", "")
                s_id = st.get("sentence_id") or st.get("id") or f"S{s_idx + 1}"
                s_start = float(st.get("start_time") or st.get("start") or 0.0)
                s_end = float(st.get("end_time") or st.get("end") or (s_start + float(st.get("duration") or 3.0)))
            else:
                s_text = getattr(st, "text", "")
                s_id = getattr(st, "sentence_id", f"S{s_idx + 1}")
                s_start = getattr(st, "start_time", getattr(st, "start", 0.0))
                s_end = getattr(st, "end_time", getattr(st, "end", s_start + getattr(st, "duration", 3.0)))

            # Match words belonging to this sentence window
            s_words = [w for w in word_timings if w.start >= (s_start - 0.15) and w.end <= (s_end + 0.15)]
            if not s_words:
                s_words = [w for w in word_timings if s_start <= ((w.start + w.end) / 2.0) <= s_end]

            s_meta = sentences_data[s_idx] if s_idx < len(sentences_data) else {}
            sentence_beats = cls._split_sentence_into_beats(
                sentence_index=s_idx,
                sentence_id=s_id,
                sentence_text=s_text,
                sentence_words=s_words,
                sentence_start=s_start,
                sentence_end=s_end,
                meta=s_meta,
                start_beat_idx=global_beat_index,
                niche=niche,
                tier=tier,
            )

            beats.extend(sentence_beats)
            global_beat_index += len(sentence_beats)

        # Enforce exact gapless continuity from 0.0 to total_duration
        if beats:
            beats[0].start_time = 0.0
            for i in range(len(beats) - 1):
                # Snap beat boundary
                boundary = round((beats[i].end_time + beats[i + 1].start_time) / 2.0, 3)
                beats[i].end_time = boundary
                beats[i].duration = round(beats[i].end_time - beats[i].start_time, 3)
                beats[i + 1].start_time = boundary
                beats[i + 1].duration = round(beats[i + 1].end_time - beats[i + 1].start_time, 3)

            beats[-1].end_time = round(total_duration, 3)
            beats[-1].duration = round(beats[-1].end_time - beats[-1].start_time, 3)

        return VideoShotPlan(
            video_id=video_id,
            script_id=script_id,
            total_duration=total_duration,
            beats=beats,
            niche=niche,
            tier=tier,
        )

    @classmethod
    def _split_sentence_into_beats(
        cls,
        sentence_index: int,
        sentence_id: str,
        sentence_text: str,
        sentence_words: list[WordTiming],
        sentence_start: float,
        sentence_end: float,
        meta: dict[str, Any],
        start_beat_idx: int,
        niche: str,
        tier: str,
    ) -> list[Beat]:
        """Splits one sentence into 1.8s - 4.0s idea beats."""
        total_dur = max(0.5, sentence_end - sentence_start)
        v_intent = meta.get("visual_intent", {}) if isinstance(meta, dict) else {}
        main_subject = v_intent.get("main_subject", "")
        raw_queries = v_intent.get("queries", [])
        setting = v_intent.get("setting", "")
        action = v_intent.get("action_or_state", "")

        # Target 1.8s to 3.8s per beat
        target_max_dur = 3.6
        num_beats = max(1, int(round(total_dur / 2.6)))
        if total_dur <= target_max_dur:
            num_beats = 1

        beats: list[Beat] = []

        if not sentence_words and num_beats > 1:
            words = sentence_text.split()
            if words:
                dur_per_word = total_dur / len(words)
                sentence_words = [
                    WordTiming(
                        word=w,
                        start=round(sentence_start + i * dur_per_word, 3),
                        end=round(sentence_start + (i + 1) * dur_per_word, 3),
                    )
                    for i, w in enumerate(words)
                ]

        if num_beats == 1 or not sentence_words:
            # Single unified beat
            entities = cls.extract_entities(sentence_text)
            b_type = cls.classify_beat_type(sentence_text, entities)
            sens, reason = cls.check_sensitivity(sentence_text, entities, tier=tier)
            queries = cls.generate_query_variants(
                phrase=sentence_text,
                main_subject=main_subject,
                entities=entities,
                b_type=b_type,
                raw_queries=raw_queries,
                niche=niche,
            )

            v_desc = f"{entities[0] if entities else main_subject} {action} {setting}".strip()
            if not v_desc:
                v_desc = sentence_text[:60]

            beats.append(
                Beat(
                    beat_id=f"B{sentence_index + 1}_1",
                    beat_index=start_beat_idx,
                    sentence_id=sentence_id,
                    sentence_index=sentence_index,
                    spoken_text=sentence_text,
                    caption_text=sentence_text,
                    start_time=round(sentence_start, 3),
                    end_time=round(sentence_end, 3),
                    duration=round(total_dur, 3),
                    visual_intent=v_desc,
                    entities=entities,
                    beat_type=b_type,
                    sensitivity=sens,
                    sensitivity_reason=reason,
                    search_queries=queries,
                    is_specific_event=bool(sens or "20" in sentence_text),
                )
            )
            return beats

        # Multi-beat split based on clause boundaries or word timestamps
        conjunctions = {"and", "but", "while", "where", "because", "which", "when", "although", "meaning"}
        cur_words: list[WordTiming] = []
        beat_num = 1
        beat_target_dur = total_dur / max(1, num_beats)

        for idx, wt in enumerate(sentence_words):
            cur_words.append(wt)
            dur = cur_words[-1].end - cur_words[0].start
            is_last = idx == len(sentence_words) - 1

            has_punct = bool(re.search(r"[,;:.!?—]$", wt.word))
            has_conj = wt.word.lower() in conjunctions and len(cur_words) >= 3
            reached_target = dur >= (beat_target_dur - 0.3)

            # Avoid leaving an orphan tail < 1.5s
            remaining_dur = sentence_end - cur_words[-1].end
            will_leave_tiny_tail = not is_last and (0.0 < remaining_dur < 1.5)

            should_split = (reached_target and (has_punct or has_conj or dur >= beat_target_dur) and not will_leave_tiny_tail) or is_last

            if should_split and cur_words:
                b_start = cur_words[0].start
                b_end = cur_words[-1].end
                phrase = " ".join(w.word for w in cur_words)

                # If this is an orphan trailing fragment < 1.5s and we already have beats in this sentence, merge it!
                if (b_end - b_start) < 1.5 and beats and (beats[-1].sentence_index == sentence_index):
                    prev = beats[-1]
                    prev.spoken_text = f"{prev.spoken_text} {phrase}".strip()
                    prev.caption_text = prev.spoken_text
                    prev.end_time = round(b_end, 3)
                    prev.duration = round(prev.end_time - prev.start_time, 3)
                    prev.entities = cls.extract_entities(prev.spoken_text)
                    cur_words = []
                    continue

                entities = cls.extract_entities(phrase)
                b_type = cls.classify_beat_type(phrase, entities)
                sens, reason = cls.check_sensitivity(phrase, entities, tier=tier)
                queries = cls.generate_query_variants(
                    phrase=phrase,
                    main_subject=main_subject,
                    entities=entities,
                    b_type=b_type,
                    raw_queries=raw_queries,
                    niche=niche,
                )

                v_desc = f"{entities[0] if entities else main_subject} {action}".strip() or phrase[:50]

                beats.append(
                    Beat(
                        beat_id=f"B{sentence_index + 1}_{beat_num}",
                        beat_index=start_beat_idx + beat_num - 1,
                        sentence_id=sentence_id,
                        sentence_index=sentence_index,
                        spoken_text=phrase,
                        caption_text=phrase,
                        start_time=round(b_start, 3),
                        end_time=round(b_end, 3),
                        duration=round(b_end - b_start, 3),
                        visual_intent=v_desc,
                        entities=entities,
                        beat_type=b_type,
                        sensitivity=sens,
                        sensitivity_reason=reason,
                        search_queries=queries,
                        is_specific_event=bool(sens or "20" in phrase),
                    )
                )

                cur_words = []
                beat_num += 1

        return beats

    @classmethod
    def extract_entities(cls, text: str) -> list[str]:
        """Extracts named entities, numbers, percentages, currency, and concrete nouns."""
        entities: list[str] = []

        # 1. Currency & Numbers (e.g. $130 million, 6 billion tons, 45%)
        num_patterns = [
            r"\$[\d,]+(?:\.\d+)?\s*(?:billion|million|trillion|k|m|b)?(?!\w)",
            r"\b\d+(?:,\d+)*(?:\.\d+)?\s*(?:billion|million|trillion|tons|miles|kilometers|degrees|percent|%)(?!\w)",
            r"\b\d+(?:,\d+)*\b",
        ]
        for pat in num_patterns:
            for match in re.finditer(pat, text, flags=re.IGNORECASE):
                entities.append(match.group(0).strip())

        # 2. Capitalized Multi-Word Entities (Nvidia Blackwell, Great Pyramids, SEC EDGAR, White House)
        cap_multi = re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b", text)
        entities.extend(cap_multi)

        # 3. Key Capitalized Acronyms & Orgs (SEC, DOJ, NASA, TSMC, AI, GPU, UK, EU)
        acronyms = re.findall(r"\b[A-Z]{2,}\b", text)
        for a in acronyms:
            if a not in {"THE", "AND", "FOR", "WITH", "BUT"}:
                entities.append(a)

        # 4. Known Technical & Industry Terms
        domain_terms = [
            "nvidia", "deepseek", "blackwell", "semiconductor", "wafer", "starship",
            "supercomputer", "telescope", "microchip", "pyramid", "neutron star",
            "galaxy", "hubble", "webb", "mars", "saturn", "orbit", "sec"
        ]
        t_lower = text.lower()
        for term in domain_terms:
            if re.search(rf"\b{term}\b", t_lower):
                entities.append(term.title())

        # Deduplicate while preserving order
        unique: list[str] = []
        for e in entities:
            if e not in unique and len(e) > 1:
                unique.append(e)

        return unique

    @classmethod
    def classify_beat_type(cls, text: str, entities: list[str]) -> BeatType:
        """Classifies the beat into one of the 9 required semantic categories."""
        t_lower = text.lower()

        # 1. Number or Stat
        if any(re.search(r"\d", e) or "%" in e or "$" in e for e in entities):
            return BeatType.NUMBER_OR_STAT

        # 2. Comparison
        if any(w in t_lower for w in cls.COMPARISON_WORDS):
            return BeatType.COMPARISON

        # 3. Timeline
        if any(w in t_lower for w in cls.TIMELINE_WORDS):
            return BeatType.TIMELINE

        # 4. Quote
        if any(w in t_lower for w in cls.QUOTE_WORDS) or '"' in text:
            return BeatType.QUOTE

        # 5. Place
        places = {"taiwan", "washington", "giza", "mars", "earth", "desert", "orbit", "china", "london", "silicon valley"}
        if any(p in t_lower for p in places):
            return BeatType.PLACE

        # 6. Person or Org
        orgs = {"sec", "doj", "white house", "nvidia", "deepseek", "openai", "nasa", "tsmc", "microsoft", "apple", "google"}
        if any(o in t_lower for o in orgs):
            return BeatType.PERSON_OR_ORG

        # 7. Process
        process_verbs = {"manufacture", "fabricated", "slice through", "rotates", "accelerate", "transforms", "transfers", "processing"}
        if any(v in t_lower for v in process_verbs):
            return BeatType.PROCESS

        # 8. Concrete Object
        objects = {"chip", "wafer", "gpu", "rocket", "pyramid", "telescope", "satellite", "star", "planet"}
        if any(obj in t_lower for obj in objects):
            return BeatType.CONCRETE_OBJECT

        return BeatType.ABSTRACT_CONCEPT

    @classmethod
    def check_sensitivity(cls, text: str, entities: list[str], tier: str = "tier_a") -> tuple[bool, str]:
        """Detects whether beat names a real person, crime, lawsuit, fraud, or disaster."""
        t_lower = text.lower()

        if tier == "tier_b":
            return True, "Tier B Sensitive News topic (strict factual & neutral rendering)"

        # Check sensitive keywords
        for kw in cls.SENSITIVE_KEYWORDS:
            if re.search(rf"\b{kw}\b", t_lower):
                return True, f"Contains sensitive keyword: '{kw}'"

        # Check real public figures
        figures = {"trump", "biden", "jensen huang", "lutnick", "musk", "zuckerberg", "altman"}
        for f in figures:
            if f in t_lower:
                return True, f"Names public figure: '{f.title()}'"

        return False, ""

    @classmethod
    def generate_query_variants(
        cls,
        phrase: str,
        main_subject: str,
        entities: list[str],
        b_type: BeatType,
        raw_queries: list[str],
        niche: str,
    ) -> list[str]:
        """Generates 3 to 6 query variants (specific, broader, synonyms, context)."""
        variants: list[str] = []
        top_entity = entities[0] if entities else main_subject

        # Clean words from phrase
        clean_words = [w for w in re.sub(r"[^\w\s]", "", phrase).split() if len(w) > 3]

        # Variant 1: Highly specific entity + context
        if top_entity:
            variants.append(f"{top_entity} {' '.join(clean_words[:2])}".strip())

        # Variant 2: Domain raw query if present
        if raw_queries:
            for q in raw_queries[:2]:
                if q not in variants:
                    variants.append(q)

        # Variant 3: Beat type specific syntax
        if b_type == BeatType.NUMBER_OR_STAT:
            variants.append(f"{top_entity} data chart")
            variants.append(f"{top_entity} statistics graph")
        elif b_type == BeatType.PLACE:
            variants.append(f"{top_entity} landscape high quality")
            variants.append(f"{top_entity} satellite view")
        elif b_type == BeatType.CONCRETE_OBJECT:
            variants.append(f"{top_entity} technology close up")
            variants.append(f"{top_entity} laboratory cleanroom")
        elif b_type == BeatType.PERSON_OR_ORG:
            variants.append(f"{top_entity} headquarters modern building")
            variants.append(f"{top_entity} corporate office")
        else:
            variants.append(f"{top_entity} high resolution footage")

        # Deduplicate while preserving order
        unique: list[str] = []
        for v in variants:
            v_clean = " ".join(v.split()).lower()
            if v_clean and v_clean not in unique:
                unique.append(v_clean)

        return unique[:6]
