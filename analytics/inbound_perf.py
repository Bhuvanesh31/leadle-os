"""Inbound lead funnel performance — process #13.

Measures how the inbound lead pipeline is converting over a time window.
Complements inbound_lead_analysis.py (current-state health) with a
funnel/conversion view: what came in, what was decided, and at what rate.

Three sections:
  new_leads       — leads created in the window, by source
  decisions       — leads advanced to deal OR archived in the window
                    (from any cohort — tracks when decisions were made)
  active_cohort   — leads created in the window still in active stages
                    (neither converted nor archived yet; shows pipeline lag)

Conversion rate = advances / (advances + archives) for leads with a decision.
Only inbound sources (config/inbound_scoring.yaml → inbound_sources) are counted.
Leads with unrecognised or null source are reported separately as "Unknown".

Outputs:
  --json FILE   machine-readable report
  --out  FILE   HTML report

Usage:
    python -m analytics.inbound_perf
    python -m analytics.inbound_perf --period last-month
    python -m analytics.inbound_perf --start 2026-05-01 --end 2026-05-31
    python -m analytics.inbound_perf --json /tmp/inbound_perf.json
"""
from __future__ import annotations

import argparse
import html as _html
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import yaml

from analytics._periods import add_period_args, resolve_args, resolve_period

_PIPELINE_CFG = Path(__file__).parent.parent / "config" / "hubspot_pipeline.yaml"
_INBOUND_CFG = Path(__file__).parent.parent / "config" / "inbound_scoring.yaml"
_REPORTS_DIR = Path(__file__).parent.parent / "reports"
_DEFAULT_PERIOD = "month"

_ADV_PROP = "hs_v2_date_entered_qualified_stage_id_233247981"
_ARCH_PROP = "hs_v2_date_entered_unqualified_stage_id_1675714327"


def _load_configs() -> tuple[dict, list[str]]:
    with open(_PIPELINE_CFG) as f:
        pipeline = yaml.safe_load(f)
    with open(_INBOUND_CFG) as f:
        inbound_cfg = yaml.safe_load(f)
    inbound_sources = [s.lower() for s in inbound_cfg.get("inbound_sources", [])]
    return pipeline, inbound_sources


def _stage_names(pipeline: dict) -> dict[str, str]:
    return {s["stage_id"]: s["name"] for s in pipeline["leads"]["stages"]}


