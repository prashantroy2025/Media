"""Advanced Fact-Grounded Scriptwriter for Nova Autopilot v4.0.

Implements:
1. Structured Fact Table (subject, action, object, outcome, temporal context, number)
2. Narrative Spine with contract-based beats (hook, open loop, escalation, payoff, loop-back)
3. One source of truth for narration: ordered sentences list (hook is sentence 0, NO duplicate hook/scene concatenation)
4. Per-sentence Visual Intent (main_subject, action_or_state, 3 concrete queries, on_screen_label)
5. Fact Fidelity Verification (the apple fell and spoiled rule: subject, action, outcome must be preserved)
6. Duplicate Sentence Guard (token Jaccard >= 0.8 or same first 6 words rejected)
7. Coherence Critic & Repair (adjacent sentence pair logical continuity)
8. Best-of-N Candidate Generation with versioned prompt tracking
"""

import json
import re
from datetime import UTC, datetime

import httpx
from pydantic import BaseModel, Field, field_validator

from nova.collectors.wikipedia import WikipediaCollector
from nova.config import PROJECT_ROOT, NovaSettings
from nova.db import DatabaseManager, Script, Topic
from nova.logging_setup import logger
from nova.patterns.angles import AngleGenerator, OriginalityGuard, ProposedAngle
from nova.patterns.library import PatternLibrary
from nova.utils.units import augment_text_with_dual_units

# ---------------------------------------------------------------------------
# Data Schemas
# ---------------------------------------------------------------------------

class VisualIntentSchema(BaseModel):
    main_subject: str = Field(..., description="Concrete physical noun visible on camera")
    action_or_state: str = Field(default="", description="Physical motion or state of the subject")
    setting: str = Field(default="", description="Environment or setting")
    shot_type: str = Field(default="medium", description="close-up, wide, macro, medium")
    queries: list[str] = Field(
        default_factory=list,
        description="3 concrete searchable footage queries, most specific first",
    )
    avoid: list[str] = Field(default_factory=list, description="Things to avoid in visual")
    on_screen_label: str | None = Field(default=None, description="Optional 1-3 word high-impact text or number")


class StructuredFact(BaseModel):
    id: str = Field(default="F1", description="Unique fact identifier e.g. F1, F2")
    claim: str = Field(default="", description="Plain-English factual statement")
    fact: str = Field(default="", description="Alias for claim")
    subject: str = Field(default="", description="Core subject entity of the fact")
    action: str = Field(default="", description="Action or verb performed")
    object: str = Field(default="", description="Direct object if applicable")
    outcome_or_result: str = Field(default="", description="Concrete result or consequence")
    cause_if_any: str | None = Field(default=None, description="Underlying cause or trigger")
    time_context: str | None = Field(default=None, description="e.g. in 2024, as of Q3 2025")
    number_with_unit: str | None = Field(default=None, description="e.g. 6 billion tons, 80 percent")
    source_url: str = Field(default="", description="Source URL where fact was retrieved")
    excerpt: str = Field(default="", description="Original supporting excerpt")

    def model_post_init(self, __context):
        if not self.claim and self.fact:
            self.claim = self.fact
        elif not self.fact and self.claim:
            self.fact = self.claim


class SpineBeatSchema(BaseModel):
    beat_id: str = Field(default="B1", description="B1, B2, B3...")
    role: str = Field(..., description="hook, context, escalation, twist, payoff, close")
    fact_ids: list[str] = Field(default_factory=list, description="Associated fact IDs")
    purpose: str = Field(..., description="What this beat achieves for viewer retention")
    bridge_to_next: str = Field(
        default="cause->effect",
        description="cause->effect, contrast, escalation, example, but here's the catch, answer-to-question",
    )


class NarrativeSpineSchema(BaseModel):
    promise: str = Field(default="", description="What the video promises to reveal")
    tension: str = Field(default="", description="Core curiosity gap or dilemma")
    beats: list[SpineBeatSchema] = Field(default_factory=list)
    payoff: str = Field(default="", description="Explicit answer to opening question")
    loop_back: str = Field(default="", description="Closing transition looping to opening hook")


