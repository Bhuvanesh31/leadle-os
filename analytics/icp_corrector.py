"""ICP corrector — flags score-to-stage mismatches in active leads. Process #16.

Scores every active lead using the same config/inbound_scoring.yaml and
config/outbound_scoring.yaml thresholds, then surfaces three categories of problems:

  HOT_UNDERSTAGED   — score >= hot threshold BUT in an early pipeline stage
                      (stage order <= 2: New Lead, Lead Validated).
                      These leads should be prioritised NOW.

  COLD_OVERSTAGED   — score < warm threshold BUT in Meeting Proposed (stage 5).
                      Possibly wrong-fit leads consuming meeting slots.

  ENRICHMENT_GAP    — one or more critical scoring inputs missing, so the
                      computed score may be artificially deflated:
                        • no job title → decision-maker score is 0
                        • no revenue AND no funding AND no employee count
                          → revenue + funding + spend dimensions are 0

Outputs:
  --json FILE   machine-readable report
  --out  FILE   HTML report

Usage:
    python -m analytics.icp_corrector
    python -m analytics.icp_corrector --json /tmp/icp_corrector.json
"""

from __future__ import annotations

import argparse
import html as _html
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

import httpx
import yaml

_PIPELINE_CFG = Path(__file__).parent.parent / "config" / "hubspot_pipeline.yaml"
_INBOUND_CFG = Path(__file__).parent.parent / "config" / "inbound_scoring.yaml"
_OUTBOUND_CFG = Path(__file__).parent.parent / "config" / "outbound_scoring.yaml"
_REPORTS_DIR = Path(__file__).parent.parent / "reports"


def _load_configs() -> tuple[dict, dict, dict, dict]:
    with open(_PIPELINE_CFG) as f:
        pipeline = yaml.safe_load(f)
    with open(_INBOUND_CFG) as f:
        inbound_cfg = yaml.safe_load(f)
    with open(_OUTBOUND_CFG) as f:
        outbound_cfg = yaml.safe_load(f)
    return pipeline, inbound_cfg, inbound_cfg, outbound_cfg


def _stage_meta(pipeline: dict) -> tuple[dict[str, str], dict[str, int], set[str], set[str]]:
    """Return (stage_id→name, stage_id→order, active_ids, rotting_ids).

    active_ids   — all non-terminal stages (includes transition stages like Advance to Deal)
    rotting_ids  — stages where inactivity is actionable (rotting: true); excludes transition stages
    """
    names, orders, active, rotting = {}, {}, set(), set()
    for s in pipeline["leads"]["stages"]:
        sid = s["stage_id"]
        names[sid] = s["name"]
        orders[sid] = s["order"]
        if not s.get("terminal", False):
            active.add(sid)
        if s.get("rotting", False):
            rotting.add(sid)
    return names, orders, active, rotting


def _score_title(title: str | None, emp_count: int | None, cfg: dict) -> tuple[int, str]:
    """Return (score, tier_label). Mirrors inbound_lead_scoring title logic."""
    if not title:
        return 0, "unknown"
    t = title.lower()
    is_small = (
        emp_count is not None and emp_count <= cfg["decision_maker"]["small_company_max_employees"]
    )
    for tier in cfg["decision_maker"]["title_tiers"]:
        for kw in tier.get("keywords", []):
            if kw.lower() in t:
                if tier["tier"] == "manager":
                    return (
                        tier.get("score_small", 22) if is_small else tier.get("score_large", 6)
                    ), "manager"
                elif tier["tier"] == "other":
                    return 0, "other"
                else:
                    return tier["score"], tier["tier"]
    return 0, "other"


