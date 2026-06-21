"""Inbound lead scoring — ICP-fit ranking.

Scores each active inbound lead 0–100 across four ICP dimensions:
  • Decision maker fit  (40 pts) — contact role × company size
  • Revenue fit         (25 pts) — company annual revenue vs $2M threshold
  • Funding fit         (20 pts) — total funding raised vs $2M threshold
  • Spend capacity      (15 pts) — derived ability to spend $10K/quarter

Fetches enriched company + contact data via HubSpot associations API.
Web enrichment is a two-step flow managed by the /inbound-lead-scoring slash command:
  1. --dump-needs-enrichment FILE  writes companies lacking revenue/funding to JSON and exits
  2. --enrich-from FILE            reads pre-computed enrichment JSON before scoring

All weights and thresholds live in config/inbound_scoring.yaml.

Usage:
    python -m analytics.inbound_lead_scoring
    python -m analytics.inbound_lead_scoring --all-sources
    python -m analytics.inbound_lead_scoring --no-enrich
    python -m analytics.inbound_lead_scoring --dump-needs-enrichment /tmp/needs.json
    python -m analytics.inbound_lead_scoring --enrich-from /tmp/enriched.json
    python -m analytics.inbound_lead_scoring --out /tmp/scored.html
"""
from __future__ import annotations

import argparse
import html as _html
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml

_BASE_URL = "https://api.hubapi.com"
_PAGE_LIMIT = 100
_CONFIG_PATH = Path(__file__).parent.parent / "config" / "hubspot_pipeline.yaml"
_SCORING_PATH = Path(__file__).parent.parent / "config" / "inbound_scoring.yaml"

_LEAD_PROPS = [
    "hs_object_id",
    "hs_lead_name",
    "hs_pipeline_stage",
    "hs_createdate",
    "hs_lastmodifieddate",
    "hs_contact_last_activity_date",
    "hs_associated_contact_firstname",
    "hs_associated_contact_lastname",
    "hs_associated_contact_email",
    "hs_associated_contact_jobtitle",   # may be empty; fallback via Contact batch
    "hs_associated_company_name",
    "lead_source_v2",
]

_CONTACT_PROPS = ["firstname", "lastname", "email", "jobtitle"]
_COMPANY_PROPS = [
    "name",
    "annualrevenue",
    "numberofemployees",
    "total_money_raised",
    "hs_latest_funding_stage",
]


# ── config ────────────────────────────────────────────────────────────────────

def _load_pipeline_cfg() -> dict:
    with open(_CONFIG_PATH) as f:
        return yaml.safe_load(f)


def _load_scoring_cfg() -> dict:
    with open(_SCORING_PATH) as f:
        return yaml.safe_load(f)


def _active_stage_ids(cfg: dict) -> list[str]:
    return [s["stage_id"] for s in cfg["leads"]["stages"] if s.get("rotting", True)]


def _stage_map(cfg: dict) -> dict[str, str]:
    return {s["stage_id"]: s["name"] for s in cfg["leads"]["stages"]}


# ── HubSpot fetch ─────────────────────────────────────────────────────────────

