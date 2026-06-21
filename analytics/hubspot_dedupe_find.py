"""HubSpot duplicate finder — contacts + companies. Process #14.

Scans all HubSpot contacts and companies for duplicate records.
Read-only: finds and reports only, never merges. Merge is process #15.

Duplicate signals (deterministic — no fuzzy matching):
  contacts:
    email_exact     — two or more contacts share the same email address (lowercased)
    name_exact      — same (firstname, lastname) pair with different emails / IDs
  companies:
    domain_exact    — two or more companies share the same website domain (lowercased)
    name_exact      — two or more companies share the identical name (lowercased)

Output columns per duplicate group:
  email/domain/name, count of records, record IDs, sample names/emails

Outputs:
  --json FILE   machine-readable report
  --out  FILE   HTML report

Usage:
    python -m analytics.hubspot_dedupe_find
    python -m analytics.hubspot_dedupe_find --json /tmp/dedupe.json
"""
from __future__ import annotations

import argparse
import html as _html
import json
import os
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import httpx

_REPORTS_DIR = Path(__file__).parent.parent / "reports"


def _paginate_search(token: str, object_type: str, properties: list[str],
                     filters: list[dict] | None = None) -> list[dict]:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    results = []
    after = None
    while True:
        body: dict = {
            "filterGroups": [{"filters": filters}] if filters else [],
            "properties": properties,
            "limit": 100,
        }
        if after:
            body["after"] = after
        r = httpx.post(
            f"https://api.hubapi.com/crm/v3/objects/{object_type}/search",
            headers=headers, json=body, timeout=30,
        )
        data = r.json()
        results.extend(data.get("results", []))
        after = (data.get("paging") or {}).get("next", {}).get("after")
        if not after:
            break
    return results


def _find_contact_dupes(contacts: list[dict]) -> tuple[list[dict], list[dict]]:
    """Return (email_dupes, name_dupes) as sorted lists of dup groups."""
    by_email: dict[str, list[dict]] = defaultdict(list)
    by_name: dict[str, list[dict]] = defaultdict(list)

    for c in contacts:
        p = c.get("properties") or {}
        cid = c["id"]
        email = (p.get("email") or "").lower().strip()
        firstname = (p.get("firstname") or "").strip()
        lastname = (p.get("lastname") or "").strip()
        company = (p.get("company") or "").strip()
        created = (p.get("createdate") or "")[:10]
        lifecycle = p.get("lifecyclestage") or ""

        row = {
            "id": cid,
            "email": p.get("email") or "",
            "name": f"{firstname} {lastname}".strip() or "(no name)",
            "company": company,
            "created": created,
            "lifecycle": lifecycle,
        }

        if email:
            by_email[email].append(row)

        if firstname and lastname:
            name_key = f"{firstname.lower()}|{lastname.lower()}"
            by_name[name_key].append(row)

    email_dupes = [
        {
            "key": email,
            "type": "email_exact",
            "count": len(rows),
            "records": rows,
        }
        for email, rows in by_email.items()
        if len(rows) > 1
    ]
    # Name dupes: only flag where records have DIFFERENT emails (otherwise email_dupes covers it)
    name_dupes = [
        {
            "key": name_key.replace("|", " "),
            "type": "name_exact",
            "count": len(rows),
            "records": rows,
        }
        for name_key, rows in by_name.items()
        if len(rows) > 1 and len({r["email"].lower() for r in rows}) > 1
    ]

    email_dupes.sort(key=lambda g: -g["count"])
    name_dupes.sort(key=lambda g: -g["count"])
    return email_dupes, name_dupes


def _find_company_dupes(companies: list[dict]) -> tuple[list[dict], list[dict]]:
    """Return (domain_dupes, name_dupes) as sorted lists of dup groups."""
    by_domain: dict[str, list[dict]] = defaultdict(list)
    by_name: dict[str, list[dict]] = defaultdict(list)

    for c in companies:
        p = c.get("properties") or {}
        cid = c["id"]
        name = (p.get("name") or "").strip()
        domain = (p.get("domain") or "").lower().strip()
        created = (p.get("createdate") or "")[:10]

        row = {
            "id": cid,
            "name": name or "(no name)",
            "domain": domain,
            "created": created,
        }

        if domain:
            by_domain[domain].append(row)
        if name:
            by_name[name.lower()].append(row)

    domain_dupes = [
        {
            "key": domain,
            "type": "domain_exact",
            "count": len(rows),
            "records": rows,
        }
        for domain, rows in by_domain.items()
        if len(rows) > 1
    ]
    name_dupes = [
        {
            "key": name_key,
            "type": "name_exact",
            "count": len(rows),
            "records": rows,
        }
        for name_key, rows in by_name.items()
        if len(rows) > 1
    ]

    domain_dupes.sort(key=lambda g: -g["count"])
    name_dupes.sort(key=lambda g: -g["count"])
    return domain_dupes, name_dupes


