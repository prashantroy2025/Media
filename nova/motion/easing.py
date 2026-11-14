"""Mathematical Easing Functions for Nova Autopilot v8.0 Motion Design.

Implements standard CSS/AfterEffects cubic easing and physical spring overshoot curves.
All functions take normalized time t in [0.0, 1.0] and return eased value.
"""

from __future__ import annotations

import math


def linear(t: float) -> float:
    return max(0.0, min(1.0, t))


def ease_out_cubic(t: float) -> float:
    """Fast acceleration into smooth deceleration."""
    t = max(0.0, min(1.0, t))
    return 1.0 - (1.0 - t) ** 3


def ease_in_out_quad(t: float) -> float:
    """Smooth acceleration and smooth deceleration."""
    t = max(0.0, min(1.0, t))
    return 2.0 * t * t if t < 0.5 else 1.0 - ((-2.0 * t + 2.0) ** 2) / 2.0


def ease_out_expo(t: float) -> float:
    """Rapid snappy pop."""
    t = max(0.0, min(1.0, t))
    return 1.0 if t >= 1.0 else 1.0 - (2.0 ** (-10.0 * t))


def spring_overshoot(t: float, overshoot: float = 1.18) -> float:
    """Dynamic kinetic spring that overshoots target (1.0) then snaps back."""
    t = max(0.0, min(1.0, t))
    if t <= 0.0:
        return 0.0
    if t >= 1.0:
        return 1.0
    # Decaying sine wave overshoot
    decay = math.exp(-6.0 * t)
    oscillation = math.cos(math.pi * 2.5 * t)
    return 1.0 - decay * oscillation * overshoot


def lerp(start: float, end: float, t: float) -> float:
    """Linear interpolation between start and end."""
    return start + (end - start) * t
