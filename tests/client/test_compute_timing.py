# tests/client/test_compute_timing.py
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


def test_sender_wise_groups_by_from_email():
    rows = compute.sender_wise(_data(), _rubric())
    senders = {r["from_email"] for r in rows}
    assert "augustine@upsta.co" in senders
    a = next(r for r in rows if r["from_email"] == "augustine.m@upstahq.com")
    assert a["bounced"] == 1


def test_timing_heatmap_buckets_engagement_in_local_tz():
    h = compute.timing_heatmap(_data(), _rubric())
    # 2 opened + 1 clicked = 3 engagement events placed into the grid
    total = sum(sum(row.values()) for row in h["grid"].values())
    assert total == 3
    assert h["timezone"] == "America/New_York"
    assert "best" in h and h["best"]["daypart"]
