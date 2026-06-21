"""Outbound lead analysis — pipeline health snapshot for LinkedIn Outbound leads.

Mirrors inbound_lead_analysis (process #6) but scoped to outbound sources.
Aggregation helpers (stage, ICP, data quality, staleness) are shared from the
inbound module since they operate on generic scored-lead dicts.

Sections:
  • Volume      : total active leads, outbound scored, stage distribution
  • ICP fit     : tier breakdown, avg/median score, top blocker
  • Data quality : enrichment gaps that affect scoring accuracy
  • Staleness   : age buckets — how long leads have been sitting
  • Flags       : leads needing immediate attention (hot + stale)

Outputs:
  --json FILE   machine-readable summary (for Claude Code narrative step)
  --out FILE    HTML report

Usage:
    python -m analytics.outbound_lead_analysis
    python -m analytics.outbound_lead_analysis --json /tmp/outbound_analysis.json
    python -m analytics.outbound_lead_analysis --enrich-from /tmp/outbound_enrichment.json
"""
from __future__ import annotations

import argparse
import html as _html
import json
import os
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path

import analytics.inbound_lead_scoring as ils
import analytics.outbound_lead_scoring as ols
from analytics.inbound_lead_analysis import (
    _data_quality,
    _icp_summary,
    _pct_bar,
    _priority_flags,
    _staleness_buckets,
    _stage_distribution,
)

_REPORTS_DIR = Path(__file__).parent.parent / "reports"


# ── outbound-specific aggregation ─────────────────────────────────────────────

def _campaign_breakdown(raw_leads: list[dict], outbound_set: set[str]) -> list[dict]:
    counts: Counter = Counter()
    for lead in raw_leads:
        src = (lead.get("properties") or {}).get("lead_source_v2") or "(untracked)"
        if src in outbound_set:
            counts[src] += 1
    return [{"source": s, "count": c} for s, c in counts.most_common()]


def build_analysis(
    raw_leads: list[dict],
    scored: list[dict],
    outbound_set: set[str],
    excluded_inbound: int,
) -> dict:
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "summary": {
            "total_active_leads": len(raw_leads),
            "outbound_scored": len(scored),
            "excluded_inbound": excluded_inbound,
        },
        "stage_distribution": _stage_distribution(scored),
        "campaign_breakdown": _campaign_breakdown(raw_leads, outbound_set),
        "icp_summary": _icp_summary(scored),
        "data_quality": _data_quality(scored),
        "staleness": _staleness_buckets(scored),
        "priority_flags": _priority_flags(scored),
        "top_leads": [
            {
                "rank": i + 1,
                "lead": r["lead_name"],
                "company": r["company"],
                "score": r["score"],
                "tier": r["tier"],
                "jobtitle": r["jobtitle"],
                "revenue_fmt": r["revenue_fmt"],
                "funding_fmt": r["funding_fmt"],
                "funding_stage": r["funding_stage"],
                "days_since": r["days_since"],
                "stage": r["stage_name"],
                "breakdown": r["breakdown"],
                "missing": r["missing"],
                "web_enriched": r["web_enriched"],
            }
            for i, r in enumerate(scored[:5])
        ],
    }


# ── HTML render ───────────────────────────────────────────────────────────────

