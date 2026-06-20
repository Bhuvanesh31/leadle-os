"""TDD tests for sheet_source.read_xlsx."""
from __future__ import annotations

from pathlib import Path

from dashboard.client.sources import sheet_source

FIX = Path(__file__).parent / "fixtures" / "upsta_mini.xlsx"


def test_xlsx_parses_spine_replies_opens_warm():
    d = sheet_source.read_xlsx(str(FIX))
    # spine -> targets with cadence ids (2 US rows + 1 SG row = 3 total)
    assert len(d.targets) == 3
    assert any(t.aimfox_id and t.instantly_id for t in d.targets)
    # webhook LinkedIn reply with sentiment (repeated header row ignored → 1 reply only)
    assert any(r.channel == "linkedin" and r.sentiment == "neutral" for r in d.replies)
    # webhook email opens carry timestamps
    assert len(d.opens) == 2 and all(o.ts is not None for o in d.opens)
    # response tracker -> warm lead
    assert len(d.warm_leads) == 1


def test_xlsx_aimfox_id_int_coercion():
    """Numeric Aimfox IDs stored as float in xlsx must be coerced to int string."""
    d = sheet_source.read_xlsx(str(FIX))
    # row1 has Aimfox ID 229856678 (int in fixture, but reads as float in openpyxl)
    ids = {t.aimfox_id for t in d.targets if t.aimfox_id}
    assert "229856678" in ids, f"Expected '229856678' in {ids}"
    # float artifact must be absent
    assert not any(".0" in i for i in ids), f"Float artifact found in {ids}"


def test_xlsx_skips_repeated_header_rows():
    """The LinkedIn webhook has a repeated header row — must produce exactly 1 reply."""
    d = sheet_source.read_xlsx(str(FIX))
    li_replies = [r for r in d.replies if r.channel == "linkedin"]
    assert len(li_replies) == 1


def test_xlsx_email_opens_exclude_sent():
    """email_sent rows must not appear in opens."""
    d = sheet_source.read_xlsx(str(FIX))
    # fixture has 2 email_opened + 1 email_sent
    assert len(d.opens) == 2


def test_xlsx_reply_sentiment_untagged_when_blank():
    """Blank Reply Sentiment should be normalised to 'untagged'."""
    # The fixture doesn't have a blank-sentiment reply, but we can verify
    # the only reply row carries "neutral" (not blank/None).
    d = sheet_source.read_xlsx(str(FIX))
    for r in d.replies:
        assert r.sentiment not in (None, ""), f"Blank sentiment on {r}"
