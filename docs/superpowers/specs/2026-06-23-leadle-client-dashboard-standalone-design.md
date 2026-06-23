# Leadle Client Dashboard — Standalone Project Design

**Date:** 2026-06-23
**Status:** Approved design, pending implementation plan
**Author:** Bhuvanesh (RevOps Architect) + Claude

## Goal

Extract the client-campaign dashboard renderer out of the `leadle-os` monorepo into a
**completely independent** standalone project, `leadle-client-dashboard`, with its own
copies of the connectors and agents it needs, its own dependencies, and its own test
suite — so Akil (Head of RevOps) can set up a folder on his own machine and run client
report renders without any part of the rest of Leadle OS.

Delivery to Akil is via a **Google Drive folder** (a zip of the project). The project
also lives in its **own private GitHub repo** (`leadle-client-dashboard`) for version
control.

## Why this shape (decisions on record)

- **Operator, not consumer.** Akil runs the render himself; he is not just receiving
  output files. So he needs runnable code + setup, not a PDF.
- **Plain Python, no Claude Code, no MCP.** The client render calls the Anthropic API
  directly (`AsyncAnthropic` in the agent wrapper). It touches no MCP server — no
  HubSpot, no `leadle_os_mcp`. Akil needs Python + API keys, nothing else.
- **Completely independent (user directive).** The standalone project carries its own
  `connectors/` and `agents/` rather than sharing the monorepo's. This forks shared
  code — a deliberately accepted maintenance cost (bug fixes now have two homes) in
  exchange for a clean handoff to a separate operator.
- **Own tests come along.** A project that can't be tested without the monorepo is not
  independent. Porting the client test suite also *proves* the namespace rewrite is
  correct.

## Architecture

A single clean package, `client_dashboard`, with connectors and agents folded inside it
(not as top-level siblings). The monorepo's `dashboard/client/*` becomes the package
root; the shared `dashboard/agents/_client.py` and the three connectors become
subpackages.

```
leadle-client-dashboard/
├── pyproject.toml            # name=leadle-client-dashboard, package=client_dashboard
├── README.md                 # what it is, architecture in 3 lines
├── SETUP.md                  # zero-to-render runbook for Akil
├── .env.example              # the 5 keys, no real secrets
├── .gitignore                # .venv, .env, *token*.json, *client_secret*.json, reports/
├── client_dashboard/
│   ├── __init__.py
│   ├── render.py             # entry: python -m client_dashboard.render
│   ├── compute.py
│   ├── constants.py
│   ├── model.py
│   ├── snapshots.py
│   ├── agents/               # OWN copy
│   │   ├── __init__.py
│   │   ├── _client.py        # Anthropic wrapper (was dashboard/agents/_client.py)
│   │   ├── _voice.md
│   │   ├── narrative.py
│   │   └── actions.py
│   ├── sources/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── loader.py
│   │   ├── client_registry.py
│   │   ├── sheet_source.py
│   │   └── aimfox_source.py
│   ├── connectors/           # OWN copy
│   │   ├── __init__.py
│   │   ├── google_sheets/    # __init__, fetch, authorize
│   │   ├── instantly/        # __init__, fetch
│   │   └── aimfox/           # __init__, fetch
│   └── templates/
│       ├── report.html.j2
│       ├── report_base.html.j2
│       └── blocks/*.j2       # campaigns, kpis, narrative, deliverability,
│                             #   reach, content, targets, variants
├── config/
│   └── clients.yaml          # client -> spreadsheet_id registry
└── tests/                    # ported from monorepo tests/client/
    └── (see Test porting)
```

## Namespace rewrite (the core mechanical work)

Every intra-repo import rewrites to the new namespace. There are exactly four edge types
(verified by import-closure scan; nothing imports analytics/identity/leadle_os_mcp/smoke):

| Old (monorepo) | New (standalone) |
|---|---|
| `from dashboard.client.X import …` | `from client_dashboard.X import …` |
| `from dashboard.client import constants` (in connectors) | `from client_dashboard import constants` |
| `from dashboard.agents._client import run_agent` | `from client_dashboard.agents._client import run_agent` |
| `from connectors.aimfox.fetch import …` / `connectors.instantly.fetch` | `from client_dashboard.connectors.aimfox.fetch import …` |

Note the one non-obvious dependency: `connectors/google_sheets/{fetch,authorize}.py`
import `dashboard.client.constants`. In the new layout the connectors live *under* the
package, so this becomes `from client_dashboard import constants` — connectors are part
of `client_dashboard`, not an independent sibling. This is correct and intended.

