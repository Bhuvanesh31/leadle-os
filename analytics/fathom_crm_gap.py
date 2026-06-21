"""Fathom → CRM gap finder — process #18.

Finds Fathom meetings that have no matching HubSpot contact or deal.
These are discovery/proposal calls that happened but were never logged in the CRM —
a signal that a deal may have been dropped or never created.

Meeting filter (from config/dashboard_rules.yaml → fathom_filter):
  - Title contains "discovery meeting" or "proposal discussion" (case-insensitive)
  - OR: Impromptu Google Meet / Zoom meetings where ALL attendees are in the
        internal allowlist (sai@leadle.in, revops@leadle.in)

Internal attendees (from leadle_internal_names) are excluded from matching.
Only external attendees (non-@leadle.in) are checked against HubSpot.

Match strategy (email_domain_first):
  1. Exact email match → any HubSpot contact with that email
  2. Domain match     → any HubSpot company whose domain matches the email domain
  For each matched contact/company, check for an active lead or open deal.

Gap states:
  no_contact          — no HubSpot contact matches the attendee email or domain
  contact_no_lead     — contact exists but no active lead
  contact_no_deal     — contact exists, lead converted, but no deal in active pipeline

Required env:
  FATHOM_API_KEY          Fathom REST API key
  HUBSPOT_PRIVATE_TOKEN   HubSpot private app token

Outputs:
  --json FILE   machine-readable report
  --out  FILE   HTML report

Usage:
    python -m analytics.fathom_crm_gap
    python -m analytics.fathom_crm_gap --period last-month
    python -m analytics.fathom_crm_gap --start 2026-05-01
    python -m analytics.fathom_crm_gap --json /tmp/fathom_gap.json
"""
from __future__ import annotations

import argparse
import html as _html
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import yaml

from analytics._periods import add_period_args, resolve_args, resolve_period

_RULES_CFG = Path(__file__).parent.parent / "config" / "dashboard_rules.yaml"
_REPORTS_DIR = Path(__file__).parent.parent / "reports"
_DEFAULT_PERIOD = "month"

_FATHOM_BASE = "https://api.fathom.ai/external/v1"
_HS_SEARCH = "https://api.hubapi.com/crm/v3/objects"


# ── config ────────────────────────────────────────────────────────────────────

def _load_rules() -> dict:
    with open(_RULES_CFG) as f:
        return yaml.safe_load(f)


# ── Fathom fetch ──────────────────────────────────────────────────────────────

def _fetch_fathom_meetings(api_key: str, start: date, end: date) -> dict:
    """Return {available, meetings: [...]} or {available: False, reason: ...}."""
    if not api_key:
        return {"available": False, "reason": "FATHOM_API_KEY not set"}

    headers = {"X-Api-Key": api_key}
    meetings: list[dict] = []
    cursor = None

    start_iso = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc).isoformat()
    end_iso = datetime.combine(end, datetime.max.time(), tzinfo=timezone.utc).isoformat()

    try:
        while True:
            params: dict = {
                "created_after": start_iso,
                "created_before": end_iso,
                "limit": 100,
            }
            if cursor:
                params["cursor"] = cursor

            r = httpx.get(f"{_FATHOM_BASE}/meetings", headers=headers,
                          params=params, timeout=30)
            r.raise_for_status()
            data = r.json()
            meetings.extend(data.get("items", data.get("meetings", [])))
            cursor = (data.get("pagination") or {}).get("next_cursor")
            if not cursor:
                break

        return {"available": True, "meetings": meetings}
    except httpx.HTTPStatusError as e:
        return {"available": False, "reason": f"Fathom HTTP {e.response.status_code}: {e.response.text[:120]}"}
    except httpx.HTTPError as e:
        return {"available": False, "reason": f"Fathom REST error: {type(e).__name__}: {e}"}


# ── meeting filter ────────────────────────────────────────────────────────────