def build_report(contacts: list[dict], companies: list[dict]) -> dict:
    contact_email_dupes, contact_name_dupes = _find_contact_dupes(contacts)
    company_domain_dupes, company_name_dupes = _find_company_dupes(companies)

    contact_records_affected = sum(g["count"] for g in contact_email_dupes)
    company_records_affected_domain = sum(g["count"] for g in company_domain_dupes)

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "scanned": {
            "contacts": len(contacts),
            "companies": len(companies),
        },
        "summary": {
            "contact_email_dup_groups": len(contact_email_dupes),
            "contact_email_records_affected": contact_records_affected,
            "contact_name_dup_groups": len(contact_name_dupes),
            "company_domain_dup_groups": len(company_domain_dupes),
            "company_domain_records_affected": company_records_affected_domain,
            "company_name_dup_groups": len(company_name_dupes),
        },
        "contact_email_dupes": contact_email_dupes[:50],
        "contact_name_dupes": contact_name_dupes[:50],
        "company_domain_dupes": company_domain_dupes[:50],
        "company_name_dupes": company_name_dupes[:30],
    }


# ── HTML render ───────────────────────────────────────────────────────────────

def _stat(n: int, label: str, color: str = "") -> str:
    style = f"color:{color}" if color else ""
    return f"""<div class="stat">
      <div class="stat-n" style="{style}">{n:,}</div>
      <div class="stat-l">{label}</div>
    </div>"""


def _dup_table(groups: list[dict], key_label: str, show_email: bool = False,
               max_groups: int = 20) -> str:
    if not groups:
        return '<tr><td colspan="4" style="padding:16px;text-align:center;color:#9ca3af;font-size:12px">No duplicates found.</td></tr>'

    rows = ""
    for g in groups[:max_groups]:
        key = _html.escape(g["key"])
        count = g["count"]
        ids = ", ".join(r["id"] for r in g["records"][:5])
        if show_email:
            sample = " &bull; ".join(
                _html.escape(f"{r['name']} ({r['company'][:20] if r['company'] else '—'})")
                for r in g["records"][:3]
            )
        else:
            sample = " &bull; ".join(
                _html.escape(f"{r['name']} [{r['domain'] or '—'}]")
                for r in g["records"][:3]
            )
        badge = f'<span style="background:#fef2f2;color:#9b2226;border-radius:4px;padding:2px 8px;font-size:11px;font-weight:600">{count}</span>'
        rows += f"""<tr>
          <td style="padding:9px 14px;font-family:'JetBrains Mono',monospace;font-size:12px">{key}</td>
          <td style="padding:9px 14px">{badge}</td>
          <td style="padding:9px 14px;font-size:11px;color:#6b7280">{ids}</td>
          <td style="padding:9px 14px;font-size:12px">{sample}</td>
        </tr>"""
    if len(groups) > max_groups:
        remaining = len(groups) - max_groups
        rows += f'<tr><td colspan="4" style="padding:10px 14px;font-size:12px;color:#6b7280;background:#f9fafb">... and {remaining:,} more groups (see JSON for full list)</td></tr>'
    return rows


