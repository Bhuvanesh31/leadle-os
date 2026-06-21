from pathlib import Path

import yaml

from dashboard.client import compute, render
from dashboard.client.model import (
    ClientData,
    EmailCampaign,
    LinkedInCampaign,
    ReplyRecord,
    TargetCo,
    WarmLead,
)

_CFG = Path(__file__).resolve().parents[2] / "config"


def _ctx():
    data = ClientData(
        email_campaigns=[EmailCampaign(name="C1", sent=100, opened=25, clicked=5, bounced=4, replied=3)],
        linkedin_campaigns=[LinkedInCampaign(name="L1", invites=50, accepted=12, replied=2, variant_message="Hi there")],
        replies=[
            ReplyRecord(channel="email", campaign="C1", sentiment="positive", name="Alice"),
            ReplyRecord(channel="linkedin", campaign="L1", sentiment="neutral", name="Bob"),
        ],
        warm_leads=[
            WarmLead(
                channel="LinkedIn", account="UPSTA", response_date="2026-06-01",
                status="Meeting booked", response_text="Let's connect.",
                linkedin_url="https://linkedin.com/in/alice", name="Alice",
                title="VP Sales", company="Acme", company_url="https://acme.com",
                location="New York",
            ),
        ],
        senders=[{"from_email": "outreach@leadle.in", "sent": 100, "bounced": 6}],
        content_steps=[{"step": 1, "sent": 100, "opened": 25}],
        targets=[
            TargetCo(
                name="Acme", country="US", location="New York",
                linkedin_url="https://linkedin.com/company/acme",
                industry="SaaS", size="51-200", segment="ICP-A",
                domain="acme.com", aimfox_id="ax-001", instantly_id="in-001",
            ),
        ],
    )
    rubric = yaml.safe_load((_CFG / "client_report_rubric.yaml").read_text())
    layout = yaml.safe_load((_CFG / "client_report_layout.yaml").read_text())
    metrics = compute.compute_all(data, rubric)
    dbag = {"emails_sent": {"value": 2, "delta": None, "baseline": True}}
    return data, metrics, dbag, rubric, layout


def test_visible_blocks_respect_audience():
    _, _, _, _, layout = _ctx()
    client_keys = {b["key"] for b in render.visible_blocks(layout, "client")}
    assert "senders" not in client_keys
    assert "actions" not in client_keys
    assert "deliverability" not in client_keys
    assert "kpis" in client_keys
    internal_keys = {b["key"] for b in render.visible_blocks(layout, "internal")}
    assert "senders" in internal_keys


def test_client_render_hides_internal_blocks():
    data, metrics, dbag, rubric, layout = _ctx()
    html = render.render(data, metrics, dbag,
                         {"narrative": "Two meetings booked."}, {"actions": []},
                         audience="client", period_label="June 2026",
                         client="UPSTA", layout=layout, rubric=rubric)
    assert "Sender health" not in html        # internal block title absent
    assert "UPSTA" in html
    assert "Engagement" in html               # timing block present + relabelled


def test_internal_render_shows_sender_health():
    data, metrics, dbag, rubric, layout = _ctx()
    html = render.render(data, metrics, dbag,
                         {"narrative": "x"}, {"actions": ["Pause & warm inbox."]},
                         audience="internal", period_label="June 2026",
                         client="UPSTA", layout=layout, rubric=rubric)
    assert "Sender health" in html
    assert "Pause &amp; warm inbox." in html


def test_cumulative_caveat_is_internal_only():
    # I1: sheet-derived metrics are not windowed; the honest caveat shows for
    # internal only, never in the client-facing report.
    data, metrics, dbag, rubric, layout = _ctx()
    internal = render.render(data, metrics, dbag, {"narrative": "x"}, {"actions": []},
                             audience="internal", period_label="June 2026",
                             client="UPSTA", layout=layout, rubric=rubric)
    client = render.render(data, metrics, dbag, {"narrative": "x"}, {"actions": []},
                           audience="client", period_label="June 2026",
                           client="UPSTA", layout=layout, rubric=rubric)
    assert "cumulative to date" in internal
    assert "cumulative to date" not in client


def test_reach_block_visible_to_both_audiences():
    layout = yaml.safe_load((_CFG / "client_report_layout.yaml").read_text())
    for audience in ("internal", "client"):
        keys = [b["key"] for b in render.visible_blocks(layout, audience)]
        assert "reach" in keys
