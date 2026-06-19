# Client Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an on-demand, per-client outreach **campaign report** (HTML) rendered for two audiences from the client's Google "Prospect list" workbook, matching the approved metric-dense layout, with UPSTA as the first sample.

**Architecture:** A self-contained `dashboard/client/` package: a *source* layer parses a locally-dumped workbook into a normalized `ClientData`; a deterministic *compute* layer produces the metric bag (KPIs, grades, campaign table, sender health, engagement-timing heatmap, lead ladder, coverage); a *snapshot* store diffs against the prior render for WoW/MoM deltas; two *agents* (Sonnet) write the narrative + actions; a *render* CLI assembles config-gated blocks into HTML per `(client, period, audience)`. MCP tools (Drive, Supabase) are session-orchestrated — the session dumps the workbook to a raw file that the script reads, mirroring this repo's HubSpot ingestion pattern.

**Tech Stack:** Python 3.12, dataclasses, `zoneinfo` (stdlib), Jinja2, PyYAML, `anthropic` AsyncAnthropic via existing `dashboard.agents._client.run_agent`, pytest.

## Global Constraints

- Python 3.12; `from __future__ import annotations` at top of every module (matches repo).
- Read-only against all source systems. No writes to Instantly/Aimfox/HubSpot/Fathom.
- Config-driven: grade thresholds, block order, per-block audience visibility, positive/meeting status keywords, timezone, toggles all live in `config/client_report_*.yaml`. No hard-coded thresholds in Python.
- Client scoping key: case-insensitive campaign-name prefix (UPSTA → `Upsta_*`).
- Voice: `LEADLE_CONTEXT.md` constraints. Client render forbids internal vocabulary (Signal-to-Motion, buying posture, funnel leak, hygiene) and operator-internal blocks.
- Agent model: `claude-sonnet-4-6`. Agents must degrade to a fallback (never hard-fail the render).
- Every block degrades independently: missing/empty data renders a neutral "not available this period" state; the report still renders.
- Test command: `python -m pytest tests/client/ -v`. Render without API: `--skip-agents`.
- Spec: `docs/superpowers/specs/2026-06-17-client-dashboard-design.md`. Data shape: `docs/data-shape/prospect-list-sheet.md`.

---

## File Structure

```
dashboard/client/
  __init__.py
  model.py                     # dataclasses: EmailEvent, LinkedInEvent, WarmLead, TargetCo, Context, ClientData
  sources/
    __init__.py
    base.py                    # ClientSource Protocol
    sheet_source.py            # parse(workbook_text, client) + read(client, workbook_path)
  compute.py                   # kpis/grades/campaign_table/sender_wise/timing_heatmap/lead_ladder/coverage/compute_all
  snapshots.py                 # LocalJsonStore + deltas()
  agents/
    __init__.py
    narrative.py               # async synthesize(metrics, audience, client)
    actions.py                 # async synthesize(metrics, client)
  render.py                    # render(...) + main() CLI
  templates/
    report_base.html.j2
    report.html.j2
    blocks/{kpis,scorecard,campaigns,content,senders,timing,deliverability,leads,narrative,actions,targets}.html.j2
config/
  client_report_rubric.yaml
  client_report_layout.yaml
schemas/
  0007_client_dashboard_snapshots.sql
.claude/commands/
  render-client-report.md
tests/client/
  __init__.py
  fixtures/upsta_workbook.txt  # trimmed deterministic workbook slice
  test_sheet_source.py
  test_compute.py
  test_snapshots.py
  test_agents.py
  test_render.py
```

---

### Task 1: Package scaffold + normalized model

**Files:**
- Create: `dashboard/client/__init__.py` (empty)
- Create: `dashboard/client/model.py`
- Create: `tests/client/__init__.py` (empty)
- Test: `tests/client/test_model.py`

**Interfaces:**
- Produces: dataclasses `EmailEvent(company,to_name,event_type,campaign,ts:datetime,from_email)`, `LinkedInEvent(event_type,company,profile_url,prospect_name,title)`, `WarmLead(channel,account,response_date,status,response_text,linkedin_url,name,title,company,company_url,location)`, `TargetCo(name,country,location,linkedin_url,industry,size,segment,domain)`, `Context(client,channels:list[str],campaign_live_dates:dict,icp:dict)`, `ClientData(emails:list[EmailEvent],linkedin:list[LinkedInEvent],warm_leads:list[WarmLead],targets:list[TargetCo],context:Context)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/client/test_model.py
from datetime import datetime, timezone
from dashboard.client.model import (
    EmailEvent, LinkedInEvent, WarmLead, TargetCo, Context, ClientData,
)


def test_clientdata_holds_normalized_records():
    e = EmailEvent("Acme", "Jane", "email_opened", "Upsta_SFDI_V1",
                   datetime(2026, 6, 4, 13, 0, tzinfo=timezone.utc), "augustine@upsta.co")
    li = LinkedInEvent("accepted", "Acme", "https://li/x", "Jane Roe", "CFO")
    wl = WarmLead("LinkedIn", "Rajesh", "5/15/2026", "Long follow up", "Hi...",
                  "https://li/x", "Jane Roe", "CFO", "Acme", "https://acme", "TX")
    tc = TargetCo("Acme", "United States", "TX", "https://li/acme", "Mfg", "501-1,000",
                  "US_Set 1", "acme.com")
    ctx = Context("UPSTA", ["LinkedIn", "Email"], {"Email": "2026-06-03"}, {"seg": "x"})
    data = ClientData([e], [li], [wl], [tc], ctx)
    assert data.emails[0].campaign == "Upsta_SFDI_V1"
    assert data.context.client == "UPSTA"
    assert data.linkedin[0].event_type == "accepted"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/client/test_model.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'dashboard.client'`

- [ ] **Step 3: Write minimal implementation**

```python
# dashboard/client/model.py
"""Normalized model: the contract every ClientSource returns and compute consumes."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class EmailEvent:
    company: str
    to_name: str
    event_type: str
    campaign: str
    ts: datetime
    from_email: str


@dataclass
class LinkedInEvent:
    event_type: str
    company: str
    profile_url: str
    prospect_name: str
    title: str


@dataclass
class WarmLead:
    channel: str
    account: str
    response_date: str
    status: str
    response_text: str
    linkedin_url: str
    name: str
    title: str
    company: str
    company_url: str
    location: str


@dataclass
class TargetCo:
    name: str
    country: str
    location: str
    linkedin_url: str
    industry: str
    size: str
    segment: str
    domain: str


@dataclass
class Context:
    client: str
    channels: list[str] = field(default_factory=list)
    campaign_live_dates: dict = field(default_factory=dict)
    icp: dict = field(default_factory=dict)


@dataclass
class ClientData:
    emails: list[EmailEvent] = field(default_factory=list)
    linkedin: list[LinkedInEvent] = field(default_factory=list)
    warm_leads: list[WarmLead] = field(default_factory=list)
    targets: list[TargetCo] = field(default_factory=list)
    context: Context | None = None
```

Also create empty `dashboard/client/__init__.py` and `tests/client/__init__.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/client/test_model.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dashboard/client/__init__.py dashboard/client/model.py tests/client/__init__.py tests/client/test_model.py
git commit -m "feat(client-dash): normalized ClientData model"
```

---

### Task 2: Config — rubric + layout

**Files:**
- Create: `config/client_report_rubric.yaml`
- Create: `config/client_report_layout.yaml`
- Test: `tests/client/test_config.py`

**Interfaces:**
- Produces: `client_report_rubric.yaml` keys → `grades` (per-metric threshold lists), `positive_statuses`, `meeting_statuses`, `timezone`, `dayparts`, `toggles.show_data_quality_notes`. `client_report_layout.yaml` → `blocks` (ordered list of `{key, title, visibility}` with `visibility in {internal, client, both}`).

- [ ] **Step 1: Write the failing test**

```python
# tests/client/test_config.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/client/test_config.py -v`
Expected: FAIL with `FileNotFoundError`

- [ ] **Step 3: Write the config files**

```yaml
# config/client_report_rubric.yaml
# Letter grades from fixed thresholds (v1). v2 replaces with portfolio percentiles.
# Each metric: descending list of [min_fraction, letter]; first match wins.
grades:
  open_rate:   [[0.55, "A"], [0.40, "B"], [0.25, "C"], [0.0, "D"]]
  reply_rate:  [[0.07, "A"], [0.04, "B"], [0.02, "C"], [0.0, "D"]]
  positive:    [[0.03, "A"], [0.015, "B"], [0.007, "C"], [0.0, "D"]]
  bounce_rate: [[0.0, "A"], [0.02, "B"], [0.04, "C"], [0.06, "D"]]   # lower is better (ascending)
  accept_rate: [[0.30, "A"], [0.20, "B"], [0.12, "C"], [0.0, "D"]]
# bounce_rate is "lower is better": compute applies it ascending (see compute.grade()).
ascending_metrics: ["bounce_rate"]
# Tracker status -> outcome classification (case-insensitive substring match).
positive_statuses: ["interested", "positive", "follow up", "long follow up", "meeting", "call booked"]
meeting_statuses: ["meeting", "call booked", "demo"]
# Engagement-timing heatmap.
timezone: "America/Detroit"   # UPSTA primary region; SG events fold in with a caveat note
dayparts:
  - ["Early 5-9",     5,  9]
  - ["Morning 9-12",  9,  12]
  - ["Midday 12-15",  12, 15]
  - ["Afternoon 15-18", 15, 18]
  - ["Evening 18-22", 18, 22]
toggles:
  show_data_quality_notes: true
```

