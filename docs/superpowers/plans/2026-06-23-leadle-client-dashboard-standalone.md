# Leadle Client Dashboard — Standalone Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the client-campaign dashboard renderer from the `leadle-os` monorepo into a completely independent standalone project (`leadle-client-dashboard`) with its own connectors, agents, and tests, then deliver it to Akil via a private GitHub repo and a Google Drive zip.

**Architecture:** This is an *extraction/refactor*, not net-new code. The existing `dashboard/client/**`, the shared agent wrapper `dashboard/agents/_client.py`, and the three connectors (`google_sheets`, `instantly`, `aimfox`) are copied verbatim into a single new package `client_dashboard`, then their imports are mechanically rewritten to the new namespace. The ported test suite is the regression gate that *proves* the rewrite is correct. Because the code already exists, tasks specify exact copy manifests + import-rewrite rules + verification commands rather than authoring logic from scratch.

**Tech Stack:** Python 3.11+, anthropic, httpx, jinja2, tenacity, pydantic, python-dotenv, pyyaml, gspread, google-auth, google-auth-oauthlib, openpyxl. Dev: pytest, pytest-asyncio, ruff. Delivery: `gh` CLI (private repo), Google Drive MCP (zip upload).

## Global Constraints

- **Source repo (read-only source of truth):** `/home/bhuvanesh/AI_Native_Workspace/30-leadle-systems/leadle_gtm_intelligence/` — copy FROM here; never modify monorepo source files in this plan.
- **Target project (all new files):** `/home/bhuvanesh/AI_Native_Workspace/30-leadle-systems/leadle-client-dashboard/` — a sibling directory, NOT inside the monorepo.
- **Package name:** `client_dashboard`. **Project / repo name:** `leadle-client-dashboard`.
- **Completely independent:** the package must not import any top-level `dashboard`, `connectors`, `analytics`, `identity`, `leadle_os_mcp`, or `smoke` module. Verified by an automated independence test.
- **No live external calls in tests:** Google / Anthropic / HTTP are faked or monkeypatched (same invariant as the monorepo). Verify with the grep in the final task.
- **Read-only against source systems:** the connectors only read; no writes. Google Sheets scope stays exactly `spreadsheets.readonly`.
- **Secrets never committed or zipped:** `.env`, `*token*.json`, `*client_secret*.json` are gitignored and excluded from the delivery zip by allowlist. Only `.env.example` ships.
- **GitHub repo visibility:** **private**.
- **Import-rewrite rules** (apply in this exact order to every `.py` under the target, source files first then test files):
  1. `from dashboard.client.agents` → `from client_dashboard.agents`
  2. `from dashboard.client.sources` → `from client_dashboard.sources`
  3. `from dashboard.client import` → `from client_dashboard import`
  4. `from dashboard.client.` → `from client_dashboard.`
  5. `from dashboard.agents._client` → `from client_dashboard.agents._client`
  6. `from connectors.` → `from client_dashboard.connectors.`
- **`_ROOT` depth fix:** any `Path(__file__).resolve().parents[2]` in a copied module that previously resolved to the monorepo root must become `parents[1]` in the new top-level package (known occurrences: `constants.py`, `render.py`).

---

### Task 1: Scaffold the standalone project (installable skeleton)

**Files:**
- Create: `leadle-client-dashboard/pyproject.toml`
- Create: `leadle-client-dashboard/.gitignore`
- Create: `leadle-client-dashboard/client_dashboard/__init__.py` (empty)
- Create: `leadle-client-dashboard/requirements.txt`

**Interfaces:**
- Produces: an installable package shell `client_dashboard` (empty), `pip install -e .` succeeds.

- [ ] **Step 1: Create the project directory and package folder**

```bash
mkdir -p /home/bhuvanesh/AI_Native_Workspace/30-leadle-systems/leadle-client-dashboard/client_dashboard
cd /home/bhuvanesh/AI_Native_Workspace/30-leadle-systems/leadle-client-dashboard
git init -q
: > client_dashboard/__init__.py
```

- [ ] **Step 2: Write `pyproject.toml`**