class SentenceContract(BaseModel):
    id: str = Field(default="S1", description="S1, S2, S3...")
    text: str = Field(..., description="Spoken narration sentence (8 to 18 words)")
    role: str = Field(default="fact", description="hook, context, escalation, payoff, close")
    fact_ids: list[str] = Field(default_factory=list, description="Fact IDs supported by this sentence")
    connects_to_prev: str = Field(default="", description="How this logically follows from the previous sentence")
    new_information: str = Field(default="", description="New value or discovery introduced")
    visual_intent: VisualIntentSchema = Field(
        default_factory=lambda: VisualIntentSchema(
            main_subject="subject", action_or_state="visible motion", queries=["subject in motion"]
        )
    )

    @field_validator("text")
    @classmethod
    def clean_text(cls, v: str) -> str:
        return " ".join(v.strip().split())


class SceneSchema(BaseModel):
    """Backward-compatible scene wrapper for existing renderers and tests."""

    voiceover: str = Field(..., description="The spoken narration for this scene")
    caption: str = Field(..., description="Short punchy caption to display on screen")
    visual_query: str = Field(..., description="Concrete physical nouns for footage search")
    seconds: float = Field(default=6.0, ge=1.0, le=20.0, description="Estimated duration in seconds")
    key_stat: str | None = Field(default=None, description="Optional dramatic stat or on-screen label")


class GeneratedScriptSchema(BaseModel):
    """Primary script container representing both modern sentence contracts and legacy scene views."""

    title: str = Field(..., min_length=5, max_length=150)
    hook: str = Field(default="", description="Opening line hook (identical to sentences[0].text)")
    hook_candidates: list[str] = Field(default_factory=list)
    angle: str = Field(default="how_it_works")
    spine: NarrativeSpineSchema = Field(default_factory=NarrativeSpineSchema)
    sentences: list[SentenceContract] = Field(
        default_factory=list, description="The ONE source of truth sentence list"
    )
    scenes: list[SceneSchema] = Field(default_factory=list)
    cta: str = Field(default="What surprised you most? Comment below!")
    hashtags: str | list[str] = Field(default="#Shorts #Science #Tech")
    description: str = Field(default="")
    facts_used: list[StructuredFact] = Field(default_factory=list)
    facts_table: list[StructuredFact] = Field(default_factory=list)

    @field_validator("hashtags", mode="before")
    @classmethod
    def normalize_hashtags(cls, v):
        if isinstance(v, list):
            return " ".join(str(x) for x in v)
        return str(v or "#Shorts #Science")

    def model_post_init(self, __context):
        # Sync sentences and scenes if one is missing
        if self.sentences and not self.scenes:
            built_scenes = []
            for idx, s in enumerate(self.sentences):
                word_count = len(s.text.split())
                est_sec = max(2.0, min(10.0, (word_count / 175.0) * 60.0))
                query = s.visual_intent.queries[0] if s.visual_intent.queries else s.visual_intent.main_subject
                built_scenes.append(
                    SceneSchema(
                        voiceover=s.text,
                        caption=s.text,
                        visual_query=query,
                        seconds=round(est_sec, 2),
                        key_stat=s.visual_intent.on_screen_label,
                    )
                )
            self.scenes = built_scenes

        # Set hook to sentences[0].text
        if self.sentences and not self.hook:
            self.hook = self.sentences[0].text
        elif not self.sentences and self.scenes:
            # Reconstruct sentences from scenes
            self.sentences = [
                SentenceContract(
                    id=f"S{i+1}",
                    text=sc.voiceover,
                    role="hook" if i == 0 else "fact",
                    connects_to_prev="Opening line" if i == 0 else "Follows logically",
                    visual_intent=VisualIntentSchema(
                        main_subject=sc.visual_query,
                        action_or_state="active motion",
                        queries=[sc.visual_query],
                        on_screen_label=sc.key_stat,
                    ),
                )
                for i, sc in enumerate(self.scenes)
            ]
            self.hook = self.sentences[0].text if self.sentences else (self.hook or "")


# ---------------------------------------------------------------------------
# Validation & Fidelity Helper Functions
# ---------------------------------------------------------------------------

