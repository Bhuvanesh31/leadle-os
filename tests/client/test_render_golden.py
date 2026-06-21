"""Golden structure test: proves productized render matches the approved design.

Loads the real XLSX fixture via sheet_source.read_xlsx to exercise the parser,
then attaches representative campaign-model data so every block renders.
Asserts section titles, audience gating, heatmap palette, headline KPI, and
autoescape integrity (no internal sender email leaking to client output).
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import yaml

from dashboard.client.model import EmailCampaign, LinkedInCampaign, OpenEvent, ReplyRecord
from dashboard.client.sources import sheet_source
from dashboard.client import compute, render

_REPO = Path(__file__).resolve().parents[2]
_CFG = _REPO / "config"
FIX_XLSX = _REPO / "tests" / "client" / "fixtures" / "upsta_mini.xlsx"

_BLUE_PALETTE = ["#EFF6FF", "#DBEAFE", "#93C5FD", "#3B82F6", "#1D4ED8"]

# Section titles that must appear in BOTH audiences.
# "Headline" is the layout config label for the kpis block; the kpis partial renders
# "Emails sent" (the KPI tile label) rather than the block title string. The remaining
# titles are emitted by each partial as <span class="t">…</span>.
_BOTH_TITLES = [
    "Emails sent",              # kpis partial: KPI tile label (no .sec-h title for this block)
    "Benchmark scorecard",
    "Which campaign performed",
    "Which content performed",
    "Which LinkedIn message worked",
    "Engagement timing",
    "Channel reach",
    "Warm &amp; named leads",   # Jinja autoescape encodes & → &amp;
    "Targets next period",
]

# Titles visible only to internal audience
_INTERNAL_ONLY_TITLES = [
    "Sender health",
    "Deliverability flags",
    "Actions this period",
]

_FIXED_TS = "2026-06-30T00:00:00"


def _build():
    """Load fixture XLSX + attach representative campaign data. Returns (data, metrics, dbag, rubric, layout)."""
    rubric = yaml.safe_load((_CFG / "client_report_rubric.yaml").read_text())
    layout = yaml.safe_load((_CFG / "client_report_layout.yaml").read_text())

    data = sheet_source.read_xlsx(str(FIX_XLSX))

    # Attach campaign data (XLSX has no API-sourced campaign numbers)
    data.email_campaigns = [
        EmailCampaign(name="SFDI·US", sent=1012, opened=293, clicked=40, bounced=64, replied=0)
    ]
    data.linkedin_campaigns = [
        LinkedInCampaign(
            name="PMP·US", invites=400, accepted=120, replied=6,
            variant_message="personal founder intro",
        )
    ]
    data.replies = [
        ReplyRecord(channel="linkedin", campaign="PMP·US", sentiment="neutral", name="X")
    ]
    data.senders = [{"from_email": "augustine.m@upstahq.com", "sent": 239, "bounced": 18}]
    data.content_steps = [
        {"step": 1, "sent": 1012, "opened": 293},
        {"step": 2, "sent": 500, "opened": 90},
    ]
    # Add a real OpenEvent so the timing heatmap palette cell gets coloured
    data.opens = [OpenEvent(channel="email", ts=datetime(2026, 6, 10, 14, 30))]

    metrics = compute.compute_all(data, rubric)
    dbag = {
        "emails_sent": {"value": 1012, "delta": None, "baseline": True},
        "invites": {"value": 400, "delta": None, "baseline": True},
    }
    return data, metrics, dbag, rubric, layout


def _render_both():
    """Return (client_html, internal_html) pair."""
    data, metrics, dbag, rubric, layout = _build()
    client_html = render.render(
        data, metrics, dbag,
        {"narrative": "Strong LinkedIn accept rate.", "degraded": False},
        {"actions": [], "degraded": True},
        audience="client",
        period_label="June 2026",
        client="UPSTA",
        layout=layout,
        rubric=rubric,
        rendered_at=_FIXED_TS,
    )
    internal_html = render.render(
        data, metrics, dbag,
        {"narrative": "Strong LinkedIn accept rate.", "degraded": False},
        {"actions": ["Pause & warm inbox."], "degraded": False},
        audience="internal",
        period_label="June 2026",
        client="UPSTA",
        layout=layout,
        rubric=rubric,
        rendered_at=_FIXED_TS,
    )
    return client_html, internal_html


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_client_contains_all_both_audience_titles():
    """Every block visible to 'both' audiences must appear in client output."""
    client_html, _ = _render_both()
    missing = [t for t in _BOTH_TITLES if t not in client_html]
    assert not missing, f"Missing section titles in client output: {missing}"


def test_client_excludes_internal_only_titles():
    """Internal-only block titles must NOT appear in client output."""
    client_html, _ = _render_both()
    present = [t for t in _INTERNAL_ONLY_TITLES if t in client_html]
    assert not present, f"Internal-only titles leaked into client output: {present}"


def test_internal_contains_sender_health_and_deliverability():
    """Internal output must include sender health and deliverability titles."""
    _, internal_html = _render_both()
    assert "Sender health" in internal_html, "Sender health block missing from internal output"
    assert "Deliverability flags" in internal_html, "Deliverability flags block missing from internal output"


def test_blue_heatmap_palette_in_client_output():
    """At least one heatmap palette hex must appear in the client output."""
    client_html, _ = _render_both()
    found = [c for c in _BLUE_PALETTE if c in client_html]
    assert found, (
        f"None of the blue palette colours {_BLUE_PALETTE} found in client output. "
        "The timing/heatmap block may have been removed or the palette changed."
    )


def test_headline_emails_sent_renders_in_client_output():
    """The emails-sent headline KPI (1,012) must appear in client output."""
    client_html, _ = _render_both()
    # Template uses '{:,}'.format(k.emails_sent) → "1,012"
    assert "1,012" in client_html, (
        "Expected headline emails-sent figure '1,012' not found in client output."
    )


def test_internal_sender_email_does_not_leak_to_client():
    """Autoescape + audience gate: sender email 'augustine' must not appear in client output."""
    client_html, _ = _render_both()
    assert "augustine" not in client_html, (
        "Internal sender email 'augustine.m@upstahq.com' leaked into client HTML output."
    )
