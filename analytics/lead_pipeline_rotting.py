"""Lead pipeline rotting — Leadle's own HubSpot lead pipeline.

Flags active leads that are going cold:
  • No future task scheduled (hs_next_activity_date is null or in the past), OR
  • No activity in the past N days (configurable in config/hubspot_pipeline.yaml,
    default: 1 day)

Only active (non-archived, non-advanced) leads are evaluated. Outputs a
Leadle-branded HTML report sorted by days since last activity.

Usage:
    python -m analytics.lead_pipeline_rotting
    python -m analytics.lead_pipeline_rotting --out /tmp/rotting.html
    python -m analytics.lead_pipeline_rotting --threshold 2   # override days
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml

_BASE_URL = "https://api.hubapi.com"
_PAGE_LIMIT = 100
_CONFIG_PATH = Path(__file__).parent.parent / "config" / "hubspot_pipeline.yaml"

_LEAD_PROPS = [
    "hs_object_id",
    "hs_lead_name",
    "hs_pipeline_stage",
    "hs_createdate",
    "hs_lastmodifieddate",
    "hs_contact_last_activity_date",
    "hs_next_activity_date",
    "hs_associated_contact_firstname",
    "hs_associated_contact_lastname",
    "hs_associated_contact_email",
    "hs_associated_company_name",
    "hubspot_owner_id",
    "lead_source_v2",
]


# ── config ────────────────────────────────────────────────────────────────────

def _load_config() -> dict:
    with open(_CONFIG_PATH) as f:
        return yaml.safe_load(f)


def _stage_map(cfg: dict) -> dict[str, str]:
    """Return {stage_id: display_name}."""
    return {s["stage_id"]: s["name"] for s in cfg["leads"]["stages"]}


def _non_rotting_stage_ids(cfg: dict) -> set[str]:
    """Stage IDs to exclude from the rotting check (terminal + converted-to-deal)."""
    return {s["stage_id"] for s in cfg["leads"]["stages"] if not s.get("rotting", True)}


# ── HubSpot fetch ─────────────────────────────────────────────────────────────

def fetch_active_leads(token: str, rotting_stage_ids: set[str]) -> list[dict]:
    """Return Lead records that are in rotting-eligible stages (being actively worked)."""
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    out: list[dict] = []
    after: str | None = None

    with httpx.Client(headers=headers, timeout=30.0) as client:
        while True:
            body: dict[str, Any] = {
                "filterGroups": [{
                    "filters": [{
                        "propertyName": "hs_pipeline_stage",
                        "operator": "IN",
                        "values": list(rotting_stage_ids),
                    }]
                }],
                "properties": _LEAD_PROPS,
                "sorts": [{"propertyName": "hs_contact_last_activity_date", "direction": "ASCENDING"}],
                "limit": _PAGE_LIMIT,
            }
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

def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00")).date()


def compute_rotting(raw_leads: list[dict], threshold_days: int, stage_map: dict[str, str]) -> dict:
    today = date.today()
    rotting: list[dict] = []
    healthy: list[dict] = []

    for lead in raw_leads:
        p = lead.get("properties", {})

        first = p.get("hs_associated_contact_firstname") or ""
        last = p.get("hs_associated_contact_lastname") or ""
        contact_name = f"{first} {last}".strip() or p.get("hs_associated_contact_email") or "—"

        stage_id = p.get("hs_pipeline_stage") or ""
        stage_name = stage_map.get(stage_id, stage_id or "Unknown")

        # Best available activity date: prefer contact-level activity, fall back to last-modified.
        last_activity = (
            _parse_date(p.get("hs_contact_last_activity_date"))
            or _parse_date(p.get("hs_lastmodifieddate"))
        )
        next_activity = _parse_date(p.get("hs_next_activity_date"))

        days_since = (today - last_activity).days if last_activity else None
        has_future_task = next_activity is not None and next_activity >= today

        # Primary rotting signal: no activity within threshold.
        # "no future task" is shown as secondary info but doesn't independently
        # flag a lead — hs_next_activity_date is not consistently populated in
        # Leadle's HubSpot setup, so using it as a sole gate produces noise.
        no_recent_activity = days_since is None or days_since > threshold_days

        row = {
            "id": lead.get("id"),
            "lead_name": p.get("hs_lead_name") or contact_name,
            "contact_name": contact_name,
            "company": p.get("hs_associated_company_name") or "—",
            "stage_id": stage_id,
            "stage_name": stage_name,
            "last_activity": last_activity.isoformat() if last_activity else None,
            "next_activity": next_activity.isoformat() if next_activity else None,
            "days_since": days_since,
            "has_future_task": has_future_task,
            "no_recent_activity": no_recent_activity,
        }

        if no_recent_activity:
            rotting.append(row)
        else:
            healthy.append(row)

    # Sort rotting: leads with no activity date first (worst), then by days_since desc.
    rotting.sort(key=lambda r: (r["days_since"] is not None, -(r["days_since"] or 9999)))

    # Per-stage breakdown of rotting leads.
    stage_counts: dict[str, int] = {}
    for r in rotting:
        stage_counts[r["stage_name"]] = stage_counts.get(r["stage_name"], 0) + 1

    return {
        "total_active": len(raw_leads),
        "rotting": rotting,
        "healthy": len(healthy),
        "stage_breakdown": stage_counts,
        "threshold_days": threshold_days,
        "today": today.isoformat(),
    }


# ── HTML render ───────────────────────────────────────────────────────────────

def _days_badge(days: int | None) -> str:
    if days is None:
        return '<span style="color:#9b2226;font-weight:600">Never</span>'
    if days == 0:
        return '<span style="color:#2d6a4f;font-weight:600">Today</span>'
    if days == 1:
        return '<span style="color:#2d6a4f">Yesterday</span>'
    if days <= 3:
        return f'<span style="color:#b45309">{days}d ago</span>'
    return f'<span style="color:#9b2226;font-weight:600">{days}d ago</span>'


def _task_badge(has_future: bool, next_date: str | None) -> str:
    if has_future and next_date:
        return f'<span style="color:#2d6a4f">✓ {next_date}</span>'
    return '<span style="color:#9b2226">None scheduled</span>'


def render_html(report: dict, generated_at: str) -> str:
    rotting = report["rotting"]
    threshold = report["threshold_days"]
    rot_pct = round(len(rotting) / max(report["total_active"], 1) * 100)

    # Stage breakdown pills.
    stage_pills = ""
    for stage, count in sorted(report["stage_breakdown"].items(), key=lambda x: -x[1]):
        stage_pills += f'<span style="background:#f3f4f6;border:1px solid #e5e7eb;border-radius:4px;padding:3px 10px;font-size:12px;margin:3px">{stage}: <strong>{count}</strong></span>'

    # Rows.
    rows_html = ""
    for r in rotting:
        task_info = (
            f'<span style="color:#2d6a4f;font-size:11px">task {r["next_activity"]}</span>'
            if r["has_future_task"] and r["next_activity"]
            else '<span style="color:#6b7280;font-size:11px">no task</span>'
        )
        reason_html = f'<span style="background:#fff1f2;color:#9b2226;border-radius:3px;padding:1px 6px;font-size:11px">no activity >{threshold}d</span> {task_info}'
        rows_html += f"""
        <tr>
          <td style="padding:10px 14px">
            <div style="font-weight:500">{r['lead_name']}</div>
            <div style="font-size:12px;color:#6b7280">{r['company']}</div>
          </td>
          <td style="padding:10px 14px;font-size:12px;color:#374151">{r['stage_name']}</td>
          <td style="padding:10px 14px">{_days_badge(r['days_since'])}</td>
          <td style="padding:10px 14px">{_task_badge(r['has_future_task'], r['next_activity'])}</td>
          <td style="padding:10px 14px">{reason_html}</td>
        </tr>"""

    empty = "" if rotting else '<tr><td colspan="5" style="padding:24px;text-align:center;color:#6b7280">No rotting leads. Pipeline is healthy.</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lead Pipeline Rotting — Leadle</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Fraunces:ital,wght@0,400;0,600;1,400&family=Inter+Tight:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');
  :root{{--bg:#fafaf7;--surface:#fff;--ink:#15171a;--green:#2d6a4f;--amber:#b45309;--red:#9b2226;--muted:#6b7280;--border:#e5e7eb}}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:var(--bg);color:var(--ink);font-family:'Inter Tight',sans-serif;font-size:14px;line-height:1.5;padding:32px 24px}}
  .wrap{{max-width:900px;margin:0 auto}}
  h1{{font-family:'Fraunces',serif;font-size:26px;font-weight:600;margin-bottom:4px}}
  .meta{{color:var(--muted);font-size:12px;margin-bottom:28px}}
  .stat-row{{display:flex;gap:16px;margin-bottom:20px}}
  .stat{{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:14px 18px;flex:1}}
  .stat-n{{font-family:'JetBrains Mono',monospace;font-size:24px;font-weight:500}}
  .stat-l{{font-size:11px;color:var(--muted);margin-top:2px;text-transform:uppercase;letter-spacing:.04em}}
  .card{{background:var(--surface);border-radius:10px;border:1px solid var(--border);overflow:hidden;margin-bottom:20px}}
  .card-title{{padding:14px 16px;font-weight:600;font-size:13px;border-bottom:1px solid var(--border);background:#f9fafb}}
  table{{width:100%;border-collapse:collapse}}
  thead th{{background:#f3f4f6;padding:10px 14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);font-weight:600}}
  tbody tr:not(:last-child){{border-bottom:1px solid var(--border)}}
  tbody tr:hover{{background:#f9fafb}}
</style>
</head>
<body>
<div class="wrap">
  <h1>Lead Pipeline Rotting</h1>
  <div class="meta">Leadle RevOps &bull; Active leads only &bull; Threshold: {threshold}d no activity &bull; Generated {generated_at}</div>

  <div class="stat-row">
    <div class="stat">
      <div class="stat-n">{report['total_active']}</div>
      <div class="stat-l">Active Leads</div>
    </div>
    <div class="stat">
      <div class="stat-n" style="color:var(--{'red' if len(rotting) > 0 else 'green'})">{len(rotting)}</div>
      <div class="stat-l">Rotting</div>
    </div>
    <div class="stat">
      <div class="stat-n" style="color:var(--{'red' if rot_pct > 50 else 'amber' if rot_pct > 20 else 'green'})">{rot_pct}%</div>
      <div class="stat-l">Rotting Rate</div>
    </div>
    <div class="stat">
      <div class="stat-n" style="color:var(--green)">{report['healthy']}</div>
      <div class="stat-l">Healthy</div>
    </div>
  </div>

  <div class="card" style="padding:14px 16px;margin-bottom:20px">
    <div style="font-size:12px;color:var(--muted);margin-bottom:8px;text-transform:uppercase;letter-spacing:.04em;font-weight:600">By Stage</div>
    <div>{stage_pills or '<span style="color:var(--muted);font-size:13px">—</span>'}</div>
  </div>

  <div class="card">
    <div class="card-title">Rotting Leads — sorted by staleness</div>
    <table>
      <thead>
        <tr>
          <th>Lead / Company</th>
          <th>Stage</th>
          <th>Last Activity</th>
          <th>Next Task</th>
          <th>Why Rotting</th>
        </tr>
      </thead>
      <tbody>{rows_html}{empty}</tbody>
    </table>
  </div>

  <div style="font-size:11px;color:var(--muted);margin-top:8px">
    "Last Activity" uses hs_contact_last_activity_date (falls back to hs_lastmodifieddate).
    "Next Task" uses hs_next_activity_date.
    Archived and advanced-to-deal leads excluded.
  </div>
</div>
</body>
</html>"""