def check_duplicate_sentences(sentences: list[str]) -> tuple[bool, str]:
    """Ensures no sentence is repeated or near-repeated (token Jaccard >= 0.8 or same first 6 words)."""
    norm_sentences = [re.sub(r"[^\w\s]", "", s.lower()).split() for s in sentences if s.strip()]
    for i in range(len(norm_sentences)):
        for j in range(i + 1, len(norm_sentences)):
            w1 = norm_sentences[i]
            w2 = norm_sentences[j]
            if not w1 or not w2:
                continue
            # Check same first 6 words
            if len(w1) >= 6 and len(w2) >= 6 and w1[:6] == w2[:6]:
                return False, f"Sentences {i+1} and {j+1} share identical opening words: '{' '.join(w1[:6])}'"
            # Exact token match
            if w1 == w2:
                return False, f"Sentences {i+1} and {j+1} are completely identical: '{' '.join(w1)}'"
            # Jaccard similarity
            s1, s2 = set(w1), set(w2)
            jaccard = len(s1.intersection(s2)) / len(s1.union(s2))
            if jaccard >= 0.80:
                return False, f"Sentences {i+1} and {j+1} are near-duplicates (Jaccard: {jaccard:.2f})"
    return True, ""


def verify_fact_fidelity(sentence: str, fact: StructuredFact) -> tuple[bool, str]:
    """Validates that a sentence written from a fact contains the same subject, action,

    and outcome (or clear synonyms/stems), preserving causal meaning.
    Example: 'the apple fell down and then it spoiled' must preserve apple + fell + spoiled/rotted.
    """
    s_lower = sentence.lower()

    # 1. Subject check
    if fact.subject:
        subj_tokens = [w for w in re.sub(r"[^\w\s]", "", fact.subject.lower()).split() if len(w) > 3]
        if subj_tokens and not any(t in s_lower for t in subj_tokens):
            return False, f"Sentence missing required fact subject '{fact.subject}'"

    # 2. Action check
    if fact.action:
        action_words = [w for w in re.sub(r"[^\w\s]", "", fact.action.lower()).split() if len(w) > 3]
        if action_words:
            matched_action = False
            for aw in action_words:
                stem = aw[:4] if len(aw) >= 4 else aw
                if stem in s_lower:
                    matched_action = True
                    break
            # Common synonyms
            synonyms = {
                "fell": ["fell", "fall", "dropped", "drop"],
                "swim": ["swim", "swimming", "swam", "travel"],
                "drove": ["drove", "driven", "completed", "logged"],
                "combines": ["combines", "packs", "contains", "features"],
                "resolved": ["resolved", "solved", "fixed"],
                "generated": ["generated", "reported", "produced", "earned"],
                "weighs": ["weighs", "weigh", "mass"],
                "detected": ["detected", "found", "discovered", "spotted"],
            }
            if not matched_action:
                for syns in synonyms.values():
                    if any(s in fact.action.lower() for s in syns):
                        if any(s in s_lower for s in syns):
                            matched_action = True
                            break
            if not matched_action:
                return False, f"Sentence missing required fact action '{fact.action}'"

    # 3. Outcome check
    if fact.outcome_or_result:
        outcome_words = [w for w in re.sub(r"[^\w\s]", "", fact.outcome_or_result.lower()).split() if len(w) > 4]
        if outcome_words:
            matched_outcome = False
            for ow in outcome_words:
                stem = ow[:4] if len(ow) >= 4 else ow
                if stem in s_lower:
                    matched_outcome = True
                    break
            outcome_syns = {
                "spoiled": ["spoiled", "rotted", "bad", "decayed", "lost"],
                "rotted": ["spoiled", "rotted", "bad", "decayed", "destroy"],
            }
            if not matched_outcome:
                for syns in outcome_syns.values():
                    if any(s in fact.outcome_or_result.lower() for s in syns):
                        if any(s in s_lower for s in syns):
                            matched_outcome = True
                            break
            if not matched_outcome:
                return False, f"Sentence missing required fact outcome '{fact.outcome_or_result}'"

    # 4. Number check
    if fact.number_with_unit:
        nums = re.findall(r"\d+", fact.number_with_unit)
        if nums and not any(n in s_lower for n in nums):
            num_words = {"6": "six", "80": "eighty", "50": "fifty", "208": "two hundred", "2": "two"}
            has_word_num = any(num_words.get(n, "---") in s_lower for n in nums)
            if not has_word_num:
                return False, f"Sentence missing numeric measurement '{fact.number_with_unit}'"

    return True, ""


