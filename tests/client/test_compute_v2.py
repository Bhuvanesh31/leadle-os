"""Task 7 — KPI + scorecard tests against campaign-level ClientData.

Accumulates through Tasks 7-11. Each task section is clearly delimited.
"""

from pathlib import Path

import yaml

from dashboard.client import compute
from dashboard.client.model import (
    ClientData,
    EmailCampaign,
    LinkedInCampaign,
    ReplyRecord,
)

ROOT = Path(__file__).resolve().parents[2]
RUBRIC = yaml.safe_load((ROOT / "config/client_report_rubric.yaml").read_text())


def _data():
    return ClientData(
        email_campaigns=[
            EmailCampaign("Upsta_SFDI_V1", 414, 140, 42, 41, 0),
            EmailCampaign("Upsta_PMP_V1", 598, 215, 0, 44, 0),
        ],
        linkedin_campaigns=[
            LinkedInCampaign("Upsta_US_PMP_V1", 188, 9, 3, "Hi founder"),
            LinkedInCampaign("Upsta_Recon_V3", 46, 0, 0, "Hi recon"),
        ],
        replies=[
            ReplyRecord("linkedin", "Upsta_US_PMP_V1", "neutral", "Donna", None),
            ReplyRecord("linkedin", "Upsta_US_PMP_V1", "untagged", "", None),
        ],
    )


# ---------------------------------------------------------------------------
# Task 7: kpis() + scorecard()
# ---------------------------------------------------------------------------


def test_kpis_aggregate_and_leads_equal_positive():
    k = compute.kpis(_data(), RUBRIC)
    # email aggregates
    assert k["emails_sent"] == 1012  # 414 + 598
    assert k["bounced"] == 85  # 41 + 44
    assert round(k["bounce_rate"], 4) == round(85 / 1012, 4)  # event-based
    assert k["opened"] == 355  # 140 + 215
    assert k["clicked"] == 42  # 42 + 0
    delivered = 1012 - 85
    assert k["delivered"] == delivered
    assert round(k["open_rate"], 6) == round(355 / delivered, 6)
    # linkedin aggregates
    assert k["invites"] == 234  # 188 + 46
    assert k["accepted"] == 9
    # replies from ReplyRecord list
    assert k["li_replies"] == 2  # both channel=="linkedin"
    assert k["email_replies"] == 0
    assert k["total_replies"] == 2
    assert k["positive_replies"] == 0  # no "positive" sentiment in fixture
    assert k["neutral_replies"] == 1
    assert k["negative_replies"] == 0
    # leads == positive_replies (invariant)
    assert k["leads"] == k["positive_replies"]


def test_kpis_meetings_counts_warm_leads_with_meeting_status():
    """meetings should still count from warm_leads if present; 0 when absent."""
    k = compute.kpis(_data(), RUBRIC)
    assert k["meetings"] == 0  # no warm_leads in _data()


def test_kpis_zero_guard_division():
    """Empty data must not raise ZeroDivisionError."""
    empty = ClientData()
    k = compute.kpis(empty, RUBRIC)
    assert k["open_rate"] == 0.0
    assert k["bounce_rate"] == 0.0
    assert k["accept_rate"] == 0.0


def test_scorecard_positive_zero_emails_grades_F():  # noqa: N802
    """With emails_sent==0 but positive_replies>0, positive rate must be 0.0 (not 1.0),
    and its grade must be 'F' — proving _rate() is used instead of max(emails_sent, 1)."""
    # No email campaigns (emails_sent=0), but inject a positive reply via the legacy path
    # by directly constructing a kpis dict to isolate scorecard's zero-guard.
    k_zeroemails = {
        "emails_sent": 0,
        "fresh_prospects": 0,
        "opened": 0,
        "clicked": 0,
        "bounced": 0,
        "delivered": 0,
        "open_rate": 0.0,
        "click_rate": 0.0,
        "bounce_rate": 0.0,
        "invites": 0,
        "accepted": 0,
        "accept_rate": 0.0,
        "li_replies": 0,
        "email_replies": 0,
        "total_replies": 1,
        "positive_replies": 1,  # positive reply exists, but no emails were sent
        "neutral_replies": 0,
        "negative_replies": 0,
        "leads": 1,
        "meetings": 0,
    }
    sc = compute.scorecard(k_zeroemails, RUBRIC)
    # positive = _rate(1, 0) = 0.0, not 1.0 — zero emails means zero positive rate
    assert sc["grades"]["positive"] == "F", (
        f"Expected 'F' but got '{sc['grades']['positive']}'; "
        "scorecard() must use _rate() not max(emails_sent, 1)"
    )


