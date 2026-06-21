# tests/test_compute_page4.py
import json
from datetime import date
from pathlib import Path

import pytest

from dashboard.compute.page4_outreach import compute
from dashboard.compute.windows import resolve_window


@pytest.fixture
def raw():
    return json.loads(
        (Path(__file__).parent / "fixtures" / "sample_raw.json").read_text()
    )


@pytest.fixture
def rules():
    return {"outreach_min_sends": 10, "followup_gap_days": 5}


def test_lemlist_campaign_aggregates(raw, rules):
    window = resolve_window("current-month", date(2026, 5, 9))
    out = compute(raw, rules, window, today=date(2026, 5, 9))
    assert len(out["lemlist"]) == 1
    c = out["lemlist"][0]
    assert c["name"] == "RevOps Q2 Outbound"
    assert c["sends"] == 120
    assert c["replies"] == 8
    assert c["reply_rate_pct"] == pytest.approx(8 / 120 * 100, rel=1e-3)


def test_outreach_below_min_sends_excluded(raw, rules):
    rules2 = {**rules, "outreach_min_sends": 250}
    window = resolve_window("current-month", date(2026, 5, 9))
    out = compute(raw, rules2, window, today=date(2026, 5, 9))
    # All campaigns under 250 sends → excluded
    assert out["lemlist"] == []
    assert out["aimfox"] == []
    assert out["instantly"] == []


def test_followup_gap_lists_alice(raw, rules):
    window = resolve_window("current-month", date(2026, 5, 9))
    out = compute(raw, rules, window, today=date(2026, 5, 9))
    # Alice: lifecycle=lead, last_activity=2026-04-15, today=2026-05-09 → 24 days gap
    gap = out["followup_gap"]
    assert any(g["email"] == "alice@scalenut.com" for g in gap)