```toml
[project]
name = "leadle-client-dashboard"
version = "0.1.0"
description = "Standalone Leadle client-campaign dashboard renderer"
requires-python = ">=3.11"
dependencies = [
    "anthropic>=0.40",
    "httpx>=0.27",
    "tenacity>=8.2",
    "jinja2>=3.1",
    "pydantic>=2.6",
    "python-dotenv>=1.0",
    "pyyaml>=6.0",
    "gspread>=6.0",
    "google-auth>=2.29",
    "google-auth-oauthlib>=1.2",
    "openpyxl>=3.1",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23", "ruff>=0.4"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["client_dashboard*"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
line-length = 100
```

- [ ] **Step 3: Write `requirements.txt`** (pip-only path for Akil; mirrors runtime deps)

```text
anthropic>=0.40
httpx>=0.27
tenacity>=8.2
jinja2>=3.1
pydantic>=2.6
python-dotenv>=1.0
pyyaml>=6.0
gspread>=6.0
google-auth>=2.29
google-auth-oauthlib>=1.2
openpyxl>=3.1
```

- [ ] **Step 4: Write `.gitignore`**

```gitignore
.venv/
venv/
__pycache__/
*.py[cod]
.env
.env.*
*token*.json
*client_secret*.json
credentials.json
reports/
.pytest_cache/
.ruff_cache/
dist/
*.egg-info/
```

- [ ] **Step 5: Verify it installs in a clean venv**

```bash
cd /home/bhuvanesh/AI_Native_Workspace/30-leadle-systems/leadle-client-dashboard
python -m venv .venv && .venv/bin/pip install -q -e ".[dev]" && .venv/bin/python -c "import client_dashboard; print('ok')"
```
Expected: `ok` (no errors).

- [ ] **Step 6: Commit the scaffold**

```bash
cd /home/bhuvanesh/AI_Native_Workspace/30-leadle-systems/leadle-client-dashboard
git add pyproject.toml requirements.txt .gitignore client_dashboard/__init__.py
git commit -q -m "chore: scaffold leadle-client-dashboard (installable skeleton)" && git log --oneline -1
```

---

### Task 2: Extract and rewrite the package source

**Files (copy FROM monorepo → TO target, then rewrite imports):**
- Create `client_dashboard/render.py`, `compute.py`, `constants.py`, `model.py`, `snapshots.py` ← from `dashboard/client/`
- Create `client_dashboard/sources/` (`__init__.py`, `base.py`, `loader.py`, `client_registry.py`, `sheet_source.py`, `aimfox_source.py`) ← from `dashboard/client/sources/`
- Create `client_dashboard/agents/` (`__init__.py`, `narrative.py`, `actions.py`) ← from `dashboard/client/agents/`; plus `_client.py`, `_voice.md` ← from `dashboard/agents/`
- Create `client_dashboard/connectors/__init__.py` (empty) and subpackages `google_sheets/` (`__init__.py`, `fetch.py`, `authorize.py`), `instantly/` (`__init__.py`, `fetch.py`), `aimfox/` (`__init__.py`, `fetch.py`) ← from `connectors/`
- Create `client_dashboard/templates/` (`report.html.j2`, `report_base.html.j2`, `blocks/{campaigns,kpis,narrative,deliverability,reach,content,targets,variants}.html.j2`) ← from `dashboard/client/templates/`
- Create `config/clients.yaml` ← from monorepo `config/clients.yaml`

**Interfaces:**
- Produces: `client_dashboard.render` (module with `main()` / `argparse` CLI), `client_dashboard.connectors.google_sheets.authorize` (runnable `-m`), all importable with no `dashboard`/`connectors` top-level references.

- [ ] **Step 1: Copy the source tree verbatim**

```bash
SRC=/home/bhuvanesh/AI_Native_Workspace/30-leadle-systems/leadle_gtm_intelligence
DST=/home/bhuvanesh/AI_Native_Workspace/30-leadle-systems/leadle-client-dashboard
cd "$DST"
# package modules + subpackages
cp "$SRC"/dashboard/client/{render,compute,constants,model,snapshots}.py client_dashboard/
cp -r "$SRC"/dashboard/client/sources client_dashboard/sources
cp -r "$SRC"/dashboard/client/agents client_dashboard/agents
cp -r "$SRC"/dashboard/client/templates client_dashboard/templates
cp "$SRC"/dashboard/agents/_client.py "$SRC"/dashboard/agents/_voice.md client_dashboard/agents/
# connectors as a subpackage
mkdir -p client_dashboard/connectors
: > client_dashboard/connectors/__init__.py
cp -r "$SRC"/connectors/google_sheets client_dashboard/connectors/google_sheets
cp -r "$SRC"/connectors/instantly client_dashboard/connectors/instantly
cp -r "$SRC"/connectors/aimfox client_dashboard/connectors/aimfox
# config
mkdir -p config && cp "$SRC"/config/clients.yaml config/clients.yaml
# strip any copied caches
find client_dashboard -name __pycache__ -type d -prune -exec rm -rf {} +
```

