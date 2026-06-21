"""Shared compute helpers: date math, pacing status, anomaly diff.

Intentionally tiny — these are utilities for per-page compute modules.
"""
from __future__ import annotations

from datetime import date


def pct_diff(current: float, baseline: float) -> float | None:
    """Percent change from baseline → current. None if baseline is zero."""
    if baseline == 0:
        return None
    return (current - baseline) / baseline * 100.0


def pacing_status(achieved: float, target: float, fraction_elapsed: float) -> str:
    """Classify pacing: on-track, warning, critical.

    on-track:  achieved/target >= fraction_elapsed * 0.9
    warning:   achieved/target >= fraction_elapsed * 0.5  (but not on-track)
    critical:  below warning threshold
    """
    if target <= 0:
        return "warning"  # missing target = warning, not critical
    achieved_frac = achieved / target
    if achieved_frac >= fraction_elapsed * 0.9:
        return "on-track"
    if achieved_frac >= fraction_elapsed * 0.5:
        return "warning"
    return "critical"


def days_between(start: date, end: date) -> int:
    """Inclusive day count between two dates."""
    return (end - start).days + 1


def in_window(d: date, start: date, end: date) -> bool:
    """Inclusive both ends."""
    return start <= d <= end