def _should_include(meeting: dict, rules: dict) -> bool:
    """Return True if this meeting should be checked for CRM gaps."""
    f = rules.get("fathom_filter", {})
    title = (meeting.get("title") or "").lower()

    # Named meeting types we care about
    for substr in f.get("include_title_substrings", []):
        if substr.lower() in title:
            return True

    # Impromptu meetings — only if attendees are all on allowlist
    pattern = f.get("impromptu_title_pattern", "")
    if pattern and re.search(pattern, meeting.get("title") or "", re.IGNORECASE):
        allowlist = {e.lower() for e in f.get("impromptu_attendee_allowlist", [])}
        # Fathom API returns calendar_invitees; fall back to attendees for compat
        invitees = meeting.get("calendar_invitees") or meeting.get("attendees") or []
        attendees = {(a.get("email") or "").lower() for a in invitees}
        if attendees and attendees.issubset(allowlist):
            return True

    return False


def _external_attendees(meeting: dict, rules: dict) -> list[str]:
    """Return list of external attendee emails (non-Leadle).

    Fathom marks each invitee with is_external; fall back to domain check.
    """
    result = []
    invitees = meeting.get("calendar_invitees") or meeting.get("attendees") or []
    for a in invitees:
        email = (a.get("email") or "").lower().strip()
        if not email:
            continue
        # Use Fathom's own is_external flag when present
        if "is_external" in a:
            if a["is_external"]:
                result.append(email)
        else:
            if not email.endswith("@leadle.in"):
                result.append(email)
    return result


# ── HubSpot matching ──────────────────────────────────────────────────────────

def _hs_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _find_contact_by_email(token: str, email: str) -> dict | None:
    r = httpx.post(f"{_HS_SEARCH}/contacts/search",
        headers=_hs_headers(token),
        json={
            "filterGroups": [{"filters": [
                {"propertyName": "email", "operator": "EQ", "value": email},
            ]}],
            "properties": ["email", "firstname", "lastname", "company",
                           "lifecyclestage", "hs_object_id"],
            "limit": 1,
        }, timeout=15)
    results = r.json().get("results", [])
    return results[0] if results else None


def _find_company_by_domain(token: str, domain: str) -> dict | None:
    r = httpx.post(f"{_HS_SEARCH}/companies/search",
        headers=_hs_headers(token),
        json={
            "filterGroups": [{"filters": [
                {"propertyName": "domain", "operator": "EQ", "value": domain},
            ]}],
            "properties": ["name", "domain", "hs_object_id"],
            "limit": 1,
        }, timeout=15)
    results = r.json().get("results", [])
    return results[0] if results else None


def _contact_has_active_lead(token: str, contact_id: str) -> bool:
    """Check if this contact is associated with an active (non-terminal) lead."""
    r = httpx.get(
        f"https://api.hubapi.com/crm/v3/objects/contacts/{contact_id}/associations/leads",
        headers=_hs_headers(token), timeout=15,
    )
    assoc = r.json().get("results", [])
    if not assoc:
        return False
    lead_ids = [a["id"] for a in assoc[:5]]
    # Check each lead's stage
    for lid in lead_ids:
        r2 = httpx.get(f"https://api.hubapi.com/crm/v3/objects/leads/{lid}",
            headers=_hs_headers(token),
            params={"properties": "hs_pipeline_stage"},
            timeout=15)
        stage = (r2.json().get("properties") or {}).get("hs_pipeline_stage") or ""
        terminal = {"qualified-stage-id", "unqualified-stage-id"}
        if stage and stage not in terminal:
            return True
    return False


def _company_has_active_deal(token: str, company_id: str) -> bool:
    """Check if this company has an open deal in the sales pipeline."""
    r = httpx.get(
        f"https://api.hubapi.com/crm/v3/objects/companies/{company_id}/associations/deals",
        headers=_hs_headers(token), timeout=15,
    )
    assoc = r.json().get("results", [])
    if not assoc:
        return False
    deal_ids = [a["id"] for a in assoc[:5]]
    terminal = {"3022478048", "3022478049"}  # Won, Lost
    for did in deal_ids:
        r2 = httpx.get(f"https://api.hubapi.com/crm/v3/objects/deals/{did}",
            headers=_hs_headers(token),
            params={"properties": "dealstage,pipeline"},
            timeout=15)
        p = r2.json().get("properties") or {}
        if p.get("pipeline") == "1906293444" and p.get("dealstage") not in terminal:
            return True
    return False


