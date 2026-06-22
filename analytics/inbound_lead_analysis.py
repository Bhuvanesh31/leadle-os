"""Inbound lead analysis — pipeline health and ICP alignment snapshot.

Aggregates inbound lead data into diagnostic sections that the
/inbound-lead-analysis slash command uses to produce a narrative.

Sections:
  • Volume  : total active leads + stage distribution
  • Sources : which inbound sources are generating leads (and which aren't)
  • ICP fit : score distribution, tier breakdown
  • Data quality : enrichment gaps that affect scoring accuracy
  • Staleness : age buckets — how long leads have been sitting
  • Flags   : leads needing immediate attention (warm/hot + rotting)

Outputs:
  --json FILE   machine-readable summary (for Claude Code narrative step)
  --out FILE    HTML report

Usage:
    python -m analytics.inbound_lead_analysis
    python -m analytics.inbound_lead_analysis --json /tmp/analysis.json
    python -m analytics.inbound_lead_analysis --all-sources
    python -m analytics.inbound_lead_analysis --enrich-from /tmp/enrichment.json
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
from statistics import mean, median

import analytics.inbound_lead_scoring as ils

_REPORTS_DIR = Path(__file__).parent.parent / "reports"


# ── aggregation helpers ───────────────────────────────────────────────────────


def _stage_distribution(scored: list[dict]) -> list[dict]:
    counts: Counter = Counter()
    for r in scored:
        counts[r["stage_name"]] += 1
    return [{"stage": s, "count": c} for s, c in counts.most_common()]


def _source_breakdown(raw_leads: list[dict], inbound_set: set[str]) -> dict:
    inbound: Counter = Counter()
    outbound: Counter = Counter()
    for lead in raw_leads:
        src = (lead.get("properties") or {}).get("lead_source_v2") or "(untracked)"
        if src in inbound_set or src == "(untracked)":
            inbound[src] += 1
        else:
            outbound[src] += 1
    return {
        "inbound": [{"source": s, "count": c} for s, c in inbound.most_common()],
        "outbound": [{"source": s, "count": c} for s, c in outbound.most_common()],
    }


def _icp_summary(scored: list[dict]) -> dict:
    if not scored:
        return {
            "hot": 0,
            "warm": 0,
            "cold": 0,
            "avg_score": 0,
            "median_score": 0,
            "top_blocker": None,
        }
    scores = [r["score"] for r in scored]
    tc = Counter(r["tier"] for r in scored)

    # What's the single most common reason for low scores?
    dm_zeros = sum(1 for r in scored if r["breakdown"]["decision_maker"] == 0)
    rev_zeros = sum(1 for r in scored if r["breakdown"]["revenue"] == 0)
    fund_zeros = sum(1 for r in scored if r["breakdown"]["funding"] == 0)
    blockers = [
        ("no job title in HubSpot", dm_zeros),
        ("no revenue data", rev_zeros),
        ("no funding data", fund_zeros),
    ]
    top_blocker = max(blockers, key=lambda x: x[1])

    return {
        "hot": tc.get("Hot", 0),
        "warm": tc.get("Warm", 0),
        "cold": tc.get("Cold", 0),
        "avg_score": round(mean(scores), 1),
        "median_score": median(scores),
        "top_blocker": top_blocker[0] if top_blocker[1] > 0 else None,
        "top_blocker_count": top_blocker[1],
    }


def _data_quality(scored: list[dict]) -> dict:
    n = len(scored)
    if n == 0:
        return {}
    missing_title = sum(1 for r in scored if r["missing"]["jobtitle"])
    missing_revenue = sum(1 for r in scored if r["missing"]["revenue"])
    missing_funding = sum(1 for r in scored if r["missing"]["funding"])
    missing_company = sum(1 for r in scored if r["missing"]["company_data"])
    web_enriched = sum(1 for r in scored if r["web_enriched"])
    return {
        "total": n,
        "missing_title": missing_title,
        "missing_title_pct": round(missing_title / n * 100),
        "missing_revenue": missing_revenue,
        "missing_revenue_pct": round(missing_revenue / n * 100),
        "missing_funding": missing_funding,
        "missing_funding_pct": round(missing_funding / n * 100),
        "missing_company": missing_company,
        "web_enriched": web_enriched,
    }


def _staleness_buckets(scored: list[dict]) -> dict:
    fresh = sum(1 for r in scored if r["days_since"] is not None and r["days_since"] <= 3)
    aging = sum(1 for r in scored if r["days_since"] is not None and 3 < r["days_since"] <= 7)
    stale = sum(1 for r in scored if r["days_since"] is not None and r["days_since"] > 7)
    never = sum(1 for r in scored if r["days_since"] is None)
    ages = [r["days_since"] for r in scored if r["days_since"] is not None]
    return {
        "fresh_0_3d": fresh,
        "aging_4_7d": aging,
        "stale_over_7d": stale,
        "never_contacted": never,
        "avg_days_since": round(mean(ages), 1) if ages else None,
        "max_days_since": max(ages) if ages else None,
    }


def _priority_flags(scored: list[dict]) -> list[dict]:
    """Leads that warrant immediate attention: warm/hot, or stale despite being warm."""
    flags = []
    for r in scored:
        reasons = []
        if r["tier"] in ("Hot", "Warm"):
            reasons.append(f"{r['tier']} ICP fit (score={r['score']})")
        if r["days_since"] is not None and r["days_since"] > 7 and r["tier"] != "Cold":
            reasons.append(f"stale ({r['days_since']}d no activity)")
        if r["days_since"] is None and r["tier"] != "Cold":
            reasons.append("never contacted")
        if reasons:
            flags.append(
                {
                    "lead": r["lead_name"],
                    "company": r["company"],
                    "score": r["score"],
                    "tier": r["tier"],
                    "stage": r["stage_name"],
                    "days_since": r["days_since"],
                    "reasons": reasons,
                }
            )
    flags.sort(key=lambda x: -x["score"])
    return flags


def build_analysis(
    raw_leads: list[dict],
    scored: list[dict],
    scoring_cfg: dict,
    stage_map: dict,
    excluded_outbound: int,
) -> dict:
    inbound_set = set(scoring_cfg["inbound_sources"])
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "summary": {
            "total_active_leads": len(raw_leads),
            "inbound_scored": len(scored),
            "excluded_outbound": excluded_outbound,
        },
        "stage_distribution": _stage_distribution(scored),
        "source_breakdown": _source_breakdown(raw_leads, inbound_set),
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


def _pct_bar(pct: int, color: str = "#9b2226") -> str:
    return (
        f'<div style="background:#e5e7eb;border-radius:3px;height:5px;width:100px;display:inline-block;vertical-align:middle">'
        f'<div style="background:{color};height:5px;border-radius:3px;width:{pct}%"></div>'
        f'</div> <span style="font-size:11px;color:#6b7280">{pct}%</span>'
    )


def render_html(analysis: dict, all_sources: bool) -> str:
    s = analysis["summary"]
    icp = analysis["icp_summary"]
    dq = analysis["data_quality"]
    st = analysis["staleness"]
    flags = analysis["priority_flags"]
    stages = analysis["stage_distribution"]
    sources = analysis["source_breakdown"]

    scope = "All sources" if all_sources else "Inbound sources only"

    # Stage distribution rows
    stage_rows = ""
    for item in stages:
        stage_rows += f"""
        <tr>
          <td style="padding:8px 14px">{item["stage"]}</td>
          <td style="padding:8px 14px;font-family:'JetBrains Mono',monospace;font-size:13px">{item["count"]}</td>
        </tr>"""

    # Source rows
    inbound_rows = "".join(
        f'<tr><td style="padding:6px 14px">{x["source"]}</td>'
        f"<td style=\"padding:6px 14px;font-family:'JetBrains Mono',monospace\">{x['count']}</td></tr>"
        for x in sources["inbound"]
    )
    outbound_rows = "".join(
        f'<tr><td style="padding:6px 14px">{x["source"]}</td>'
        f"<td style=\"padding:6px 14px;font-family:'JetBrains Mono',monospace\">{x['count']}</td></tr>"
        for x in sources["outbound"]
    )

    # Priority flag rows
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
            <span style="color:{tier_color};font-weight:600;font-size:12px">{f["tier"]}</span>
            <span style="font-family:'JetBrains Mono',monospace;font-size:11px;color:#6b7280"> {f["score"]}</span>
          </td>
          <td style="padding:10px 14px;font-size:12px;color:#374151">{f["stage"]}</td>
          <td style="padding:10px 14px;font-size:12px;color:#6b7280">{days_label}</td>
          <td style="padding:10px 14px;font-size:11px;color:#374151">{reasons_esc}</td>
        </tr>"""

    no_flags = (
        '<tr><td colspan="5" style="padding:20px;text-align:center;color:#6b7280;font-size:12px">'
        "No priority flags — all warm/hot leads are active.</td></tr>"
        if not flags
        else ""
    )

    dq_blocker = (
        f'<div style="margin-top:10px;font-size:12px;color:#78350f">'
        f"<strong>Top scoring gap:</strong> {icp['top_blocker']} — affects "
        f"{icp['top_blocker_count']} of {dq['total']} leads</div>"
        if icp.get("top_blocker")
        else ""
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Inbound Lead Analysis — Leadle</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Fraunces:ital,wght@0,400;0,600;1,400&family=Inter+Tight:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');
  :root{{--bg:#fafaf7;--surface:#fff;--ink:#15171a;--green:#2d6a4f;--amber:#b45309;--red:#9b2226;--muted:#6b7280;--border:#e5e7eb}}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:var(--bg);color:var(--ink);font-family:'Inter Tight',sans-serif;font-size:14px;line-height:1.5;padding:32px 24px}}
  .wrap{{max-width:1100px;margin:0 auto}}
  h1{{font-family:'Fraunces',serif;font-size:26px;font-weight:600;margin-bottom:4px}}
  h2{{font-family:'Fraunces',serif;font-size:16px;font-weight:600;margin-bottom:12px}}
  .meta{{color:var(--muted);font-size:12px;margin-bottom:28px}}
  .grid2{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:20px}}
  .grid3{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;margin-bottom:20px}}
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
  <h1>Inbound Lead Analysis</h1>
  <div class="meta">Leadle RevOps &bull; {scope} &bull; Generated {analysis["generated_at"]}</div>

  <div class="stat-row">
    <div class="stat">
      <div class="stat-n">{s["total_active_leads"]}</div>
      <div class="stat-l">Total Active Leads</div>
    </div>
    <div class="stat">
      <div class="stat-n">{s["inbound_scored"]}</div>
      <div class="stat-l">Inbound (Scored)</div>
    </div>
    <div class="stat">
      <div class="stat-n" style="color:var(--amber)">{s["excluded_outbound"]}</div>
      <div class="stat-l">Outbound (Excluded)</div>
    </div>
    <div class="stat">
      <div class="stat-n" style="color:var(--red)">{icp["hot"]}</div>
      <div class="stat-l">Hot (≥65)</div>
    </div>
    <div class="stat">
      <div class="stat-n" style="color:var(--amber)">{icp["warm"]}</div>
      <div class="stat-l">Warm (35–64)</div>
    </div>
    <div class="stat">
      <div class="stat-n" style="color:var(--muted)">{icp["cold"]}</div>
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
        <div class="card-title">Source Breakdown</div>
        <table>
          <thead><tr><th>Source</th><th>Leads</th></tr></thead>
          <tbody>
            {inbound_rows}
            {'<tr><td colspan="2" style="padding:6px 14px;font-size:11px;color:#9b2226;font-style:italic">— outbound —</td></tr>' if outbound_rows else ""}
            {outbound_rows}
          </tbody>
        </table>
      </div>
    </div>
    <div>
      <div class="card">
        <div class="card-title">ICP Fit Summary</div>
        <div style="padding:16px">
          <div style="font-size:12px;color:var(--muted);margin-bottom:6px">Average score</div>
          <div style="font-family:'JetBrains Mono',monospace;font-size:24px;font-weight:500;margin-bottom:12px">{icp["avg_score"]}<span style="font-size:14px;color:var(--muted)">/100</span></div>
          <div style="font-size:12px;color:var(--muted);margin-bottom:4px">Median: {icp["median_score"]}</div>
          {dq_blocker}
        </div>
      </div>
      <div class="card">
        <div class="card-title">Data Quality</div>
        <div style="padding:14px 16px">
          <div class="dq-row">
            <span class="dq-label">Missing job title</span>
            {_pct_bar(dq.get("missing_title_pct", 0))}
            <span class="dq-count">{dq.get("missing_title", 0)}</span>
          </div>
          <div class="dq-row">
            <span class="dq-label">Missing revenue</span>
            {_pct_bar(dq.get("missing_revenue_pct", 0))}
            <span class="dq-count">{dq.get("missing_revenue", 0)}</span>
          </div>
          <div class="dq-row">
            <span class="dq-label">Missing funding</span>
            {_pct_bar(dq.get("missing_funding_pct", 0))}
            <span class="dq-count">{dq.get("missing_funding", 0)}</span>
          </div>
          <div class="dq-row" style="border:none">
            <span class="dq-label">No company record</span>
            {_pct_bar(round(dq.get("missing_company", 0) / dq.get("total", 1) * 100) if dq.get("total") else 0)}
            <span class="dq-count">{dq.get("missing_company", 0)}</span>
          </div>
          {'<div style="margin-top:10px;font-size:11px;color:#1e40af">★ ' + str(dq.get("web_enriched", 0)) + " companies enriched via web search this run</div>" if dq.get("web_enriched") else ""}
        </div>
      </div>
      <div class="card">
        <div class="card-title">Staleness</div>
        <div style="padding:14px 16px;display:grid;grid-template-columns:1fr 1fr;gap:10px">
          <div>
            <div style="font-family:'JetBrains Mono',monospace;font-size:20px;color:#2d6a4f">{st.get("fresh_0_3d", 0)}</div>
            <div style="font-size:11px;color:var(--muted)">Fresh (≤3d)</div>
          </div>
          <div>
            <div style="font-family:'JetBrains Mono',monospace;font-size:20px;color:#b45309">{st.get("aging_4_7d", 0)}</div>
            <div style="font-size:11px;color:var(--muted)">Aging (4–7d)</div>
          </div>
          <div>
            <div style="font-family:'JetBrains Mono',monospace;font-size:20px;color:#9b2226">{st.get("stale_over_7d", 0)}</div>
            <div style="font-size:11px;color:var(--muted)">Stale (>7d)</div>
          </div>
          <div>
            <div style="font-family:'JetBrains Mono',monospace;font-size:20px;color:#6b7280">{st.get("never_contacted", 0)}</div>
            <div style="font-size:11px;color:var(--muted)">Never contacted</div>
          </div>
        </div>
        {f'<div style="padding:0 16px 14px;font-size:12px;color:var(--muted)">Avg {st["avg_days_since"]}d since last activity &bull; Worst {st["max_days_since"]}d</div>' if st.get("avg_days_since") is not None else ""}
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
    parser = argparse.ArgumentParser(prog="analytics.inbound_lead_analysis")
    parser.add_argument("--all-sources", action="store_true")
    parser.add_argument(
        "--enrich-from",
        metavar="FILE",
        help="Pre-computed enrichment JSON from /inbound-lead-scoring flow",
    )
    parser.add_argument("--json", metavar="FILE", help="Dump analysis JSON to this path")
    parser.add_argument("--out", metavar="FILE", help="Output HTML path")
    args = parser.parse_args(argv)

    token = os.environ.get("HUBSPOT_PRIVATE_TOKEN")
    if not token:
        print("ERROR: HUBSPOT_PRIVATE_TOKEN not set", file=sys.stderr)
        return 1

    pipeline_cfg = ils._load_pipeline_cfg()
    scoring_cfg = ils._load_scoring_cfg()
    stage_ids = ils._active_stage_ids(pipeline_cfg)
    stage_map = ils._stage_map(pipeline_cfg)
    set(scoring_cfg["inbound_sources"])

    print("Fetching active leads...", file=sys.stderr)
    raw = ils.fetch_active_leads(token, stage_ids)
    print(f"  {len(raw)} leads fetched", file=sys.stderr)

    print("Resolving associations...", file=sys.stderr)
    contacts, companies = ils.enrich_leads(token, raw)
    print(f"  {len(contacts)} contacts, {len(companies)} companies", file=sys.stderr)

    if args.enrich_from:
        enrichment = json.loads(Path(args.enrich_from).read_text(encoding="utf-8"))
        companies = ils.apply_enrichment(raw, companies, enrichment)

    report = ils.compute_scores(raw, contacts, companies, scoring_cfg, stage_map, args.all_sources)
    scored = report["scored"]

    analysis = build_analysis(raw, scored, scoring_cfg, stage_map, report["excluded_outbound"])

    if args.json:
        Path(args.json).write_text(json.dumps(analysis, indent=2), encoding="utf-8")
        print(f"Analysis JSON → {args.json}", file=sys.stderr)

    html = render_html(analysis, args.all_sources)
    out_path = args.out
    if not out_path:
        slug = date.today().isoformat()
        _REPORTS_DIR.mkdir(exist_ok=True)
        out_path = str(_REPORTS_DIR / f"inbound-lead-analysis-{slug}.html")
    Path(out_path).write_text(html, encoding="utf-8")
    print(f"Report → {out_path}", file=sys.stderr)

    icp = analysis["icp_summary"]
    dq = analysis["data_quality"]
    st = analysis["staleness"]
    print(f"\nInbound Lead Analysis — {analysis['generated_at']}")
    print(
        f"  {analysis['summary']['inbound_scored']} inbound  |  "
        f"Hot:{icp['hot']}  Warm:{icp['warm']}  Cold:{icp['cold']}  "
        f"|  Avg score: {icp['avg_score']}"
    )
    print(
        f"  Staleness: {st['fresh_0_3d']} fresh / {st['aging_4_7d']} aging / "
        f"{st['stale_over_7d']} stale / {st['never_contacted']} never contacted"
    )
    print(
        f"  Data gaps: {dq.get('missing_title', 0)} no title  "
        f"{dq.get('missing_revenue', 0)} no revenue  "
        f"{dq.get('missing_funding', 0)} no funding"
    )
    if icp.get("top_blocker"):
        print(f"  Top score blocker: {icp['top_blocker']} ({icp['top_blocker_count']} leads)")
    if analysis["priority_flags"]:
        print(f"  {len(analysis['priority_flags'])} leads flagged for attention:")
        for f in analysis["priority_flags"]:
            print(
                f"    → {f['lead']} / {f['company']} [{f['tier']} {f['score']}]  "
                + " | ".join(f["reasons"])
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
