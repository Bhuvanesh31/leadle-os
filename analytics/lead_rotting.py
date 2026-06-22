"""Lead rotting analysis — all active leads, both inbound and outbound. Process #10.

Two independent rot signals:
  activity_stalled  — no logged activity for >= stalled_lead_days (from dashboard_rules.yaml)
  stage_stuck       — in same pipeline stage for >= lead_stage_stuck_days

A lead can be activity-stalled but progressing (Sai emailed yesterday but it's been 3
weeks in New Lead). Or it can be stage-stuck but recently emailed. Both are rot signals;
the combination is critical.

Severity:
  CRITICAL  — both signals firing
  STALLED   — only activity-stalled
  STUCK     — only stage-stuck
  OK        — neither (fresh and progressing)

Thresholds from config/dashboard_rules.yaml (edit there, not here).
Stage-entered dates from config/hubspot_pipeline.yaml → hs_v2_date_entered_* properties.

Outputs:
  --json FILE   machine-readable report
  --out  FILE   HTML report

Usage:
    python -m analytics.lead_rotting
    python -m analytics.lead_rotting --json /tmp/lead_rotting.json
"""

from __future__ import annotations

import argparse
import html as _html
import json
import os
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import yaml

_REPORTS_DIR = Path(__file__).parent.parent / "reports"
_PIPELINE_CFG = Path(__file__).parent.parent / "config" / "hubspot_pipeline.yaml"
_RULES_CFG = Path(__file__).parent.parent / "config" / "dashboard_rules.yaml"
_INBOUND_CFG = Path(__file__).parent.parent / "config" / "inbound_scoring.yaml"
_OUTBOUND_CFG = Path(__file__).parent.parent / "config" / "outbound_scoring.yaml"


def _load_configs() -> tuple[dict, dict, set[str], set[str]]:
    with open(_PIPELINE_CFG) as f:
        pipeline = yaml.safe_load(f)
    with open(_RULES_CFG) as f:
        rules = yaml.safe_load(f)
    with open(_INBOUND_CFG) as f:
        inbound = yaml.safe_load(f)
    with open(_OUTBOUND_CFG) as f:
        outbound = yaml.safe_load(f)
    inbound_set = set(inbound.get("inbound_sources", []))
    outbound_set = set(outbound.get("outbound_sources", []))
    return pipeline, rules, inbound_set, outbound_set


def _stage_meta(pipeline: dict) -> tuple[dict[str, str], dict[str, str], set[str]]:
    """Return (stage_id→name, stage_id→prop, active_stage_ids)."""
    stage_names: dict[str, str] = {}
    stage_props: dict[str, str] = {}
    active_ids: set[str] = set()
    for stage in pipeline["leads"]["stages"]:
        sid = stage["stage_id"]
        stage_names[sid] = stage["name"]
        stage_props[sid] = stage.get("prop", "")
        if not stage.get("terminal", False) and stage.get("rotting", False):
            active_ids.add(sid)
    return stage_names, stage_props, active_ids


def _days_since(ts_str: str | None) -> int | None:
    if not ts_str:
        return None
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        now = datetime.now(tz=UTC)
        return max(0, (now - dt).days)
    except ValueError:
        return None


def _fetch_active_leads(
    token: str, active_ids: set[str], stage_props: dict[str, str]
) -> list[dict]:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    base_props = [
        "hs_lead_name",
        "lead_source_v2",
        "hs_pipeline_stage",
        "hs_contact_last_activity_date",
        "hs_createdate",
        "hs_associated_company_name",
        "hs_associated_contact_firstname",
        "hs_associated_contact_lastname",
    ]
    # Include all stage-entered date properties to compute days_in_stage
    stage_date_props = [p for p in stage_props.values() if p]
    all_props = list(dict.fromkeys(base_props + stage_date_props))

    results = []
    after = None
    while True:
        body: dict = {
            "filterGroups": [
                {
                    "filters": [
                        {
                            "propertyName": "hs_pipeline_stage",
                            "operator": "IN",
                            "values": list(active_ids),
                        },
                    ]
                }
            ],
            "properties": all_props,
            "limit": 100,
        }
        if after:
            body["after"] = after
        r = httpx.post(
            "https://api.hubapi.com/crm/v3/objects/leads/search",
            headers=headers,
            json=body,
            timeout=30,
        )
        data = r.json()
        results.extend(data.get("results", []))
        after = (data.get("paging") or {}).get("next", {}).get("after")
        if not after:
            break
    return results