```yaml
# config/client_report_layout.yaml
# Block order + per-audience visibility. render.py --audience filters on this.
blocks:
  - {key: kpis,          title: "Headline",                  visibility: both}
  - {key: scorecard,     title: "Benchmark scorecard",       visibility: both}
  - {key: campaigns,     title: "Which campaign performed",  visibility: both}
  - {key: content,       title: "Which content performed",   visibility: both}
  - {key: senders,       title: "Sender health",             visibility: internal}
  - {key: timing,        title: "Engagement timing",         visibility: both}
  - {key: deliverability, title: "Deliverability flags",     visibility: internal}
  - {key: leads,         title: "Warm & named leads",        visibility: both}
  - {key: narrative,     title: "Narrative",                 visibility: both}
  - {key: actions,       title: "Actions this period",       visibility: internal}
  - {key: targets,       title: "Targets next period",       visibility: both}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/client/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add config/client_report_rubric.yaml config/client_report_layout.yaml tests/client/test_config.py
git commit -m "feat(client-dash): rubric + layout config"
```

---

### Task 3: Sheet source — parse workbook text into ClientData

**Files:**
- Create: `dashboard/client/sources/__init__.py` (empty)
- Create: `dashboard/client/sources/base.py`
- Create: `dashboard/client/sources/sheet_source.py`
- Create: `tests/client/fixtures/upsta_workbook.txt` (deterministic slice below)
- Test: `tests/client/test_sheet_source.py`

**Interfaces:**
- Consumes: `dashboard.client.model.*`.
- Produces: `sheet_source.parse(workbook_text: str, client: str) -> ClientData`; `sheet_source.read(client: str, workbook_path: str) -> ClientData`; `base.ClientSource` Protocol with `read(client, **kw) -> ClientData`. Client filter: email events kept when `campaign` lower-startswith `f"{client.lower()}_"`. The workbook text is the markdown-table dump produced by the Drive MCP `read_file_content` tool.

- [ ] **Step 1: Create the fixture**

```text
# tests/client/fixtures/upsta_workbook.txt
| Column 1 | Offering to the market | Channels | Target Market Segment |
| :-: | :-: | :-: | :-: |
| ICP 1 |  | LinkedIn, Email, Warm Calling | Mid to large enterprise |

| Item | Status | Responsibility | Target Completion Date | Actual Completion Date | Comments |
| :-: | :-: | :-: | :-: | :-: | :-: |
| Campaign kickstart | Completed | Leadle | 12 May 2026 | 14 May 2026 | Linkedin first / 3 June Email |

| Channel | Account | Response Date | Status | Response | LinkedIn | Name | Job Title | Company | Company Url | Company Web | Loc |
| :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: |
| LinkedIn | Rajesh Viswanath | 5/15/2026 | Long follow up | Hi Rajesh, keep my contact. | https://www.linkedin.com/in/salman-bari-26ba62b5/ | Salman Bari | Senior Director Finance | Utopia Brands | https://www.linkedin.com/company/utopiabrands/ | http://utopiabrands.com | Texas, United States |
| Email | Augustine | 6/12/2026 | Meeting booked | Sure, let's talk Thursday. | https://www.linkedin.com/in/dana-cfo/ | Dana Lin | CFO | Red Nucleus | https://www.linkedin.com/company/red-nucleus/ | http://rednucleus.com | Ohio, United States |

| Company Name | Company Country | Company Location | Company Linked In URL | Primary Industry | Size (Text) | Account Process | Company Domain |
| :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: |
| Pegasus Logistics Group | United States | Coppell, TX | https://www.linkedin.com/company/pegasus-logistics-group | Transportation | 501-1,000 | US_Set 1 | pegasuslogisticsgroup.com |
| Unisteel Technology Limited | Singapore | Singapore | https://www.linkedin.com/company/unisteel-technology-limited | Manufacturing | 1,001-5,000 | SG_Set 1 | unisteel.com |

| Event Type | Company Name | Profile Url | Company Url | Prospect Name | Title |
| :-: | :-: | :-: | :-: | :-: | :-: |
| connect | MetalTek International | https://www.linkedin.com/in/karen-loritz/ |  | Karen Loritz | Chief Financial Officer |
| accepted | The Master Lock Company | https://www.linkedin.com/in/jesse-herron/ |  | Jesse Herron | Chief Financial Officer |
| reply | Huntsville Utilities | https://www.linkedin.com/in/donna-saunders/ |  | Donna Saunders | Controller |

| Company Name | To Name | Event Type | Campaign Name | Event Timestamp | From Email |
| :-: | :-: | :-: | :-: | :-: | :-: |
| Lovesac |  | email_sent | Upsta_SFDI_V1 | 2026-06-04T13:33:26.012Z | augustine@upsta.co |
| Red Nucleus |  | email_opened | Upsta_PMP_V1 | 2026-06-10T16:58:21.302Z | augustine.m@upstaanalytics.co |
| Lovesac |  | email_opened | Upsta_SFDI_V1 | 2026-06-09T16:10:00.000Z | augustine@upsta.co |
| PANTHERx |  | link_clicked | Upsta_SFDI_V1 | 2026-06-12T14:58:40.888Z | augustine@upstaanalytics.co |
| BouncedCo |  | email_bounced | Upsta_PMP_V1 | 2026-06-05T10:00:00.000Z | augustine.m@upstahq.com |
| OtherClient |  | email_sent | Acme_Campaign_V1 | 2026-06-04T13:00:00.000Z | x@acme.co |
```

- [ ] **Step 2: Write the failing test**

```python
# tests/client/test_sheet_source.py
from pathlib import Path
from dashboard.client.sources import sheet_source

_FIX = Path(__file__).parent / "fixtures" / "upsta_workbook.txt"


def _data():
    return sheet_source.parse(_FIX.read_text(), client="UPSTA")


def test_email_events_filtered_to_client():
    d = _data()
    assert all(e.campaign.lower().startswith("upsta_") for e in d.emails)
    # OtherClient/Acme_Campaign_V1 row excluded
    assert len(d.emails) == 5
    assert sum(1 for e in d.emails if e.event_type == "email_opened") == 2


def test_linkedin_events_parsed():
    d = _data()
    kinds = sorted(e.event_type for e in d.linkedin)
    assert kinds == ["accepted", "connect", "reply"]


def test_warm_leads_parsed_with_status():
    d = _data()
    statuses = {w.status for w in d.warm_leads}
    assert "Long follow up" in statuses and "Meeting booked" in statuses
    assert d.warm_leads[0].name == "Salman Bari"


def test_targets_carry_segment():
    d = _data()
    segs = {t.segment for t in d.targets}
    assert {"US_Set 1", "SG_Set 1"} <= segs


def test_context_channels_from_icp():
    d = _data()
    assert "Email" in d.context.channels and "Warm Calling" in d.context.channels
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/client/test_sheet_source.py -v`
Expected: FAIL with `ModuleNotFoundError: dashboard.client.sources`

- [ ] **Step 4: Write the implementation**

```python
# dashboard/client/sources/base.py
from __future__ import annotations

from typing import Protocol

from dashboard.client.model import ClientData


class ClientSource(Protocol):
    def read(self, client: str, **kwargs) -> ClientData: ...
```

```python
# dashboard/client/sources/sheet_source.py
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
    """Yield data rows of the first table whose header starts with header_prefix."""
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
        warm.append(WarmLead(*r[:12]))

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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/client/test_sheet_source.py -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Commit**

```bash
git add dashboard/client/sources tests/client/test_sheet_source.py tests/client/fixtures/upsta_workbook.txt
git commit -m "feat(client-dash): sheet source parses workbook into ClientData"
```

---

### Task 4: Compute — KPIs, grades, campaign table

**Files:**
- Create: `dashboard/client/compute.py`
- Test: `tests/client/test_compute.py`

**Interfaces:**
- Consumes: `ClientData`, rubric dict.
- Produces: `compute.kpis(data, rubric) -> dict` (keys: emails_sent, opened, clicked, bounced, open_rate, click_rate, bounce_rate, invites, accepted, li_replied, accept_rate, li_reply_rate, positive_replies, meetings); `compute.grade(metric, value, rubric) -> str`; `compute.scorecard(kpis, rubric) -> dict`; `compute.campaign_table(data, rubric) -> list[dict]` (per campaign: name, channel, sends, reply_or_accept_rate, positives, grade).

- [ ] **Step 1: Write the failing test**

```python
# tests/client/test_compute.py
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


