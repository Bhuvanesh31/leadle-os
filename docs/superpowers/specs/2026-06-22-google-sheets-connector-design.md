# Google Sheets Connector — Design

**Date:** 2026-06-22
**Status:** Approved (brainstorming), pending implementation plan
**Builds on:** `2026-06-21-client-dashboard-productization-design.md` (extends the `dashboard/client/` source layer)

## Problem

The client-dashboard render pipeline reads the UPSTA workbook from a **local `.xlsx` file**
(`sheet_source.read_xlsx(path)`). Getting that file currently means a manual download from Google
Drive (or a Drive MCP call that returns ~644 KB of base64 into the session). Both are stopgaps: the
end goal is a fully automated, Slack-delivered report that no human has to feed a file to. The first
step toward that is reading the sheet **directly via the Google Sheets API**, with credentials that
work unattended.

This effort adds that direct-read connector. It does **not** build the Slack delivery layer or change
metric windowing (the deferred I1) — those are separate follow-ons.

## Setup reality (drives the auth decision)

Every client workbook is owned **inside the leadle.in Google Workspace**, but the sheets are
**scattered across folders owned by different people** and reach the operator only because they are
**shared with `revops@leadle.in`**. There is no single parent folder to share, and corralling sheets
would mean moving files the operator does not own. The existing share-to-`revops@leadle.in` access is
the asset to build on.

## Decisions (locked in brainstorming)

1. **Auth: OAuth user credentials, acting as `revops@leadle.in`.** The connector authorizes *as the
   operator's own account*, so it instantly sees every sheet already shared to `revops@leadle.in`,
   across every folder and owner, with **zero per-sheet or per-folder sharing**. A service account was
   rejected: it starts with access to nothing and would need each scattered sheet granted to a robot
   email — the exact friction we are removing. (A bare API key was also rejected: it only works on
   fully public sheets, and client data cannot be public.)
2. **Consent screen = Internal.** The OAuth app is published as **Internal** to the leadle.in
   Workspace. This removes the 7-day refresh-token expiry that applies to "Testing" apps and skips
   Google verification, making the cached refresh token durable enough for unattended cron / Slack
   automation.
3. **Runtime surface: Sheets default, `--xlsx` optional override.** The pipeline reads live from
   Sheets by default (no path needed). `--xlsx <path>` still works for offline runs, debugging, and
   reproducing a specific report. The file reader stays regardless (tests need a deterministic input).
4. **Architecture: parse core + two row-providers** (Approach A). Decouple "where rows come from"
   from "how rows become `ClientData`". One tested parser, two inputs (xlsx file, live Sheets).
5. **Library: `gspread` + `google-auth` + `google-auth-oauthlib`.** Simplest read path
   (`get_all_values()` returns rows directly); `google-auth-oauthlib` runs the one-time consent flow
   and refreshes the token. Hand-rolling Sheets OAuth over `httpx` is not worth it. These are the
   first non-`httpx` connector dependencies — justified by the auth complexity.
6. **Read-only invariant honored.** OAuth scope is `spreadsheets.readonly`. Because sheets are fetched
   by **ID** (from the registry), no Drive scope is needed. No writes, consistent with the
   project-wide read-only rule.
7. **Config-driven client registry.** Replace the single hardcoded `SHEET_DRIVE_ID` with
   `config/clients.yaml` mapping `client -> spreadsheet_id` (seeded with UPSTA). Adding a client is a
   config edit, not a code change — consistent with the config-driven principle and the
   "many clients, many sheets" reality. Resolution by client name; no Drive search.

## Credentials & token model

OAuth needs two files on disk, both referenced by env vars and both gitignored:

- **Client secret** (`GOOGLE_SHEETS_CLIENT_SECRET` → path to the OAuth *Desktop app* client-secret
  JSON downloaded from GCP). Identifies the app.
- **Authorized-user token** (`GOOGLE_SHEETS_TOKEN` → path to the cached token JSON holding the refresh
  token). Written by the one-time consent flow; refreshed automatically thereafter.

One-time bootstrap: a human runs `python -m connectors.google_sheets.authorize` once, which launches
the browser consent (sign in as `revops@leadle.in`, grant `spreadsheets.readonly`) and writes the
token file. Every subsequent run — interactive or scheduled — loads the token and refreshes silently;
no human in the loop. For local runs the env vars live in `.env`; for the future scheduled/Slack run
they live in that environment's secret store.

## Architecture

