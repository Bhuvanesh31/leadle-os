"""v1 source: parse the Drive-dumped 'Prospect list' workbook text into ClientData.

The workbook arrives as the markdown-table text emitted by the Drive MCP
read_file_content tool (the session dumps it to a file; this module reads that
file). Tables are delimited by their header row; underscores may be backslash-
escaped in the dump, so we strip backslashes from every cell.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from dashboard.client.model import (
    ClientData, Context, EmailEvent, LinkedInEvent, TargetCo, WarmLead,
)

# Header signatures (first few columns) that mark the start of each table.
_H_RESP = "| Channel | Account | Response Date | Status"
_H_TARGET = "| Company Name | Company Country | Company Location"
_H_LI = "| Event Type | Company Name | Profile Url"
_H_EMAIL = "| Company Name | To Name | Event Type | Campaign Name"
_H_ICP = "| Column 1 | Offering to the market"
_ALL_HEADERS = (_H_RESP, _H_TARGET, _H_LI, _H_EMAIL, _H_ICP,
                "| Item | Status | Responsibility")


def _cells(line: str) -> list[str]:
    return [c.strip().replace("\\", "") for c in line.strip().strip("|").split("|")]


def _is_sep(line: str) -> bool:
    return set(line.replace("|", "").replace(" ", "")) <= set(":-")


def _rows_under(lines: list[str], header_prefix: str) -> list[list[str]]:
    """Return data rows of the first table whose header starts with header_prefix."""
    out: list[list[str]] = []
    i = 0
    while i < len(lines) and not lines[i].startswith(header_prefix):
        i += 1
    i += 1  # skip header
    while i < len(lines):
        ln = lines[i]
        if not ln.strip().startswith("|"):
            i += 1
            continue
        if _is_sep(ln):
            i += 1
            continue
        if any(ln.startswith(h) for h in _ALL_HEADERS):
            break
        out.append(_cells(ln))
        i += 1
    return out


def parse(workbook_text: str, client: str) -> ClientData:
    lines = workbook_text.split("\n")
    pfx = f"{client.lower()}_"

    emails: list[EmailEvent] = []
    for r in _rows_under(lines, _H_EMAIL):
        if len(r) < 6 or r[2] in ("", "Event Type"):
            continue
        campaign = r[3]
        if not campaign.lower().startswith(pfx):
            continue
        try:
            ts = datetime.fromisoformat(r[4].replace("Z", "+00:00"))
        except ValueError:
            continue
        emails.append(EmailEvent(r[0], r[1], r[2], campaign, ts, r[5]))

    linkedin: list[LinkedInEvent] = []
    for r in _rows_under(lines, _H_LI):
        if len(r) < 6 or r[0] in ("", "Event Type"):
            continue
        linkedin.append(LinkedInEvent(r[0], r[1], r[2], r[4], r[5]))

    warm: list[WarmLead] = []
    for r in _rows_under(lines, _H_RESP):
        if len(r) < 12 or r[0] in ("", "Channel"):
            continue
        # Columns: Channel(0) Account(1) ResponseDate(2) Status(3) Response(4)
        # LinkedIn(5) Name(6) JobTitle(7) Company(8) CompanyUrl(9) CompanyWeb(10) Loc(11)
        # WarmLead has 11 fields; skip CompanyWeb (index 10), use Loc (index 11) as location.
        warm.append(WarmLead(*r[:10], r[11]))

    targets: list[TargetCo] = []
    for r in _rows_under(lines, _H_TARGET):
        if len(r) < 8 or r[0] in ("", "Company Name"):
            continue
        targets.append(TargetCo(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7]))

    channels: list[str] = []
    for r in _rows_under(lines, _H_ICP):
        if len(r) >= 3 and r[2]:
            channels = [c.strip() for c in r[2].split(",") if c.strip()]
            break

    ctx = Context(client=client, channels=channels, campaign_live_dates={}, icp={})
    return ClientData(emails, linkedin, warm, targets, ctx)


def read(client: str, workbook_path: str) -> ClientData:
    return parse(Path(workbook_path).read_text(encoding="utf-8"), client)