def test_kpis_count_events():
    k = compute.kpis(_data(), _rubric())
    assert k["emails_sent"] == 2          # two email_sent rows for UPSTA
    assert k["opened"] == 2
    assert k["clicked"] == 1
    assert k["bounced"] == 1
    assert k["invites"] == 1 and k["accepted"] == 1 and k["li_replied"] == 1
    assert k["open_rate"] == 1.0          # 2 opened / 2 sent
    # tracker: "Long follow up" + "Meeting booked" both positive; one is a meeting
    assert k["positive_replies"] == 2
    assert k["meetings"] == 1


def test_grade_ascending_metric_bounce():
    r = _rubric()
    assert compute.grade("bounce_rate", 0.0, r) == "A"
    assert compute.grade("bounce_rate", 0.05, r) == "C"


def test_grade_descending_metric_reply():
    r = _rubric()
    assert compute.grade("reply_rate", 0.08, r) == "A"
    assert compute.grade("reply_rate", 0.03, r) == "C"


def test_campaign_table_groups_by_campaign():
    rows = compute.campaign_table(_data(), _rubric())
    names = {row["name"] for row in rows}
    assert "Upsta_SFDI_V1" in names
    sfdi = next(r for r in rows if r["name"] == "Upsta_SFDI_V1")
    assert sfdi["channel"] == "Email"
    assert sfdi["sends"] == 1   # one email_sent for SFDI in fixture
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/client/test_compute.py -v`
Expected: FAIL with `ModuleNotFoundError: dashboard.client.compute`

- [ ] **Step 3: Write the implementation**

```python
# dashboard/client/compute.py
"""Deterministic compute over ClientData. Pure functions, no I/O, no agents."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime

from dashboard.client.model import ClientData


def _rate(n: int, d: int) -> float:
    return (n / d) if d else 0.0


def _status_hits(status: str, keywords: list[str]) -> bool:
    s = (status or "").lower()
    return any(k in s for k in keywords)


def kpis(data: ClientData, rubric: dict) -> dict:
    ec = Counter(e.event_type for e in data.emails)
    sent = ec.get("email_sent", 0)
    opened = ec.get("email_opened", 0)
    clicked = ec.get("link_clicked", 0)
    bounced = ec.get("email_bounced", 0)
    lc = Counter(e.event_type for e in data.linkedin)
    invites = lc.get("connect", 0)
    accepted = lc.get("accepted", 0)
    li_replied = lc.get("reply", 0)
    positive = sum(1 for w in data.warm_leads
                   if _status_hits(w.status, rubric["positive_statuses"]))
    meetings = sum(1 for w in data.warm_leads
                   if _status_hits(w.status, rubric["meeting_statuses"]))
    return {
        "emails_sent": sent, "opened": opened, "clicked": clicked, "bounced": bounced,
        "open_rate": _rate(opened, sent), "click_rate": _rate(clicked, sent),
        "bounce_rate": _rate(bounced, sent),
        "invites": invites, "accepted": accepted, "li_replied": li_replied,
        "accept_rate": _rate(accepted, invites),
        "li_reply_rate": _rate(li_replied, invites),
        "positive_replies": positive, "meetings": meetings,
    }


def grade(metric: str, value: float, rubric: dict) -> str:
    bands = rubric["grades"][metric]
    if metric in rubric.get("ascending_metrics", []):
        # lower is better: bands ascend by min threshold, last satisfied wins
        letter = bands[0][1]
        for threshold, let in bands:
            if value >= threshold:
                letter = let
        return letter
    for threshold, let in bands:  # descending: first satisfied wins
        if value >= threshold:
            return let
    return bands[-1][1]


def scorecard(k: dict, rubric: dict) -> dict:
    metrics = {
        "open_rate": k["open_rate"], "reply_rate": k["li_reply_rate"],
        "positive": _rate(k["positive_replies"], max(k["emails_sent"], 1)),
        "bounce_rate": k["bounce_rate"], "accept_rate": k["accept_rate"],
    }
    grades = {m: grade(m, v, rubric) for m, v in metrics.items()}
    order = "ABCD"
    worst = max((grades[m] for m in grades), key=lambda g: order.index(g))
    overall = worst  # roll-up = weakest band (conservative)
    return {"grades": grades, "overall": overall}


def campaign_table(data: ClientData, rubric: dict) -> list[dict]:
    by_campaign: dict[str, Counter] = defaultdict(Counter)
    for e in data.emails:
        by_campaign[e.campaign][e.event_type] += 1
    rows = []
    for name, c in sorted(by_campaign.items()):
        sends = c.get("email_sent", 0)
        opened = c.get("email_opened", 0)
        rows.append({
            "name": name, "channel": "Email", "sends": sends,
            "rate": _rate(opened, sends), "rate_label": "open",
            "positives": 0,
            "grade": grade("open_rate", _rate(opened, sends), rubric),
        })
    return rows
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/client/test_compute.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dashboard/client/compute.py tests/client/test_compute.py
git commit -m "feat(client-dash): KPIs, grades, campaign table"
```

---

### Task 5: Compute — sender health, deliverability, engagement-timing heatmap

**Files:**
- Modify: `dashboard/client/compute.py` (append functions)
- Test: `tests/client/test_compute_timing.py`

**Interfaces:**
- Produces: `compute.sender_wise(data) -> list[dict]` (from_email, volume, opened, open_rate, bounced, bounce_rate, flag:bool); `compute.deliverability(data, rubric) -> list[dict]` (sender, bounce_rate, note) for senders over the bounce band; `compute.timing_heatmap(data, rubric) -> dict` (weekdays, dayparts, grid[weekday][daypart_label]=count, best:{weekday,daypart}, timezone, note).

- [ ] **Step 1: Write the failing test**

```python
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
    rows = compute.sender_wise(_data())
    senders = {r["from_email"] for r in rows}
    assert "augustine@upsta.co" in senders
    a = next(r for r in rows if r["from_email"] == "augustine.m@upstahq.com")
    assert a["bounced"] == 1


def test_timing_heatmap_buckets_engagement_in_local_tz():
    h = compute.timing_heatmap(_data(), _rubric())
    # 2 opened + 1 clicked = 3 engagement events placed into the grid
    total = sum(sum(row.values()) for row in h["grid"].values())
    assert total == 3
    assert h["timezone"] == "America/Detroit"
    assert "best" in h and h["best"]["daypart"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/client/test_compute_timing.py -v`
Expected: FAIL with `AttributeError: module ... has no attribute 'sender_wise'`

- [ ] **Step 3: Append the implementation to `compute.py`**

```python
# --- append to dashboard/client/compute.py ---
from zoneinfo import ZoneInfo  # add to imports at top


def sender_wise(data: ClientData) -> list[dict]:
    agg: dict[str, Counter] = defaultdict(Counter)
    for e in data.emails:
        agg[e.from_email][e.event_type] += 1
    rows = []
    for sender, c in sorted(agg.items()):
        sent = c.get("email_sent", 0)
        vol = sum(c.values())
        bounced = c.get("email_bounced", 0)
        denom = sent or vol
        rows.append({
            "from_email": sender, "volume": vol,
            "opened": c.get("email_opened", 0),
            "open_rate": _rate(c.get("email_opened", 0), sent),
            "bounced": bounced, "bounce_rate": _rate(bounced, denom),
            "flag": _rate(bounced, denom) >= 0.04,
        })
    return rows


def deliverability(data: ClientData, rubric: dict) -> list[dict]:
    flags = []
    for s in sender_wise(data):
        if s["flag"]:
            flags.append({
                "sender": s["from_email"],
                "bounce_rate": s["bounce_rate"],
                "note": "pause & warm",
            })
    return flags


def _daypart(hour: int, dayparts: list) -> str | None:
    for label, start, end in dayparts:
        if start <= hour < end:
            return label
    return None


def timing_heatmap(data: ClientData, rubric: dict) -> dict:
    tz = ZoneInfo(rubric["timezone"])
    dayparts = rubric["dayparts"]
    weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri"]
    labels = [d[0] for d in dayparts]
    grid = {wd: {lbl: 0 for lbl in labels} for wd in weekdays}
    best = {"weekday": None, "daypart": None, "count": -1}
    for e in data.emails:
        if e.event_type not in ("email_opened", "link_clicked"):
            continue
        local = e.ts.astimezone(tz)
        wd = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][local.weekday()]
        if wd not in grid:
            continue
        part = _daypart(local.hour, dayparts)
        if part is None:
            continue
        grid[wd][part] += 1
        if grid[wd][part] > best["count"]:
            best = {"weekday": wd, "daypart": part, "count": grid[wd][part]}
    return {
        "weekdays": weekdays, "dayparts": labels, "grid": grid, "best": best,
        "timezone": rubric["timezone"],
        "note": "Engagement (opens/clicks), not replies. LinkedIn timing N/A (Aimfox).",
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/client/test_compute_timing.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dashboard/client/compute.py tests/client/test_compute_timing.py
git commit -m "feat(client-dash): sender health, deliverability, engagement-timing heatmap"
```

---

### Task 6: Compute — lead ladder, coverage, compute_all assembler

**Files:**
- Modify: `dashboard/client/compute.py` (append)
- Test: `tests/client/test_compute_ladder.py`

**Interfaces:**
- Produces: `compute.lead_ladder(data, rubric) -> dict` (hot:list, warm:list, reached_count:int; each lead {name,title,company,channel,status,tier,response_text}); `compute.coverage(data) -> dict` (by_segment:{seg:{targets:int, contacted:int}}, contacted_total, target_total); `compute.compute_all(data, rubric) -> dict` (the metric bag: kpis, scorecard, campaigns, senders, deliverability, timing, leads, coverage).

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/client/test_compute_ladder.py -v`
Expected: FAIL with `AttributeError: ... 'lead_ladder'`

- [ ] **Step 3: Append the implementation**

```python
# --- append to dashboard/client/compute.py ---


def lead_ladder(data: ClientData, rubric: dict) -> dict:
    hot: list[dict] = []
    seen: set[str] = set()
    for w in data.warm_leads:
        key = (w.linkedin_url or w.name).lower()
        if key in seen:
            continue
        seen.add(key)
        is_meeting = _status_hits(w.status, rubric["meeting_statuses"])
        is_positive = _status_hits(w.status, rubric["positive_statuses"])
        if is_meeting or is_positive:
            hot.append({
                "name": w.name, "title": w.title, "company": w.company,
                "channel": w.channel, "status": w.status, "tier": "Hot",
                "response_text": w.response_text,
            })
    # Warm tier = engaged on LinkedIn (accepted) not already Hot
    warm: list[dict] = []
    for e in data.linkedin:
        if e.event_type != "accepted":
            continue
        key = (e.profile_url or e.prospect_name).lower()
        if key in seen:
            continue
        seen.add(key)
        warm.append({
            "name": e.prospect_name, "title": e.title, "company": e.company,
            "channel": "LinkedIn", "status": "Accepted invite", "tier": "Warm",
            "response_text": "",
        })
    reached = len(data.emails) + len(data.linkedin) - len(hot) - len(warm)
    return {"hot": hot, "warm": warm, "reached_count": max(reached, 0)}


def coverage(data: ClientData) -> dict:
    by_segment: dict[str, dict] = defaultdict(lambda: {"targets": 0, "contacted": 0})
    contacted_companies = {e.company for e in data.emails} | {
        e.company for e in data.linkedin}
    for t in data.targets:
        seg = by_segment[t.segment]
        seg["targets"] += 1
        if t.name in contacted_companies:
            seg["contacted"] += 1
    return {
        "by_segment": dict(by_segment),
        "target_total": len(data.targets),
        "contacted_total": len(contacted_companies),
    }


def compute_all(data: ClientData, rubric: dict) -> dict:
    k = kpis(data, rubric)
    return {
        "kpis": k,
        "scorecard": scorecard(k, rubric),
        "campaigns": campaign_table(data, rubric),
        "senders": sender_wise(data),
        "deliverability": deliverability(data, rubric),
        "timing": timing_heatmap(data, rubric),
        "leads": lead_ladder(data, rubric),
        "coverage": coverage(data),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/client/test_compute_ladder.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dashboard/client/compute.py tests/client/test_compute_ladder.py
git commit -m "feat(client-dash): lead ladder, coverage, compute_all assembler"
```

---

### Task 7: Snapshot store + deltas

**Files:**
- Create: `dashboard/client/snapshots.py`
- Create: `schemas/0007_client_dashboard_snapshots.sql`
- Test: `tests/client/test_snapshots.py`

**Interfaces:**
- Produces: `snapshots.LocalJsonStore(path)` with `.prior(client, period_kind) -> dict | None` and `.save(client, period_kind, period_end, metrics: dict) -> None`; module fn `snapshots.deltas(current: dict, prior: dict | None) -> dict` returning `{key: {"value": v, "delta": d | None, "baseline": bool}}` for the flat KPI bag (`metrics["kpis"]`).

- [ ] **Step 1: Write the failing test**

```python
# tests/client/test_snapshots.py
from dashboard.client import snapshots


def test_baseline_when_no_prior():
    d = snapshots.deltas({"emails_sent": 200}, None)
    assert d["emails_sent"]["baseline"] is True
    assert d["emails_sent"]["delta"] is None


def test_delta_vs_prior():
    d = snapshots.deltas({"emails_sent": 220}, {"emails_sent": 200})
    assert d["emails_sent"]["delta"] == 20
    assert d["emails_sent"]["baseline"] is False


def test_store_roundtrip(tmp_path):
    store = snapshots.LocalJsonStore(tmp_path / "snaps.json")
    assert store.prior("UPSTA", "monthly") is None
    store.save("UPSTA", "monthly", "2026-05-31", {"kpis": {"emails_sent": 100}})
    store.save("UPSTA", "monthly", "2026-06-30", {"kpis": {"emails_sent": 220}})
    prior = store.prior("UPSTA", "monthly", before="2026-06-30")
    assert prior["kpis"]["emails_sent"] == 100   # most recent before current period
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/client/test_snapshots.py -v`
Expected: FAIL with `ModuleNotFoundError: dashboard.client.snapshots`

- [ ] **Step 3: Write the implementation**

```python
# dashboard/client/snapshots.py
"""Snapshot persistence + delta computation.