def _classify_source(src: str | None, inbound_set: set[str], outbound_set: set[str]) -> str:
    src = src or ""
    if src in outbound_set:
        return "Outbound"
    return "Inbound"


def _severity(stalled: bool, stuck: bool) -> str:
    if stalled and stuck:
        return "CRITICAL"
    if stalled:
        return "STALLED"
    if stuck:
        return "STUCK"
    return "OK"


_SEV_ORDER = {"CRITICAL": 0, "STALLED": 1, "STUCK": 2, "OK": 3}


def build_report(
    leads: list[dict],
    pipeline: dict,
    rules: dict,
    inbound_set: set[str],
    outbound_set: set[str],
) -> dict:
    stage_names, stage_props, _ = _stage_meta(pipeline)
    stalled_thresh = rules.get("stalled_lead_days", 5)
    stuck_thresh = rules.get("lead_stage_stuck_days", 14)

    rows = []
    severity_counts: dict[str, int] = {"CRITICAL": 0, "STALLED": 0, "STUCK": 0, "OK": 0}

    for lead in leads:
        p = lead.get("properties") or {}
        stage_id = p.get("hs_pipeline_stage") or ""
        stage_name = stage_names.get(stage_id, stage_id)
        stage_prop = stage_props.get(stage_id, "")

        days_activity = _days_since(p.get("hs_contact_last_activity_date"))
        days_in_stage = _days_since(p.get(stage_prop)) if stage_prop else None

        stalled = days_activity is not None and days_activity >= stalled_thresh
        stuck = days_in_stage is not None and days_in_stage >= stuck_thresh
        sev = _severity(stalled, stuck)
        severity_counts[sev] += 1

        src = p.get("lead_source_v2") or ""
        fn = p.get("hs_associated_contact_firstname") or ""
        ln = p.get("hs_associated_contact_lastname") or ""
        contact_name = (fn + " " + ln).strip() or "—"

        rows.append(
            {
                "lead_name": p.get("hs_lead_name") or "(unnamed)",
                "contact_name": contact_name,
                "company": p.get("hs_associated_company_name") or "—",
                "source": src,
                "channel": _classify_source(src, inbound_set, outbound_set),
                "stage_name": stage_name,
                "days_since_activity": days_activity,
                "days_in_stage": days_in_stage,
                "is_stalled": stalled,
                "is_stuck": stuck,
                "severity": sev,
            }
        )

    rows.sort(key=lambda r: (_SEV_ORDER[r["severity"]], -(r["days_in_stage"] or 0)))

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "thresholds": {
            "stalled_lead_days": stalled_thresh,
            "lead_stage_stuck_days": stuck_thresh,
        },
        "total_active": len(leads),
        "severity_counts": severity_counts,
        "leads": rows,
    }


# ── HTML render ───────────────────────────────────────────────────────────────


def _sev_badge(sev: str) -> str:
    colors = {
        "CRITICAL": ("background:#fef2f2;color:#9b2226", "CRITICAL"),
        "STALLED": ("background:#fffbeb;color:#b45309", "STALLED"),
        "STUCK": ("background:#eff6ff;color:#1e40af", "STUCK"),
        "OK": ("background:#f0fdf4;color:#2d6a4f", "OK"),
    }
    style, label = colors.get(sev, ("", sev))
    return f'<span style="{style};border-radius:4px;padding:2px 7px;font-size:11px;font-weight:600">{label}</span>'


def _days_cell(days: int | None, threshold: int, bad_color: str) -> str:
    if days is None:
        return '<span style="color:#9ca3af">—</span>'
    color = bad_color if days >= threshold else "#374151"
    return f"<span style=\"color:{color};font-family:'JetBrains Mono',monospace;font-size:12px\">{days}d</span>"


