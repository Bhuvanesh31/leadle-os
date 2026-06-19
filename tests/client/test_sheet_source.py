from pathlib import Path
from dashboard.client.sources import sheet_source

_FIX = Path(__file__).parent / "fixtures" / "upsta_workbook.txt"


def _data():
    return sheet_source.parse(_FIX.read_text(), client="UPSTA")


def test_email_events_filtered_to_client():
    d = _data()
    assert all(e.campaign.lower().startswith("upsta_") for e in d.emails)
    # OtherClient/Acme_Campaign_V1 row excluded; fixture has 6 UPSTA rows (2 email_sent)
    assert len(d.emails) == 6
    assert sum(1 for e in d.emails if e.event_type == "email_opened") == 2


def test_linkedin_events_parsed():
    d = _data()
    kinds = sorted(e.event_type for e in d.linkedin)
    assert kinds == ["accepted", "connect", "reply"]


def test_warm_leads_parsed_with_status():
    d = _data()
    statuses = {w.status for w in d.warm_leads}
    assert "Long follow up" in statuses and "Meeting booked" in statuses
    assert d.warm_leads[0].name == "Salman Bari"


def test_targets_carry_segment():
    d = _data()
    segs = {t.segment for t in d.targets}
    assert {"US_Set 1", "SG_Set 1"} <= segs


def test_context_channels_from_icp():
    d = _data()
    assert "Email" in d.context.channels and "Warm Calling" in d.context.channels


_MT = Path(__file__).parent / "fixtures" / "upsta_multitable.txt"


def _mt():
    return sheet_source.parse(_MT.read_text(), client="UPSTA")


def test_email_events_concatenated_across_paginated_tables():
    d = _mt()
    # two email blocks, 2 UPSTA rows each -> 4 (old parser read only the first block)
    assert len(d.emails) == 4
    assert sum(1 for e in d.emails if e.event_type == "email_sent") == 2


def test_spine_pages_and_cadence_ids_parsed_by_header():
    d = _mt()
    assert len(d.targets) == 4  # both spine pages read
    by = {t.name: t for t in d.targets}
    # header-aware: domain comes from the "Company Domain" column, not a fixed index
    assert by["Real Alloy"].domain == "realalloy.com"
    assert by["Real Alloy"].aimfox_id == "229856678"
    assert by["Real Alloy"].instantly_id == "019e89de-both"
    assert by["Pegasus Logistics"].aimfox_id == ""   # email-only prospect
    assert by["Mapletree"].instantly_id == ""        # not in any cadence yet
