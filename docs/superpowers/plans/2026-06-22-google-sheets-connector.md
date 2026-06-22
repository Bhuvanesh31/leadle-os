# Google Sheets Connector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the client-dashboard render pipeline read the UPSTA workbook live from the Google Sheets API (no manual xlsx download), with `--xlsx` retained as an offline override.

**Architecture:** Refactor the existing xlsx parser into a provider-agnostic core (`_parse_tabs`) fed by two row-providers — `read_xlsx` (openpyxl) and `read_sheets` (live Sheets via a new `connectors/google_sheets/fetch.py`). Auth is OAuth user credentials acting as `revops@leadle.in`. A `config/clients.yaml` registry maps client → spreadsheet id.

**Tech Stack:** Python 3, openpyxl (existing), gspread + google-auth + google-auth-oauthlib (new), PyYAML (existing), pytest.

## Global Constraints

- **Read-only against source systems.** OAuth scope is exactly `https://www.googleapis.com/auth/spreadsheets.readonly`. No writes to Google Sheets.
- **No live Google API calls in tests.** Every test injects a fake gspread client or monkeypatches; nothing touches the network or real auth.
- **Behavior-preserving refactor.** `read_xlsx(path)` keeps its public signature and produces identical `ClientData` for the existing fixture after the refactor. All current `tests/client/test_sheet_source_xlsx.py` assertions stay green.
- **Config-driven, not hard-coded.** Client → spreadsheet id lives in `config/clients.yaml`, resolved by name. Adding a client is a config edit, not a code change.
- **Sheets default, `--xlsx` override.** `--xlsx` becomes optional; omitting it reads live from the configured sheet.
- **Auth identity:** OAuth as `revops@leadle.in`, consent screen Internal. Two env vars: `GOOGLE_SHEETS_CLIENT_SECRET` (client-secret JSON path, used only by the one-time consent CLI) and `GOOGLE_SHEETS_TOKEN` (cached token JSON path, used by every run).
- **Sheet errors are fatal** (ground truth); Aimfox/Instantly continue to degrade to empty independently.
- **Lazy-import the Google libraries** inside the auth path only (mirrors `read_xlsx`'s local `import openpyxl`), so the no-network test paths run without the libraries imported at module load.
- **Run tests with** `.venv/bin/python -m pytest`.

---

### Task 1: Dependencies, client registry, constants, gitignore

**Files:**
- Modify: `pyproject.toml` (dependencies list, after line 44)
- Create: `config/clients.yaml`
- Create: `dashboard/client/sources/client_registry.py`
- Modify: `dashboard/client/constants.py`
- Modify: `.gitignore`
- Test: `tests/client/test_client_registry.py`

**Interfaces:**
- Produces: `client_registry.spreadsheet_id_for(client: str) -> str` (raises `KeyError` listing known clients on miss); constants `GOOGLE_SHEETS_CLIENT_SECRET_ENV`, `GOOGLE_SHEETS_TOKEN_ENV`, `CLIENTS_CONFIG`.

- [ ] **Step 1: Add the new dependencies to `pyproject.toml`**

Insert this block inside the `dependencies = [ ... ]` array, immediately after the `croniter>=2.0` line (line 44):

```toml
    # ─── Google Sheets connector (OAuth, read-only) ──────────────────
    "gspread>=6.0",
    "google-auth>=2.28",
    "google-auth-oauthlib>=1.2",
```

- [ ] **Step 2: Install the dependencies**

Run: `.venv/bin/python -m pip install -e .`
Expected: installs `gspread`, `google-auth`, `google-auth-oauthlib` (and their transitive deps) with no errors. Verify:

Run: `.venv/bin/python -c "import gspread, google.oauth2.credentials, google_auth_oauthlib.flow; print('google libs OK')"`
Expected: `google libs OK`

- [ ] **Step 3: Create `config/clients.yaml`**

```yaml
# Client -> Google Sheets workbook registry.
# Adding a client is a config edit, not a code change. The connector reads
# each sheet live as revops@leadle.in (the account every workbook is shared with).
clients:
  UPSTA:
    spreadsheet_id: "1GgFeDdXpy1ZlDjH8bTWNL_c7m0ihSSO_-iYNyzadCQg"
```

- [ ] **Step 4: Add constants to `dashboard/client/constants.py`**

Append to the end of the file (the file currently has no imports — add the `Path` import at the top, below the existing comment header):

At the top of the file, after the two comment lines (before `SHEET_DRIVE_ID`), add:

```python
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
```

At the end of the file, append:

```python
# Google Sheets connector (OAuth as revops@leadle.in, scope spreadsheets.readonly)
GOOGLE_SHEETS_CLIENT_SECRET_ENV = "GOOGLE_SHEETS_CLIENT_SECRET"
GOOGLE_SHEETS_TOKEN_ENV = "GOOGLE_SHEETS_TOKEN"
CLIENTS_CONFIG = str(_ROOT / "config" / "clients.yaml")
```

- [ ] **Step 5: Write the failing test `tests/client/test_client_registry.py`**

```python
"""Tests for the client -> spreadsheet_id registry."""
import pytest

from dashboard.client.sources import client_registry


def test_resolves_known_client():
    assert client_registry.spreadsheet_id_for("UPSTA") == \
        "1GgFeDdXpy1ZlDjH8bTWNL_c7m0ihSSO_-iYNyzadCQg"


def test_unknown_client_raises_listing_known():
    with pytest.raises(KeyError) as exc:
        client_registry.spreadsheet_id_for("NOPE")
    assert "UPSTA" in str(exc.value)
```

- [ ] **Step 6: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/client/test_client_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'dashboard.client.sources.client_registry'`

- [ ] **Step 7: Create `dashboard/client/sources/client_registry.py`**

```python
"""Resolve a client name to its Google Sheets spreadsheet id (config/clients.yaml)."""
from __future__ import annotations

from pathlib import Path

import yaml

from dashboard.client import constants


def _load() -> dict:
    text = Path(constants.CLIENTS_CONFIG).read_text(encoding="utf-8")
    data = yaml.safe_load(text) or {}
    return data.get("clients", {})


def spreadsheet_id_for(client: str) -> str:
    """Return the spreadsheet id for `client`, or raise KeyError listing known clients."""
    clients = _load()
    entry = clients.get(client)
    if not entry or "spreadsheet_id" not in entry:
        known = ", ".join(sorted(clients)) or "(none)"
        raise KeyError(f"Unknown client '{client}'. Known clients: {known}")
    return entry["spreadsheet_id"]
```

- [ ] **Step 8: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/client/test_client_registry.py -v`
Expected: PASS (2 passed)

- [ ] **Step 9: Add token/secret filenames to `.gitignore`**

Append under the existing credentials section (the file already ignores `credentials.json` and `service_account*.json`):

```gitignore
google_sheets_token.json
google_sheets_client_secret*.json
```

- [ ] **Step 10: Commit**

```bash
git add pyproject.toml config/clients.yaml dashboard/client/sources/client_registry.py dashboard/client/constants.py .gitignore tests/client/test_client_registry.py
git commit -m "feat(sheets-connector): deps, clients.yaml registry, constants

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Extract `_parse_tabs` core from `read_xlsx` (behavior-preserving)

**Files:**
- Modify: `dashboard/client/sources/sheet_source.py` (lines 221-369 — the `read_xlsx` function and the constants block above it)
- Test: `tests/client/test_sheet_source_xlsx.py` (existing — must stay green), `tests/client/test_parse_tabs.py` (new)

**Interfaces:**
- Produces: `_parse_tabs(tabs: dict[str, list]) -> ClientData` where each value is `rows` (row 0 = header, each row a list/tuple of cell values); module constant `_ALL_SHEET_TABS: tuple[str, ...]`.
- Consumes: existing module helpers `_get`, `_coerce_aimfox_id`, `_parse_ts`, `_is_header_repeat`, and constants `_SPINE_TABS`, `_WH_LINKEDIN`, `_WH_EMAIL`, `_RESP_TAB`, `_LI_REPLY_TYPES`.

- [ ] **Step 1: Write the failing test `tests/client/test_parse_tabs.py`**

This test feeds `_parse_tabs` canned rows directly (header first), exercising the provider-agnostic core with gspread-style **string** cells (including empty-string cells that must be skipped):

```python
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
            ["Channel", "Account", "Response Date", "Status", "Response", "LinkedIn",
             "Name", "Job Title", "Company", "Company Url", "Loc"],
            ["LinkedIn", "UPSTA", "2026-06-01", "Meeting", "yes", "u/bob",
             "Bob", "VP", "Acme", "acme.com", "NY"],
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/client/test_parse_tabs.py -v`
Expected: FAIL with `AttributeError: module ... has no attribute '_parse_tabs'`

- [ ] **Step 3: Add the tab-list constant and an empty-row helper**

In `dashboard/client/sources/sheet_source.py`, immediately after the existing line `_RESP_TAB = "Response Tracker"` (line 161), add:

```python

# Canonical tab set the parser understands (header row first in each).
_ALL_SHEET_TABS = (*_SPINE_TABS, _WH_LINKEDIN, _WH_EMAIL, _RESP_TAB)


def _row_is_empty(row) -> bool:
    """True when every cell is None or blank (covers openpyxl None and gspread '')."""
    return all(v is None or str(v).strip() == "" for v in row)
```

- [ ] **Step 4: Replace the body of `read_xlsx` with `_parse_tabs` + a thin reader**

Replace the entire current `read_xlsx` function (lines 221-369) with the following two functions. The parsing logic is moved verbatim from `read_xlsx`, with three mechanical changes: (a) it reads from `tabs.get(name)` instead of `wb[name]`, (b) `header_row = rows[0]` / iterate `rows[1:]`, (c) the all-None skip becomes `_row_is_empty(row)` and col-map building also excludes blank header cells:

```python
def _parse_tabs(tabs: dict[str, list]) -> ClientData:
    """Build ClientData from a {tab_name: rows} map (row 0 = header).

    Provider-agnostic: rows may come from openpyxl (Python types) or gspread
    (strings). Resolves columns by header NAME, skips repeated-header and empty
    rows, int-coerces numeric Aimfox IDs. Missing tabs are simply absent from
    the map and contribute nothing.
    """
    from dashboard.client.model import OpenEvent, ReplyRecord

    targets: list[TargetCo] = []
    replies: list = []
    opens: list = []
    warm_leads: list[WarmLead] = []

    def _colmap(header_row) -> dict[str, int]:
        return {
            str(v).strip(): idx
            for idx, v in enumerate(header_row)
            if v is not None and str(v).strip() != ""
        }

    # ── Spine tabs ────────────────────────────────────────────────────────────
    for tab_name in _SPINE_TABS:
        rows = tabs.get(tab_name)
        if not rows:
            continue
        header_row = rows[0]
        col_map = _colmap(header_row)
        for row in rows[1:]:
            if _row_is_empty(row):
                continue
            if _is_header_repeat(tuple(row), tuple(header_row)):
                continue
            rv = list(row)
            name = _get(rv, col_map, "Company Name")
            if not name:
                continue
            raw_af = _get(rv, col_map, "Aimfox ID")
            targets.append(TargetCo(
                name=name,
                country=_get(rv, col_map, "Company Country"),
                location=_get(rv, col_map, "Company Location"),
                linkedin_url=_get(rv, col_map, "Company Linked In URL", "Company LinkedIn URL"),
                industry=_get(rv, col_map, "Primary Industry"),
                size=_get(rv, col_map, "Size (Text)", "Size"),
                segment=_get(rv, col_map, "Account Process"),
                domain=_get(rv, col_map, "Company Domain"),
                aimfox_id=_coerce_aimfox_id(raw_af),
                aimfox_urn=_get(rv, col_map, "Aimfox URN"),
                instantly_id=_get(rv, col_map, "Instantly ID"),
            ))

    # ── Webhook - LinkedIn ────────────────────────────────────────────────────
    rows = tabs.get(_WH_LINKEDIN)
    if rows:
        header_row = rows[0]
        col_map = _colmap(header_row)
        for row in rows[1:]:
            if _row_is_empty(row):
                continue
            if _is_header_repeat(tuple(row), tuple(header_row)):
                continue
            rv = list(row)
            evt = _get(rv, col_map, "Event Type").lower()
            if evt not in _LI_REPLY_TYPES:
                continue
            sentiment = _get(rv, col_map, "Reply Sentiment") or "untagged"
            campaign = _get(rv, col_map, "Campaign Name")
            name = _get(rv, col_map, "Prospect Name")
            raw_ts = _get(rv, col_map, "Timestamp") if "Timestamp" in col_map else None
            ts = _parse_ts(raw_ts)
            replies.append(ReplyRecord(
                channel="linkedin",
                campaign=campaign,
                sentiment=sentiment,
                name=name,
                ts=ts,
            ))

    # ── Webhook - Email ───────────────────────────────────────────────────────
    rows = tabs.get(_WH_EMAIL)
    if rows:
        header_row = rows[0]
        col_map = _colmap(header_row)
        for row in rows[1:]:
            if _row_is_empty(row):
                continue
            if _is_header_repeat(tuple(row), tuple(header_row)):
                continue
            rv = list(row)
            evt = _get(rv, col_map, "Event Type").lower()
            if evt == "email_opened":
                raw_ts = _get(rv, col_map, "Event Timestamp") if "Event Timestamp" in col_map else None
                ts = _parse_ts(raw_ts)
                if ts is not None:
                    opens.append(OpenEvent(channel="email", ts=ts))

    # ── Response Tracker ─────────────────────────────────────────────────────
    rows = tabs.get(_RESP_TAB)
    if rows:
        header_row = rows[0]
        col_map = _colmap(header_row)
        for row in rows[1:]:
            if _row_is_empty(row):
                continue
            if _is_header_repeat(tuple(row), tuple(header_row)):
                continue
            rv = list(row)
            channel = _get(rv, col_map, "Channel")
            if not channel:
                continue
            warm_leads.append(WarmLead(
                channel=channel,
                account=_get(rv, col_map, "Account"),
                response_date=_get(rv, col_map, "Response Date"),
                status=_get(rv, col_map, "Status"),
                response_text=_get(rv, col_map, "Response"),
                linkedin_url=_get(rv, col_map, "LinkedIn"),
                name=_get(rv, col_map, "Name"),
                title=_get(rv, col_map, "Job Title"),
                company=_get(rv, col_map, "Company"),
                company_url=_get(rv, col_map, "Company Url"),
                location=_get(rv, col_map, "Loc"),
            ))

    return ClientData(targets=targets, replies=replies, opens=opens, warm_leads=warm_leads)


def read_xlsx(path: str) -> ClientData:
    """Parse the client prospect XLSX workbook and return a ClientData.

    Reads the known tabs into {tab: rows} with openpyxl(read_only, data_only),
    then delegates to the provider-agnostic _parse_tabs core.
    """
    import openpyxl  # local import — not always in the text-parse path

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    tabs: dict[str, list] = {}
    for tab_name in _ALL_SHEET_TABS:
        if tab_name in wb.sheetnames:
            tabs[tab_name] = list(wb[tab_name].iter_rows(values_only=True))
    wb.close()
    return _parse_tabs(tabs)
```

- [ ] **Step 5: Run the new test to verify it passes**

Run: `.venv/bin/python -m pytest tests/client/test_parse_tabs.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Run the existing xlsx regression suite — behavior must be unchanged**

Run: `.venv/bin/python -m pytest tests/client/test_sheet_source_xlsx.py -v`
Expected: PASS (all existing assertions green — same target/reply/open/warm counts as before the refactor)

- [ ] **Step 7: Commit**

```bash
git add dashboard/client/sources/sheet_source.py tests/client/test_parse_tabs.py
git commit -m "refactor(sheets-connector): extract provider-agnostic _parse_tabs core

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: `connectors/google_sheets/fetch.py` — raw Sheets fetch

**Files:**
- Create: `connectors/google_sheets/__init__.py`
- Create: `connectors/google_sheets/fetch.py`
- Test: `tests/client/test_sheets_fetch.py`

**Interfaces:**
- Produces: `fetch(spreadsheet_id: str, tab_names, *, client=None) -> dict[str, list]` (returns `{tab_name: rows}`, omitting absent tabs; `rows` = `worksheet.get_all_values()`); `_authorized_client()` (raises `RuntimeError` on missing/invalid token).
- Consumes: `constants.GOOGLE_SHEETS_TOKEN_ENV`.

- [ ] **Step 1: Write the failing test `tests/client/test_sheets_fetch.py`**

```python
"""Tests for connectors.google_sheets.fetch — injected fake client, no network/auth."""
import pytest

from connectors.google_sheets import fetch


class _FakeWorksheet:
    def __init__(self, title, rows):
        self.title = title
        self._rows = rows

    def get_all_values(self):
        return self._rows


class _FakeSpreadsheet:
    def __init__(self, sheets):
        self._sheets = sheets  # dict[title -> rows]

    def worksheets(self):
        return [_FakeWorksheet(t, r) for t, r in self._sheets.items()]

    def worksheet(self, title):
        return _FakeWorksheet(title, self._sheets[title])


class _FakeClient:
    def __init__(self, sheets):
        self._sheets = sheets

    def open_by_key(self, key):
        assert key == "sheet-123"
        return _FakeSpreadsheet(self._sheets)


def test_fetch_returns_requested_tabs_and_omits_absent():
    fake = _FakeClient({
        "Prospect Data-US": [["Company Name"], ["Acme"]],
        "Webhook - Email": [["Event Type"], ["email_opened"]],
    })
    out = fetch.fetch("sheet-123",
                      ["Prospect Data-US", "Webhook - Email", "Response Tracker"],
                      client=fake)
    assert set(out) == {"Prospect Data-US", "Webhook - Email"}  # absent tab omitted
    assert out["Prospect Data-US"] == [["Company Name"], ["Acme"]]


def test_authorized_client_errors_without_token(monkeypatch):
    monkeypatch.delenv("GOOGLE_SHEETS_TOKEN", raising=False)
    with pytest.raises(RuntimeError) as exc:
        fetch._authorized_client()
    assert "GOOGLE_SHEETS_TOKEN" in str(exc.value)
    assert "authorize" in str(exc.value)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/client/test_sheets_fetch.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'connectors.google_sheets'`

- [ ] **Step 3: Create `connectors/google_sheets/__init__.py`**

```python
```
(empty file)

- [ ] **Step 4: Create `connectors/google_sheets/fetch.py`**

```python
"""Raw Google Sheets fetch: spreadsheet_id + tab names -> {tab: rows}.

Authorizes as the operator (OAuth, scope spreadsheets.readonly). The gspread
client is injectable so tests never hit the network or auth. The Google
libraries are imported lazily inside _authorized_client so the injected-client
path needs neither installed.
"""
from __future__ import annotations

import os

from dashboard.client import constants

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


def _authorized_client():
    """Build an authorized gspread client from the cached OAuth token.

    The token JSON (written once by connectors.google_sheets.authorize) carries
    the refresh token and client id/secret, so refresh needs no extra files.
    Raises RuntimeError with an actionable message when the token is
    missing/invalid.
    """
    token_path = os.environ.get(constants.GOOGLE_SHEETS_TOKEN_ENV)
    if not token_path or not os.path.exists(token_path):
        raise RuntimeError(
            f"Google Sheets token missing. Set {constants.GOOGLE_SHEETS_TOKEN_ENV} to the "
            f"OAuth token path and run once: python -m connectors.google_sheets.authorize"
        )

    import gspread
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    creds = Credentials.from_authorized_user_file(token_path, _SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(token_path, "w", encoding="utf-8") as fh:
                fh.write(creds.to_json())
        else:
            raise RuntimeError(
                "Google Sheets token invalid and cannot refresh. Re-run once: "
                "python -m connectors.google_sheets.authorize"
            )
    return gspread.authorize(creds)


def fetch(spreadsheet_id: str, tab_names, *, client=None) -> dict[str, list]:
    """Return {tab_name: rows} for each requested tab that exists in the sheet.

    rows = worksheet.get_all_values() (list of row-lists, header first). Tabs
    absent from the spreadsheet are omitted. Inject `client` in tests to skip
    auth and network.
    """
    gc = client or _authorized_client()
    sh = gc.open_by_key(spreadsheet_id)
    existing = {ws.title for ws in sh.worksheets()}
    out: dict[str, list] = {}
    for name in tab_names:
        if name in existing:
            out[name] = sh.worksheet(name).get_all_values()
    return out
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/client/test_sheets_fetch.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add connectors/google_sheets/__init__.py connectors/google_sheets/fetch.py tests/client/test_sheets_fetch.py
git commit -m "feat(sheets-connector): google_sheets.fetch with OAuth + injectable client

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: `read_sheets` provider + source-parity guarantee

**Files:**
- Modify: `dashboard/client/sources/sheet_source.py` (add `read_sheets` after `read_xlsx`)
- Test: `tests/client/test_read_sheets_parity.py`

**Interfaces:**
- Produces: `read_sheets(spreadsheet_id: str, *, client=None) -> ClientData`.
- Consumes: `_parse_tabs`, `_ALL_SHEET_TABS` (Task 2); `connectors.google_sheets.fetch.fetch` (Task 3).

- [ ] **Step 1: Write the failing parity test `tests/client/test_read_sheets_parity.py`**

The fake client serves the **same rows openpyxl reads from the fixture**, so `read_sheets` (via fetch → `_parse_tabs`) must produce a `ClientData` identical to `read_xlsx` (openpyxl → `_parse_tabs`):

```python
"""read_sheets must produce the same ClientData as read_xlsx for the same rows."""
from pathlib import Path

import openpyxl

from dashboard.client.sources import sheet_source

FIX = Path(__file__).parent / "fixtures" / "upsta_mini.xlsx"


class _FakeWorksheet:
    def __init__(self, title, rows):
        self.title, self._rows = title, rows

    def get_all_values(self):
        return self._rows


class _FakeSpreadsheet:
    def __init__(self, sheets):
        self._sheets = sheets

    def worksheets(self):
        return [_FakeWorksheet(t, r) for t, r in self._sheets.items()]

    def worksheet(self, title):
        return _FakeWorksheet(title, self._sheets[title])


class _FakeClient:
    def __init__(self, sheets):
        self._sheets = sheets

    def open_by_key(self, key):
        return _FakeSpreadsheet(self._sheets)


def _fixture_tabs():
    wb = openpyxl.load_workbook(str(FIX), read_only=True, data_only=True)
    tabs = {}
    for name in sheet_source._ALL_SHEET_TABS:
        if name in wb.sheetnames:
            tabs[name] = [list(r) for r in wb[name].iter_rows(values_only=True)]
    wb.close()
    return tabs


def test_read_sheets_matches_read_xlsx():
    fake = _FakeClient(_fixture_tabs())
    from_sheets = sheet_source.read_sheets("any-id", client=fake)
    from_xlsx = sheet_source.read_xlsx(str(FIX))

    assert len(from_sheets.targets) == len(from_xlsx.targets)
    assert len(from_sheets.replies) == len(from_xlsx.replies)
    assert len(from_sheets.opens) == len(from_xlsx.opens)
    assert len(from_sheets.warm_leads) == len(from_xlsx.warm_leads)
    assert {t.aimfox_id for t in from_sheets.targets} == {t.aimfox_id for t in from_xlsx.targets}
    assert {r.sentiment for r in from_sheets.replies} == {r.sentiment for r in from_xlsx.replies}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/client/test_read_sheets_parity.py -v`
Expected: FAIL with `AttributeError: module ... has no attribute 'read_sheets'`

- [ ] **Step 3: Add `read_sheets` to `dashboard/client/sources/sheet_source.py`**

Add immediately after the `read_xlsx` function:

```python
def read_sheets(spreadsheet_id: str, *, client=None) -> ClientData:
    """Read the workbook live from Google Sheets and return a ClientData.

    Fetches the known tabs via the google_sheets connector, then delegates to
    the same _parse_tabs core read_xlsx uses. Inject `client` in tests.
    """
    from connectors.google_sheets import fetch as sheets_fetch

    tabs = sheets_fetch.fetch(spreadsheet_id, list(_ALL_SHEET_TABS), client=client)
    return _parse_tabs(tabs)
```

- [ ] **Step 4: Run the parity test to verify it passes**

Run: `.venv/bin/python -m pytest tests/client/test_read_sheets_parity.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add dashboard/client/sources/sheet_source.py tests/client/test_read_sheets_parity.py
git commit -m "feat(sheets-connector): read_sheets provider + xlsx parity test

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: `authorize.py` — one-time OAuth consent CLI

**Files:**
- Create: `connectors/google_sheets/authorize.py`
- Test: `tests/client/test_sheets_authorize.py`

**Interfaces:**
- Produces: `main() -> int` (runs the consent flow; raises `RuntimeError` before any browser when env vars are unset).
- Consumes: `constants.GOOGLE_SHEETS_CLIENT_SECRET_ENV`, `constants.GOOGLE_SHEETS_TOKEN_ENV`.

- [ ] **Step 1: Write the failing test `tests/client/test_sheets_authorize.py`**

```python
"""authorize.main must fail clearly (before any browser) when env is unset."""
import pytest

from connectors.google_sheets import authorize


def test_main_requires_client_secret_env(monkeypatch):
    monkeypatch.delenv("GOOGLE_SHEETS_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("GOOGLE_SHEETS_TOKEN", "/tmp/token.json")
    with pytest.raises(RuntimeError) as exc:
        authorize.main()
    assert "GOOGLE_SHEETS_CLIENT_SECRET" in str(exc.value)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/client/test_sheets_authorize.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'connectors.google_sheets.authorize'`

- [ ] **Step 3: Create `connectors/google_sheets/authorize.py`**

```python
"""One-time OAuth consent for the Google Sheets connector.

Run once: `python -m connectors.google_sheets.authorize`. Opens the browser to
sign in as revops@leadle.in, grants spreadsheets.readonly, and writes the token
JSON to GOOGLE_SHEETS_TOKEN. Not on the render hot path.
"""
from __future__ import annotations

import os

from dashboard.client import constants

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


def main() -> int:
    secret_path = os.environ.get(constants.GOOGLE_SHEETS_CLIENT_SECRET_ENV)
    token_path = os.environ.get(constants.GOOGLE_SHEETS_TOKEN_ENV)
    if not secret_path or not os.path.exists(secret_path):
        raise RuntimeError(
            f"Set {constants.GOOGLE_SHEETS_CLIENT_SECRET_ENV} to the OAuth client-secret "
            f"JSON (Desktop app) downloaded from GCP."
        )
    if not token_path:
        raise RuntimeError(
            f"Set {constants.GOOGLE_SHEETS_TOKEN_ENV} to the path where the token "
            f"should be written."
        )

    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(secret_path, _SCOPES)
    creds = flow.run_local_server(port=0)
    with open(token_path, "w", encoding="utf-8") as fh:
        fh.write(creds.to_json())
    print(f"Token written to {token_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/client/test_sheets_authorize.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add connectors/google_sheets/authorize.py tests/client/test_sheets_authorize.py
git commit -m "feat(sheets-connector): one-time OAuth consent CLI

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: Wire loader + render CLI to live Sheets by default

**Files:**
- Modify: `dashboard/client/sources/loader.py` (signature + sheet-selection block, lines 15-33)
- Modify: `dashboard/client/render.py` (`--xlsx` arg line 68; the `loader.load(...)` call lines 103-109)
- Modify: `tests/client/test_loader.py` (update every `loader.load(...)` call to the new signature)
- Test: `tests/client/test_loader.py` (existing + 1 new selection test)

**Interfaces:**
- Consumes: `client_registry.spreadsheet_id_for` (Task 1), `sheet_source.read_sheets` (Task 4), `sheet_source.read_xlsx` (existing).
- Produces: `load(window, *, client="UPSTA", xlsx_path=None, aimfox_key, instantly_key, name_contains, aimfox_client=None, instantly_client=None, sheets_client=None) -> ClientData`.

- [ ] **Step 1: Change the `load` signature and sheet-selection block in `loader.py`**

Replace the current signature and the `# ── Sheet (ground truth) ──` block (lines 15-33) with:

```python
def load(
    window: tuple[str, str],
    *,
    client: str = "UPSTA",
    xlsx_path: str | None = None,
    aimfox_key: str,
    instantly_key: str,
    name_contains: str,
    aimfox_client: httpx.Client | None = None,
    instantly_client: httpx.Client | None = None,
    sheets_client=None,
) -> ClientData:
    """Merge sheet + Aimfox + Instantly into a single ClientData.

    Sheet source: live Google Sheets by default (resolved from `client` via
    config/clients.yaml). Pass `xlsx_path` to read an offline workbook instead.

    Degrade contract:
    - Aimfox exception → linkedin_campaigns stays []
    - Instantly unavailable/exception → email_campaigns, senders, content_steps stay []
    - Sheet errors propagate (the sheet is the ground truth; failures there are fatal).
    """
    # ── Sheet (ground truth) ──────────────────────────────────────────────────
    if xlsx_path is not None:
        data = sheet_source.read_xlsx(xlsx_path)
    else:
        from dashboard.client.sources import client_registry
        spreadsheet_id = client_registry.spreadsheet_id_for(client)
        data = sheet_source.read_sheets(spreadsheet_id, client=sheets_client)
```

(The Aimfox + Instantly blocks below are unchanged.)

- [ ] **Step 2: Update `render.py` — make `--xlsx` optional and pass new kwargs**

In `dashboard/client/render.py`, change line 68 from:

```python
    ap.add_argument("--xlsx", required=True, help="Path to Drive-dumped workbook (.xlsx)")
```

to:

```python
    ap.add_argument("--xlsx", default=None,
                    help="Optional offline workbook (.xlsx). Omit to read live from the "
                         "configured Google Sheet for --client.")
```

Then change the `loader.load(...)` call (lines 103-109) from positional `args.xlsx, window` to:

```python
        data = loader.load(
            window,
            client=client_name,
            xlsx_path=args.xlsx,
            aimfox_key=os.environ.get(constants.AIMFOX_ENV, ""),
            instantly_key=os.environ.get(constants.INSTANTLY_ENV, ""),
            name_contains=constants.CAMPAIGN_FILTER,
        )
```

- [ ] **Step 3: Update existing `loader.load(...)` calls in `tests/client/test_loader.py`**

Every existing call passes the xlsx path positionally, e.g. `loader.load(MINI_XLSX, WINDOW, aimfox_key=..., ...)`. Change each to pass `window` positionally and the xlsx path as a keyword:

```python
loader.load(WINDOW, xlsx_path=MINI_XLSX, aimfox_key=AIMFOX_KEY,
            instantly_key=INSTANTLY_KEY, name_contains=NAME_CONTAINS,
            aimfox_client=..., instantly_client=...)
```

Run a search to find every call site first:
Run: `grep -n "loader.load(" tests/client/test_loader.py`
Update each occurrence to the keyword form above (keep whatever `aimfox_client`/`instantly_client` mock each call already passes).

- [ ] **Step 4: Add a selection test to `tests/client/test_loader.py`**

Append:

```python
def test_load_default_reads_sheets(monkeypatch):
    """xlsx_path=None resolves the registry and calls read_sheets (no xlsx)."""
    calls = {}

    def fake_read_sheets(spreadsheet_id, *, client=None):
        calls["id"] = spreadsheet_id
        return ClientData(targets=[], replies=[], opens=[], warm_leads=[])

    monkeypatch.setattr(
        "dashboard.client.sources.client_registry.spreadsheet_id_for",
        lambda c: "resolved-id-for-" + c,
    )
    monkeypatch.setattr(
        "dashboard.client.sources.sheet_source.read_sheets", fake_read_sheets
    )
    # Aimfox/Instantly will degrade to [] with no clients passed.
    loader.load(WINDOW, client="UPSTA", aimfox_key="", instantly_key="",
                name_contains=NAME_CONTAINS)
    assert calls["id"] == "resolved-id-for-UPSTA"
```

- [ ] **Step 5: Run the loader suite to verify it passes**

Run: `.venv/bin/python -m pytest tests/client/test_loader.py -v`
Expected: PASS (existing tests + `test_load_default_reads_sheets`)

- [ ] **Step 6: Verify `--xlsx` is now optional at the argparse level**

Run the CLI with **no** `--xlsx` and an empty token so it cannot reach the network — argparse must accept the call and the run must fail later on the missing token, NOT on a required `--xlsx`:

Run: `GOOGLE_SHEETS_TOKEN= .venv/bin/python -m dashboard.client.render --client UPSTA --period monthly --skip-agents 2>&1 | tail -3`
Expected: an error mentioning `GOOGLE_SHEETS_TOKEN` (the missing-token RuntimeError from `_authorized_client`). It must NOT say `the following arguments are required: --xlsx` — that would mean the parser still requires it. This proves argparse accepted the call without `--xlsx` and reached the live-Sheets path (which then fails offline, as expected with no token).

Also run the existing render CLI test to confirm the `--xlsx` path still works:
Run: `.venv/bin/python -m pytest tests/client/test_render_cli.py -v`
Expected: PASS

- [ ] **Step 7: Run the full client suite**

Run: `.venv/bin/python -m pytest tests/client -q`
Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add dashboard/client/sources/loader.py dashboard/client/render.py tests/client/test_loader.py
git commit -m "feat(sheets-connector): loader+render default to live Sheets, --xlsx optional

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: Runbook + slash command + spec prerequisites doc

**Files:**
- Modify: `docs/data-shape/prospect-list-sheet.md` (the `## Render runbook` section)
- Modify: `.claude/commands/render-client-report.md`

**Interfaces:** none (docs only).

- [ ] **Step 1: Update the runbook in `docs/data-shape/prospect-list-sheet.md`**

Replace the body of the existing `## Render runbook` section with content covering both paths. The live default must be documented first:

```markdown
## Render runbook

The client report reads the workbook **live from Google Sheets by default** — no
download. The connector authorizes as `revops@leadle.in` (OAuth, scope
`spreadsheets.readonly`) and resolves the sheet id from `config/clients.yaml`.

**One-time setup (per machine/environment):**
1. In the leadle.in GCP project, enable the Google Sheets API.
2. OAuth consent screen → user type **Internal**; add scope `.../auth/spreadsheets.readonly`.
3. Create an OAuth client of type **Desktop app**; download the client-secret JSON.
4. `export GOOGLE_SHEETS_CLIENT_SECRET=/path/to/client_secret.json`
   `export GOOGLE_SHEETS_TOKEN=/path/to/google_sheets_token.json`
5. `python -m connectors.google_sheets.authorize` — sign in as `revops@leadle.in`.
   Writes the token to `$GOOGLE_SHEETS_TOKEN`. Both files are gitignored.

**Render (live, default):**
```bash
python -m dashboard.client.render --client UPSTA --all-periods --audience both --period-end <YYYY-MM-DD>
```

**Render (offline override):** pass `--xlsx <path>` to read a downloaded workbook
instead of the live sheet (debugging / reproducing a past report).

**Required env for campaign numbers:** `AIMFOX_API_KEY`, `INSTANTLY_API_KEY`
(absence degrades those blocks to empty, not a crash).

**Outputs:** `reports/client/<client>-<period_end>-<period>-<audience>.html` (4 files:
monthly/weekly × internal/client).

**Adding a client:** add an entry to `config/clients.yaml` (`client -> spreadsheet_id`)
and ensure the workbook is shared with `revops@leadle.in`. No code change.

The slash command `/render-client-report` automates the live render.
```

- [ ] **Step 2: Update `.claude/commands/render-client-report.md`**

Rewrite the protocol so the default path is the live Sheets read (no Drive MCP download), keeping `--xlsx` as a documented fallback. Set frontmatter `allowed-tools: Bash` (the Drive MCP tools are no longer needed for the default path). Body:

```markdown
---
description: Render the UPSTA client campaign report (4 outputs) live from Google Sheets + APIs
allowed-tools: Bash
---

Render the CLIENT campaign dashboard (`dashboard.client.render`) for `$1` (default UPSTA).

1. Resolve today's date: `date "+%Y-%m-%d"`.
2. Confirm the Google Sheets token exists: `test -f "$GOOGLE_SHEETS_TOKEN" && echo ok`.
   If missing, tell the user to run `python -m connectors.google_sheets.authorize` once
   (see `docs/data-shape/prospect-list-sheet.md`).
3. Confirm `AIMFOX_API_KEY` and `INSTANTLY_API_KEY` are in env (absence degrades campaign
   blocks to empty, not a crash).
4. Run (reads live from the sheet configured in `config/clients.yaml` for the client):
   ```bash
   source .venv/bin/activate && python -m dashboard.client.render \
     --client ${1:-UPSTA} --all-periods --audience both --period-end <today>
   ```
   Offline fallback: add `--xlsx /tmp/upsta_workbook.xlsx` to read a downloaded workbook.
5. Report the 4 output paths printed by the CLI. If any source degraded, note it.
```

- [ ] **Step 3: Verify the runbook documents the live command**

Run: `grep -n "render --client UPSTA\|spreadsheets.readonly\|clients.yaml" docs/data-shape/prospect-list-sheet.md`
Expected: matches present (live command, scope, registry all documented).

- [ ] **Step 4: Commit**

```bash
git add docs/data-shape/prospect-list-sheet.md .claude/commands/render-client-report.md
git commit -m "docs(sheets-connector): runbook + slash command for live Sheets render

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Final verification (after all tasks)

- [ ] Run the full client suite: `.venv/bin/python -m pytest tests/client -q` — all green.
- [ ] Run the whole suite: `.venv/bin/python -m pytest -q` — no regressions.
- [ ] Confirm no live Google call exists in any test: `grep -rn "open_by_key\|InstalledAppFlow\|from_authorized_user_file\|run_local_server" tests/` returns nothing.
- [ ] Lint: `.venv/bin/ruff check dashboard/client connectors/google_sheets config tests/client` — clean.
