from pathlib import Path
import yaml
from dashboard.client.sources import sheet_source
from dashboard.client import compute, render

_FIX = Path(__file__).parent / "fixtures" / "upsta_workbook.txt"
_CFG = Path(__file__).resolve().parents[2] / "config"


def _ctx():
    data = sheet_source.parse(_FIX.read_text(), client="UPSTA")
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


def test_reach_block_visible_to_both_audiences():
    layout = yaml.safe_load((_CFG / "client_report_layout.yaml").read_text())
    for audience in ("internal", "client"):
        keys = [b["key"] for b in render.visible_blocks(layout, audience)]
        assert "reach" in keys
