# tests/client/test_campaign_boxes.py
from dashboard.client import compute
from dashboard.client.model import ClientData, EmailCampaign, LinkedInCampaign

# RUBRIC adapted to match grade()'s expected shape:
#   rubric["grades"][metric] = [[threshold_float, letter], ...] descending
# The brief had {"open_rate": [["A", 0.4], ...]} (flat, wrong order) —
# we wrap in "grades" and swap to [threshold, letter] to match compute.grade().
RUBRIC = {
    "grades": {
        "open_rate": [[0.4, "A"], [0.0, "B"]],
        "accept_rate": [[0.3, "A"], [0.0, "B"]],
    },
    "ascending_metrics": [],
}


def _data():
    return ClientData(
        email_campaigns=[
            EmailCampaign(name="hi-reply", sent=100, opened=50, clicked=10, bounced=2, replied=8),
            EmailCampaign(name="mid", sent=100, opened=40, clicked=5, bounced=1, replied=2),
            EmailCampaign(name="dead", sent=100, opened=0, clicked=0, bounced=0, replied=0),
        ],
        linkedin_campaigns=[
            LinkedInCampaign(name="li-good", invites=100, accepted=30, replied=5),
            LinkedInCampaign(name="li-dead", invites=40, accepted=0, replied=0),
        ],
        content_steps=[
            {"campaign": "hi-reply", "step": 1, "opened": 50, "sent": 100, "clicked": 10,
             "subject": "S1", "body_preview": "b1"},
            {"campaign": "dead", "step": 1, "opened": 0, "sent": 100, "clicked": 0,
             "subject": "S0", "body_preview": "b0"},
        ],
    )


def test_email_campaigns_ranked_and_filtered():
    box = compute.campaign_boxes(_data(), RUBRIC)
    names = [r["name"] for r in box["email_campaigns"]]
    assert names == ["hi-reply", "mid"]          # 'dead' (0 opens) excluded
    assert "dead" in box["excluded"]["email"]


def test_linkedin_excludes_zero_connections():
    box = compute.campaign_boxes(_data(), RUBRIC)
    assert [r["name"] for r in box["linkedin_campaigns"]] == ["li-good"]
    assert "li-dead" in box["excluded"]["linkedin"]


def test_email_steps_filtered_and_labelled():
    box = compute.campaign_boxes(_data(), RUBRIC)
    steps = box["email_steps"]
    assert len(steps) == 1                         # the 0-open 'dead' step dropped
    assert steps[0]["label"] == "hi-reply — Step 1"
    assert steps[0]["subject"] == "S1"


def test_email_steps_sorted_by_open_rate():
    d = ClientData(content_steps=[
        {"campaign": "c", "step": 1, "opened": 30, "sent": 100, "clicked": 1, "subject": "s1", "body_preview": "b1"},
        {"campaign": "c", "step": 2, "opened": 60, "sent": 100, "clicked": 2, "subject": "s2", "body_preview": "b2"},
    ])
    steps = compute.campaign_boxes(d, RUBRIC)["email_steps"]
    assert [s["step"] for s in steps] == [2, 1]   # 60% before 30%


def test_top_5_truncation():
    d = ClientData(email_campaigns=[
        EmailCampaign(name=f"c{i}", sent=100, opened=10 + i, clicked=i, bounced=0, replied=i)
        for i in range(8)
    ])
    box = compute.campaign_boxes(d, RUBRIC)
    assert len(box["email_campaigns"]) == 5
    assert [r["name"] for r in box["email_campaigns"]] == ["c7", "c6", "c5", "c4", "c3"]


def test_step_none_never_in_label():
    d = ClientData(content_steps=[
        {"campaign": "c", "step": None, "opened": 10, "sent": 100, "clicked": 0, "subject": "s", "body_preview": "b"},
    ])
    steps = compute.campaign_boxes(d, RUBRIC)["email_steps"]
    assert steps and "Step None" not in steps[0]["label"]
    assert steps[0]["label"] == "c — Step ?"