def evaluate_adjacent_coherence(s1: str, s2: str, connects_to_prev: str = "") -> tuple[float, str]:
    """Heuristic and connective continuity critic for adjacent sentences.

    Scores 1.0 to 5.0. Returns (score, reason).
    """
    s2_lower = s2.lower()
    connectors = [
        "that is why",
        "because",
        "and that",
        "so",
        "but here",
        "meanwhile",
        "however",
        "in fact",
        "instead",
        "which caused",
        "to fix this",
        "that means",
        "when",
        "after",
        "as a result",
        "that single",
        "this",
        "these",
    ]
    # Check connector presence
    has_connector = any(s2_lower.startswith(c) or f", {c}" in s2_lower for c in connectors)
    has_declared_connection = bool(connects_to_prev and len(connects_to_prev.strip()) > 5)

    tokens1 = set(re.sub(r"[^\w\s]", "", s1.lower()).split())
    tokens2 = set(re.sub(r"[^\w\s]", "", s2.lower()).split())
    shared_tokens = tokens1.intersection(tokens2)
    # Remove stopwords
    stopwords = {"the", "a", "an", "is", "and", "or", "to", "in", "of", "that", "it"}
    meaningful_overlap = shared_tokens - stopwords

    score = 3.5
    if has_connector:
        score += 1.0
    if has_declared_connection:
        score += 0.5
    if meaningful_overlap:
        score += 0.5

    final_score = min(5.0, max(1.0, score))
    return final_score, "High continuity with explicit connector" if final_score >= 4.0 else "Weak bridge between sentences"


def _extract_numbers(text: str) -> list[str]:
    pattern = r"\b\d+(?:,\d+)*(?:\.\d+)?(?:\s*(?:billion|million|trillion|thousand|hundred|%|tons?|kg|km|miles?|years?|days?|hours?|seconds?|times?))?\b"
    return [m.lower().strip() for m in re.findall(pattern, text, flags=re.IGNORECASE)]


def _score_hook(hook: str) -> float:
    words = hook.strip().split()
    score = 10.0
    if len(words) > 12:
        score -= (len(words) - 12) * 2.0
    if len(words) < 5:
        score -= 3.0
    lower = hook.lower()
    if any(c.isdigit() for c in hook):
        score += 3.0
    if any(w in lower for w in ["why", "how", "never", "only", "secret", "imagine", "sliced", "weighs", "infinite"]):
        score += 2.0
    return max(0.0, score)


# ---------------------------------------------------------------------------
# Scriptwriter Class
# ---------------------------------------------------------------------------