def render_html(report: dict) -> str:
    s = report["summary"]
    sc = report["scanned"]

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>HubSpot Dedupe — Leadle</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Fraunces:ital,wght@0,400;0,600;1,400&family=Inter+Tight:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');
  :root{{--bg:#fafaf7;--surface:#fff;--ink:#15171a;--red:#9b2226;--amber:#b45309;--green:#2d6a4f;--muted:#6b7280;--border:#e5e7eb}}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:var(--bg);color:var(--ink);font-family:'Inter Tight',sans-serif;font-size:14px;line-height:1.5;padding:32px 24px}}
  .wrap{{max-width:1200px;margin:0 auto}}
  h1{{font-family:'Fraunces',serif;font-size:26px;font-weight:600;margin-bottom:4px}}
  .meta{{color:var(--muted);font-size:12px;margin-bottom:28px}}
  .stat-row{{display:flex;gap:16px;margin-bottom:20px;flex-wrap:wrap}}
  .stat{{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:14px 18px;min-width:150px}}
  .stat-n{{font-family:'JetBrains Mono',monospace;font-size:22px;font-weight:500}}
  .stat-l{{font-size:11px;color:var(--muted);margin-top:2px;text-transform:uppercase;letter-spacing:.04em}}
  .card{{background:var(--surface);border-radius:10px;border:1px solid var(--border);overflow:hidden;margin-bottom:24px}}
  .card-title{{padding:12px 16px;font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.05em;border-bottom:1px solid var(--border);background:#f9fafb;color:var(--muted)}}
  table{{width:100%;border-collapse:collapse}}
  thead th{{background:#f3f4f6;padding:9px 14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);font-weight:600}}
  tbody tr:not(:last-child){{border-bottom:1px solid var(--border)}}
  tbody tr:hover{{background:#f9fafb}}
  .note{{background:#fffbeb;border:1px solid #fde68a;border-radius:8px;padding:12px 16px;font-size:12px;color:#92400e;margin-bottom:20px}}
</style>
</head>
<body>
<div class="wrap">
  <h1>HubSpot Duplicate Finder</h1>
  <div class="meta">Leadle RevOps &bull; {sc['contacts']:,} contacts + {sc['companies']:,} companies scanned &bull; Generated {report['generated_at']}</div>

  <div class="note">Read-only report. Use /hubspot-dedupe-fix (process #15) to merge records after confirming which to keep.</div>

  <h2 style="font-size:13px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin-bottom:12px">Contacts</h2>
  <div class="stat-row">
    {_stat(s['contact_email_dup_groups'], 'Email dup groups', '#9b2226')}
    {_stat(s['contact_email_records_affected'], 'Contact records affected')}
    {_stat(s['contact_name_dup_groups'], 'Same-name dup groups', '#b45309')}
  </div>

  <div class="card">
    <div class="card-title">Duplicate Emails — same email address on multiple contact records</div>
    <table>
      <thead><tr><th>Email</th><th>Records</th><th>HubSpot IDs</th><th>Names / Companies</th></tr></thead>
      <tbody>{_dup_table(report['contact_email_dupes'], 'Email', show_email=True)}</tbody>
    </table>
  </div>

  <div class="card">
    <div class="card-title">Duplicate Names — same first+last, different emails</div>
    <table>
      <thead><tr><th>Name</th><th>Records</th><th>HubSpot IDs</th><th>Emails / Companies</th></tr></thead>
      <tbody>{_dup_table(report['contact_name_dupes'], 'Name', show_email=True)}</tbody>
    </table>
  </div>

  <h2 style="font-size:13px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin:24px 0 12px">Companies</h2>
  <div class="stat-row">
    {_stat(s['company_domain_dup_groups'], 'Domain dup groups', '#9b2226')}
    {_stat(s['company_domain_records_affected'], 'Company records affected')}
    {_stat(s['company_name_dup_groups'], 'Same-name dup groups', '#b45309')}
  </div>

  <div class="card">
    <div class="card-title">Duplicate Domains — same website domain on multiple company records</div>
    <table>
      <thead><tr><th>Domain</th><th>Records</th><th>HubSpot IDs</th><th>Company Names</th></tr></thead>
      <tbody>{_dup_table(report['company_domain_dupes'], 'Domain', show_email=False)}</tbody>
    </table>
  </div>

  <div class="card">
    <div class="card-title">Duplicate Company Names — identical name on multiple records</div>
    <table>
      <thead><tr><th>Name</th><th>Records</th><th>HubSpot IDs</th><th>Domains</th></tr></thead>
      <tbody>{_dup_table(report['company_name_dupes'], 'Name', show_email=False)}</tbody>
    </table>
  </div>
</div>
</body>
</html>"""


# ── main ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="analytics.hubspot_dedupe_find")
    parser.add_argument("--json", metavar="FILE", help="Dump report JSON to this path")
    parser.add_argument("--out", metavar="FILE", help="Output HTML path")
    args = parser.parse_args(argv)

    token = os.environ.get("HUBSPOT_PRIVATE_TOKEN")
    if not token:
        print("ERROR: HUBSPOT_PRIVATE_TOKEN not set", file=sys.stderr)
        return 1

    print("Fetching all contacts...", file=sys.stderr)
    contacts = _paginate_search(
        token, "contacts",
        ["email", "firstname", "lastname", "company", "createdate", "lifecyclestage"],
    )
    print(f"  {len(contacts)} contacts", file=sys.stderr)

    print("Fetching all companies...", file=sys.stderr)
    companies = _paginate_search(
        token, "companies",
        ["name", "domain", "createdate"],
    )
    print(f"  {len(companies)} companies", file=sys.stderr)

    report = build_report(contacts, companies)
    s = report["summary"]

    print(f"\nHubSpot Dedupe Scan — {report['generated_at']}")
    print(f"  Scanned: {report['scanned']['contacts']:,} contacts  {report['scanned']['companies']:,} companies")
    print("\n  Contacts:")
    print(f"    Email duplicates:  {s['contact_email_dup_groups']} groups  ({s['contact_email_records_affected']} records affected)")
    print(f"    Name duplicates:   {s['contact_name_dup_groups']} groups")
    print("\n  Companies:")
    print(f"    Domain duplicates: {s['company_domain_dup_groups']} groups  ({s['company_domain_records_affected']} records affected)")
    print(f"    Name duplicates:   {s['company_name_dup_groups']} groups")

    if report["contact_email_dupes"]:
        print("\n  Top email dup groups:")
        for g in report["contact_email_dupes"][:5]:
            ids = ", ".join(r["id"] for r in g["records"][:3])
            print(f"    {g['key']:45} x{g['count']}  [{ids}]")

    if report["company_domain_dupes"]:
        print("\n  Top domain dup groups:")
        for g in report["company_domain_dupes"][:5]:
            names = " / ".join(r["name"] for r in g["records"][:3])
            print(f"    {g['key']:35} x{g['count']}  [{names}]")

    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nReport JSON → {args.json}", file=sys.stderr)

    html = render_html(report)
    out_path = args.out
    if not out_path:
        slug = date.today().isoformat()
        _REPORTS_DIR.mkdir(exist_ok=True)
        out_path = str(_REPORTS_DIR / f"hubspot-dedupe-{slug}.html")
    Path(out_path).write_text(html, encoding="utf-8")
    print(f"Report → {out_path}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
