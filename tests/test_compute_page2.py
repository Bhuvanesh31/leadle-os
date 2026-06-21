# tests/test_compute_page2.py
import json
from datetime import date
from pathlib import Path

import pytest

from dashboard.compute.page2_activity import compute


@pytest.fixture
def raw():
    return json.loads(
        (Path(__file__).parent / "fixtures" / "sample_raw.json").read_text()
    )


@pytest.fixture
def rules():
    return {"rotting_deal_days": 14, "stalled_lead_days": 5}


def test_rotting_deals_picks_up_old_activity(raw, rules):
    out = compute(raw, rules, today=date(2026, 5, 9))
    # Scalenut last activity 2026-03-08 → today 2026-05-09 → 62 days stale
    rotting = out["rotting_deals"]
    assert any(d["name"] == "Scalenut" for d in rotting)
    scalenut = next(d for d in rotting if d["name"] == "Scalenut")
    assert scalenut["days_stale"] == 62


def test_rotting_deals_excludes_won(raw, rules):
    out = compute(raw, rules, today=date(2026, 5, 9))
    assert not any(d["name"] == "Acme Won" for d in out["rotting_deals"])


def test_pipeline_at_risk_sums_amounts(raw, rules):
    out = compute(raw, rules, today=date(2026, 5, 9))
    # Scalenut 5000 stale; QuoDeck 8000 (last_activity 2026-04-20 → 19 days stale)
    assert out["pipeline_at_risk"] == 13000


def test_stalled_leads_filters_by_reply_status(raw, rules):
    out = compute(raw, rules, today=date(2026, 5, 9))
    # Alice replied 2026-04-15, lifecycle=lead, days_since_reply=24 → stalled
    stalled = out["stalled_leads"]
    assert any(s["email"] == "alice@scalenut.com" for s in stalled)


def test_kpi_strip_counts(raw, rules):
    out = compute(raw, rules, today=date(2026, 5, 9))
    assert out["kpi"]["rotting_count"] == 2
    assert out["kpi"]["stalled_count"] >= 1
