# Dashboard Fasttrack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a 4-tab generated dashboard for Leadle's GTM funnel, system health, and delivery health — fed live from 5 hosted MCPs, output to local HTML.

**Architecture:** `/render-dashboard` slash command orchestrates Claude as MCP client; Python computes deterministic analytics, runs 4 LLM-narrative agents via the Anthropic SDK, renders Jinja templates, writes single-file HTML to `./reports/`. No database, no scheduling. Spec: `docs/superpowers/specs/2026-05-09-dashboard-fasttrack-design.md`.

**Tech Stack:** Python 3.11+, Anthropic SDK, MCP (HTTP transport), Jinja2, structlog, tenacity, pytest, ruamel.yaml.

**Phases:** 9 phases. Each phase ends with a commit producing a working state.

---

## Phase 0 — Setup

**Purpose:** Verify dev environment, install deps, scaffold directories. No code, no tests yet.

### Task 0.1: Verify Python and dev deps installed

**Files:** none (environment check)

- [ ] **Step 1: Verify Python 3.11+**

```bash
python --version
```
Expected: `Python 3.11.x` or higher. If lower, install Python 3.11+.

- [ ] **Step 2: Install project + dev deps via uv (or pip)**

```bash
cd /home/bhuvanesh/leadle_master_claude
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

- [ ] **Step 3: Verify pytest runs**

```bash
pytest --version
```
Expected: `pytest 8.x` reported.

- [ ] **Step 4: Verify imports of key libs**

```bash
python -c "import anthropic, jinja2, structlog, tenacity, ruamel.yaml; print('ok')"
```
Expected: `ok`

### Task 0.2: Scaffold directories

**Files:**
- Create: `dashboard/compute/__init__.py` (empty)
- Create: `dashboard/agents/__init__.py` (empty)
- Create: `tests/fixtures/.gitkeep` (empty placeholder)
- Create: `.cache/.gitkeep` (empty placeholder)

- [ ] **Step 1: Make directories**

```bash
cd /home/bhuvanesh/leadle_master_claude
mkdir -p dashboard/compute dashboard/agents tests/fixtures .cache
touch dashboard/compute/__init__.py dashboard/agents/__init__.py tests/fixtures/.gitkeep .cache/.gitkeep
```

- [ ] **Step 2: Add `.cache/` to `.gitignore` (transient JSON dumps shouldn't commit)**

Modify `.gitignore`, add under `# Generated` section:
```
.cache/*
!.cache/.gitkeep
```

- [ ] **Step 3: Verify pytest still discovers correctly**

```bash
pytest --collect-only 2>&1 | head -20
```
Expected: collects 0 tests cleanly (no errors).

### Task 0.3: Commit Phase 0

- [ ] **Step 1: Stage and commit**

```bash
git add dashboard/compute dashboard/agents tests/fixtures .cache .gitignore
git commit -m "$(cat <<'EOF'
Scaffold dashboard fasttrack directories

Adds dashboard/compute/, dashboard/agents/, tests/fixtures/, .cache/.
Empty packages — implementations land in subsequent phases.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Phase 1 — Window resolver (TDD-required, highest leverage)

**Purpose:** Build the load-bearing date arithmetic. If this is right, every compute module operating on `WindowSpec` is automatically right. If wrong, every section silently shows wrong data.

### Task 1.1: Create `config/dashboard_windows.yaml`

**Files:**
- Create: `config/dashboard_windows.yaml`

- [ ] **Step 1: Write the YAML**

```yaml
# Indian fiscal year: Apr–Mar. FY label = year of fiscal start.
fiscal_year:
  start_month: 4

quarters:
  q1: [4, 5, 6]
  q2: [7, 8, 9]
  q3: [10, 11, 12]
  q4: [1, 2, 3]

supported_windows:
  - current-week
  - last-week
  - last-7d
  - current-month
  - last-month
  - month-april
  - month-may
  - month-june
  - month-july
  - month-august
  - month-september
  - month-october
  - month-november
  - month-december
  - month-january
  - month-february
  - month-march
  - last-30d
  - last-60d
  - last-90d
  - current-quarter
  - last-quarter
  - q1
  - q2
  - q3
  - q4
```

### Task 1.2: WindowSpec dataclass + skeleton resolve_window

**Files:**
- Create: `dashboard/compute/windows.py`

- [ ] **Step 1: Write the failing test for WindowSpec instantiation**

Create `tests/test_windows.py`:
```python
from datetime import date
from dashboard.compute.windows import WindowSpec, resolve_window


def test_window_spec_is_frozen():
    spec = WindowSpec(
        name="last-7d",
        label="Last 7 days",
        start=date(2026, 5, 2),
        end=date(2026, 5, 9),
        prior_start=date(2026, 4, 25),
        prior_end=date(2026, 5, 1),
    )
    assert spec.name == "last-7d"


def test_resolve_window_unknown_arg_raises():
    import pytest
    with pytest.raises(ValueError, match="Unknown window"):
        resolve_window("nonsense", date(2026, 5, 9))
```

- [ ] **Step 2: Run test — should fail with ImportError**

```bash
pytest tests/test_windows.py -v
```
Expected: `ImportError` (`dashboard.compute.windows` doesn't exist yet).

- [ ] **Step 3: Implement skeleton `windows.py`**

```python
"""Window resolution: window arg + today → concrete WindowSpec.

The dashboard uses an Indian fiscal year (Apr–Mar). FY2026 = Apr 2026 – Mar 2027.
Every window arg resolves to (start, end, prior_start, prior_end) given today.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Final

from ruamel.yaml import YAML

_CONFIG_PATH: Final = Path(__file__).resolve().parents[2] / "config" / "dashboard_windows.yaml"


@dataclass(frozen=True)
class WindowSpec:
    name: str
    label: str
    start: date
    end: date           # inclusive
    prior_start: date
    prior_end: date     # inclusive


def _load_config() -> dict:
    return YAML(typ="safe").load(_CONFIG_PATH.read_text())


def resolve_window(arg: str, today: date) -> WindowSpec:
    """Map a window arg to a concrete WindowSpec.

    Raises ValueError if arg is not in supported_windows.
    """
    cfg = _load_config()
    if arg not in cfg["supported_windows"]:
        raise ValueError(f"Unknown window: {arg!r}. See config/dashboard_windows.yaml.")
    raise NotImplementedError(f"Window {arg} not yet implemented")
```

- [ ] **Step 4: Run test — both tests should now pass**

```bash
pytest tests/test_windows.py -v
```
Expected: both tests PASS (`test_window_spec_is_frozen`, `test_resolve_window_unknown_arg_raises`).

### Task 1.3: TDD rolling-day windows (`last-7d`, `last-30d`, `last-60d`, `last-90d`)

**Files:**
- Modify: `tests/test_windows.py`
- Modify: `dashboard/compute/windows.py`

- [ ] **Step 1: Add failing tests for rolling-day windows**

Append to `tests/test_windows.py`:
```python
import pytest


@pytest.mark.parametrize("arg, days", [
    ("last-7d", 7),
    ("last-30d", 30),
    ("last-60d", 60),
    ("last-90d", 90),
])
def test_rolling_day_windows(arg, days):
    today = date(2026, 5, 9)
    spec = resolve_window(arg, today)
    assert spec.end == today
    assert (spec.end - spec.start).days == days - 1
    # prior period = same length, ending the day before window start
    assert spec.prior_end == spec.start - timedelta(days=1)
    assert (spec.prior_end - spec.prior_start).days == days - 1
```

- [ ] **Step 2: Run — expect FAIL with NotImplementedError**

```bash
pytest tests/test_windows.py -k rolling -v
```
Expected: `NotImplementedError`.

- [ ] **Step 3: Implement rolling-day branch in `resolve_window`**

Replace the `raise NotImplementedError` line with:
```python
    # Rolling N-day windows: last-7d, last-30d, last-60d, last-90d
    if arg.startswith("last-") and arg.endswith("d"):
        try:
            days = int(arg[5:-1])
        except ValueError:
            raise ValueError(f"Bad rolling-day arg: {arg!r}")
        end = today
        start = today - timedelta(days=days - 1)
        prior_end = start - timedelta(days=1)
        prior_start = prior_end - timedelta(days=days - 1)
        return WindowSpec(
            name=arg,
            label=f"Last {days} days ({start:%b %-d} – {end:%b %-d, %Y})",
            start=start, end=end,
            prior_start=prior_start, prior_end=prior_end,
        )

    raise NotImplementedError(f"Window {arg} not yet implemented")
```

- [ ] **Step 4: Run — should pass**

```bash
pytest tests/test_windows.py -v
```
Expected: all rolling-day tests PASS.

### Task 1.4: TDD calendar-month windows (`current-month`, `last-month`)

- [ ] **Step 1: Add failing tests**

Append to `tests/test_windows.py`:
```python
def test_current_month_window():
    spec = resolve_window("current-month", date(2026, 5, 9))
    assert spec.start == date(2026, 5, 1)
    assert spec.end == date(2026, 5, 31)
    assert spec.prior_start == date(2026, 4, 1)
    assert spec.prior_end == date(2026, 4, 30)
    assert "May 2026" in spec.label


def test_last_month_window():
    spec = resolve_window("last-month", date(2026, 5, 9))
    assert spec.start == date(2026, 4, 1)
    assert spec.end == date(2026, 4, 30)
    assert spec.prior_start == date(2026, 3, 1)
    assert spec.prior_end == date(2026, 3, 31)


def test_current_month_january_rolls_back_to_december_prior():
    spec = resolve_window("current-month", date(2026, 1, 15))
    assert spec.start == date(2026, 1, 1)
    assert spec.end == date(2026, 1, 31)
    assert spec.prior_start == date(2025, 12, 1)
    assert spec.prior_end == date(2025, 12, 31)
```

- [ ] **Step 2: Run — expect FAIL**

```bash
pytest tests/test_windows.py -k month -v
```
Expected: NotImplementedError on three tests.

- [ ] **Step 3: Implement month helpers + branch**

Add at module top, after imports:
```python
import calendar


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    """Return (first_day, last_day) of a calendar month."""
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def _prior_month(year: int, month: int) -> tuple[int, int]:
    """Return (year, month) of the calendar month before this one."""
    if month == 1:
        return year - 1, 12
    return year, month - 1
```

Add inside `resolve_window`, before the rolling-day branch:
```python
    if arg == "current-month":
        s, e = _month_bounds(today.year, today.month)
        py, pm = _prior_month(today.year, today.month)
        ps, pe = _month_bounds(py, pm)
        return WindowSpec(
            name=arg,
            label=f"{s:%B %Y}",
            start=s, end=e,
            prior_start=ps, prior_end=pe,
        )

    if arg == "last-month":
        py, pm = _prior_month(today.year, today.month)
        s, e = _month_bounds(py, pm)
        ppy, ppm = _prior_month(py, pm)
        ps, pe = _month_bounds(ppy, ppm)
        return WindowSpec(
            name=arg,
            label=f"{s:%B %Y}",
            start=s, end=e,
            prior_start=ps, prior_end=pe,
        )
```

- [ ] **Step 4: Run — all month tests should pass**

```bash
pytest tests/test_windows.py -k month -v
```
Expected: PASS.

### Task 1.5: TDD weekly windows (`current-week`, `last-week`)

- [ ] **Step 1: Add failing tests**

Append:
```python
def test_current_week_iso_monday_to_sunday():
    # 2026-05-09 is a Saturday; ISO week is Mon May 4 – Sun May 10
    spec = resolve_window("current-week", date(2026, 5, 9))
    assert spec.start == date(2026, 5, 4)   # Monday
    assert spec.end == date(2026, 5, 10)    # Sunday
    assert spec.prior_start == date(2026, 4, 27)  # prior Monday
    assert spec.prior_end == date(2026, 5, 3)     # prior Sunday


def test_last_week_iso():
    spec = resolve_window("last-week", date(2026, 5, 9))
    assert spec.start == date(2026, 4, 27)
    assert spec.end == date(2026, 5, 3)
    assert spec.prior_start == date(2026, 4, 20)
    assert spec.prior_end == date(2026, 4, 26)
```

- [ ] **Step 2: Run — FAIL**

```bash
pytest tests/test_windows.py -k week -v
```

- [ ] **Step 3: Implement weekly branch**

Add helper at module level:
```python
def _iso_week_bounds(d: date) -> tuple[date, date]:
    """Return (Monday, Sunday) of the ISO week containing d."""
    monday = d - timedelta(days=d.weekday())
    return monday, monday + timedelta(days=6)
```

Add branch in `resolve_window`, before rolling-day:
```python
    if arg == "current-week":
        s, e = _iso_week_bounds(today)
        ps = s - timedelta(days=7)
        pe = e - timedelta(days=7)
        return WindowSpec(
            name=arg,
            label=f"Week of {s:%b %-d, %Y}",
            start=s, end=e,
            prior_start=ps, prior_end=pe,
        )

    if arg == "last-week":
        cs, _ = _iso_week_bounds(today)
        s = cs - timedelta(days=7)
        e = s + timedelta(days=6)
        ps = s - timedelta(days=7)
        pe = e - timedelta(days=7)
        return WindowSpec(
            name=arg,
            label=f"Week of {s:%b %-d, %Y}",
            start=s, end=e,
            prior_start=ps, prior_end=pe,
        )
```

- [ ] **Step 4: Run — PASS**

```bash
pytest tests/test_windows.py -k week -v
```

### Task 1.6: TDD fiscal quarters (`q1`, `q2`, `q3`, `q4`, `current-quarter`, `last-quarter`)

- [ ] **Step 1: Add failing tests**

Append:
```python
@pytest.mark.parametrize("today, arg, expected_start, expected_end, expected_label_contains", [
    # Today in May 2026 → FY2026 (Apr 2026 – Mar 2027) is current FY
    (date(2026, 5, 9), "q1", date(2026, 4, 1), date(2026, 6, 30), "Q1 FY2026"),
    (date(2026, 5, 9), "q2", date(2026, 7, 1), date(2026, 9, 30), "Q2 FY2026"),
    (date(2026, 5, 9), "q3", date(2026, 10, 1), date(2026, 12, 31), "Q3 FY2026"),
    (date(2026, 5, 9), "q4", date(2027, 1, 1), date(2027, 3, 31), "Q4 FY2026"),
    (date(2026, 5, 9), "current-quarter", date(2026, 4, 1), date(2026, 6, 30), "Q1 FY2026"),
    (date(2026, 5, 9), "last-quarter", date(2026, 1, 1), date(2026, 3, 31), "Q4 FY2025"),

    # Today in Feb 2026 → FY2025 (Apr 2025 – Mar 2026) is current FY
    (date(2026, 2, 15), "current-quarter", date(2026, 1, 1), date(2026, 3, 31), "Q4 FY2025"),
    (date(2026, 2, 15), "q1", date(2025, 4, 1), date(2025, 6, 30), "Q1 FY2025"),

    # Today on FY boundary
    (date(2026, 4, 1), "current-quarter", date(2026, 4, 1), date(2026, 6, 30), "Q1 FY2026"),
    (date(2026, 3, 31), "current-quarter", date(2026, 1, 1), date(2026, 3, 31), "Q4 FY2025"),
])
def test_quarter_resolution(today, arg, expected_start, expected_end, expected_label_contains):
    spec = resolve_window(arg, today)
    assert spec.start == expected_start
    assert spec.end == expected_end
    assert expected_label_contains in spec.label
```

- [ ] **Step 2: Run — FAIL**

```bash
pytest tests/test_windows.py -k quarter -v
```

- [ ] **Step 3: Implement FY quarter helpers + branches**

Add helpers:
```python
def _current_fy(today: date, fy_start_month: int) -> int:
    """Return the FY label (year of fiscal start) for today.

    Indian FY: Apr–Mar. FY2026 = Apr 2026 – Mar 2027.
    If today is Feb 2026 and FY starts in April, current FY = 2025 (Apr 2025 – Mar 2026).
    """
    if today.month >= fy_start_month:
        return today.year
    return today.year - 1


def _quarter_bounds(fy: int, q: str, quarters_cfg: dict[str, list[int]]) -> tuple[date, date]:
    """Return (start, end) of quarter q in fiscal year fy.

    quarters_cfg maps quarter name to list of calendar months, e.g. {'q4': [1,2,3]}.
    Months belonging to the *next* calendar year (q4 in Indian FY) roll forward.
    """
    months = quarters_cfg[q]
    fy_start = months[0]  # first month of this quarter
    # If quarter starts in or after FY start month, it's in the FY-start year.
    # Otherwise it's in the next calendar year (q4 case).
    quarters_starting_year = fy if fy_start >= 4 else fy + 1
    s_year = quarters_starting_year
    s_month = months[0]
    e_year = quarters_starting_year if months[-1] >= months[0] else quarters_starting_year
    e_month = months[-1]
    s = date(s_year, s_month, 1)
    e_last_day = calendar.monthrange(e_year, e_month)[1]
    e = date(e_year, e_month, e_last_day)
    return s, e


def _which_quarter(today: date, quarters_cfg: dict[str, list[int]]) -> str:
    """Return the quarter name (q1/q2/q3/q4) containing today's calendar month."""
    for qname, months in quarters_cfg.items():
        if today.month in months:
            return qname
    raise RuntimeError(f"No quarter contains month {today.month} — config error")


