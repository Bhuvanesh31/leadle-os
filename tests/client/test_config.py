from pathlib import Path
import yaml

_CFG = Path(__file__).resolve().parents[2] / "config"


def test_rubric_has_grade_thresholds_and_keywords():
    r = yaml.safe_load((_CFG / "client_report_rubric.yaml").read_text())
    assert "open_rate" in r["grades"] and "reply_rate" in r["grades"]
    # each grade entry is a descending list of [min_value, letter]
    assert r["grades"]["reply_rate"][0][1] == "A"
    assert isinstance(r["positive_statuses"], list) and r["positive_statuses"]
    assert isinstance(r["meeting_statuses"], list)
    assert r["timezone"]  # default tz for the heatmap
    assert r["dayparts"]  # list of [label, start_hour, end_hour]


def test_layout_blocks_have_visibility():
    lay = yaml.safe_load((_CFG / "client_report_layout.yaml").read_text())
    keys = {b["key"] for b in lay["blocks"]}
    assert {"kpis", "campaigns", "senders", "timing", "narrative", "actions"} <= keys
    for b in lay["blocks"]:
        assert b["visibility"] in {"internal", "client", "both"}
    # operator-internal blocks must not be client-visible
    vis = {b["key"]: b["visibility"] for b in lay["blocks"]}
    assert vis["senders"] == "internal"
    assert vis["deliverability"] == "internal"
    assert vis["actions"] == "internal"
