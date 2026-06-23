# Client Dashboard Ranking, Filtering & Week-over-Week — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the client report's broken flat per-step block with four ranked/filtered boxes (email campaigns, email steps, LinkedIn campaigns, LinkedIn variants) and surface week-over-week movement (KPI arrows + prev-week tooltips on every numeric).

**Architecture:** Deterministic Python + Jinja only — no AI (per CLAUDE.md impact rule). A new Instantly fetch adds campaign name + step copy to step rows. `compute.campaign_boxes()` produces the four top-5 boxes plus the excluded non-performers list (the seam Sub-project B will render). The snapshot store *already persists full metrics*; this plan adds a nested delta computation (`snapshots.box_deltas`) with per-metric direction, then templates render arrows/tooltips.

**Tech Stack:** Python 3.11+, httpx, Jinja2, pytest. Existing modules: `connectors/instantly/fetch.py`, `dashboard/client/compute.py`, `dashboard/client/snapshots.py`, `dashboard/client/render.py`, `dashboard/client/templates/blocks/`.

## Global Constraints

- **Scope: client report only** (`dashboard/client/`). Do NOT touch the 4-tab dashboard, the narrative/actions agents, or any external API removal — those are Sub-projects B and C.
- **No AI in this work.** Ranking/filtering/display is deterministic.
- **No live external calls in any test.** Instantly/Aimfox/Sheets are faked/monkeypatched (existing invariant). Verify: `grep -rn "open_by_key\|InstalledAppFlow\|httpx.Client(" tests/` shows only fakes.
- **Read-only invariant:** no writes to any source system; Google Sheets scope stays `spreadsheets.readonly`.
- **Top-5 per box, after filtering.** Email excludes `open_rate == 0`; LinkedIn excludes `accept_rate == 0` (≈ 0 connections).
- **Ranking keys:** email campaigns `(-reply_rate, -click_rate, -open_rate)`; email steps `-open_rate`; LinkedIn campaigns `(-reply_rate, -accept_rate)`; LinkedIn variants `(-reply_rate, -accept_rate)`.
- **Delta direction:** higher-is-better for all rates/counts EXCEPT `bounce_rate` (lower is better → a decrease is green).
- **Snapshot is already full-metrics** — do NOT change storage; only add delta computation. Old snapshots (pre-change box structure) must degrade to baseline, never crash.
- Run tests with `.venv/bin/python -m pytest` (the rebuilt venv).

---

### Task 1: Instantly step rows carry campaign name + subject/body copy

**Files:**
- Modify: `connectors/instantly/fetch.py` (`_campaign_steps`, add `_step_copy`)
- Test: `tests/client/test_instantly_steps.py` (Create)

**Interfaces:**
- Produces: each element of the `steps` list now includes keys `campaign` (str), `step` (orig), `sent`, `opened`, `clicked`, `subject` (str, "" if absent), `body_preview` (str ≤120 chars, "" if absent).

- [ ] **Step 1: Write the failing test**

```python
# tests/client/test_instantly_steps.py
"""Step rows must carry their campaign name + step copy (subject/body)."""
import httpx
from connectors.instantly import fetch


def _client(routes):
    def handler(request):
        return routes[request.url.path](request)
    return httpx.Client(transport=httpx.MockTransport(handler), base_url=fetch._BASE_URL)


def test_steps_carry_campaign_name_and_copy():
    camps = [{"id": "c1", "name": "UPSTA-US-Founders"}]
    routes = {
        "/campaigns/analytics/steps": lambda r: httpx.Response(
            200, json=[{"step": 1, "sent": 100, "opened": 40, "clicked": 5}]
        ),
        "/campaigns/c1": lambda r: httpx.Response(
            200, json={"sequences": [{"steps": [
                {"variants": [{"subject": "Quick question", "body": "Hi {{first}}, are you the right person for X? " * 5}]}
            ]}]},
        ),
    }
    steps = fetch._campaign_steps(_client(routes), camps)
    assert steps[0]["campaign"] == "UPSTA-US-Founders"
    assert steps[0]["subject"] == "Quick question"
    assert steps[0]["body_preview"].startswith("Hi {{first}}")
    assert len(steps[0]["body_preview"]) <= 120


def test_steps_degrade_when_copy_missing():
    camps = [{"id": "c1", "name": "UPSTA-US-Founders"}]
    routes = {
        "/campaigns/analytics/steps": lambda r: httpx.Response(
            200, json=[{"step": 2, "sent": 50, "opened": 10, "clicked": 0}]
        ),
        "/campaigns/c1": lambda r: httpx.Response(404, json={}),
    }
    steps = fetch._campaign_steps(_client(routes), camps)
    assert steps[0]["campaign"] == "UPSTA-US-Founders"
    assert steps[0]["subject"] == ""
    assert steps[0]["body_preview"] == ""
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/client/test_instantly_steps.py -q`
Expected: FAIL (`KeyError: 'campaign'` — current rows lack the key).

