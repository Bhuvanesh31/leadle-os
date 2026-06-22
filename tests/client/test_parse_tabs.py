"""Tests for the provider-agnostic _parse_tabs core."""

from dashboard.client.sources import sheet_source


def test_parse_tabs_builds_clientdata_from_string_rows():
    tabs = {
        "Prospect Data-US": [
            ["Company Name", "Company Country", "Aimfox ID", "Instantly ID"],
            ["Acme", "US", "229856678", "in-1"],
            ["", "", "", ""],  # empty row must be skipped
        ],
        "Webhook - LinkedIn": [
            ["Event Type", "Reply Sentiment", "Campaign Name", "Prospect Name", "Timestamp"],
            ["reply", "neutral", "Upsta_US", "Bob", "2026-06-01 10:00:00"],
        ],
        "Webhook - Email": [
            ["Event Type", "Event Timestamp"],
            ["email_opened", "2026-06-02 09:00:00"],
            ["email_sent", "2026-06-02 09:00:00"],  # not an open
        ],
        "Response Tracker": [
            [
                "Channel",
                "Account",
                "Response Date",
                "Status",
                "Response",
                "LinkedIn",
                "Name",
                "Job Title",
                "Company",
                "Company Url",
                "Loc",
            ],
            [
                "LinkedIn",
                "UPSTA",
                "2026-06-01",
                "Meeting",
                "yes",
                "u/bob",
                "Bob",
                "VP",
                "Acme",
                "acme.com",
                "NY",
            ],
        ],
    }
    d = sheet_source._parse_tabs(tabs)
    assert len(d.targets) == 1 and d.targets[0].aimfox_id == "229856678"
    assert len(d.replies) == 1 and d.replies[0].sentiment == "neutral"
    assert len(d.opens) == 1 and d.opens[0].ts is not None
    assert len(d.warm_leads) == 1 and d.warm_leads[0].name == "Bob"


def test_parse_tabs_omits_missing_tabs_without_crashing():
    d = sheet_source._parse_tabs({})  # no tabs at all
    assert d.targets == [] and d.replies == [] and d.opens == [] and d.warm_leads == []
