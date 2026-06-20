"""Deal pipeline rotting — Leadle's Sales Pipeline (id=1906293444).

Flags active deals going cold:
  • No activity in the past N days (default: 4, set in config/hubspot_pipeline.yaml)

Only active (non-Won, non-Lost) deals in the Sales Pipeline are evaluated.
Outputs a Leadle-branded HTML report sorted by staleness (worst first).
Close-date overdue is surfaced as an urgency flag.

Usage:
    python -m analytics.deal_pipeline_rotting
    python -m analytics.deal_pipeline_rotting --out /tmp/rotting-deals.html
    python -m analytics.deal_pipeline_rotting --threshold 2   # override days
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml

_BASE_URL = "https://api.hubapi.com"
_PAGE_LIMIT = 100
_CONFIG_PATH = Path(__file__).parent.parent / "config" / "hubspot_pipeline.yaml"

_DEAL_PROPS = [
    "dealname",
    "pipeline",
    "dealstage",
    "amount",
    "closedate",
    "createdate",
    "notes_last_contacted",
    "hs_lastmodifieddate",
    "hs_next_activity_date",
    "hubspot_owner_id",
]


# ── config ────────────────────────────────────────────────────────────────────

def _load_config() -> dict:
    with open(_CONFIG_PATH) as f:
        return yaml.safe_load(f)


def _deal_stage_map(cfg: dict) -> dict[str, str]:
    return {s["stage_id"]: s["name"] for s in cfg["deals"]["stages"]}


def _rotting_stage_ids(cfg: dict) -> list[str]:
    return [s["stage_id"] for s in cfg["deals"]["stages"] if s.get("rotting", True)]


# ── HubSpot fetch ─────────────────────────────────────────────────────────────

def fetch_active_deals(token: str, pipeline_id: str, rotting_ids: list[str]) -> list[dict]:
    """Return deal records that are in active (rotting-eligible) stages of the Sales Pipeline."""
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    out: list[dict] = []
    after: str | None = None

    with httpx.Client(headers=headers, timeout=30.0) as client:
        while True:
            body: dict[str, Any] = {
                "filterGroups": [{
                    "filters": [
                        {"propertyName": "pipeline", "operator": "EQ", "value": pipeline_id},
                        {"propertyName": "dealstage", "operator": "IN", "values": rotting_ids},
                    ]
                }],
                "properties": _DEAL_PROPS,
                "sorts": [{"propertyName": "notes_last_contacted", "direction": "ASCENDING"}],
                "limit": _PAGE_LIMIT,
            }
            if after:
                body["after"] = after
            r = client.post(f"{_BASE_URL}/crm/v3/objects/deals/search", json=body)
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
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _fmt_amount(s: str | None) -> str:
    if not s:
        return "—"
    try:
        return f"₹{float(s):,.0f}"
    except ValueError:
        return s


def compute_rotting(raw_deals: list[dict], threshold_days: int, stage_map: dict[str, str]) -> dict:
    today = date.today()
    rotting: list[dict] = []
    healthy: list[dict] = []

    for deal in raw_deals:
        p = deal.get("properties", {})

        stage_id = p.get("dealstage") or ""
        stage_name = stage_map.get(stage_id, stage_id or "Unknown")

        # notes_last_contacted = human-triggered only (calls, meetings logged by Sai).
        # Fallback: hs_lastmodifieddate catches automated touches but is noisier.
        last_activity = (
            _parse_date(p.get("notes_last_contacted"))
            or _parse_date(p.get("hs_lastmodifieddate"))
        )
        next_activity = _parse_date(p.get("hs_next_activity_date"))
        close_date = _parse_date(p.get("closedate"))

        days_since = (today - last_activity).days if last_activity else None
        has_future_task = next_activity is not None and next_activity >= today
        close_overdue = close_date is not None and close_date < today

        no_recent_activity = days_since is None or days_since > threshold_days

        row = {
            "id": deal.get("id"),
            "deal_name": p.get("dealname") or "—",
            "stage_id": stage_id,
            "stage_name": stage_name,
            "amount": _fmt_amount(p.get("amount")),
            "close_date": close_date.isoformat() if close_date else None,
            "close_overdue": close_overdue,
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

    # Sort: no-activity-ever first, then by days_since descending.
    rotting.sort(key=lambda r: (r["days_since"] is not None, -(r["days_since"] or 9999)))

    stage_counts: dict[str, int] = {}
    for r in rotting:
        stage_counts[r["stage_name"]] = stage_counts.get(r["stage_name"], 0) + 1

    overdue_count = sum(1 for r in rotting if r["close_overdue"])

    return {
        "total_active": len(raw_deals),
        "rotting": rotting,
        "healthy": len(healthy),
        "stage_breakdown": stage_counts,
        "threshold_days": threshold_days,
        "overdue_count": overdue_count,
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


def _close_badge(close_date: str | None, overdue: bool) -> str:
    if not close_date:
        return '<span style="color:#6b7280">—</span>'
    if overdue:
        return f'<span style="color:#9b2226;font-weight:600">⚠ {close_date}</span>'
    return f'<span style="color:#374151">{close_date}</span>'


def render_html(report: dict, generated_at: str) -> str:
    rotting = report["rotting"]
    threshold = report["threshold_days"]
    rot_pct = round(len(rotting) / max(report["total_active"], 1) * 100)

    stage_pills = ""
    for stage, count in sorted(report["stage_breakdown"].items(), key=lambda x: -x[1]):
        stage_pills += (
            f'<span style="background:#f3f4f6;border:1px solid #e5e7eb;border-radius:4px;'
            f'padding:3px 10px;font-size:12px;margin:3px">{stage}: <strong>{count}</strong></span>'
        )

    rows_html = ""
    for r in rotting:
        task_info = (
            f'<span style="color:#2d6a4f;font-size:11px">task {r["next_activity"]}</span>'
            if r["has_future_task"] and r["next_activity"]
            else '<span style="color:#6b7280;font-size:11px">no task</span>'
        )
        reason_html = (
            f'<span style="background:#fff1f2;color:#9b2226;border-radius:3px;'
            f'padding:1px 6px;font-size:11px">no activity >{threshold}d</span> {task_info}'
        )
        overdue_flag = (
            ' <span style="background:#fef3c7;color:#92400e;border-radius:3px;'
            'padding:1px 5px;font-size:10px;margin-left:4px">CLOSE OVERDUE</span>'
            if r["close_overdue"] else ""
        )
        rows_html += f"""
        <tr>
          <td style="padding:10px 14px">
            <div style="font-weight:500">{r['deal_name']}{overdue_flag}</div>
            <div style="font-size:12px;color:#6b7280">{r['amount']}</div>
          </td>
          <td style="padding:10px 14px;font-size:12px;color:#374151">{r['stage_name']}</td>
          <td style="padding:10px 14px">{_days_badge(r['days_since'])}</td>
          <td style="padding:10px 14px">{_close_badge(r['close_date'], r['close_overdue'])}</td>
          <td style="padding:10px 14px">{reason_html}</td>
        </tr>"""

    empty = (
        "" if rotting
        else '<tr><td colspan="5" style="padding:24px;text-align:center;color:#6b7280">'
             'No rotting deals. Pipeline is healthy.</td></tr>'
    )

    overdue_banner = ""
    if report["overdue_count"] > 0:
        overdue_banner = f"""
      <div style="background:#fffbeb;border:1px solid #fde68a;border-radius:8px;padding:12px 16px;margin-bottom:20px">
        <span style="color:#92400e;font-weight:600">{report['overdue_count']} deal{'s' if report['overdue_count'] != 1 else ''} past expected close date</span>
        <span style="color:#78350f;font-size:13px"> — close dates need updating or deal needs a push.</span>
      </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Deal Pipeline Rotting — Leadle</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Fraunces:ital,wght@0,400;0,600;1,400&family=Inter+Tight:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');
  :root{{--bg:#fafaf7;--surface:#fff;--ink:#15171a;--green:#2d6a4f;--amber:#b45309;--red:#9b2226;--blue:#1e40af;--muted:#6b7280;--border:#e5e7eb}}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:var(--bg);color:var(--ink);font-family:'Inter Tight',sans-serif;font-size:14px;line-height:1.5;padding:32px 24px}}
  .wrap{{max-width:960px;margin:0 auto}}
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
  <h1>Deal Pipeline Rotting</h1>
  <div class="meta">Leadle RevOps &bull; Sales Pipeline &bull; Threshold: {threshold}d no activity &bull; Generated {generated_at}</div>

  <div class="stat-row">
    <div class="stat">
      <div class="stat-n">{report['total_active']}</div>
      <div class="stat-l">Active Deals</div>
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
    <div class="stat">
      <div class="stat-n" style="color:var(--{'amber' if report['overdue_count'] > 0 else 'muted'})">{report['overdue_count']}</div>
      <div class="stat-l">Close Overdue</div>
    </div>
  </div>

  {overdue_banner}

  <div class="card" style="padding:14px 16px;margin-bottom:20px">
    <div style="font-size:12px;color:var(--muted);margin-bottom:8px;text-transform:uppercase;letter-spacing:.04em;font-weight:600">By Stage</div>
    <div>{stage_pills or '<span style="color:var(--muted);font-size:13px">—</span>'}</div>
  </div>

  <div class="card">
    <div class="card-title">Rotting Deals — sorted by staleness</div>
    <table>
      <thead>
        <tr>
          <th>Deal / Value</th>
          <th>Stage</th>
          <th>Last Activity</th>
          <th>Expected Close</th>
          <th>Why Rotting</th>
        </tr>
      </thead>
      <tbody>{rows_html}{empty}</tbody>
    </table>
  </div>

  <div style="font-size:11px;color:var(--muted);margin-top:8px">
    "Last Activity" uses notes_last_contacted (human-triggered), falls back to hs_lastmodifieddate.
    Won and Lost deals excluded. Sales Pipeline only.
  </div>
</div>
</body>
</html>"""


# ── CLI ───────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    from dotenv import load_dotenv
    load_dotenv()

    parser = argparse.ArgumentParser(prog="analytics.deal_pipeline_rotting")
    parser.add_argument("--threshold", type=int, help="Override days-without-activity threshold from config")
    parser.add_argument("--out", help="Output HTML path. Defaults to reports/deal-pipeline-rotting-<date>.html")
    args = parser.parse_args(argv)

    token = os.environ.get("HUBSPOT_PRIVATE_TOKEN")
    if not token:
        print("ERROR: HUBSPOT_PRIVATE_TOKEN not set", file=sys.stderr)
        return 1

    cfg = _load_config()
    threshold = args.threshold if args.threshold is not None else cfg["rotting"]["deal_no_activity_days"]
    pipeline_id = cfg["deals"]["pipeline_id"]
    stage_map = _deal_stage_map(cfg)
    rot_ids = _rotting_stage_ids(cfg)

    print(f"Fetching active deals in {len(rot_ids)} stage(s)...", file=sys.stderr)
    raw = fetch_active_deals(token, pipeline_id, rot_ids)
    print(f"  {len(raw)} active deals fetched", file=sys.stderr)

    report = compute_rotting(raw, threshold, stage_map)

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    html = render_html(report, generated_at)

    out_path = args.out
    if not out_path:
        slug = date.today().isoformat()
        reports_dir = Path(__file__).parent.parent / "reports"
        reports_dir.mkdir(exist_ok=True)
        out_path = str(reports_dir / f"deal-pipeline-rotting-{slug}.html")

    Path(out_path).write_text(html, encoding="utf-8")
    print(f"Report written to {out_path}", file=sys.stderr)

    rotting = report["rotting"]
    print(f"\nDeal Pipeline Rotting ({date.today()})")
    print(f"  Active: {report['total_active']}  Rotting: {len(rotting)}  Healthy: {report['healthy']}  Close Overdue: {report['overdue_count']}")
    if rotting:
        print(f"  By stage: {dict(sorted(report['stage_breakdown'].items(), key=lambda x: -x[1]))}")
        worst = rotting[0]
        print(f"  Worst: {worst['deal_name']} ({worst['days_since'] or 'Never'}d since activity) — {worst['stage_name']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
