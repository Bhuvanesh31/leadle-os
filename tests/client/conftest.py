"""Shared fixtures for client-dashboard template tests.

Builds an inline campaign-model ClientData (the same construction style as
tests/client/test_render.py), runs compute.compute_all, then render.render for
each audience. The sources.load assembler is a later task and is deliberately
not used here.
"""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml

from dashboard.client import compute, render
from dashboard.client.model import (
    ClientData,
    EmailCampaign,
    LinkedInCampaign,
    OpenEvent,
    ReplyRecord,
    TargetCo,
    WarmLead,
)

_CFG = Path(__file__).resolve().parents[2] / "config"


def load_rubric() -> dict:
    return yaml.safe_load((_CFG / "client_report_rubric.yaml").read_text())


def load_layout() -> dict:
    return yaml.safe_load((_CFG / "client_report_layout.yaml").read_text())


def _et(year, month, day, hour):
    return datetime(year, month, day, hour, tzinfo=ZoneInfo("America/New_York"))


def make_data() -> ClientData:
    """A representative dataset with opens (so the heatmap lights up), a flagged
    sender (augustine@…, bounce over threshold), email + LinkedIn campaigns, and a
    campaign name containing a '<' to exercise autoescape."""
    # 2026-06-03 is a Wednesday; spread opens across days/hours so a 'best' cell exists.
    opens = (
        [OpenEvent(channel="email", ts=_et(2026, 6, 3, 10)) for _ in range(8)]  # Wed morning
        + [OpenEvent(channel="email", ts=_et(2026, 6, 4, 10)) for _ in range(3)]  # Thu morning
        + [OpenEvent(channel="email", ts=_et(2026, 6, 2, 13))]  # Tue midday
    )
    return ClientData(
        email_campaigns=[
            EmailCampaign(name="A<b", sent=100, opened=30, clicked=6, bounced=8, replied=0),
            EmailCampaign(name="Clean SG", sent=60, opened=18, clicked=3, bounced=2, replied=0),
        ],
        linkedin_campaigns=[
            LinkedInCampaign(
                name="Founder intro",
                invites=120,
                accepted=9,
                replied=3,
                variant_message="I'm the founder at Acme",
            ),
            LinkedInCampaign(
                name="CFO angle",
                invites=80,
                accepted=5,
                replied=0,
                variant_message="we work with finance leaders",
            ),
        ],
        replies=[
            ReplyRecord(
                channel="linkedin", campaign="Founder intro", sentiment="neutral", name="Bob"
            ),
            ReplyRecord(channel="email", campaign="A<b", sentiment="positive", name="Alice"),
        ],
        warm_leads=[
            WarmLead(
                channel="LinkedIn",
                account="ACME",
                response_date="2026-06-01",
                status="Meeting booked",
                response_text="Let's connect.",
                linkedin_url="https://linkedin.com/in/carol",
                name="Carol",
                title="VP Finance",
                company="Acme",
                company_url="https://acme.com",
                location="New York",
            ),
        ],
        senders=[
            {"from_email": "augustine@upsta.co", "sent": 200, "bounced": 16},  # 8% → flagged
            {"from_email": "rajesh@upsta.co", "sent": 180, "bounced": 4},  # 2.2% → ok
        ],
        content_steps=[
            {"step": 1, "sent": 100, "opened": 24},
            {"step": 2, "sent": 90, "opened": 16},
            {"step": 3, "sent": 80, "opened": 26},  # best (highest open rate)
        ],
        opens=opens,
        targets=[
            TargetCo(
                name="Acme",
                country="US",
                location="New York",
                linkedin_url="https://linkedin.com/company/acme",
                industry="SaaS",
                size="51-200",
                segment="ICP-A",
                domain="acme.com",
                aimfox_id="ax-001",
                instantly_id="in-001",
            ),
            TargetCo(
                name="Globex",
                country="SG",
                location="Singapore",
                linkedin_url="https://linkedin.com/company/globex",
                industry="Fintech",
                size="11-50",
                segment="ICP-B",
                domain="globex.com",
                aimfox_id="ax-002",
                instantly_id="",
            ),
        ],
    )


def make_data_zero_opens() -> ClientData:
    """No opens at all → metrics.timing.best.weekday is None (the guarded path)."""
    return ClientData(
        email_campaigns=[
            EmailCampaign(name="C1", sent=50, opened=0, clicked=0, bounced=1, replied=0)
        ],
        senders=[{"from_email": "augustine@upsta.co", "sent": 50, "bounced": 1}],
        content_steps=[],
        opens=[],
    )


def _render(data: ClientData, audience: str) -> str:
    rubric = load_rubric()
    layout = load_layout()
    metrics = compute.compute_all(data, rubric)
    dbag = {
        "emails_sent": {"value": metrics["kpis"]["emails_sent"], "delta": None, "baseline": True}
    }
    return render.render(
        data,
        metrics,
        dbag,
        {"narrative": "June ran hot on volume.", "degraded": False},
        {"actions": ["Pause & warm the augustine inbox."], "degraded": False},
        audience=audience,
        period_label="June 2026",
        client="UPSTA",
        layout=layout,
        rubric=rubric,
    )


@pytest.fixture
def rendered_client_html() -> str:
    return _render(make_data(), "client")


@pytest.fixture
def rendered_internal_html() -> str:
    return _render(make_data(), "internal")


@pytest.fixture
def rendered_client_zero_opens() -> str:
    return _render(make_data_zero_opens(), "client")