def test_scorecard_open_grade_A():  # noqa: N802
    k = compute.kpis(_data(), RUBRIC)
    sc = compute.scorecard(k, RUBRIC)
    # open_rate = 355 / 927 ≈ 0.383 → >=0.20 band = A
    assert sc["grades"]["open_rate"] == "A"


def test_scorecard_has_required_keys():
    k = compute.kpis(_data(), RUBRIC)
    sc = compute.scorecard(k, RUBRIC)
    assert "grades" in sc and "overall" in sc
    for metric in ("open_rate", "reply_rate", "positive", "bounce_rate", "accept_rate"):
        assert metric in sc["grades"], f"missing grade for {metric}"


def test_scorecard_overall_is_weakest():
    """overall must equal the weakest (lowest) grade across all graded metrics."""
    k = compute.kpis(_data(), RUBRIC)
    sc = compute.scorecard(k, RUBRIC)
    order = "ABCDF"
    worst = max(sc["grades"].values(), key=lambda g: order.index(g))
    assert sc["overall"] == worst


# ---------------------------------------------------------------------------
# Task 8: campaign_table()
# ---------------------------------------------------------------------------


def test_campaign_table_email_rows_precede_linkedin_rows():
    """All Email channel rows must appear before any LinkedIn channel row."""
    rows = compute.campaign_table(_data(), RUBRIC)
    channels = [r["channel"] for r in rows]
    # Find the index of first LinkedIn row
    li_indices = [i for i, ch in enumerate(channels) if ch == "LinkedIn"]
    em_indices = [i for i, ch in enumerate(channels) if ch == "Email"]
    assert em_indices, "No Email rows returned"
    assert li_indices, "No LinkedIn rows returned"
    assert max(em_indices) < min(li_indices), "All Email rows must precede all LinkedIn rows"


def test_campaign_table_email_row_shape():
    """Email rows have the correct keys and computed values."""
    rows = compute.campaign_table(_data(), RUBRIC)
    email_rows = [r for r in rows if r["channel"] == "Email"]
    sfdi = next(r for r in email_rows if "SFDI" in r["name"])
    # sent = EmailCampaign.sent
    assert sfdi["sent"] == 414
    # reply_rate = replied / sent = 0 / 414
    assert sfdi["reply_rate"] == 0.0
    # delivered = sent - bounced = 414 - 41 = 373
    # secondary (click_rate) = clicked / delivered = 42 / 373
    assert abs(sfdi["secondary"] - 42 / 373) < 1e-9
    assert sfdi["secondary_label"] == "click"
    # open_rate = opened / delivered = 140 / 373
    assert abs(sfdi["open_rate"] - 140 / 373) < 1e-9
    # bounce_rate = bounced / sent = 41 / 414
    assert abs(sfdi["bounce_rate"] - 41 / 414) < 1e-9
    assert "grade" in sfdi


def test_campaign_table_email_sfdi_ranked_before_pmp():
    """Email rows ranked by (reply_rate desc, click_rate desc, open_rate desc).
    SFDI: click_rate=42/373≈0.113 > PMP: click_rate=0 → SFDI first."""
    rows = compute.campaign_table(_data(), RUBRIC)
    email_rows = [r for r in rows if r["channel"] == "Email"]
    names = [r["name"] for r in email_rows]
    sfdi_idx = next(i for i, n in enumerate(names) if "SFDI" in n)
    pmp_idx = next(i for i, n in enumerate(names) if "PMP" in n)
    assert sfdi_idx < pmp_idx, (
        f"SFDI (click_rate≈0.113) should rank before PMP (click_rate=0); got order {names}"
    )


