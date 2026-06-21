# tests/client/test_compute.py
from pathlib import Path
import yaml
from dashboard.client.sources import sheet_source
from dashboard.client import compute
from dashboard.client.model import (
    ClientData, EmailCampaign, LinkedInCampaign, ReplyRecord, TargetCo, WarmLead,
)

_FIX = Path(__file__).parent / "fixtures" / "upsta_workbook.txt"
_CFG = Path(__file__).resolve().parents[2] / "config"


def _event_data():
    """Raw event-based parse of the fixture (used by non-KPI tests)."""
    return sheet_source.parse(_FIX.read_text(), client="UPSTA")


def _rubric():
    return yaml.safe_load((_CFG / "client_report_rubric.yaml").read_text())


def _kpi_data():
    """Campaign-level ClientData mirroring the fixture's UPSTA rows.

    Fixture events per campaign:
      SFDI_V1: 1 sent, 1 opened, 1 clicked, 0 bounced
      PMP_V1:  1 sent, 1 opened, 0 clicked, 1 bounced
    LinkedIn: 1 connect(invite), 1 accepted, 1 reply
    Warm leads: "Long follow up" (positive), "Meeting booked" (meeting+positive)
    """
    return ClientData(
        email_campaigns=[
            EmailCampaign("Upsta_SFDI_V1", sent=1, opened=1, clicked=1, bounced=0, replied=0),
            EmailCampaign("Upsta_PMP_V1",  sent=1, opened=1, clicked=0, bounced=1, replied=0),
        ],
        linkedin_campaigns=[
            LinkedInCampaign("Upsta_LI_V1", invites=1, accepted=1, replied=1),
        ],
        replies=[
            ReplyRecord("linkedin", "Upsta_LI_V1", "neutral", "Donna Saunders", None),
        ],
        warm_leads=[
            WarmLead("LinkedIn", "Utopia Brands", "5/15/2026", "Long follow up",
                     "Hi Rajesh", "https://linkedin.com/in/salman", "Salman Bari",
                     "Senior Director Finance", "Utopia Brands", "", "Texas"),
            WarmLead("Email", "Red Nucleus", "6/12/2026", "Meeting booked",
                     "Sure, let's talk", "https://linkedin.com/in/dana-cfo", "Dana Lin",
                     "CFO", "Red Nucleus", "", "Ohio"),
        ],
    )


def test_kpis_count_events():
    k = compute.kpis(_kpi_data(), _rubric())
    assert k["emails_sent"] == 2          # two email campaigns, 1 sent each
    assert k["opened"] == 2
    assert k["clicked"] == 1
    assert k["bounced"] == 1
    assert k["invites"] == 1 and k["accepted"] == 1
    assert k["li_replies"] == 1           # 1 linkedin ReplyRecord
    # open_rate = opened / delivered = 2 / (2-1) = 2.0, capped by math; deliver=1
    assert k["open_rate"] == 2.0          # 2 opened / (2 sent - 1 bounced)
    # tracker: "Long follow up" + "Meeting booked" both positive; one is a meeting
    assert k["positive_replies"] == 0     # warm_leads no longer drive positive_replies
    assert k["meetings"] == 1


def test_grade_ascending_metric_bounce():
    r = _rubric()
    assert compute.grade("bounce_rate", 0.0, r) == "A"
    assert compute.grade("bounce_rate", 0.05, r) == "C"


def test_grade_descending_metric_reply():
    r = _rubric()
    assert compute.grade("reply_rate", 0.08, r) == "A"
    assert compute.grade("reply_rate", 0.03, r) == "C"


def test_campaign_table_groups_by_campaign():
    """campaign_table reads from email_campaigns + linkedin_campaigns.
    _kpi_data() provides 2 email campaigns + 1 LinkedIn campaign."""
    rows = compute.campaign_table(_kpi_data(), _rubric())
    email_rows = [r for r in rows if r["channel"] == "Email"]
    li_rows = [r for r in rows if r["channel"] == "LinkedIn"]
    names = {row["name"] for row in rows}
    assert "Upsta_SFDI_V1" in names
    sfdi = next(r for r in email_rows if r["name"] == "Upsta_SFDI_V1")
    assert sfdi["channel"] == "Email"
    assert sfdi["sent"] == 1           # EmailCampaign.sent = 1
    assert sfdi["secondary_label"] == "click"
    assert li_rows, "Expected at least one LinkedIn row"
    assert li_rows[0]["secondary_label"] == "accept"


def _reach_targets():
    return [
        TargetCo("Real Alloy", "US", "", "", "Mfg", "", "US_Set 1", "realalloy.com",
                 aimfox_id="A1", aimfox_urn="U1", instantly_id="I1"),   # both
        TargetCo("Metropolitan", "US", "", "", "Log", "", "US_Set 1", "gomwd.com",
                 aimfox_id="A2", aimfox_urn="U2", instantly_id=""),     # LinkedIn only
        TargetCo("Pegasus", "US", "", "", "Log", "", "US_Set 1", "pegasus.com",
                 aimfox_id="", aimfox_urn="", instantly_id="I3"),       # email only
        TargetCo("Mapletree", "SG", "", "", "RE", "", "SG_Set 1", "mapletree.com.sg"),  # neither
    ]


def test_channel_reach_counts_unique_per_channel_and_both():
    r = compute.channel_reach(ClientData(targets=_reach_targets()))
    assert r == {"linkedin_reached": 2, "email_reached": 2, "both_reached": 1}


def test_channel_reach_dedupes_on_id_value():
    ts = _reach_targets() + [
        TargetCo("Dup", "US", "", "", "Mfg", "", "US_Set 1", "dup.com",
                 aimfox_id="A1", instantly_id="I1")]  # repeats A1/I1
    r = compute.channel_reach(ClientData(targets=ts))
    assert r == {"linkedin_reached": 2, "email_reached": 2, "both_reached": 1}