- [ ] **Step 2: Trim non-render connector files**

`instantly/` may carry a `cli.py` and other endpoints not on the render path. Keep only what `__init__.py` and `fetch.py` need:

```bash
cd "$DST/client_dashboard/connectors/instantly"
# If __init__.py imports cli or other modules, keep them; otherwise remove extras.
grep -q "cli" __init__.py || rm -f cli.py
ls
```
Expected: at minimum `__init__.py`, `fetch.py`. If `__init__.py` references other modules, those stay (do not break imports).

- [ ] **Step 3: Apply the import-rewrite rules to every source `.py`**

```bash
cd "$DST"
find client_dashboard -name '*.py' -print0 | xargs -0 sed -i \
  -e 's/from dashboard\.client\.agents/from client_dashboard.agents/g' \
  -e 's/from dashboard\.client\.sources/from client_dashboard.sources/g' \
  -e 's/from dashboard\.client import/from client_dashboard import/g' \
  -e 's/from dashboard\.client\./from client_dashboard./g' \
  -e 's/from dashboard\.agents\._client/from client_dashboard.agents._client/g' \
  -e 's/from connectors\./from client_dashboard.connectors./g'
```

- [ ] **Step 4: Fix `_ROOT` depth in `constants.py` and `render.py`**

```bash
cd "$DST"
sed -i 's/Path(__file__)\.resolve()\.parents\[2\]/Path(__file__).resolve().parents[1]/' \
  client_dashboard/constants.py client_dashboard/render.py
# Audit: any remaining parents[2] in the package that pointed at repo root?
grep -rn "parents\[2\]" client_dashboard/ || echo "no stray parents[2] — good"
```
Expected: `no stray parents[2] — good`. If any remain, inspect and fix so they resolve to the project root or the package dir as the original intent required.

- [ ] **Step 5: Verify the whole package imports with zero monorepo references**

```bash
cd "$DST"
# No lingering old-namespace imports:
grep -rnE "from (dashboard|connectors)\." client_dashboard/ && echo "FAIL: stale imports remain" || echo "imports clean"
# It actually imports:
.venv/bin/python -c "import client_dashboard.render, client_dashboard.compute, client_dashboard.snapshots, client_dashboard.model; import client_dashboard.sources.loader, client_dashboard.sources.sheet_source, client_dashboard.sources.aimfox_source, client_dashboard.sources.client_registry; import client_dashboard.agents.narrative, client_dashboard.agents.actions, client_dashboard.agents._client; import client_dashboard.connectors.google_sheets.fetch, client_dashboard.connectors.google_sheets.authorize, client_dashboard.connectors.instantly.fetch, client_dashboard.connectors.aimfox.fetch; print('all imports ok')"
```
Expected: `imports clean` then `all imports ok`.

- [ ] **Step 6: Verify the CLI entry points resolve**

```bash
cd "$DST"
.venv/bin/python -m client_dashboard.render --help | head -5
.venv/bin/python -c "import runpy, sys; sys.argv=['authorize','--help']" 2>/dev/null; echo "authorize module present:"; .venv/bin/python -c "import client_dashboard.connectors.google_sheets.authorize as a; print(hasattr(a,'__file__'))"
```
Expected: `render --help` prints usage including `--client`, `--all-periods`, `--audience`, `--period-end`, `--xlsx`; authorize present prints `True`.

- [ ] **Step 7: Commit the extracted package**

```bash
cd /home/bhuvanesh/AI_Native_Workspace/30-leadle-systems/leadle-client-dashboard
git add client_dashboard config
git commit -q -m "feat: extract client_dashboard package with rewritten namespace" && git log --oneline -1
```

---

### Task 3: Port the test suite (the rewrite's proof)

**Files:**
- Create `tests/` ← copy from monorepo `tests/client/` (all `.py` + `conftest.py` + `fixtures/`)
- Create `tests/test_independence.py` (NEW — proves no monorepo coupling)