def test_campaign_table_linkedin_row_shape():
    """LinkedIn rows have the correct keys and computed values."""
    rows = compute.campaign_table(_data(), RUBRIC)
    li_rows = [r for r in rows if r["channel"] == "LinkedIn"]
    pmp = next(r for r in li_rows if "PMP" in r["name"])
    # sent = invites
    assert pmp["sent"] == 188
    # reply_rate = replied / invites = 3 / 188
    assert abs(pmp["reply_rate"] - 3 / 188) < 1e-9
    # secondary (accept_rate) = accepted / invites = 9 / 188
    assert abs(pmp["secondary"] - 9 / 188) < 1e-9
    assert pmp["secondary_label"] == "accept"
    # open_rate and bounce_rate are None for LinkedIn
    assert pmp["open_rate"] is None
    assert pmp["bounce_rate"] is None
    assert "grade" in pmp


def test_campaign_table_linkedin_pmp_ranked_before_recon():
    """LinkedIn rows ranked by (reply_rate desc, accept_rate desc).
    PMP: reply_rate=3/188>0; Recon: reply_rate=0 → PMP first."""
    rows = compute.campaign_table(_data(), RUBRIC)
    li_rows = [r for r in rows if r["channel"] == "LinkedIn"]
    names = [r["name"] for r in li_rows]
    pmp_idx = next(i for i, n in enumerate(names) if "PMP" in n)
    recon_idx = next(i for i, n in enumerate(names) if "Recon" in n)
    assert pmp_idx < recon_idx, (
        f"PMP (reply_rate>0) should rank before Recon (reply_rate=0); got order {names}"
    )


def test_campaign_table_zero_guard_no_sent():
    """campaign_table must not raise when sent/invites are 0."""
    data = ClientData(
        email_campaigns=[
            EmailCampaign("ZeroEmail", sent=0, opened=0, clicked=0, bounced=0, replied=0)
        ],
        linkedin_campaigns=[LinkedInCampaign("ZeroLI", invites=0, accepted=0, replied=0)],
    )
    rows = compute.campaign_table(data, RUBRIC)
    em = next(r for r in rows if r["channel"] == "Email")
    li = next(r for r in rows if r["channel"] == "LinkedIn")
    assert em["reply_rate"] == 0.0
    assert em["secondary"] == 0.0
    assert li["reply_rate"] == 0.0
    assert li["secondary"] == 0.0


# ---------------------------------------------------------------------------
# Task 9: variants(), content_steps(), sender_wise() (rewrite)
# ---------------------------------------------------------------------------


def test_variants_returns_sorted_and_flags_winner():
    data = ClientData(
        linkedin_campaigns=[
            LinkedInCampaign(
                "Upsta_US_PMP_V1",
                invites=188,
                accepted=9,
                replied=3,
                variant_message="Hi founder, noticed you lead GTM at",
            ),
            LinkedInCampaign(
                "Upsta_Recon_V3", invites=46, accepted=0, replied=0, variant_message="Hi recon"
            ),
        ],
    )
    rows = compute.variants(data, RUBRIC)
    assert len(rows) == 2
    # sorted by reply_rate desc: PMP (3/188) before Recon (0/46)
    assert rows[0]["name"] == "Upsta_US_PMP_V1"
    assert rows[1]["name"] == "Upsta_Recon_V3"
    # rates
    assert abs(rows[0]["reply_rate"] - 3 / 188) < 1e-9
    assert abs(rows[0]["accept_rate"] - 9 / 188) < 1e-9
    assert rows[0]["replies"] == 3
    # winner = first row with replies > 0
    assert rows[0]["winner"] is True
    assert rows[1]["winner"] is False


def test_variants_hook_truncated_to_80_chars():
    long_msg = "A" * 100
    data = ClientData(
        linkedin_campaigns=[
            LinkedInCampaign("V1", invites=10, accepted=1, replied=1, variant_message=long_msg)
        ],
    )
    rows = compute.variants(data, RUBRIC)
    assert rows[0]["hook"] == long_msg[:80]


def test_variants_empty_variant_message_gives_empty_hook():
    data = ClientData(
        linkedin_campaigns=[
            LinkedInCampaign("V1", invites=10, accepted=1, replied=0, variant_message="")
        ],
    )
    rows = compute.variants(data, RUBRIC)
    assert rows[0]["hook"] == ""


def test_variants_empty_linkedin_campaigns_returns_empty():
    data = ClientData()
    rows = compute.variants(data, RUBRIC)
    assert rows == []