- [ ] **Step 3: Implement — add campaign name + a copy fetch joined by step index**

In `connectors/instantly/fetch.py`, replace the body of `_campaign_steps` so each step row carries the campaign name and copy. Add a helper that reads the campaign sequence and returns copy keyed by step index (0-based position in `sequences[0]["steps"]`), with the analytics `step` (often 1-based) mapped via `index = step - 1` when `step` is an int, else positional.

```python
def _step_copy(client: httpx.Client, campaign_id: str) -> dict[int, dict]:
    """Map step-index -> {subject, body_preview} from the campaign sequence. {} on error."""
    try:
        r = client.get(f"{_BASE_URL}/campaigns/{campaign_id}")
        r.raise_for_status()
        seq = (r.json().get("sequences") or [{}])[0].get("steps") or []
    except httpx.HTTPError:
        return {}
    out: dict[int, dict] = {}
    for i, s in enumerate(seq):
        variants = s.get("variants") or [{}]
        v = variants[0]
        out[i] = {
            "subject": (v.get("subject") or "").strip(),
            "body_preview": (v.get("body") or "").strip()[:120],
        }
    return out


def _campaign_steps(client: httpx.Client, camps: list[dict]) -> list[dict]:
    """Per-step analytics for each campaign, with campaign name + step copy. [] on error."""
    all_steps = []
    for c in camps:
        try:
            r = client.get(f"{_BASE_URL}/campaigns/analytics/steps", params={"id": c["id"]})
            r.raise_for_status()
            rows = r.json()
        except httpx.HTTPError:
            continue
        if not isinstance(rows, list):
            continue
        copy = _step_copy(client, c["id"])
        for row in rows:
            step = row.get("step")
            idx = (step - 1) if isinstance(step, int) and step > 0 else None
            cp = copy.get(idx, {}) if idx is not None else {}
            all_steps.append(
                {
                    "campaign": c.get("name", ""),
                    "step": step,
                    "sent": int(row.get("sent", 0) or 0),
                    "opened": int(row.get("opened", 0) or 0),
                    "clicked": int(row.get("clicked", 0) or 0),
                    "subject": cp.get("subject", ""),
                    "body_preview": cp.get("body_preview", ""),
                }
            )
    return all_steps
```

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `.venv/bin/python -m pytest tests/client/test_instantly_steps.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add connectors/instantly/fetch.py tests/client/test_instantly_steps.py
git commit -m "feat(instantly): step rows carry campaign name + subject/body copy"
```

---

### Task 2: compute.campaign_boxes — four ranked/filtered boxes + excluded list

**Files:**
- Modify: `dashboard/client/compute.py` (add `campaign_boxes`; reuse `_rate`, `grade`, `variants`)
- Test: `tests/client/test_campaign_boxes.py` (Create)

**Interfaces:**
- Consumes: `data.email_campaigns` (EmailCampaign: name, sent, opened, clicked, bounced, replied), `data.linkedin_campaigns` (name, invites, accepted, replied), `data.content_steps` (now with `campaign`, `step`, `opened`, `sent`, `clicked`, `subject`, `body_preview`), and `variants(data, rubric)`.
- Produces: `campaign_boxes(data, rubric) -> dict` with keys:
  - `email_campaigns`: list[dict] (≤5) — {name, reply_rate, click_rate, open_rate, bounce_rate, sent, grade}
  - `email_steps`: list[dict] (≤5) — {campaign, step, label, open_rate, click_rate, subject, body_preview}
  - `linkedin_campaigns`: list[dict] (≤5) — {name, reply_rate, accept_rate, connections, invites}
  - `linkedin_variants`: list[dict] (≤5) — {name, reply_rate, accept_rate, hook}
  - `excluded`: {"email": list[str names], "linkedin": list[str names]} — non-performers dropped (for Sub-project B)