def render_html(analysis: dict) -> str:
    s = analysis["summary"]
    icp = analysis["icp_summary"]
    dq = analysis["data_quality"]
    st = analysis["staleness"]
    flags = analysis["priority_flags"]
    stages = analysis["stage_distribution"]
    campaigns = analysis["campaign_breakdown"]

    stage_rows = "".join(
        f'<tr><td style="padding:8px 14px">{item["stage"]}</td>'
        f'<td style="padding:8px 14px;font-family:\'JetBrains Mono\',monospace;font-size:13px">{item["count"]}</td></tr>'
        for item in stages
    )

    campaign_rows = "".join(
        f'<tr><td style="padding:6px 14px">{x["source"]}</td>'
        f'<td style="padding:6px 14px;font-family:\'JetBrains Mono\',monospace">{x["count"]}</td></tr>'
        for x in campaigns
    )

    flag_rows = ""
    for f in flags:
        tier_color = {"Hot": "#9b2226", "Warm": "#b45309", "Cold": "#6b7280"}[f["tier"]]
        days_label = f"{f['days_since']}d ago" if f["days_since"] is not None else "Never contacted"
        lead_esc = _html.escape(f["lead"])
        company_esc = _html.escape(f["company"])
        reasons_esc = " | ".join(_html.escape(r) for r in f["reasons"])
        flag_rows += f"""
        <tr>
          <td style="padding:10px 14px">
            <div style="font-weight:500">{lead_esc}</div>
            <div style="font-size:12px;color:#6b7280">{company_esc}</div>
          </td>
          <td style="padding:10px 14px">
            <span style="color:{tier_color};font-weight:600;font-size:12px">{f['tier']}</span>
            <span style="font-family:'JetBrains Mono',monospace;font-size:11px;color:#6b7280"> {f['score']}</span>
          </td>
          <td style="padding:10px 14px;font-size:12px;color:#374151">{f['stage']}</td>
          <td style="padding:10px 14px;font-size:12px;color:#6b7280">{days_label}</td>
          <td style="padding:10px 14px;font-size:11px;color:#374151">{reasons_esc}</td>
        </tr>"""

    no_flags = (
        '<tr><td colspan="5" style="padding:20px;text-align:center;color:#6b7280;font-size:12px">'
        'No priority flags — all warm/hot leads are active.</td></tr>'
        if not flags else ""
    )

    dq_blocker = (
        f'<div style="margin-top:10px;font-size:12px;color:#78350f">'
        f'<strong>Top scoring gap:</strong> {icp["top_blocker"]} — affects '
        f'{icp["top_blocker_count"]} of {dq["total"]} leads</div>'
        if icp.get("top_blocker") else ""
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Outbound Lead Analysis — Leadle</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Fraunces:ital,wght@0,400;0,600;1,400&family=Inter+Tight:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');
  :root{{--bg:#fafaf7;--surface:#fff;--ink:#15171a;--green:#2d6a4f;--amber:#b45309;--red:#9b2226;--muted:#6b7280;--border:#e5e7eb}}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:var(--bg);color:var(--ink);font-family:'Inter Tight',sans-serif;font-size:14px;line-height:1.5;padding:32px 24px}}
  .wrap{{max-width:1100px;margin:0 auto}}
  h1{{font-family:'Fraunces',serif;font-size:26px;font-weight:600;margin-bottom:4px}}
  .meta{{color:var(--muted);font-size:12px;margin-bottom:28px}}
  .grid2{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:20px}}
  .card{{background:var(--surface);border-radius:10px;border:1px solid var(--border);overflow:hidden;margin-bottom:20px}}
  .card-title{{padding:12px 16px;font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.05em;border-bottom:1px solid var(--border);background:#f9fafb;color:var(--muted)}}
  .stat-row{{display:flex;gap:16px;margin-bottom:20px}}
  .stat{{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:14px 18px;flex:1}}
  .stat-n{{font-family:'JetBrains Mono',monospace;font-size:22px;font-weight:500}}
  .stat-l{{font-size:11px;color:var(--muted);margin-top:2px;text-transform:uppercase;letter-spacing:.04em}}
  table{{width:100%;border-collapse:collapse}}
  thead th{{background:#f3f4f6;padding:9px 14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);font-weight:600}}
  tbody tr:not(:last-child){{border-bottom:1px solid var(--border)}}
  tbody tr:hover{{background:#f9fafb}}
  .dq-row{{display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid var(--border)}}
  .dq-label{{font-size:12px;color:var(--ink);flex:1}}
  .dq-count{{font-family:'JetBrains Mono',monospace;font-size:12px;color:var(--red);min-width:30px;text-align:right}}
</style>
</head>
<body>
<div class="wrap">
  <h1>Outbound Lead Analysis</h1>
  <div class="meta">Leadle RevOps &bull; LinkedIn Outbound &bull; Generated {analysis['generated_at']}</div>

  <div class="stat-row">
    <div class="stat">
      <div class="stat-n">{s['total_active_leads']}</div>
      <div class="stat-l">Total Active Leads</div>
    </div>
    <div class="stat">
      <div class="stat-n">{s['outbound_scored']}</div>
      <div class="stat-l">Outbound (Scored)</div>
    </div>
    <div class="stat">
      <div class="stat-n" style="color:var(--amber)">{s['excluded_inbound']}</div>
      <div class="stat-l">Inbound (Excluded)</div>
    </div>
    <div class="stat">
      <div class="stat-n" style="color:var(--red)">{icp['hot']}</div>
      <div class="stat-l">Hot (≥65)</div>
    </div>
    <div class="stat">
      <div class="stat-n" style="color:var(--amber)">{icp['warm']}</div>
      <div class="stat-l">Warm (35–64)</div>
    </div>
    <div class="stat">
      <div class="stat-n" style="color:var(--muted)">{icp['cold']}</div>
      <div class="stat-l">Cold (&lt;35)</div>
    </div>
  </div>

  <div class="grid2">
    <div>
      <div class="card">
        <div class="card-title">Stage Distribution</div>
        <table>
          <thead><tr><th>Stage</th><th>Leads</th></tr></thead>
          <tbody>{stage_rows}</tbody>
        </table>
      </div>
      <div class="card">
        <div class="card-title">Campaign Sources</div>
        <table>
          <thead><tr><th>Source</th><th>Leads</th></tr></thead>
          <tbody>{campaign_rows}</tbody>
        </table>
      </div>
    </div>
    <div>
      <div class="card">
        <div class="card-title">ICP Fit Summary</div>
        <div style="padding:16px">
          <div style="font-size:12px;color:var(--muted);margin-bottom:6px">Average score</div>
          <div style="font-family:'JetBrains Mono',monospace;font-size:24px;font-weight:500;margin-bottom:12px">{icp['avg_score']}<span style="font-size:14px;color:var(--muted)">/100</span></div>
          <div style="font-size:12px;color:var(--muted);margin-bottom:4px">Median: {icp['median_score']}</div>
          {dq_blocker}
        </div>
      </div>
      <div class="card">
        <div class="card-title">Data Quality</div>
        <div style="padding:14px 16px">
          <div class="dq-row">
            <span class="dq-label">Missing job title</span>
            {_pct_bar(dq.get('missing_title_pct', 0))}
            <span class="dq-count">{dq.get('missing_title', 0)}</span>
          </div>
          <div class="dq-row">
            <span class="dq-label">Missing revenue</span>
            {_pct_bar(dq.get('missing_revenue_pct', 0))}
            <span class="dq-count">{dq.get('missing_revenue', 0)}</span>
          </div>
          <div class="dq-row">
            <span class="dq-label">Missing funding</span>
            {_pct_bar(dq.get('missing_funding_pct', 0))}
            <span class="dq-count">{dq.get('missing_funding', 0)}</span>
          </div>
          <div class="dq-row" style="border:none">
            <span class="dq-label">No company record</span>
            {_pct_bar(round(dq.get('missing_company', 0) / dq.get('total', 1) * 100) if dq.get('total') else 0)}
            <span class="dq-count">{dq.get('missing_company', 0)}</span>
          </div>
          {'<div style="margin-top:10px;font-size:11px;color:#1e40af">★ ' + str(dq.get("web_enriched", 0)) + ' companies enriched via web search this run</div>' if dq.get('web_enriched') else ''}
        </div>
      </div>
      <div class="card">
        <div class="card-title">Staleness</div>
        <div style="padding:14px 16px;display:grid;grid-template-columns:1fr 1fr;gap:10px">
          <div>
            <div style="font-family:'JetBrains Mono',monospace;font-size:20px;color:#2d6a4f">{st.get('fresh_0_3d', 0)}</div>
            <div style="font-size:11px;color:var(--muted)">Fresh (≤3d)</div>
          </div>
          <div>
            <div style="font-family:'JetBrains Mono',monospace;font-size:20px;color:#b45309">{st.get('aging_4_7d', 0)}</div>
            <div style="font-size:11px;color:var(--muted)">Aging (4–7d)</div>
          </div>
          <div>
            <div style="font-family:'JetBrains Mono',monospace;font-size:20px;color:#9b2226">{st.get('stale_over_7d', 0)}</div>
            <div style="font-size:11px;color:var(--muted)">Stale (>7d)</div>
          </div>
          <div>
            <div style="font-family:'JetBrains Mono',monospace;font-size:20px;color:#6b7280">{st.get('never_contacted', 0)}</div>
            <div style="font-size:11px;color:var(--muted)">Never contacted</div>
          </div>
        </div>
        {f'<div style="padding:0 16px 14px;font-size:12px;color:var(--muted)">Avg {st["avg_days_since"]}d since last activity &bull; Worst {st["max_days_since"]}d</div>' if st.get("avg_days_since") is not None else ''}
      </div>
    </div>
  </div>

  <div class="card">
    <div class="card-title">Priority Flags — Needs Attention</div>
    <table>
      <thead><tr><th>Lead / Company</th><th>Score</th><th>Stage</th><th>Last Activity</th><th>Why flagged</th></tr></thead>
      <tbody>{flag_rows}{no_flags}</tbody>
    </table>
  </div>

</div>
</body>
</html>"""


# ── main ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="analytics.outbound_lead_analysis")
    parser.add_argument("--enrich-from", metavar="FILE",
                        help="Pre-computed enrichment JSON from /outbound-lead-scoring flow")
    parser.add_argument("--json", metavar="FILE", help="Dump analysis JSON to this path")
    parser.add_argument("--out", metavar="FILE", help="Output HTML path")
    args = parser.parse_args(argv)

    token = os.environ.get("HUBSPOT_PRIVATE_TOKEN")
    if not token:
        print("ERROR: HUBSPOT_PRIVATE_TOKEN not set", file=sys.stderr)
        return 1

    pipeline_cfg = ils._load_pipeline_cfg()
    outbound_cfg = ols._load_outbound_cfg()
    scoring_cfg = ols._normalise_cfg(outbound_cfg)
    stage_ids = ils._active_stage_ids(pipeline_cfg)
    stage_map = ils._stage_map(pipeline_cfg)
    outbound_set = set(outbound_cfg.get("outbound_sources", []))

    print("Fetching active leads...", file=sys.stderr)
    raw = ils.fetch_active_leads(token, stage_ids)
    print(f"  {len(raw)} leads fetched", file=sys.stderr)

    print("Resolving associations...", file=sys.stderr)
    contacts, companies = ils.enrich_leads(token, raw)
    print(f"  {len(contacts)} contacts, {len(companies)} companies", file=sys.stderr)

    if args.enrich_from:
        enrichment = json.loads(Path(args.enrich_from).read_text(encoding="utf-8"))
        companies = ils.apply_enrichment(raw, companies, enrichment)
        n_enriched = sum(1 for c in companies.values() if c.get("web_enriched"))
        print(f"  Applied enrichment: {n_enriched} companies updated", file=sys.stderr)

    report = ils.compute_scores(raw, contacts, companies, scoring_cfg, stage_map, all_sources=False)
    scored = report["scored"]
    excluded_inbound = report["excluded_outbound"]  # excluded_outbound = non-outbound leads

    analysis = build_analysis(raw, scored, outbound_set, excluded_inbound)

    if args.json:
        Path(args.json).write_text(json.dumps(analysis, indent=2), encoding="utf-8")
        print(f"Analysis JSON → {args.json}", file=sys.stderr)

    html = render_html(analysis)
    out_path = args.out
    if not out_path:
        slug = date.today().isoformat()
        _REPORTS_DIR.mkdir(exist_ok=True)
        out_path = str(_REPORTS_DIR / f"outbound-lead-analysis-{slug}.html")
    Path(out_path).write_text(html, encoding="utf-8")
    print(f"Report → {out_path}", file=sys.stderr)

    icp = analysis["icp_summary"]
    dq = analysis["data_quality"]
    st = analysis["staleness"]
    print(f"\nOutbound Lead Analysis — {analysis['generated_at']}")
    print(f"  {analysis['summary']['outbound_scored']} outbound  |  "
          f"Hot:{icp['hot']}  Warm:{icp['warm']}  Cold:{icp['cold']}  "
          f"|  Avg score: {icp['avg_score']}")
    print(f"  Staleness: {st['fresh_0_3d']} fresh / {st['aging_4_7d']} aging / "
          f"{st['stale_over_7d']} stale / {st['never_contacted']} never contacted")
    print(f"  Data gaps: {dq.get('missing_title',0)} no title  "
          f"{dq.get('missing_revenue',0)} no revenue  "
          f"{dq.get('missing_funding',0)} no funding")
    if icp.get("top_blocker"):
        print(f"  Top score blocker: {icp['top_blocker']} ({icp['top_blocker_count']} leads)")
    if analysis["priority_flags"]:
        print(f"  {len(analysis['priority_flags'])} leads flagged for attention:")
        for f in analysis["priority_flags"]:
            print(f"    → {f['lead']} / {f['company']} [{f['tier']} {f['score']}]  "
                  + " | ".join(f["reasons"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
