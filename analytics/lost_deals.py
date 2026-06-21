"""Lost deals analysis — process #17.

Fetches all deals that moved to the Lost stage in a time window and surfaces:

  volume         — count and total amount lost in the window
  reason_clusters— free-text closed_lost_reason grouped into buckets via keywords
  stage_of_loss  — which pipeline stage the deal was last active in before Lost
  time_in_pipe   — days from Meeting Booked entry to Lost entry (where traceable)
  amount_buckets — lost deal distribution by deal size

Default window: last-quarter (captures enough volume; change with --period or --start/--end).

Outputs:
  --json FILE   machine-readable report
  --out  FILE   HTML report

Usage:
    python -m analytics.lost_deals
    python -m analytics.lost_deals --period last-month
    python -m analytics.lost_deals --start 2026-04-01 --end 2026-06-21
    python -m analytics.lost_deals --json /tmp/lost_deals.json
"""
from __future__ import annotations

import argparse
import html as _html
import json
import os
import re
import sys
from collections import defaultdict
from datetime import UTC, date, datetime
from pathlib import Path

import httpx

from analytics._periods import add_period_args, resolve_args, resolve_period

_PIPELINE_CFG = Path(__file__).parent.parent / "config" / "hubspot_pipeline.yaml"
_REPORTS_DIR = Path(__file__).parent.parent / "reports"
_DEFAULT_PERIOD = "last-quarter"

_LOST_STAGE_ID = "3022478049"

# Deal pipeline active stage IDs in funnel order
_ACTIVE_STAGES = [
    ("3022488285", "Meeting Booked"),
    ("3022488286", "Discovery Call"),
    ("3022488287", "Prospect Qualified"),
    ("3022488288", "Proposal Made"),
    ("3022488289", "Proposal Walkthrough"),
    ("3022488290", "Negotiation"),
    ("3022488291", "Verbal Yes"),
]

# Keyword clusters for closed_lost_reason free text (first match wins)
_REASON_CLUSTERS: list[tuple[str, list[str]]] = [
    ("Unresponsive / No-show", [
        "no show", "no response", "unresponsive", "not responding",
        "ghost", "unreachable", " ur", "^ur$", "no reply",
    ]),
    ("Not ICP fit", [
        "not a good fit", "not good fit", "wrong fit", "not the right fit",
        "not fit", "bad fit", "no fit", "not our target", "not icp",
    ]),
    ("Budget / Pricing", [
        "budget", "pricing", "price", "cost", "expensive", "afford",
        "low budget", "small to start", "outcome based",
    ]),
    ("Not ready / Too early", [
        "not ready", "not now", "too early", "later", "next quarter",
        "timing", "freeze",
    ]),
    ("Lost to competition", [
        "competition", "competitor", "went with", "chose another",
        "other vendor", "other agency",
    ]),
    ("No authority / Wrong stakeholder", [
        "no authority", "not decision", "not the right person",
        "wrong contact", "no authority",
    ]),
    ("Payment / Terms", [
        "payment terms", "payment", "terms", "contract",
    ]),
    ("Other / Unknown", []),  # catch-all
]


def _cluster_reason(reason: str | None) -> str:
    if not reason or not reason.strip():
        return "No reason recorded"
    r = reason.lower().strip()
    for cluster_name, keywords in _REASON_CLUSTERS:
        for kw in keywords:
            if re.search(kw, r):
                return cluster_name
    return "Other / Unknown"


def _date_to_epoch_ms(d: date) -> int:
    dt = datetime.combine(d, datetime.min.time(), tzinfo=UTC)
    return int(dt.timestamp() * 1000)


def _parse_date(ts: str | None) -> date | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _days_between(a: date | None, b: date | None) -> int | None:
    if a is None or b is None:
        return None
    return max(0, (b - a).days)


def _last_active_stage(p: dict) -> str:
    best_stage_name = None
    best_date = ""
    for sid, sname in _ACTIVE_STAGES:
        val = p.get(f"hs_v2_date_entered_{sid}") or ""
        if val and val > best_date:
            best_date = val
            best_stage_name = sname
    return best_stage_name or "(no stage data)"