def _parse_revenue(val: str | None) -> float | None:
    if not val:
        return None
    try:
        return float(str(val).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _score_revenue(revenue: float | None, cfg: dict) -> int:
    if revenue is None:
        return cfg["revenue"]["unknown_score"]
    for tier in cfg["revenue"]["tiers"]:
        if revenue >= tier["min_usd"]:
            return tier["score"]
    return cfg["revenue"]["unknown_score"]


def _score_funding(funding: float | None, cfg: dict) -> int:
    if funding is None:
        return cfg["funding"]["unknown_score"]
    for tier in cfg["funding"]["tiers"]:
        if funding >= tier["min_usd"]:
            return tier["score"]
    return cfg["funding"]["unknown_score"]


def _score_spend(revenue: float | None, funding: float | None, cfg: dict) -> int:
    sc = cfg["spend_capacity"]
    rev_min = cfg["revenue"]["icp_min_usd"]
    rev_low = cfg["revenue"]["tiers"][-1]["min_usd"] if cfg["revenue"]["tiers"] else 500_000
    if revenue is not None and revenue >= rev_min:
        return sc["high_score"]
    if (revenue is not None and revenue >= rev_low) or (funding is not None and funding > 0):
        return sc["medium_score"]
    return sc["low_score"]


def _tier_label(score: int, cfg: dict) -> str:
    if score >= cfg["tiers"]["hot"]:
        return "HOT"
    if score >= cfg["tiers"]["warm"]:
        return "WARM"
    return "COLD"


def _fetch_active_leads(token: str, active_ids: set[str]) -> list[dict]:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
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
            "properties": [
                "hs_lead_name",
                "lead_source_v2",
                "hs_pipeline_stage",
                "hs_contact_job_title",
                "hs_associated_contact_email",
            ],
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


def _fetch_company_for_lead(token: str, lead_id: str) -> dict | None:
    """Return company properties dict, or None if no company associated."""
    headers = {"Authorization": f"Bearer {token}"}
    r = httpx.get(
        f"https://api.hubapi.com/crm/v3/objects/leads/{lead_id}/associations/companies",
        headers=headers,
        timeout=15,
    )
    assoc = r.json().get("results", [])
    if not assoc:
        return None
    company_id = assoc[0]["id"]
    r2 = httpx.get(
        f"https://api.hubapi.com/crm/v3/objects/companies/{company_id}",
        headers=headers,
        params={"properties": "name,annualrevenue,numberofemployees,total_money_raised,domain"},
        timeout=15,
    )
    return r2.json().get("properties") or {}


def build_report(
    token: str, leads: list[dict], pipeline: dict, inbound_cfg: dict, outbound_cfg: dict
) -> dict:
    stage_names, stage_orders, _, rotting_ids = _stage_meta(pipeline)
    inbound_sources = {s.lower() for s in inbound_cfg.get("inbound_sources", [])}

    rows = []
    for lead in leads:
        p = lead.get("properties") or {}
        lead_id = lead["id"]
        name = p.get("hs_lead_name") or "(unnamed)"
        source_raw = p.get("lead_source_v2") or ""
        stage_id = p.get("hs_pipeline_stage") or ""
        stage_name = stage_names.get(stage_id, stage_id)
        stage_order = stage_orders.get(stage_id, 99)
        job_title = p.get("hs_contact_job_title") or ""

        cfg = inbound_cfg if source_raw.lower() in inbound_sources else outbound_cfg

        # Fetch company data
        company = _fetch_company_for_lead(token, lead_id) or {}
        company_name = company.get("name") or "—"
        emp_raw = company.get("numberofemployees")
        emp_count = int(emp_raw) if emp_raw and str(emp_raw).isdigit() else None
        revenue = _parse_revenue(company.get("annualrevenue"))
        funding = _parse_revenue(company.get("total_money_raised"))

        dm_score, dm_tier = _score_title(job_title, emp_count, cfg)
        rev_score = _score_revenue(revenue, cfg)
        fund_score = _score_funding(funding, cfg)
        spend_score = _score_spend(revenue, funding, cfg)
        total_score = dm_score + rev_score + fund_score + spend_score
        tier = _tier_label(total_score, cfg)

        # Detect enrichment gaps
        gaps = []
        if not job_title:
            gaps.append("no_job_title")
        if revenue is None and funding is None and emp_count is None:
            gaps.append("no_company_financials")
        elif revenue is None and funding is None:
            gaps.append("no_revenue_or_funding")

        # Classify mismatch
        flags = []
        hot_threshold = cfg["tiers"]["hot"]
        warm_threshold = cfg["tiers"]["warm"]
        in_rotting_stage = stage_id in rotting_ids
        has_enough_data = "no_job_title" not in gaps  # need at least a title to trust score

        if total_score >= hot_threshold and stage_order <= 2:
            flags.append("HOT_UNDERSTAGED")
        # COLD_OVERSTAGED only fires for actively-worked stages with trustworthy scores
        if (
            total_score < warm_threshold
            and stage_order >= 5
            and in_rotting_stage
            and has_enough_data
        ):
            flags.append("COLD_OVERSTAGED")
        if gaps:
            flags.append("ENRICHMENT_GAP")

        rows.append(
            {
                "lead_id": lead_id,
                "name": name,
                "company": company_name,
                "source": source_raw or "(none)",
                "stage": stage_name,
                "stage_order": stage_order,
                "job_title": job_title or "(missing)",
                "score": total_score,
                "tier": tier,
                "score_breakdown": {
                    "decision_maker": dm_score,
                    "dm_tier": dm_tier,
                    "revenue": rev_score,
                    "funding": fund_score,
                    "spend_capacity": spend_score,
                },
                "enrichment": {
                    "revenue": revenue,
                    "funding": funding,
                    "employees": emp_count,
                },
                "gaps": gaps,
                "flags": flags,
            }
        )

    # Sort: flagged first, then by score desc
    flag_priority = {"HOT_UNDERSTAGED": 0, "COLD_OVERSTAGED": 1, "ENRICHMENT_GAP": 2}
    rows.sort(
        key=lambda r: (
            min((flag_priority.get(f, 9) for f in r["flags"]), default=9),
            -r["score"],
        )
    )

    hot_us = [r for r in rows if "HOT_UNDERSTAGED" in r["flags"]]
    cold_os = [r for r in rows if "COLD_OVERSTAGED" in r["flags"]]
    enrich_gaps = [
        r
        for r in rows
        if "ENRICHMENT_GAP" in r["flags"]
        and "HOT_UNDERSTAGED" not in r["flags"]
        and "COLD_OVERSTAGED" not in r["flags"]
    ]
    ok = [r for r in rows if not r["flags"]]

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total_active": len(rows),
        "summary": {
            "hot_understaged": len(hot_us),
            "cold_overstaged": len(cold_os),
            "enrichment_gap_only": len(enrich_gaps),
            "ok": len(ok),
        },
        "hot_understaged": hot_us,
        "cold_overstaged": cold_os,
        "enrichment_gap": enrich_gaps,
        "ok": ok,
        "all_leads": rows,
    }