def _prior_quarter(q: str) -> tuple[str, int]:
    """Return (prior_quarter_name, fy_offset) — fy_offset=-1 if prior is in prior FY."""
    order = ["q1", "q2", "q3", "q4"]
    i = order.index(q)
    if i == 0:
        return "q4", -1
    return order[i - 1], 0
```

Add branches in `resolve_window`:
```python
    quarters_cfg = cfg["quarters"]
    fy_start_month = cfg["fiscal_year"]["start_month"]
    current_fy = _current_fy(today, fy_start_month)

    # Specific quarter args (q1, q2, q3, q4) → that quarter of *current* FY
    if arg in quarters_cfg:
        s, e = _quarter_bounds(current_fy, arg, quarters_cfg)
        ps, pe = _quarter_bounds(current_fy - 1, arg, quarters_cfg)
        return WindowSpec(
            name=f"{arg}-fy{current_fy}",
            label=f"{arg.upper()} FY{current_fy} ({s:%b}–{e:%b %Y})",
            start=s, end=e,
            prior_start=ps, prior_end=pe,
        )

    if arg == "current-quarter":
        q = _which_quarter(today, quarters_cfg)
        # The quarter's FY is current_fy unless q4 + today's month is Jan/Feb/Mar
        # (q4 of FY N happens in calendar Jan–Mar of year N+1, so the FY label is N).
        q_fy = current_fy
        s, e = _quarter_bounds(q_fy, q, quarters_cfg)
        prior_q, fy_offset = _prior_quarter(q)
        ps, pe = _quarter_bounds(q_fy + fy_offset, prior_q, quarters_cfg)
        return WindowSpec(
            name=f"{q}-fy{q_fy}",
            label=f"{q.upper()} FY{q_fy} ({s:%b}–{e:%b %Y})",
            start=s, end=e,
            prior_start=ps, prior_end=pe,
        )

    if arg == "last-quarter":
        q_now = _which_quarter(today, quarters_cfg)
        prior_q, fy_offset = _prior_quarter(q_now)
        prior_q_fy = current_fy + fy_offset
        s, e = _quarter_bounds(prior_q_fy, prior_q, quarters_cfg)
        # prior of prior:
        prior_prior_q, fy_offset2 = _prior_quarter(prior_q)
        ps, pe = _quarter_bounds(prior_q_fy + fy_offset2, prior_prior_q, quarters_cfg)
        return WindowSpec(
            name=f"{prior_q}-fy{prior_q_fy}",
            label=f"{prior_q.upper()} FY{prior_q_fy} ({s:%b}–{e:%b %Y})",
            start=s, end=e,
            prior_start=ps, prior_end=pe,
        )
```

- [ ] **Step 4: Run — all quarter tests should pass**

```bash
pytest tests/test_windows.py -k quarter -v
```
Expected: 10 PASS.

### Task 1.7: TDD named-month windows (`month-april` … `month-march`)

- [ ] **Step 1: Add failing tests**

Append:
```python
@pytest.mark.parametrize("today, arg, expected_year, expected_month", [
    # Today in May 2026 (FY2026)
    (date(2026, 5, 9), "month-april", 2026, 4),     # FY2026's April = Apr 2026
    (date(2026, 5, 9), "month-may", 2026, 5),
    (date(2026, 5, 9), "month-march", 2027, 3),     # FY2026's March = Mar 2027
    (date(2026, 5, 9), "month-january", 2027, 1),

    # Today in Feb 2026 (FY2025)
    (date(2026, 2, 15), "month-april", 2025, 4),    # FY2025's April = Apr 2025
    (date(2026, 2, 15), "month-march", 2026, 3),    # FY2025's March = Mar 2026
])
def test_named_month_resolves_within_current_fy(today, arg, expected_year, expected_month):
    spec = resolve_window(arg, today)
    assert spec.start.year == expected_year
    assert spec.start.month == expected_month
    assert spec.start.day == 1
```

- [ ] **Step 2: Run — FAIL**

```bash
pytest tests/test_windows.py -k named_month -v
```

- [ ] **Step 3: Implement named-month branch**

Add helper:
```python
_MONTH_NAMES = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}
```

Add branch in `resolve_window`, before the q1/q2/q3/q4 branch:
```python
    if arg.startswith("month-"):
        name = arg[len("month-"):]
        if name not in _MONTH_NAMES:
            raise ValueError(f"Bad named-month arg: {arg!r}")
        target_month = _MONTH_NAMES[name]
        # Resolve within current FY: months in [fy_start..12] live in calendar year = fy
        #                            months in [1..fy_start-1] live in calendar year = fy + 1
        if target_month >= fy_start_month:
            target_year = current_fy
        else:
            target_year = current_fy + 1
        s, e = _month_bounds(target_year, target_month)
        # Prior period = same month in prior FY
        if target_month >= fy_start_month:
            prior_year = current_fy - 1
        else:
            prior_year = current_fy   # since prior FY's same-month is one year earlier in calendar
        ps, pe = _month_bounds(prior_year, target_month)
        return WindowSpec(
            name=arg,
            label=f"{s:%B %Y}",
            start=s, end=e,
            prior_start=ps, prior_end=pe,
        )
```

- [ ] **Step 4: Run — all named-month tests pass**

```bash
pytest tests/test_windows.py -v
```
Expected: every test PASS.

### Task 1.8: Commit Phase 1

- [ ] **Step 1: Run full test suite**

```bash
pytest tests/test_windows.py -v
```
Expected: ~25+ tests PASS.

- [ ] **Step 2: Commit**

```bash
git add config/dashboard_windows.yaml dashboard/compute/windows.py tests/test_windows.py
git commit -m "$(cat <<'EOF'
Add window resolver with FY-aware date arithmetic

Implements WindowSpec dataclass and resolve_window() supporting
weekly, monthly, quarterly, rolling-N-day, and named-month windows.
Uses Indian fiscal year (Apr–Mar). 25+ parametrized tests cover FY
boundary cases (Mar 31, Apr 1, Q4 wrap-around).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Phase 2 — Compute foundation (configs, shared helpers, fixture)

**Purpose:** Stand up the shared compute scaffolding all per-page modules will use.

### Task 2.1: Create `config/dashboard_rules.yaml`

**Files:**
- Create: `config/dashboard_rules.yaml`

- [ ] **Step 1: Write the YAML**

```yaml
rotting_deal_days: 14
stalled_lead_days: 5
followup_gap_days: 5
outreach_min_sends: 10
anomaly_pct_threshold: 30

hygiene:
  require_owner: true
  require_source: true
  require_lifecycle: true

fathom_gap:
  attendee_match_strategy: email_domain_first
  fuzzy_match_threshold: 85
```

### Task 2.2: Create `config/dashboard_targets.yaml`

- [ ] **Step 1: Write the YAML**

```yaml
# USD per the dashboard mock. Resolve INR conversion at use-site if needed.
annual:
  goal_amount: 319000
  goal_currency: USD
  target_date: 2026-10-31

monthly:
  target_amount: 61800
  target_currency: USD

pipeline_coverage:
  ratio_target: 3.0
  ratio_warning_below: 2.0
  ratio_critical_below: 1.0
```

### Task 2.3: Create `config/dashboard_layout.yaml`

- [ ] **Step 1: Write the YAML**

```yaml
pages:
  page1_revenue:
    enabled: true
    sections:
      goal_snapshot: true
      monthly_control: true
      execution: true
      channel_performance: true
      channel_economics: true
      funnel: true
      accountability: true
      hygiene: true
      forward_motion: true
  page2_activity:
    enabled: true
  page3_actions:
    enabled: true
  page4_outreach:
    enabled: true
```

### Task 2.4: TDD `compute/shared.py` helpers

**Files:**
- Create: `dashboard/compute/shared.py`
- Create: `tests/test_compute_shared.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_compute_shared.py
from datetime import date
import pytest
from dashboard.compute.shared import pct_diff, pacing_status, days_between, in_window


def test_pct_diff_normal():
    assert pct_diff(120, 100) == 20.0
    assert pct_diff(80, 100) == -20.0


def test_pct_diff_baseline_zero_returns_none():
    # Cannot compute % when baseline is zero
    assert pct_diff(50, 0) is None


def test_pacing_status_on_track():
    # 50% of period elapsed, 50% of goal achieved → on-track
    assert pacing_status(achieved=50, target=100, fraction_elapsed=0.5) == "on-track"


def test_pacing_status_critical():
    # 50% elapsed, 5% achieved → critical
    assert pacing_status(achieved=5, target=100, fraction_elapsed=0.5) == "critical"


def test_pacing_status_warning():
    # 50% elapsed, 30% achieved → warning
    assert pacing_status(achieved=30, target=100, fraction_elapsed=0.5) == "warning"


def test_days_between_inclusive():
    assert days_between(date(2026, 5, 1), date(2026, 5, 9)) == 8


def test_in_window_inclusive_bounds():
    start = date(2026, 5, 1)
    end = date(2026, 5, 31)
    assert in_window(date(2026, 5, 1), start, end) is True
    assert in_window(date(2026, 5, 31), start, end) is True
    assert in_window(date(2026, 4, 30), start, end) is False
    assert in_window(date(2026, 6, 1), start, end) is False
```

- [ ] **Step 2: Run — FAIL**

```bash
pytest tests/test_compute_shared.py -v
```

- [ ] **Step 3: Implement `compute/shared.py`**

```python
"""Shared compute helpers: date math, pacing status, anomaly diff.

Intentionally tiny — these are utilities for per-page compute modules.
"""
from __future__ import annotations

from datetime import date


def pct_diff(current: float, baseline: float) -> float | None:
    """Percent change from baseline → current. None if baseline is zero."""
    if baseline == 0:
        return None
    return (current - baseline) / baseline * 100.0


def pacing_status(achieved: float, target: float, fraction_elapsed: float) -> str:
    """Classify pacing: on-track, warning, critical.

    on-track:  achieved/target >= fraction_elapsed * 0.9
    warning:   achieved/target >= fraction_elapsed * 0.5  (but not on-track)
    critical:  below warning threshold
    """
    if target <= 0:
        return "warning"  # missing target = warning, not critical
    achieved_frac = achieved / target
    if achieved_frac >= fraction_elapsed * 0.9:
        return "on-track"
    if achieved_frac >= fraction_elapsed * 0.5:
        return "warning"
    return "critical"


def days_between(start: date, end: date) -> int:
    """Inclusive day count between two dates."""
    return (end - start).days + 1


def in_window(d: date, start: date, end: date) -> bool:
    """Inclusive both ends."""
    return start <= d <= end
```

- [ ] **Step 4: Run — PASS**

```bash
pytest tests/test_compute_shared.py -v
```

### Task 2.5: Create `tests/fixtures/sample_raw.json`

**Files:**
- Create: `tests/fixtures/sample_raw.json`

- [ ] **Step 1: Write a minimal hand-crafted fixture**