def _classify_gap(token: str, email: str) -> tuple[str, str, str]:
    """Return (gap_state, contact_name, company_name)."""
    domain = email.split("@")[-1] if "@" in email else ""

    # 1. Exact email match
    contact = _find_contact_by_email(token, email)
    if contact:
        p = contact.get("properties") or {}
        cname = f"{p.get('firstname','') or ''} {p.get('lastname','') or ''}".strip() or email
        company = p.get("company") or domain
        # Check for active lead via contact
        if _contact_has_active_lead(token, contact["id"]):
            return "has_active_lead", cname, company
        return "contact_no_lead", cname, company

    # 2. Domain match via company
    if domain:
        company_rec = _find_company_by_domain(token, domain)
        if company_rec:
            p = company_rec.get("properties") or {}
            cname = p.get("name") or domain
            if _company_has_active_deal(token, company_rec["id"]):
                return "has_active_deal", email, cname
            return "contact_no_deal", email, cname

    return "no_contact", email, domain or email


# ── build report ──────────────────────────────────────────────────────────────

def build_report(fathom_result: dict, hs_token: str, rules: dict,
                 window_start: date, window_end: date, window_label: str) -> dict:
    meetings = fathom_result.get("meetings", [])

    # Filter meetings to relevant types
    relevant = [m for m in meetings if _should_include(m, rules)]

    gaps = []
    covered = []

    for m in relevant:
        ext = _external_attendees(m, rules)
        if not ext:
            continue

        email = ext[0]  # primary external attendee
        gap_state, contact_name, company_name = _classify_gap(hs_token, email)

        title = m.get("title") or m.get("meeting_title") or "(no title)"
        scheduled = m.get("scheduled_start_time") or m.get("created_at") or ""
        scheduled_date = scheduled[:10] if scheduled else None

        row = {
            "meeting_id": m.get("id"),
            "title": title,
            "scheduled_date": scheduled_date,
            "contact_email": email,
            "contact_name": contact_name,
            "company": company_name,
            "gap_state": gap_state,
            "all_external": ext,
        }

        if gap_state in ("no_contact", "contact_no_lead", "contact_no_deal"):
            gaps.append(row)
        else:
            covered.append(row)

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "window": {"start": window_start.isoformat(), "end": window_end.isoformat(), "label": window_label},
        "fathom_available": fathom_result.get("available", False),
        "fathom_reason": fathom_result.get("reason"),
        "summary": {
            "meetings_fetched": len(meetings),
            "meetings_relevant": len(relevant),
            "gaps": len(gaps),
            "covered": len(covered),
        },
        "gaps": sorted(gaps, key=lambda r: r["scheduled_date"] or "", reverse=True),
        "covered": covered,
    }


# ── HTML render ───────────────────────────────────────────────────────────────

_GAP_STATE_LABELS = {
    "no_contact":     ("No CRM record", "#9b2226"),
    "contact_no_lead": ("Contact, no lead", "#b45309"),
    "contact_no_deal": ("Company, no deal", "#1e40af"),
}


def _gap_badge(state: str) -> str:
    label, color = _GAP_STATE_LABELS.get(state, (state, "#6b7280"))
    return f'<span style="background:{color}1a;color:{color};border-radius:4px;padding:2px 7px;font-size:11px;font-weight:600">{label}</span>'


