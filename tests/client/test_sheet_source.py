from pathlib import Path
from dashboard.client.sources import sheet_source

_FIX = Path(__file__).parent / "fixtures" / "upsta_workbook.txt"


def _data():
    return sheet_source.parse(_FIX.read_text(), client="UPSTA")


def test_email_events_filtered_to_client():
    d = _data()
    assert all(e.campaign.lower().startswith("upsta_") for e in d.emails)
    # OtherClient/Acme_Campaign_V1 row excluded
    assert len(d.emails) == 5
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