- [ ] **Step 1: Write the failing test**

```python
# tests/client/test_campaign_boxes.py
from dashboard.client import compute
from dashboard.client.model import ClientData, EmailCampaign, LinkedInCampaign

RUBRIC = {"open_rate": [["A", 0.4], ["B", 0.0]], "accept_rate": [["A", 0.3], ["B", 0.0]]}


def _data():
    return ClientData(
        email_campaigns=[
            EmailCampaign(name="hi-reply", sent=100, opened=50, clicked=10, bounced=2, replied=8),
            EmailCampaign(name="mid", sent=100, opened=40, clicked=5, bounced=1, replied=2),
            EmailCampaign(name="dead", sent=100, opened=0, clicked=0, bounced=0, replied=0),
        ],
        linkedin_campaigns=[
            LinkedInCampaign(name="li-good", invites=100, accepted=30, replied=5),
            LinkedInCampaign(name="li-dead", invites=40, accepted=0, replied=0),
        ],
        content_steps=[
            {"campaign": "hi-reply", "step": 1, "opened": 50, "sent": 100, "clicked": 10,
             "subject": "S1", "body_preview": "b1"},
            {"campaign": "dead", "step": 1, "opened": 0, "sent": 100, "clicked": 0,
             "subject": "S0", "body_preview": "b0"},
        ],
    )


def test_email_campaigns_ranked_and_filtered():
    box = compute.campaign_boxes(_data(), RUBRIC)
    names = [r["name"] for r in box["email_campaigns"]]
    assert names == ["hi-reply", "mid"]          # 'dead' (0 opens) excluded
    assert "dead" in box["excluded"]["email"]


def test_linkedin_excludes_zero_connections():
    box = compute.campaign_boxes(_data(), RUBRIC)
    assert [r["name"] for r in box["linkedin_campaigns"]] == ["li-good"]
    assert "li-dead" in box["excluded"]["linkedin"]


def test_email_steps_filtered_and_labelled():
    box = compute.campaign_boxes(_data(), RUBRIC)
    steps = box["email_steps"]
    assert len(steps) == 1                         # the 0-open 'dead' step dropped
    assert steps[0]["label"] == "hi-reply — Step 1"
    assert steps[0]["subject"] == "S1"


def test_top_5_truncation():
    d = ClientData(email_campaigns=[
        EmailCampaign(name=f"c{i}", sent=100, opened=10 + i, clicked=i, bounced=0, replied=i)
        for i in range(8)
    ])
    box = compute.campaign_boxes(d, RUBRIC)
    assert len(box["email_campaigns"]) == 5
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/client/test_campaign_boxes.py -q`
Expected: FAIL (`AttributeError: module 'compute' has no attribute 'campaign_boxes'`).

- [ ] **Step 3: Implement campaign_boxes**

Add to `dashboard/client/compute.py` (reuses existing `_rate`, `grade`, `variants`):

