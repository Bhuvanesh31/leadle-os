# tests/test_compute_page1.py
import json
from datetime import date
from pathlib import Path
import pytest
from dashboard.compute.windows import resolve_window
from dashboard.compute.page1_revenue import compute


@pytest.fixture
def raw():
    return json.loads(
        (Path(__file__).parent / "fixtures" / "sample_raw.json").read_text()
    )


@pytest.fixture
def rules():
    return {"rotting_deal_days": 14, "stalled_lead_days": 5, "followup_gap_days": 5,
            "outreach_min_sends": 10, "anomaly_pct_threshold": 30,
            "hygiene": {"require_owner": True, "require_source": True, "require_lifecycle": True}}


@pytest.fixture
def targets():
    return {"annual": {"goal_amount": 319000, "goal_currency": "USD",
                       "target_date": "2026-10-31"},
            "monthly": {"target_amount": 61800, "target_currency": "USD"},
            "pipeline_coverage": {"ratio_target": 3.0, "ratio_warning_below": 2.0,
                                  "ratio_critical_below": 1.0}}


@pytest.fixture
def window():
    return resolve_window("current-month", date(2026, 5, 9))


def test_goal_snapshot_ytd_revenue(raw, rules, targets, window):
    out = compute(raw, rules, targets, window)
    # Closed-won YTD = single Acme deal at $12,000 (closedate 2026-04-28, in 2026 calendar)
    assert out["goal_snapshot"]["ytd_revenue"] == 12000
    assert out["goal_snapshot"]["goal_amount"] == 319000
    assert out["goal_snapshot"]["pct_of_goal"] == pytest.approx(12000 / 319000 * 100, rel=1e-3)


def test_monthly_control_pipeline_coverage(raw, rules, targets, window):
    out = compute(raw, rules, targets, window)
    # Open pipeline = $5K (Scalenut) + $8K (QuoDeck) = $13K
    # Monthly target = $61,800 → coverage = 13000 / 61800 ≈ 0.21
    assert out["monthly_control"]["open_pipeline"] == 13000
    assert out["monthly_control"]["pipeline_coverage_ratio"] == pytest.approx(13000 / 61800, rel=1e-3)


def test_funnel_stage_counts(raw, rules, targets, window):
    out = compute(raw, rules, targets, window)
    # 1 discovery, 1 proposal, 1 closedwon
    counts = out["funnel"]["stage_counts"]
    assert counts.get("discovery") == 1
    assert counts.get("proposal") == 1
    assert counts.get("closedwon") == 1


def test_hygiene_finds_no_issues_in_clean_fixture(raw, rules, targets, window):
    out = compute(raw, rules, targets, window)
    # Fixture deals/contacts all have owner, source, lifecycle → no issues
    assert out["hygiene"]["missing_source_count"] == 0
    assert out["hygiene"]["missing_owner_count"] == 0


def test_channel_performance_groups_by_source(raw, rules, targets, window):
    out = compute(raw, rules, targets, window)
    channels = {c["channel"]: c for c in out["channel_performance"]["channels"]}
    assert "ORGANIC_SEARCH" in channels
    assert "REFERRALS" in channels
    assert channels["REFERRALS"]["closed_won_revenue"] == 12000