```json
{
  "render_id": "test-fixture-001",
  "window": {
    "name": "current-month",
    "label": "May 2026",
    "start": "2026-05-01",
    "end": "2026-05-31",
    "prior_start": "2026-04-01",
    "prior_end": "2026-04-30"
  },
  "rendered_at": "2026-05-09T10:00:00+05:30",
  "sources": {
    "hubspot": {
      "available": true,
      "fetched_at": "2026-05-09T09:55:00+05:30",
      "data": {
        "deals": [
          {
            "id": "1001", "dealname": "Scalenut",
            "amount": 5000, "dealstage": "discovery",
            "closedate": null, "createdate": "2026-03-04",
            "last_activity_date": "2026-03-08",
            "hubspot_owner_id": "owner-sai",
            "hs_analytics_source": "ORGANIC_SEARCH",
            "company_id": "comp-101"
          },
          {
            "id": "1002", "dealname": "QuoDeck",
            "amount": 8000, "dealstage": "proposal",
            "closedate": null, "createdate": "2026-04-15",
            "last_activity_date": "2026-04-20",
            "hubspot_owner_id": "owner-sai",
            "hs_analytics_source": "DIRECT_TRAFFIC",
            "company_id": "comp-102"
          },
          {
            "id": "1003", "dealname": "Acme Won",
            "amount": 12000, "dealstage": "closedwon",
            "closedate": "2026-04-28", "createdate": "2026-02-10",
            "last_activity_date": "2026-04-28",
            "hubspot_owner_id": "owner-sai",
            "hs_analytics_source": "REFERRALS",
            "company_id": "comp-103"
          }
        ],
        "contacts": [
          {
            "id": "c1", "email": "alice@scalenut.com",
            "lifecyclestage": "lead",
            "hs_analytics_source": "ORGANIC_SEARCH",
            "createdate": "2026-03-01",
            "last_activity_date": "2026-04-15",
            "hubspot_owner_id": "owner-sai"
          },
          {
            "id": "c2", "email": "bob@quodeck.com",
            "lifecyclestage": "salesqualifiedlead",
            "hs_analytics_source": "DIRECT_TRAFFIC",
            "createdate": "2026-04-10",
            "last_activity_date": "2026-04-20",
            "hubspot_owner_id": "owner-sai"
          }
        ],
        "companies": [
          {"id": "comp-101", "name": "Scalenut", "domain": "scalenut.com"},
          {"id": "comp-102", "name": "QuoDeck", "domain": "quodeck.com"},
          {"id": "comp-103", "name": "Acme", "domain": "acme.com"}
        ],
        "owners": [
          {"id": "owner-sai", "firstName": "Sai", "lastName": "K", "email": "sai@leadle.in"}
        ]
      }
    },
    "lemlist": {
      "available": true,
      "fetched_at": "2026-05-09T09:55:30+05:30",
      "data": {
        "campaigns": [
          {
            "id": "lc1", "name": "RevOps Q2 Outbound",
            "stats": {"sends": 120, "opens": 45, "replies": 8, "meetings": 2},
            "created_at": "2026-04-01"
          }
        ],
        "leads": [
          {
            "id": "ll-1", "email": "alice@scalenut.com",
            "campaign_id": "lc1",
            "hubspot_contact_id": "c1",
            "reply_status": "positive",
            "replied_at": "2026-04-15"
          }
        ]
      }
    },
    "aimfox": {
      "available": true,
      "fetched_at": "2026-05-09T09:55:45+05:30",
      "data": {
        "campaigns": [
          {
            "id": "ac1", "name": "CTO LinkedIn",
            "stats": {"sends": 80, "replies": 5, "meetings": 1}
          }
        ],
        "leads": []
      }
    },
    "instantly": {
      "available": true,
      "fetched_at": "2026-05-09T09:56:00+05:30",
      "data": {
        "campaigns": [
          {
            "id": "ic1", "name": "Email Drip Q2",
            "stats": {"sends": 200, "replies": 12, "meetings": 3}
          }
        ],
        "leads": []
      }
    },
    "fathom": {
      "available": true,
      "fetched_at": "2026-05-09T09:56:15+05:30",
      "data": {
        "meetings": [
          {
            "id": "fm1", "title": "Discovery — Scalenut",
            "scheduled_at": "2026-04-12T14:00:00+05:30",
            "host_email": "sai@leadle.in",
            "attendees": [{"email": "alice@scalenut.com"}],
            "call_type": "discovery"
          },
          {
            "id": "fm2", "title": "Discovery — Acme Corp",
            "scheduled_at": "2026-04-22T15:00:00+05:30",
            "host_email": "sai@leadle.in",
            "attendees": [{"email": "carol@acme-corp.io"}],
            "call_type": "discovery"
          }
        ]
      }
    }
  }
}
```

### Task 2.6: Commit Phase 2

```bash
git add config/dashboard_rules.yaml config/dashboard_targets.yaml \
        config/dashboard_layout.yaml dashboard/compute/shared.py \
        tests/test_compute_shared.py tests/fixtures/sample_raw.json
git commit -m "$(cat <<'EOF'
Add compute foundation: configs, shared helpers, sample fixture

Three YAML configs (rules, targets, layout) per spec §8.
Shared helpers (pct_diff, pacing_status, days_between, in_window)
with pytest coverage. Hand-crafted minimal fixture in tests/fixtures/
for compute module TDD.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Phase 3 — Per-page compute modules

**Purpose:** Implement the deterministic analytics for each tab. TDD against the fixture.

### Task 3.1: TDD `compute/page1_revenue.py`

**Files:**
- Create: `dashboard/compute/page1_revenue.py`
- Create: `tests/test_compute_page1.py`

- [ ] **Step 1: Write failing tests for §01 Goal Snapshot**

```python
# tests/test_compute_page1.py
import json
from datetime import date
from pathlib import Path
import pytest
from dashboard.compute.windows import resolve_window
from dashboard.compute.page1_revenue import compute


@pytest.fixture
def raw():
    return json.loads(
        (Path(__file__).parent / "fixtures" / "sample_raw.json").read_text()
    )


@pytest.fixture
def rules():
    return {"rotting_deal_days": 14, "stalled_lead_days": 5, "followup_gap_days": 5,
            "outreach_min_sends": 10, "anomaly_pct_threshold": 30,
            "hygiene": {"require_owner": True, "require_source": True, "require_lifecycle": True}}


@pytest.fixture
def targets():
    return {"annual": {"goal_amount": 319000, "goal_currency": "USD",
                       "target_date": "2026-10-31"},
            "monthly": {"target_amount": 61800, "target_currency": "USD"},
            "pipeline_coverage": {"ratio_target": 3.0, "ratio_warning_below": 2.0,
                                  "ratio_critical_below": 1.0}}


@pytest.fixture
def window():
    return resolve_window("current-month", date(2026, 5, 9))


def test_goal_snapshot_ytd_revenue(raw, rules, targets, window):
    out = compute(raw, rules, targets, window)
    # Closed-won YTD = single Acme deal at $12,000 (closedate 2026-04-28, in 2026 calendar)
    assert out["goal_snapshot"]["ytd_revenue"] == 12000
    assert out["goal_snapshot"]["goal_amount"] == 319000
    assert out["goal_snapshot"]["pct_of_goal"] == pytest.approx(12000 / 319000 * 100, rel=1e-3)


def test_monthly_control_pipeline_coverage(raw, rules, targets, window):
    out = compute(raw, rules, targets, window)
    # Open pipeline = $5K (Scalenut) + $8K (QuoDeck) = $13K
    # Monthly target = $61,800 → coverage = 13000 / 61800 ≈ 0.21
    assert out["monthly_control"]["open_pipeline"] == 13000
    assert out["monthly_control"]["pipeline_coverage_ratio"] == pytest.approx(13000 / 61800, rel=1e-3)


def test_funnel_stage_counts(raw, rules, targets, window):
    out = compute(raw, rules, targets, window)
    # 1 discovery, 1 proposal, 1 closedwon
    counts = out["funnel"]["stage_counts"]
    assert counts.get("discovery") == 1
    assert counts.get("proposal") == 1
    assert counts.get("closedwon") == 1


def test_hygiene_finds_no_issues_in_clean_fixture(raw, rules, targets, window):
    out = compute(raw, rules, targets, window)
    # Fixture deals/contacts all have owner, source, lifecycle → no issues
    assert out["hygiene"]["missing_source_count"] == 0
    assert out["hygiene"]["missing_owner_count"] == 0


def test_channel_performance_groups_by_source(raw, rules, targets, window):
    out = compute(raw, rules, targets, window)
    channels = {c["channel"]: c for c in out["channel_performance"]["channels"]}
    assert "ORGANIC_SEARCH" in channels
    assert "REFERRALS" in channels
    assert channels["REFERRALS"]["closed_won_revenue"] == 12000