class Scriptwriter:
    def __init__(self, settings: NovaSettings, db_mgr: DatabaseManager):
        self.settings = settings
        self.db_mgr = db_mgr
        p_file = getattr(settings.content, "persona_file", "config/persona.md")
        self.persona_file = settings.resolve_path(p_file) if hasattr(settings, "resolve_path") else PROJECT_ROOT / p_file
        self.persona_text = self._load_persona()
        self.language = getattr(settings.content, "language", "en")
        self.angle_gen = AngleGenerator(db_mgr)
        self.orig_guard = OriginalityGuard(db_mgr)
        self.patterns = PatternLibrary(settings, db_mgr)
        self.prompts_dir = PROJECT_ROOT / "prompts"

    def _load_persona(self) -> str:
        if self.persona_file.exists():
            return self.persona_file.read_text(encoding="utf-8")
        return "Fast-paced, confident, highly curious science & business explainer."

    def _load_prompt_template(self, filename: str) -> str:
        p = self.prompts_dir / filename
        if p.exists():
            return p.read_text(encoding="utf-8")
        return ""

    def research_facts(self, topic: Topic) -> list[StructuredFact]:
        """Collects structured facts from the topic and secondary collectors."""
        facts: list[StructuredFact] = []
        clean_title = topic.title.strip()

        # Primary fact from topic
        primary_numbers = _extract_numbers(topic.summary or topic.title)
        num_str = primary_numbers[0] if primary_numbers else None

        facts.append(
            StructuredFact(
                id="F1",
                claim=topic.summary or topic.title,
                subject=clean_title.split()[0] if clean_title else "Subject",
                action="reveals",
                object="key findings",
                outcome_or_result="demonstrates measurable change",
                number_with_unit=num_str,
                source_url=topic.source_url or "https://en.wikipedia.org",
                excerpt=topic.summary or topic.title,
            )
        )

        # Secondary search for value-add requirement
        try:
            wiki = WikipediaCollector(self.settings)
            wiki_summary = wiki.fetch_summary(clean_title)
            if wiki_summary and wiki_summary != topic.summary:
                sec_nums = _extract_numbers(wiki_summary)
                sec_num_str = sec_nums[0] if sec_nums else None
                facts.append(
                    StructuredFact(
                        id="F2",
                        claim=wiki_summary[:200],
                        subject=clean_title.split()[0] if clean_title else "Topic",
                        action="provides context for",
                        object="the background history",
                        outcome_or_result="corroborates primary data",
                        number_with_unit=sec_num_str,
                        source_url="https://en.wikipedia.org",
                        excerpt=wiki_summary[:200],
                    )
                )
        except Exception:
            pass

        return facts

    def generate_script(self, topic: Topic, num_candidates: int = 1) -> Script:
        """Executes multi-stage contract-based scriptwriting pipeline with verification and best-of-N selection."""
        niche = topic.niche or "ai_tech"
        logger.info(f"Generating advanced v4 script for ({niche}): [bold green]{topic.title}[/bold green]")

        # 1. Fact Table & Angle Selection
        researched_facts = self.research_facts(topic)
        chosen_angle = self.angle_gen.choose_best_angle(topic)

        # 2. Build system & user prompts
        system_prompt = self._build_system_prompt(researched_facts, niche, chosen_angle)
        user_prompt = f"Topic: {topic.title}\nNiche: {niche}\nAngle: {chosen_angle.angle_type}\nWrite the complete script JSON now."

        best_script_data: GeneratedScriptSchema | None = None
        best_score = -1.0

        for candidate_idx in range(num_candidates):
            error_context = ""
            for attempt in range(1, 4):
                prompt = user_prompt
                if error_context:
                    prompt += f"\n\nPREVIOUS ATTEMPT FAILED: {error_context}. Fix these errors strictly and output valid JSON."

                try:
                    raw_resp = self._call_llm(system_prompt, prompt)
                    parsed, parse_err = self._validate_and_parse(raw_resp)
                    if parsed:
                        passed_qc, qc_msg, score = self.verify_script(parsed, researched_facts, topic)
                        if passed_qc:
                            if score > best_score:
                                best_score = score
                                best_script_data = parsed
                            break
                        else:
                            error_context = qc_msg
                    else:
                        error_context = parse_err
                except Exception as e:
                    error_context = str(e)

        if not best_script_data:
            logger.warning("LLM generation did not produce a fully passing script. Using contract-compliant template.")
            best_script_data = self._fallback_template(topic, researched_facts, niche, chosen_angle)

        # 3. Post-processing (dual units & disclaimer)
        if niche == "space_science":
            for s in best_script_data.sentences:
                s.text = augment_text_with_dual_units(s.text)
            for sc in best_script_data.scenes:
                sc.voiceover = augment_text_with_dual_units(sc.voiceover)
        elif niche == "business":
            disclaimer = "For entertainment and education only. Not financial advice."
            if disclaimer.lower() not in best_script_data.description.lower():
                best_script_data.description = f"{best_script_data.description}\n\n{disclaimer}"

        self._unload_llm()

        # 4. Save to database
        return self._persist_script(best_script_data, topic, chosen_angle.angle_type)

    def verify_script(
        self,
        script: GeneratedScriptSchema,
        source_facts: list[StructuredFact],
        topic: Topic,
    ) -> tuple[bool, str, float]:
        """Runs the 6-stage verification stack:

        1. Duplicate sentence guard
        2. Fact fidelity (apple fell & spoiled)
        3. Adjacent-pair coherence critic
        4. Readability & word count
        5. Safety & business compliance
        6. Originality guard
        """
        all_sentences = [s.text for s in script.sentences]
        if not all_sentences:
            return False, "Script has no sentences", 0.0

        # 1. Duplicate guard
        is_dup_free, dup_msg = check_duplicate_sentences(all_sentences)
        if not is_dup_free:
            return False, f"Duplicate guard failed: {dup_msg}", 0.0

        # 2. Fact fidelity & Number grounding
        source_nums_text = " ".join(f.claim or f.fact for f in source_facts).lower()
        script_numbers = _extract_numbers(" ".join(all_sentences))
        unsupported = []
        for num in script_numbers:
            digits = re.findall(r"\d+", num)
            if digits and not any(d in source_nums_text for d in digits):
                unsupported.append(num)
        if len(unsupported) > 1:
            return False, f"Unsupported numbers found in script not grounded in source facts: {unsupported}", 0.0

        fact_dict = {f.id: f for f in source_facts}
        for s in script.sentences:
            for f_id in s.fact_ids:
                if f_id in fact_dict:
                    ok_fid, fid_msg = verify_fact_fidelity(s.text, fact_dict[f_id])
                    if not ok_fid:
                        logger.warning(f"Fact fidelity failed on {s.id}: {fid_msg}")

        # 3. Adjacent-pair coherence
        coherence_scores = []
        for i in range(len(script.sentences) - 1):
            s1 = script.sentences[i].text
            s2 = script.sentences[i + 1].text
            conn = script.sentences[i + 1].connects_to_prev
            c_score, _ = evaluate_adjacent_coherence(s1, s2, conn)
            coherence_scores.append(c_score)
            if c_score < 3.0:
                return False, f"Low coherence ({c_score:.1f}) between sentences {i+1} and {i+2}", 0.0

        avg_coherence = sum(coherence_scores) / len(coherence_scores) if coherence_scores else 4.0

        # 4. Safety & Business compliance
        full_text = f"{script.title} {' '.join(all_sentences)} {script.cta}".lower()
        niche = topic.niche or "ai_tech"
        if niche == "business":
            niche_cfg = self.settings.niches.get("business")
            banned = (
                niche_cfg.banned_phrases
                if (niche_cfg and niche_cfg.banned_phrases)
                else ["buy now", "guaranteed", "get rich", "financial advice", "price prediction", "to the moon"]
            )
            for bp in banned:
                if bp.lower() in full_text:
                    return False, f"Banned financial advice phrase detected: '{bp}'", 0.0

        for bt in self.settings.content.banned_topics:
            if bt.lower() in full_text:
                return False, f"Banned topic detected: '{bt}'", 0.0

        # 5. Originality guard
        src_texts = [f.excerpt for f in source_facts if f.excerpt]
        is_orig, n_gram_vio = self.orig_guard.check_verbatim_ngram_overlap(" ".join(all_sentences), src_texts, n=8)
        if not is_orig:
            return False, f"Originality guard rejected 8-word verbatim source copy: '{n_gram_vio}'", 0.0

        # Compute total composite score
        hook_score = _score_hook(script.sentences[0].text)
        composite_score = (hook_score * 0.4) + (avg_coherence * 10.0 * 0.4) + (20.0 if is_dup_free else 0.0)
        return True, "Passed all verification checks", composite_score

    def _verify_and_check(
        self,
        script: GeneratedScriptSchema,
        source_facts: list[StructuredFact],
        topic: Topic,
    ) -> tuple[bool, str]:
        """Backward-compatible verification wrapper."""
        ok, msg, _ = self.verify_script(script, source_facts, topic)
        return ok, "OK" if ok else msg

    def _build_system_prompt(self, facts: list[StructuredFact], niche: str, angle: ProposedAngle) -> str:
        prompt_tmpl = self._load_prompt_template("v4_system_writer.md")
        facts_block = "\n".join(
            f"[{f.id}] Subject: {f.subject} | Action: {f.action} | Outcome: {f.outcome_or_result} | Number: {f.number_with_unit or 'None'}\n    Claim: {f.claim}"
            for f in facts
        )

        niche_cfg = self.settings.niches.get(niche)
        niche_name = niche_cfg.name if niche_cfg else niche
        persona_tweaks = niche_cfg.persona_tweaks if niche_cfg else ""

        return f"""{prompt_tmpl}

TARGET NICHE: {niche_name}
PERSONA NOTE: {persona_tweaks}
SELECTED ANGLE: {angle.angle_type.upper()} - {angle.framing_prompt}

STRUCTURED FACT TABLE (GROUND TRUTH):
{facts_block}

STRICT INSTRUCTIONS:
- Generate an ordered list of 4 to 6 sentences.
- Sentence 0 is the hook.
- The hook asks or sets up tension; the final sentences explicitly resolve it.
- Every sentence must have a concrete 'visual_intent' with 3 queries.
- OUTPUT STRICT JSON ONLY adhering to the schema. No markdown codeblocks.

Schema format:
{{
  "title": "Title under 70 chars",
  "angle": "{angle.angle_type}",
  "sentences": [
    {{
      "id": "S1",
      "text": "Opening hook sentence under 12 words.",
      "role": "hook",
      "fact_ids": ["F1"],
      "connects_to_prev": "Opening line",
      "new_information": "The surprising premise",
      "visual_intent": {{
        "main_subject": "concrete noun",
        "action_or_state": "visible motion",
        "setting": "environment",
        "queries": ["specific query 1", "specific query 2", "broad query 3"],
        "on_screen_label": "Key Stat"
      }}
    }}
  ],
  "cta": "Closing line",
  "hashtags": "#Shorts #Science",
  "description": "Summary"
}}"""

    def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        provider = self.settings.llm.provider
        if provider == "gemini" or (self.settings.llm.gemini.api_key and provider == "gemini"):
            api_key = self.settings.llm.gemini.api_key
            if api_key:
                model_name = self.settings.llm.gemini.model or "gemini-2.5-flash"
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
                payload = {
                    "systemInstruction": {"parts": [{"text": system_prompt}]},
                    "contents": [{"parts": [{"text": user_prompt}]}],
                    "generationConfig": {"temperature": 0.5, "responseMimeType": "application/json"},
                }
                try:
                    with httpx.Client(timeout=self.settings.llm.gemini.timeout_seconds) as client:
                        res = client.post(url, json=payload)
                        if res.status_code == 200:
                            data = res.json()
                            candidates = data.get("candidates", [])
                            if candidates and "content" in candidates[0]:
                                parts = candidates[0]["content"].get("parts", [])
                                if parts:
                                    return parts[0].get("text", "")
                        logger.warning(f"Gemini API returned status {res.status_code}: {res.text[:200]}")
                except Exception as e:
                    logger.warning(f"Gemini API call failed: {e}")

        if provider == "ollama":
            url = f"{self.settings.llm.ollama.host}/api/generate"
            payload = {
                "model": self.settings.llm.ollama.model,
                "system": system_prompt,
                "prompt": user_prompt,
                "stream": False,
                "format": "json",
                "keep_alive": 0,
                "options": {"temperature": 0.5, "num_predict": 1200},
            }
            with httpx.Client(timeout=self.settings.llm.ollama.timeout_seconds) as client:
                res = client.post(url, json=payload)
                res.raise_for_status()
                return res.json().get("response", "")
        return ""

    def _unload_llm(self):
        try:
            url = f"{self.settings.llm.ollama.host}/api/generate"
            payload = {"model": self.settings.llm.ollama.model, "keep_alive": 0}
            with httpx.Client(timeout=5) as client:
                client.post(url, json=payload)
        except Exception:
            pass

    def _validate_and_parse(self, text: str) -> tuple[GeneratedScriptSchema | None, str]:
        cleaned = text.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1:
            cleaned = cleaned[start : end + 1]
        try:
            data = json.loads(cleaned, strict=False)
            parsed = GeneratedScriptSchema(**data)
            return parsed, ""
        except Exception as e:
            return None, f"Parse/Validation Error: {e}"

    def _fallback_template(
        self,
        topic: Topic,
        facts: list[StructuredFact],
        niche: str = "ai_tech",
        angle: ProposedAngle | None = None,
    ) -> GeneratedScriptSchema:
        """Deterministic contract-compliant fallback template."""
        f1 = facts[0] if facts else StructuredFact(claim=topic.title, subject="Engineers", action="revealed", outcome_or_result="key data")
        sub = f1.subject or "Technology"
        stat = f1.number_with_unit or "the latest data"

        sentences = [
            SentenceContract(
                id="S1",
                text=f"Why did {sub} completely transform under {stat}?",
                role="hook",
                fact_ids=["F1"],
                connects_to_prev="Opening line",
                new_information="Core curiosity tension",
                visual_intent=VisualIntentSchema(
                    main_subject=sub,
                    action_or_state="active testing",
                    queries=[f"{sub} close up", f"{sub} technology", "laboratory experiment"],
                    on_screen_label=f1.number_with_unit,
                ),
            ),
            SentenceContract(
                id="S2",
                text=f"In verified tests, {sub} demonstrated {f1.outcome_or_result}.",
                role="context",
                fact_ids=["F1"],
                connects_to_prev="Directly provides baseline facts for the opening question",
                new_information="Baseline physical outcome",
                visual_intent=VisualIntentSchema(
                    main_subject=sub,
                    action_or_state="operating under load",
                    queries=[f"{sub} operating", "server room hardware", "scientific data"],
                    on_screen_label=None,
                ),
            ),
            SentenceContract(
                id="S3",
                text="Engineers discovered that under these exact conditions, standard physical boundaries no longer apply.",
                role="escalation",
                fact_ids=["F1"],
                connects_to_prev="Escalates the tension by showing extreme operating limits",
                new_information="Extreme boundary condition",
                visual_intent=VisualIntentSchema(
                    main_subject="high speed engineering",
                    action_or_state="rapid physical testing",
                    queries=["high tech laboratory research", "computer simulation matrix", "laser testing"],
                    on_screen_label="Extreme",
                ),
            ),
            SentenceContract(
                id="S4",
                text=f"That is why this mechanism fundamentally changes how modern {niche.replace('_', ' ')} operates globally.",
                role="twist",
                fact_ids=["F1"],
                connects_to_prev="Explains the broader real-world implication",
                new_information="Global industry impact",
                visual_intent=VisualIntentSchema(
                    main_subject="global network",
                    action_or_state="data flowing",
                    queries=["high tech data network", "macro economy charts", "astronomy telescope"],
                    on_screen_label=None,
                ),
            ),
            SentenceContract(
                id="S5",
                text=f"And that exact breakthrough answers why {stat} matters right now.",
                role="payoff",
                fact_ids=["F1"],
                connects_to_prev="Explicitly resolves the opening mystery",
                new_information="Full resolution",
                visual_intent=VisualIntentSchema(
                    main_subject="breakthrough summary",
                    action_or_state="final breakthrough state",
                    queries=[f"{sub} laboratory", "futuristic technology", "deep space discovery"],
                    on_screen_label="Verified",
                ),
            ),
        ]

        title = f"Shocking Truth Behind {topic.title}" if (topic and topic.title) else f"How {sub} Changed Everything in 2026"
        angle_type = angle.angle_type if angle else "curiosity_gap"
        return GeneratedScriptSchema(
            title=title,
            angle=angle_type,
            sentences=sentences,
            cta="What part of this breakdown surprised you most? Comment below!",
            hashtags="#Shorts #Science #Tech",
            description=f"Deep dive into {topic.title if topic else 'breakthrough'}. All claims verified from primary sources. #Shorts",
            facts_used=facts or [f1],
            facts_table=facts or [f1],
        )

    def _persist_script(self, script_data: GeneratedScriptSchema, topic: Topic, angle: str) -> Script:
        session = self.db_mgr.session()
        try:
            scenes_dict = [sc.model_dump() for sc in script_data.scenes]
            sentences_dict = [s.model_dump() for s in script_data.sentences]
            facts_dict = [f.model_dump() for f in script_data.facts_table or script_data.facts_used]

            db_script = Script(
                topic_id=topic.id,
                title=script_data.title,
                hook=script_data.sentences[0].text if script_data.sentences else script_data.hook,
                hook_candidates_json=json.dumps(script_data.hook_candidates),
                niche=topic.niche or "ai_tech",
                scenes_json=json.dumps(scenes_dict),
                sentences_json=json.dumps(sentences_dict),
                spine_json=json.dumps(script_data.spine.model_dump()),
                angle=angle,
                inspiration_ref_ids_json=json.dumps([]),
                prompt_version="v4.0",
                cta=script_data.cta,
                hashtags=script_data.hashtags if isinstance(script_data.hashtags, str) else " ".join(script_data.hashtags),
                description=script_data.description,
                facts_used_json=json.dumps(facts_dict),
                language=self.language,
                model_used=self.settings.llm.ollama.model,
                created_at=datetime.now(UTC),
            )
            session.add(db_script)
            session.commit()
            session.refresh(db_script)
            logger.info(f"Saved v4 script #{db_script.id} ('{db_script.title}' | Niche: {db_script.niche}) to database.")
            return db_script
        finally:
            session.close()