def fetch_active_leads(token: str, stage_ids: list[str]) -> list[dict]:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    out: list[dict] = []
    after: str | None = None

    with httpx.Client(headers=headers, timeout=30.0) as client:
        while True:
            body: dict[str, Any] = {
                "filterGroups": [{"filters": [
                    {"propertyName": "hs_pipeline_stage", "operator": "IN", "values": stage_ids}
                ]}],
                "properties": _LEAD_PROPS,
                "sorts": [{"propertyName": "hs_createdate", "direction": "DESCENDING"}],
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


def _batch_associations(client: httpx.Client, from_type: str, to_type: str,
                         from_ids: list[str]) -> dict[str, str]:
    """Return {from_id: first_to_id} via v4 batch associations API."""
    result: dict[str, str] = {}
    for i in range(0, len(from_ids), 100):
        chunk = from_ids[i:i + 100]
        r = client.post(
            f"{_BASE_URL}/crm/v4/associations/{from_type}/{to_type}/batch/read",
            json={"inputs": [{"id": fid} for fid in chunk]},
        )
        if r.status_code in (404, 400):
            break
        r.raise_for_status()
        for assoc in r.json().get("results", []):
            from_id = str(assoc["from"]["id"])
            to_list = assoc.get("to", [])
            if to_list:
                result[from_id] = str(to_list[0]["toObjectId"])
    return result


def _batch_read(client: httpx.Client, object_type: str,
                ids: list[str], properties: list[str]) -> dict[str, dict]:
    """Return {id: properties_dict} via v3 batch read API."""
    result: dict[str, dict] = {}
    for i in range(0, len(ids), 100):
        chunk = ids[i:i + 100]
        r = client.post(
            f"{_BASE_URL}/crm/v3/objects/{object_type}/batch/read",
            json={"inputs": [{"id": oid} for oid in chunk], "properties": properties},
        )
        r.raise_for_status()
        for obj in r.json().get("results", []):
            result[str(obj["id"])] = obj.get("properties", {})
    return result


def enrich_leads(token: str, leads: list[dict]) -> tuple[dict[str, dict], dict[str, dict]]:
    """Return ({lead_id: contact_props}, {lead_id: company_props}) via associations."""
    lead_ids = [str(lead["id"]) for lead in leads]
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    with httpx.Client(headers=headers, timeout=30.0) as client:
        lead_to_contact = _batch_associations(client, "leads", "contacts", lead_ids)
        lead_to_company = _batch_associations(client, "leads", "companies", lead_ids)

        # Dedupe IDs before batch-reading
        contact_ids = list(set(lead_to_contact.values()))
        company_ids = list(set(lead_to_company.values()))

        contacts_by_id = _batch_read(client, "contacts", contact_ids, _CONTACT_PROPS) if contact_ids else {}
        companies_by_id = _batch_read(client, "companies", company_ids, _COMPANY_PROPS) if company_ids else {}

    # Map back to lead_id
    contacts: dict[str, dict] = {
        lid: contacts_by_id[cid]
        for lid, cid in lead_to_contact.items()
        if cid in contacts_by_id
    }
    companies: dict[str, dict] = {
        lid: companies_by_id[cid]
        for lid, cid in lead_to_company.items()
        if cid in companies_by_id
    }
    return contacts, companies


# ── web enrichment (two-step: dump → external lookup → apply) ─────────────────
#
# Web enrichment is orchestrated by the /inbound-lead-scoring slash command.
# The Python script handles the deterministic parts; Claude Code handles web lookup
# using the Exa MCP tool.  The two halves share a JSON contract file.


def _companies_needing_enrichment(
    leads: list[dict],
    companies: dict[str, dict],
    inbound_set: set[str],
    all_sources: bool,
) -> list[dict]:
    """Return [{lead_id, company_name}] for inbound leads missing revenue + funding."""
    seen_names: set[str] = set()
    result = []
    for lead in leads:
        source = (lead.get("properties") or {}).get("lead_source_v2") or ""
        if not all_sources and source not in inbound_set:
            continue

        lid = str(lead["id"])
        comp = companies.get(lid, {})

        if comp.get("annualrevenue") and comp.get("total_money_raised"):
            continue

        p = lead.get("properties", {})
        company_name = (
            p.get("hs_associated_company_name") or comp.get("name") or ""
        ).strip()
        if not company_name or company_name in seen_names:
            continue

        seen_names.add(company_name)
        result.append({"lead_id": lid, "company_name": company_name})
    return result


def apply_enrichment(
    leads: list[dict],
    companies: dict[str, dict],
    enrichment: dict[str, dict],
) -> dict[str, dict]:
    """Merge web-sourced enrichment data into companies dict.

    enrichment format: {"Company Name": {"annual_revenue_usd": N, "total_funding_usd": N,
                                          "funding_stage": "Series A"}}
    Returns a new companies dict; marks patched records with web_enriched = 'true'.
    """
    enriched = {lid: dict(props) for lid, props in companies.items()}

    name_to_lids: dict[str, list[str]] = {}
    for lead in leads:
        lid = str(lead["id"])
        comp = enriched.get(lid, {})
        p = lead.get("properties", {})
        name = (p.get("hs_associated_company_name") or comp.get("name") or "").strip()
        if name:
            name_to_lids.setdefault(name, []).append(lid)

    for company_name, web in enrichment.items():
        for lid in name_to_lids.get(company_name, []):
            comp = enriched.get(lid, {})
            patched = False
            if not comp.get("annualrevenue") and web.get("annual_revenue_usd") is not None:
                comp["annualrevenue"] = str(web["annual_revenue_usd"])
                patched = True
            if not comp.get("total_money_raised") and web.get("total_funding_usd") is not None:
                comp["total_money_raised"] = str(web["total_funding_usd"])
                patched = True
            if web.get("funding_stage") and not comp.get("hs_latest_funding_stage"):
                comp["hs_latest_funding_stage"] = web["funding_stage"]
            if patched:
                comp["web_enriched"] = "true"
                enriched[lid] = comp

    return enriched


# ── scoring ───────────────────────────────────────────────────────────────────

def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _parse_float(s: str | None) -> float | None:
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _classify_title(title: str | None, employees: int | None, cfg: dict) -> tuple[int, str]:
    """Return (score, tier_name). Tier name used for display."""
    if not title:
        return 0, "unknown"
    title_lower = title.lower()
    small_threshold = cfg["decision_maker"]["small_company_max_employees"]
    is_small = employees is not None and employees <= small_threshold

    for tier in cfg["decision_maker"]["title_tiers"]:
        if tier["tier"] == "other":
            continue   # catch-all — no keywords to match, returns at end
        keywords = [kw.lower() for kw in tier.get("keywords", [])]
        if any(kw in title_lower for kw in keywords):
            name = tier["tier"]
            if name == "manager":
                score = tier["score_small"] if is_small else tier["score_large"]
                label = f"Manager ({'small co.' if is_small else 'large co.'})"
            else:
                score = tier.get("score", 0)
                label = name.replace("_", " ").title()
            return score, label
    return 0, "other"


def _score_tiered(value: float | None, tiers: list[dict], unknown_score: int) -> int:
    if value is None:
        return unknown_score
    for tier in sorted(tiers, key=lambda t: -t["min_usd"]):
        if value >= tier["min_usd"]:
            return tier["score"]
    return unknown_score


def _score_spend(revenue: float | None, funding: float | None, cfg: dict) -> int:
    sc = cfg["spend_capacity"]
    rev_min = cfg["revenue"]["icp_min_usd"]
    if revenue is not None and revenue >= rev_min:
        return sc["high_score"]
    if (revenue is not None and revenue >= 500000) or (funding is not None and funding > 0):
        return sc["medium_score"]
    return sc["low_score"]


def _tier(score: int, cfg: dict) -> str:
    if score >= cfg["tiers"]["hot"]:
        return "Hot"
    if score >= cfg["tiers"]["warm"]:
        return "Warm"
    return "Cold"


def _fmt_usd(value: float | None) -> str:
    if value is None:
        return "—"
    if value >= 1_000_000:
        return f"${value/1_000_000:.1f}M"
    if value >= 1_000:
        return f"${value/1_000:.0f}K"
    return f"${value:.0f}"


def score_lead(lead: dict, contact_props: dict | None,
               company_props: dict | None, cfg: dict, stage_map: dict) -> dict:
    p = lead.get("properties", {})
    cp = contact_props or {}
    comp = company_props or {}

    first = p.get("hs_associated_contact_firstname") or cp.get("firstname") or ""
    last = p.get("hs_associated_contact_lastname") or cp.get("lastname") or ""
    contact_name = f"{first} {last}".strip() or p.get("hs_associated_contact_email") or "—"
    email = p.get("hs_associated_contact_email") or cp.get("email") or ""

    # Job title: try rolled-up Lead property first, then Contact record
    jobtitle = (p.get("hs_associated_contact_jobtitle") or "").strip() or cp.get("jobtitle") or ""

    company_name = p.get("hs_associated_company_name") or comp.get("name") or "—"
    employees_raw = _parse_float(comp.get("numberofemployees"))
    employees = int(employees_raw) if employees_raw is not None else None
    revenue = _parse_float(comp.get("annualrevenue"))
    funding = _parse_float(comp.get("total_money_raised"))
    funding_stage = comp.get("hs_latest_funding_stage") or ""

    stage_id = p.get("hs_pipeline_stage") or ""
    source = p.get("lead_source_v2") or ""
    created = _parse_date(p.get("hs_createdate"))
    last_activity = (
        _parse_date(p.get("hs_contact_last_activity_date"))
        or _parse_date(p.get("hs_lastmodifieddate"))
    )
    days_since = (date.today() - last_activity).days if last_activity else None

    dm_score, dm_tier = _classify_title(jobtitle, employees, cfg)
    rev_score = _score_tiered(revenue, cfg["revenue"]["tiers"], cfg["revenue"]["unknown_score"])
    fund_score = _score_tiered(funding, cfg["funding"]["tiers"], cfg["funding"]["unknown_score"])
    spend_score = _score_spend(revenue, funding, cfg)
    total = dm_score + rev_score + fund_score + spend_score

    return {
        "id": lead.get("id"),
        "lead_name": p.get("hs_lead_name") or contact_name,
        "contact_name": contact_name,
        "company": company_name,
        "email": email or "—",
        "jobtitle": jobtitle or "—",
        "dm_tier": dm_tier,
        "stage_name": stage_map.get(stage_id, stage_id or "Unknown"),
        "source": source or "—",
        "created": created.isoformat() if created else "—",
        "last_activity": last_activity.isoformat() if last_activity else None,
        "days_since": days_since,
        "employees": employees,
        "revenue_fmt": _fmt_usd(revenue),
        "funding_fmt": _fmt_usd(funding),
        "funding_stage": funding_stage,
        "score": total,
        "tier": _tier(total, cfg),
        "breakdown": {
            "decision_maker": dm_score,
            "revenue": rev_score,
            "funding": fund_score,
            "spend_capacity": spend_score,
        },
        "web_enriched": comp.get("web_enriched") == "true",
        "missing": {
            "jobtitle": not jobtitle,
            "revenue": revenue is None,
            "funding": funding is None,
            "company_data": not company_props,
        },
    }


def compute_scores(raw_leads: list[dict], contacts: dict[str, dict],
                   companies: dict[str, dict], scoring_cfg: dict,
                   stage_map: dict[str, str], all_sources: bool) -> dict:
    inbound_set = set(scoring_cfg["inbound_sources"])
    scored = []
    excluded = 0

    for lead in raw_leads:
        source = (lead.get("properties") or {}).get("lead_source_v2") or ""
        if not all_sources and source not in inbound_set:
            excluded += 1
            continue
        lid = str(lead["id"])
        scored.append(score_lead(
            lead,
            contacts.get(lid),
            companies.get(lid),
            scoring_cfg,
            stage_map,
        ))

    scored.sort(key=lambda r: -r["score"])
    tc = {"Hot": 0, "Warm": 0, "Cold": 0}
    for r in scored:
        tc[r["tier"]] += 1

    missing_company = sum(1 for r in scored if r["missing"]["company_data"])
    missing_title = sum(1 for r in scored if r["missing"]["jobtitle"])

    return {
        "scored": scored,
        "excluded_outbound": excluded,
        "tier_counts": tc,
        "total": len(scored),
        "missing_company": missing_company,
        "missing_title": missing_title,
    }


# ── HTML render ───────────────────────────────────────────────────────────────

_TIER_COLOR = {"Hot": "#9b2226", "Warm": "#b45309", "Cold": "#6b7280"}
_TIER_BG = {"Hot": "#fff1f2", "Warm": "#fffbeb", "Cold": "#f9fafb"}


def _score_bar(score: int) -> str:
    color = "#9b2226" if score >= 65 else "#b45309" if score >= 35 else "#6b7280"
    return (
        f'<div style="display:flex;align-items:center;gap:8px">'
        f'<div style="background:#e5e7eb;border-radius:4px;height:6px;width:70px">'
        f'<div style="background:{color};height:6px;border-radius:4px;width:{score}%"></div>'
        f'</div>'
        f'<span style="font-family:\'JetBrains Mono\',monospace;font-size:12px;'
        f'color:{color};font-weight:600">{score}</span>'
        f'</div>'
    )


def _tier_badge(tier: str) -> str:
    color = _TIER_COLOR[tier]
    bg = _TIER_BG[tier]
    return (
        f'<span style="background:{bg};color:{color};border:1px solid {color}33;'
        f'border-radius:4px;padding:2px 8px;font-size:11px;font-weight:600">{tier}</span>'
    )


def _days_cell(days: int | None) -> str:
    if days is None:
        return '<span style="color:#9b2226">Never</span>'
    if days == 0:
        return '<span style="color:#2d6a4f">Today</span>'
    if days <= 3:
        return f'<span style="color:#b45309">{days}d ago</span>'
    return f'<span style="color:#9b2226">{days}d ago</span>'


def _missing_flag(label: str) -> str:
    return (
        f'<span style="background:#fef9c3;color:#92400e;border-radius:3px;'
        f'padding:1px 5px;font-size:10px">{label}</span>'
    )


def render_html(report: dict, generated_at: str, all_sources: bool) -> str:
    scored = report["scored"]
    tc = report["tier_counts"]
    scope_note = "All sources" if all_sources else "Inbound sources only"

    rows_html = ""
    for rank, r in enumerate(scored, 1):
        bd = r["breakdown"]
        tip = (
            f"DM:{bd['decision_maker']} + Revenue:{bd['revenue']} + "
            f"Funding:{bd['funding']} + Spend:{bd['spend_capacity']}"
        )
        missing_flags = ""
        if r["missing"]["jobtitle"]:
            missing_flags += _missing_flag("no title") + " "
        if r["missing"]["company_data"]:
            missing_flags += _missing_flag("no company data") + " "
        elif r["missing"]["revenue"]:
            missing_flags += _missing_flag("no revenue") + " "

        # Funding display: show stage if known, amount otherwise
        fund_display = r["funding_fmt"]
        if r["funding_stage"] and r["funding_fmt"] != "—":
            fund_display = f'{r["funding_fmt"]} ({r["funding_stage"]})'
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
          <td style="padding:10px 14px">{_tier_badge(r['tier'])}</td>
          <td style="padding:10px 14px" title="{tip}">{_score_bar(r['score'])}</td>
          <td style="padding:10px 14px">
            <div style="font-size:12px;font-weight:500">{jobtitle}</div>
            <div style="font-size:11px;color:#6b7280">{r['dm_tier']}</div>
            {missing_flags}
          </td>
          <td style="padding:10px 14px;font-size:12px">
            <div>{r['revenue_fmt']}{' <span style="background:#dbeafe;color:#1e40af;border-radius:3px;padding:1px 4px;font-size:10px">web</span>' if r['web_enriched'] else ""}</div>
            <div style="color:#6b7280;font-size:11px">{f"{r['employees']:,} employees" if r['employees'] else "—"}</div>
          </td>
          <td style="padding:10px 14px;font-size:12px;color:#374151">{fund_display_esc}</td>
          <td style="padding:10px 14px;font-size:12px;color:#374151">{r['stage_name']}</td>
          <td style="padding:10px 14px">{_days_cell(r['days_since'])}</td>
        </tr>"""

    empty = (
        "" if scored
        else '<tr><td colspan="9" style="padding:24px;text-align:center;color:#6b7280">No inbound leads found.</td></tr>'
    )

    data_quality_note = ""
    if report["missing_company"] or report["missing_title"]:
        notes = []
        if report["missing_company"]:
            notes.append(f"{report['missing_company']} lead(s) have no associated company (scored 0 on revenue/funding/spend)")
        if report["missing_title"]:
            notes.append(f"{report['missing_title']} lead(s) have no job title (scored 0 on decision maker)")
        data_quality_note = f"""
      <div style="background:#fffbeb;border:1px solid #fde68a;border-radius:8px;padding:12px 16px;margin-bottom:20px;font-size:12px;color:#78350f">
        <strong>Data gaps affecting scores:</strong> {' | '.join(notes)}.
        Enrich via Clay or HubSpot Breeze to improve accuracy.
      </div>"""

    outbound_note = ""
    if report["excluded_outbound"] and not all_sources:
        outbound_note = (
            f'<div style="font-size:12px;color:#6b7280;margin-bottom:16px">'
            f'{report["excluded_outbound"]} outbound-sourced lead(s) excluded '
            f'(run with --all-sources or use /outbound-lead-scoring for those).</div>'
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Inbound Lead Scoring — Leadle</title>
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
  <h1>Inbound Lead Scoring</h1>
  <div class="meta">Leadle RevOps &bull; {scope_note} &bull; ICP-fit score (0–100) &bull; Generated {generated_at}</div>

  <div class="stat-row">
    <div class="stat">
      <div class="stat-n">{report['total']}</div>
      <div class="stat-l">Inbound Leads</div>
    </div>
    <div class="stat">
      <div class="stat-n" style="color:var(--red)">{tc.get('Hot', 0)}</div>
      <div class="stat-l">Hot (≥65)</div>
    </div>
    <div class="stat">
      <div class="stat-n" style="color:var(--amber)">{tc.get('Warm', 0)}</div>
      <div class="stat-l">Warm (35–64)</div>
    </div>
    <div class="stat">
      <div class="stat-n" style="color:var(--muted)">{tc.get('Cold', 0)}</div>
      <div class="stat-l">Cold (&lt;35)</div>
    </div>
  </div>

  {data_quality_note}
  {outbound_note}

  <div class="card">
    <div class="card-title">Leads ranked by ICP-fit score — hover score bar for dimension breakdown</div>
    <table>
      <thead>
        <tr>
          <th>#</th>
          <th>Lead / Company</th>
          <th>Tier</th>
          <th>Score</th>
          <th>Title / DM Fit</th>
          <th>Revenue / Size</th>
          <th>Funding</th>
          <th>Stage</th>
          <th>Last Activity</th>
        </tr>
      </thead>
      <tbody>{rows_html}{empty}</tbody>
    </table>
  </div>

  <div style="font-size:11px;color:var(--muted);margin-top:8px">
    Score = Decision Maker fit (40) + Revenue ≥$2M (25) + Funding ≥$2M (20) + Spend capacity $10K/Q (15).
    All weights in config/inbound_scoring.yaml. Hover score bar for dimension breakdown.
    Company data from HubSpot annualrevenue / total_money_raised — enrichment via Clay improves coverage.
  </div>
</div>
</body>
</html>"""


# ── CLI ───────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    from dotenv import load_dotenv
    load_dotenv()

    parser = argparse.ArgumentParser(prog="analytics.inbound_lead_scoring")
    parser.add_argument("--all-sources", action="store_true",
                        help="Score all leads regardless of source")
    parser.add_argument("--no-enrich", action="store_true",
                        help="Skip web enrichment step entirely")
    parser.add_argument("--dump-needs-enrichment", metavar="FILE",
                        help="Write companies lacking revenue/funding to JSON file and exit")
    parser.add_argument("--enrich-from", metavar="FILE",
                        help="Read pre-computed enrichment JSON and apply before scoring")
    parser.add_argument("--out", help="Output HTML path")
    args = parser.parse_args(argv)

    token = os.environ.get("HUBSPOT_PRIVATE_TOKEN")
    if not token:
        print("ERROR: HUBSPOT_PRIVATE_TOKEN not set", file=sys.stderr)
        return 1

    pipeline_cfg = _load_pipeline_cfg()
    scoring_cfg = _load_scoring_cfg()
    stage_ids = _active_stage_ids(pipeline_cfg)
    stage_map = _stage_map(pipeline_cfg)
    inbound_set = set(scoring_cfg["inbound_sources"])

    print("Fetching active leads...", file=sys.stderr)
    raw = fetch_active_leads(token, stage_ids)
    print(f"  {len(raw)} leads fetched", file=sys.stderr)

    print("Resolving associations (contacts + companies)...", file=sys.stderr)
    contacts, companies = enrich_leads(token, raw)
    print(f"  {len(contacts)} contacts, {len(companies)} companies resolved", file=sys.stderr)

    if args.dump_needs_enrichment:
        needs = _companies_needing_enrichment(raw, companies, inbound_set, args.all_sources)
        Path(args.dump_needs_enrichment).write_text(json.dumps(needs, indent=2), encoding="utf-8")
        print(f"  {len(needs)} companies need enrichment → {args.dump_needs_enrichment}", file=sys.stderr)
        return 0

    if args.enrich_from and not args.no_enrich:
        enrichment_data = json.loads(Path(args.enrich_from).read_text(encoding="utf-8"))
        companies = apply_enrichment(raw, companies, enrichment_data)
        n_enriched = sum(1 for c in companies.values() if c.get("web_enriched"))
        print(f"  Applied enrichment: {n_enriched} companies updated", file=sys.stderr)

    report = compute_scores(raw, contacts, companies, scoring_cfg, stage_map, args.all_sources)

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    html = render_html(report, generated_at, args.all_sources)

    out_path = args.out
    if not out_path:
        slug = date.today().isoformat()
        reports_dir = Path(__file__).parent.parent / "reports"
        reports_dir.mkdir(exist_ok=True)
        out_path = str(reports_dir / f"inbound-lead-scoring-{slug}.html")

    Path(out_path).write_text(html, encoding="utf-8")
    print(f"Report written to {out_path}", file=sys.stderr)

    scored = report["scored"]
    tc = report["tier_counts"]
    print(f"\nInbound Lead Scoring — ICP Fit ({date.today()})")
    print(f"  Scored: {report['total']}  Hot: {tc.get('Hot',0)}  Warm: {tc.get('Warm',0)}  Cold: {tc.get('Cold',0)}")
    if report["excluded_outbound"] and not args.all_sources:
        print(f"  {report['excluded_outbound']} outbound leads excluded (--all-sources to include)")
    if report["missing_company"]:
        print(f"  ⚠  {report['missing_company']} leads with no company data (scored 0 on 3 dimensions)")
    if report["missing_title"]:
        print(f"  ⚠  {report['missing_title']} leads with no job title (scored 0 on DM fit)")
    if scored:
        top = scored[0]
        bd = top["breakdown"]
        print(f"  Top: {top['lead_name']} — {top['company']} | score={top['score']} ({top['tier']})")
        print(f"       DM:{bd['decision_maker']}  Rev:{bd['revenue']}  Fund:{bd['funding']}  Spend:{bd['spend_capacity']}")
        print(f"       Title: {top['jobtitle']} | Revenue: {top['revenue_fmt']} | Funding: {top['funding_fmt']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