v1 uses a local JSON store (no creds). The Supabase table (schemas/0007) is the
v2 home and the corpus for cross-client benchmarks; the row shape matches.
"""
from __future__ import annotations

import json
from pathlib import Path


class LocalJsonStore:
    def __init__(self, path):
        self.path = Path(path)

    def _all(self) -> list[dict]:
        if not self.path.exists():
            return []
        return json.loads(self.path.read_text() or "[]")

    def prior(self, client: str, period_kind: str, before: str | None = None) -> dict | None:
        rows = [r for r in self._all()
                if r["client"] == client and r["period_kind"] == period_kind]
        if before is not None:
            rows = [r for r in rows if r["period_end"] < before]
        if not rows:
            return None
        rows.sort(key=lambda r: r["period_end"])
        return rows[-1]["metrics"]

    def save(self, client: str, period_kind: str, period_end: str, metrics: dict) -> None:
        rows = [r for r in self._all()
                if not (r["client"] == client and r["period_kind"] == period_kind
                        and r["period_end"] == period_end)]
        rows.append({"client": client, "period_kind": period_kind,
                     "period_end": period_end, "metrics": metrics})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(rows, indent=2))


def deltas(current: dict, prior: dict | None) -> dict:
    out: dict = {}
    for key, value in current.items():
        if not isinstance(value, (int, float)):
            continue
        if prior is None or key not in prior:
            out[key] = {"value": value, "delta": None, "baseline": True}
        else:
            out[key] = {"value": value, "delta": round(value - prior[key], 4),
                        "baseline": False}
    return out
```

```sql
-- schemas/0007_client_dashboard_snapshots.sql
-- One row per (client, cadence, period). metrics kept as jsonb (explore-first;
-- typed columns earned later). Powers WoW/MoM deltas in v1 and cross-client
-- percentile benchmarks in v2.
create table if not exists client_dashboard_snapshots (
    client       text not null,
    period_kind  text not null,          -- 'weekly' | 'monthly'
    period_end   date not null,
    rendered_at  timestamptz not null default now(),
    metrics      jsonb not null,
    primary key (client, period_kind, period_end)
);
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/client/test_snapshots.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dashboard/client/snapshots.py schemas/0007_client_dashboard_snapshots.sql tests/client/test_snapshots.py
git commit -m "feat(client-dash): snapshot store + deltas (+ supabase schema)"
```

---

### Task 8: Agents — narrative + actions

**Files:**
- Create: `dashboard/client/agents/__init__.py` (empty)
- Create: `dashboard/client/agents/narrative.py`
- Create: `dashboard/client/agents/actions.py`
- Test: `tests/client/test_agents.py`

**Interfaces:**
- Consumes: `dashboard.agents._client.run_agent` (signature: `run_agent(*, model, role_prompt, json_schema_description, input_payload, fallback_factory, client=None) -> dict` returning `{"degraded": bool, ...}`).
- Produces: `narrative.synthesize(metrics: dict, *, audience: str, client: str) -> dict` (`{degraded, narrative}`); `actions.synthesize(metrics: dict, *, client: str) -> dict` (`{degraded, actions: list[str]}`). Both must return a usable fallback when `run_agent` degrades.

- [ ] **Step 1: Write the failing test** (no API call — force the fallback path)

```python
# tests/client/test_agents.py
import asyncio
from dashboard.client.agents import narrative, actions


class _BoomClient:
    """Stand-in AsyncAnthropic whose .messages.create raises -> run_agent degrades."""
    class messages:
        @staticmethod
        async def create(*a, **k):
            raise RuntimeError("no api in test")


def test_narrative_falls_back_without_api():
    metrics = {"kpis": {"emails_sent": 224, "opened": 129, "meetings": 1,
                        "positive_replies": 2, "accepted": 42, "invites": 239}}
    out = asyncio.run(narrative.synthesize(metrics, audience="client",
                                           client="UPSTA", client_obj=_BoomClient()))
    assert out["degraded"] is True
    assert isinstance(out["narrative"], str) and out["narrative"]


def test_actions_falls_back_without_api():
    metrics = {"kpis": {"bounce_rate": 0.07, "emails_sent": 224}}
    out = asyncio.run(actions.synthesize(metrics, client="UPSTA",
                                         client_obj=_BoomClient()))
    assert out["degraded"] is True
    assert isinstance(out["actions"], list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/client/test_agents.py -v`
Expected: FAIL with `ModuleNotFoundError: dashboard.client.agents`

- [ ] **Step 3: Write the implementations**

```python
# dashboard/client/agents/narrative.py
"""Narrative agent (Sonnet). Client audience uses the client-safe voice."""
from __future__ import annotations

from dashboard.agents._client import run_agent

_MODEL = "claude-sonnet-4-6"

_ROLE_CLIENT = """
You write a short, plain narrative summarizing an outreach campaign report for the CLIENT.
Proof-first and honest. No internal mechanics (no mailbox warming, no 'pause sender').
Forbidden: delve, leverage, unlock, ecosystem, em dashes, listy filler, preachy endings.
2-4 short sentences. Use only numbers present in the input.
"""

_ROLE_INTERNAL = """
You write a short internal narrative summarizing an outreach campaign report for Leadle ops.
Call out the winner, the laggard, and the single biggest risk (deliverability/sender).
Forbidden: delve, leverage, unlock, ecosystem, em dashes, listy filler. 2-4 short sentences.
Use only numbers present in the input.
"""

_SCHEMA = """
Return JSON of this exact shape:
{ "narrative": "<2-4 sentence summary>" }
"""


def _fallback(payload: dict) -> dict:
    k = payload
    return {"narrative": (
        f"{k.get('emails_sent', 0)} emails sent, {k.get('opened', 0)} opened; "
        f"{k.get('accepted', 0)} LinkedIn invites accepted. "
        f"{k.get('positive_replies', 0)} positive replies, "
        f"{k.get('meetings', 0)} meetings booked so far.")}


async def synthesize(metrics: dict, *, audience: str, client: str, client_obj=None) -> dict:
    payload = dict(metrics.get("kpis", {}))
    role = _ROLE_CLIENT if audience == "client" else _ROLE_INTERNAL
    return await run_agent(
        model=_MODEL, role_prompt=role, json_schema_description=_SCHEMA,
        input_payload=payload, fallback_factory=_fallback, client=client_obj,
    )
```

```python
# dashboard/client/agents/actions.py
"""Actions agent (Sonnet). Internal audience only — never rendered for clients."""
from __future__ import annotations

from dashboard.agents._client import run_agent

_MODEL = "claude-sonnet-4-6"

_ROLE = """
You propose up to 4 concrete operator actions for this outreach campaign for the next period
(scale a winner, swap a weak subject, pause/warm a bouncing inbox, follow up positives).
Each under 90 characters. Use only numbers present in the input.
"""

_SCHEMA = """
Return JSON of this exact shape:
{ "actions": ["<action>", "... up to 4 ..."] }
"""


def _fallback(payload: dict) -> dict:
    acts = []
    if payload.get("bounce_rate", 0) >= 0.04:
        acts.append("Pause & warm the bouncing inbox before next send.")
    acts.append("Follow up every positive reply within 24h.")
    return {"actions": acts}


async def synthesize(metrics: dict, *, client: str, client_obj=None) -> dict:
    payload = dict(metrics.get("kpis", {}))
    return await run_agent(
        model=_MODEL, role_prompt=_ROLE, json_schema_description=_SCHEMA,
        input_payload=payload, fallback_factory=_fallback, client=client_obj,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/client/test_agents.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dashboard/client/agents tests/client/test_agents.py
git commit -m "feat(client-dash): narrative + actions agents (Sonnet, with fallbacks)"
```

---

### Task 9: Templates + render CLI (two audiences, two periods)

**Files:**
- Create: `dashboard/client/templates/report_base.html.j2`
- Create: `dashboard/client/templates/report.html.j2`
- Create: `dashboard/client/templates/blocks/kpis.html.j2`
- Create: `dashboard/client/templates/blocks/scorecard.html.j2`
- Create: `dashboard/client/templates/blocks/campaigns.html.j2`
- Create: `dashboard/client/templates/blocks/content.html.j2`
- Create: `dashboard/client/templates/blocks/senders.html.j2`
- Create: `dashboard/client/templates/blocks/timing.html.j2`
- Create: `dashboard/client/templates/blocks/deliverability.html.j2`
- Create: `dashboard/client/templates/blocks/leads.html.j2`
- Create: `dashboard/client/templates/blocks/narrative.html.j2`
- Create: `dashboard/client/templates/blocks/actions.html.j2`
- Create: `dashboard/client/templates/blocks/targets.html.j2`
- Create: `dashboard/client/render.py`
- Test: `tests/client/test_render.py`

**Interfaces:**
- Consumes: `compute.compute_all`, `snapshots.deltas`, `narrative.synthesize`, `actions.synthesize`, layout + rubric YAML.
- Produces: `render.render(data, metrics, deltas_bag, narrative, actions, *, audience, period_label, client, layout, rubric) -> str`; `render.visible_blocks(layout, audience) -> list[dict]`; `render.main() -> int` with args `--client --workbook --period {weekly,monthly} --period-end --audience {internal,client} --skip-agents --snapshot-store --output-dir`.

- [ ] **Step 1: Write the failing test**

```python
# tests/client/test_render.py
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
    assert "Pause &amp; warm inbox." in html or "Pause & warm inbox." in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/client/test_render.py -v`
Expected: FAIL with `ModuleNotFoundError: dashboard.client.render`

- [ ] **Step 3: Write the templates**

```jinja
{# dashboard/client/templates/report_base.html.j2 #}
<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>{{ client }} — campaign report</title>
<style>
 body{font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;color:#1a1a1a;margin:0;background:#fafafa}
 .wrap{max-width:900px;margin:0 auto;padding:24px}
 h1{font-size:20px;margin:0} .sub{color:#666;font-size:13px}
 .tag{background:#eef;border-radius:4px;padding:1px 6px;font-size:11px;color:#446}
 section{background:#fff;border:1px solid #eee;border-radius:8px;padding:16px;margin:14px 0}
 h2{font-size:14px;margin:0 0 10px;color:#333}
 .tiles{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}
 .tile{background:#f7f7f9;border-radius:6px;padding:10px}
 .tile .v{font-size:20px;font-weight:600} .tile .l{font-size:11px;color:#777}
 .delta-up{color:#197;font-size:11px} .delta-base{color:#999;font-size:11px}
 table{width:100%;border-collapse:collapse;font-size:13px}
 th,td{text-align:left;padding:6px 8px;border-bottom:1px solid #f0f0f0}
 .grade{display:inline-block;width:20px;text-align:center;border-radius:4px;background:#eef;font-weight:600}
 .heat td{text-align:center} .note{color:#888;font-size:12px;margin-top:8px}
 .flag{color:#b44}
</style></head>
<body><div class="wrap">
 <header>
  <h1>{{ client }} <span class="tag">campaign report</span></h1>
  <div class="sub">{{ period_label }}{% if sample %} · sample data{% endif %}</div>
 </header>
 {% block body %}{% endblock %}
 <footer class="sub" style="margin:18px 0">Generated {{ rendered_at }} · audience: {{ audience }}</footer>
</div></body></html>
```

```jinja
{# dashboard/client/templates/report.html.j2 #}
{% extends "report_base.html.j2" %}
{% block body %}
 {% for b in blocks %}
   <section>
     <h2>{{ b.title }}</h2>
     {% include "blocks/" + b.key + ".html.j2" %}
   </section>
 {% endfor %}
{% endblock %}
```

```jinja
{# dashboard/client/templates/blocks/kpis.html.j2 #}
{% set k = metrics.kpis %}
<div class="tiles">
  {% for label, key, pct in [
      ("Emails sent","emails_sent",False),("Open rate","open_rate",True),
      ("Positive replies","positive_replies",False),("Meetings","meetings",False),
      ("Invites","invites",False),("Accept rate","accept_rate",True),
      ("LI replies","li_replied",False),("Bounce rate","bounce_rate",True)] %}
   <div class="tile">
     <div class="v">{% if pct %}{{ '%.0f%%' % (k[key]*100) }}{% else %}{{ k[key] }}{% endif %}</div>
     <div class="l">{{ label }}</div>
     {% set d = deltas.get(key) %}
     {% if d and d.baseline %}<div class="delta-base">baseline</div>
     {% elif d and d.delta is not none %}<div class="delta-up">Δ {{ d.delta }}</div>{% endif %}
   </div>
  {% endfor %}
</div>
```

```jinja
{# dashboard/client/templates/blocks/scorecard.html.j2 #}
{% set s = metrics.scorecard %}
<table><tr>
 {% for m, g in s.grades.items() %}<th>{{ m }}</th>{% endfor %}<th>Overall</th></tr><tr>
 {% for m, g in s.grades.items() %}<td><span class="grade">{{ g }}</span></td>{% endfor %}
 <td><span class="grade">{{ s.overall }}</span></td></tr></table>
```

```jinja
{# dashboard/client/templates/blocks/campaigns.html.j2 #}
{% if metrics.campaigns %}
<table><tr><th>Campaign</th><th>Channel</th><th>Sent</th><th>Rate</th><th>Grade</th></tr>
 {% for c in metrics.campaigns %}
 <tr><td>{{ c.name }}</td><td>{{ c.channel }}</td><td>{{ c.sends }}</td>
     <td>{{ '%.1f%%' % (c.rate*100) }} {{ c.rate_label }}</td>
     <td><span class="grade">{{ c.grade }}</span></td></tr>
 {% endfor %}</table>
{% else %}<div class="note">No campaign activity this period.</div>{% endif %}
```

```jinja
{# dashboard/client/templates/blocks/content.html.j2 #}
<div class="note">Per-step reply attribution not available from the export; LinkedIn templates shown unranked (Aimfox gives no per-step data).</div>
```

```jinja
{# dashboard/client/templates/blocks/senders.html.j2 #}
<table><tr><th>Sender</th><th>Volume</th><th>Open rate</th><th>Bounce</th></tr>
 {% for s in metrics.senders %}
 <tr><td>{{ s.from_email }}</td><td>{{ s.volume }}</td>
     <td>{{ '%.0f%%' % (s.open_rate*100) }}</td>
     <td class="{{ 'flag' if s.flag }}">{{ '%.1f%%' % (s.bounce_rate*100) }}</td></tr>
 {% endfor %}</table>
```

```jinja
{# dashboard/client/templates/blocks/timing.html.j2 #}
{% set t = metrics.timing %}
<table class="heat"><tr><th>Day</th>{% for p in t.dayparts %}<th>{{ p }}</th>{% endfor %}</tr>
 {% for wd in t.weekdays %}<tr><td>{{ wd }}</td>
   {% for p in t.dayparts %}<td>{{ t.grid[wd][p] or '' }}</td>{% endfor %}</tr>
 {% endfor %}</table>
<div class="note">Best: {{ t.best.weekday }} {{ t.best.daypart }} ({{ t.timezone }}). {{ t.note }}</div>
```

```jinja
{# dashboard/client/templates/blocks/deliverability.html.j2 #}
{% if metrics.deliverability %}
 {% for f in metrics.deliverability %}
   <div class="flag">{{ f.sender }} bounce {{ '%.1f%%' % (f.bounce_rate*100) }} — {{ f.note }}</div>
 {% endfor %}
{% else %}<div class="note">No deliverability flags.</div>{% endif %}
```

```jinja
{# dashboard/client/templates/blocks/leads.html.j2 #}
{% set L = metrics.leads %}
{% if L.hot or L.warm %}
<table><tr><th>Name</th><th>Title</th><th>Company</th><th>Channel</th><th>Status</th></tr>
 {% for x in L.hot + L.warm %}
 <tr><td>{{ x.name }}</td><td>{{ x.title }}</td><td>{{ x.company }}</td>
     <td>{{ x.channel }}</td><td>{{ x.tier }} · {{ x.status }}</td></tr>
 {% endfor %}</table>
{% else %}<div class="note">No warm leads logged yet — campaign is live.</div>{% endif %}
<div class="note">{{ L.reached_count }} prospects reached.</div>
```

```jinja
{# dashboard/client/templates/blocks/narrative.html.j2 #}
<p>{{ narrative.narrative }}</p>
```

```jinja
{# dashboard/client/templates/blocks/actions.html.j2 #}
{% if actions.actions %}<ul>{% for a in actions.actions %}<li>{{ a }}</li>{% endfor %}</ul>
{% else %}<div class="note">No actions flagged.</div>{% endif %}
```

```jinja
{# dashboard/client/templates/blocks/targets.html.j2 #}
{% set cov = metrics.coverage %}
<div class="note">{{ cov.contacted_total }} of {{ cov.target_total }} target accounts contacted.</div>
```

- [ ] **Step 4: Write `render.py`**

```python
# dashboard/client/render.py
"""On-demand client campaign report: source -> compute -> agents -> HTML.

