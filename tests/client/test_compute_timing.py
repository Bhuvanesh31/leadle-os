# tests/client/test_compute_timing.py
"""TDD tests for timing_heatmap — sources from data.opens (OpenEvent), not data.emails.

Scenario:
  - Wed Morning 9-12 × 3 email opens
  - Fri Afternoon 15-18 × 1 email open
  - 1 linkedin open (channel="linkedin") — must be ignored
  max = 3  →  Wed/Morning level = ceil(4*3/3) = 4
             Fri/Afternoon level = ceil(4*1/3) = ceil(1.33) = 2
             Mon/<any> level = 0 (untouched)
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
import yaml

from dashboard.client.model import ClientData, OpenEvent
from dashboard.client import compute

_CFG = Path(__file__).resolve().parents[2] / "config"

ET = ZoneInfo("America/New_York")


def _rubric():
    return yaml.safe_load((_CFG / "client_report_rubric.yaml").read_text())


def _utc(year, month, day, hour_et):
    """Return a UTC-aware datetime that maps to hour_et in America/New_York."""
    local_dt = datetime(year, month, day, hour_et, 0, 0, tzinfo=ET)
    return local_dt.astimezone(timezone.utc)


def test_timing_heatmap_from_opens():
    """Core scenario: Wed Morning ×3, Fri Afternoon ×1; linkedin open ignored."""
    # Wednesday = weekday 2; 2026-06-17 is a Wednesday
    # Morning 9-12: use hour 10 ET
    wed_open_1 = OpenEvent(channel="email", ts=_utc(2026, 6, 17, 10))
    wed_open_2 = OpenEvent(channel="email", ts=_utc(2026, 6, 17, 11))
    wed_open_3 = OpenEvent(channel="email", ts=_utc(2026, 6, 17, 9))
    # Friday = weekday 4; 2026-06-19 is a Friday
    # Afternoon 15-18: use hour 16 ET
    fri_open = OpenEvent(channel="email", ts=_utc(2026, 6, 19, 16))
    # LinkedIn open — must be skipped
    li_open = OpenEvent(channel="linkedin", ts=_utc(2026, 6, 17, 10))

    data = ClientData(opens=[wed_open_1, wed_open_2, wed_open_3, fri_open, li_open])
    result = compute.timing_heatmap(data, _rubric())

    assert result["max"] == 3
    assert result["best"]["weekday"] == "Wed"
    assert result["best"]["daypart"] == "Morning 9-12"
    assert result["best"]["count"] == 3

    levels = result["levels"]

    # Max cell: Wed / Morning 9-12 → ceil(4*3/3) = 4
    assert levels["Wed"]["Morning 9-12"] == 4
    # Fri / Afternoon → ceil(4*1/3) = ceil(1.33) = 2
    assert levels["Fri"]["Afternoon 15-18"] == 2
    # Untouched: Mon / any daypart → 0
    assert levels["Mon"]["Morning 9-12"] == 0

    # Grid counts
    assert result["grid"]["Wed"]["Morning 9-12"] == 3
    assert result["grid"]["Fri"]["Afternoon 15-18"] == 1

    assert result["timezone"] == "America/New_York"
    assert "note" in result
    assert "LinkedIn" in result["note"]


def test_timing_heatmap_no_opens():
    """Empty opens list: max == 0, all levels 0."""
    data = ClientData(opens=[])
    result = compute.timing_heatmap(data, _rubric())

    assert result["max"] == 0
    assert result["best"]["count"] == -1  # no best cell found

    for wd in result["weekdays"]:
        for dp in result["dayparts"]:
            assert result["levels"][wd][dp] == 0


def test_timing_heatmap_linkedin_opens_excluded():
    """LinkedIn opens must NOT affect the grid or levels."""
    li_open = OpenEvent(channel="linkedin", ts=_utc(2026, 6, 17, 10))
    data = ClientData(opens=[li_open])
    result = compute.timing_heatmap(data, _rubric())

    assert result["max"] == 0
    for wd in result["weekdays"]:
        for dp in result["dayparts"]:
            assert result["levels"][wd][dp] == 0


def test_timing_heatmap_weekend_opens_excluded():
    """Sat/Sun opens must NOT appear in the Mon-Fri grid."""
    # 2026-06-20 is Saturday
    sat_open = OpenEvent(channel="email", ts=_utc(2026, 6, 20, 10))
    data = ClientData(opens=[sat_open])
    result = compute.timing_heatmap(data, _rubric())

    assert result["max"] == 0
    for wd in result["weekdays"]:
        for dp in result["dayparts"]:
            assert result["levels"][wd][dp] == 0


def test_timing_heatmap_none_ts_does_not_crash():
    """OpenEvent with ts=None must be silently skipped; only real opens are counted."""
    real_open = OpenEvent(channel="email", ts=_utc(2026, 6, 17, 10))  # Wed morning
    null_open = OpenEvent(channel="email", ts=None)
    data = ClientData(opens=[null_open, real_open])
    # Must not raise AttributeError
    result = compute.timing_heatmap(data, _rubric())
    # Only the real open is counted
    assert result["max"] == 1
    assert result["grid"]["Wed"]["Morning 9-12"] == 1