**Interfaces:**
- Consumes: the full `client_dashboard` package from Task 2.
- Produces: a green `pytest -q` run with zero live external calls.

- [ ] **Step 1: Copy the test tree and rewrite imports**

```bash
SRC=/home/bhuvanesh/AI_Native_Workspace/30-leadle-systems/leadle_gtm_intelligence
DST=/home/bhuvanesh/AI_Native_Workspace/30-leadle-systems/leadle-client-dashboard
cd "$DST"
cp -r "$SRC"/tests/client tests
find tests -name __pycache__ -type d -prune -exec rm -rf {} +
# Same rewrite rules, plus bare module-path references in monkeypatch strings:
find tests -name '*.py' -print0 | xargs -0 sed -i \
  -e 's/from dashboard\.client\.agents/from client_dashboard.agents/g' \
  -e 's/from dashboard\.client\.sources/from client_dashboard.sources/g' \
  -e 's/from dashboard\.client import/from client_dashboard import/g' \
  -e 's/from dashboard\.client\./from client_dashboard./g' \
  -e 's/from dashboard\.agents\._client/from client_dashboard.agents._client/g' \
  -e 's/from connectors\./from client_dashboard.connectors./g' \
  -e 's/dashboard\.client\.sources/client_dashboard.sources/g' \
  -e 's/dashboard\.client\.agents/client_dashboard.agents/g' \
  -e 's/dashboard\.client\./client_dashboard./g' \
  -e 's/dashboard\.agents\._client/client_dashboard.agents._client/g' \
  -e 's/\bconnectors\.\(google_sheets\|instantly\|aimfox\)/client_dashboard.connectors.\1/g'
```

The last four rules also catch `monkeypatch.setattr("dashboard.client.sources.loader....")` style **string** references, which the import rules miss.

- [ ] **Step 2: Run the ported suite — expect failures to surface any missed references**

```bash
cd "$DST"
.venv/bin/python -m pytest -q 2>&1 | tail -25
```
Expected first run: most pass; any failure is an `ImportError`/`AttributeError` naming a leftover `dashboard.` or `connectors.` string. Fix each by extending the same rewrite to that exact string, re-run until green. Do NOT change test assertions — only path strings.

- [ ] **Step 3: Add the independence test**

Create `tests/test_independence.py`:

```python
"""The package must be self-contained: no import of monorepo-only top-level modules."""
import ast
import pathlib

PKG = pathlib.Path(__file__).resolve().parents[1] / "client_dashboard"
FORBIDDEN = {"dashboard", "connectors", "analytics", "identity", "leadle_os_mcp", "smoke"}


def _imported_top_levels(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    tops: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            tops.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            tops.add(node.module.split(".")[0])
    return tops


def test_no_monorepo_imports():
    offenders = {}
    for py in PKG.rglob("*.py"):
        bad = _imported_top_levels(py) & FORBIDDEN
        if bad:
            offenders[str(py.relative_to(PKG))] = sorted(bad)
    assert not offenders, f"monorepo imports leaked: {offenders}"
```

- [ ] **Step 4: Run the independence test**

```bash
cd "$DST"
.venv/bin/python -m pytest tests/test_independence.py -q
```
Expected: PASS (1 passed). A failure lists exactly which file still imports a forbidden top-level module — fix it in `client_dashboard/`, re-run.

- [ ] **Step 5: Full green suite + no-live-call audit**

```bash
cd "$DST"
.venv/bin/python -m pytest -q 2>&1 | tail -5
grep -rnE "open_by_key|InstalledAppFlow|from_authorized_user_file|run_local_server" tests/ && echo "FAIL: live Google call in tests" || echo "no live Google calls — good"
```
Expected: all tests pass; `no live Google calls — good`.

- [ ] **Step 6: Commit the test suite**

```bash
cd /home/bhuvanesh/AI_Native_Workspace/30-leadle-systems/leadle-client-dashboard
git add tests
git commit -q -m "test: port client suite + add independence test" && git log --oneline -1
```

---

### Task 4: Author the operator-facing docs

**Files:**
- Create `leadle-client-dashboard/.env.example`
- Create `leadle-client-dashboard/SETUP.md`
- Create `leadle-client-dashboard/README.md`

**Interfaces:**
- Produces: the zero-to-render runbook Akil follows; ships in the zip and the repo.