def _fetch_lost_in_window(token: str, window_start: date, window_end: date) -> list[dict]:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    start_ms = str(_date_to_epoch_ms(window_start))
    end_ms = str(_date_to_epoch_ms(window_end))

    lost_prop = f"hs_v2_date_entered_{_LOST_STAGE_ID}"
    stage_props = [f"hs_v2_date_entered_{sid}" for sid, _ in _ACTIVE_STAGES]

    results = []
    after = None
    while True:
        body: dict = {
            "filterGroups": [{"filters": [
                {"propertyName": "dealstage", "operator": "EQ", "value": _LOST_STAGE_ID},
                {"propertyName": lost_prop, "operator": "GTE", "value": start_ms},
                {"propertyName": lost_prop, "operator": "LTE", "value": end_ms},
            ]}],
            "properties": ["dealname", "amount", "closedate", "closed_lost_reason", "closed_lost_tag", lost_prop, *stage_props],
            "sorts": [{"propertyName": lost_prop, "direction": "DESCENDING"}],
            "limit": 100,
        }
        if after:
            body["after"] = after
        r = httpx.post(
            "https://api.hubapi.com/crm/v3/objects/deals/search",
            headers=headers, json=body, timeout=30,
        )
        data = r.json()
        results.extend(data.get("results", []))
        after = (data.get("paging") or {}).get("next", {}).get("after")
        if not after:
            break
    return results


def build_report(deals: list[dict], window_start: date, window_end: date,
                 window_label: str) -> dict:
    lost_prop = f"hs_v2_date_entered_{_LOST_STAGE_ID}"

    reason_counts: dict[str, int] = defaultdict(int)
    stage_counts: dict[str, int] = defaultdict(int)
    amt_buckets: dict[str, int] = {"$0 (no amount)": 0, "< $1K": 0, "$1K–$5K": 0,
                                    "$5K–$20K": 0, "$20K+": 0}
    time_in_pipe: list[int] = []
    total_amount = 0.0
    rows = []

    for deal in deals:
        p = deal.get("properties") or {}
        name = p.get("dealname") or "(unnamed)"
        lost_date = _parse_date(p.get(lost_prop))
        booked_date = _parse_date(p.get("hs_v2_date_entered_3022488285"))
        last_stage = _last_active_stage(p)
        reason_raw = p.get("closed_lost_reason") or ""
        cluster = _cluster_reason(reason_raw)
        reason_counts[cluster] += 1
        stage_counts[last_stage] += 1

        amt_raw = p.get("amount")
        try:
            amt = float(amt_raw) if amt_raw else None
        except (ValueError, TypeError):
            amt = None

        if amt is not None:
            total_amount += amt
            if amt >= 20_000:
                amt_buckets["$20K+"] += 1
            elif amt >= 5_000:
                amt_buckets["$5K–$20K"] += 1
            elif amt >= 1_000:
                amt_buckets["$1K–$5K"] += 1
            else:
                amt_buckets["< $1K"] += 1
        else:
            amt_buckets["$0 (no amount)"] += 1

        days = _days_between(booked_date, lost_date)
        if days is not None:
            time_in_pipe.append(days)

        rows.append({
            "name": name,
            "lost_date": lost_date.isoformat() if lost_date else None,
            "last_stage": last_stage,
            "reason_raw": reason_raw,
            "reason_cluster": cluster,
            "amount": amt,
            "amount_fmt": f"${amt:,.0f}" if amt else "—",
            "days_in_pipe": days,
        })

    avg_days = round(sum(time_in_pipe) / len(time_in_pipe)) if time_in_pipe else None

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "window": {
            "start": window_start.isoformat(),
            "end": window_end.isoformat(),
            "label": window_label,
        },
        "summary": {
            "total_lost": len(deals),
            "total_amount_lost": round(total_amount),
            "avg_days_in_pipe": avg_days,
            "days_sample_size": len(time_in_pipe),
        },
        "reason_clusters": sorted(
            [{"reason": k, "count": v} for k, v in reason_counts.items()],
            key=lambda x: -x["count"],
        ),
        "stage_of_loss": sorted(
            [{"stage": k, "count": v} for k, v in stage_counts.items()],
            key=lambda x: -x["count"],
        ),
        "amount_buckets": [
            {"bucket": k, "count": v} for k, v in amt_buckets.items() if v > 0
        ],
        "deals": sorted(rows, key=lambda r: r["lost_date"] or "", reverse=True),
    }