```

- [ ] **Step 2: Run — FAIL with ImportError or NotImplementedError**

```bash
pytest tests/test_compute_page1.py -v
```

- [ ] **Step 3: Implement `compute/page1_revenue.py`**

```python
"""Page 1 — Revenue Engine compute.

Section-by-section deterministic analytics. Window-aware where applicable,
point-in-time for hygiene. Output is a dict mapping section keys to computed values.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Any

from dashboard.compute.shared import pacing_status, pct_diff
from dashboard.compute.windows import WindowSpec


def _parse_iso_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def compute(raw: dict, rules: dict, targets: dict, window: WindowSpec) -> dict[str, Any]:
    hubspot = raw["sources"]["hubspot"]
    if not hubspot.get("available"):
        return {"unavailable": True, "reason": hubspot.get("error", "HubSpot unavailable")}

    deals = hubspot["data"].get("deals", [])
    contacts = hubspot["data"].get("contacts", [])
    owners = hubspot["data"].get("owners", [])

    return {
        "goal_snapshot": _goal_snapshot(deals, targets),
        "monthly_control": _monthly_control(deals, targets),
        "execution": _execution_panel(deals, contacts, raw, window),
        "channel_performance": _channel_performance(deals, window),
        "channel_economics": _channel_economics(deals, window),
        "funnel": _funnel(deals, window),
        "accountability": _accountability(deals, owners, window),
        "hygiene": _hygiene(deals, contacts, rules["hygiene"]),
        "forward_motion_input": _forward_motion_input(deals, contacts, rules, window),
    }


def _goal_snapshot(deals: list[dict], targets: dict) -> dict:
    goal = targets["annual"]["goal_amount"]
    target_date = date.fromisoformat(targets["annual"]["target_date"])
    today = date.today()
    fy_start = date(today.year if today.month >= 4 else today.year - 1, 4, 1)
    ytd_revenue = sum(
        d.get("amount", 0) for d in deals
        if d.get("dealstage") == "closedwon"
        and (cd := _parse_iso_date(d.get("closedate")))
        and fy_start <= cd <= today
    )
    pct_of_goal = (ytd_revenue / goal * 100) if goal > 0 else 0
    months_remaining = max(1, (target_date.year - today.year) * 12 + (target_date.month - today.month))
    monthly_needed = (goal - ytd_revenue) / months_remaining if months_remaining > 0 else 0
    return {
        "ytd_revenue": ytd_revenue,
        "goal_amount": goal,
        "goal_currency": targets["annual"]["goal_currency"],
        "pct_of_goal": pct_of_goal,
        "revenue_remaining": goal - ytd_revenue,
        "monthly_needed": monthly_needed,
        "run_rate_status": "critical" if pct_of_goal < 30 else
                           "warning" if pct_of_goal < 60 else "on-track",
    }


def _monthly_control(deals: list[dict], targets: dict) -> dict:
    today = date.today()
    month_start = date(today.year, today.month, 1)
    monthly_target = targets["monthly"]["target_amount"]
    mtd_revenue = sum(
        d.get("amount", 0) for d in deals
        if d.get("dealstage") == "closedwon"
        and (cd := _parse_iso_date(d.get("closedate")))
        and month_start <= cd <= today
    )
    open_pipeline = sum(
        d.get("amount", 0) for d in deals
        if d.get("dealstage") not in ("closedwon", "closedlost")
    )
    coverage = open_pipeline / monthly_target if monthly_target > 0 else 0
    cov_target = targets["pipeline_coverage"]["ratio_target"]
    cov_warning = targets["pipeline_coverage"]["ratio_warning_below"]
    cov_critical = targets["pipeline_coverage"]["ratio_critical_below"]
    coverage_status = ("critical" if coverage < cov_critical else
                       "warning" if coverage < cov_warning else
                       "on-track")
    return {
        "mtd_revenue": mtd_revenue,
        "monthly_target": monthly_target,
        "pct_target_achieved": (mtd_revenue / monthly_target * 100) if monthly_target > 0 else 0,
        "monthly_gap": monthly_target - mtd_revenue,
        "open_pipeline": open_pipeline,
        "pipeline_coverage_ratio": coverage,
        "pipeline_coverage_status": coverage_status,
        "closed_won_count": sum(
            1 for d in deals if d.get("dealstage") == "closedwon"
            and (cd := _parse_iso_date(d.get("closedate")))
            and month_start <= cd <= today
        ),
    }


def _execution_panel(deals: list[dict], contacts: list[dict], raw: dict,
                     window: WindowSpec) -> dict:
    s, e = window.start, window.end
    new_leads = sum(1 for c in contacts
                    if (cd := _parse_iso_date(c.get("createdate")))
                    and s <= cd <= e)
    qualified = sum(1 for c in contacts
                    if c.get("lifecyclestage") in ("salesqualifiedlead", "marketingqualifiedlead")
                    and (cd := _parse_iso_date(c.get("createdate")))
                    and s <= cd <= e)
    fathom = raw["sources"].get("fathom", {})
    meetings = []
    if fathom.get("available"):
        meetings = [
            m for m in fathom["data"].get("meetings", [])
            if (md := _parse_iso_date(m.get("scheduled_at")))
            and s <= md <= e
        ]
    opportunities = sum(1 for d in deals
                        if (cd := _parse_iso_date(d.get("createdate")))
                        and s <= cd <= e)
    proposals = sum(1 for d in deals
                    if d.get("dealstage") == "proposal"
                    and (cd := _parse_iso_date(d.get("createdate")))
                    and s <= cd <= e)
    pipeline_added = sum(d.get("amount", 0) for d in deals
                         if (cd := _parse_iso_date(d.get("createdate")))
                         and s <= cd <= e)
    return {
        "window_label": window.label,
        "new_leads": new_leads,
        "qualified_leads": qualified,
        "qualification_rate": (qualified / new_leads * 100) if new_leads > 0 else 0,
        "meetings_booked": len(meetings),
        "opportunities": opportunities,
        "proposals_sent": proposals,
        "pipeline_added": pipeline_added,
    }


def _channel_performance(deals: list[dict], window: WindowSpec) -> dict:
    by_channel = defaultdict(lambda: {"deal_count": 0, "pipeline": 0, "closed_won_revenue": 0})
    for d in deals:
        ch = d.get("hs_analytics_source", "UNKNOWN")
        by_channel[ch]["deal_count"] += 1
        if d.get("dealstage") not in ("closedwon", "closedlost"):
            by_channel[ch]["pipeline"] += d.get("amount", 0)
        elif d.get("dealstage") == "closedwon":
            by_channel[ch]["closed_won_revenue"] += d.get("amount", 0)
    return {"channels": [{"channel": k, **v} for k, v in by_channel.items()]}


def _channel_economics(deals: list[dict], window: WindowSpec) -> dict:
    perf = _channel_performance(deals, window)
    out = []
    for ch in perf["channels"]:
        won_count = sum(
            1 for d in deals
            if d.get("hs_analytics_source") == ch["channel"]
            and d.get("dealstage") == "closedwon"
        )
        acv = ch["closed_won_revenue"] / won_count if won_count > 0 else None
        out.append({**ch, "won_count": won_count, "acv": acv})
    return {"channels": out}


def _funnel(deals: list[dict], window: WindowSpec) -> dict:
    stage_order = ["new", "qualified", "discovery", "proposal", "negotiation", "closedwon"]
    counts = defaultdict(int)
    for d in deals:
        stage = d.get("dealstage", "")
        if stage in stage_order:
            counts[stage] += 1
    conversions = []
    for i in range(len(stage_order) - 1):
        a = counts.get(stage_order[i], 0)
        b = counts.get(stage_order[i + 1], 0)
        rate = (b / a * 100) if a > 0 else None
        conversions.append({"from_stage": stage_order[i], "to_stage": stage_order[i + 1],
                            "from_count": a, "to_count": b, "conversion_pct": rate})
    return {"stage_counts": dict(counts), "conversions": conversions}


def _accountability(deals: list[dict], owners: list[dict], window: WindowSpec) -> dict:
    owner_map = {o["id"]: o for o in owners}
    by_owner = defaultdict(lambda: {"deal_count": 0, "pipeline": 0, "closed_won": 0})
    for d in deals:
        oid = d.get("hubspot_owner_id")
        if oid:
            by_owner[oid]["deal_count"] += 1
            if d.get("dealstage") not in ("closedwon", "closedlost"):
                by_owner[oid]["pipeline"] += d.get("amount", 0)
            elif d.get("dealstage") == "closedwon":
                by_owner[oid]["closed_won"] += d.get("amount", 0)
    rows = []
    for oid, stats in by_owner.items():
        owner = owner_map.get(oid, {"firstName": "?", "lastName": ""})
        rows.append({
            "owner_id": oid,
            "owner_name": f"{owner.get('firstName','')} {owner.get('lastName','')}".strip(),
            **stats,
        })
    return {"owners": rows}


def _hygiene(deals: list[dict], contacts: list[dict], rules: dict) -> dict:
    issues = []
    missing_source_count = 0
    missing_owner_count = 0
    missing_lifecycle_count = 0
    for d in deals:
        if rules.get("require_owner") and not d.get("hubspot_owner_id"):
            missing_owner_count += 1
            issues.append({"type": "missing_owner", "entity": "deal",
                           "id": d.get("id"), "name": d.get("dealname")})
        if rules.get("require_source") and not d.get("hs_analytics_source"):
            missing_source_count += 1
            issues.append({"type": "missing_source", "entity": "deal",
                           "id": d.get("id"), "name": d.get("dealname")})
    for c in contacts:
        if rules.get("require_lifecycle") and not c.get("lifecyclestage"):
            missing_lifecycle_count += 1
            issues.append({"type": "missing_lifecycle", "entity": "contact",
                           "id": c.get("id"), "email": c.get("email")})
        if rules.get("require_source") and not c.get("hs_analytics_source"):
            missing_source_count += 1
            issues.append({"type": "missing_source", "entity": "contact",
                           "id": c.get("id"), "email": c.get("email")})
    return {
        "missing_source_count": missing_source_count,
        "missing_owner_count": missing_owner_count,
        "missing_lifecycle_count": missing_lifecycle_count,
        "total_issues": len(issues),
        "issues": issues,
    }


def _forward_motion_input(deals: list[dict], contacts: list[dict],
                          rules: dict, window: WindowSpec) -> dict:
    """Aggregate rule outputs that the Forward Motion agent consumes."""
    today = date.today()
    rotting_deals = [
        {"id": d.get("id"), "name": d.get("dealname"), "amount": d.get("amount"),
         "stage": d.get("dealstage"), "last_activity": d.get("last_activity_date"),
         "days_stale": (today - la).days if (la := _parse_iso_date(d.get("last_activity_date"))) else None}
        for d in deals
        if d.get("dealstage") not in ("closedwon", "closedlost")
        and (la := _parse_iso_date(d.get("last_activity_date")))
        and (today - la).days > rules["rotting_deal_days"]
    ]
    return {
        "rotting_deals": sorted(rotting_deals, key=lambda x: x.get("days_stale") or 0, reverse=True),
        "rotting_pipeline_at_risk": sum(d.get("amount") or 0 for d in rotting_deals),
    }
```

- [ ] **Step 4: Run — tests should pass**

```bash
pytest tests/test_compute_page1.py -v
```
Expected: all 5 tests PASS.

### Task 3.2: TDD `compute/page2_activity.py`

**Files:**
- Create: `dashboard/compute/page2_activity.py`
- Create: `tests/test_compute_page2.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_compute_page2.py
import json
from datetime import date
from pathlib import Path
import pytest
from dashboard.compute.page2_activity import compute


@pytest.fixture
def raw():
    return json.loads(
        (Path(__file__).parent / "fixtures" / "sample_raw.json").read_text()
    )


@pytest.fixture
def rules():
    return {"rotting_deal_days": 14, "stalled_lead_days": 5}


def test_rotting_deals_picks_up_old_activity(raw, rules):
    out = compute(raw, rules, today=date(2026, 5, 9))
    # Scalenut last activity 2026-03-08 → today 2026-05-09 → 62 days stale
    rotting = out["rotting_deals"]
    assert any(d["name"] == "Scalenut" for d in rotting)
    scalenut = next(d for d in rotting if d["name"] == "Scalenut")
    assert scalenut["days_stale"] == 62


def test_rotting_deals_excludes_won(raw, rules):
    out = compute(raw, rules, today=date(2026, 5, 9))
    assert not any(d["name"] == "Acme Won" for d in out["rotting_deals"])


def test_pipeline_at_risk_sums_amounts(raw, rules):
    out = compute(raw, rules, today=date(2026, 5, 9))
    # Scalenut 5000 stale; QuoDeck 8000 (last_activity 2026-04-20 → 19 days stale)
    assert out["pipeline_at_risk"] == 13000


def test_stalled_leads_filters_by_reply_status(raw, rules):
    out = compute(raw, rules, today=date(2026, 5, 9))
    # Alice replied 2026-04-15, lifecycle=lead, days_since_reply=24 → stalled
    stalled = out["stalled_leads"]
    assert any(s["email"] == "alice@scalenut.com" for s in stalled)


def test_kpi_strip_counts(raw, rules):
    out = compute(raw, rules, today=date(2026, 5, 9))
    assert out["kpi"]["rotting_count"] == 2
    assert out["kpi"]["stalled_count"] >= 1
```

- [ ] **Step 2: Run — FAIL**

```bash
pytest tests/test_compute_page2.py -v
```

- [ ] **Step 3: Implement `compute/page2_activity.py`**

```python
"""Page 2 — Activity & Rot. Point-in-time current state. Not window-aware."""
from __future__ import annotations

from datetime import date
from typing import Any

from dashboard.compute.page1_revenue import _parse_iso_date


def compute(raw: dict, rules: dict, today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    hubspot = raw["sources"].get("hubspot", {})
    if not hubspot.get("available"):
        return {"unavailable": True}

    deals = hubspot["data"].get("deals", [])
    contacts = hubspot["data"].get("contacts", [])

    rotting = _rotting_deals(deals, rules, today)
    stalled = _stalled_leads(contacts, raw, rules, today)
    return {
        "rotting_deals": rotting,
        "pipeline_at_risk": sum(d["amount"] or 0 for d in rotting),
        "stalled_leads": stalled,
        "kpi": {
            "rotting_count": len(rotting),
            "stalled_count": len(stalled),
            "stalled_30d_plus": sum(1 for s in stalled if (s.get("days_stalled") or 0) >= 30),
            "most_critical_deal": rotting[0] if rotting else None,
        },
    }


def _rotting_deals(deals: list[dict], rules: dict, today: date) -> list[dict]:
    out = []
    for d in deals:
        if d.get("dealstage") in ("closedwon", "closedlost"):
            continue
        la = _parse_iso_date(d.get("last_activity_date"))
        if not la:
            continue
        days_stale = (today - la).days
        if days_stale > rules["rotting_deal_days"]:
            out.append({
                "id": d.get("id"), "name": d.get("dealname"),
                "amount": d.get("amount"), "stage": d.get("dealstage"),
                "last_activity": d.get("last_activity_date"),
                "days_stale": days_stale,
            })
    return sorted(out, key=lambda x: x["days_stale"], reverse=True)


def _stalled_leads(contacts: list[dict], raw: dict, rules: dict, today: date) -> list[dict]:
    """Cross-tool join: outreach replies + HubSpot lifecycle != Meeting Booked."""
    replied_contact_ids = set()
    for source in ("lemlist", "aimfox", "instantly"):
        src = raw["sources"].get(source, {})
        if not src.get("available"):
            continue
        for lead in src["data"].get("leads", []):
            if lead.get("reply_status") in ("positive", "neutral", "replied"):
                if hcid := lead.get("hubspot_contact_id"):
                    replied_contact_ids.add(hcid)
    out = []
    for c in contacts:
        if c["id"] not in replied_contact_ids:
            continue
        if c.get("lifecyclestage") in ("opportunity", "customer", "salesqualifiedlead"):
            continue  # already advanced to meeting/opportunity
        la = _parse_iso_date(c.get("last_activity_date"))
        if not la:
            continue
        days = (today - la).days
        if days > rules["stalled_lead_days"]:
            out.append({"id": c["id"], "email": c.get("email"),
                        "lifecycle": c.get("lifecyclestage"),
                        "last_activity": c.get("last_activity_date"),
                        "days_stalled": days})
    return sorted(out, key=lambda x: x["days_stalled"], reverse=True)
```

- [ ] **Step 4: Run — PASS**

```bash
pytest tests/test_compute_page2.py -v
```

### Task 3.3: TDD `compute/page3_actions.py`

**Files:**
- Create: `dashboard/compute/page3_actions.py`
- Create: `tests/test_compute_page3.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_compute_page3.py
import json
from datetime import date
from pathlib import Path
import pytest
from dashboard.compute.windows import resolve_window
from dashboard.compute.page3_actions import compute


@pytest.fixture
def raw():
    return json.loads(
        (Path(__file__).parent / "fixtures" / "sample_raw.json").read_text()
    )


@pytest.fixture
def rules():
    return {"fathom_gap": {"attendee_match_strategy": "email_domain_first",
                           "fuzzy_match_threshold": 85}}


def test_fathom_gap_finds_acme_corp_with_no_deal(raw, rules):
    # fm2: Acme Corp meeting 2026-04-22; no deal in HubSpot for "acme-corp.io"
    window = resolve_window("month-april", date(2026, 5, 9))
    out = compute(raw, rules, window)
    gap_companies = [g["company"] for g in out["fathom_gap"]]
    assert any("Acme" in c or "acme" in c.lower() for c in gap_companies)


def test_fathom_gap_excludes_scalenut_with_existing_deal(raw, rules):
    window = resolve_window("month-april", date(2026, 5, 9))
    out = compute(raw, rules, window)
    # Scalenut has a deal (id=1001), so it should NOT be in the gap
    assert not any("Scalenut" == g["company"] for g in out["fathom_gap"])


def test_fathom_gap_window_filters_meetings(raw, rules):
    # Window = May 2026 → no Fathom meetings in fixture (both are April)
    window = resolve_window("month-may", date(2026, 5, 9))
    out = compute(raw, rules, window)
    assert out["fathom_gap"] == []
```

- [ ] **Step 2: Run — FAIL**

```bash
pytest tests/test_compute_page3.py -v
```

- [ ] **Step 3: Implement `compute/page3_actions.py`**

```python
"""Page 3 — Sales Actions. Fathom Gap detection (SOP is static template-only)."""
from __future__ import annotations

from datetime import date
from typing import Any

from dashboard.compute.page1_revenue import _parse_iso_date
from dashboard.compute.windows import WindowSpec


def compute(raw: dict, rules: dict, window: WindowSpec) -> dict[str, Any]:
    fathom = raw["sources"].get("fathom", {})
    hubspot = raw["sources"].get("hubspot", {})
    if not fathom.get("available") or not hubspot.get("available"):
        return {"fathom_gap": [], "unavailable": True}

    meetings = fathom["data"].get("meetings", [])
    deals = hubspot["data"].get("deals", [])
    companies = hubspot["data"].get("companies", [])
    domain_to_company = {c["domain"].lower(): c for c in companies if c.get("domain")}
    company_id_to_deals = {}
    for d in deals:
        cid = d.get("company_id")
        if cid:
            company_id_to_deals.setdefault(cid, []).append(d)

    gap = []
    for m in meetings:
        scheduled = _parse_iso_date(m.get("scheduled_at"))
        if not scheduled or not (window.start <= scheduled <= window.end):
            continue
        attendee_emails = [a.get("email", "") for a in m.get("attendees", [])]
        external = [e for e in attendee_emails
                    if e and not e.endswith("@leadle.in")]
        if not external:
            continue
        domain = external[0].split("@")[-1].lower() if "@" in external[0] else ""
        company = domain_to_company.get(domain)
        if company:
            cid = company["id"]
            if cid in company_id_to_deals:
                continue  # has a deal, not a gap
        gap.append({
            "company": company["name"] if company else _company_from_email(external[0]),
            "contact_email": external[0],
            "last_call_date": scheduled.isoformat(),
            "call_type": m.get("call_type", "unknown"),
            "crm_state": "no deal" if not company else "company exists, no deal",
            "suggested_action_default": "Create deal in HubSpot · stage: Discovery",
        })
    return {"fathom_gap": gap, "gap_count": len(gap)}


def _company_from_email(email: str) -> str:
    if "@" not in email:
        return "Unknown"
    domain = email.split("@")[1]
    root = domain.split(".")[0]
    return root.capitalize()
```

- [ ] **Step 4: Run — PASS**

```bash
pytest tests/test_compute_page3.py -v
```

### Task 3.4: TDD `compute/page4_outreach.py`

**Files:**
- Create: `dashboard/compute/page4_outreach.py`
- Create: `tests/test_compute_page4.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_compute_page4.py
import json
from datetime import date
from pathlib import Path
import pytest
from dashboard.compute.windows import resolve_window
from dashboard.compute.page4_outreach import compute


@pytest.fixture
def raw():
    return json.loads(
        (Path(__file__).parent / "fixtures" / "sample_raw.json").read_text()
    )


@pytest.fixture
def rules():
    return {"outreach_min_sends": 10, "followup_gap_days": 5}


def test_lemlist_campaign_aggregates(raw, rules):
    window = resolve_window("current-month", date(2026, 5, 9))
    out = compute(raw, rules, window, today=date(2026, 5, 9))
    assert len(out["lemlist"]) == 1
    c = out["lemlist"][0]
    assert c["name"] == "RevOps Q2 Outbound"
    assert c["sends"] == 120
    assert c["replies"] == 8
    assert c["reply_rate_pct"] == pytest.approx(8 / 120 * 100, rel=1e-3)


def test_outreach_below_min_sends_excluded(raw, rules):
    rules2 = {**rules, "outreach_min_sends": 200}
    window = resolve_window("current-month", date(2026, 5, 9))
    out = compute(raw, rules2, window, today=date(2026, 5, 9))
    # All campaigns under 200 sends → excluded
    assert out["lemlist"] == []
    assert out["aimfox"] == []
    assert out["instantly"] == []


def test_followup_gap_lists_alice(raw, rules):
    window = resolve_window("current-month", date(2026, 5, 9))
    out = compute(raw, rules, window, today=date(2026, 5, 9))
    # Alice: lifecycle=lead, last_activity=2026-04-15, today=2026-05-09 → 24 days gap
    gap = out["followup_gap"]
    assert any(g["email"] == "alice@scalenut.com" for g in gap)
```

- [ ] **Step 2: Run — FAIL**

```bash
pytest tests/test_compute_page4.py -v
```

- [ ] **Step 3: Implement `compute/page4_outreach.py`**

```python
"""Page 4 — Outreach. Campaign metrics + follow-up gap."""
from __future__ import annotations

from datetime import date
from typing import Any

from dashboard.compute.page1_revenue import _parse_iso_date
from dashboard.compute.windows import WindowSpec


def compute(raw: dict, rules: dict, window: WindowSpec,
            today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    return {
        "lemlist": _campaigns(raw, "lemlist", rules),
        "aimfox": _campaigns(raw, "aimfox", rules),
        "instantly": _campaigns(raw, "instantly", rules),
        "followup_gap": _followup_gap(raw, rules, today),
    }


def _campaigns(raw: dict, source: str, rules: dict) -> list[dict]:
    src = raw["sources"].get(source, {})
    if not src.get("available"):
        return []
    out = []
    for c in src["data"].get("campaigns", []):
        stats = c.get("stats", {})
        sends = stats.get("sends", 0)
        if sends < rules["outreach_min_sends"]:
            continue
        replies = stats.get("replies", 0)
        meetings = stats.get("meetings", 0)
        out.append({
            "id": c.get("id"),
            "name": c.get("name"),
            "sends": sends,
            "replies": replies,
            "reply_rate_pct": (replies / sends * 100) if sends > 0 else 0,
            "meetings": meetings,
            "meeting_rate_pct": (meetings / sends * 100) if sends > 0 else 0,
        })
    return sorted(out, key=lambda x: x["reply_rate_pct"], reverse=True)


def _followup_gap(raw: dict, rules: dict, today: date) -> list[dict]:
    hubspot = raw["sources"].get("hubspot", {})
    if not hubspot.get("available"):
        return []
    out = []
    for c in hubspot["data"].get("contacts", []):
        if c.get("lifecyclestage") != "lead":
            continue
        la = _parse_iso_date(c.get("last_activity_date"))
        if not la:
            continue
        days = (today - la).days
        if days > rules["followup_gap_days"]:
            out.append({
                "id": c.get("id"),
                "email": c.get("email"),
                "last_activity": c.get("last_activity_date"),
                "days_since_activity": days,
            })
    return sorted(out, key=lambda x: x["days_since_activity"], reverse=True)
```

- [ ] **Step 4: Run — PASS**

```bash
pytest tests/test_compute_page4.py -v
```

### Task 3.5: Commit Phase 3

```bash
git add dashboard/compute/page1_revenue.py dashboard/compute/page2_activity.py \
        dashboard/compute/page3_actions.py dashboard/compute/page4_outreach.py \
        tests/test_compute_page1.py tests/test_compute_page2.py \
        tests/test_compute_page3.py tests/test_compute_page4.py
git commit -m "$(cat <<'EOF'
Add per-page compute modules with TDD coverage

page1_revenue: 9 sections (goal/monthly/execution/channel × 2/funnel/
  accountability/hygiene/forward-motion-input)
page2_activity: rotting deals + stalled leads (cross-tool join)
page3_actions: Fathom gap detection
page4_outreach: campaign aggregation + follow-up gap

All modules tested against tests/fixtures/sample_raw.json.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Phase 4 — Templates

**Purpose:** Build Jinja templates that match the dashboard mock structure. Every template uses defensive `| default("—")` for degraded states.

### Task 4.1: Extract CSS + create `base.html.j2`

**Files:**
- Create: `dashboard/templates/base.html.j2`

- [ ] **Step 1: Read CSS from the mock**

```bash
sed -n '1,500p' "/home/bhuvanesh/Downloads/leadle-dashboard-2026-05-04 (1).html" > /tmp/mock_head.html
```
Identify the `<style>...</style>` block. (Inline CSS is large — copy verbatim.)

- [ ] **Step 2: Write `base.html.j2`**

```jinja
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Leadle Revenue Engine Dashboard — {{ window.label }}</title>
<style>
{# Paste the entire <style>...</style> contents from the mock here #}
{# (Inline CSS — single-file output, no external assets) #}
</style>
</head>
<body>

<div class="tab-nav">
  <button class="tab-btn active" id="btn-page1" onclick="showTab('page1')">Revenue Engine</button>
  <button class="tab-btn" id="btn-page2" onclick="showTab('page2')">Activity &amp; Rot</button>
  <button class="tab-btn" id="btn-page3" onclick="showTab('page3')">Sales Actions</button>
  <button class="tab-btn" id="btn-page4" onclick="showTab('page4')">Outreach</button>
</div>

<div id="page1" class="tab-content active">
  {% include "page1_revenue.html.j2" %}
</div>

<div id="page2" class="tab-content">
  {% include "page2_activity.html.j2" %}
</div>

<div id="page3" class="tab-content">
  {% include "page3_actions.html.j2" %}
</div>

<div id="page4" class="tab-content">
  {% include "page4_outreach.html.j2" %}
</div>

<footer class="footer">
  <span>Leadle RevOps · Confidential</span>
  <span>{{ window.label }} · Rendered {{ rendered_at }}</span>
  {% if degraded_sections %}
    <span style="color: #d97706;">⚠ {{ degraded_sections|length }} degraded</span>
  {% endif %}
</footer>

<script>
function showTab(id) {
  document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  document.getElementById('btn-' + id).classList.add('active');
}
</script>
</body>
</html>
```

### Task 4.2: Create per-tab templates (faithful to mock structure)

**Files:**
- Create: `dashboard/templates/page1_revenue.html.j2`
- Create: `dashboard/templates/page2_activity.html.j2`
- Create: `dashboard/templates/page3_actions.html.j2`
- Create: `dashboard/templates/page4_outreach.html.j2`
- Create: `dashboard/templates/_sop_inbound.html.j2`
- Create: `dashboard/templates/_sop_outbound.html.j2`

- [ ] **Step 1: Page 1 — Revenue Engine template (sketch — full version transcribes mock §01-09)**

`page1_revenue.html.j2`:
```jinja
{% set p = analytics.page1 %}
<header class="header">
  <div>
    <div class="brand-row">
      <div class="logo">L</div>
      <div class="brand-meta">Leadle · RevOps Command</div>
    </div>
    <h1 class="title display">Revenue Engine Dashboard</h1>
  </div>
</header>

{# 01 — Goal Snapshot #}
<section class="section">
  <div class="section-head">
    <div>
      <div class="section-num">01 — Goal Snapshot</div>
      <h2 class="section-title">Are we on track to hit the {{ p.goal_snapshot.goal_currency }}{{ "{:,}".format(p.goal_snapshot.goal_amount) | default('—') }} goal?</h2>
    </div>
  </div>
  <div class="kpi-grid cols-5">
    <div class="kpi">
      <div class="kpi-label">Revenue Goal</div>
      <div class="kpi-value mono">${{ "{:,}".format(p.goal_snapshot.goal_amount) }}</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">YTD Revenue Closed</div>
      <div class="kpi-value mono">${{ "{:,}".format(p.goal_snapshot.ytd_revenue | default(0)) }}</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">% Goal Achieved</div>
      <div class="kpi-value mono">{{ "%.1f"|format(p.goal_snapshot.pct_of_goal | default(0)) }}%</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Revenue Remaining</div>
      <div class="kpi-value mono">${{ "{:,}".format(p.goal_snapshot.revenue_remaining | default(0)) }}</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Run-Rate Status</div>
      <div class="kpi-value">
        <span class="status-pill {{ p.goal_snapshot.run_rate_status }}">{{ p.goal_snapshot.run_rate_status | title }}</span>
      </div>
    </div>
  </div>
</section>

{# 02 — Monthly Control Panel — transcribe similarly with kpi-grid cols-4 #}
{# 03 — Execution Panel — kpi-grid cols-4 with new_leads, qualified, meetings, opps, etc. #}
{# 04 — Channel Performance — table over p.channel_performance.channels #}
{# 05 — Channel Economics — three side-by-side cards #}

{# 06 — Funnel — narrated #}
<section class="section">
  <div class="section-head">
    <div class="section-num">06 — Funnel</div>
    <h2 class="section-title">Where the funnel leaks</h2>
  </div>
  <table class="funnel-table">
    <thead><tr><th>From</th><th>To</th><th>Count</th><th>Conv %</th></tr></thead>
    <tbody>
      {% for c in p.funnel.conversions %}
      <tr>
        <td>{{ c.from_stage }}</td>
        <td>{{ c.to_stage }}</td>
        <td>{{ c.from_count }} → {{ c.to_count }}</td>
        <td>{{ "%.1f"|format(c.conversion_pct) if c.conversion_pct is not none else '—' }}%</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% if narratives.funnel_leak and not narratives.funnel_leak.degraded %}
  <div class="narrative">
    <h3>{{ narratives.funnel_leak.headline }}</h3>
    <p>{{ narratives.funnel_leak.explanation }}</p>
  </div>
  {% else %}
  <div class="narrative degraded">
    <span class="badge">narrative unavailable</span>
  </div>
  {% endif %}
</section>

{# 07 — Accountability — owners table #}

{# 08 — Hygiene — narrated #}
<section class="section">
  <div class="section-num">08 — Hygiene</div>
  <h2 class="section-title">Data quality alerts</h2>
  <div>{{ p.hygiene.total_issues }} total issues</div>
  {% if narratives.hygiene and not narratives.hygiene.degraded %}
    {% for cat in narratives.hygiene.categories %}
      <div class="hygiene-cat {{ cat.severity }}">
        <h4>{{ cat.title }}</h4>
        <p>{{ cat.summary }}</p>
      </div>
    {% endfor %}
  {% endif %}
</section>

{# 09 — Forward Motion — narrated #}
<section class="section">
  <div class="section-num">09 — Forward Motion</div>
  <h2 class="section-title">This Window's Revenue Actions</h2>
  {% if narratives.forward_motion and not narratives.forward_motion.degraded %}
    <div class="actions-grid">
      {% for action in narratives.forward_motion.commitments %}
      <div class="action-card">
        <div class="action-num">{{ "%02d"|format(loop.index) }}</div>
        <div class="action-owner">{{ action.owner }}</div>
        <div class="action-text">{{ action.text|safe }}</div>
      </div>
      {% endfor %}
    </div>
  {% else %}
    <div class="actions-grid degraded">
      <span class="badge">narrative unavailable — top items past threshold:</span>
      {% for d in p.forward_motion_input.rotting_deals[:5] %}
      <div class="action-card">{{ d.name }} · {{ d.days_stale }}d stale · ${{ d.amount }}</div>
      {% endfor %}
    </div>
  {% endif %}
</section>
```

(Full transcription of §02–07 follows the same shape — visit each section in the mock and translate static-data uses into `{{ p.<section>.<field> }}` expressions.)

- [ ] **Step 2: Page 2 — Activity & Rot template**

`page2_activity.html.j2`:
```jinja
{% set p = analytics.page2 %}
<header class="header">
  <h1 class="title display">Activity &amp; Rot Monitor</h1>
</header>

<section class="section">
  <div class="kpi-grid cols-4">
    <div class="kpi">
      <div class="kpi-label">Rotting Deals</div>
      <div class="kpi-value mono">{{ p.kpi.rotting_count | default(0) }}</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Pipeline at Risk</div>
      <div class="kpi-value mono">${{ "{:,}".format(p.pipeline_at_risk | default(0)) }}</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Stalled Leads</div>
      <div class="kpi-value mono">{{ p.kpi.stalled_count | default(0) }}</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Most Critical Deal</div>
      <div class="kpi-value">{{ (p.kpi.most_critical_deal.name if p.kpi.most_critical_deal else '—') }}</div>
    </div>
  </div>
</section>

<section class="section">
  <h2 class="section-title">Rotting Deals — open, no recent activity</h2>
  <table>
    <thead><tr><th>Deal</th><th>Stage</th><th>Last Activity</th><th>Days Stale</th><th>Amount</th></tr></thead>
    <tbody>
      {% for d in p.rotting_deals %}
      <tr><td>{{ d.name }}</td><td>{{ d.stage }}</td><td>{{ d.last_activity }}</td>
          <td>{{ d.days_stale }}</td><td>${{ "{:,}".format(d.amount or 0) }}</td></tr>
      {% endfor %}
    </tbody>
  </table>
</section>

<section class="section">
  <h2 class="section-title">Stalled Leads — replied, no meeting booked</h2>
  <table>
    <thead><tr><th>Email</th><th>Lifecycle</th><th>Last Activity</th><th>Days</th></tr></thead>
    <tbody>
      {% for s in p.stalled_leads %}
      <tr><td>{{ s.email }}</td><td>{{ s.lifecycle }}</td>
          <td>{{ s.last_activity }}</td><td>{{ s.days_stalled }}</td></tr>
      {% endfor %}
    </tbody>
  </table>
</section>
```

- [ ] **Step 3: Page 3 — Sales Actions template**

`page3_actions.html.j2`:
```jinja
{% set p = analytics.page3 %}
<header class="header">
  <h1 class="title display">Sales Actions</h1>
</header>

<section class="section">
  <h2>Sales Pipeline SOP</h2>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;">
    {% include "_sop_inbound.html.j2" %}
    {% include "_sop_outbound.html.j2" %}
  </div>
</section>

<section class="section">
  <h2>{{ window.label }} Fathom Gap — Missing CRM Records</h2>
  <p>{{ p.gap_count }} companies with calls in window but no deal in HubSpot.</p>
  <table>
    <thead><tr><th>Company</th><th>Contact</th><th>Last Call</th><th>Type</th><th>CRM State</th><th>Action Needed</th></tr></thead>
    <tbody>
      {% for g in p.fathom_gap %}
      <tr>
        <td>{{ g.company }}</td>
        <td>{{ g.contact_email }}</td>
        <td>{{ g.last_call_date }}</td>
        <td>{{ g.call_type }}</td>
        <td>{{ g.crm_state }}</td>
        <td>
          {% if narratives.fathom_gap and not narratives.fathom_gap.degraded
              and narratives.fathom_gap.actions[loop.index0] %}
            {{ narratives.fathom_gap.actions[loop.index0].action }}
          {% else %}
            {{ g.suggested_action_default }}
          {% endif %}
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</section>
```

- [ ] **Step 4: SOP partials (static, hard-coded)**

`_sop_inbound.html.j2`:
```jinja
<div class="sop-card">
  <span class="badge inbound">Inbound</span>
  <h3>Web Form / Demo Request</h3>
  <ol>
    <li>Contact submits form → HubSpot captures contact (source = Web Form)</li>
    <li>Auto-create Lead record → Lead pipeline → New Lead stage. Assign to Sai.</li>
    <li>Meeting booked → Advance lead, create Deal in Meeting Booked stage.</li>
  </ol>
</div>
```

`_sop_outbound.html.j2`:
```jinja
<div class="sop-card">
  <span class="badge outbound">Outbound</span>
  <h3>LinkedIn / Email Sequence</h3>
  <ol>
    <li>Prospect in sequence (LinkedIn or email outreach active)</li>
    <li>Positive / Neutral reply received</li>
    <li>Auto-create Lead record → Assign to Sai.</li>
    <li>Meeting booked → Advance lead, create Deal in Meeting Booked stage.</li>
  </ol>
</div>
```

- [ ] **Step 5: Page 4 — Outreach template**

`page4_outreach.html.j2`:
```jinja
{% set p = analytics.page4 %}
<header class="header">
  <h1 class="title display">Outreach</h1>
</header>

{% for source_label, source_key in [('Lemlist', 'lemlist'), ('Aimfox — LinkedIn', 'aimfox'), ('Instantly — Email', 'instantly')] %}
<section class="section">
  <h2>{{ source_label }} Campaigns</h2>
  <table>
    <thead><tr><th>Campaign</th><th>Sends</th><th>Replies</th><th>Reply Rate</th><th>Meetings</th></tr></thead>
    <tbody>
      {% for c in p[source_key] %}
      <tr>
        <td>{{ c.name }}</td>
        <td>{{ c.sends }}</td>
        <td>{{ c.replies }}</td>
        <td>{{ "%.1f"|format(c.reply_rate_pct) }}%</td>
        <td>{{ c.meetings }}</td>
      </tr>
      {% else %}
      <tr><td colspan="5">No campaigns above min-sends threshold.</td></tr>
      {% endfor %}
    </tbody>
  </table>
</section>
{% endfor %}

<section class="section">
  <h2>Follow-up Gap</h2>
  <table>
    <thead><tr><th>Email</th><th>Last Activity</th><th>Days Since</th></tr></thead>
    <tbody>
      {% for g in p.followup_gap %}
      <tr><td>{{ g.email }}</td><td>{{ g.last_activity }}</td><td>{{ g.days_since_activity }}</td></tr>
      {% endfor %}
    </tbody>
  </table>
</section>
```

### Task 4.3: Test templates render

**Files:**
- Create: `tests/test_templates.py`

- [ ] **Step 1: Write rendering test**

```python
# tests/test_templates.py
import json
from datetime import date
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, StrictUndefined


@pytest.fixture
def env():
    return Environment(
        loader=FileSystemLoader("dashboard/templates"),
        undefined=StrictUndefined,
        autoescape=True,
    )


@pytest.fixture
def context():
    return {
        "analytics": {
            "page1": {
                "goal_snapshot": {"ytd_revenue": 12000, "goal_amount": 319000,
                                  "goal_currency": "USD", "pct_of_goal": 3.76,
                                  "revenue_remaining": 307000, "monthly_needed": 61400,
                                  "run_rate_status": "critical"},
                "monthly_control": {"mtd_revenue": 0, "monthly_target": 61800,
                                    "pct_target_achieved": 0, "monthly_gap": 61800,
                                    "open_pipeline": 13000, "pipeline_coverage_ratio": 0.21,
                                    "pipeline_coverage_status": "critical", "closed_won_count": 0},
                "execution": {"window_label": "May 2026", "new_leads": 2, "qualified_leads": 1,
                              "qualification_rate": 50.0, "meetings_booked": 2,
                              "opportunities": 1, "proposals_sent": 0, "pipeline_added": 0},
                "channel_performance": {"channels": [{"channel": "ORGANIC_SEARCH", "deal_count": 1,
                                                      "pipeline": 5000, "closed_won_revenue": 0}]},
                "channel_economics": {"channels": []},
                "funnel": {"stage_counts": {"discovery": 1, "proposal": 1, "closedwon": 1},
                           "conversions": [{"from_stage": "discovery", "to_stage": "proposal",
                                            "from_count": 1, "to_count": 1, "conversion_pct": 100.0}]},
                "accountability": {"owners": []},
                "hygiene": {"missing_source_count": 0, "missing_owner_count": 0,
                            "missing_lifecycle_count": 0, "total_issues": 0, "issues": []},
                "forward_motion_input": {"rotting_deals": [], "rotting_pipeline_at_risk": 0},
            },
            "page2": {"rotting_deals": [], "pipeline_at_risk": 0, "stalled_leads": [],
                      "kpi": {"rotting_count": 0, "stalled_count": 0,
                              "stalled_30d_plus": 0, "most_critical_deal": None}},
            "page3": {"fathom_gap": [], "gap_count": 0},
            "page4": {"lemlist": [], "aimfox": [], "instantly": [], "followup_gap": []},
        },
        "narratives": {
            "forward_motion": {"degraded": True},
            "funnel_leak": {"degraded": True},
            "hygiene": {"degraded": True},
            "fathom_gap": {"degraded": True, "actions": []},
        },
        "window": {"label": "May 2026", "name": "current-month"},
        "rendered_at": "2026-05-09T10:00:00",
        "degraded_sections": ["funnel narrative", "hygiene narrative"],
    }


def test_base_renders_without_error(env, context):
    html = env.get_template("base.html.j2").render(**context)
    assert "Leadle Revenue Engine Dashboard" in html
    assert "May 2026" in html


def test_all_four_tabs_present(env, context):
    html = env.get_template("base.html.j2").render(**context)
    for tab_id in ("page1", "page2", "page3", "page4"):
        assert f'id="{tab_id}"' in html


def test_degraded_narratives_show_fallback_badges(env, context):
    html = env.get_template("base.html.j2").render(**context)
    assert "narrative unavailable" in html
```

- [ ] **Step 2: Run — should pass**

```bash
pytest tests/test_templates.py -v
```

(If StrictUndefined raises on a missing key, add a defensive `| default(...)` in the template at the offending field. This is the linting purpose of using StrictUndefined in tests.)

### Task 4.4: Commit Phase 4

```bash
git add dashboard/templates/ tests/test_templates.py
git commit -m "$(cat <<'EOF'
Add Jinja templates for 4-tab dashboard

base.html.j2 with shared CSS + tab navigation; per-tab partials for
Revenue Engine, Activity & Rot, Sales Actions, Outreach. Static SOP
partials for Page 3. Defensive | default() guards everywhere narratives
might be degraded. Test suite renders with full and degraded contexts.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Phase 5 — Agent shared client + voice

**Purpose:** Build the shared agent infrastructure: voice constraints, async Anthropic SDK wrapper, retries, structured-output parsing, hallucination validator, fallback path.

### Task 5.1: Create `dashboard/agents/_voice.md`

**Files:**
- Create: `dashboard/agents/_voice.md`

- [ ] **Step 1: Write the voice constraints**

```markdown
# Leadle voice constraints

You are writing for Bhuvanesh (RevOps Architect at Leadle). The reader is sharp, knows the business, and reads dashboards daily. Match this voice strictly.

## Tone
- Conversational, thinking out loud, dry humor.
- Short sentences. Land the point and stop.
- No preachy endings. No sign-offs. No "in summary."

## Forbidden phrases and patterns
- AI tells: "delve", "leverage", "unlock", "ecosystem", "robust", "comprehensive", "in today's fast-paced".
- Em dashes (—). Use parentheses, colons, or new sentences instead.
- Listy bullet structure when prose is sharper.
- Filler micro-sentences ("Got it.", "Of course.", "Certainly.").
- Captions that re-state the section label without adding POV.

## Numerical discipline
- NEVER cite a number that isn't in the analytics input you were given. Don't paraphrase numbers ("around 5" when input had 5; "nearly 20K" when input had $19,500).
- When unsure of a value, omit it. Never round in a way that changes magnitude.
- Currency: match the input currency exactly. Don't convert.

## Naming
- Sai, Bhuvanesh, Akil, Bhuvaneswari, Harinie, Suraj — these are the people. Use first names, no titles.
- Tools: HubSpot, Lemlist, Aimfox, Instantly, Fathom, Clay, Slack — exact casing.

## Format
- Output JSON exactly matching the schema I give you. No markdown, no explanation outside the JSON.
- Keep prose fields short — under 150 characters where reasonable.
```

### Task 5.2: TDD `dashboard/agents/_client.py` — basic SDK wrapper

**Files:**
- Create: `dashboard/agents/_client.py`
- Create: `tests/test_agents_client.py`

- [ ] **Step 1: Write failing tests for the validator**

```python
# tests/test_agents_client.py
import pytest
from dashboard.agents._client import validate_no_hallucinated_numbers


def test_validator_passes_when_all_numbers_in_input():
    input_text = "5 rotting deals worth $19,500, 73 stalled leads"
    output_text = "5 deals stalling, $19.5K at risk, 73 leads waiting"
    # Should pass — every output number ($19.5K → 19500) appears in input.
    assert validate_no_hallucinated_numbers(input_text, output_text) is True


def test_validator_rejects_hallucinated_number():
    input_text = "5 rotting deals worth $19,500"
    output_text = "5 deals worth $25,000 at risk"
    # 25000 is not in input
    assert validate_no_hallucinated_numbers(input_text, output_text) is False


def test_validator_accepts_paraphrased_with_same_value():
    input_text = "Pipeline coverage is 0.52x"
    output_text = "Coverage at 0.52x — well below target"
    assert validate_no_hallucinated_numbers(input_text, output_text) is True


def test_validator_normalizes_k_suffix():
    input_text = "$19500"
    output_text = "$19.5K is at risk"
    assert validate_no_hallucinated_numbers(input_text, output_text) is True


def test_validator_normalizes_commas():
    input_text = "12000 in revenue"
    output_text = "$12,000 in revenue"
    assert validate_no_hallucinated_numbers(input_text, output_text) is True
```

- [ ] **Step 2: Run — FAIL**

```bash
pytest tests/test_agents_client.py -v
```

- [ ] **Step 3: Implement validator + sketch async client**

```python
# dashboard/agents/_client.py
"""Shared agent infrastructure: Anthropic SDK wrapper with retries,
structured output parsing, and hallucination validation.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from anthropic import APIError, AsyncAnthropic, RateLimitError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

