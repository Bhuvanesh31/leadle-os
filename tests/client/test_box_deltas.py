# tests/client/test_box_deltas.py
from dashboard.client import snapshots

LOWER_BETTER = {"bounce_rate"}


def test_kpi_up_down_and_baseline():
    cur = {"kpis": {"leads": 10, "email_replies": 5}, "boxes": {"email_campaigns": []}}
    prior = {"kpis": {"leads": 7}}
    d = snapshots.box_deltas(cur, prior)
    assert d["kpis.leads"]["dir"] == "up" and d["kpis.leads"]["delta"] == 3
    assert d["kpis.email_replies"]["dir"] == "baseline"      # not in prior


def test_bounce_rate_inverted():
    cur = {"kpis": {}, "boxes": {"email_campaigns": [{"name": "c1", "bounce_rate": 0.02, "reply_rate": 0.05}]}}
    prior = {"boxes": {"email_campaigns": [{"name": "c1", "bounce_rate": 0.05, "reply_rate": 0.03}]}}
    d = snapshots.box_deltas(cur, prior)
    assert d["campaign.c1.bounce_rate"]["dir"] == "up"       # bounce went DOWN -> good -> green/up
    assert d["campaign.c1.reply_rate"]["dir"] == "up"        # reply went up -> good


def test_no_prior_is_baseline():
    cur = {"kpis": {"leads": 4}, "boxes": {"email_campaigns": []}}
    d = snapshots.box_deltas(cur, None)
    assert d["kpis.leads"]["dir"] == "baseline"


def test_variants_keyed_by_name():
    cur = {"kpis": {}, "boxes": {"linkedin_variants": [{"name": "v1", "reply_rate": 0.05, "accept_rate": 0.3}]}}
    prior = {"boxes": {"linkedin_variants": [{"name": "v1", "reply_rate": 0.02, "accept_rate": 0.3}]}}
    d = snapshots.box_deltas(cur, prior)
    assert d["variant.v1.reply_rate"]["dir"] == "up"