```python
def campaign_boxes(data: ClientData, rubric: dict) -> dict:
    """Four ranked, top-5, performer-only boxes + the excluded non-performers."""
    excluded = {"email": [], "linkedin": []}

    # Email campaigns: reply -> click -> open; drop 0-open
    email = []
    for c in data.email_campaigns:
        delivered = c.sent - c.bounced
        open_rate = _rate(c.opened, delivered)
        if open_rate == 0:
            excluded["email"].append(c.name)
            continue
        email.append({
            "name": c.name, "sent": c.sent,
            "reply_rate": _rate(c.replied, c.sent),
            "click_rate": _rate(c.clicked, delivered),
            "open_rate": open_rate,
            "bounce_rate": _rate(c.bounced, c.sent),
            "grade": grade("open_rate", open_rate, rubric),
        })
    email.sort(key=lambda r: (-r["reply_rate"], -r["click_rate"], -r["open_rate"]))

    # Email steps: drop 0-open; rank by open_rate; label "campaign — Step N"
    steps = []
    for s in data.content_steps:
        open_rate = _rate(int(s.get("opened", 0) or 0), int(s.get("sent", 0) or 0))
        if open_rate == 0:
            continue
        steps.append({
            "campaign": s.get("campaign", ""), "step": s.get("step"),
            "label": f'{s.get("campaign", "")} — Step {s.get("step")}',
            "open_rate": open_rate,
            "click_rate": _rate(int(s.get("clicked", 0) or 0), int(s.get("sent", 0) or 0)),
            "subject": s.get("subject", ""), "body_preview": s.get("body_preview", ""),
        })
    steps.sort(key=lambda r: -r["open_rate"])

    # LinkedIn campaigns: reply -> accept; drop 0 connections
    li = []
    for c in data.linkedin_campaigns:
        accept_rate = _rate(c.accepted, c.invites)
        if c.accepted == 0:
            excluded["linkedin"].append(c.name)
            continue
        li.append({
            "name": c.name, "invites": c.invites, "connections": c.accepted,
            "reply_rate": _rate(c.replied, c.invites), "accept_rate": accept_rate,
        })
    li.sort(key=lambda r: (-r["reply_rate"], -r["accept_rate"]))

    # LinkedIn variants: reuse variants(); drop 0 accepts
    var = [v for v in variants(data, rubric) if v["accept_rate"] > 0]
    var.sort(key=lambda r: (-r["reply_rate"], -r["accept_rate"]))

    return {
        "email_campaigns": email[:5],
        "email_steps": steps[:5],
        "linkedin_campaigns": li[:5],
        "linkedin_variants": var[:5],
        "excluded": excluded,
    }
```

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `.venv/bin/python -m pytest tests/client/test_campaign_boxes.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add dashboard/client/compute.py tests/client/test_campaign_boxes.py
git commit -m "feat(compute): campaign_boxes — 4 ranked/filtered boxes + excluded list"
```

---

### Task 3: snapshots.box_deltas — nested week-over-week with per-metric direction

**Files:**
- Modify: `dashboard/client/snapshots.py` (add `box_deltas`, keep `deltas`)
- Test: `tests/client/test_box_deltas.py` (Create)

**Interfaces:**
- Consumes: current `metrics` dict (has `kpis` + `boxes` from Task 4 wiring) and a prior `metrics` dict (or None).
- Produces: `box_deltas(current_metrics, prior_metrics) -> dict` mapping each numeric to `{value, delta, dir}` where `dir` ∈ {"up","down","flat","baseline"} after applying direction (bounce_rate inverted). Keyed: `kpis.<key>`, and `campaign.<name>.<field>` for email/linkedin campaigns matched by name. Unmatched/new/no-prior → `dir="baseline", delta=None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/client/test_box_deltas.py
from dashboard.client import snapshots

LOWER_BETTER = {"bounce_rate"}


def test_kpi_up_down_and_baseline():
    cur = {"kpis": {"leads": 10, "email_replies": 5}, "boxes": {"email_campaigns": []}}
    prior = {"kpis": {"leads": 7}}
    d = snapshots.box_deltas(cur, prior)
    assert d["kpis.leads"]["dir"] == "up" and d["kpis.leads"]["delta"] == 3
    assert d["kpis.email_replies"]["dir"] == "baseline"      # not in prior


def test_bounce_rate_inverted():
    cur = {"kpis": {}, "boxes": {"email_campaigns": [{"name": "c1", "bounce_rate": 0.02, "reply_rate": 0.05}]}}
    prior = {"boxes": {"email_campaigns": [{"name": "c1", "bounce_rate": 0.05, "reply_rate": 0.03}]}}
    d = snapshots.box_deltas(cur, prior)
    assert d["campaign.c1.bounce_rate"]["dir"] == "up"       # bounce went DOWN -> good -> green/up
    assert d["campaign.c1.reply_rate"]["dir"] == "up"        # reply went up -> good


def test_no_prior_is_baseline():
    cur = {"kpis": {"leads": 4}, "boxes": {"email_campaigns": []}}
    d = snapshots.box_deltas(cur, None)
    assert d["kpis.leads"]["dir"] == "baseline"


def test_variants_keyed_by_name():
    cur = {"kpis": {}, "boxes": {"linkedin_variants": [{"name": "v1", "reply_rate": 0.05, "accept_rate": 0.3}]}}
    prior = {"boxes": {"linkedin_variants": [{"name": "v1", "reply_rate": 0.02, "accept_rate": 0.3}]}}
    d = snapshots.box_deltas(cur, prior)
    assert d["variant.v1.reply_rate"]["dir"] == "up"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/client/test_box_deltas.py -q`