# ── HTML render ───────────────────────────────────────────────────────────────

_CLUSTER_COLORS = {
    "Unresponsive / No-show":           "#b45309",
    "Not ICP fit":                      "#9b2226",
    "Budget / Pricing":                 "#1e40af",
    "Not ready / Too early":            "#6b7280",
    "Lost to competition":              "#7c3aed",
    "No authority / Wrong stakeholder": "#0f766e",
    "Payment / Terms":                  "#374151",
    "Other / Unknown":                  "#9ca3af",
    "No reason recorded":               "#d1d5db",
}


def _reason_badge(cluster: str) -> str:
    color = _CLUSTER_COLORS.get(cluster, "#6b7280")
    label = _html.escape(cluster)
    return f'<span style="color:{color};font-size:11px;font-weight:500">{label}</span>'


def render_html(report: dict) -> str:
    s = report["summary"]
    window = report["window"]
    amt_fmt = f"${s['total_amount_lost']:,}" if s["total_amount_lost"] else "—"
    avg_days = f"{s['avg_days_in_pipe']}d (n={s['days_sample_size']})" if s["avg_days_in_pipe"] else "—"

    # Reason bar chart (simple HTML bars)
    total = s["total_lost"] or 1
    reason_bars = ""
    for row in report["reason_clusters"]:
        pct = round(row["count"] / total * 100)
        color = _CLUSTER_COLORS.get(row["reason"], "#6b7280")
        label = _html.escape(row["reason"])
        reason_bars += f"""
        <div style="display:flex;align-items:center;gap:12px;margin-bottom:8px">
          <div style="width:180px;font-size:12px;color:#374151;flex-shrink:0">{label}</div>
          <div style="background:#f3f4f6;border-radius:4px;flex:1;height:20px;position:relative">
            <div style="background:{color};border-radius:4px;width:{pct}%;height:100%;min-width:2px"></div>
          </div>
          <div style="font-family:'JetBrains Mono',monospace;font-size:12px;width:60px;text-align:right;color:#374151">{row['count']} ({pct}%)</div>
        </div>"""

    # Stage of loss table
    stage_rows = ""
    for row in report["stage_of_loss"]:
        stage_rows += f'<tr><td style="padding:8px 14px;font-size:13px">{_html.escape(row["stage"])}</td><td style="padding:8px 14px;font-family:\'JetBrains Mono\',monospace;font-size:12px">{row["count"]}</td></tr>'

    # Recent lost deals table (top 20)
    deal_rows = ""
    for r in report["deals"][:20]:
        name = _html.escape(r["name"])
        stage = _html.escape(r["last_stage"])
        reason_raw = _html.escape((r["reason_raw"] or "—")[:60])
        deal_rows += f"""<tr>
          <td style="padding:9px 14px;font-size:13px;font-weight:500">{name}</td>
          <td style="padding:9px 14px;font-family:'JetBrains Mono',monospace;font-size:12px">{r['lost_date'] or '—'}</td>
          <td style="padding:9px 14px;font-size:12px;color:#6b7280">{stage}</td>
          <td style="padding:9px 14px;font-family:'JetBrains Mono',monospace;font-size:12px">{r['amount_fmt']}</td>
          <td style="padding:9px 14px">{_reason_badge(r['reason_cluster'])}</td>
          <td style="padding:9px 14px;font-size:11px;color:#6b7280">{reason_raw}</td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lost Deals Analysis — Leadle</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Fraunces:ital,wght@0,400;0,600;1,400&family=Inter+Tight:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');
  :root{{--bg:#fafaf7;--surface:#fff;--ink:#15171a;--red:#9b2226;--amber:#b45309;--muted:#6b7280;--border:#e5e7eb}}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:var(--bg);color:var(--ink);font-family:'Inter Tight',sans-serif;font-size:14px;line-height:1.5;padding:32px 24px}}
  .wrap{{max-width:1200px;margin:0 auto}}
  h1{{font-family:'Fraunces',serif;font-size:26px;font-weight:600;margin-bottom:4px}}
  .meta{{color:var(--muted);font-size:12px;margin-bottom:28px}}
  .stat-row{{display:flex;gap:16px;margin-bottom:20px}}
  .stat{{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:14px 18px;flex:1}}
  .stat-n{{font-family:'JetBrains Mono',monospace;font-size:22px;font-weight:500}}
  .stat-l{{font-size:11px;color:var(--muted);margin-top:2px;text-transform:uppercase;letter-spacing:.04em}}
  .grid{{display:grid;grid-template-columns:2fr 1fr;gap:16px;margin-bottom:24px}}
  .card{{background:var(--surface);border-radius:10px;border:1px solid var(--border);overflow:hidden}}
  .card.full{{grid-column:1/-1}}
  .card-title{{padding:12px 16px;font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.05em;border-bottom:1px solid var(--border);background:#f9fafb;color:var(--muted)}}
  .card-body{{padding:16px}}
  table{{width:100%;border-collapse:collapse}}
  thead th{{background:#f3f4f6;padding:9px 14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);font-weight:600}}
  tbody tr:not(:last-child){{border-bottom:1px solid var(--border)}}
  tbody tr:hover{{background:#f9fafb}}
</style>
</head>
<body>
<div class="wrap">
  <h1>Lost Deals Analysis</h1>
  <div class="meta">Leadle RevOps &bull; {_html.escape(window['label'])} &bull; Generated {report['generated_at']}</div>

  <div class="stat-row">
    <div class="stat">
      <div class="stat-n" style="color:var(--red)">{s['total_lost']}</div>
      <div class="stat-l">Deals Lost</div>
    </div>
    <div class="stat">
      <div class="stat-n">{amt_fmt}</div>
      <div class="stat-l">Pipeline Value Lost</div>
    </div>
    <div class="stat">
      <div class="stat-n">{avg_days}</div>
      <div class="stat-l">Avg Days in Pipeline</div>
    </div>
  </div>

  <div class="grid">
    <div class="card">
      <div class="card-title">Loss Reasons</div>
      <div class="card-body">{reason_bars}</div>
    </div>
    <div class="card">
      <div class="card-title">Stage at Loss</div>
      <table>
        <thead><tr><th>Stage</th><th>Count</th></tr></thead>
        <tbody>{stage_rows}</tbody>
      </table>
    </div>
    <div class="card full">
      <div class="card-title">Recent Lost Deals (top 20, most recent first)</div>
      <table>
        <thead>
          <tr><th>Deal</th><th>Lost Date</th><th>Last Stage</th><th>Amount</th><th>Reason Cluster</th><th>Raw Reason</th></tr>
        </thead>
        <tbody>{deal_rows}</tbody>
      </table>
    </div>
  </div>
</div>
</body>
</html>"""