_VOICE_MD = Path(__file__).parent / "_voice.md"
_NUMBER_REGEX = re.compile(r"-?\$?\d[\d,.]*[KMB]?", re.IGNORECASE)


def _normalize_number(s: str) -> float | None:
    """Strip currency, expand K/M/B suffixes, return float."""
    s = s.replace("$", "").replace(",", "").strip().upper()
    multiplier = 1
    if s.endswith("K"):
        multiplier = 1_000
        s = s[:-1]
    elif s.endswith("M"):
        multiplier = 1_000_000
        s = s[:-1]
    elif s.endswith("B"):
        multiplier = 1_000_000_000
        s = s[:-1]
    try:
        return float(s) * multiplier
    except ValueError:
        return None


def validate_no_hallucinated_numbers(input_text: str, output_text: str,
                                     tolerance: float = 0.001) -> bool:
    """Every digit-string in output must match a digit-string in input
    (after normalization). Returns False if any output number is novel.
    """
    input_nums: list[float] = []
    for m in _NUMBER_REGEX.findall(input_text):
        n = _normalize_number(m)
        if n is not None:
            input_nums.append(n)
    for m in _NUMBER_REGEX.findall(output_text):
        n = _normalize_number(m)
        if n is None:
            continue
        if not any(abs(n - i) <= tolerance * max(abs(n), abs(i), 1) for i in input_nums):
            return False
    return True