Expected: FAIL (`AttributeError: ... has no attribute 'box_deltas'`).

- [ ] **Step 3: Implement box_deltas**

Add to `dashboard/client/snapshots.py`:

```python
_LOWER_IS_BETTER = {"bounce_rate"}


def _dir(field: str, cur, prior):
    if prior is None or not isinstance(cur, (int, float)) or not isinstance(prior, (int, float)):
        return {"value": cur, "delta": None, "dir": "baseline"}
    delta = round(cur - prior, 4)
    if delta == 0:
        return {"value": cur, "delta": 0, "dir": "flat"}
    improved = (delta < 0) if field in _LOWER_IS_BETTER else (delta > 0)
    return {"value": cur, "delta": delta, "dir": "up" if improved else "down"}


def box_deltas(current: dict, prior: dict | None) -> dict:
    out: dict = {}
    pk = (prior or {}).get("kpis", {})
    for k, v in (current.get("kpis") or {}).items():
        out[f"kpis.{k}"] = _dir(k, v, pk.get(k) if prior else None)

    pboxes = (prior or {}).get("boxes", {})
    cboxes = current.get("boxes") or {}
    # Boxes with a stable identity (name) get per-row WoW. Email steps are intentionally
    # excluded: their week-to-week identity is unstable and 'step' is an id, not a metric.
    for box, prefix in (("email_campaigns", "campaign"),
                        ("linkedin_campaigns", "campaign"),
                        ("linkedin_variants", "variant")):
        prior_by_name = {r["name"]: r for r in (pboxes.get(box) or [])}
        for row in cboxes.get(box, []):
            prow = prior_by_name.get(row["name"]) if prior else None
            for field, val in row.items():
                if isinstance(val, (int, float)):
                    out[f"{prefix}.{row['name']}.{field}"] = _dir(
                        field, val, (prow or {}).get(field) if prow else None
                    )
    return out
```

**Coverage note:** WoW deltas cover KPIs + email campaigns + LinkedIn campaigns + LinkedIn variants (everything with a stable name identity). Email *step* rows render current values only (no prev-week tooltip) because step identity shifts week to week — this is the one place that intentionally narrows the spec's "all numerics."

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `.venv/bin/python -m pytest tests/client/test_box_deltas.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add dashboard/client/snapshots.py tests/client/test_box_deltas.py
git commit -m "feat(snapshots): box_deltas — nested WoW deltas with per-metric direction"
```

---

### Task 4: Wire campaign_boxes + box_deltas into compute_all and render

**Files:**
- Modify: `dashboard/client/compute.py` (`compute_all` adds `"boxes"`)
- Modify: `dashboard/client/render.py` (compute `box_deltas`, pass to template)
- Test: `tests/client/test_render_wiring.py` (Create)

**Interfaces:**
- Consumes: `campaign_boxes` (Task 2), `box_deltas` (Task 3).
- Produces: `compute_all(...)["boxes"]` present; `render(...)` passes `deltas` = `box_deltas(metrics, prior)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/client/test_render_wiring.py
from dashboard.client import compute
from dashboard.client.model import ClientData, EmailCampaign

RUBRIC = {"open_rate": [["A", 0.4], ["B", 0.0]], "accept_rate": [["A", 0.3], ["B", 0.0]]}


def test_compute_all_has_boxes():
    d = ClientData(email_campaigns=[EmailCampaign(name="c", sent=10, opened=5, clicked=1, bounced=0, replied=1)])
    m = compute.compute_all(d, RUBRIC)
    assert "boxes" in m
    assert "email_campaigns" in m["boxes"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/client/test_render_wiring.py -q`