```
render CLI (default: no --xlsx)
   |
loader.load(client, xlsx_path=None, ...)
   |
   +-- xlsx_path given?  -- yes --> sheet_source.read_xlsx(path)   [openpyxl -> rows]
   |                                          \
   +-- no (default) --> resolve client -> spreadsheet_id (config/clients.yaml)
   |                       |                  \
   |              sheet_source.read_sheets(spreadsheet_id)          \
   |                       |                                         v
   |          connectors/google_sheets/fetch.py             _parse_tabs(tabs) -> ClientData
   |          (gspread + OAuth-as-revops, readonly)         (spine / webhook LI / webhook
   |                |  open_by_key, get_all_values per tab   email / response tracker;
   |                v                                        header-aware; the existing
   |           {tab_name: rows}  ------------------------>   tested parsing logic)
   |
   (then Aimfox + Instantly REST as today)
```

## Components

### `dashboard/client/sources/sheet_source.py` (refactor — behavior-preserving)
- **`_parse_tabs(tabs: dict[str, list[list]]) -> ClientData`** — the core parser. Takes a map of
  `tab_name -> rows` (each row a list of cell values, raw/stringy as the sheet returns them) and
  produces `ClientData` (targets, replies, opens, warm_leads). All current spine / `Webhook -
  LinkedIn` / `Webhook - Email` / `Response Tracker` logic moves here unchanged, including
  header-awareness, the `_parse_ts` handling, and the "skip tab if absent" behavior.
- **`read_xlsx(path) -> ClientData`** (unchanged public signature) — opens the file with openpyxl
  (`read_only=True, data_only=True`), reads the known tabs into `{tab: rows}`, calls `_parse_tabs`.
- **`read_sheets(spreadsheet_id, *, client=None) -> ClientData`** — obtains `{tab: rows}` from the
  connector (passing the injectable `client` through for tests), calls `_parse_tabs`.

### `connectors/google_sheets/fetch.py` (new — generic raw fetch)
- **`fetch(spreadsheet_id, tab_names, *, client=None) -> dict[str, list[list]]`** — when no `client`
  is injected, builds an authorized gspread client via `_authorized_client()` (loads the token from
  `GOOGLE_SHEETS_TOKEN`, refreshing against the client secret as needed, scope
  `spreadsheets.readonly`); opens the spreadsheet by key; returns `{tab_name: get_all_values()}` for
  each requested tab that exists. Tabs absent from the spreadsheet are omitted (parser treats missing
  tabs the same as the xlsx path). Tests inject a fake client and never touch the network or auth.
- **`_authorized_client()`** — internal: loads `Credentials` from the token file, refreshes if
  expired, returns a `gspread` client. Raises a clear error if the token/client-secret env vars are
  unset or the files are missing/unparseable.

### `connectors/google_sheets/authorize.py` (new — one-time consent CLI)
- **`main()`** — runs `InstalledAppFlow` (from `google-auth-oauthlib`) against the client secret at
  `GOOGLE_SHEETS_CLIENT_SECRET`, scope `spreadsheets.readonly`, opens the browser for the operator to
  sign in as `revops@leadle.in`, and writes the resulting token JSON to `GOOGLE_SHEETS_TOKEN`. Run
  once by a human; not on the render hot path.

### `config/clients.yaml` (new — client → sheet registry)
- Maps client name to spreadsheet id, seeded with the existing UPSTA id:
  ```yaml
  clients:
    UPSTA:
      spreadsheet_id: "1GgFeDdXpy1ZlDjH8bTWNL_c7m0ihSSO_-iYNyzadCQg"
  ```
- A tiny loader resolves `client -> spreadsheet_id`; unknown client → clear error listing known
  clients.

### `dashboard/client/constants.py`
- Add `GOOGLE_SHEETS_CLIENT_SECRET_ENV = "GOOGLE_SHEETS_CLIENT_SECRET"`,
  `GOOGLE_SHEETS_TOKEN_ENV = "GOOGLE_SHEETS_TOKEN"`, and `CLIENTS_CONFIG` (path to
  `config/clients.yaml`). `SHEET_DRIVE_ID` stays for now as the UPSTA seed value referenced by the
  registry, but the pipeline resolves through the registry, not the constant.

### `dashboard/client/sources/loader.py`
- `load(...)` gains `client` and optional `xlsx_path: str | None`. When `xlsx_path` is provided →
  `read_xlsx(xlsx_path)`. When `None` (default) → resolve `client` to a `spreadsheet_id` via
  `config/clients.yaml`, then `read_sheets(spreadsheet_id)`. Sheet read errors propagate (ground
  truth); Aimfox/Instantly keep degrading independently.

### `dashboard/client/render.py`
- `--xlsx` becomes optional (default `None` → live Sheets). The existing client identifier drives
  registry resolution. Help text notes that omitting `--xlsx` reads live from the configured sheet.

