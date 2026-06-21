# tests/test_compute_page3.py
import json
from datetime import date
from pathlib import Path
import pytest
from dashboard.compute.windows import resolve_window
from dashboard.compute.page3_actions import compute


@pytest.fixture
def raw():
    return json.loads(
        (Path(__file__).parent / "fixtures" / "sample_raw.json").read_text()
    )


@pytest.fixture
def rules():
    return {"fathom_gap": {"attendee_match_strategy": "email_domain_first",
                           "fuzzy_match_threshold": 85}}


def test_fathom_gap_finds_acme_corp_with_no_deal(raw, rules):
    # fm2: Acme Corp meeting 2026-04-22; no deal in HubSpot for "acme-corp.io"
    window = resolve_window("month-april", date(2026, 5, 9))
    out = compute(raw, rules, window)
    gap_companies = [g["company"] for g in out["fathom_gap"]]
    assert any("Acme" in c or "acme" in c.lower() for c in gap_companies)


def test_fathom_gap_excludes_scalenut_with_existing_deal(raw, rules):
    window = resolve_window("month-april", date(2026, 5, 9))
    out = compute(raw, rules, window)
    # Scalenut has a deal (id=1001), so it should NOT be in the gap
    assert not any("Scalenut" == g["company"] for g in out["fathom_gap"])


def test_fathom_gap_window_filters_meetings(raw, rules):
    # Window = May 2026 → no Fathom meetings in fixture (both are April)
    window = resolve_window("month-may", date(2026, 5, 9))
    out = compute(raw, rules, window)
    assert out["fathom_gap"] == []
