# tests/client/test_compute_ladder.py
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


def test_lead_ladder_hot_from_tracker():
    lad = compute.lead_ladder(_data(), _rubric())
    hot_names = {h["name"] for h in lad["hot"]}
    assert "Dana Lin" in hot_names          # "Meeting booked" -> Hot
    assert "Salman Bari" in hot_names       # "Long follow up" -> Hot (positive)


def test_compute_all_assembles_bag():
    bag = compute.compute_all(_data(), _rubric())
    assert set(bag) >= {"kpis", "scorecard", "campaigns", "senders",
                        "deliverability", "timing", "leads", "coverage"}
    assert bag["kpis"]["emails_sent"] == 2
