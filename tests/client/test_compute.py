# tests/client/test_compute.py
from pathlib import Path
import yaml
from dashboard.client.sources import sheet_source
from dashboard.client import compute

_FIX = Path(__file__).parent / "fixtures" / "upsta_workbook.txt"
_CFG = Path(__file__).resolve().parents[2] / "config"


def _data():
    return sheet_source.parse(_FIX.read_text(), client="UPSTA")


def _rubric():
    return yaml.safe_load((_CFG / "client_report_rubric.yaml").read_text())


def test_kpis_count_events():
    k = compute.kpis(_data(), _rubric())
    assert k["emails_sent"] == 2          # two email_sent rows for UPSTA
    assert k["opened"] == 2
    assert k["clicked"] == 1
    assert k["bounced"] == 1
    assert k["invites"] == 1 and k["accepted"] == 1 and k["li_replied"] == 1
    assert k["open_rate"] == 1.0          # 2 opened / 2 sent
    # tracker: "Long follow up" + "Meeting booked" both positive; one is a meeting
    assert k["positive_replies"] == 2
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
    rows = compute.campaign_table(_data(), _rubric())
    names = {row["name"] for row in rows}
    assert "Upsta_SFDI_V1" in names
    sfdi = next(r for r in rows if r["name"] == "Upsta_SFDI_V1")
    assert sfdi["channel"] == "Email"
    assert sfdi["sends"] == 1   # one email_sent for SFDI in fixture
