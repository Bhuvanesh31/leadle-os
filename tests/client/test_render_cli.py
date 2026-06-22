"""Tests for the render CLI: 4-output run (period × audience) and window helper.

No live API calls. Loader callees are monkeypatched to return canned data.
The real XLSX fixture is used (via sheet_source.read_xlsx).
"""

from __future__ import annotations

from pathlib import Path

from dashboard.client import render
from dashboard.client.constants import AIMFOX_ENV, INSTANTLY_ENV
from dashboard.client.model import LinkedInCampaign

FIX_XLSX = Path(__file__).parent / "fixtures" / "upsta_mini.xlsx"

# ---------------------------------------------------------------------------
# Canned API stubs
# ---------------------------------------------------------------------------

_LI_CAMPAIGN = LinkedInCampaign(
    name="upsta-li-test", invites=20, accepted=5, replied=1, variant_message="Hello"
)

_INSTANTLY_PAYLOAD = {
    "available": True,
    "data": {
        "campaigns": [
            {
                "name": "upsta-email-test",
                "sent": 50,
                "opened": 10,
                "clicked": 2,
                "bounced": 1,
                "replied": 3,
            }
        ],
        "senders": [{"from_email": "test@example.com", "sent": 50, "bounced": 1}],
        "steps": [{"step": 1, "sent": 50, "opened": 10}],
    },
}


# ---------------------------------------------------------------------------
# Window helper tests
# ---------------------------------------------------------------------------


def test_window_monthly():
    assert render._window("monthly", "2026-06-30") == ("2026-06-01", "2026-06-30")


def test_window_weekly():
    assert render._window("weekly", "2026-06-30") == ("2026-06-24", "2026-06-30")


# ---------------------------------------------------------------------------
# Main CLI — 4 outputs test
# ---------------------------------------------------------------------------


def test_main_all_periods_both_audiences_writes_four(tmp_path, monkeypatch):
    # Patch out live network calls inside the loader
    monkeypatch.setattr(
        "dashboard.client.sources.loader.aimfox_source.read",
        lambda *a, **k: [_LI_CAMPAIGN],
    )
    monkeypatch.setattr(
        "dashboard.client.sources.loader.instantly_fetch.fetch",
        lambda *a, **k: _INSTANTLY_PAYLOAD,
    )
    # Set dummy env vars so os.environ.get() returns non-empty keys
    monkeypatch.setenv(AIMFOX_ENV, "x")
    monkeypatch.setenv(INSTANTLY_ENV, "x")

    rc = render.main(
        [
            "--xlsx",
            str(FIX_XLSX),
            "--all-periods",
            "--audience",
            "both",
            "--skip-agents",
            "--period-end",
            "2026-06-30",
            "--output-dir",
            str(tmp_path),
            "--snapshot-store",
            str(tmp_path / "snaps.json"),
        ]
    )

    assert rc == 0
    names = {p.name for p in tmp_path.glob("*.html")}
    assert names == {
        "UPSTA-2026-06-30-monthly-internal.html",
        "UPSTA-2026-06-30-monthly-client.html",
        "UPSTA-2026-06-30-weekly-internal.html",
        "UPSTA-2026-06-30-weekly-client.html",
    }
