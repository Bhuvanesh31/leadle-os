# tests/client/test_render_wiring.py
from pathlib import Path

import yaml

from dashboard.client import compute
from dashboard.client.model import ClientData, EmailCampaign

_CFG = Path(__file__).resolve().parents[2] / "config"


def _rubric():
    return yaml.safe_load((_CFG / "client_report_rubric.yaml").read_text())


def test_compute_all_has_boxes():
    d = ClientData(email_campaigns=[EmailCampaign(name="c", sent=10, opened=5, clicked=1, bounced=0, replied=1)])
    m = compute.compute_all(d, _rubric())
    assert "boxes" in m
    assert "email_campaigns" in m["boxes"]