def render_html(report: dict) -> str:
    sc = report["severity_counts"]
    thresh = report["thresholds"]
    rows_html = ""

    for r in report["leads"]:
        if r["severity"] == "OK":
            continue  # OK leads don't need to appear in the rotting report
        lead_name = _html.escape(r["lead_name"])
        company = _html.escape(r["company"])
        source = _html.escape(r["source"] or "(untracked)")
        rows_html += f"""
        <tr>
          <td style="padding:10px 14px">
            <div style="font-weight:500;font-size:13px">{lead_name}</div>
            <div style="font-size:12px;color:#6b7280">{company}</div>
          </td>
          <td style="padding:10px 14px">{_sev_badge(r["severity"])}</td>
          <td style="padding:10px 14px">
            <span style="font-size:12px;color:{"#1e40af" if r["channel"] == "Outbound" else "#2d6a4f"};font-weight:500">{r["channel"]}</span>
            <div style="font-size:11px;color:#9ca3af">{source}</div>
          </td>
          <td style="padding:10px 14px;font-size:12px;color:#374151">{r["stage_name"]}</td>
          <td style="padding:10px 14px">{_days_cell(r["days_since_activity"], thresh["stalled_lead_days"], "#9b2226")}</td>
          <td style="padding:10px 14px">{_days_cell(r["days_in_stage"], thresh["lead_stage_stuck_days"], "#1e40af")}</td>
        </tr>"""

    ok_count = sc.get("OK", 0)
    no_rot = (
        f'<tr><td colspan="6" style="padding:20px;text-align:center;color:#6b7280;font-size:12px">'
        f"All {ok_count} active leads are fresh. No rot detected.</td></tr>"
        if not rows_html
        else ""
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lead Rotting — Leadle</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Fraunces:ital,wght@0,400;0,600;1,400&family=Inter+Tight:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');
  :root{{--bg:#fafaf7;--surface:#fff;--ink:#15171a;--red:#9b2226;--amber:#b45309;--blue:#1e40af;--green:#2d6a4f;--muted:#6b7280;--border:#e5e7eb}}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:var(--bg);color:var(--ink);font-family:'Inter Tight',sans-serif;font-size:14px;line-height:1.5;padding:32px 24px}}
  .wrap{{max-width:1100px;margin:0 auto}}
  h1{{font-family:'Fraunces',serif;font-size:26px;font-weight:600;margin-bottom:4px}}
  .meta{{color:var(--muted);font-size:12px;margin-bottom:28px}}
  .stat-row{{display:flex;gap:16px;margin-bottom:20px}}
  .stat{{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:14px 18px;flex:1}}
  .stat-n{{font-family:'JetBrains Mono',monospace;font-size:22px;font-weight:500}}
  .stat-l{{font-size:11px;color:var(--muted);margin-top:2px;text-transform:uppercase;letter-spacing:.04em}}
  .card{{background:var(--surface);border-radius:10px;border:1px solid var(--border);overflow:hidden;margin-bottom:20px}}
  .card-title{{padding:12px 16px;font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.05em;border-bottom:1px solid var(--border);background:#f9fafb;color:var(--muted)}}
  .legend{{padding:12px 16px;font-size:12px;color:var(--muted);border-bottom:1px solid var(--border);background:#fafaf7}}
  table{{width:100%;border-collapse:collapse}}
  thead th{{background:#f3f4f6;padding:9px 14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);font-weight:600}}
  tbody tr:not(:last-child){{border-bottom:1px solid var(--border)}}
  tbody tr:hover{{background:#f9fafb}}
</style>
</head>
<body>
<div class="wrap">
  <h1>Lead Rotting</h1>
  <div class="meta">Leadle RevOps &bull; All active leads (inbound + outbound) &bull; Generated {report["generated_at"]}</div>

  <div class="stat-row">
    <div class="stat">
      <div class="stat-n">{report["total_active"]}</div>
      <div class="stat-l">Active Leads</div>
    </div>
    <div class="stat">
      <div class="stat-n" style="color:var(--red)">{sc.get("CRITICAL", 0)}</div>
      <div class="stat-l">Critical (both signals)</div>
    </div>
    <div class="stat">
      <div class="stat-n" style="color:var(--amber)">{sc.get("STALLED", 0)}</div>
      <div class="stat-l">Stalled (no activity ≥{thresh["stalled_lead_days"]}d)</div>
    </div>
    <div class="stat">
      <div class="stat-n" style="color:var(--blue)">{sc.get("STUCK", 0)}</div>
      <div class="stat-l">Stuck (same stage ≥{thresh["lead_stage_stuck_days"]}d)</div>
    </div>
    <div class="stat">
      <div class="stat-n" style="color:var(--green)">{sc.get("OK", 0)}</div>
      <div class="stat-l">OK (fresh)</div>
    </div>
  </div>

  <div class="card">
    <div class="card-title">Rotting Leads — Ranked by Severity</div>
    <div class="legend">
      <strong>CRITICAL</strong> = stalled (no activity ≥{thresh["stalled_lead_days"]}d) AND stage-stuck (≥{thresh["lead_stage_stuck_days"]}d in same stage) &bull;
      <strong>STALLED</strong> = only no-activity signal &bull;
      <strong>STUCK</strong> = only stage-progression signal &bull;
      OK leads hidden.
    </div>
    <table>
      <thead>
        <tr>
          <th>Lead / Company</th>
          <th>Severity</th>
          <th>Channel</th>
          <th>Stage</th>
          <th>Last Activity</th>
          <th>Days in Stage</th>
        </tr>
      </thead>
      <tbody>{rows_html}{no_rot}</tbody>
    </table>
  </div>
</div>
</body>
</html>"""


# ── main ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="analytics.lead_rotting")
    parser.add_argument("--json", metavar="FILE", help="Dump report JSON to this path")
    parser.add_argument("--out", metavar="FILE", help="Output HTML path")
    args = parser.parse_args(argv)

    token = os.environ.get("HUBSPOT_PRIVATE_TOKEN")
    if not token:
        print("ERROR: HUBSPOT_PRIVATE_TOKEN not set", file=sys.stderr)
        return 1

    pipeline, rules, inbound_set, outbound_set = _load_configs()
    _, stage_props, active_ids = _stage_meta(pipeline)

    print("Fetching active leads...", file=sys.stderr)
    leads = _fetch_active_leads(token, active_ids, stage_props)
    print(f"  {len(leads)} active leads", file=sys.stderr)

    report = build_report(leads, pipeline, rules, inbound_set, outbound_set)
    sc = report["severity_counts"]
    thresh = report["thresholds"]

    print(f"\nLead Rotting — {report['generated_at']}")
    print(
        f"  Active: {report['total_active']}  |  "
        f"Critical: {sc['CRITICAL']}  Stalled: {sc['STALLED']}  "
        f"Stuck: {sc['STUCK']}  OK: {sc['OK']}"
    )
    print(
        f"  Thresholds: stalled>={thresh['stalled_lead_days']}d activity  "
        f"stuck>={thresh['lead_stage_stuck_days']}d in stage"
    )

    critical = [r for r in report["leads"] if r["severity"] == "CRITICAL"]
    if critical:
        print(f"  Critical leads ({len(critical)}):")
        for r in critical:
            print(
                f"    → {r['lead_name']} / {r['company']}  "
                f"[{r['stage_name']}]  "
                f"activity={r['days_since_activity']}d  "
                f"in_stage={r['days_in_stage']}d  "
                f"({r['channel']})"
            )

    stalled = [r for r in report["leads"] if r["severity"] == "STALLED"]
    if stalled:
        print(f"  Stalled (activity only, {len(stalled)}):")
        for r in stalled:
            print(f"    → {r['lead_name']} / {r['company']}  activity={r['days_since_activity']}d")

    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Report JSON → {args.json}", file=sys.stderr)

    html = render_html(report)
    out_path = args.out
    if not out_path:
        slug = date.today().isoformat()
        _REPORTS_DIR.mkdir(exist_ok=True)
        out_path = str(_REPORTS_DIR / f"lead-rotting-{slug}.html")
    Path(out_path).write_text(html, encoding="utf-8")
    print(f"Report → {out_path}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
