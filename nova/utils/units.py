"""Unit conversion utilities for Nova Autopilot v3.0.

Provides deterministic, code-based conversions and formatting between imperial
and metric systems for high-accuracy science and general explanation scripts.
"""

import re


def convert_miles_to_km(miles: float) -> float:
    """Converts miles to kilometers."""
    return round(miles * 1.609344, 2)


def convert_km_to_miles(km: float) -> float:
    """Converts kilometers to miles."""
    return round(km / 1.609344, 2)


def convert_pounds_to_kg(lbs: float) -> float:
    """Converts pounds to kilograms."""
    return round(lbs * 0.45359237, 2)


def convert_kg_to_pounds(kg: float) -> float:
    """Converts kilograms to pounds."""
    return round(kg / 0.45359237, 2)


def convert_tons_to_metric_tons(tons: float) -> float:
    """Converts US short tons (2,000 lbs) to metric tons (1,000 kg)."""
    return round(tons * 0.90718474, 2)


def convert_feet_to_meters(feet: float) -> float:
    """Converts feet to meters."""
    return round(feet * 0.3048, 2)


def convert_meters_to_feet(meters: float) -> float:
    """Converts meters to feet."""
    return round(meters / 0.3048, 2)


def convert_fahrenheit_to_celsius(f: float) -> float:
    """Converts Fahrenheit to Celsius."""
    return round((f - 32.0) * (5.0 / 9.0), 1)


def convert_celsius_to_fahrenheit(c: float) -> float:
    """Converts Celsius to Fahrenheit."""
    return round((c * (9.0 / 5.0)) + 32.0, 1)


def format_measurement(val: float, unit: str, format_type: str = "imperial_with_metric") -> str:
    """Formats a measurement into US imperial with metric in parentheses.

    Examples:
        format_measurement(60, "miles") -> "60 miles (97 km)"
        format_measurement(100, "km") -> "62 miles (100 km)"
        format_measurement(500, "lbs") -> "500 pounds (227 kg)"
        format_measurement(6, "billion tons") -> "6 billion tons (5.4 billion metric tons)"
    """
    clean_unit = unit.lower().strip()

    if clean_unit in ["mile", "miles"]:
        km = convert_miles_to_km(val)
        km_str = f"{km:g}"
        val_str = f"{val:g}"
        return f"{val_str} miles ({km_str} km)" if format_type == "imperial_with_metric" else f"{val_str} miles"

    if clean_unit in ["km", "kilometer", "kilometers"]:
        miles = convert_km_to_miles(val)
        miles_str = f"{miles:g}"
        val_str = f"{val:g}"
        return f"{miles_str} miles ({val_str} km)" if format_type == "imperial_with_metric" else f"{val_str} km"

    if clean_unit in ["pound", "pounds", "lb", "lbs"]:
        kg = convert_pounds_to_kg(val)
        kg_str = f"{kg:g}"
        val_str = f"{val:g}"
        return f"{val_str} pounds ({kg_str} kg)" if format_type == "imperial_with_metric" else f"{val_str} pounds"

    if clean_unit in ["kg", "kilogram", "kilograms"]:
        lbs = convert_kg_to_pounds(val)
        lbs_str = f"{lbs:g}"
        val_str = f"{val:g}"
        return f"{lbs_str} pounds ({val_str} kg)" if format_type == "imperial_with_metric" else f"{val_str} kg"

    if clean_unit in ["ton", "tons", "billion tons", "million tons"]:
        if "billion" in clean_unit:
            m_tons = round(val * 0.90718474, 1)
            return f"{val:g} billion tons ({m_tons:g} billion metric tons)"
        if "million" in clean_unit:
            m_tons = round(val * 0.90718474, 1)
            return f"{val:g} million tons ({m_tons:g} million metric tons)"
        m_tons = convert_tons_to_metric_tons(val)
        return f"{val:g} tons ({m_tons:g} metric tons)"

    if clean_unit in ["foot", "feet", "ft"]:
        meters = convert_feet_to_meters(val)
        return f"{val:g} feet ({meters:g} meters)"

    if clean_unit in ["meter", "meters", "m"]:
        feet = convert_meters_to_feet(val)
        return f"{feet:g} feet ({val:g} meters)"

    if clean_unit in ["f", "fahrenheit", "°f"]:
        c = convert_fahrenheit_to_celsius(val)
        return f"{val:g}°F ({c:g}°C)"

    if clean_unit in ["c", "celsius", "°c"]:
        f_val = convert_celsius_to_fahrenheit(val)
        return f"{f_val:g}°F ({val:g}°C)"

    return f"{val:g} {unit}"


def augment_text_with_dual_units(text: str) -> str:
    """Scans text for standalone single-unit measurements and augments them with dual units."""
    # Pattern 1: X miles (where not already followed by parenthesized km or inside parentheses)
    pattern_miles = r"(?<!\()\b(\d+(?:\.\d+)?)\s*(?:miles|mile)\b(?!\s*\([^)]*km\))"

    def _replace_miles(m):
        val = float(m.group(1))
        km = convert_miles_to_km(val)
        return f"{val:g} miles ({km:g} km)"

    text = re.sub(pattern_miles, _replace_miles, text, flags=re.IGNORECASE)

    # Pattern 2: X km / kilometers (where not already inside parentheses or preceded by miles)
    pattern_km = r"(?<!\()\b(\d+(?:\.\d+)?)\s*(?:km|kilometers?)\b(?!\))"

    def _replace_km(m):
        val = float(m.group(1))
        miles = convert_km_to_miles(val)
        return f"{miles:g} miles ({val:g} km)"

    text = re.sub(pattern_km, _replace_km, text, flags=re.IGNORECASE)

    return text