# ── HTML render ───────────────────────────────────────────────────────────────

_TIER_STYLE = {
    "HOT": "background:#fef2f2;color:#9b2226",
    "WARM": "background:#fffbeb;color:#b45309",
    "COLD": "background:#eff6ff;color:#1e40af",
}

_FLAG_STYLE = {
    "HOT_UNDERSTAGED": "background:#fef2f2;color:#9b2226",
    "COLD_OVERSTAGED": "background:#eff6ff;color:#1e40af",
    "ENRICHMENT_GAP": "background:#fffbeb;color:#b45309",
}


def _badge(label: str, style: str) -> str:
    return f'<span style="{style};border-radius:4px;padding:2px 7px;font-size:11px;font-weight:600">{label}</span>'


def _lead_rows(rows: list[dict]) -> str:
    if not rows:
        return '<tr><td colspan="7" style="padding:16px;text-align:center;color:#9ca3af;font-size:12px">None.</td></tr>'
    out = ""
    for r in rows:
        name = _html.escape(r["name"])
        company = _html.escape(r["company"])
        jt = _html.escape(r["job_title"])
        tier_badge = _badge(r["tier"], _TIER_STYLE.get(r["tier"], ""))
        flags_html = " ".join(_badge(f, _FLAG_STYLE.get(f, "")) for f in r["flags"])
        sb = r["score_breakdown"]
        breakdown = f"DM={sb['decision_maker']} Rev={sb['revenue']} Fund={sb['funding']} Spend={sb['spend_capacity']}"
        gaps = ", ".join(r["gaps"]) if r["gaps"] else "—"
        out += f"""<tr>
          <td style="padding:9px 14px">
            <div style="font-size:13px;font-weight:500">{name}</div>
            <div style="font-size:11px;color:#6b7280">{company}</div>
          </td>
          <td style="padding:9px 14px;font-size:12px">{jt}</td>
          <td style="padding:9px 14px">
            <span style="font-family:'JetBrains Mono',monospace;font-size:13px;font-weight:600">{r["score"]}</span>
            {tier_badge}
            <div style="font-size:10px;color:#9ca3af;margin-top:3px">{breakdown}</div>
          </td>
          <td style="padding:9px 14px;font-size:12px;color:#374151">{r["stage"]}</td>
          <td style="padding:9px 14px">{flags_html if flags_html else "—"}</td>
          <td style="padding:9px 14px;font-size:11px;color:#b45309">{gaps}</td>
        </tr>"""
    return out