- [ ] **Step 1: Write `.env.example`** (no real secrets — placeholders only)

```bash
cat > /home/bhuvanesh/AI_Native_Workspace/30-leadle-systems/leadle-client-dashboard/.env.example <<'EOF'
# Leadle Client Dashboard — copy to .env and fill in. NEVER commit .env.

# Anthropic (narrative + actions agents)
ANTHROPIC_API_KEY=

# Campaign numbers (absence degrades those blocks to empty, not a crash)
AIMFOX_API_KEY=
INSTANTLY_API_KEY=

# Google Sheets (OAuth as your @leadle.in identity, scope spreadsheets.readonly)
GOOGLE_SHEETS_CLIENT_SECRET=/absolute/path/to/client_secret.json
GOOGLE_SHEETS_TOKEN=/absolute/path/to/google_sheets_token.json
EOF
```

- [ ] **Step 2: Write `SETUP.md`**

```markdown
# Setup — Leadle Client Dashboard

Run the UPSTA client report on your own machine. Plain Python; no Claude Code, no MCP.

## 1. Python + install
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## 2. Credentials
```bash
cp .env.example .env
```
Fill `.env`:
- `ANTHROPIC_API_KEY`, `AIMFOX_API_KEY`, `INSTANTLY_API_KEY` — ask Bhuvanesh.
- `GOOGLE_SHEETS_CLIENT_SECRET` / `GOOGLE_SHEETS_TOKEN` — see step 3.

## 3. Google Sheets access (one-time)
1. In the leadle.in GCP project: enable the Google Sheets API; OAuth consent screen
   user type **Internal**; add scope `.../auth/spreadsheets.readonly`; create an OAuth
   client of type **Desktop app**; download the client-secret JSON.
2. Point `GOOGLE_SHEETS_CLIENT_SECRET` at that JSON and `GOOGLE_SHEETS_TOKEN` at a
   writable path for the token.
3. Ensure the UPSTA workbook is **shared with your @leadle.in address**.
4. Authorize (opens a browser; sign in as your @leadle.in identity):
   ```bash
   set -a; source .env; set +a
   python -m client_dashboard.connectors.google_sheets.authorize
   ```

## 4. Render
```bash
set -a; source .env; set +a
python -m client_dashboard.render --client UPSTA --all-periods --audience both \
  --period-end $(date +%Y-%m-%d)
```
Offline override: add `--xlsx /path/to/workbook.xlsx` to read a downloaded workbook
instead of the live sheet.

## 5. Output
Four files in `reports/client/`:
`UPSTA-<period_end>-<monthly|weekly>-<internal|client>.html`.

Adding a client: add an entry to `config/clients.yaml` (`client -> spreadsheet_id`) and
share that workbook with your @leadle.in identity. No code change.
```

- [ ] **Step 3: Write `README.md`**

```markdown
# Leadle Client Dashboard

Standalone renderer for Leadle's per-client campaign report. Reads the client workbook
live from Google Sheets plus Aimfox/Instantly campaign APIs, runs deterministic compute,
and writes four HTML reports (monthly/weekly × internal/client).

Extracted from the Leadle OS monorepo as a self-contained project — its own connectors,
agents, and tests; no shared code. See `SETUP.md` to run it.

```bash
pip install -r requirements.txt
python -m client_dashboard.render --client UPSTA --all-periods --audience both
```
```

- [ ] **Step 4: Verify SETUP commands are internally consistent**

```bash
cd /home/bhuvanesh/AI_Native_Workspace/30-leadle-systems/leadle-client-dashboard
grep -q "client_dashboard.connectors.google_sheets.authorize" SETUP.md \
  && grep -q "client_dashboard.render --client UPSTA" SETUP.md \
  && echo "runbook commands match entry points"
```
Expected: `runbook commands match entry points`.

- [ ] **Step 5: Commit the docs**

```bash
cd /home/bhuvanesh/AI_Native_Workspace/30-leadle-systems/leadle-client-dashboard
git add README.md SETUP.md .env.example
git commit -q -m "docs: operator runbook, README, env template" && git log --oneline -1
```

---

### Task 5: Create the private GitHub repo and push

**Files:** none new (remote + history audit only).

**Interfaces:**
- Consumes: the four local commits from Tasks 1–4.
- Produces: a private GitHub repo `leadle-client-dashboard` with `main` pushed.

