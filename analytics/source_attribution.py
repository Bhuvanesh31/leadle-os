"""HubSpot source attribution gap finder — process #9.

Scans ALL leads (active + terminal) for missing or unrecognised lead_source_v2 values.
Source gaps affect which scoring model is applied and can silently exclude leads from
both inbound and outbound reports.

Gap types:
  unattributed   — lead_source_v2 is empty or null
  unrecognized   — has a value, but that value isn't in either scoring config
                   (e.g. "LinkedIn Inbound", "Reference", "Inbound Call")

Known sources (loaded from config):
  inbound  → config/inbound_scoring.yaml  → inbound_sources list
  outbound → config/outbound_scoring.yaml → outbound_sources list

Outputs:
  --json FILE   machine-readable report (for Claude Code narrative step)
  --out FILE    HTML report

Usage:
    python -m analytics.source_attribution
    python -m analytics.source_attribution --json /tmp/source_gaps.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path

import httpx
import yaml

_REPORTS_DIR = Path(__file__).parent.parent / "reports"
_INBOUND_CFG = Path(__file__).parent.parent / "config" / "inbound_scoring.yaml"
_OUTBOUND_CFG = Path(__file__).parent.parent / "config" / "outbound_scoring.yaml"

_STAGE_NAMES = {
    "new-stage-id": "New Lead",
    "attempting-stage-id": "Lead Validated",
    "connected-stage-id": "Lead Qualified",
    "3200435922": "Lead Engaged",
    "3200435923": "Meeting Proposed",
    "qualified-stage-id": "Advance to Deal",
    "unqualified-stage-id": "Lead Archived",
}

_ACTIVE_STAGES = {
    "new-stage-id", "attempting-stage-id", "connected-stage-id",
    "3200435922", "3200435923",
}


def _load_known_sources() -> tuple[set[str], set[str]]:
    with open(_INBOUND_CFG) as f:
        inbound_cfg = yaml.safe_load(f)
    with open(_OUTBOUND_CFG) as f:
        outbound_cfg = yaml.safe_load(f)
    inbound = set(inbound_cfg.get("inbound_sources", [])) - {""}
    outbound = set(outbound_cfg.get("outbound_sources", []))
    return inbound, outbound


def _fetch_all_leads(token: str) -> list[dict]:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    props = [
        "hs_lead_name", "lead_source_v2", "hs_pipeline_stage",
        "hs_createdate", "hs_associated_company_name",
    ]
    results = []
    after = None
    while True:
        body: dict = {"properties": props, "limit": 100}
        if after:
            body["after"] = after
        r = httpx.post(
            "https://api.hubapi.com/crm/v3/objects/leads/search",
            headers=headers, json=body, timeout=30,
        )
        data = r.json()
        results.extend(data.get("results", []))
        after = (data.get("paging") or {}).get("next", {}).get("after")
        if not after:
            break
    return results


def _classify(source: str | None, inbound: set[str], outbound: set[str]) -> str:
    if not source:
        return "unattributed"
    if source in inbound:
        return "known_inbound"
    if source in outbound:
        return "known_outbound"
    return "unrecognized"


def build_report(leads: list[dict], inbound: set[str], outbound: set[str]) -> dict:
    source_counts: Counter = Counter()
    gap_leads: list[dict] = []
    unrecognized_sources: Counter = Counter()
    by_class: Counter = Counter()

    for lead in leads:
        p = lead.get("properties") or {}
        src = p.get("lead_source_v2") or ""
        stage_id = p.get("hs_pipeline_stage") or ""
        cls = _classify(src, inbound, outbound)
        source_counts[src] += 1
        by_class[cls] += 1

        if cls in ("unattributed", "unrecognized"):
            gap_leads.append({
                "lead_name": p.get("hs_lead_name") or "(unnamed)",
                "company": p.get("hs_associated_company_name") or "—",
                "source": src,
                "classification": cls,
                "stage_id": stage_id,
                "stage_name": _STAGE_NAMES.get(stage_id, stage_id),
                "is_active": stage_id in _ACTIVE_STAGES,
                "created": (p.get("hs_createdate") or "")[:10],
            })
            if cls == "unrecognized":
                unrecognized_sources[src] += 1

    gap_leads.sort(key=lambda x: (not x["is_active"], x["source"], x["created"]))

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total_leads": len(leads),
        "by_classification": dict(by_class),
        "source_distribution": [
            {"source": s or "(empty)", "count": c, "classification": _classify(s, inbound, outbound)}
            for s, c in source_counts.most_common()
        ],
        "unrecognized_sources": [
            {"source": s, "count": c} for s, c in unrecognized_sources.most_common()
        ],
        "gap_leads": gap_leads,
        "config_recommendation": {
            "add_to_inbound_sources": sorted(
                s for s in unrecognized_sources
                if s not in outbound and _looks_inbound(s)
            ),
            "add_to_outbound_sources": sorted(
                s for s in unrecognized_sources
                if s not in inbound and not _looks_inbound(s)
            ),
        },
    }


def _looks_inbound(source: str) -> bool:
    outbound_hints = ("outbound", "campaign", "sequence", "cold")
    return not any(h in source.lower() for h in outbound_hints)


# ── HTML render ───────────────────────────────────────────────────────────────

def render_html(report: dict) -> str:
    bc = report["by_classification"]
    gap_leads = report["gap_leads"]

    source_rows = ""
    for item in report["source_distribution"]:
        cls_color = {
            "known_inbound": "#2d6a4f",
            "known_outbound": "#1e40af",
            "unattributed": "#9b2226",
            "unrecognized": "#b45309",
        }.get(item["classification"], "#6b7280")
        cls_label = {
            "known_inbound": "Inbound",
            "known_outbound": "Outbound",
            "unattributed": "Unattributed",
            "unrecognized": "Unrecognized",
        }.get(item["classification"], item["classification"])
        source_rows += f"""
        <tr>
          <td style="padding:9px 14px;font-family:'JetBrains Mono',monospace;font-size:12px">{item['source']}</td>
          <td style="padding:9px 14px;font-family:'JetBrains Mono',monospace;font-size:13px;text-align:right">{item['count']}</td>
          <td style="padding:9px 14px">
            <span style="color:{cls_color};font-size:12px;font-weight:500">{cls_label}</span>
          </td>
        </tr>"""

    gap_rows = ""
    for g in gap_leads:
        active_badge = (
            '<span style="background:#fef2f2;color:#9b2226;border-radius:4px;padding:1px 6px;font-size:10px;font-weight:600">ACTIVE</span>'
            if g["is_active"] else
            '<span style="background:#f3f4f6;color:#9ca3af;border-radius:4px;padding:1px 6px;font-size:10px">archived/converted</span>'
        )
        src_display = g["source"] if g["source"] else "(empty)"
        cls_color = "#9b2226" if g["classification"] == "unattributed" else "#b45309"
        gap_rows += f"""
        <tr>
          <td style="padding:10px 14px">
            <div style="font-weight:500;font-size:13px">{g['lead_name']}</div>
            <div style="font-size:12px;color:#6b7280">{g['company']}</div>
          </td>
          <td style="padding:10px 14px;font-family:'JetBrains Mono',monospace;font-size:12px;color:{cls_color}">{src_display}</td>
          <td style="padding:10px 14px;font-size:12px;color:#374151">{g['stage_name']}</td>
          <td style="padding:10px 14px">{active_badge}</td>
          <td style="padding:10px 14px;font-size:12px;color:#6b7280">{g['created']}</td>
        </tr>"""

    reco = report["config_recommendation"]
    reco_inbound = ", ".join(f'"{s}"' for s in reco["add_to_inbound_sources"]) or "none"
    reco_outbound = ", ".join(f'"{s}"' for s in reco["add_to_outbound_sources"]) or "none"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Source Attribution Gaps — Leadle</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Fraunces:ital,wght@0,400;0,600;1,400&family=Inter+Tight:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');
  :root{{--bg:#fafaf7;--surface:#fff;--ink:#15171a;--green:#2d6a4f;--amber:#b45309;--red:#9b2226;--muted:#6b7280;--border:#e5e7eb}}
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
  .grid2{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:20px}}
  table{{width:100%;border-collapse:collapse}}
  thead th{{background:#f3f4f6;padding:9px 14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);font-weight:600}}
  tbody tr:not(:last-child){{border-bottom:1px solid var(--border)}}
  tbody tr:hover{{background:#f9fafb}}
  .reco{{background:#fffbeb;border:1px solid #fde68a;border-radius:8px;padding:14px 16px;margin-bottom:20px;font-size:13px}}
  .reco strong{{color:#78350f}}
  code{{background:#f3f4f6;border-radius:3px;padding:1px 5px;font-family:'JetBrains Mono',monospace;font-size:12px}}
</style>
</head>
<body>
<div class="wrap">
  <h1>Source Attribution Gaps</h1>
  <div class="meta">Leadle RevOps &bull; All leads (active + archived) &bull; Generated {report['generated_at']}</div>

  <div class="stat-row">
    <div class="stat">
      <div class="stat-n">{report['total_leads']}</div>
      <div class="stat-l">Total Leads</div>
    </div>
    <div class="stat">
      <div class="stat-n" style="color:var(--green)">{bc.get('known_inbound', 0)}</div>
      <div class="stat-l">Known Inbound</div>
    </div>
    <div class="stat">
      <div class="stat-n" style="color:#1e40af">{bc.get('known_outbound', 0)}</div>
      <div class="stat-l">Known Outbound</div>
    </div>
    <div class="stat">
      <div class="stat-n" style="color:var(--red)">{bc.get('unattributed', 0)}</div>
      <div class="stat-l">Unattributed</div>
    </div>
    <div class="stat">
      <div class="stat-n" style="color:var(--amber)">{bc.get('unrecognized', 0)}</div>
      <div class="stat-l">Unrecognized Source</div>
    </div>
  </div>

  <div class="reco">
    <strong>Config fix recommended:</strong><br>
    Add to <code>inbound_sources</code> in <code>config/inbound_scoring.yaml</code>: {reco_inbound}<br>
    Add to <code>outbound_sources</code> in <code>config/outbound_scoring.yaml</code>: {reco_outbound if reco["add_to_outbound_sources"] else "none"}
  </div>

  <div class="grid2">
    <div class="card">
      <div class="card-title">Source Distribution — All Leads</div>
      <table>
        <thead><tr><th>Source Value</th><th style="text-align:right">Count</th><th>Classification</th></tr></thead>
        <tbody>{source_rows}</tbody>
      </table>
    </div>
    <div>
      <div class="card" style="padding:16px">
        <div style="font-weight:600;font-size:13px;margin-bottom:12px">About This Report</div>
        <p style="font-size:13px;color:#374151;line-height:1.6;margin-bottom:10px">
          <strong>Unattributed</strong> leads have an empty <code>lead_source_v2</code> field.
          The inbound scoring config includes <code>""</code> as a valid inbound source,
          so these are silently counted as inbound.
        </p>
        <p style="font-size:13px;color:#374151;line-height:1.6;margin-bottom:10px">
          <strong>Unrecognized</strong> leads have a custom source value that isn't
          in either <code>inbound_sources</code> or <code>outbound_sources</code>.
          They are excluded from both scoring models unless <code>--all-sources</code> is used.
        </p>
        <p style="font-size:13px;color:#374151;line-height:1.6">
          Fix: update the YAML configs to include the new source values.
          HubSpot record updates (tagging empty-source leads) must be done manually
          in HubSpot — this system is read-only.
        </p>
      </div>
    </div>
  </div>

  <div class="card">
    <div class="card-title">Gap Leads — Needs Source Fix in HubSpot</div>
    <table>
      <thead>
        <tr>
          <th>Lead / Company</th>
          <th>Source Value</th>
          <th>Stage</th>
          <th>Status</th>
          <th>Created</th>
        </tr>
      </thead>
      <tbody>{gap_rows}</tbody>
    </table>
  </div>
</div>
</body>
</html>"""


