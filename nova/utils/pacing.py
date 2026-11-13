"""Unified Speaking Pace & Words-Per-Minute Calculation Engine for Nova Autopilot v6.0."""

from __future__ import annotations

import re
from typing import Union


def count_words(text: str) -> int:
    """Counts spoken words accurately, treating hyphenated compounds as distinct words if spoken."""
    if not text:
        return 0
    # Clean tags and brackets
    cleaned = re.sub(r"\{[^}]+\}", " ", text)
    cleaned = re.sub(r"\[[^\]]+\]", " ", cleaned)
    tokens = [w for w in cleaned.strip().split() if w]
    return len(tokens)


def compute_wpm(text_or_words: Union[str, list[str]], duration_seconds: float) -> float:
    """Calculates words per minute using the single unified standard definition across TTS and Quality Gate.

    WPM = (Total Spoken Words / Audio Duration Seconds) * 60.0
    """
    if duration_seconds <= 0.05:
        return 0.0

    if isinstance(text_or_words, str):
        total_words = count_words(text_or_words)
    else:
        total_words = sum(count_words(t) for t in text_or_words if t)

    return round((total_words / duration_seconds) * 60.0, 1)
