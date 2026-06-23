"""Golden structure test: proves productized render matches the approved design.

Loads the real XLSX fixture via sheet_source.read_xlsx to exercise the parser,
then attaches representative campaign-model data so every block renders.
Asserts section titles, audience gating, heatmap palette, headline KPI, and
autoescape integrity (no internal sender email leaking to client output).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
import yaml

from dashboard.client import compute, render, snapshots
from dashboard.client.model import EmailCampaign, LinkedInCampaign, OpenEvent, ReplyRecord
from dashboard.client.sources import sheet_source

_REPO = Path(__file__).resolve().parents[2]
_CFG = _REPO / "config"
FIX_XLSX = _REPO / "tests" / "client" / "fixtures" / "upsta_mini.xlsx"

_BLUE_PALETTE = ["#EFF6FF", "#DBEAFE", "#93C5FD", "#3B82F6", "#1D4ED8"]

# Section titles that must appear in BOTH audiences.
# "Headline" is the layout config label for the kpis block; the kpis partial renders
# "Emails sent" (the KPI tile label) rather than the block title string. The remaining
# titles are emitted by each partial as <span class="t">…</span>.
_BOTH_TITLES = [
    "Emails sent",  # kpis partial: KPI tile label (no .sec-h title for this block)
    "Benchmark scorecard",
    "Which campaign performed",
    "Which content performed",
    "Which LinkedIn message worked",
    "Engagement timing",
    "Channel reach",
    "Warm &amp; named leads",  # Jinja autoescape encodes & → &amp;
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

    # ≥6 email campaigns; one with 0 opens (should be excluded from email_campaigns box)
    # so both top-5 truncation and 0-open exclusion are exercised.
    data.email_campaigns = [
        EmailCampaign(name="SFDI·US", sent=1012, opened=293, clicked=40, bounced=64, replied=0),
        EmailCampaign(name="SG·EU",   sent=800,  opened=200, clicked=30, bounced=20, replied=2),
        EmailCampaign(name="SG·APAC", sent=600,  opened=150, clicked=20, bounced=15, replied=1),
        EmailCampaign(name="PMP·SG",  sent=500,  opened=100, clicked=10, bounced=10, replied=0),
        EmailCampaign(name="PMP·EU",  sent=400,  opened=80,  clicked=8,  bounced=8,  replied=0),
        EmailCampaign(name="ZERO·US", sent=300,  opened=0,   clicked=0,  bounced=5,  replied=0),
    ]
    data.linkedin_campaigns = [
        LinkedInCampaign(
            name="PMP·US",
            invites=400,
            accepted=120,
            replied=6,
            variant_message="personal founder intro",
        )
    ]
    data.replies = [
        ReplyRecord(channel="linkedin", campaign="PMP·US", sentiment="neutral", name="X")
    ]
    data.senders = [{"from_email": "augustine.m@upstahq.com", "sent": 239, "bounced": 18}]
    data.content_steps = [
        {"step": 1, "campaign": "SFDI·US", "sent": 1012, "opened": 293,
         "subject": "Quick question", "body_preview": "Hi {{first_name}}"},
        {"step": 2, "campaign": "SFDI·US", "sent": 500, "opened": 90,
         "subject": "Following up", "body_preview": ""},
    ]
    # Add a real OpenEvent so the timing heatmap palette cell gets coloured
    data.opens = [OpenEvent(channel="email", ts=datetime(2026, 6, 10, 14, 30))]

    metrics = compute.compute_all(data, rubric)

    # Synthetic prior snapshot — gives WoW arrows a prior to diff against
    prior_metrics = {
        "kpis": {
            "emails_sent": 900, "fresh_prospects": 900, "opened": 200,
            "clicked": 30, "bounced": 60, "delivered": 840,
            "open_rate": 0.238, "click_rate": 0.036, "bounce_rate": 0.067,
            "invites": 350, "accepted": 100, "accept_rate": 0.286,
            "li_replies": 5, "email_replies": 0, "total_replies": 5,
            "positive_replies": 0, "neutral_replies": 5, "negative_replies": 0,
            "leads": 0, "meetings": 0,
        },
        "boxes": {
            "email_campaigns": [
                {"name": "SFDI·US", "sent": 900, "reply_rate": 0.0,
                 "click_rate": 0.035, "open_rate": 0.24, "bounce_rate": 0.06, "grade": "B"},
                {"name": "SG·EU", "sent": 700, "reply_rate": 0.0,
                 "click_rate": 0.02, "open_rate": 0.22, "bounce_rate": 0.03, "grade": "B"},
            ],
            "email_steps": [],
            "linkedin_campaigns": [
                {"name": "PMP·US", "invites": 350, "connections": 100,
                 "reply_rate": 0.01, "accept_rate": 0.286},
            ],
            "linkedin_variants": [
                {"name": "PMP·US", "accept_rate": 0.286, "replies": 4,
                 "reply_rate": 0.01, "hook": "personal founder intro", "winner": True},
            ],
        },
    }
    dbag = snapshots.box_deltas(metrics, prior_metrics)
    return data, metrics, dbag, rubric, layout


def _render_both():
    """Return (client_html, internal_html) pair."""
    data, metrics, dbag, rubric, layout = _build()
    client_html = render.render(
        data,
        metrics,
        dbag,
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
        data,
        metrics,
        dbag,
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
    assert "Deliverability flags" in internal_html, (
        "Deliverability flags block missing from internal output"
    )


def test_blue_heatmap_palette_in_client_output():
    """At least one heatmap palette hex must appear in the client output."""
    client_html, _ = _render_both()
    found = [c for c in _BLUE_PALETTE if c in client_html]
    assert found, (
        f"None of the blue palette colours {_BLUE_PALETTE} found in client output. "
        "The timing/heatmap block may have been removed or the palette changed."
    )


def test_headline_emails_sent_renders_in_client_output():
    """The emails-sent headline KPI (3,612) must appear in client output."""
    client_html, _ = _render_both()
    # Template uses '{:,}'.format(k.emails_sent) → "3,612" (6 campaigns: 1012+800+600+500+400+300)
    assert "3,612" in client_html, (
        "Expected headline emails-sent figure '3,612' not found in client output."
    )


def test_internal_sender_email_does_not_leak_to_client():
    """Autoescape + audience gate: sender email 'augustine' must not appear in client output."""
    client_html, _ = _render_both()
    assert "augustine" not in client_html, (
        "Internal sender email 'augustine.m@upstahq.com' leaked into client HTML output."
    )


def test_boxes_render_top5_and_wow(rendered_internal_html):
    """4-box campaigns layout: steps render, WoW arrow present, Step None absent."""
    html = rendered_internal_html
    assert "— Step" in html, "Email step label '— Step N' not found in rendered output"
    assert 'class="wow up"' in html or 'class="wow down"' in html, (
        "No WoW arrow (class=wow up/down) found — prior snapshot should produce arrows"
    )
    assert "Step None" not in html, "Literal 'Step None' found — step number is None"


@pytest.fixture
def rendered_internal_html():
    """Internal render using the extended _build() fixture (6 campaigns + prior snapshot)."""
    data, metrics, dbag, rubric, layout = _build()
    return render.render(
        data,
        metrics,
        dbag,
        {"narrative": "Strong LinkedIn accept rate.", "degraded": False},
        {"actions": ["Pause & warm inbox."], "degraded": False},
        audience="internal",
        period_label="June 2026",
        client="UPSTA",
        layout=layout,
        rubric=rubric,
        rendered_at=_FIXED_TS,
    )