# ── main ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="analytics.lost_deals")
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

    print(f"Window: {label}", file=sys.stderr)
    print("Fetching lost deals...", file=sys.stderr)
    deals = _fetch_lost_in_window(token, start, end)
    print(f"  {len(deals)} lost deals in window", file=sys.stderr)

    report = build_report(deals, start, end, label)
    s = report["summary"]

    print(f"\nLost Deals — {label}")
    print(f"  Total lost:     {s['total_lost']}")
    print(f"  Pipeline value: ${s['total_amount_lost']:,}")
    avg_days_display = f"{s['avg_days_in_pipe']}d (n={s['days_sample_size']})" if s["avg_days_in_pipe"] is not None else f"n/a (n={s['days_sample_size']})"
    print(f"  Avg days:       {avg_days_display}")

    print("\n  Loss reasons:")
    for row in report["reason_clusters"]:
        pct = round(row["count"] / (s["total_lost"] or 1) * 100)
        print(f"    {row['reason']:40} {row['count']:3d} ({pct}%)")

    print("\n  Stage at loss:")
    for row in report["stage_of_loss"]:
        print(f"    {row['stage']:25} {row['count']:3d}")

    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Report JSON → {args.json}", file=sys.stderr)

    html = render_html(report)
    out_path = args.out
    if not out_path:
        slug = date.today().isoformat()
        _REPORTS_DIR.mkdir(exist_ok=True)
        out_path = str(_REPORTS_DIR / f"lost-deals-{slug}.html")
    Path(out_path).write_text(html, encoding="utf-8")
    print(f"Report → {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