def test_variants_no_winner_when_all_replies_zero():
    data = ClientData(
        linkedin_campaigns=[
            LinkedInCampaign("V1", invites=50, accepted=5, replied=0),
            LinkedInCampaign("V2", invites=30, accepted=2, replied=0),
        ],
    )
    rows = compute.variants(data, RUBRIC)
    # No winner when all replies == 0
    assert all(r["winner"] is False for r in rows)


def test_variants_zero_guard_on_invites():
    data = ClientData(
        linkedin_campaigns=[LinkedInCampaign("V1", invites=0, accepted=0, replied=0)],
    )
    rows = compute.variants(data, RUBRIC)
    assert rows[0]["reply_rate"] == 0.0
    assert rows[0]["accept_rate"] == 0.0


def test_content_steps_basic():
    """open_rate = opened / sent; pin exact value."""
    data = ClientData(
        content_steps=[
            {"step": 1, "sent": 100, "opened": 24, "clicked": 6},
            {"step": 2, "sent": 50, "opened": 9, "clicked": 2},
        ],
    )
    rows = compute.content_steps(data)
    assert len(rows) == 2
    assert rows[0]["step"] == 1
    assert abs(rows[0]["open_rate"] - 0.24) < 1e-9
    assert abs(rows[1]["open_rate"] - 9 / 50) < 1e-9


def test_content_steps_zero_sent_guard():
    """Zero sent must yield open_rate == 0.0 (no ZeroDivisionError)."""
    data = ClientData(
        content_steps=[{"step": 1, "sent": 0, "opened": 0, "clicked": 0}],
    )
    rows = compute.content_steps(data)
    assert rows[0]["open_rate"] == 0.0


def test_content_steps_empty_returns_empty():
    data = ClientData()
    rows = compute.content_steps(data)
    assert rows == []


def test_sender_wise_reads_data_senders():
    """sender_wise now reads data.senders (list of dicts) not data.emails events."""
    data = ClientData(
        senders=[
            {"from_email": "alice@upsta.co", "sent": 60, "bounced": 2},
            {"from_email": "bob@upsta.co", "sent": 40, "bounced": 3},
        ],
    )
    rows = compute.sender_wise(data, RUBRIC)
    assert len(rows) == 2
    alice = next(r for r in rows if r["from_email"] == "alice@upsta.co")
    assert alice["volume"] == 60
    assert alice["bounced"] == 2
    assert abs(alice["bounce_rate"] - 2 / 60) < 1e-9
    assert "flag" in alice


def test_sender_wise_flag_at_threshold():
    """bounce_rate >= bounce_flag_threshold (0.04) should set flag=True."""
    data = ClientData(
        senders=[
            {"from_email": "high@upsta.co", "sent": 100, "bounced": 4},  # exactly 0.04 -> flag
            {"from_email": "low@upsta.co", "sent": 100, "bounced": 3},  # 0.03 -> no flag
        ],
    )
    rows = compute.sender_wise(data, RUBRIC)
    high = next(r for r in rows if r["from_email"] == "high@upsta.co")
    low = next(r for r in rows if r["from_email"] == "low@upsta.co")
    assert high["flag"] is True
    assert low["flag"] is False


def test_sender_wise_empty_senders_returns_empty():
    data = ClientData()
    rows = compute.sender_wise(data, RUBRIC)
    assert rows == []


def test_sender_wise_zero_guard_on_sent():
    data = ClientData(
        senders=[{"from_email": "x@x.co", "sent": 0, "bounced": 0}],
    )
    rows = compute.sender_wise(data, RUBRIC)
    assert rows[0]["bounce_rate"] == 0.0


def test_deliverability_still_works_with_new_sender_shape():
    """deliverability() calls sender_wise() — verify the flag key is preserved."""
    data = ClientData(
        senders=[
            {"from_email": "flagged@upsta.co", "sent": 100, "bounced": 5},  # 0.05 >= 0.04
            {"from_email": "ok@upsta.co", "sent": 100, "bounced": 1},  # 0.01 < 0.04
        ],
    )
    flags = compute.deliverability(data, RUBRIC)
    assert len(flags) == 1
    assert flags[0]["sender"] == "flagged@upsta.co"