def _date_to_epoch_ms(d: date) -> int:
    dt = datetime.combine(d, datetime.min.time(), tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _parse_date(ts_str: str | None) -> date | None:
    if not ts_str:
        return None
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _fetch_leads_in_lookback(token: str, lookback_start: date) -> list[dict]:
    """Fetch all leads created since lookback_start, plus any with decisions since lookback_start."""
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    cutoff_ms = str(_date_to_epoch_ms(lookback_start))

    props = [
        "hs_lead_name", "hs_pipeline_stage", "lead_source_v2",
        "hs_createdate", "hs_contact_company",
        _ADV_PROP, _ARCH_PROP,
    ]

    # Two passes: leads created in lookback AND leads with decisions in lookback
    # Union them by lead ID to avoid double-counting
    all_leads: dict[str, dict] = {}

    def _search(filters: list[dict]) -> None:
        after = None
        while True:
            body: dict = {
                "filterGroups": [{"filters": filters}],
                "properties": props,
                "limit": 100,
            }
            if after:
                body["after"] = after
            r = httpx.post(
                "https://api.hubapi.com/crm/v3/objects/leads/search",
                headers=headers, json=body, timeout=30,
            )
            data = r.json()
            for lead in data.get("results", []):
                all_leads[lead["id"]] = lead
            after = (data.get("paging") or {}).get("next", {}).get("after")
            if not after:
                break

    # Pass 1: created in lookback window
    _search([{"propertyName": "hs_createdate", "operator": "GTE", "value": cutoff_ms}])
    # Pass 2: advanced to deal in lookback window
    _search([{"propertyName": _ADV_PROP, "operator": "GTE", "value": cutoff_ms}])
    # Pass 3: archived in lookback window
    _search([{"propertyName": _ARCH_PROP, "operator": "GTE", "value": cutoff_ms}])

    return list(all_leads.values())


def _source_bucket(raw_source: str | None, inbound_sources: list[str]) -> str:
    if not raw_source:
        return "Unknown"
    if raw_source.lower() in inbound_sources:
        return raw_source
    return "Other / Outbound"


def build_report(leads: list[dict], pipeline: dict, inbound_sources: list[str],
                 window_start: date, window_end: date, window_label: str) -> dict:
    stage_names = _stage_names(pipeline)

    # Classify each lead against the window
    new_this_window: list[dict] = []
    advanced_this_window: list[dict] = []
    archived_this_window: list[dict] = []
    active_from_window: list[dict] = []  # created in window, still open

    for lead in leads:
        p = lead.get("properties") or {}
        created = _parse_date(p.get("hs_createdate"))
        adv_date = _parse_date(p.get(_ADV_PROP))
        arch_date = _parse_date(p.get(_ARCH_PROP))
        stage_id = p.get("hs_pipeline_stage") or ""
        source = p.get("lead_source_v2")
        bucket = _source_bucket(source, inbound_sources)
        name = p.get("hs_lead_name") or "(unnamed)"
        company = p.get("hs_contact_company") or "—"

        row = {
            "name": name,
            "company": company,
            "source": source or "(none)",
            "source_bucket": bucket,
            "stage": stage_names.get(stage_id, stage_id),
            "created": created.isoformat() if created else None,
            "adv_date": adv_date.isoformat() if adv_date else None,
            "arch_date": arch_date.isoformat() if arch_date else None,
        }

        if created and window_start <= created <= window_end:
            new_this_window.append(row)
            if not adv_date and not arch_date:
                active_from_window.append(row)

        if adv_date and window_start <= adv_date <= window_end:
            advanced_this_window.append(row)

        if arch_date and window_start <= arch_date <= window_end:
            archived_this_window.append(row)

    # Source-level breakdown for new leads
    source_new: dict[str, int] = {}
    for r in new_this_window:
        source_new[r["source_bucket"]] = source_new.get(r["source_bucket"], 0) + 1

    # Source-level decisions (advanced + archived) for conversion rate
    source_adv: dict[str, int] = {}
    source_arch: dict[str, int] = {}
    for r in advanced_this_window:
        source_adv[r["source_bucket"]] = source_adv.get(r["source_bucket"], 0) + 1
    for r in archived_this_window:
        source_arch[r["source_bucket"]] = source_arch.get(r["source_bucket"], 0) + 1

    all_decision_sources = sorted(set(list(source_adv.keys()) + list(source_arch.keys())))
    source_conversion = []
    for src in all_decision_sources:
        adv = source_adv.get(src, 0)
        arch = source_arch.get(src, 0)
        total = adv + arch
        rate = round(adv / total * 100, 1) if total > 0 else None
        source_conversion.append({
            "source": src,
            "advanced": adv,
            "archived": arch,
            "total_decided": total,
            "conversion_rate_pct": rate,
        })
    source_conversion.sort(key=lambda x: x["conversion_rate_pct"] or -1, reverse=True)

    total_adv = len(advanced_this_window)
    total_arch = len(archived_this_window)
    total_decided = total_adv + total_arch
    overall_rate = round(total_adv / total_decided * 100, 1) if total_decided > 0 else None

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "window": {
            "start": window_start.isoformat(),
            "end": window_end.isoformat(),
            "label": window_label,
        },
        "summary": {
            "new_leads": len(new_this_window),
            "advanced_to_deal": total_adv,
            "archived": total_arch,
            "total_decided": total_decided,
            "still_active_from_window": len(active_from_window),
            "overall_conversion_rate_pct": overall_rate,
        },
        "source_new_leads": [
            {"source": k, "count": v}
            for k, v in sorted(source_new.items(), key=lambda x: -x[1])
        ],
        "source_conversion": source_conversion,
        "advanced_leads": sorted(advanced_this_window, key=lambda r: r["adv_date"] or "", reverse=True),
        "archived_leads": sorted(archived_this_window, key=lambda r: r["arch_date"] or "", reverse=True),
        "active_from_window": active_from_window,
    }


# ── HTML render ───────────────────────────────────────────────────────────────

def _rate_cell(rate: float | None, warn_below: float = 30.0) -> str:
    if rate is None:
        return '<span style="color:#9ca3af">—</span>'
    color = "#9b2226" if rate < warn_below else "#2d6a4f" if rate >= 50 else "#374151"
    return f'<span style="color:{color};font-family:\'JetBrains Mono\',monospace;font-size:12px;font-weight:500">{rate:.1f}%</span>'


