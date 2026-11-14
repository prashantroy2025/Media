"""Narration Text Normalizer and Pronunciation Harmonizer for Nova Autopilot v8.0.

Ensures that currency, numbers, years, percentages, units, acronyms, and versions
are converted into spoken word sequences, creating an exact 1:1 match between
synthesized speech audio and Whisper-aligned karaoke subtitles.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from nova.config import PROJECT_ROOT

PRONUNCIATION_FILE = PROJECT_ROOT / "config" / "pronunciations.yaml"


def load_pronunciations() -> dict[str, str]:
    if PRONUNCIATION_FILE.exists():
        try:
            data = yaml.safe_load(PRONUNCIATION_FILE.read_text(encoding="utf-8")) or {}
            return data.get("terms", {})
        except Exception:
            pass
    return {}


PRONUNCIATIONS = load_pronunciations()

# Basic number to word conversions
SMALL_NUMBERS = {
    0: "zero",
    1: "one",
    2: "two",
    3: "three",
    4: "four",
    5: "five",
    6: "six",
    7: "seven",
    8: "eight",
    9: "nine",
    10: "ten",
    11: "eleven",
    12: "twelve",
    13: "thirteen",
    14: "fourteen",
    15: "fifteen",
    16: "sixteen",
    17: "seventeen",
    18: "eighteen",
    19: "nineteen",
    20: "twenty",
    30: "thirty",
    40: "forty",
    50: "fifty",
    60: "sixty",
    70: "seventy",
    80: "eighty",
    90: "ninety",
}


def number_to_words(n: int) -> str:
    """Converts an integer (up to 999,999) into English words."""
    if n in SMALL_NUMBERS:
        return SMALL_NUMBERS[n]
    if n < 100:
        tens = (n // 10) * 10
        ones = n % 10
        return f"{SMALL_NUMBERS[tens]}-{SMALL_NUMBERS[ones]}"
    if n < 1000:
        hundreds = n // 100
        rem = n % 100
        if rem == 0:
            return f"{SMALL_NUMBERS[hundreds]} hundred"
        return f"{SMALL_NUMBERS[hundreds]} hundred {number_to_words(rem)}"
    if n < 1000000:
        thousands = n // 1000
        rem = n % 1000
        if rem == 0:
            return f"{number_to_words(thousands)} thousand"
        return f"{number_to_words(thousands)} thousand {number_to_words(rem)}"
    return str(n)


def normalize_year(year_str: str) -> str:
    """Converts 4-digit years like 2027 -> twenty twenty-seven, 1998 -> nineteen ninety-eight."""
    try:
        y = int(year_str)
        if 2000 <= y <= 2009:
            return f"two thousand {SMALL_NUMBERS.get(y - 2000, str(y - 2000))}"
        if 2010 <= y <= 2099:
            c = y // 100  # 20
            d = y % 100  # 27
            return f"{SMALL_NUMBERS[c]} {number_to_words(d)}"
        if 1900 <= y <= 1999:
            c = y // 100  # 19
            d = y % 100  # 98
            return f"{SMALL_NUMBERS[c]} {number_to_words(d)}"
    except Exception:
        pass
    return year_str


class NarrationNormalizer:
    """Converts technical and numeric text into fluent spoken English."""

    @classmethod
    def normalize(cls, text: str) -> str:
        res = text

        # 1. Apply dictionary pronunciation respellings first for exact term matches
        for term, spoken in PRONUNCIATIONS.items():
            pattern = r"\b" + re.escape(term) + r"\b"
            res = re.sub(pattern, spoken, res)

        # 2. Currency: $130 million -> one hundred thirty million dollars, $208 billion -> two hundred eight billion dollars
        def _curr_repl(match):
            val_str = match.group(1).replace(",", "")
            unit = match.group(2) or ""
            try:
                num = int(float(val_str))
                words = number_to_words(num)
                if unit:
                    return f"{words} {unit} dollars"
                return f"{words} dollars"
            except Exception:
                return match.group(0)

        res = re.sub(
            r"\$(\d+(?:,\d+)*(?:\.\d+)?)\s*(billion|million|trillion|thousand)?",
            _curr_repl,
            res,
            flags=re.IGNORECASE,
        )

        # 3. Percentages: 80% -> eighty percent, 90.5% -> ninety point five percent
        def _pct_repl(match):
            num_str = match.group(1).replace(",", "")
            try:
                if "." in num_str:
                    whole, dec = num_str.split(".", 1)
                    w_whole = number_to_words(int(whole))
                    w_dec = " ".join(SMALL_NUMBERS.get(int(d), d) for d in dec)
                    return f"{w_whole} point {w_dec} percent"
                return f"{number_to_words(int(num_str))} percent"
            except Exception:
                return match.group(0)

        res = re.sub(r"\b(\d+(?:,\d+)*(?:\.\d+)?)\s*%", _pct_repl, res)

        # 4. Standalone 4-digit Years (1900-2099)
        def _year_repl(match):
            return normalize_year(match.group(1))

        res = re.sub(r"\b(19\d\d|20\d\d)\b", _year_repl, res)

        # 5. Units & Dimensions
        res = re.sub(r"\b(\d+)\s*km\b", r"\1 kilometers", res, flags=re.I)
        res = re.sub(r"\b(\d+)\s*kg\b", r"\1 kilograms", res, flags=re.I)

        return res
