# tests/test_compute_shared.py
from datetime import date

from dashboard.compute.shared import days_between, in_window, pacing_status, pct_diff


def test_pct_diff_normal():
    assert pct_diff(120, 100) == 20.0
    assert pct_diff(80, 100) == -20.0


def test_pct_diff_baseline_zero_returns_none():
    # Cannot compute % when baseline is zero
    assert pct_diff(50, 0) is None


def test_pacing_status_on_track():
    # 50% of period elapsed, 50% of goal achieved → on-track
    assert pacing_status(achieved=50, target=100, fraction_elapsed=0.5) == "on-track"


def test_pacing_status_critical():
    # 50% elapsed, 5% achieved → critical
    assert pacing_status(achieved=5, target=100, fraction_elapsed=0.5) == "critical"


def test_pacing_status_warning():
    # 50% elapsed, 30% achieved → warning
    assert pacing_status(achieved=30, target=100, fraction_elapsed=0.5) == "warning"


def test_days_between_inclusive():
    assert days_between(date(2026, 5, 1), date(2026, 5, 9)) == 9


def test_in_window_inclusive_bounds():
    start = date(2026, 5, 1)
    end = date(2026, 5, 31)
    assert in_window(date(2026, 5, 1), start, end) is True
    assert in_window(date(2026, 5, 31), start, end) is True
    assert in_window(date(2026, 4, 30), start, end) is False
    assert in_window(date(2026, 6, 1), start, end) is False
