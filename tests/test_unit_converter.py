"""Unit tests for code-based unit conversion helper."""

import pytest

from nova.utils.units import (
    augment_text_with_dual_units,
    convert_celsius_to_fahrenheit,
    convert_fahrenheit_to_celsius,
    convert_feet_to_meters,
    convert_km_to_miles,
    convert_meters_to_feet,
    convert_miles_to_km,
    convert_pounds_to_kg,
    convert_tons_to_metric_tons,
    format_measurement,
)


def test_distance_conversions():
    assert convert_miles_to_km(60.0) == pytest.approx(96.56, 0.01)
    assert convert_km_to_miles(100.0) == pytest.approx(62.14, 0.01)


def test_weight_conversions():
    assert convert_pounds_to_kg(100.0) == pytest.approx(45.36, 0.01)
    assert convert_tons_to_metric_tons(10.0) == pytest.approx(9.07, 0.01)


def test_length_conversions():
    assert convert_feet_to_meters(100.0) == pytest.approx(30.48, 0.01)
    assert convert_meters_to_feet(10.0) == pytest.approx(32.81, 0.01)


def test_temperature_conversions():
    assert convert_fahrenheit_to_celsius(212.0) == 100.0
    assert convert_fahrenheit_to_celsius(32.0) == 0.0
    assert convert_celsius_to_fahrenheit(0.0) == 32.0
    assert convert_celsius_to_fahrenheit(100.0) == 212.0


def test_format_measurement():
    assert format_measurement(60, "miles") == "60 miles (96.56 km)"
    assert format_measurement(100, "km") == "62.14 miles (100 km)"
    assert format_measurement(6, "billion tons") == "6 billion tons (5.4 billion metric tons)"
    assert format_measurement(500, "lbs") == "500 pounds (226.8 kg)"
    assert format_measurement(70, "F") == "70°F (21.1°C)"


def test_augment_text():
    text = "The satellite travels 60 miles above the atmosphere."
    augmented = augment_text_with_dual_units(text)
    assert "60 miles (96.56 km)" in augmented
