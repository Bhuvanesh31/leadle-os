"""Outbound lead scoring — ICP-fit ranking for LinkedIn Outbound leads.

Same four scoring dimensions as inbound_lead_scoring:
  • Decision maker fit  (40 pts)
  • Revenue fit         (25 pts)
  • Funding fit         (20 pts)
  • Spend capacity      (15 pts)

Filters to outbound sources (LinkedIn Outbound, Email Outbound) per
config/outbound_scoring.yaml. Uses the same HubSpot fetch + associations
logic from analytics.inbound_lead_scoring.

Web enrichment follows the same two-step flow:
  1. --dump-needs-enrichment FILE   write companies needing enrichment + exit
  2. --enrich-from FILE             read pre-computed enrichment JSON

Usage:
    python -m analytics.outbound_lead_scoring
    python -m analytics.outbound_lead_scoring --dump-needs-enrichment /tmp/needs.json
    python -m analytics.outbound_lead_scoring --enrich-from /tmp/enriched.json
    python -m analytics.outbound_lead_scoring --out /tmp/scored.html
"""

from __future__ import annotations

import argparse
import html as _html
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

import analytics.inbound_lead_scoring as ils

_SCORING_PATH = Path(__file__).parent.parent / "config" / "outbound_scoring.yaml"
_REPORTS_DIR = Path(__file__).parent.parent / "reports"


def _load_outbound_cfg() -> dict:
    import yaml

    with open(_SCORING_PATH) as f:
        return yaml.safe_load(f)


def _outbound_stage_ids(pipeline_cfg: dict) -> list[str]:
    return ils._active_stage_ids(pipeline_cfg)


def _normalise_cfg(outbound_cfg: dict) -> dict:
    """Return a cfg dict compatible with inbound scoring functions.

    The inbound scoring functions read 'inbound_sources' to filter leads.
    Outbound config uses 'outbound_sources' as the key. This adapter maps
    the outbound sources into the slot the scoring functions expect.
    """
    cfg = dict(outbound_cfg)
    cfg["inbound_sources"] = outbound_cfg.get("outbound_sources", [])
    return cfg


# ── HTML render — same structure as inbound, different labels ─────────────────