Expected: FAIL (`KeyError: 'boxes'`).

- [ ] **Step 3: Wire it**

In `dashboard/client/compute.py`, in `compute_all`'s returned dict add:
```python
        "boxes": campaign_boxes(data, rubric),
```

In `dashboard/client/render.py` `main()`, replace the KPI-only delta line:
```python
        deltas_bag = snapshots.deltas(metrics["kpis"], prior.get("kpis") if prior else None)
```
with the full nested delta over the whole metrics dict:
```python
        deltas_bag = snapshots.box_deltas(metrics, prior)
```
(`prior` is already `store.prior(client_name, period, before=args.period_end)`, i.e. the full prior metrics dict — pass it whole, not `.get("kpis")`.)

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `.venv/bin/python -m pytest tests/client/test_render_wiring.py tests/client/test_box_deltas.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dashboard/client/compute.py dashboard/client/render.py tests/client/test_render_wiring.py
git commit -m "feat(render): wire campaign_boxes + box_deltas into compute_all and render"
```

---

### Task 5: Templates — 4-box layout, WoW arrows/tooltips, remove flat content block

**Files:**
- Create: `dashboard/client/templates/blocks/_wow.html.j2` (arrow/tooltip macros)
- Rewrite: `dashboard/client/templates/blocks/campaigns.html.j2` (4 boxes)
- Modify: `dashboard/client/templates/blocks/content.html.j2` (remove flat per-step table — replace body with a comment noting it moved into campaigns box; or delete the block from the layout)
- Modify: `dashboard/client/templates/blocks/kpis.html.j2` (add arrows on headline KPIs)
- Modify: `config/client_report_layout.yaml` (ensure the campaigns block is present; drop the standalone `content` block if listed)
- Test: `tests/client/test_render_golden.py` (extend existing golden test)

**Interfaces:**
- Consumes: `metrics.boxes` (Task 4), `deltas` dict keyed `kpis.<k>` / `campaign.<name>.<field>` (Task 3/4).

- [ ] **Step 1: Write the failing golden assertion**

Extend `tests/client/test_render_golden.py` (the fixture must have ≥6 email campaigns incl. one 0-open, and a synthetic prior snapshot). Add:

```python
def test_boxes_render_top5_and_wow(rendered_internal_html):
    html = rendered_internal_html  # existing fixture that renders the internal report
    assert "Top campaigns" in html or "campaigns performed" in html
    assert "— Step" in html                       # email step label format
    assert 'class="wow up"' in html or 'class="wow down"' in html  # an arrow rendered
    assert "Step None" not in html                # the bug is gone
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/client/test_render_golden.py -q`
Expected: FAIL (no `— Step` / `wow` markup yet; possibly `Step None` still present).

- [ ] **Step 3: Add the WoW macro**

Create `dashboard/client/templates/blocks/_wow.html.j2`:

```jinja
{% macro arrow(key) -%}
  {%- set d = deltas.get(key) -%}
  {%- if d and d.dir in ('up','down') -%}
    <span class="wow {{ d.dir }}">{{ '▲' if d.dir == 'up' else '▼' }}</span>
  {%- endif -%}
{%- endmacro %}

{% macro tip(key) -%}
  {%- set d = deltas.get(key) -%}
  {%- if d and d.delta is not none -%}
    title="prev {{ (d.value - d.delta) }} ({{ '+' if d.delta >= 0 else '' }}{{ d.delta }})"
  {%- else -%}
    title="no prior week"
  {%- endif -%}
{%- endmacro %}
```

- [ ] **Step 4: Rewrite the campaigns block as four boxes**

Replace `dashboard/client/templates/blocks/campaigns.html.j2` body with four `.sec` boxes driven by `metrics.boxes` (`email_campaigns`, `email_steps`, `linkedin_campaigns`, `linkedin_variants`). Import the macros at top:

```jinja
{% from "blocks/_wow.html.j2" import arrow, tip %}
```
Each box: a heading, then a table of up to 5 rows. Email campaigns row example:
```jinja
<tr>
  <td class="camp">{{ c.name }}</td>
  <td class="num" {{ tip('campaign.' ~ c.name ~ '.reply_rate') }}>{{ '%.1f%%' % (c.reply_rate*100) }} {{ arrow('campaign.' ~ c.name ~ '.reply_rate') }}</td>
  <td class="num" {{ tip('campaign.' ~ c.name ~ '.click_rate') }}>{{ '%.1f%%' % (c.click_rate*100) }}</td>
  <td class="num" {{ tip('campaign.' ~ c.name ~ '.open_rate') }}>{{ '%.0f%%' % (c.open_rate*100) }}</td>
</tr>
```
Email steps row shows the label + content line:
```jinja
<tr><td class="k">{{ s.label }}<div class="content-line">{{ s.subject }}{% if s.body_preview %} · {{ s.body_preview }}{% endif %}</div></td>
    <td class="num">{{ '%.0f%%' % (s.open_rate*100) }}</td></tr>
```
LinkedIn campaigns use `reply_rate` + `connections`; LinkedIn variants use `reply_rate` + `accept_rate` + `hook` as the content line. Each box guards empty: `{% if metrics.boxes.email_campaigns %}…{% else %}<div class="note">No performing campaigns this period.</div>{% endif %}`.

- [ ] **Step 5: Add KPI arrows + remove flat content**

In `kpis.html.j2`, import the macros and append `{{ arrow('kpis.<field>') }}` and `{{ tip('kpis.<field>') }}` to each headline KPI (e.g. `fresh_prospects`, `email_replies`, `positive_replies`, `leads`, `meetings`, `accept_rate`). In `content.html.j2`, remove the flat per-step `<table>` (its data now lives in the email-steps box) — leave the file as an empty `{# moved into campaigns box #}` or remove the `content` entry from `config/client_report_layout.yaml`. Verify no template still references `metrics.content` for the flat list.

- [ ] **Step 6: Run the tests and make sure they pass**

Run: `.venv/bin/python -m pytest tests/client/test_render_golden.py tests/client/test_templates_v2.py -q`
Expected: PASS, and `Step None` absent.

- [ ] **Step 7: Commit**

```bash
git add dashboard/client/templates/blocks/_wow.html.j2 dashboard/client/templates/blocks/campaigns.html.j2 dashboard/client/templates/blocks/content.html.j2 dashboard/client/templates/blocks/kpis.html.j2 config/client_report_layout.yaml tests/client/test_render_golden.py
git commit -m "feat(templates): 4-box campaigns layout + WoW arrows/tooltips; remove flat step block"
```

---

### Task 6: Integration — full suite + live render verification

**Files:** none new (verification).

- [ ] **Step 1: Full client suite green**

Run: `.venv/bin/python -m pytest tests/client -q`
Expected: all pass.

- [ ] **Step 2: No live external calls in tests**

Run: `grep -rn "open_by_key\|InstalledAppFlow\|run_local_server" tests/client/ ; grep -rln "MockTransport\|monkeypatch\|_Fake" tests/client/ | head`
Expected: no live-call constructors; fakes/monkeypatch present.

- [ ] **Step 3: Live weekly render shows the new boxes + WoW**

```bash
source .venv/bin/activate && set -a && source .env && set +a
python -m dashboard.client.render --client UPSTA --period weekly --audience both --period-end 2026-06-23 --skip-agents
grep -c "— Step\|wow " reports/client/UPSTA-2026-06-23-weekly-internal.html
grep -c "Step None" reports/client/UPSTA-2026-06-23-weekly-internal.html
```
Expected: first grep > 0 (boxes + arrows present), second grep == 0 (`Step None` gone). Note: WoW arrows only appear where a prior weekly snapshot exists; first run after the change may show baseline (no arrows) for campaign rows — that is correct.

---

## Final verification (after all tasks)

- [ ] `.venv/bin/python -m pytest tests/client -q` all green.
- [ ] The four boxes render, top-5, filtered, with campaign names + content lines.
- [ ] KPIs show WoW arrows; numerics carry prev-week tooltips; baseline path clean.
- [ ] `Step None` no longer appears in any rendered report.
- [ ] No live external calls in tests; read-only invariant intact.