def load_voice() -> str:
    return _VOICE_MD.read_text(encoding="utf-8")


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type((APIError, RateLimitError)),
)
async def _call_claude(client: AsyncAnthropic, *, model: str, system: str,
                       user: str, max_tokens: int = 1024) -> str:
    msg = await client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in msg.content if hasattr(b, "text"))


async def run_agent(
    *,
    model: str,
    role_prompt: str,
    json_schema_description: str,
    input_payload: dict,
    fallback_factory: Callable[[dict], dict],
    client: AsyncAnthropic | None = None,
) -> dict:
    """Run a single agent. Returns {'degraded': bool, ...} dict.

    On any failure (API error, malformed JSON, hallucination) → fallback.
    """
    client = client or AsyncAnthropic()
    voice = load_voice()
    system = f"{voice}\n\n---\n\n{role_prompt}\n\n{json_schema_description}"
    user = f"Input:\n```json\n{json.dumps(input_payload, indent=2)}\n```\n\nReturn JSON only."

    try:
        text = await _call_claude(client, model=model, system=system, user=user)
        parsed = _extract_json(text)
        if parsed is None:
            # Retry once with stricter instruction
            text = await _call_claude(client, model=model, system=system,
                                      user=user + "\n\nIMPORTANT: respond with JSON ONLY, no prose.")
            parsed = _extract_json(text)
        if parsed is None:
            raise ValueError("Agent returned no parseable JSON")

        if not validate_no_hallucinated_numbers(json.dumps(input_payload), json.dumps(parsed)):
            raise ValueError("Hallucinated number detected in agent output")

        return {"degraded": False, **parsed}
    except Exception as e:
        return {"degraded": True, "reason": str(e), **fallback_factory(input_payload)}