def render_html(report: dict) -> str:
    s = report["summary"]
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ICP Corrector — Leadle</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Fraunces:ital,wght@0,400;0,600;1,400&family=Inter+Tight:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');
  :root{{--bg:#fafaf7;--surface:#fff;--ink:#15171a;--red:#9b2226;--amber:#b45309;--blue:#1e40af;--muted:#6b7280;--border:#e5e7eb}}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:var(--bg);color:var(--ink);font-family:'Inter Tight',sans-serif;font-size:14px;line-height:1.5;padding:32px 24px}}
  .wrap{{max-width:1200px;margin:0 auto}}
  h1{{font-family:'Fraunces',serif;font-size:26px;font-weight:600;margin-bottom:4px}}
  .meta{{color:var(--muted);font-size:12px;margin-bottom:28px}}
  .stat-row{{display:flex;gap:16px;margin-bottom:20px}}
  .stat{{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:14px 18px;flex:1}}
  .stat-n{{font-family:'JetBrains Mono',monospace;font-size:22px;font-weight:500}}
  .stat-l{{font-size:11px;color:var(--muted);margin-top:2px;text-transform:uppercase;letter-spacing:.04em}}
  .card{{background:var(--surface);border-radius:10px;border:1px solid var(--border);overflow:hidden;margin-bottom:24px}}
  .card-title{{padding:12px 16px;font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.05em;border-bottom:1px solid var(--border);background:#f9fafb;color:var(--muted)}}
  table{{width:100%;border-collapse:collapse}}
  thead th{{background:#f3f4f6;padding:9px 14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);font-weight:600}}
  tbody tr:not(:last-child){{border-bottom:1px solid var(--border)}}
  tbody tr:hover{{background:#f9fafb}}
</style>
</head>
<body>
<div class="wrap">
  <h1>ICP Corrector</h1>
  <div class="meta">Leadle RevOps &bull; {report["total_active"]} active leads scored &bull; Generated {report["generated_at"]}</div>

  <div class="stat-row">
    <div class="stat">
      <div class="stat-n" style="color:var(--red)">{s["hot_understaged"]}</div>
      <div class="stat-l">HOT understaged</div>
    </div>
    <div class="stat">
      <div class="stat-n" style="color:var(--blue)">{s["cold_overstaged"]}</div>
      <div class="stat-l">COLD overstaged</div>
    </div>
    <div class="stat">
      <div class="stat-n" style="color:var(--amber)">{s["enrichment_gap_only"]}</div>
      <div class="stat-l">Enrichment gap only</div>
    </div>
    <div class="stat">
      <div class="stat-n">{s["ok"]}</div>
      <div class="stat-l">OK (no flags)</div>
    </div>
  </div>

  <div class="card">
    <div class="card-title">HOT Understaged — high ICP fit stuck in early stages (action now)</div>
    <table>
      <thead><tr><th>Lead / Company</th><th>Title</th><th>Score</th><th>Stage</th><th>Flags</th><th>Data Gaps</th></tr></thead>
      <tbody>{_lead_rows(report["hot_understaged"])}</tbody>
    </table>
  </div>

  <div class="card">
    <div class="card-title">COLD Overstaged — low ICP fit at Meeting Proposed (review fit)</div>
    <table>
      <thead><tr><th>Lead / Company</th><th>Title</th><th>Score</th><th>Stage</th><th>Flags</th><th>Data Gaps</th></tr></thead>
      <tbody>{_lead_rows(report["cold_overstaged"])}</tbody>
    </table>
  </div>

  <div class="card">
    <div class="card-title">Enrichment Gap — score may be deflated by missing data</div>
    <table>
      <thead><tr><th>Lead / Company</th><th>Title</th><th>Score</th><th>Stage</th><th>Flags</th><th>Data Gaps</th></tr></thead>
      <tbody>{_lead_rows(report["enrichment_gap"])}</tbody>
    </table>
  </div>

  <div class="card">
    <div class="card-title">All Active Leads — scored</div>
    <table>
      <thead><tr><th>Lead / Company</th><th>Title</th><th>Score</th><th>Stage</th><th>Flags</th><th>Data Gaps</th></tr></thead>
      <tbody>{_lead_rows(report["all_leads"])}</tbody>
    </table>
  </div>
</div>
</body>
</html>"""


# ── main ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="analytics.icp_corrector")
    parser.add_argument("--json", metavar="FILE", help="Dump report JSON to this path")
    parser.add_argument("--out", metavar="FILE", help="Output HTML path")
    args = parser.parse_args(argv)

    token = os.environ.get("HUBSPOT_PRIVATE_TOKEN")
    if not token:
        print("ERROR: HUBSPOT_PRIVATE_TOKEN not set", file=sys.stderr)
        return 1

    pipeline, inbound_cfg, _, outbound_cfg = _load_configs()
    _, _, active_ids, _ = _stage_meta(pipeline)

    print("Fetching active leads...", file=sys.stderr)
    leads = _fetch_active_leads(token, active_ids)
    print(f"  {len(leads)} active leads", file=sys.stderr)

    print("Fetching company data per lead...", file=sys.stderr)
    report = build_report(token, leads, pipeline, inbound_cfg, outbound_cfg)
    s = report["summary"]

    print(f"\nICP Corrector — {report['generated_at']}")
    print(f"  Active leads scored: {report['total_active']}")
    print(f"  HOT understaged:     {s['hot_understaged']}")
    print(f"  COLD overstaged:     {s['cold_overstaged']}")
    print(f"  Enrichment gap only: {s['enrichment_gap_only']}")
    print(f"  OK (no flags):       {s['ok']}")

    if report["hot_understaged"]:
        print("\n  HOT understaged leads:")
        for r in report["hot_understaged"]:
            print(
                f"    [{r['score']:3d}] {r['name'][:35]:35} | {r['stage']:20} | {r['job_title'][:30]}"
            )

    if report["cold_overstaged"]:
        print("\n  COLD overstaged leads:")
        for r in report["cold_overstaged"]:
            print(
                f"    [{r['score']:3d}] {r['name'][:35]:35} | {r['stage']:20} | {r['job_title'][:30]}"
            )

    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Report JSON → {args.json}", file=sys.stderr)

    html = render_html(report)
    out_path = args.out
    if not out_path:
        slug = date.today().isoformat()
        _REPORTS_DIR.mkdir(exist_ok=True)
        out_path = str(_REPORTS_DIR / f"icp-corrector-{slug}.html")
    Path(out_path).write_text(html, encoding="utf-8")
    print(f"Report → {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