# ── CLI ───────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    from dotenv import load_dotenv
    load_dotenv()

    parser = argparse.ArgumentParser(prog="analytics.lead_pipeline_rotting")
    parser.add_argument("--threshold", type=int, help="Override days-without-activity threshold from config")
    parser.add_argument("--out", help="Output HTML path. Defaults to reports/lead-pipeline-rotting-<date>.html")
    args = parser.parse_args(argv)

    token = os.environ.get("HUBSPOT_PRIVATE_TOKEN")
    if not token:
        print("ERROR: HUBSPOT_PRIVATE_TOKEN not set", file=sys.stderr)
        return 1

    cfg = _load_config()
    threshold = args.threshold if args.threshold is not None else cfg["rotting"]["lead_no_activity_days"]
    non_rotting = _non_rotting_stage_ids(cfg)
    rotting_stage_ids = {s["stage_id"] for s in cfg["leads"]["stages"]} - non_rotting
    stage_map = _stage_map(cfg)

    print(f"Fetching leads in {len(rotting_stage_ids)} active stage(s)...", file=sys.stderr)
    raw = fetch_active_leads(token, rotting_stage_ids)
    print(f"  {len(raw)} active leads fetched", file=sys.stderr)

    report = compute_rotting(raw, threshold, stage_map)

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    html = render_html(report, generated_at)

    out_path = args.out
    if not out_path:
        slug = date.today().isoformat()
        reports_dir = Path(__file__).parent.parent / "reports"
        reports_dir.mkdir(exist_ok=True)
        out_path = str(reports_dir / f"lead-pipeline-rotting-{slug}.html")

    Path(out_path).write_text(html, encoding="utf-8")
    print(f"Report written to {out_path}", file=sys.stderr)

    rotting = report["rotting"]
    print(f"\nLead Pipeline Rotting ({date.today()})")
    print(f"  Active: {report['total_active']}  Rotting: {len(rotting)}  Healthy: {report['healthy']}")
    if rotting:
        print(f"  By stage: {dict(sorted(report['stage_breakdown'].items(), key=lambda x: -x[1]))}")
        print(f"  Worst: {rotting[0]['lead_name']} — {rotting[0]['company']} ({rotting[0]['days_since'] or 'Never'}d since activity)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