def _extract_json(text: str) -> dict | None:
    """Pull the first JSON object out of text. Tolerates leading/trailing prose."""
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
```

- [ ] **Step 4: Run — validator tests pass**

```bash
pytest tests/test_agents_client.py -v
```

### Task 5.3: TDD fallback + run_agent flow

- [ ] **Step 1: Add tests with mocked SDK**

Append to `tests/test_agents_client.py`:
```python
from unittest.mock import AsyncMock, MagicMock
import pytest
from dashboard.agents._client import run_agent


@pytest.mark.asyncio
async def test_run_agent_returns_parsed_on_clean_response():
    mock_client = MagicMock()
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text='{"headline": "ok", "value": 5}')]
    mock_client.messages.create = AsyncMock(return_value=mock_msg)

    out = await run_agent(
        model="claude-sonnet-4-5",
        role_prompt="Return JSON.",
        json_schema_description="{headline: str, value: int}",
        input_payload={"value": 5},
        fallback_factory=lambda p: {"headline": "fallback"},
        client=mock_client,
    )
    assert out["degraded"] is False
    assert out["headline"] == "ok"


@pytest.mark.asyncio
async def test_run_agent_falls_back_on_hallucinated_number():
    mock_client = MagicMock()
    mock_msg = MagicMock()
    # Output number 999 not in input (input has 5)
    mock_msg.content = [MagicMock(text='{"headline": "999 rotting deals"}')]
    mock_client.messages.create = AsyncMock(return_value=mock_msg)

    out = await run_agent(
        model="claude-sonnet-4-5",
        role_prompt="Return JSON.",
        json_schema_description="{headline: str}",
        input_payload={"rotting_deals": 5},
        fallback_factory=lambda p: {"headline": "fallback"},
        client=mock_client,
    )
    assert out["degraded"] is True
    assert out["headline"] == "fallback"
```

- [ ] **Step 2: Run — should pass (run_agent already implements the contract)**

```bash
pytest tests/test_agents_client.py -v
```

### Task 5.4: Commit Phase 5

```bash
git add dashboard/agents/_voice.md dashboard/agents/_client.py tests/test_agents_client.py
git commit -m "$(cat <<'EOF'
Add agent shared client: voice, async SDK wrapper, hallucination validator

_voice.md encodes Leadle voice constraints (forbidden AI phrases, em dashes,
numerical discipline). _client.py provides run_agent() with tenacity retries,
JSON extraction, hallucination validation (digit-string normalization match),
and fail-open fallback. Validator tested across paraphrasing, K-suffix
normalization, comma normalization, hallucination rejection.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Phase 6 — Per-agent implementations

**Purpose:** Each agent module is a thin wrapper around `run_agent()` — defines its role, schema, input slicer, and fallback.

### Task 6.1: `dashboard/agents/forward_motion.py`

**Files:**
- Create: `dashboard/agents/forward_motion.py`

- [ ] **Step 1: Implement**

```python
"""Forward Motion agent — synthesizes Page 1 §09 commitments (Sonnet)."""
from __future__ import annotations

from dashboard.agents._client import run_agent

_MODEL = "claude-sonnet-4-5"

_ROLE = """
You synthesize 5 weekly revenue commitments for Leadle's RevOps team based on the dashboard's analytics output.

Pick the 5 highest-impact actions. Assign each to one of: Sai (Sales Head), Bhuvanesh (RevOps), Akil (Head of RevOps), Founders. Phrase each commitment with specific deal names, dollar amounts, day counts where relevant. Keep each under 200 characters.
"""

_SCHEMA = """
Return JSON of this exact shape:
{
  "commitments": [
    {"owner": "Sai|Bhuvanesh|Akil|Founders", "text": "<action with specifics>"},
    ... exactly 5 items ...
  ]
}
"""


def _fallback(input_payload: dict) -> dict:
    deals = input_payload.get("rotting_deals", [])[:5]
    return {
        "commitments": [
            {"owner": "Sai",
             "text": f"Review {d.get('name')} (stale {d.get('days_stale')}d, ${d.get('amount')})"}
            for d in deals
        ] or [{"owner": "Sai", "text": "No rule-flagged actions in window."}]
    }


async def synthesize(analytics: dict) -> dict:
    p1 = analytics.get("page1", {})
    p2 = analytics.get("page2", {})
    p4 = analytics.get("page4", {})
    payload = {
        "rotting_deals": p1.get("forward_motion_input", {}).get("rotting_deals", [])[:10],
        "pipeline_at_risk": p1.get("forward_motion_input", {}).get("rotting_pipeline_at_risk", 0),
        "stalled_leads_count": p2.get("kpi", {}).get("stalled_count", 0),
        "monthly_target": p1.get("monthly_control", {}).get("monthly_target", 0),
        "monthly_gap": p1.get("monthly_control", {}).get("monthly_gap", 0),
        "pipeline_coverage_ratio": p1.get("monthly_control", {}).get("pipeline_coverage_ratio", 0),
        "hygiene_issues_count": p1.get("hygiene", {}).get("total_issues", 0),
        "followup_gap_count": len(p4.get("followup_gap", [])),
    }
    return await run_agent(
        model=_MODEL,
        role_prompt=_ROLE,
        json_schema_description=_SCHEMA,
        input_payload=payload,
        fallback_factory=_fallback,
    )
```

### Task 6.2: `dashboard/agents/funnel_leak.py`

```python
"""Funnel Leak agent — interprets Page 1 §06 conversions (Sonnet)."""
from __future__ import annotations

from dashboard.agents._client import run_agent

_MODEL = "claude-sonnet-4-5"

_ROLE = """
You identify the largest leak in the sales funnel and explain its likely cause in one short paragraph.

Pick the single stage transition with the lowest conversion rate (or smallest absolute count drop, whichever is more meaningful). Headline names the leak. Explanation is one short sentence (<200 chars) about why this stage might be the bottleneck. Don't speculate beyond what the numbers support.
"""

_SCHEMA = """
{"headline": "<one line, e.g. 'Discovery → Proposal at 12%'>",
 "explanation": "<≤200 chars>",
 "leaking_stage": "<from_stage>",
 "conversion_pct": <float>}
"""


def _fallback(input_payload: dict) -> dict:
    convs = input_payload.get("conversions", [])
    if not convs:
        return {"headline": "—", "explanation": "Insufficient data.",
                "leaking_stage": "", "conversion_pct": 0.0}
    worst = min((c for c in convs if c.get("conversion_pct") is not None),
                key=lambda c: c["conversion_pct"], default=None)
    if not worst:
        return {"headline": "—", "explanation": "No conversions computed.",
                "leaking_stage": "", "conversion_pct": 0.0}
    return {
        "headline": f"{worst['from_stage']} → {worst['to_stage']} at {worst['conversion_pct']:.1f}%",
        "explanation": "Lowest conversion rate in the funnel.",
        "leaking_stage": worst["from_stage"],
        "conversion_pct": worst["conversion_pct"],
    }


async def synthesize(analytics: dict) -> dict:
    p = analytics.get("page1", {}).get("funnel", {})
    payload = {"stage_counts": p.get("stage_counts", {}),
               "conversions": p.get("conversions", [])}
    return await run_agent(model=_MODEL, role_prompt=_ROLE,
                           json_schema_description=_SCHEMA,
                           input_payload=payload, fallback_factory=_fallback)
```

### Task 6.3: `dashboard/agents/hygiene.py`

```python
"""Hygiene agent — categorizes Page 1 §08 issues by impact (Sonnet)."""
from __future__ import annotations

from dashboard.agents._client import run_agent

_MODEL = "claude-sonnet-4-5"

_ROLE = """
You categorize hygiene issues by business impact. Group similar issues. Mark severity: blocking (blocks monthly close), important (affects reporting), cosmetic (nice-to-fix).

Output 3–6 categories. Each has a title, a one-sentence summary, count, severity, and a one-sentence "fix" hint (specific, not generic).
"""

_SCHEMA = """
{"categories": [
  {"title": "<short>", "summary": "<≤150 chars>", "count": <int>,
   "severity": "blocking|important|cosmetic", "fix": "<≤150 chars>"}
]}
"""


def _fallback(input_payload: dict) -> dict:
    return {"categories": [
        {"title": "Hygiene issues",
         "summary": f"Total {input_payload.get('total_issues', 0)} issues across deals and contacts.",
         "count": input_payload.get("total_issues", 0),
         "severity": "important",
         "fix": "Review issues list manually."}
    ]}


async def synthesize(analytics: dict) -> dict:
    payload = analytics.get("page1", {}).get("hygiene", {})
    return await run_agent(model=_MODEL, role_prompt=_ROLE,
                           json_schema_description=_SCHEMA,
                           input_payload=payload, fallback_factory=_fallback)
```

### Task 6.4: `dashboard/agents/fathom_gap.py`

```python
"""Fathom Gap agent — per-row Action Needed (Haiku, batched)."""
from __future__ import annotations

from dashboard.agents._client import run_agent

_MODEL = "claude-haiku-4-5-20251001"

_ROLE = """
For each Fathom call without a HubSpot deal, produce a single short action recommendation. Be specific: include the company name, the right stage to create the deal in (Discovery if call_type=discovery, else stage matching the call), and any context-relevant note (e.g., contact_id mismatch, domain not found).
"""

_SCHEMA = """
{"actions": [
  {"company": "<name>", "action": "<≤120 chars action>"}
  ... one per input row, in order ...
]}
"""


def _fallback(input_payload: dict) -> dict:
    rows = input_payload.get("gap_rows", [])
    return {"actions": [
        {"company": r.get("company", "?"),
         "action": r.get("suggested_action_default", "Create deal in HubSpot · stage: Discovery")}
        for r in rows
    ]}


async def synthesize(analytics: dict) -> dict:
    rows = analytics.get("page3", {}).get("fathom_gap", [])
    return await run_agent(model=_MODEL, role_prompt=_ROLE,
                           json_schema_description=_SCHEMA,
                           input_payload={"gap_rows": rows},
                           fallback_factory=_fallback)
```

### Task 6.5: Commit Phase 6