## Data flow

- **Default (live):** `render --client UPSTA` → `loader.load(client="UPSTA", xlsx_path=None)` →
  resolve `UPSTA` → spreadsheet_id via `clients.yaml` → `read_sheets(spreadsheet_id)` →
  `connectors.google_sheets.fetch` authorizes as revops (readonly), `open_by_key`, `get_all_values`
  per known tab → `{tab: rows}` → `_parse_tabs` → `ClientData` → Aimfox + Instantly → compute → render.
- **Override (file):** `render --xlsx <path>` → `read_xlsx(path)` → same `_parse_tabs` → identical
  downstream.

## Error handling & degradation

- **Missing/invalid creds** (token or client-secret env unset, file missing/unparseable, refresh
  fails) → hard fail with an actionable message naming `GOOGLE_SHEETS_TOKEN` /
  `GOOGLE_SHEETS_CLIENT_SECRET` and pointing to `python -m connectors.google_sheets.authorize`.
- **Unknown client** (not in `clients.yaml`) → hard fail listing the known clients.
- **Sheets API error / spreadsheet not found / no access** → hard fail. The sheet is the spine /
  ground truth; consistent with the productization spec (only Aimfox/Instantly degrade gracefully).
- **Missing expected tab** → omitted from `{tab: rows}`; `_parse_tabs` handles absence exactly as
  `read_xlsx` does today (no crash, that source's records stay empty).

## Testing (no live Google calls)

- **Parser regression:** existing xlsx-fixture tests continue to exercise `_parse_tabs` via
  `read_xlsx`; add one assertion that `read_xlsx(upsta_mini.xlsx)` output is unchanged after the
  refactor.
- **Connector fetch:** inject a fake gspread-like client (returns canned `get_all_values` per tab);
  assert `fetch(...)` returns the expected `{tab: rows}` and omits absent tabs. No network, no auth.
- **Source parity (key guarantee):** feed `read_sheets` (via injected client) the *same rows* the
  xlsx fixture contains; assert the resulting `ClientData` equals `read_xlsx(upsta_mini.xlsx)`. This
  proves the live and file paths produce identical structured data.
- **Client registry:** `clients.yaml` resolution returns the right id for a known client and raises a
  clear error for an unknown one.
- **Loader selection:** `load(xlsx_path=set)` uses the file path; `load(xlsx_path=None, client=...)`
  resolves the registry and calls `read_sheets` (assert via injection/monkeypatch). No live calls.
- **Missing-creds error:** `_authorized_client` with unset/bad token or client-secret env raises the
  clear, actionable error.

## Dependencies

- Add `gspread`, `google-auth`, and `google-auth-oauthlib` to the project requirements. First
  non-`httpx` external dependencies in the connector layer; justified by Sheets OAuth.

## Prerequisites (one-time, user-provisioned)

1. In the leadle.in GCP project, enable the Google Sheets API.
2. Configure the OAuth consent screen with **user type = Internal**; add scope
   `.../auth/spreadsheets.readonly`.
3. Create an OAuth client of type **Desktop app**; download its client-secret JSON.
4. Set `GOOGLE_SHEETS_CLIENT_SECRET` to that path in `.env`.
5. Run `python -m connectors.google_sheets.authorize` once; sign in as `revops@leadle.in`; this writes
   the token to the path in `GOOGLE_SHEETS_TOKEN` (set that env var first). Both files are gitignored.
6. Ensure each client workbook is shared with `revops@leadle.in` (already true today) and registered
   in `config/clients.yaml`.

## Out of scope (this effort)

- Slack delivery / scheduled push (next sub-project).
- Metric windowing (deferred I1 — weekly vs monthly webhook/spine data).
- Decoupling automation from the personal `revops@leadle.in` account onto a dedicated service user
  (e.g. `reports@leadle.in`) — same OAuth code, different login; revisit if/when offboarding risk
  matters.
- Caching the sheet read (each run fetches fresh; revisit only if rate limits bite).

## Success criteria

- `python -m dashboard.client.render --client UPSTA` (no `--xlsx`) renders the 4 outputs by reading
  the UPSTA sheet live as `revops@leadle.in` — no manual download, no Drive MCP, no base64-in-context.
- `--xlsx <path>` still reproduces a report from a file.
- `read_sheets` and `read_xlsx` produce identical `ClientData` for equivalent input (parity test green).
- Adding a client is a `config/clients.yaml` edit, no code change.
- Read-only throughout (scope `spreadsheets.readonly`).
- Full test suite green, no live Google API calls in tests.