def render_html(report: dict) -> str:
    s = report["summary"]
    window = report["window"]

    status_block = ""
    if not report["fathom_available"]:
        reason = _html.escape(report.get("fathom_reason") or "unavailable")
        status_block = f'<div style="background:#fef2f2;border:1px solid #fecaca;border-radius:8px;padding:12px 16px;font-size:12px;color:#9b2226;margin-bottom:20px">Fathom unavailable: {reason}</div>'

    gap_rows = ""
    for r in report["gaps"]:
        title = _html.escape(r["title"])
        email = _html.escape(r["contact_email"])
        company = _html.escape(r["company"])
        gap_rows += f"""<tr>
          <td style="padding:9px 14px;font-size:13px;font-weight:500">{title}</td>
          <td style="padding:9px 14px;font-family:'JetBrains Mono',monospace;font-size:12px">{r['scheduled_date'] or '—'}</td>
          <td style="padding:9px 14px;font-size:12px">{email}</td>
          <td style="padding:9px 14px;font-size:12px;color:#6b7280">{company}</td>
          <td style="padding:9px 14px">{_gap_badge(r['gap_state'])}</td>
        </tr>"""
    if not gap_rows:
        msg = "No gaps found — all relevant Fathom meetings have a matching CRM record." if report["fathom_available"] else "Fathom data unavailable."
        gap_rows = f'<tr><td colspan="5" style="padding:20px;text-align:center;color:#9ca3af;font-size:12px">{msg}</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Fathom → CRM Gap — Leadle</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Fraunces:ital,wght@0,400;0,600;1,400&family=Inter+Tight:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');
  :root{{--bg:#fafaf7;--surface:#fff;--ink:#15171a;--red:#9b2226;--amber:#b45309;--blue:#1e40af;--muted:#6b7280;--border:#e5e7eb}}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:var(--bg);color:var(--ink);font-family:'Inter Tight',sans-serif;font-size:14px;line-height:1.5;padding:32px 24px}}
  .wrap{{max-width:1100px;margin:0 auto}}
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
  <h1>Fathom → CRM Gap</h1>
  <div class="meta">Leadle RevOps &bull; {_html.escape(window['label'])} &bull; Generated {report['generated_at']}</div>
  {status_block}

  <div class="stat-row">
    <div class="stat">
      <div class="stat-n">{s['meetings_fetched']}</div>
      <div class="stat-l">Fathom Meetings</div>
    </div>
    <div class="stat">
      <div class="stat-n">{s['meetings_relevant']}</div>
      <div class="stat-l">Relevant (filtered)</div>
    </div>
    <div class="stat">
      <div class="stat-n" style="color:var(--red)">{s['gaps']}</div>
      <div class="stat-l">CRM Gaps</div>
    </div>
    <div class="stat">
      <div class="stat-n" style="color:#2d6a4f">{s['covered']}</div>
      <div class="stat-l">Matched to CRM</div>
    </div>
  </div>

  <div class="card">
    <div class="card-title">Meetings with No CRM Record — action required</div>
    <table>
      <thead>
        <tr>
          <th>Meeting Title</th><th>Date</th><th>Attendee Email</th>
          <th>Company (guessed)</th><th>Gap State</th>
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
    parser = argparse.ArgumentParser(prog="analytics.fathom_crm_gap")
    add_period_args(parser)
    parser.add_argument("--json", metavar="FILE", help="Dump report JSON to this path")
    parser.add_argument("--out", metavar="FILE", help="Output HTML path")
    args = parser.parse_args(argv)

    start, end, label = resolve_args(args)
    if start is None:
        start, end, label = resolve_period(_DEFAULT_PERIOD)

    fathom_key = os.environ.get("FATHOM_API_KEY", "")
    hs_token = os.environ.get("HUBSPOT_PRIVATE_TOKEN", "")

    if not hs_token:
        print("ERROR: HUBSPOT_PRIVATE_TOKEN not set", file=sys.stderr)
        return 1

    rules = _load_rules()
    print(f"Window: {label}", file=sys.stderr)

    print("Fetching Fathom meetings...", file=sys.stderr)
    fathom_result = _fetch_fathom_meetings(fathom_key, start, end)
    if fathom_result["available"]:
        print(f"  {len(fathom_result['meetings'])} meetings fetched", file=sys.stderr)
    else:
        print(f"  UNAVAILABLE: {fathom_result['reason']}", file=sys.stderr)

    print("Matching against HubSpot...", file=sys.stderr)
    report = build_report(fathom_result, hs_token, rules, start, end, label)
    s = report["summary"]

    print(f"\nFathom → CRM Gap — {label}")
    print(f"  Fathom available:  {report['fathom_available']}")
    print(f"  Meetings fetched:  {s['meetings_fetched']}")
    print(f"  Relevant meetings: {s['meetings_relevant']}")
    print(f"  Gaps found:        {s['gaps']}")
    print(f"  CRM covered:       {s['covered']}")

    if report["gaps"]:
        print("\n  Gaps:")
        for g in report["gaps"]:
            print(f"    [{g['gap_state']:20}] {g['title'][:40]:40} | {g['contact_email']} | {g['scheduled_date']}")

    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Report JSON → {args.json}", file=sys.stderr)

    html = render_html(report)
    out_path = args.out
    if not out_path:
        slug = date.today().isoformat()
        _REPORTS_DIR.mkdir(exist_ok=True)
        out_path = str(_REPORTS_DIR / f"fathom-crm-gap-{slug}.html")
    Path(out_path).write_text(html, encoding="utf-8")
    print(f"Report → {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