def _n(val: int) -> str:
    return f'<span style="font-family:\'JetBrains Mono\',monospace;font-size:12px">{val:,}</span>'


def render_html(report: dict) -> str:
    s = report["summary"]
    window = report["window"]
    rate_display = f"{s['overall_conversion_rate_pct']:.1f}%" if s["overall_conversion_rate_pct"] is not None else "—"
    rate_color = "#9b2226" if (s["overall_conversion_rate_pct"] or 0) < 30 else "#2d6a4f"

    # Source new-leads table
    src_new_rows = ""
    for row in report["source_new_leads"]:
        src = _html.escape(row["source"])
        src_new_rows += f'<tr><td style="padding:9px 14px;font-size:13px">{src}</td><td style="padding:9px 14px">{_n(row["count"])}</td></tr>'
    if not src_new_rows:
        src_new_rows = '<tr><td colspan="2" style="padding:16px;text-align:center;color:#9ca3af;font-size:12px">No new leads in window.</td></tr>'

    # Source conversion table
    conv_rows = ""
    for row in report["source_conversion"]:
        src = _html.escape(row["source"])
        conv_rows += f"""<tr>
          <td style="padding:9px 14px;font-size:13px">{src}</td>
          <td style="padding:9px 14px">{_n(row['advanced'])}</td>
          <td style="padding:9px 14px">{_n(row['archived'])}</td>
          <td style="padding:9px 14px">{_n(row['total_decided'])}</td>
          <td style="padding:9px 14px">{_rate_cell(row['conversion_rate_pct'])}</td>
        </tr>"""
    if not conv_rows:
        conv_rows = '<tr><td colspan="5" style="padding:16px;text-align:center;color:#9ca3af;font-size:12px">No decisions in window.</td></tr>'

    # Advanced leads table
    adv_rows = ""
    for r in report["advanced_leads"][:20]:
        name = _html.escape(r["name"])
        company = _html.escape(r["company"])
        src = _html.escape(r["source"])
        adv_rows += f"""<tr>
          <td style="padding:9px 14px">
            <div style="font-size:13px;font-weight:500">{name}</div>
            <div style="font-size:11px;color:#6b7280">{company}</div>
          </td>
          <td style="padding:9px 14px;font-size:12px;color:#6b7280">{src}</td>
          <td style="padding:9px 14px;font-size:12px;font-family:'JetBrains Mono',monospace">{r['adv_date'] or '—'}</td>
          <td style="padding:9px 14px;font-size:12px;color:#6b7280">{r['created'] or '—'}</td>
        </tr>"""
    if not adv_rows:
        adv_rows = '<tr><td colspan="4" style="padding:16px;text-align:center;color:#9ca3af;font-size:12px">No advances to deal in window.</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Inbound Lead Performance — Leadle</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Fraunces:ital,wght@0,400;0,600;1,400&family=Inter+Tight:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');
  :root{{--bg:#fafaf7;--surface:#fff;--ink:#15171a;--red:#9b2226;--amber:#b45309;--green:#2d6a4f;--muted:#6b7280;--border:#e5e7eb}}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:var(--bg);color:var(--ink);font-family:'Inter Tight',sans-serif;font-size:14px;line-height:1.5;padding:32px 24px}}
  .wrap{{max-width:1100px;margin:0 auto}}
  h1{{font-family:'Fraunces',serif;font-size:26px;font-weight:600;margin-bottom:4px}}
  .meta{{color:var(--muted);font-size:12px;margin-bottom:28px}}
  .stat-row{{display:flex;gap:16px;margin-bottom:20px}}
  .stat{{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:14px 18px;flex:1}}
  .stat-n{{font-family:'JetBrains Mono',monospace;font-size:22px;font-weight:500}}
  .stat-l{{font-size:11px;color:var(--muted);margin-top:2px;text-transform:uppercase;letter-spacing:.04em}}
  .grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:24px}}
  .card{{background:var(--surface);border-radius:10px;border:1px solid var(--border);overflow:hidden}}
  .card.full{{grid-column:1/-1}}
  .card-title{{padding:12px 16px;font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.05em;border-bottom:1px solid var(--border);background:#f9fafb;color:var(--muted)}}
  table{{width:100%;border-collapse:collapse}}
  thead th{{background:#f3f4f6;padding:9px 14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);font-weight:600}}
  tbody tr:not(:last-child){{border-bottom:1px solid var(--border)}}
  tbody tr:hover{{background:#f9fafb}}
</style>
</head>
<body>
<div class="wrap">
  <h1>Inbound Lead Performance</h1>
  <div class="meta">Leadle RevOps &bull; {_html.escape(window['label'])} &bull; Generated {report['generated_at']}</div>

  <div class="stat-row">
    <div class="stat">
      <div class="stat-n">{s['new_leads']}</div>
      <div class="stat-l">New Leads (window)</div>
    </div>
    <div class="stat">
      <div class="stat-n" style="color:var(--green)">{s['advanced_to_deal']}</div>
      <div class="stat-l">Advanced to Deal</div>
    </div>
    <div class="stat">
      <div class="stat-n" style="color:var(--muted)">{s['archived']}</div>
      <div class="stat-l">Archived (unqualified)</div>
    </div>
    <div class="stat">
      <div class="stat-n" style="color:{rate_color}">{rate_display}</div>
      <div class="stat-l">Conversion Rate (decided)</div>
    </div>
    <div class="stat">
      <div class="stat-n" style="color:var(--amber)">{s['still_active_from_window']}</div>
      <div class="stat-l">Still Active (from window)</div>
    </div>
  </div>

  <div class="grid">
    <div class="card">
      <div class="card-title">New Leads by Source</div>
      <table>
        <thead><tr><th>Source</th><th>Count</th></tr></thead>
        <tbody>{src_new_rows}</tbody>
      </table>
    </div>

    <div class="card">
      <div class="card-title">Conversion Rate by Source (decisions in window)</div>
      <table>
        <thead><tr><th>Source</th><th>Advanced</th><th>Archived</th><th>Decided</th><th>Rate</th></tr></thead>
        <tbody>{conv_rows}</tbody>
      </table>
    </div>

    <div class="card full">
      <div class="card-title">Leads Advanced to Deal in Window (most recent first)</div>
      <table>
        <thead><tr><th>Lead / Company</th><th>Source</th><th>Advanced Date</th><th>Created</th></tr></thead>
        <tbody>{adv_rows}</tbody>
      </table>
    </div>
  </div>
</div>
</body>
</html>"""


# ── main ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="analytics.inbound_perf")
    add_period_args(parser)
    parser.add_argument("--json", metavar="FILE", help="Dump report JSON to this path")
    parser.add_argument("--out", metavar="FILE", help="Output HTML path")
    args = parser.parse_args(argv)

    start, end, label = resolve_args(args)
    if start is None:
        start, end, label = resolve_period(_DEFAULT_PERIOD)

    token = os.environ.get("HUBSPOT_PRIVATE_TOKEN")
    if not token:
        print("ERROR: HUBSPOT_PRIVATE_TOKEN not set", file=sys.stderr)
        return 1

    pipeline, inbound_sources = _load_configs()

    # Lookback covers the window + 90d prior to catch early-cohort decisions
    lookback_start = start - timedelta(days=90)
    print(f"Window: {label}", file=sys.stderr)
    print(f"Fetching leads (lookback from {lookback_start})...", file=sys.stderr)
    leads = _fetch_leads_in_lookback(token, lookback_start)
    print(f"  {len(leads)} leads fetched", file=sys.stderr)

    report = build_report(leads, pipeline, inbound_sources, start, end, label)
    s = report["summary"]
    rate = s["overall_conversion_rate_pct"]

    print(f"\nInbound Lead Performance — {label}")
    print(f"  New leads:       {s['new_leads']}")
    print(f"  Advanced to deal:{s['advanced_to_deal']}")
    print(f"  Archived:        {s['archived']}")
    print(f"  Still active:    {s['still_active_from_window']}")
    print(f"  Conversion rate: {f'{rate:.1f}%' if rate is not None else 'n/a (no decisions yet)'}")

    if report["source_conversion"]:
        print("  By source (decided):")
        for row in report["source_conversion"]:
            r = f"{row['conversion_rate_pct']:.1f}%" if row["conversion_rate_pct"] is not None else "n/a"
            print(f"    {row['source']:30} adv={row['advanced']}  arch={row['archived']}  rate={r}")

    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Report JSON → {args.json}", file=sys.stderr)

    html = render_html(report)
    out_path = args.out
    if not out_path:
        slug = date.today().isoformat()
        _REPORTS_DIR.mkdir(exist_ok=True)
        out_path = str(_REPORTS_DIR / f"inbound-perf-{slug}.html")
    Path(out_path).write_text(html, encoding="utf-8")
    print(f"Report → {out_path}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