# ── main ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="analytics.source_attribution")
    parser.add_argument("--json", metavar="FILE", help="Dump report JSON to this path")
    parser.add_argument("--out", metavar="FILE", help="Output HTML path")
    args = parser.parse_args(argv)

    token = os.environ.get("HUBSPOT_PRIVATE_TOKEN")
    if not token:
        print("ERROR: HUBSPOT_PRIVATE_TOKEN not set", file=sys.stderr)
        return 1

    inbound_known, outbound_known = _load_known_sources()

    print("Fetching all leads...", file=sys.stderr)
    leads = _fetch_all_leads(token)
    print(f"  {len(leads)} total leads", file=sys.stderr)

    report = build_report(leads, inbound_known, outbound_known)
    bc = report["by_classification"]

    print(f"\nSource Attribution — {report['generated_at']}")
    print(f"  Total: {report['total_leads']}  |  "
          f"Known inbound: {bc.get('known_inbound', 0)}  "
          f"Known outbound: {bc.get('known_outbound', 0)}  "
          f"Unattributed: {bc.get('unattributed', 0)}  "
          f"Unrecognized: {bc.get('unrecognized', 0)}")

    if report["unrecognized_sources"]:
        print("  Unrecognized source values:")
        for item in report["unrecognized_sources"]:
            print(f"    '{item['source']}': {item['count']} leads")

    active_gaps = [g for g in report["gap_leads"] if g["is_active"]]
    if active_gaps:
        print(f"  ⚠  {len(active_gaps)} ACTIVE leads with source gaps (affect current scoring):")
        for g in active_gaps:
            print(f"    → {g['lead_name']} / {g['company']} [{g['stage_name']}] source='{g['source']}'")

    reco = report["config_recommendation"]
    if reco["add_to_inbound_sources"]:
        print(f"  → Add to inbound_sources config: {reco['add_to_inbound_sources']}")
    if reco["add_to_outbound_sources"]:
        print(f"  → Add to outbound_sources config: {reco['add_to_outbound_sources']}")

    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Report JSON → {args.json}", file=sys.stderr)

    html = render_html(report)
    out_path = args.out
    if not out_path:
        slug = date.today().isoformat()
        _REPORTS_DIR.mkdir(exist_ok=True)
        out_path = str(_REPORTS_DIR / f"source-attribution-{slug}.html")
    Path(out_path).write_text(html, encoding="utf-8")
    print(f"Report → {out_path}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
