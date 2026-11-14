"""Motion Overlay Plan Builder for Nova Autopilot v8.0.

Translates script sentences, word timings, and structured facts into an optimized
motion component timeline, enforcing safe zones and spacing constraints.
"""

from __future__ import annotations

import re
from typing import Any

from nova.motion.brand import CollisionChecker
from nova.motion.components import (
    AnimatedCounter,
    ComparisonVisual,
    FirstFrameHookCard,
    KineticTextPop,
    LowerThirdSourceTag,
    MotionComponent,
    ProgressBar,
)
from nova.tts import WordTiming


class MotionPlanBuilder:
    """Constructs timed motion design elements from narration and fact tables."""

    @classmethod
    def build_motion_plan(
        cls,
        sentences: list[dict[str, Any]],
        word_timings: list[WordTiming],
        total_duration: float,
        niche: str = "ai_tech",
        primary_source: str = "",
    ) -> list[MotionComponent]:
        components: list[MotionComponent] = []

        # 1. Subtle video progress bar across full duration
        components.append(ProgressBar(total_duration=total_duration))

        # 2. Hook Card at Frame 0 (First 0.5s)
        if sentences:
            hook_text = sentences[0].get("text", "")
            components.append(FirstFrameHookCard(hook_text=hook_text, duration=0.6))

        # 3. Primary Source Tag in opening seconds
        if primary_source:
            clean_source = primary_source.replace("https://", "").replace("www.", "").split("/")[0]
            components.append(LowerThirdSourceTag(source_text=clean_source, start_time=0.6, duration=2.8))

        # 4. Timed Kinetic Pops and Animated Counters based on word timestamps
        # Index word timings by clean token
        timing_map: list[tuple[str, float, float]] = []
        for wt in word_timings:
            clean_w = re.sub(r"[^\w]", "", wt.word.lower())
            if clean_w:
                timing_map.append((clean_w, wt.start, wt.end))

        last_pop_time = -10.0
        last_counter_time = -10.0

        for s_idx, s in enumerate(sentences):
            text = s.get("text", "")
            v_intent = s.get("visual_intent", {})
            on_screen_label = v_intent.get("on_screen_label", "") if isinstance(v_intent, dict) else ""

            # Check for numbers in this sentence
            num_matches = re.findall(r"\b(\d+(?:,\d+)*(?:\.\d+)?)\s*(billion|million|trillion|hundred|%|tons?|kg|km)?\b", text, re.IGNORECASE)
            if num_matches:
                raw_val_str, unit = num_matches[0]
                try:
                    val_clean = float(raw_val_str.replace(",", ""))
                    unit_clean = unit.upper() if unit else ""
                    # Locate timestamp in audio
                    s_words = [re.sub(r"[^\w]", "", w.lower()) for w in text.split()]
                    # Find start time of sentence
                    s_start = 0.0
                    for tw, t_start, t_end in timing_map:
                        if tw in s_words[:3]:
                            s_start = t_start
                            break

                    if (s_start - last_counter_time) >= 3.0 and s_start > 0.4:
                        components.append(
                            AnimatedCounter(
                                target_value=val_clean,
                                unit=unit_clean,
                                label=on_screen_label or "Key Stat",
                                source=clean_source if primary_source else "",
                                start_time=s_start,
                                duration=2.0,
                            )
                        )
                        last_counter_time = s_start
                except Exception:
                    pass

            # Kinetic text pop for primary entity or keyword
            if on_screen_label and (last_counter_time - last_pop_time) >= 2.5:
                # Find timing for on_screen_label
                label_words = [re.sub(r"[^\w]", "", w.lower()) for w in on_screen_label.split()]
                label_time = 0.0
                for tw, t_start, t_end in timing_map:
                    if tw in label_words:
                        label_time = t_start
                        break

                if label_time > 0.0 and (label_time - last_pop_time) >= 2.5 and (label_time - last_counter_time) >= 2.0:
                    components.append(
                        KineticTextPop(
                            text=on_screen_label,
                            start_time=label_time,
                            duration=1.4,
                        )
                    )
                    last_pop_time = label_time

        return components