MCP-orchestrated ingestion: the session dumps the Drive workbook to --workbook
before running this. Snapshots use a local JSON store by default.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date, datetime
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

from dashboard.client import compute, snapshots
from dashboard.client.agents import actions as actions_agent
from dashboard.client.agents import narrative as narrative_agent
from dashboard.client.sources import sheet_source

_ROOT = Path(__file__).resolve().parents[2]
_CONFIG = _ROOT / "config"
_TEMPLATES = Path(__file__).parent / "templates"


def _load(name: str) -> dict:
    return yaml.safe_load((_CONFIG / name).read_text())


def visible_blocks(layout: dict, audience: str) -> list[dict]:
    return [b for b in layout["blocks"]
            if b["visibility"] == "both" or b["visibility"] == audience]


def render(data, metrics, deltas_bag, narrative, actions, *, audience, period_label,
           client, layout, rubric, sample=False) -> str:
    env = Environment(loader=FileSystemLoader(str(_TEMPLATES)),
                      autoescape=select_autoescape(["html", "xml"]))
    template = env.get_template("report.html.j2")
    return template.render(
        client=client, period_label=period_label, audience=audience, sample=sample,
        blocks=visible_blocks(layout, audience), metrics=metrics,
        deltas=deltas_bag, narrative=narrative, actions=actions,
        rendered_at=datetime.now().isoformat(timespec="seconds"),
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", required=True)
    ap.add_argument("--workbook", required=True, help="Path to Drive-dumped workbook text")
    ap.add_argument("--period", choices=["weekly", "monthly"], default="monthly")
    ap.add_argument("--period-end", default=date.today().isoformat())
    ap.add_argument("--period-label", default=None)
    ap.add_argument("--audience", choices=["internal", "client"], default="client")
    ap.add_argument("--skip-agents", action="store_true")
    ap.add_argument("--snapshot-store", default=str(_ROOT / "reports" / "client" / "_snapshots.json"))
    ap.add_argument("--output-dir", default=str(_ROOT / "reports" / "client"))
    ap.add_argument("--sample", action="store_true")
    args = ap.parse_args()

    rubric = _load("client_report_rubric.yaml")
    layout = _load("client_report_layout.yaml")

    data = sheet_source.read(args.client, args.workbook)
    if not data.emails and not data.linkedin and not data.warm_leads:
        print(f"No data matched client '{args.client}'. Check the campaign prefix.",
              file=sys.stderr)
        return 2

    metrics = compute.compute_all(data, rubric)

    store = snapshots.LocalJsonStore(args.snapshot_store)
    prior = store.prior(args.client, args.period, before=args.period_end)
    deltas_bag = snapshots.deltas(metrics["kpis"], prior.get("kpis") if prior else None)

    if args.skip_agents:
        narrative = {"degraded": True, "narrative": ""}
        actions = {"degraded": True, "actions": []}
    else:
        narrative = asyncio.run(narrative_agent.synthesize(
            metrics, audience=args.audience, client=args.client))
        actions = asyncio.run(actions_agent.synthesize(metrics, client=args.client))

    label = args.period_label or f"{args.period} ending {args.period_end}"
    html = render(data, metrics, deltas_bag, narrative, actions,
                  audience=args.audience, period_label=label, client=args.client,
                  layout=layout, rubric=rubric, sample=args.sample)

    store.save(args.client, args.period, args.period_end, metrics)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{args.client}-{args.period_end}-{args.period}-{args.audience}.html"
    out.write_text(html, encoding="utf-8")
    print(f"Client report rendered: {out.absolute()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/client/test_render.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest tests/client/ -v`
Expected: PASS (all tasks' tests green)

- [ ] **Step 7: Commit**

```bash
git add dashboard/client/templates dashboard/client/render.py tests/client/test_render.py
git commit -m "feat(client-dash): templates + render CLI (two audiences, deltas, snapshots)"
```

---

### Task 10: Slash command + ingestion doc + UPSTA sample render

**Files:**
- Create: `.claude/commands/render-client-report.md`
- Modify: `docs/data-shape/prospect-list-sheet.md` (append ingestion + render runbook)
- Test: manual end-to-end (documented below)

**Interfaces:**
- Consumes: everything above. No new code interfaces.

- [ ] **Step 1: Write the slash command**

```markdown
<!-- .claude/commands/render-client-report.md -->
---
description: Render a client outreach campaign report (on-demand snapshot)
---

Render the per-client campaign report. Arguments: `<CLIENT> [weekly|monthly] [internal|client]`.

Steps:
1. Fetch the client's "Prospect list" workbook via the Google Drive MCP
   (`read_file_content`) and write the returned text to
   `reports/client/_raw/<CLIENT>_workbook.txt` (create dirs as needed).
2. Run both audiences:
   `python -m dashboard.client.render --client <CLIENT> --workbook reports/client/_raw/<CLIENT>_workbook.txt --period <PERIOD> --audience client --sample`
   and again with `--audience internal`.
3. Report the two output paths under `reports/client/`. Do not commit `reports/`.
```

- [ ] **Step 2: Append the runbook to the data-shape doc**

Append a "## Render runbook" section to `docs/data-shape/prospect-list-sheet.md`
documenting: the Drive→raw-file dump step, the two render commands, that snapshots
accumulate in `reports/client/_snapshots.json`, and that the first render shows `baseline`
(no deltas).

- [ ] **Step 3: Produce the real UPSTA sample (manual, in-session)**

Fetch the live UPSTA workbook via Drive MCP, dump to `reports/client/_raw/UPSTA_workbook.txt`, then:

Run:
```bash
python -m dashboard.client.render --client UPSTA \
  --workbook reports/client/_raw/UPSTA_workbook.txt \
  --period monthly --period-label "June 2026" --audience client --sample
python -m dashboard.client.render --client UPSTA \
  --workbook reports/client/_raw/UPSTA_workbook.txt \
  --period monthly --period-label "June 2026" --audience internal --sample
```
Expected: two files under `reports/client/`. Open the client HTML and verify against the
real tallies (LinkedIn 239/42/3; Email 224/129/41/16); confirm Sender health + Deliverability
+ Actions appear ONLY in the internal file.

- [ ] **Step 4: Commit (code/docs only — reports/ is gitignored)**

```bash
git add .claude/commands/render-client-report.md docs/data-shape/prospect-list-sheet.md
git commit -m "feat(client-dash): render-client-report command + ingestion runbook"
```

- [ ] **Step 5: Show the team**

Send the client-audience HTML to the team channel for layout/tone/metric feedback (this is
the success gate from the spec).

---

> **Tasks 11–12 added 2026-06-19** (cadence-ID update). Execution order on resume:
> **Task 11 → Task 12 → Task 10** (Task 10's re-render/show-team gate runs last, after the
> parser fix and the reach block exist). Task 11 also fixes the known multi-table parser bug.

### Task 11: Parser hardening — paginated tables + header-aware spine + cadence IDs

**Why:** The Drive flatten splits each large table into multiple consecutive blocks (same
header re-emitted); the v1 parser read only the first, so live UPSTA KPIs came out 0. The
prospect spine is per-prospect, wide, and varies in width, and now carries
`Aimfox ID | Aimfox URN | Instantly ID`. Fix both: concatenate all blocks under a header, and
parse the spine by column NAME.

**Files:**
- Modify: `dashboard/client/model.py` (TargetCo + 3 fields)
- Modify: `dashboard/client/sources/sheet_source.py` (`_tables_under`, `_rows_under` concat, header-aware targets)
- Create: `tests/client/fixtures/upsta_multitable.txt`
- Test: `tests/client/test_sheet_source.py` (2 new tests)

**Interfaces:**
- Consumes: existing `_cells`, `_is_sep`, `_ALL_HEADERS`, `_H_*` signatures.
- Produces: `TargetCo(..., aimfox_id="", aimfox_urn="", instantly_id="")`; `_rows_under` now
  returns rows across ALL matching tables.

- [ ] **Step 1: Extend the model**

```python
@dataclass
class TargetCo:
    name: str
    country: str
    location: str
    linkedin_url: str
    industry: str
    size: str
    segment: str
    domain: str
    aimfox_id: str = ""
    aimfox_urn: str = ""
    instantly_id: str = ""
```

- [ ] **Step 2: Write the failing tests** (`tests/client/test_sheet_source.py`, append)

```python
_MT = Path(__file__).parent / "fixtures" / "upsta_multitable.txt"


def _mt():
    return sheet_source.parse(_MT.read_text(), client="UPSTA")


def test_email_events_concatenated_across_paginated_tables():
    d = _mt()
    # two email blocks, 2 UPSTA rows each -> 4 (old parser read only the first block)
    assert len(d.emails) == 4
    assert sum(1 for e in d.emails if e.event_type == "email_sent") == 2


def test_spine_pages_and_cadence_ids_parsed_by_header():
    d = _mt()
    assert len(d.targets) == 4  # both spine pages read
    by = {t.name: t for t in d.targets}
    # header-aware: domain comes from the "Company Domain" column, not a fixed index
    assert by["Real Alloy"].domain == "realalloy.com"
    assert by["Real Alloy"].aimfox_id == "229856678"
    assert by["Real Alloy"].instantly_id == "019e89de-both"
    assert by["Pegasus Logistics"].aimfox_id == ""   # email-only prospect
    assert by["Mapletree"].instantly_id == ""        # not in any cadence yet
```

- [ ] **Step 3: Create the fixture** (`tests/client/fixtures/upsta_multitable.txt`)

```
| Column 1 | Offering to the market | Channels | Target Market Segment |
| :-: | :-: | :-: | :-: |
| ICP 1 |  | LinkedIn, Email | Mid market |

| Company Name | Company Country | Company Location | Company Linked In URL | Primary Industry | Size (Text) | Account Process | First Name | Last Name | Full Name | Company Domain | Aimfox ID | Aimfox URN | Instantly ID |
| :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: |
| Real Alloy | United States | Cleveland | https://www.linkedin.com/company/real-alloy | Manufacturing | 1,001-5,000 | US_Set 1 | Chris | Garisek | Chris Garisek | realalloy.com | 229856678 | ACoAAA2zVaY | 019e89de-both |
| Metropolitan | United States | Perth Amboy | https://www.linkedin.com/company/metropolitan | Logistics | 501-1,000 | US_Set 1 | Petrus | vds | Petrus vds | gomwd.com | 59745740 | ACoAAAOPpcw |  |

| Company Name | Company Country | Company Location | Company Linked In URL | Primary Industry | Size (Text) | Account Process | First Name | Last Name | Full Name | Company Domain | Aimfox ID | Aimfox URN | Instantly ID |
| :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: |
| Pegasus Logistics | United States | Coppell | https://www.linkedin.com/company/pegasus | Logistics | 501-1,000 | US_Set 1 | Scott | Donahue | Scott Donahue | pegasus.com |  |  | 019e89de-email |
| Mapletree | Singapore | Singapore | https://www.linkedin.com/company/mapletree | Real Estate | 1,001-5,000 | SG_Set 1 | Oh | Chuan | Oh Chuan | mapletree.com.sg |  |  |  |

| Company Name | To Name | Event Type | Campaign Name | Event Timestamp | From Email |
| :-: | :-: | :-: | :-: | :-: | :-: |
| Real Alloy |  | email_sent | Upsta_SFDI_V1 | 2026-06-04T13:00:00.000Z | a@upsta.co |
| Real Alloy |  | email_opened | Upsta_SFDI_V1 | 2026-06-05T13:00:00.000Z | a@upsta.co |

| Company Name | To Name | Event Type | Campaign Name | Event Timestamp | From Email |
| :-: | :-: | :-: | :-: | :-: | :-: |
| Pegasus Logistics |  | email_sent | Upsta_PMP_V1 | 2026-06-06T13:00:00.000Z | a@upsta.co |
| Globex |  | email_opened | Upsta_PMP_V1 | 2026-06-07T13:00:00.000Z | a@upsta.co |
```

- [ ] **Step 4: Run the new tests, verify they FAIL**

Run: `python -m pytest tests/client/test_sheet_source.py -k "concatenated or cadence_ids" -v`
Expected: FAIL (old `_rows_under` reads first table only; `TargetCo` has no `aimfox_id`).

- [ ] **Step 5: Implement** (`dashboard/client/sources/sheet_source.py`)

Replace `_rows_under` with a multi-table generator + concatenator, add header helpers, and
rewrite the targets loop to be header-aware. Email/LinkedIn/warm/ICP loops keep calling
`_rows_under` (now concatenating across all blocks — this is the multi-table bug fix).

```python
def _tables_under(lines: list[str], header_prefix: str):
    """Yield (header_cells, data_rows) for EVERY table whose header starts with
    header_prefix. The Drive flatten re-emits the header for each paginated block."""
    i, n = 0, len(lines)
    while i < n:
        if lines[i].startswith(header_prefix):
            header = _cells(lines[i])
            i += 1
            rows: list[list[str]] = []
            while i < n:
                ln = lines[i]
                if not ln.strip().startswith("|"):
                    i += 1
                    continue
                if _is_sep(ln):
                    i += 1
                    continue
                if any(ln.startswith(h) for h in _ALL_HEADERS):
                    break  # next table (possibly the same header = next page)
                rows.append(_cells(ln))
                i += 1
            yield header, rows
        else:
            i += 1


def _rows_under(lines: list[str], header_prefix: str) -> list[list[str]]:
    """Data rows across ALL tables under header_prefix, concatenated."""
    out: list[list[str]] = []
    for _header, rows in _tables_under(lines, header_prefix):
        out.extend(rows)
    return out


def _col(header: list[str], *names: str) -> int:
    for nm in names:
        if nm in header:
            return header.index(nm)
    return -1


def _g(row: list[str], idx: int) -> str:
    return row[idx] if 0 <= idx < len(row) else ""
```

Rewrite the targets loop in `parse()` (replace the old positional `for r in _rows_under(lines, _H_TARGET)` block):

```python
    targets: list[TargetCo] = []
    for header, rows in _tables_under(lines, _H_TARGET):
        c_name = _col(header, "Company Name")
        c_country = _col(header, "Company Country")
        c_loc = _col(header, "Company Location")
        c_li = _col(header, "Company Linked In URL", "Company LinkedIn URL")
        c_ind = _col(header, "Primary Industry")
        c_size = _col(header, "Size (Text)", "Size")
        c_seg = _col(header, "Account Process")
        c_dom = _col(header, "Company Domain")
        c_af = _col(header, "Aimfox ID")
        c_urn = _col(header, "Aimfox URN")
        c_inst = _col(header, "Instantly ID")
        for r in rows:
            name = _g(r, c_name)
            if name in ("", "Company Name"):
                continue
            targets.append(TargetCo(
                name, _g(r, c_country), _g(r, c_loc), _g(r, c_li), _g(r, c_ind),
                _g(r, c_size), _g(r, c_seg), _g(r, c_dom),
                aimfox_id=_g(r, c_af), aimfox_urn=_g(r, c_urn),
                instantly_id=_g(r, c_inst)))
```

- [ ] **Step 6: Run the full client suite**

Run: `python -m pytest tests/client/ -v`
Expected: PASS — new tests green; all prior tests still green (single-table fixture → one
block → identical results; `domain` for the narrow fixture still resolves via header name;
new TargetCo fields default to "").

- [ ] **Step 7: Commit**

```bash
git add dashboard/client/model.py dashboard/client/sources/sheet_source.py \
        tests/client/fixtures/upsta_multitable.txt tests/client/test_sheet_source.py
git commit -m "fix(client-dash): read all paginated tables; header-aware spine parse + cadence IDs"
```

### Task 12: Channel-reach compute + dashboard block

**Why:** Surface unique prospects reached per channel and the both-channel overlap, computed
deterministically from the spine cadence IDs (no event join).

**Files:**
- Modify: `dashboard/client/compute.py` (`channel_reach` + bag entry)
- Modify: `config/client_report_layout.yaml` (add `reach` block before `leads`)
- Create: `dashboard/client/templates/blocks/reach.html.j2`
- Test: `tests/client/test_compute.py` (append), `tests/client/test_render.py` (append)

**Interfaces:**
- Consumes: `TargetCo.aimfox_id`, `TargetCo.instantly_id` (Task 11).
- Produces: `compute.channel_reach(data) -> {"linkedin_reached", "email_reached", "both_reached"}`;
  `compute_all` bag gains `"reach"`; template reads `metrics.reach`.

- [ ] **Step 1: Write the failing tests**

`tests/client/test_compute.py` (append):

```python
from dashboard.client.model import ClientData, TargetCo


def _reach_targets():
    return [
        TargetCo("Real Alloy", "US", "", "", "Mfg", "", "US_Set 1", "realalloy.com",
                 aimfox_id="A1", aimfox_urn="U1", instantly_id="I1"),   # both
        TargetCo("Metropolitan", "US", "", "", "Log", "", "US_Set 1", "gomwd.com",
                 aimfox_id="A2", aimfox_urn="U2", instantly_id=""),     # LinkedIn only
        TargetCo("Pegasus", "US", "", "", "Log", "", "US_Set 1", "pegasus.com",
                 aimfox_id="", aimfox_urn="", instantly_id="I3"),       # email only
        TargetCo("Mapletree", "SG", "", "", "RE", "", "SG_Set 1", "mapletree.com.sg"),  # neither
    ]


def test_channel_reach_counts_unique_per_channel_and_both():
    r = compute.channel_reach(ClientData(targets=_reach_targets()))
    assert r == {"linkedin_reached": 2, "email_reached": 2, "both_reached": 1}


def test_channel_reach_dedupes_on_id_value():
    ts = _reach_targets() + [
        TargetCo("Dup", "US", "", "", "Mfg", "", "US_Set 1", "dup.com",
                 aimfox_id="A1", instantly_id="I1")]  # repeats A1/I1
    r = compute.channel_reach(ClientData(targets=ts))
    assert r == {"linkedin_reached": 2, "email_reached": 2, "both_reached": 1}
```

`tests/client/test_render.py` (append):

```python
def test_reach_block_visible_to_both_audiences():
    layout = yaml.safe_load((_CFG / "client_report_layout.yaml").read_text())
    for audience in ("internal", "client"):
        keys = [b["key"] for b in render.visible_blocks(layout, audience)]
        assert "reach" in keys
```

(`compute`, `yaml`, `_CFG`, `render` are already imported at the top of these files.)

- [ ] **Step 2: Run, verify FAIL**

Run: `python -m pytest tests/client/test_compute.py -k channel_reach tests/client/test_render.py -k reach_block -v`
Expected: FAIL (`channel_reach` undefined; no `reach` block in layout).

- [ ] **Step 3: Implement compute** (`dashboard/client/compute.py`)

```python
def channel_reach(data: ClientData) -> dict:
    """Unique prospects reached per channel, from the spine cadence IDs.
    Non-empty Aimfox ID = entered LinkedIn cadence; Instantly ID = entered email cadence.
    Dedupe on the id value (it is the unique key); 'both' = holds both ids."""
    li = {t.aimfox_id for t in data.targets if t.aimfox_id}
    em = {t.instantly_id for t in data.targets if t.instantly_id}
    both = {t.aimfox_id for t in data.targets if t.aimfox_id and t.instantly_id}
    return {
        "linkedin_reached": len(li),
        "email_reached": len(em),
        "both_reached": len(both),
    }
```

Add to the `compute_all` bag (after `"coverage": coverage(data),`):

```python
        "reach": channel_reach(data),
```

- [ ] **Step 4: Add the layout block** (`config/client_report_layout.yaml`, before the `leads` row)

```yaml
  - {key: reach,         title: "Channel reach",             visibility: both}
```

- [ ] **Step 5: Create the block template** (`dashboard/client/templates/blocks/reach.html.j2`)

```jinja
{# dashboard/client/templates/blocks/reach.html.j2 #}
{% set r = metrics.reach %}
<div class="tiles">
  <div class="tile"><div class="v">{{ r.linkedin_reached }}</div><div class="l">Reached on LinkedIn</div></div>
  <div class="tile"><div class="v">{{ r.email_reached }}</div><div class="l">Reached on email</div></div>
  <div class="tile"><div class="v">{{ r.both_reached }}</div><div class="l">Both channels</div></div>
</div>
```

- [ ] **Step 6: Run the full client suite**

Run: `python -m pytest tests/client/ -v`
Expected: PASS. `test_compute_all_assembles_bag` still green (it asserts a superset).

- [ ] **Step 7: Commit**

```bash
git add dashboard/client/compute.py config/client_report_layout.yaml \
        dashboard/client/templates/blocks/reach.html.j2 \
        tests/client/test_compute.py tests/client/test_render.py
git commit -m "feat(client-dash): channel-reach block from spine cadence IDs"
```

---

## Self-Review

**1. Spec coverage**

| Spec section | Task |
|---|---|
| §2 on-demand, two cadences, two audiences, sheet source | Tasks 2, 9 |
| §3 module layout + source seam (base.py / sheet/live) | Tasks 1, 3, 9 |
| §3.1 two-audience visibility table | Tasks 2 (config), 9 (filter + tests) |
| §4 data sources (5 tabs) | Task 3 parse + fixture |
| §5 normalized model | Task 1 |
| §6 compute (KPIs, deltas, scorecard, campaign, sender, timing, coverage, ladder) | Tasks 4, 5, 6, 7 |
| §7 agents narrative + actions | Task 8 |
| §8 layout/order + tone + data-quality toggle | Tasks 2, 9 |
| §9 error handling / degradation | Tasks 3 (empty tabs), 8 (agent fallback), 9 (no-match abort) |
| §10 snapshot store + schema | Task 7 |
| §11 sample plan | Task 10 |
| §13 decisions (rubric grades, deltas, meetings from tracker) | Tasks 2, 4, 7 |

No uncovered spec requirement. The timing block is implemented as engagement (not reply) per the updated §6/§8.

**2. Placeholder scan:** No "TBD"/"add error handling"/"similar to Task N". The `content` block is intentionally a stated-limitation note (per-step attribution unavailable from the export) — that is a real rendered state, not a placeholder. `live_source.py` is deliberately deferred to v2 and is NOT a task here.

**3. Type consistency:** `ClientData`/event dataclasses (Task 1) consumed unchanged in Tasks 3–9. `run_agent(*, model, role_prompt, json_schema_description, input_payload, fallback_factory, client=None)` matches `dashboard/agents/_client.py`. `compute_all` keys (kpis/scorecard/campaigns/senders/deliverability/timing/leads/coverage) match the template includes in Task 9 and the metric bag saved by snapshots. `deltas(current, prior)` is fed `metrics["kpis"]` in both Task 7 tests and `render.main`.

---

## Execution Handoff

Plan complete. Choose execution mode when ready (see end of conversation).