Entry points after rewrite:
- One-time auth: `python -m client_dashboard.connectors.google_sheets.authorize`
- Render: `python -m client_dashboard.render --client UPSTA --all-periods --audience both --period-end <YYYY-MM-DD>`

## Dependencies (trimmed)

Only the client render's actual deps — the monorepo's supabase/mcp/slack-sdk/psycopg/
thefuzz/tldextract/croniter/structlog are NOT on this path and are dropped.

```
anthropic, httpx, tenacity, jinja2, pydantic, python-dotenv,
pyyaml, gspread, google-auth, google-auth-oauthlib, openpyxl
```
Dev: pytest, pytest-asyncio, ruff. Python >= 3.11.

## Secrets and config

Akil needs five env vars (filled by him; never shipped):
- `ANTHROPIC_API_KEY` — narrative agents
- `AIMFOX_API_KEY`, `INSTANTLY_API_KEY` — campaign numbers (absence degrades those
  blocks to empty, not a crash)
- `GOOGLE_SHEETS_CLIENT_SECRET` — authorize CLI only
- `GOOGLE_SHEETS_TOKEN` — generated by running `authorize` once with his own
  `@leadle.in` Google identity (the UPSTA workbook shared to him)

`.gitignore` and the packaging step both exclude `.env`, `*token*.json`,
`*client_secret*.json` by allowlist, so a real secret cannot reach GitHub or the Drive
folder by construction.

## Test porting

Port `tests/client/` (25 files incl. `conftest.py` + `fixtures/`) with the same
namespace rewrite. These must all pass against the standalone package before delivery —
that is the proof the extraction is correct. Critically includes:
`test_read_sheets_parity.py`, `test_sheets_fetch.py`, `test_sheets_authorize.py`,
`test_parse_tabs.py`, `test_loader.py`, `test_render_cli.py`, `test_render_golden.py`,
`test_compute*.py`, `test_agents.py`. No test may make a live Google/Anthropic/HTTP call
(fakes injected — same invariant as the monorepo).

## SETUP.md (what Akil follows)

1. Install Python 3.11+. `python -m venv .venv && source .venv/bin/activate`
2. `pip install -r requirements.txt` (or `pip install -e .`)
3. `cp .env.example .env`; fill the 5 keys (get API keys from Bhuvanesh; provision a
   GCP OAuth client per the runbook).
4. `python -m client_dashboard.connectors.google_sheets.authorize` — sign in as his
   `@leadle.in` identity (UPSTA sheet must be shared with him).
5. `python -m client_dashboard.render --client UPSTA --all-periods --audience both`
6. Outputs land in `reports/client/<client>-<period_end>-<period>-<audience>.html` (4).

## Delivery

1. Build the project on disk at
   `/home/bhuvanesh/AI_Native_Workspace/30-leadle-systems/leadle-client-dashboard/`.
2. `git init`, commit, create **private** GitHub repo `leadle-client-dashboard`, push.
3. Zip the project (exclude `.git`, `.venv`, `reports/*`, any secret) →
   `leadle-client-dashboard.zip`.
4. Create a Google Drive folder (`Leadle — Client Dashboard Kit`) in revops@leadle.in's
   Drive; upload the zip + a readable copy of `SETUP.md`.
5. Bhuvanesh shares that Drive folder with Akil.

## Out of scope

- Akil running inside Claude Code (not needed — plain Python).
- The HubSpot / Slack / Supabase / 17-analytics paths, the Sai brief, the 4-tab MCP
  dashboard — none ship.
- Any write-back to source systems (read-only invariant holds).
- PDF conversion of outputs (HTML only, as today).
- Automated re-delivery / sync to Drive (manual re-zip when code changes, for now).

## Done when

- Standalone repo exists, `pip install -e .` works in a clean venv.
- Full ported test suite passes (`pytest -q`) with zero live external calls.
- `python -m client_dashboard.render --client UPSTA …` produces the 4 HTML files.
- Private GitHub repo pushed; zip uploaded to the shared Drive folder; no secret in
  either.

## Risks

- **Fork drift.** `connectors/google_sheets` etc. now exist in two repos. Accepted;
  revisit if the client dashboard and monorepo diverge enough to hurt.
- **Namespace-rewrite misses.** Mitigated by porting tests first and running them.
- **Google identity.** Akil authorizes as his own `@leadle.in` account; the UPSTA
  workbook must be shared with him, else `read_sheets` 403s. Documented in SETUP.md.