- [ ] **Step 1: Confirm history carries no secret**

```bash
cd /home/bhuvanesh/AI_Native_Workspace/30-leadle-systems/leadle-client-dashboard
git status --porcelain || true   # working tree should be clean after Task 4
git ls-files | grep -E '\.env$|token.*\.json|client_secret.*\.json' && echo "FAIL: secret tracked" || echo "no secret tracked — good"
git log -p | grep -iE 'api_key|secret|token' | grep -viE 'example|_ENV|GOOGLE_SHEETS_(CLIENT_SECRET|TOKEN)=$|placeholder' || echo "no secret values in history — good"
```
Expected: `no secret tracked — good` and `no secret values in history — good`. If anything real appears, stop and scrub before pushing.

- [ ] **Step 2: Create the private GitHub repo and push**

```bash
cd /home/bhuvanesh/AI_Native_Workspace/30-leadle-systems/leadle-client-dashboard
git branch -M main
gh repo create leadle-client-dashboard --private --source=. --remote=origin --push
gh repo view --json visibility,url --jq '{visibility,url}'
```
Expected: `{"visibility":"PRIVATE","url":"https://github.com/.../leadle-client-dashboard"}`.

- [ ] **Step 3: Verify clean clone installs and tests pass (true independence check)**

```bash
TMP=$(mktemp -d); cd "$TMP"
git clone -q "$(cd /home/bhuvanesh/AI_Native_Workspace/30-leadle-systems/leadle-client-dashboard && git remote get-url origin)" lcd
cd lcd && python -m venv .venv && .venv/bin/pip install -q -e ".[dev]" \
  && .venv/bin/python -m pytest -q 2>&1 | tail -3
```
Expected: full suite passes from a fresh clone with no monorepo on the path. (This is the definitive proof of independence.)

---

### Task 6: Deliver to Akil's Google Drive

**Note:** This task is executed in the **main session** (it needs the Google Drive MCP and ends with a manual sharing step), not by a code subagent.

**Files:**
- Create `dist/leadle-client-dashboard.zip` (transient, gitignored)

**Interfaces:**
- Consumes: the committed, pushed project from Task 5.
- Produces: a Drive folder containing the zip + readable SETUP, ready for Bhuvanesh to share with Akil.

- [ ] **Step 1: Build the delivery zip (secrets + scratch excluded by allowlist)**

```bash
cd /home/bhuvanesh/AI_Native_Workspace/30-leadle-systems/leadle-client-dashboard
mkdir -p dist
git archive --format=zip -o dist/leadle-client-dashboard.zip HEAD
# git archive ships only tracked files → no .env/.venv/token by construction.
unzip -l dist/leadle-client-dashboard.zip | grep -E '\.env$|token|client_secret' && echo "FAIL: secret in zip" || echo "zip clean — no secrets"
```
Expected: `zip clean — no secrets`.

- [ ] **Step 2: Create the Drive folder + upload (main session, Drive MCP)**

In the main session: use `mcp__claude_ai_Google_Drive__create_file` to create a folder
named `Leadle — Client Dashboard Kit` (`mimeType: application/vnd.google-apps.folder`),
then upload `dist/leadle-client-dashboard.zip` into it as base64 with
`contentMimeType: application/zip` and `disableConversionToGoogleType: true`, and upload
`SETUP.md` as `text/plain` (let it convert to a readable Google Doc so Akil can read it
without unzipping). Capture the folder id and zip file id.

- [ ] **Step 3: Confirm upload and hand off the sharing step**

Report the Drive folder link to Bhuvanesh. **Sharing with Akil is done by Bhuvanesh** in
the Drive UI (or provide Akil's email for an explicit add) — the upload lands in
revops@leadle.in's Drive; sharing is a deliberate human action, not automated here.

---

## Final verification (after all tasks)

- [ ] Fresh clone → `pip install -e ".[dev]"` → `pytest -q` all green (Task 5 Step 3).
- [ ] `tests/test_independence.py` passes (no `dashboard`/`connectors`/etc. imports).
- [ ] `python -m client_dashboard.render --help` shows the expected flags.
- [ ] GitHub repo is **private**; no secret in history (`git log -p | grep -iE 'api_key|secret|token' | grep -v example` returns only placeholders).
- [ ] Delivery zip contains no secret; Drive folder created and reported for sharing.
