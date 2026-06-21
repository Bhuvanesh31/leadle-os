# Client Dashboard Productization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the approved hand-built client dashboard (`reports/client/upsta-monthly-full.html`) into a callable, tested function that regenerates 4 outputs (weekly+monthly × internal+client) from live Aimfox/Instantly APIs + the prospect workbook XLSX, by extending the existing `dashboard/client/` pipeline.

**Architecture:** Three sources (Aimfox REST = LinkedIn campaign analytics + variant text; Instantly REST = email campaign analytics; sheet XLSX = spine prospects + webhook reply sentiment + open timestamps) merge into a normalized `ClientData`. `compute.compute_all` produces one metrics dict per block. Jinja templates (audience-gated) render it; the render CLI emits all four outputs. Hardcoded for UPSTA + Aimfox + Instantly (no multi-client machinery).

**Tech Stack:** Python 3.12, `openpyxl` (XLSX), `httpx` (REST), Jinja2 (autoescape on), pytest. Existing: `dashboard/client/{model,compute,snapshots,render}.py`, `dashboard/client/agents/{narrative,actions}.py`, `connectors/aimfox/`.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-06-21-client-dashboard-productization-design.md`. Design fidelity target is `reports/client/upsta-monthly-full.html` (verbatim CSS/markup source for templates).
- **Hardcode UPSTA + Aimfox + Instantly.** No `config/clients/` selector, no generic client loader. UPSTA source identifiers are constants in `dashboard/client/constants.py`.
- **Source split (locked):** campaign reply *counts/rates* are API-authoritative (Aimfox/Instantly); reply *sentiment split* (positive/neutral/negative) and hourly *open timestamps* are webhook-XLSX-authoritative.
- **Leads = any positive response.** Meetings stay degraded (no CRM).
- **Bounce = event-based** (`email_bounced` events / `email_sent` events). Bounce threshold sourced from `rubric.bounce_flag_threshold` (never hardcode the number in code).
- **Audience gating:** client outputs must never contain `senders`, `deliverability`, `actions` blocks, nor the strings `augustine`, `pause & warm`, `Sender health` (test-enforced). Driven by `config/client_report_layout.yaml` `visibility`.
- **Jinja autoescape = True** (already enforced; keep it).
- **Voice:** user-facing copy avoids em dashes and the AI-filler list in `CLAUDE.md`. Use parens/colons.
- **No live API calls in tests** — mock `httpx`/connector responses; XLSX via a committed fixture.
- **Connector pattern:** mirror `connectors/aimfox/{fetch.py,cli.py}` — env key via `dotenv`, returns `{available: bool, data|reason}`, CLI exit 0 always.
- **Periods:** monthly compares MoM, weekly compares WoW, via the existing `snapshots.deltas`.

---

## File Structure

**Create:**
- `dashboard/client/constants.py` — UPSTA hardcoded identifiers (sheet id, tab names, campaign filter, timezone, env var names).
- `connectors/instantly/fetch.py` — Instantly REST: per-campaign analytics, account analytics, step analytics.
- `connectors/instantly/cli.py` — CLI wrapper (mirror aimfox cli).
- `dashboard/client/sources/aimfox_source.py` — Aimfox → `LinkedInCampaign[]` (+ variant text).
- `dashboard/client/sources/instantly_source.py` — Instantly → `EmailCampaign[]`, sender rows, content steps.
- `dashboard/client/sources/loader.py` — `load(xlsx_path, window) -> ClientData` assembler.
- `tests/client/test_sheet_source_xlsx.py`, `tests/client/test_instantly_source.py`, `tests/client/test_aimfox_source.py`, `tests/client/test_loader.py`, `tests/client/test_compute_v2.py`, `tests/client/test_render_golden.py`.
- `tests/client/fixtures/upsta_mini.xlsx` — tiny real-shaped workbook (built by a committed generator script `tests/client/fixtures/make_upsta_mini.py`).

**Modify:**
- `dashboard/client/model.py` — add `EmailCampaign`, `LinkedInCampaign`, `ReplyRecord`, `OpenEvent`; extend `ClientData`.
- `dashboard/client/sources/sheet_source.py` — XLSX ingestion + webhook tabs + spine + response tracker.
- `dashboard/client/compute.py` — rewrite blocks to consume campaign-level data + replies.
- `config/client_report_rubric.yaml` — grade bands tuned to UPSTA + benchmarks block + variant/content config.
- `config/client_report_layout.yaml` — add `variants` block; keep visibility.
- `dashboard/client/templates/report_base.html.j2` + `blocks/*.html.j2` — rebuild to approved design.
- `dashboard/client/render.py` — emit 4 outputs; period (weekly/monthly) + audience loop; call `loader.load`.
- `dashboard/client/agents/actions.py` — already rubric-sourced (Task done pre-plan); confirm only.

---

### Task 1: Model extension — campaign-level + reply records

**Files:**
- Modify: `dashboard/client/model.py`
- Test: `tests/client/test_model_v2.py` (create)

**Interfaces:**
- Produces:
  - `EmailCampaign(name: str, sent: int, opened: int, clicked: int, bounced: int, replied: int)`
  - `LinkedInCampaign(name: str, invites: int, accepted: int, replied: int, variant_message: str = "")`
  - `ReplyRecord(channel: str, campaign: str, sentiment: str, name: str, ts: datetime | None)` — `channel` in {"email","linkedin"}; `sentiment` in {"positive","neutral","negative","untagged"}.
  - `OpenEvent(channel: str, ts: datetime)` — email opens for the timing heatmap.
  - `ClientData` gains fields: `email_campaigns: list[EmailCampaign]`, `linkedin_campaigns: list[LinkedInCampaign]`, `replies: list[ReplyRecord]`, `opens: list[OpenEvent]`, `senders: list[dict]` (raw per-inbox dicts from Instantly), `content_steps: list[dict]`. Keep existing `emails`, `linkedin`, `warm_leads`, `targets`, `context` (back-compat; `emails`/`linkedin` may be empty under the new sources).

- [ ] **Step 1: Write the failing test**

```python
# tests/client/test_model_v2.py
from datetime import datetime
from dashboard.client.model import (
    ClientData, EmailCampaign, LinkedInCampaign, ReplyRecord, OpenEvent)

def test_new_dataclasses_and_clientdata_fields():
    ec = EmailCampaign(name="Upsta_SFDI_V1", sent=414, opened=140, clicked=42,
                       bounced=41, replied=0)
    lc = LinkedInCampaign(name="Upsta_US_PMP_V1", invites=188, accepted=9,
                          replied=3, variant_message="Hi {{FIRST_NAME}}, I'm ...")
    rr = ReplyRecord(channel="linkedin", campaign="Upsta_US_PMP_V1",
                     sentiment="neutral", name="Donna Saunders", ts=None)
    oe = OpenEvent(channel="email", ts=datetime(2026, 6, 3, 13, 14))
    d = ClientData(email_campaigns=[ec], linkedin_campaigns=[lc],
                   replies=[rr], opens=[oe])
    assert d.email_campaigns[0].clicked == 42
    assert d.linkedin_campaigns[0].variant_message.startswith("Hi")
    assert d.replies[0].sentiment == "neutral"
    assert d.opens[0].ts.hour == 13
    # back-compat defaults
    assert d.emails == [] and d.targets == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/client/test_model_v2.py -v`
Expected: FAIL with `ImportError` / `TypeError` (new classes/fields absent).

- [ ] **Step 3: Implement**

Add to `dashboard/client/model.py` (after the existing dataclasses):

```python
@dataclass
class EmailCampaign:
    name: str
    sent: int = 0
    opened: int = 0
    clicked: int = 0
    bounced: int = 0
    replied: int = 0

@dataclass
class LinkedInCampaign:
    name: str
    invites: int = 0
    accepted: int = 0
    replied: int = 0
    variant_message: str = ""

@dataclass
class ReplyRecord:
    channel: str
    campaign: str
    sentiment: str
    name: str
    ts: "datetime | None" = None

@dataclass
class OpenEvent:
    channel: str
    ts: datetime
```

Extend `ClientData` field list with:

```python
    email_campaigns: list[EmailCampaign] = field(default_factory=list)
    linkedin_campaigns: list[LinkedInCampaign] = field(default_factory=list)
    replies: list[ReplyRecord] = field(default_factory=list)
    opens: list[OpenEvent] = field(default_factory=list)
    senders: list[dict] = field(default_factory=list)
    content_steps: list[dict] = field(default_factory=list)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/client/test_model_v2.py -v`
Expected: PASS.

- [ ] **Step 5: Run full suite (no regressions), then commit**

Run: `.venv/bin/python -m pytest tests/ -q` — Expected: all pass.
```bash
git add dashboard/client/model.py tests/client/test_model_v2.py
git commit -m "feat(client-dash): model — campaign-level + reply/open records"
```

---

### Task 2: Instantly REST connector (email campaign analytics)

**Files:**
- Create: `connectors/instantly/fetch.py`, `connectors/instantly/cli.py`
- Test: `tests/connectors/test_instantly_fetch.py` (create)

**Interfaces:**
- Produces `fetch(api_key, window_start, window_end, *, name_contains, client=None) -> dict`:
  `{"available": True, "data": {"campaigns": [{"name", "sent", "opened", "clicked", "bounced", "replied"}], "senders": [{"from_email","sent","bounced"}], "steps": [{"step","opened","clicked"}]}}` or `{"available": False, "reason": str}`.
- Base URL `https://api.instantly.ai/api/v2`. Auth header `Authorization: Bearer <key>`. **Set `User-Agent: Mozilla/5.0`** (urllib/default UA is WAF-blocked — see `docs/data-shape`). Per-campaign analytics endpoint: `GET /campaigns/analytics?id=<id>&start_date=&end_date=` (authoritative totals, NOT the daily endpoint).

- [ ] **Step 1: Write the failing test** (mock httpx)

```python
# tests/connectors/test_instantly_fetch.py
import httpx
from connectors.instantly.fetch import fetch

def _mock(transport_map):
    def handler(request: httpx.Request) -> httpx.Response:
        for frag, payload in transport_map.items():
            if frag in str(request.url):
                return httpx.Response(200, json=payload)
        return httpx.Response(404, json={})
    return httpx.MockTransport(handler)

def test_fetch_shapes_campaigns_and_filters_by_name():
    tmap = {
        "/campaigns": {"items": [
            {"id": "c1", "name": "Upsta_SFDI_V1"},
            {"id": "c2", "name": "OtherClient_V1"}]},
        "/campaigns/analytics": {"emails_sent_count": 414, "open_count": 140,
                                 "link_click_count": 42, "bounced_count": 41,
                                 "reply_count": 0},
    }
    client = httpx.Client(transport=_mock(tmap))
    out = fetch("KEY", "2026-06-01", "2026-06-30", name_contains="upsta", client=client)
    assert out["available"] is True
    camps = out["data"]["campaigns"]
    assert [c["name"] for c in camps] == ["Upsta_SFDI_V1"]  # filtered
    assert camps[0]["sent"] == 414 and camps[0]["clicked"] == 42

def test_fetch_degrades_on_http_error():
    def boom(request): raise httpx.ConnectError("down")
    client = httpx.Client(transport=httpx.MockTransport(boom))
    out = fetch("KEY", "2026-06-01", "2026-06-30", name_contains="upsta", client=client)
    assert out["available"] is False and "reason" in out
```

- [ ] **Step 2: Run to verify it fails** — `.venv/bin/python -m pytest tests/connectors/test_instantly_fetch.py -v` → FAIL (module missing).

- [ ] **Step 3: Implement `connectors/instantly/fetch.py`**

```python
"""Instantly REST connector. Mirrors connectors/aimfox/fetch.py.
Per-campaign authoritative analytics (NOT the daily endpoint, which double-counts).
"""
from __future__ import annotations
from datetime import date
from typing import Any
import httpx

_BASE_URL = "https://api.instantly.ai/api/v2"
_TIMEOUT = 30.0
_UA = "Mozilla/5.0"  # default urllib UA is WAF-blocked (see docs/data-shape)


def fetch(api_key: str, window_start, window_end, *,
          name_contains: str | None = None,
          client: httpx.Client | None = None) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {api_key}", "User-Agent": _UA}
    owns = client is None
    client = client or httpx.Client(headers=headers, timeout=_TIMEOUT)
    try:
        camps = _list_campaigns(client)
        if name_contains:
            needle = name_contains.lower()
            camps = [c for c in camps if needle in (c.get("name") or "").lower()]
        out = [_shape(c, _analytics(client, c["id"], window_start, window_end))
               for c in camps]
        return {"available": True, "data": {"campaigns": out, "senders": [], "steps": []}}
    except httpx.HTTPError as e:
        return {"available": False, "reason": f"instantly REST error: {type(e).__name__}: {e}"}
    finally:
        if owns:
            client.close()


def _list_campaigns(client):
    r = client.get(f"{_BASE_URL}/campaigns")
    r.raise_for_status()
    body = r.json()
    return body.get("items", body.get("campaigns", []))


def _analytics(client, cid, start, end):
    r = client.get(f"{_BASE_URL}/campaigns/analytics",
                   params={"id": cid, "start_date": str(start), "end_date": str(end)})
    r.raise_for_status()
    a = r.json()
    if isinstance(a, list):
        a = a[0] if a else {}
    return a


def _shape(c, a):
    return {
        "name": c.get("name"),
        "sent": int(a.get("emails_sent_count", 0) or 0),
        "opened": int(a.get("open_count", 0) or 0),
        "clicked": int(a.get("link_click_count", 0) or 0),
        "bounced": int(a.get("bounced_count", 0) or 0),
        "replied": int(a.get("reply_count", 0) or 0),
    }
```

- [ ] **Step 4: Run to verify pass** — same pytest → PASS.

- [ ] **Step 5: Add CLI** `connectors/instantly/cli.py` (mirror aimfox cli: load_dotenv, read `INSTANTLY_API_KEY`, `--start/--end/--name-contains`, print JSON, exit 0). Then commit.

```bash
git add connectors/instantly/ tests/connectors/test_instantly_fetch.py
git commit -m "feat(connectors): instantly REST — per-campaign email analytics"
```

> NOTE for implementer: `senders` and `steps` arrays are returned empty here and populated in Task 9 (they need the account-analytics and step-analytics endpoints). Leaving them `[]` keeps Task 2 independently shippable and tested.

---

### Task 3: Aimfox source — LinkedIn campaigns + variant text

**Files:**
- Create: `dashboard/client/sources/aimfox_source.py`
- Modify: `connectors/aimfox/fetch.py` (add a `fetch_campaign_detail` for variant text + accept/reply analytics)
- Test: `tests/client/test_aimfox_source.py`

**Interfaces:**
- Consumes: env `AIMFOX_API_KEY`, window, campaign filter `"upsta"`.
- Produces `aimfox_source.read(api_key, window, *, name_contains, client=None) -> list[LinkedInCampaign]` where each carries `invites` (sent_connections), `accepted` (accepted_connections), `replied` (replies + inmail_replies), `variant_message` (PRIMARY_CONNECT flow `template.message`).
- Per-campaign analytics: `GET /analytics/interactions?campaign_id=&from=&to=&bucket=1%20day` (bucket MUST be url-encoded `1 day`). Variant text: `GET /campaigns/{id}` → `flows[]` first `type=="PRIMARY_CONNECT"` → `template.message`.

- [ ] **Step 1: Write failing test** (mock httpx via the same `_mock` helper as Task 2; assert one `LinkedInCampaign` with invites/accepted/replied summed from buckets and `variant_message` from the flow). Full test code:

```python
# tests/client/test_aimfox_source.py
import httpx
from dashboard.client.sources import aimfox_source

def _mock(m):
    def h(req):
        for frag, payload in m.items():
            if frag in str(req.url):
                return httpx.Response(200, json=payload)
        return httpx.Response(404, json={})
    return httpx.MockTransport(h)

def test_read_builds_campaign_with_variant_and_metrics():
    m = {
        "/campaigns?": {"campaigns": [{"id": "a1", "name": "Upsta_US_PMP_V1"},
                                      {"id": "z9", "name": "Other_V1"}]},
        "/campaigns/a1": {"campaign": {"flows": [
            {"type": "PRIMARY_CONNECT", "template": {"message": "Hi {{FIRST_NAME}}, founder"}}]}},
        "/analytics/interactions": {"buckets": [
            {"sent_connections": 100, "accepted_connections": 5, "replies": 2, "inmail_replies": 1},
            {"sent_connections": 88, "accepted_connections": 4, "replies": 0, "inmail_replies": 0}]},
    }
    client = httpx.Client(transport=_mock(m))
    camps = aimfox_source.read("KEY", ("2026-05-01", "2026-07-01"),
                               name_contains="upsta", client=client)
    assert len(camps) == 1
    c = camps[0]
    assert c.name == "Upsta_US_PMP_V1"
    assert c.invites == 188 and c.accepted == 9 and c.replied == 3
    assert c.variant_message.startswith("Hi")
```

- [ ] **Step 2: Verify fail** → module missing.

- [ ] **Step 3: Implement `aimfox_source.read`** building `LinkedInCampaign` objects (list campaigns, filter by name_contains, per campaign sum interaction buckets + pull PRIMARY_CONNECT message). Reuse `connectors.aimfox.fetch` helpers where possible; add `fetch_campaign_detail(client, cid)` to `connectors/aimfox/fetch.py` returning the `campaign` dict. Convert window ISO dates to epoch-ms (reuse `_window_to_epoch_ms`).

- [ ] **Step 4: Verify pass.**

- [ ] **Step 5: Commit** `feat(client-dash): aimfox source — LinkedIn campaigns + variant text`.

---

### Task 4: sheet_source XLSX ingestion (spine + webhook sentiment + opens + warm leads)

**Files:**
- Modify: `dashboard/client/sources/sheet_source.py` (add `read_xlsx(path) -> ClientData`; keep old text `read` for back-compat or remove if unused — check `render.py` call site, which Task 13 updates)
- Test: `tests/client/test_sheet_source_xlsx.py`
- Create fixture generator: `tests/client/fixtures/make_upsta_mini.py` + committed `tests/client/fixtures/upsta_mini.xlsx`

**Interfaces:**
- Produces `sheet_source.read_xlsx(path: str) -> ClientData` populating: `targets` (spine rows → `TargetCo` with `aimfox_id`/`instantly_id`), `replies` (webhook reply rows → `ReplyRecord` with sentiment), `opens` (webhook email `email_opened` rows → `OpenEvent` with ts), `warm_leads` (Response Tracker rows). Engine: `openpyxl.load_workbook(path, read_only=True, data_only=True)`; per tab iterate rows, skip repeated header rows and all-None rows; resolve columns by header NAME.
- Tab names (from `constants.py`, Task 6): spine `["Prospect Data-US", "Prospect Data- Singapore"]`, webhook `"Webhook - LinkedIn"`/`"Webhook - Email"`, `"Response Tracker"`.

- [ ] **Step 1: Write the fixture generator** `tests/client/fixtures/make_upsta_mini.py` using openpyxl to build a tiny workbook with: a spine tab (2 rows, one with both ids, one email-only), a `Webhook - LinkedIn` tab (1 reply row, sentiment "neutral", + a repeated header row to exercise pagination), a `Webhook - Email` tab (2 `email_opened` rows with timestamps + 1 `email_sent`), a `Response Tracker` tab (1 positive row). Run it to emit `upsta_mini.xlsx`. (Commit the .xlsx so tests don't depend on regeneration.)

- [ ] **Step 2: Write the failing test**

```python
# tests/client/test_sheet_source_xlsx.py
from pathlib import Path
from dashboard.client.sources import sheet_source

FIX = Path(__file__).parent / "fixtures" / "upsta_mini.xlsx"

def test_xlsx_parses_spine_replies_opens_warm():
    d = sheet_source.read_xlsx(str(FIX))
    # spine -> targets with cadence ids
    assert len(d.targets) == 2
    assert any(t.aimfox_id and t.instantly_id for t in d.targets)
    # webhook LinkedIn reply with sentiment (repeated header row ignored)
    assert any(r.channel == "linkedin" and r.sentiment == "neutral" for r in d.replies)
    # webhook email opens carry timestamps
    assert len(d.opens) == 2 and all(o.ts is not None for o in d.opens)
    # response tracker -> warm lead
    assert len(d.warm_leads) == 1
```

- [ ] **Step 3: Verify fail** → `read_xlsx` missing.

- [ ] **Step 4: Implement `read_xlsx`** — openpyxl reader with a header-name column map; reuse the repeated-header skip logic from `/tmp/reply_metrics.py` (see spec). Email reply sentiment column is `Reply Sentiment`; LinkedIn `Event Type` in {reply, campaign_reply} = reply rows; email opens = `Event Type == email_opened` rows (ts from `Event Timestamp`). Spine ids resolved by header name `Aimfox ID`/`Instantly ID` (int-coerce numeric Aimfox IDs to avoid float artifacts).

- [ ] **Step 5: Verify pass; full suite; commit** `feat(client-dash): sheet_source XLSX ingestion (spine/sentiment/opens)`.

---

### Task 5: Sources assembler (`loader.load`)

**Files:**
- Create: `dashboard/client/sources/loader.py`
- Test: `tests/client/test_loader.py`

**Interfaces:**
- Consumes: `sheet_source.read_xlsx`, `aimfox_source.read`, `instantly_source.read` (Task 9 adds instantly_source; until then loader calls `connectors.instantly.fetch` and shapes to `EmailCampaign`).
- Produces `loader.load(xlsx_path: str, window: tuple[str,str], *, aimfox_key: str, instantly_key: str, name_contains: str, aimfox_client=None, instantly_client=None) -> ClientData` — merges sheet (targets/replies/opens/warm_leads) + aimfox (linkedin_campaigns) + instantly (email_campaigns). On an API source returning `available: False`, leaves that campaign list `[]` and records nothing fatal (degrade).

- [ ] **Step 1: Failing test** — call `load` with the mini XLSX + mocked aimfox/instantly clients; assert `ClientData` has targets (from sheet), linkedin_campaigns (from aimfox), email_campaigns (from instantly), replies (from sheet). Full test mirrors Tasks 2-4 mocks.

- [ ] **Step 2-4:** implement the merge; verify.

- [ ] **Step 5: Commit** `feat(client-dash): sources loader assembles XLSX + Aimfox + Instantly`.

---

### Task 6: Config + constants (benchmarks, grade bands, blocks, UPSTA identifiers)

**Files:**
- Create: `dashboard/client/constants.py`
- Modify: `config/client_report_rubric.yaml`, `config/client_report_layout.yaml`
- Test: `tests/client/test_config.py`

**Interfaces:**
- `constants.py` exposes: `SHEET_DRIVE_ID="1GgFeDdXpy1ZlDjH8bTWNL_c7m0ihSSO_-iYNyzadCQg"`, `SPINE_TABS=["Prospect Data-US","Prospect Data- Singapore"]`, `WEBHOOK_LI="Webhook - LinkedIn"`, `WEBHOOK_EMAIL="Webhook - Email"`, `RESPONSE_TRACKER="Response Tracker"`, `CAMPAIGN_FILTER="upsta"`, `TIMEZONE="America/New_York"`, `AIMFOX_ENV="AIMFOX_API_KEY"`, `INSTANTLY_ENV="INSTANTLY_API_KEY"`.
- rubric gains `benchmarks: {open_rate: 0.20, click_rate: 0.02, positive_replies_month: 4, total_replies_month: 12, bounce_rate_max: 0.04}` and re-tuned `grades` bands so UPSTA's 29% open → A (e.g. `open_rate: [[0.20,"A"],[0.12,"B"],[0.08,"C"],[0.04,"D"],[0.0,"F"]]`; add `"F"` floor to each metric). Set `timezone: "America/New_York"`.
- layout gains `{key: variants, title: "Which LinkedIn message worked", visibility: both}` after `content`.

- [ ] **Step 1: Failing test**

```python
# tests/client/test_config.py
import yaml
from pathlib import Path
from dashboard.client import constants
ROOT = Path(__file__).resolve().parents[2]

def test_rubric_has_benchmarks_and_f_floor():
    r = yaml.safe_load((ROOT/"config/client_report_rubric.yaml").read_text())
    assert r["benchmarks"]["open_rate"] == 0.20
    assert r["grades"]["open_rate"][0] == [0.20, "A"]
    assert any(b[1] == "F" for b in r["grades"]["open_rate"])

def test_layout_has_variants_block():
    l = yaml.safe_load((ROOT/"config/client_report_layout.yaml").read_text())
    assert any(b["key"] == "variants" for b in l["blocks"])

def test_constants_present():
    assert constants.CAMPAIGN_FILTER == "upsta"
    assert constants.TIMEZONE == "America/New_York"
```

- [ ] **Step 2-4:** add constants + edit YAMLs; verify.

- [ ] **Step 5: Commit** `feat(client-dash): UPSTA constants + benchmark bands + variants block`.

---

### Task 7: Compute — KPIs + scorecard from campaign data + replies

**Files:**
- Modify: `dashboard/client/compute.py`
- Test: `tests/client/test_compute_v2.py` (create; covers Tasks 7-11)

**Interfaces:**
- Rewrite `kpis(data, rubric) -> dict` to aggregate over `data.email_campaigns` (sent/opened/clicked/bounced summed) and `data.linkedin_campaigns` (invites/accepted summed), and `data.replies` for sentiment. Keys: `emails_sent, opened, clicked, bounced, open_rate (opened/(sent-bounced)? — use delivered=sent-bounced), click_rate, bounce_rate (bounced/sent, event-based), invites, accepted, accept_rate, li_replies (len replies channel==linkedin), email_replies (channel==email, human), total_replies, positive_replies (sentiment=='positive'), neutral_replies, negative_replies, leads (==positive_replies), meetings (from warm_leads meeting_statuses), fresh_prospects (distinct via opens/instantly_id — keep simple: sum campaign sent)`.
- `scorecard(k, rubric)` grades `open_rate, reply_rate (=total_replies/ benchmark-relative via grade bands), positive, bounce_rate, accept_rate`; overall = weakest (extend order string to `"ABCDF"`).

- [ ] **Step 1: Failing test** (build a `ClientData` with 2 EmailCampaign + 2 LinkedInCampaign + reply records; assert kpi sums, bounce event-based, positive count, leads==positive, and scorecard grades open→A given band).

```python
# tests/client/test_compute_v2.py  (excerpt — full file accumulates across Tasks 7-11)
import yaml
from pathlib import Path
from datetime import datetime
from dashboard.client import compute
from dashboard.client.model import (ClientData, EmailCampaign, LinkedInCampaign, ReplyRecord)
ROOT = Path(__file__).resolve().parents[2]
RUBRIC = yaml.safe_load((ROOT/"config/client_report_rubric.yaml").read_text())

def _data():
    return ClientData(
        email_campaigns=[EmailCampaign("Upsta_SFDI_V1",414,140,42,41,0),
                         EmailCampaign("Upsta_PMP_V1",598,215,0,44,0)],
        linkedin_campaigns=[LinkedInCampaign("Upsta_US_PMP_V1",188,9,3,"Hi founder"),
                            LinkedInCampaign("Upsta_Recon_V3",46,0,0,"Hi recon")],
        replies=[ReplyRecord("linkedin","Upsta_US_PMP_V1","neutral","Donna",None),
                 ReplyRecord("linkedin","Upsta_US_PMP_V1","untagged","",None)])

def test_kpis_aggregate_and_leads_equal_positive():
    k = compute.kpis(_data(), RUBRIC)
    assert k["emails_sent"] == 1012 and k["bounced"] == 85
    assert round(k["bounce_rate"], 4) == round(85/1012, 4)  # event-based
    assert k["invites"] == 234 and k["accepted"] == 9
    assert k["li_replies"] == 2 and k["positive_replies"] == 0
    assert k["leads"] == k["positive_replies"]

def test_scorecard_open_grade_A():
    k = compute.kpis(_data(), RUBRIC)
    sc = compute.scorecard(k, RUBRIC)
    # open_rate = 355 / (1012-85) = 0.383 -> band >=0.20 = A? (re-tuned bands: >=0.20 A)
    assert sc["grades"]["open_rate"] == "A"
```

- [ ] **Step 2-4:** implement; verify. (Adjust the open-rate denominator decision: `delivered = sent - bounced`.)

- [ ] **Step 5: Commit** `feat(client-dash): compute KPIs + scorecard from campaign data`.

---

### Task 8: Compute — unified campaign table (email + LinkedIn, ranked, graded)

**Files:** Modify `dashboard/client/compute.py`; extend `tests/client/test_compute_v2.py`.

**Interfaces:**
- `campaign_table(data, rubric) -> list[dict]` returns email rows then LinkedIn rows. Email row: `{name, channel:"Email", sent, reply_rate:0.0, secondary:click_rate, secondary_label:"click", open_rate, bounce_rate, grade}`, sorted by `(reply_rate desc, click_rate desc, open_rate desc)`. LinkedIn row: `{name, channel:"LinkedIn", sent:invites, reply_rate:replied/invites, secondary:accept_rate, secondary_label:"accept", bounce_rate:None, grade}`, sorted by `(reply_rate desc, accept_rate desc)`. Grade per channel from rubric bands.

- [ ] **Step 1: Failing test** — assert email rows ordered with SFDI (click 0.101) before PMP (click 0), LinkedIn PMP (reply>0) first; assert `channel` grouping (all email rows precede all LinkedIn rows).
- [ ] **Step 2-4:** implement; verify.
- [ ] **Step 5: Commit** `feat(client-dash): unified campaign table ranked per channel`.

---

### Task 9: Compute — variants + content steps; Instantly senders/steps

**Files:** Modify `connectors/instantly/fetch.py` (populate `senders` via `GET /accounts/analytics`, `steps` via `GET /campaigns/analytics/steps`); modify `dashboard/client/compute.py`; extend tests.

**Interfaces:**
- `variants(data, rubric) -> list[dict]` from `data.linkedin_campaigns`: `{name, accept_rate, replies, reply_rate, hook}` (hook = first ~80 chars of `variant_message`), sorted reply_rate→accept_rate; flag the reply winner.
- `content_steps(data) -> list[dict]` from `data.content_steps` (Instantly steps): `{step, open_rate}`.
- `sender_wise(data, rubric)` now reads `data.senders` (each `{from_email, sent, bounced}`); bounce event-based; `flag = bounce_rate >= rubric["bounce_flag_threshold"]`.

- [ ] **Step 1-4:** tests + impl (mock the two new Instantly endpoints in `tests/connectors/test_instantly_fetch.py`).
- [ ] **Step 5: Commit** `feat(client-dash): variants, content steps, sender health`.

---

### Task 10: Compute — timing heatmap (blue matrix) from webhook opens

**Files:** Modify `dashboard/client/compute.py`; extend tests.

**Interfaces:**
- `timing_heatmap(data, rubric) -> dict` from `data.opens` (email `OpenEvent`s). Convert ts to `rubric["timezone"]`, bucket weekday(Mon-Fri) × daypart (rubric `dayparts`), produce `grid[weekday][daypart] = count`, `max`, and per-cell intensity level 0-4 (`level = 0 if c==0 else 1..4 by quartile of max`). Return `{weekdays, dayparts, grid, levels, max, best, timezone}`. Template maps level→blue shade.

- [ ] **Step 1: Failing test** — build opens on Wed morning ×3, Fri afternoon ×1; assert Wed/morning level==4 (max), Fri level lower, empty cells level 0.
- [ ] **Step 2-4:** implement; verify.
- [ ] **Step 5: Commit** `feat(client-dash): blue timing heatmap from webhook opens`.

---

### Task 11: Compute — channel reach + lead ladder (positive = lead); compute_all

**Files:** Modify `dashboard/client/compute.py`; extend tests.

**Interfaces:**
- `channel_reach(data)` unchanged logic (spine cadence ids) — keep.
- `lead_ladder(data, rubric)` rework: Hot = `data.replies` with sentiment=="positive" (each a named lead) + warm_leads positive/meeting; Warm = LinkedIn accepted (from `linkedin_campaigns` accepted counts — show count, not names, since campaign-level has no names); `reached` from `channel_reach`. Ladder dict: `{reached, engaged, positive_leads, meetings, hot:[...], warm_count}`.
- `compute_all(data, rubric)` returns keys matching layout blocks: `kpis, scorecard, campaigns, content, variants, senders, deliverability, timing, reach, leads, narrative?(no - agent), targets?`. (narrative/actions injected by render, not compute.)

- [ ] **Step 1-4:** tests (assert positive reply becomes a Hot lead; leads count == positive); impl; verify full suite.
- [ ] **Step 5: Commit** `feat(client-dash): reach + lead ladder (positive=lead) + compute_all`.

---

### Task 12: Templates — rebuild to approved design

**Files:**
- Modify: `dashboard/client/templates/report_base.html.j2` (CSS design system), all `dashboard/client/templates/blocks/*.html.j2`, add `blocks/variants.html.j2`.
- Test: `tests/client/test_templates_v2.py`

**Interfaces:**
- **Verbatim design source:** `reports/client/upsta-monthly-full.html`. The implementer ports its `<style>` block into `report_base.html.j2` and its section markup into the matching block partials, replacing hardcoded numbers with `{{ metrics.<...> }}` / loops. Keep `autoescape=True`. Tooltips (`.pop/.tip/.rowtip`) and the blue heatmap palette (`#EFF6FF #DBEAFE #93C5FD #3B82F6 #1D4ED8`, by `level`) come from that file.
- Blocks render from `metrics[b.key]`; audience gating stays via `visible_blocks(layout, audience)`.

- [ ] **Step 1: Failing test**

```python
# tests/client/test_templates_v2.py
from dashboard.client import render
# build a metrics dict via compute over the mini fixture + mocked APIs (helper), then:
def test_client_output_has_no_internal_leak_and_shows_kpis(rendered_client_html):
    h = rendered_client_html
    assert "1,012" in h or "1012" in h  # an emails-sent figure renders
    for leak in ("augustine", "pause & warm", "Sender health", "Signal-to-Motion"):
        assert leak.lower() not in h.lower()

def test_internal_output_includes_sender_health(rendered_internal_html):
    assert "sender" in rendered_internal_html.lower()
```

(Provide `rendered_client_html`/`rendered_internal_html` fixtures in `conftest.py` that run compute over the mini XLSX + mocked Aimfox/Instantly and render each audience.)

- [ ] **Step 2-4:** port CSS + markup; verify gating + autoescape (`<` in a campaign name renders escaped).
- [ ] **Step 5: Commit** `feat(client-dash): templates rebuilt to approved design`.

---

### Task 13: Render CLI — 4 outputs (weekly+monthly × internal+client)

**Files:** Modify `dashboard/client/render.py`; test `tests/client/test_render_cli.py`.

**Interfaces:**
- `main()` args: `--xlsx <path>` (replaces `--workbook`), `--period {weekly,monthly}` OR `--all-periods`, `--audience {internal,client,both}` default both, `--period-end`, `--snapshot-store`, `--output-dir`.
- Flow: resolve window from period+period-end; `loader.load(xlsx, window, aimfox_key=os.environ[...], instantly_key=..., name_contains=constants.CAMPAIGN_FILTER)`; `compute_all`; snapshot deltas (MoM monthly / WoW weekly); agents (narrative per audience, actions internal); render each requested (period × audience) → write `reports/client/upsta-<period_end>-<period>-<audience>.html`. Print each path.
- Default invocation renders all 4: `--all-periods --audience both`.

- [ ] **Step 1: Failing test** — invoke `main(["--xlsx", FIX, "--all-periods", "--audience", "both", "--skip-agents", "--period-end", "2026-06-30", "--output-dir", tmp])` with monkeypatched loader API clients (env keys faked, httpx mocked) → asserts 4 files written with expected names.
- [ ] **Step 2-4:** implement; verify.
- [ ] **Step 5: Commit** `feat(client-dash): render emits 4 outputs (period x audience)`.

---

### Task 14: Slash command + render runbook + golden check; live UPSTA render

**Files:**
- Create: `.claude/commands/render-client-report.md`
- Modify: `docs/data-shape/prospect-list-sheet.md` (append "Render runbook" section)
- Test: `tests/client/test_render_golden.py`

**Interfaces:**
- Slash command protocol: (1) download the workbook XLSX via Drive MCP (`download_file_content`, exportMimeType `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`) using `constants.SHEET_DRIVE_ID` to a temp path; (2) run `python -m dashboard.client.render --xlsx <path> --all-periods --audience both --period-end <today>`; (3) report the 4 output paths. Allowed-tools: Bash, Google Drive MCP.
- Runbook section: env keys required (`AIMFOX_API_KEY`, `INSTANTLY_API_KEY`), the XLSX download step, the render command, where outputs land.
- `test_render_golden.py`: render the mini fixture (client+monthly) and assert the key block structure markers are present (`Benchmark scorecard`, `Which campaign performed`, `Which LinkedIn message worked`, the heatmap legend), i.e. the productized output structurally matches the approved design.

- [ ] **Step 1-4:** write command + runbook + golden test; verify full suite green.
- [ ] **Step 5:** Live UPSTA render via the slash command's steps (session downloads real XLSX; render with real env keys). Sanity-check numbers against this session's figures (emails ~1,661; LI invites ~786 to-date; positive 0; bounce ~6.3%). Note any API-vs-webhook deltas in the internal output's reconciliation note.
- [ ] **Step 6: Commit** `feat(client-dash): render-client-report command + runbook + golden test`.

---

## Self-Review

**Spec coverage:** source layer (T2-T5), compute blocks (T7-T11), config/constants (T6), templates (T12), 4-output render (T13), error handling (degrade paths in T2/T5/T13), testing (every task + golden T14), slash command + runbook (T14), leads=positive (T7/T11), bounce event-based (T7), audience gating (T12). Covered.

**Placeholder scan:** template task references the approved HTML as the verbatim source rather than re-transcribing 340 lines — concrete in-repo artifact, not a placeholder. Connector `senders`/`steps` empty-then-filled is explicitly sequenced (T2→T9), not a TODO.

**Type consistency:** `EmailCampaign`/`LinkedInCampaign`/`ReplyRecord`/`OpenEvent` (T1) are consumed with the same field names in compute (T7-T11), loader (T5), and sources (T3-T4). `kpis` keys used by `scorecard` (T7), `campaign_table` (T8), templates (T12) match. `loader.load` signature (T5) matches the render call site (T13).
