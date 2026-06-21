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

## Decisions (locked in brainstorming)

1. **Auth: service account.** A GCP service account with a JSON key; the UPSTA sheet is shared
   read-only with the service-account email. This is the only method that runs unattended (cron /
   scheduled / Slack automation) without a human consent step.
2. **Runtime surface: Sheets default, `--xlsx` optional override.** The pipeline reads live from
   Sheets by default (no path needed). `--xlsx <path>` still works for offline runs, debugging, and
   reproducing a specific report. The file reader stays regardless (tests need a deterministic input).
3. **Architecture: parse core + two row-providers** (Approach A). Decouple "where rows come from"
   from "how rows become `ClientData`". One tested parser, two inputs (xlsx file, live Sheets).
4. **Library: `gspread` + `google-auth`.** Simplest read path (`get_all_values()` returns rows
   directly). Hand-rolling Sheets JWT auth over `httpx` is not worth it. These are the first
   non-`httpx` connector dependencies — justified by the auth complexity.
5. **Read-only invariant honored.** Service-account scope is `spreadsheets.readonly`; the sheet is
   shared as Viewer. No writes, consistent with the project-wide read-only rule.
6. **Single UPSTA sheet, no generalization.** Reuse `constants.SHEET_DRIVE_ID`. No multi-sheet /
   multi-client machinery (YAGNI — matches the productization hardcode decision).

## Architecture

```
render CLI (default: no --xlsx)
   |
loader.load(xlsx_path=None, ...)
   |
   +-- xlsx_path given?  -- yes --> sheet_source.read_xlsx(path)   [openpyxl -> rows]
   |                                          \
   +-- no (default) ------> sheet_source.read_sheets(             \
            SHEET_DRIVE_ID, creds_path=env)                        \
                 |                                                  v
        connectors/google_sheets/fetch.py                   _parse_tabs(tabs) -> ClientData
        (gspread + google-auth, readonly)                   (spine / webhook LI / webhook
                 |  open_by_key, get_all_values per tab       email / response tracker;
                 v                                            header-aware; the existing
            {tab_name: rows}  --------------------------->    tested parsing logic)
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
- **`read_sheets(spreadsheet_id, *, creds_path, client=None) -> ClientData`** — obtains
  `{tab: rows}` from the connector (passing the injectable `client` through for tests), calls
  `_parse_tabs`.

### `connectors/google_sheets/fetch.py` (new — generic raw fetch)
- **`fetch(spreadsheet_id, tab_names, *, creds_path, client=None) -> dict[str, list[list]]`** —
  authorizes a service account from `creds_path` (scope `spreadsheets.readonly`) unless an
  authorized `client` is injected (tests), opens the spreadsheet by key, and returns
  `{tab_name: get_all_values()}` for each requested tab that exists. Tabs absent from the
  spreadsheet are omitted from the result (parser treats missing tabs the same as the xlsx path).

### `dashboard/client/constants.py`
- Add `GOOGLE_SHEETS_ENV = "GOOGLE_SHEETS_CREDENTIALS"` (env var holding the path to the
  service-account JSON). `SHEET_DRIVE_ID` already exists and is reused as the spreadsheet id.

### `dashboard/client/sources/loader.py`
- `load(...)` gains optional `xlsx_path: str | None`. When provided → `read_xlsx(xlsx_path)`. When
  `None` (default) → `read_sheets(constants.SHEET_DRIVE_ID, creds_path=os.environ.get(GOOGLE_SHEETS_ENV))`.
  Sheet read errors propagate (ground truth); Aimfox/Instantly keep degrading independently.

### `dashboard/client/render.py`
- `--xlsx` becomes optional (default `None` → live Sheets). All other args unchanged. Help text notes
  that omitting `--xlsx` reads live from the configured sheet.

## Data flow

- **Default (live):** `render` → `loader.load(xlsx_path=None)` → `read_sheets(SHEET_DRIVE_ID, creds)`
  → `connectors.google_sheets.fetch` authorizes the SA (readonly), `open_by_key`, `get_all_values`
  per known tab → `{tab: rows}` → `_parse_tabs` → `ClientData` → Aimfox + Instantly → compute → render.
- **Override (file):** `render --xlsx <path>` → `read_xlsx(path)` → same `_parse_tabs` → identical
  downstream.

## Credentials

- `GOOGLE_SHEETS_CREDENTIALS` env var = filesystem path to the service-account JSON key.
- `google-auth`: `service_account.Credentials.from_service_account_file(path,
  scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])`.
- The service account must have **Viewer** access to the UPSTA sheet (the user shares it).
- For local runs the var lives in `.env`; for the future scheduled/Slack run it lives in that
  environment's secret store.

## Error handling & degradation

- **Missing/invalid creds** (env unset, file missing/unparseable) → hard fail with an actionable
  message naming `GOOGLE_SHEETS_CREDENTIALS` and instructing to share the sheet with the SA email.
- **Sheets API error / spreadsheet not found / no access** → hard fail. The sheet is the spine /
  ground truth; consistent with the productization spec (only Aimfox/Instantly degrade gracefully).
- **Missing expected tab** → omitted from `{tab: rows}`; `_parse_tabs` handles absence exactly as
  `read_xlsx` does today (no crash, that source's records stay empty).

## Testing (no live Google calls)

- **Parser regression:** existing xlsx-fixture tests continue to exercise `_parse_tabs` via
  `read_xlsx`; add one assertion that `read_xlsx(upsta_mini.xlsx)` output is unchanged after the
  refactor.
- **Connector fetch:** inject a fake gspread-like client (returns canned `get_all_values` per tab);
  assert `fetch(...)` returns the expected `{tab: rows}` and omits absent tabs. No network.
- **Source parity (key guarantee):** feed `read_sheets` (via injected client) the *same rows* the
  xlsx fixture contains; assert the resulting `ClientData` equals `read_xlsx(upsta_mini.xlsx)`. This
  proves the live and file paths produce identical structured data.
- **Loader selection:** `load(xlsx_path=set)` uses the file path; `load(xlsx_path=None)` calls
  `read_sheets` (assert via injection/monkeypatch). No live calls.
- **Missing-creds error:** `read_sheets`/`fetch` with an unset/bad creds path raises the clear error.

## Dependencies

- Add `gspread` and `google-auth` to the project requirements. First non-`httpx` external
  dependencies in the connector layer; justified by Sheets service-account auth.

## Prerequisites (one-time, user-provisioned)

1. Create (or reuse) a GCP project; enable the Google Sheets API.
2. Create a service account; download its JSON key.
3. Share the UPSTA sheet (`SHEET_DRIVE_ID`) as **Viewer** with the service-account email.
4. Set `GOOGLE_SHEETS_CREDENTIALS` to the key path in `.env` (and later in the cron/Slack env).

## Out of scope (this effort)

- Slack delivery / scheduled push (next sub-project).
- Metric windowing (deferred I1 — weekly vs monthly webhook/spine data).
- Multi-sheet / multi-client generalization.
- Caching the sheet read (each run fetches fresh; revisit only if rate limits bite).

## Success criteria

- `python -m dashboard.client.render` (no `--xlsx`) renders the 4 outputs by reading the UPSTA sheet
  live via the service account — no manual download, no Drive MCP, no base64-in-context.
- `--xlsx <path>` still reproduces a report from a file.
- `read_sheets` and `read_xlsx` produce identical `ClientData` for equivalent input (parity test green).
- Read-only throughout (SA scope `spreadsheets.readonly`).
- Full test suite green, no live Google API calls in tests.
