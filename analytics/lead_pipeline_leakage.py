"""Lead pipeline leakage — Leadle's own HubSpot lead funnel.

Shows how many leads ever entered each stage (hs_v2_date_entered_* properties),
the conversion rate between consecutive stages, and the single biggest drop-off
(the "leak"). Outputs a self-contained Leadle-branded HTML report.

Usage:
    python -m analytics.lead_pipeline_leakage                          # all-time
    python -m analytics.lead_pipeline_leakage --start 2026-01-01      # cohort from date
    python -m analytics.lead_pipeline_leakage --start 2026-01-01 --end 2026-06-30
    python -m analytics.lead_pipeline_leakage --out /tmp/leak.html
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml

_BASE_URL = "https://api.hubapi.com"
_PAGE_LIMIT = 100
_CONFIG_PATH = Path(__file__).parent.parent / "config" / "hubspot_pipeline.yaml"

# Base lead properties always requested alongside stage-history properties.
_BASE_PROPS = [
    "hs_object_id",
    "hs_lead_name",
    "hs_pipeline_stage",
    "hs_createdate",
    "hs_associated_contact_firstname",
    "hs_associated_contact_lastname",
    "hs_associated_company_name",
    "lead_source_v2",
]


# ── config ────────────────────────────────────────────────────────────────────


def _load_stages() -> list[dict]:
    with open(_CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    return sorted(cfg["leads"]["stages"], key=lambda s: s["order"])


# ── HubSpot fetch ─────────────────────────────────────────────────────────────


def _epoch_ms(d: date, *, end_of_day: bool = False) -> str:
    if end_of_day:
        dt = datetime.combine(d, datetime.max.time(), tzinfo=UTC)
    else:
        dt = datetime.combine(d, datetime.min.time(), tzinfo=UTC)
    return str(int(dt.timestamp() * 1000))


def fetch_leads(token: str, start: date | None, end: date | None) -> list[dict]:
    """Return raw Lead property dicts from HubSpot, with stage-history props included."""
    stages = _load_stages()
    stage_props = [s["prop"] for s in stages]
    properties = _BASE_PROPS + stage_props

    filters: list[dict] = []
    if start:
        filters.append(
            {"propertyName": "hs_createdate", "operator": "GTE", "value": _epoch_ms(start)}
        )
    if end:
        filters.append(
            {
                "propertyName": "hs_createdate",
                "operator": "LTE",
                "value": _epoch_ms(end, end_of_day=True),
            }
        )

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    out: list[dict] = []
    after: str | None = None

    with httpx.Client(headers=headers, timeout=30.0) as client:
        while True:
            body: dict[str, Any] = {
                "properties": properties,
                "sorts": [{"propertyName": "hs_createdate", "direction": "ASCENDING"}],
                "limit": _PAGE_LIMIT,
            }
            if filters:
                body["filterGroups"] = [{"filters": filters}]
            if after:
                body["after"] = after
            r = client.post(f"{_BASE_URL}/crm/v3/objects/leads/search", json=body)
            r.raise_for_status()
            data = r.json()
            out.extend(data.get("results", []))
            after = (data.get("paging") or {}).get("next", {}).get("after")
            if not after:
                break

    return out


# ── compute ───────────────────────────────────────────────────────────────────


def compute_leakage(raw_leads: list[dict]) -> dict:
    """Build funnel counts + conversion rates from raw Lead records."""
    stages = _load_stages()
    funnel_stages = [s for s in stages if not s["terminal"]]
    terminal_stages = [s for s in stages if s["terminal"]]

    # Count leads that ever entered each stage (non-null date-entered property).
    stage_entered: dict[str, int] = {}
    current_stage_counts: dict[str, int] = {}

    for lead in raw_leads:
        p = lead.get("properties", {})
        for s in stages:
            if p.get(s["prop"]):
                stage_entered[s["stage_id"]] = stage_entered.get(s["stage_id"], 0) + 1
        cur = p.get("hs_pipeline_stage")
        if cur:
            current_stage_counts[cur] = current_stage_counts.get(cur, 0) + 1

    # If no stage-history properties came back (property might not exist on
    # this HubSpot tier), fall back to current stage as a proxy.
    use_entered_counts = any(stage_entered.values())
    if not use_entered_counts:
        stage_entered = {s["stage_id"]: current_stage_counts.get(s["stage_id"], 0) for s in stages}

    # Build funnel rows.
    # "reach_pct" = % of all leads that ever touched this stage (top-of-funnel
    # denominator). This stays ≤ 100% even when HubSpot stage-jumping occurs.
    # "dropped" = leads that entered the prior stage but never entered this one
    # (negative = stage-jumping is happening; shown as "—" in the report).
    total = len(raw_leads) or 1
    funnel_rows = []
    for i, s in enumerate(funnel_stages):
        entered = stage_entered.get(s["stage_id"], 0)
        current = current_stage_counts.get(s["stage_id"], 0)
        reach_pct = round(entered / total * 100, 1)
        if i == 0:
            dropped = 0
            skipped_in = False
        else:
            prev_entered = stage_entered.get(funnel_stages[i - 1]["stage_id"], 0)
            raw_drop = prev_entered - entered
            dropped = raw_drop if raw_drop >= 0 else 0
            skipped_in = raw_drop < 0  # leads jumped in from earlier/later stages
        funnel_rows.append(
            {
                "stage_id": s["stage_id"],
                "name": s["name"],
                "entered": entered,
                "current": current,
                "reach_pct": reach_pct,
                "dropped": dropped,
                "skipped_in": skipped_in,
            }
        )

    # Archived (terminal exit) count.
    archived = sum(stage_entered.get(s["stage_id"], 0) for s in terminal_stages)

    # Biggest leak = stage with the most absolute leads dropped entering it
    # (previous stage entered - this stage entered, where positive).
    droppable = [r for r in funnel_rows if r["dropped"] > 0]
    worst = max(droppable, key=lambda r: r["dropped"]) if droppable else None

    return {
        "total": len(raw_leads),
        "funnel": funnel_rows,
        "archived": archived,
        "worst_leak": worst,
        "source": "hs_v2_date_entered" if use_entered_counts else "current_stage_proxy",
    }


# ── HTML render ───────────────────────────────────────────────────────────────


def render_html(report: dict, generated_at: str, window_label: str) -> str:
    top = report["funnel"][0]["entered"] if report["funnel"] else 1

    def bar_pct(n: int) -> int:
        return round(n / max(top, 1) * 100)

    def reach_color(pct: float) -> str:
        if pct >= 50:
            return "#2d6a4f"
        if pct >= 25:
            return "#b45309"
        return "#9b2226"

    rows_html = ""
    for row in report["funnel"]:
        bar = bar_pct(row["entered"])
        color = reach_color(row["reach_pct"])
        reach_badge = f'<span style="color:{color};font-weight:600">{row["reach_pct"]}%</span>'
        if row["skipped_in"]:
            dropped_cell = '<span style="color:#6b7280;font-size:12px">jumps in</span>'
        elif row["dropped"] > 0:
            dropped_cell = f'<span style="color:#9b2226">-{row["dropped"]}</span>'
        else:
            dropped_cell = "—"
        leak_marker = ""
        if report["worst_leak"] and row["stage_id"] == report["worst_leak"]["stage_id"]:
            leak_marker = ' <span style="background:#9b2226;color:#fff;border-radius:3px;padding:1px 6px;font-size:11px;margin-left:6px">LEAK</span>'
        rows_html += f"""
        <tr>
          <td style="padding:10px 14px">
            <div style="display:flex;align-items:center;gap:10px">
              <div style="flex:1;background:#e5e7eb;border-radius:4px;height:8px;max-width:180px">
                <div style="background:#2d6a4f;height:8px;border-radius:4px;width:{bar}%"></div>
              </div>
              <span style="font-weight:500">{row["name"]}</span>{leak_marker}
            </div>
          </td>
          <td style="padding:10px 14px;text-align:right;font-variant-numeric:tabular-nums">{row["entered"]}</td>
          <td style="padding:10px 14px;text-align:right">{reach_badge}</td>
          <td style="padding:10px 14px;text-align:right">{dropped_cell}</td>
          <td style="padding:10px 14px;text-align:right;color:#6b7280">{row["current"]}</td>
        </tr>"""

    leak_box = ""
    if report["worst_leak"]:
        w = report["worst_leak"]
        leak_box = f"""
      <div style="background:#fff1f2;border:1px solid #fecdd3;border-radius:8px;padding:16px 20px;margin-bottom:24px">
        <div style="font-family:'Fraunces',serif;font-size:15px;font-weight:600;color:#9b2226;margin-bottom:4px">
          Biggest leak: {w["name"]}
        </div>
        <div style="font-size:13px;color:#7f1d1d">
          {w["dropped"]} leads entered the prior stage but never reached {w["name"]}
          ({w["reach_pct"]}% of all leads ever touched this stage).
        </div>
      </div>"""

    proxy_note = ""
    if report["source"] == "current_stage_proxy":
        proxy_note = """<div style="font-size:12px;color:#b45309;margin-top:8px">
          Note: Stage-history properties not available — showing current stage distribution as proxy.
          Counts reflect where leads sit today, not historical flow.
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lead Pipeline Leakage — Leadle</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Fraunces:ital,wght@0,400;0,600;1,400&family=Inter+Tight:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');
  :root {{
    --bg:#fafaf7; --surface:#ffffff; --ink:#15171a;
    --green:#2d6a4f; --amber:#b45309; --red:#9b2226; --blue:#1e40af;
    --muted:#6b7280; --border:#e5e7eb;
  }}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:var(--bg);color:var(--ink);font-family:'Inter Tight',sans-serif;
        font-size:14px;line-height:1.5;padding:32px 24px}}
  .wrap{{max-width:780px;margin:0 auto}}
  h1{{font-family:'Fraunces',serif;font-size:26px;font-weight:600;margin-bottom:4px}}
  .meta{{color:var(--muted);font-size:12px;margin-bottom:28px}}
  .card{{background:var(--surface);border-radius:10px;border:1px solid var(--border);
         overflow:hidden;margin-bottom:20px}}
  table{{width:100%;border-collapse:collapse}}
  thead th{{background:#f3f4f6;padding:10px 14px;text-align:left;
             font-size:11px;text-transform:uppercase;letter-spacing:.05em;
             color:var(--muted);font-weight:600}}
  thead th:not(:first-child){{text-align:right}}
  tbody tr:not(:last-child){{border-bottom:1px solid var(--border)}}
  tbody tr:hover{{background:#f9fafb}}
  .stat-row{{display:flex;gap:16px;margin-bottom:20px}}
  .stat{{background:var(--surface);border:1px solid var(--border);border-radius:8px;
          padding:14px 18px;flex:1}}
  .stat-n{{font-family:'JetBrains Mono',monospace;font-size:24px;font-weight:500;
            color:var(--ink)}}
  .stat-l{{font-size:11px;color:var(--muted);margin-top:2px;text-transform:uppercase;
             letter-spacing:.04em}}
</style>
</head>
<body>
<div class="wrap">
  <h1>Lead Pipeline Leakage</h1>
  <div class="meta">Leadle RevOps &bull; {window_label} &bull; Generated {generated_at}</div>

  <div class="stat-row">
    <div class="stat">
      <div class="stat-n">{report["total"]}</div>
      <div class="stat-l">Total Leads</div>
    </div>
    <div class="stat">
      <div class="stat-n">{report["funnel"][-1]["entered"] if report["funnel"] else 0}</div>
      <div class="stat-l">Advanced to Deal</div>
    </div>
    <div class="stat">
      <div class="stat-n">{report["archived"]}</div>
      <div class="stat-l">Archived (Lost)</div>
    </div>
    <div class="stat">
      <div class="stat-n" style="color:var(--{"green" if (report["funnel"][-1]["reach_pct"] or 0) >= 25 else "red"})">
        {report["funnel"][-1]["reach_pct"] or "—"}{"%" if report["funnel"][-1]["reach_pct"] else ""}
      </div>
      <div class="stat-l">End-to-End Rate</div>
    </div>
  </div>

  {leak_box}

  <div class="card">
    <table>
      <thead>
        <tr>
          <th>Stage</th>
          <th>Ever Entered</th>
          <th>% of All Leads</th>
          <th>Dropped From Prior</th>
          <th>Currently In</th>
        </tr>
      </thead>
      <tbody>{rows_html}
      </tbody>
    </table>
  </div>
  {proxy_note}
  <div style="margin-top:12px;color:var(--muted);font-size:11px">
    "Ever Entered" = count with non-null hs_v2_date_entered_&lt;stage&gt; (historical flow).
    "Currently In" = live snapshot of hs_pipeline_stage today.
  </div>
</div>
</body>
</html>"""


# ── CLI ───────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    from dotenv import load_dotenv

    load_dotenv()

    from analytics._periods import add_period_args, resolve_args

    parser = argparse.ArgumentParser(prog="analytics.lead_pipeline_leakage")
    add_period_args(parser)
    parser.add_argument(
        "--out", help="Output HTML path. Defaults to reports/lead-pipeline-leakage-<date>.html"
    )
    args = parser.parse_args(argv)

    token = os.environ.get("HUBSPOT_PRIVATE_TOKEN")
    if not token:
        print("ERROR: HUBSPOT_PRIVATE_TOKEN not set", file=sys.stderr)
        return 1

    start, end, window_label = resolve_args(args)

    print(f"Fetching leads ({window_label})...", file=sys.stderr)
    raw = fetch_leads(token, start, end)
    print(f"  {len(raw)} leads fetched", file=sys.stderr)

    report = compute_leakage(raw)

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    html = render_html(report, generated_at, window_label)

    out_path = args.out
    if not out_path:
        slug = date.today().isoformat()
        reports_dir = Path(__file__).parent.parent / "reports"
        reports_dir.mkdir(exist_ok=True)
        out_path = str(reports_dir / f"lead-pipeline-leakage-{slug}.html")

    Path(out_path).write_text(html, encoding="utf-8")
    print(f"Report written to {out_path}", file=sys.stderr)

    # Summary to stdout for slash command capture.
    print(f"\nLead Pipeline Leakage Summary ({window_label})")
    print(f"  Total leads: {report['total']}")
    for row in report["funnel"]:
        skip = "  (jumps in)" if row["skipped_in"] else ""
        leak = (
            " ← LEAK"
            if (report["worst_leak"] and row["stage_id"] == report["worst_leak"]["stage_id"])
            else ""
        )
        print(
            f"  {row['name']:25s}  entered={row['entered']:4d}  reach={row['reach_pct']:5.1f}%  drop={row['dropped']:3d}{skip}{leak}"
        )
    print(f"  Archived: {report['archived']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