def render_html(report: dict, generated_at: str) -> str:
    scored = report["scored"]
    tc = report["tier_counts"]

    rows_html = ""
    for rank, r in enumerate(scored, 1):
        bd = r["breakdown"]
        tip = (
            f"DM:{bd['decision_maker']} + Revenue:{bd['revenue']} + "
            f"Funding:{bd['funding']} + Spend:{bd['spend_capacity']}"
        )
        missing_flags = ""
        if r["missing"]["jobtitle"]:
            missing_flags += ils._missing_flag("no title") + " "
        if r["missing"]["company_data"]:
            missing_flags += ils._missing_flag("no company data") + " "
        elif r["missing"]["revenue"]:
            missing_flags += ils._missing_flag("no revenue") + " "

        fund_display = r["funding_fmt"]
        if r["funding_stage"] and r["funding_fmt"] != "—":
            fund_display = f"{r['funding_fmt']} ({r['funding_stage']})"
        elif r["funding_stage"]:
            fund_display = r["funding_stage"]

        lead_name = _html.escape(r["lead_name"])
        company = _html.escape(r["company"])
        jobtitle = _html.escape(r["jobtitle"])
        fund_display_esc = _html.escape(fund_display)
        rows_html += f"""
        <tr>
          <td style="padding:10px 14px;color:#6b7280;font-size:12px">{rank}</td>
          <td style="padding:10px 14px">
            <div style="font-weight:500">{lead_name}</div>
            <div style="font-size:12px;color:#6b7280">{company}</div>
          </td>
          <td style="padding:10px 14px">{ils._tier_badge(r["tier"])}</td>
          <td style="padding:10px 14px" title="{tip}">{ils._score_bar(r["score"])}</td>
          <td style="padding:10px 14px">
            <div style="font-size:12px;font-weight:500">{jobtitle}</div>
            <div style="font-size:11px;color:#6b7280">{r["dm_tier"]}</div>
            {missing_flags}
          </td>
          <td style="padding:10px 14px;font-size:12px">
            <div>{r["revenue_fmt"]}{' <span style="background:#dbeafe;color:#1e40af;border-radius:3px;padding:1px 4px;font-size:10px">web</span>' if r["web_enriched"] else ""}</div>
            <div style="color:#6b7280;font-size:11px">{f"{r['employees']:,} employees" if r["employees"] else "—"}</div>
          </td>
          <td style="padding:10px 14px;font-size:12px;color:#374151">{fund_display_esc}</td>
          <td style="padding:10px 14px;font-size:12px;color:#374151">{r["stage_name"]}</td>
          <td style="padding:10px 14px">{ils._days_cell(r["days_since"])}</td>
        </tr>"""

    empty = (
        ""
        if scored
        else '<tr><td colspan="9" style="padding:24px;text-align:center;color:#6b7280">No outbound leads found.</td></tr>'
    )

    data_quality_note = ""
    if report["missing_company"] or report["missing_title"]:
        notes = []
        if report["missing_company"]:
            notes.append(f"{report['missing_company']} lead(s) have no associated company")
        if report["missing_title"]:
            notes.append(
                f"{report['missing_title']} lead(s) have no job title — check contact record"
            )
        data_quality_note = f"""
      <div style="background:#fffbeb;border:1px solid #fde68a;border-radius:8px;padding:12px 16px;margin-bottom:20px;font-size:12px;color:#78350f">
        <strong>Data gaps affecting scores:</strong> {" | ".join(notes)}.
        Enrich via Clay or HubSpot Breeze.
      </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Outbound Lead Scoring — Leadle</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Fraunces:ital,wght@0,400;0,600;1,400&family=Inter+Tight:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');
  :root{{--bg:#fafaf7;--surface:#fff;--ink:#15171a;--green:#2d6a4f;--amber:#b45309;--red:#9b2226;--muted:#6b7280;--border:#e5e7eb}}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:var(--bg);color:var(--ink);font-family:'Inter Tight',sans-serif;font-size:14px;line-height:1.5;padding:32px 24px}}
  .wrap{{max-width:1200px;margin:0 auto}}
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
  <h1>Outbound Lead Scoring</h1>
  <div class="meta">Leadle RevOps &bull; LinkedIn Outbound &bull; ICP-fit score (0–100) &bull; Generated {generated_at}</div>

  <div class="stat-row">
    <div class="stat">
      <div class="stat-n">{report["total"]}</div>
      <div class="stat-l">Outbound Leads</div>
    </div>
    <div class="stat">
      <div class="stat-n" style="color:var(--red)">{tc.get("Hot", 0)}</div>
      <div class="stat-l">Hot (≥65)</div>
    </div>
    <div class="stat">
      <div class="stat-n" style="color:var(--amber)">{tc.get("Warm", 0)}</div>
      <div class="stat-l">Warm (35–64)</div>
    </div>
    <div class="stat">
      <div class="stat-n" style="color:var(--muted)">{tc.get("Cold", 0)}</div>
      <div class="stat-l">Cold (&lt;35)</div>
    </div>
  </div>

  {data_quality_note}

  <div class="card">
    <div class="card-title">Outbound Leads — ICP Fit Ranking</div>
    <table>
      <thead>
        <tr>
          <th>#</th><th>Lead / Company</th><th>Tier</th><th>Score</th>
          <th>Title / DM Fit</th><th>Revenue</th><th>Funding</th>
          <th>Stage</th><th>Last Activity</th>
        </tr>
      </thead>
      <tbody>{rows_html}{empty}</tbody>
    </table>
  </div>
</div>
</body>
</html>"""