```bash
git add dashboard/agents/forward_motion.py dashboard/agents/funnel_leak.py \
        dashboard/agents/hygiene.py dashboard/agents/fathom_gap.py
git commit -m "$(cat <<'EOF'
Add 4 narrative agents (Forward Motion, Funnel Leak, Hygiene, Fathom Gap)

Each agent: role prompt + schema + input slicer + deterministic fallback.
Forward Motion / Funnel Leak / Hygiene → Sonnet for narrative quality.
Fathom Gap → Haiku batched for per-row light classification.
All agents fail open via fallback_factory; render never breaks on agent error.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Phase 7 — Render orchestrator

**Purpose:** Glue compute + agents + Jinja + file write into a runnable CLI.

### Task 7.1: Implement `dashboard/render.py`

**Files:**
- Create: `dashboard/render.py`

- [ ] **Step 1: Write the entry point**

```python
"""Dashboard render CLI: python -m dashboard.render --input <raw.json>."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from ruamel.yaml import YAML

from dashboard.agents import fathom_gap, forward_motion, funnel_leak, hygiene
from dashboard.compute import page1_revenue, page2_activity, page3_actions, page4_outreach
from dashboard.compute.windows import WindowSpec

_ROOT = Path(__file__).resolve().parents[1]
_CONFIG = _ROOT / "config"
_TEMPLATES = _ROOT / "dashboard" / "templates"


def _load_yaml(name: str) -> dict:
    return YAML(typ="safe").load((_CONFIG / name).read_text())


def _window_from_raw(raw: dict) -> WindowSpec:
    w = raw["window"]
    return WindowSpec(
        name=w["name"], label=w["label"],
        start=date.fromisoformat(w["start"]),
        end=date.fromisoformat(w["end"]),
        prior_start=date.fromisoformat(w["prior_start"]),
        prior_end=date.fromisoformat(w["prior_end"]),
    )


async def _narrate(analytics: dict) -> dict:
    fm, fl, hy, fg = await asyncio.gather(
        forward_motion.synthesize(analytics),
        funnel_leak.synthesize(analytics),
        hygiene.synthesize(analytics),
        fathom_gap.synthesize(analytics),
    )
    return {"forward_motion": fm, "funnel_leak": fl, "hygiene": hy, "fathom_gap": fg}


def _degraded_sections(narratives: dict) -> list[str]:
    return [k for k, v in narratives.items() if v.get("degraded")]


def render(raw: dict, *, skip_agents: bool = False) -> str:
    rules = _load_yaml("dashboard_rules.yaml")
    targets = _load_yaml("dashboard_targets.yaml")
    layout = _load_yaml("dashboard_layout.yaml")
    window = _window_from_raw(raw)

    today = date.fromisoformat(raw["window"]["end"])  # use window end for "today" framing

    analytics = {
        "page1": page1_revenue.compute(raw, rules, targets, window),
        "page2": page2_activity.compute(raw, rules, today=today),
        "page3": page3_actions.compute(raw, rules, window),
        "page4": page4_outreach.compute(raw, rules, window, today=today),
    }

    if skip_agents:
        narratives = {k: {"degraded": True} for k in
                      ["forward_motion", "funnel_leak", "hygiene", "fathom_gap"]}
    else:
        narratives = asyncio.run(_narrate(analytics))

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template("base.html.j2")
    html = template.render(
        analytics=analytics,
        narratives=narratives,
        window={"label": window.label, "name": window.name,
                "start": window.start.isoformat(), "end": window.end.isoformat()},
        rendered_at=datetime.now().isoformat(timespec="seconds"),
        degraded_sections=_degraded_sections(narratives),
        layout=layout,
    )
    return html


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Path to dashboard_raw_*.json")
    parser.add_argument("--skip-agents", action="store_true",
                        help="Skip Anthropic SDK calls (CI/test mode)")
    parser.add_argument("--output-dir", default=str(_ROOT / "reports"))
    args = parser.parse_args()

    raw = json.loads(Path(args.input).read_text())
    html = render(raw, skip_agents=args.skip_agents)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    end_date = raw["window"]["end"]
    window_name = raw["window"]["name"]
    out_path = out_dir / f"dashboard_{end_date}_{window_name}.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"✅ Dashboard rendered: {out_path.absolute()}")
    print(f"   Window: {raw['window']['label']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

### Task 7.2: TDD end-to-end Python pipeline (mocked agents)

**Files:**
- Create: `tests/test_render.py`

- [ ] **Step 1: Write the e2e test**

```python
# tests/test_render.py
import json
from pathlib import Path

import pytest
from dashboard.render import render


@pytest.fixture
def sample_raw():
    return json.loads((Path(__file__).parent / "fixtures" / "sample_raw.json").read_text())


def test_render_produces_html_with_skip_agents(sample_raw):
    html = render(sample_raw, skip_agents=True)
    assert "<!DOCTYPE html>" in html
    assert "Leadle Revenue Engine Dashboard" in html
    assert "May 2026" in html


def test_render_includes_all_four_tabs(sample_raw):
    html = render(sample_raw, skip_agents=True)
    for tab_id in ("page1", "page2", "page3", "page4"):
        assert f'id="{tab_id}"' in html


def test_render_shows_fixture_data(sample_raw):
    html = render(sample_raw, skip_agents=True)
    assert "Scalenut" in html
    assert "QuoDeck" in html


def test_render_includes_degraded_badges(sample_raw):
    html = render(sample_raw, skip_agents=True)
    assert "narrative unavailable" in html
```

- [ ] **Step 2: Run — PASS**

```bash
pytest tests/test_render.py -v
```

### Task 7.3: Commit Phase 7

```bash
git add dashboard/render.py tests/test_render.py
git commit -m "$(cat <<'EOF'
Add render orchestrator and end-to-end Python pipeline

dashboard/render.py: CLI entry point glueing compute + agents + Jinja.
asyncio.gather runs all 4 agents concurrently. --skip-agents flag
exercises deterministic path for CI / fixture testing. End-to-end test
renders sample_raw.json into a complete HTML file with all 4 tabs.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Phase 8 — Slash command + MCP setup

**Purpose:** Wire up the live MCP integration and the interactive slash command. This is the only phase requiring manual user interaction.

### Task 8.1: Install MCP servers (manual)

**Files:** none (configures Claude Code globally)

- [ ] **Step 1: Add Lemlist MCP**

```bash
claude mcp add --transport http lemlist https://app.lemlist.com/mcp
```
A browser opens for OAuth consent. Complete the flow.

- [ ] **Step 2: Add Aimfox MCP**

```bash
claude mcp add --transport http aimfox https://mcp.aimfox.com
```
Complete OAuth.

- [ ] **Step 3: Add Instantly MCP**

First obtain API key from Instantly → Settings → Integrations → API Keys → Create API Key. Set as env var:

```bash
export INSTANTLY_API_KEY=<paste_key>
claude mcp add --transport http instantly "https://mcp.instantly.ai/mcp/$INSTANTLY_API_KEY"
```

- [ ] **Step 4: Add Fathom MCP**

```bash
claude mcp add fathom -- npx mcp-remote@latest https://api.fathom.ai/mcp
```
Browser OAuth flow.

- [ ] **Step 5: Verify all 5 MCPs connected**

```bash
claude mcp list
```
Expected: `hubspot`, `lemlist`, `aimfox`, `instantly`, `fathom` all listed.

### Task 8.2: Create `config/dashboard_window_prompt.yaml`

**Files:**
- Create: `config/dashboard_window_prompt.yaml`

- [ ] **Step 1: Write the YAML**

```yaml
primary_options:
  - last-7d
  - current-month
  - current-quarter
  - last-quarter
prompt_template: |
  What time window for this dashboard?
  Today: {today} · Current FY quarter: {current_quarter_label}
```

### Task 8.3: Create `.claude/commands/render-dashboard.md`

**Files:**
- Create: `.claude/commands/render-dashboard.md`

- [ ] **Step 1: Write the slash command**

```markdown
---
description: Render the Leadle 4-tab dashboard from live MCP data
allowed-tools: AskUserQuestion, Bash, mcp__claude_ai_HubSpot__*, mcp__lemlist__*, mcp__aimfox__*, mcp__instantly__*, mcp__fathom__*
---

# /render-dashboard

You are rendering the Leadle dashboard. Follow this protocol exactly.

## Phase 0 — Window selection

1. Read `config/dashboard_windows.yaml` and `config/dashboard_window_prompt.yaml`.
2. Compute today's date (use `date "+%Y-%m-%d"` via Bash) and FY quarter context.
3. Use `AskUserQuestion` to ask:

   > "What time window for this dashboard?
   >  Today: {today} · Current FY quarter: {q_label}"

   Options: the 4 in `primary_options` from the prompt YAML, plus "Other (specify)".

4. If "Other" → second `AskUserQuestion` listing every window in `supported_windows` from `dashboard_windows.yaml`.

5. Resolve the window by running:

   ```bash
   python -c "
   from datetime import date
   from dashboard.compute.windows import resolve_window
   import json
   spec = resolve_window('<arg>', date.today())
   print(json.dumps({'name': spec.name, 'label': spec.label,
                     'start': spec.start.isoformat(), 'end': spec.end.isoformat(),
                     'prior_start': spec.prior_start.isoformat(),
                     'prior_end': spec.prior_end.isoformat()}))
   "
   ```

6. Show the resolved range and ask the user to confirm before proceeding.

## Phase 1 — Fetch from MCPs

Call each MCP for the data slices documented in spec §6. For each source, log "Fetching <source>..." before the call. On failure, mark `available: false, error: <msg>` and continue.

**HubSpot:**
- `mcp__claude_ai_HubSpot__search_crm_objects` for deals (filter `last_modified >= prior_start`), paginate until empty.
- `mcp__claude_ai_HubSpot__search_crm_objects` for contacts (filter `createdate >= today - 365d`), paginate.
- `mcp__claude_ai_HubSpot__search_crm_objects` for companies referenced.
- `mcp__claude_ai_HubSpot__search_owners`.
- `mcp__claude_ai_HubSpot__get_properties` for deals (one call).

**Lemlist, Aimfox, Instantly, Fathom:** introspect the MCP's tool list first via the MCP. Fetch campaigns + leads/conversations + per-campaign stats + (Fathom) meetings. Document tool names you used in a comment at the top of the cache file.

Save all results to `.cache/dashboard_raw_<end_date>_<window_name>.json` matching the schema in spec §5 Phase 1.

## Phase 2–5 — Compute, narrate, render, write

Run:

```bash
python -m dashboard.render --input .cache/dashboard_raw_<end_date>_<window_name>.json
```

Print the path to the produced HTML file.

## Phase 6 — Surface

Print to chat:

```
✅ Dashboard rendered: <absolute path>
   Window: <window label>
   <degradation report if any>
```

If any source was unavailable, list it. If any agent degraded (check the rendered HTML for `narrative unavailable` strings or read the structlog file), list those.
```

### Task 8.4: Verify slash command discoverable

- [ ] **Step 1: Run `/help` in Claude Code (interactive)**

In your Claude Code session, type `/` and verify `/render-dashboard` appears in the list.

### Task 8.5: Commit Phase 8

```bash
git add config/dashboard_window_prompt.yaml .claude/commands/render-dashboard.md
git commit -m "$(cat <<'EOF'
Add /render-dashboard slash command and window-prompt config

Slash command orchestrates Phase 0 (interactive window selection) →
Phase 1 (live MCP fetch from all 5 sources) → Phase 2–5 (Python render)
→ Phase 6 (surface result with degradation report).

config/dashboard_window_prompt.yaml controls the 4 options surfaced in
the primary AskUserQuestion (defaults: last-7d, current-month,
current-quarter, last-quarter).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Phase 9 — Manual smoke + fixture refresh

**Purpose:** First real-world run; capture real data; tune.

### Task 9.1: Create `smoke/MANUAL.md`

**Files:**
- Create: `smoke/MANUAL.md`

- [ ] **Step 1: Write the checklist**

```markdown
# Manual Smoke Test — Dashboard Fasttrack

Run this checklist after any change to MCP fetch logic, agent prompts, or templates. CI cannot replicate live MCP behavior.

## Pre-flight
- [ ] All 5 MCPs connected: `claude mcp list` shows hubspot, lemlist, aimfox, instantly, fathom
- [ ] OAuth tokens valid (no `reauth` errors): try a simple HubSpot query
- [ ] `.cache/` directory writable
- [ ] `./reports/` directory writable

## Render
- [ ] Run `/render-dashboard`
- [ ] Pick "Last 7 days"
- [ ] Confirm the resolved range matches expectation
- [ ] Watch for "Fetching <source>..." progress lines
- [ ] Render completes (~3–7 min)

## Output verification
- [ ] HTML file produced at `./reports/dashboard_<date>_<window>.html`
- [ ] File opens in browser without errors
- [ ] All 4 tabs visible (Revenue Engine, Activity & Rot, Sales Actions, Outreach)
- [ ] Page 1 KPI strips populated (no `—` everywhere — that means data fetch failed silently)
- [ ] Page 1 §06 Funnel narrative present (or degraded badge if Sonnet was unavailable)
- [ ] Page 1 §09 Forward Motion shows 5 commitment cards (or fallback list)
- [ ] Page 2 rotting deals + stalled leads present
- [ ] Page 3 Fathom Gap table populated for the chosen month
- [ ] Page 4 campaigns from each tool appear

## Smell-test the data
- [ ] Spot-check: pick a known deal in HubSpot, verify it appears in the right tab/section
- [ ] Spot-check: pick a known Fathom meeting, verify it shows in Page 3 if applicable
- [ ] Numbers in narratives match numbers in tables (hallucination validator passed)

## Capture fixture
- [ ] Once verified, copy `.cache/dashboard_raw_<date>_<window>.json` aside
- [ ] Scrub PII: emails (replace with `<id>@<scrubbed-domain>.com`), real names if necessary
- [ ] Replace `tests/fixtures/sample_raw.json` with the scrubbed version
- [ ] Re-run `pytest` — all tests still pass against the new fixture (update expectations if needed)
```

### Task 9.2: Run first real render

- [ ] **Step 1: In your Claude Code session, run `/render-dashboard`**

- [ ] **Step 2: Pick `last-7d`**

- [ ] **Step 3: Confirm window**

- [ ] **Step 4: Wait for render to complete; record any errors in the log**

- [ ] **Step 5: Open the HTML file in a browser; walk the manual checklist**

### Task 9.3: Capture and scrub real fixture

- [ ] **Step 1: Copy real `.cache/dashboard_raw_*.json` somewhere safe**

```bash
cp .cache/dashboard_raw_*_*.json /tmp/real_render_capture.json
```

- [ ] **Step 2: Scrub PII**

Open `/tmp/real_render_capture.json` and:
- Replace all real lead/contact emails with `lead-<id>@example.com`
- Replace real company domains with `<sanitized>.example.com`
- Keep IDs, dates, amounts, stages, statuses verbatim — those drive the tests

- [ ] **Step 3: Replace `tests/fixtures/sample_raw.json` with the scrubbed version**

- [ ] **Step 4: Run full test suite — fix any expectations**

```bash
pytest -v
```

If a test now fails because real data has different shapes than the hand-crafted fixture, update the test expectation (don't change the test logic — change the asserted numbers).

### Task 9.4: Commit Phase 9

```bash
git add smoke/MANUAL.md tests/fixtures/sample_raw.json tests/test_compute_*.py
git commit -m "$(cat <<'EOF'
Replace hand-crafted fixture with scrubbed real-render capture

Manual smoke checklist documented in smoke/MANUAL.md. tests/fixtures/
sample_raw.json now reflects actual MCP output shapes (PII scrubbed).
Test expectations updated to match real-data values.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Self-review

### Spec coverage check

| Spec section | Plan task(s) covering it |
|---|---|
| §1.1 In scope (4 tabs, 4 agents, window selector, local output) | All phases together |
| §2 Architectural principles (MCP-only, no persistence, fail-open, validation) | Phase 5 (validation), Phase 8 (MCP), Phase 7 (orchestrator) |
| §3 Architecture (6-phase pipeline) | Phase 7 render.py implements Phases 2–5; Phase 8 slash command implements Phases 0, 1, 6 |
| §4 Component inventory | Tasks 0.2, 1.1–1.2, 2.1–2.5, 3.1–3.4, 4.1–4.2, 5.1–5.2, 6.1–6.4, 7.1, 8.1–8.3 |
| §5 Data flow | Phases 7–8 |
| §6 Per-tab data plan | Phase 3 (compute), Phase 4 (templates), Phase 8 (slash command MCP fetches) |
| §7 Window selector | Phase 1 fully |
| §8 Configuration model | Tasks 1.1, 2.1, 2.2, 2.3, 8.2 |
| §9 Error handling (retry, hallucination, fail-open, degradation report) | Task 5.2–5.3 (validator + retry), Task 7.1 (degradation surface) |
| §10 Testing strategy (5 layers) | Tasks 1.3–1.7 (L1), 2.4 + 3.1–3.4 (L2), 5.2–5.3 (L3), 4.3 (L4), 7.2 (L5), 9.1 (manual) |
| §11 Cost envelope | Documented in spec, no plan task needed |
| §12 Open questions | Task 9.1–9.4 (manual smoke surfaces these) |

### Placeholder check

Searched for "TBD", "TODO", "implement later" — none in steps. Some `{# ... #}` comments in Jinja templates note where the engineer transcribes from the mock; those are direction, not placeholders.

### Type consistency

Cross-checked function signatures across phases:

- `WindowSpec` shape consistent across Phase 1, 3, 7
- `compute.pageN(raw, rules, [targets,] window, [today=...])` signatures consistent
- `agents.<name>.synthesize(analytics) -> dict[degraded, ...]` consistent
- `run_agent` keyword args consistent across all 4 agents

---

## Execution

**Plan complete and saved to `docs/superpowers/plans/2026-05-09-dashboard-fasttrack.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