# ── main ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="analytics.outbound_lead_scoring")
    parser.add_argument(
        "--no-enrich", action="store_true", help="Skip web enrichment step entirely"
    )
    parser.add_argument(
        "--dump-needs-enrichment",
        metavar="FILE",
        help="Write companies lacking revenue/funding to JSON file and exit",
    )
    parser.add_argument(
        "--enrich-from",
        metavar="FILE",
        help="Read pre-computed enrichment JSON and apply before scoring",
    )
    parser.add_argument("--out", help="Output HTML path")
    args = parser.parse_args(argv)

    token = os.environ.get("HUBSPOT_PRIVATE_TOKEN")
    if not token:
        print("ERROR: HUBSPOT_PRIVATE_TOKEN not set", file=sys.stderr)
        return 1

    pipeline_cfg = ils._load_pipeline_cfg()
    outbound_cfg = _load_outbound_cfg()
    scoring_cfg = _normalise_cfg(outbound_cfg)
    stage_ids = ils._active_stage_ids(pipeline_cfg)
    stage_map = ils._stage_map(pipeline_cfg)
    outbound_set = set(outbound_cfg.get("outbound_sources", []))

    print("Fetching active leads...", file=sys.stderr)
    raw = ils.fetch_active_leads(token, stage_ids)
    print(f"  {len(raw)} leads fetched", file=sys.stderr)

    print("Resolving associations (contacts + companies)...", file=sys.stderr)
    contacts, companies = ils.enrich_leads(token, raw)
    print(f"  {len(contacts)} contacts, {len(companies)} companies resolved", file=sys.stderr)

    if args.dump_needs_enrichment:
        needs = ils._companies_needing_enrichment(raw, companies, outbound_set, all_sources=False)
        Path(args.dump_needs_enrichment).write_text(json.dumps(needs, indent=2), encoding="utf-8")
        print(
            f"  {len(needs)} companies need enrichment → {args.dump_needs_enrichment}",
            file=sys.stderr,
        )
        return 0

    if args.enrich_from and not args.no_enrich:
        enrichment = json.loads(Path(args.enrich_from).read_text(encoding="utf-8"))
        companies = ils.apply_enrichment(raw, companies, enrichment)
        n_enriched = sum(1 for c in companies.values() if c.get("web_enriched"))
        print(f"  Applied enrichment: {n_enriched} companies updated", file=sys.stderr)

    # compute_scores uses all_sources=False and filters by scoring_cfg["inbound_sources"]
    # which we've mapped to outbound_sources via _normalise_cfg
    report = ils.compute_scores(raw, contacts, companies, scoring_cfg, stage_map, all_sources=False)

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    html = render_html(report, generated_at)

    out_path = args.out
    if not out_path:
        slug = date.today().isoformat()
        _REPORTS_DIR.mkdir(exist_ok=True)
        out_path = str(_REPORTS_DIR / f"outbound-lead-scoring-{slug}.html")

    Path(out_path).write_text(html, encoding="utf-8")
    print(f"Report written to {out_path}", file=sys.stderr)

    scored = report["scored"]
    tc = report["tier_counts"]
    print(f"\nOutbound Lead Scoring — ICP Fit ({date.today()})")
    print(
        f"  Scored: {report['total']}  Hot: {tc.get('Hot', 0)}  Warm: {tc.get('Warm', 0)}  Cold: {tc.get('Cold', 0)}"
    )
    if report["missing_title"]:
        print(f"  ⚠  {report['missing_title']} leads with no job title (scored 0 on DM fit)")
    if scored:
        top = scored[0]
        bd = top["breakdown"]
        print(
            f"  Top: {top['lead_name']} — {top['company']} | score={top['score']} ({top['tier']})"
        )
        print(
            f"       DM:{bd['decision_maker']}  Rev:{bd['revenue']}  Fund:{bd['funding']}  Spend:{bd['spend_capacity']}"
        )
        print(
            f"       Title: {top['jobtitle']} | Revenue: {top['revenue_fmt']} | Funding: {top['funding_fmt']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
