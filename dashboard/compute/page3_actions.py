"""Page 3 — Sales Actions. Fathom ↔ HubSpot CRM-hygiene gap detection.

Two distinct gaps surface here:

  Gap A (lead_to_deal): A Fathom call happened with someone who exists in
  HubSpot as a Lead (or Contact) but NOT as a Deal. The proper Leadle flow
  promotes Lead → Deal in Discovery stage once a discovery call is recorded;
  these are the cases that haven't been promoted.

  Gap B (no_crm): A Fathom call happened with someone who has no HubSpot
  record at all — no Lead, no Deal, no Contact. The full CRM entry needs
  to be created.

Matching cascade per Fathom meeting:
  1. Email (highest confidence) — attendee email vs Lead.contact_email and
     Contact.email
  2. Person name — attendee name vs Lead.contact_name + Lead.lead_name
  3. Title-derived entity — parse "X <> Leadle" or "X and Sai Ganesh" patterns,
     match substring against Deal.dealname and Lead.lead_name
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from dashboard.compute.page1_revenue import _parse_iso_date
from dashboard.compute.windows import WindowSpec

# Leadle team names that appear in Fathom attendees — exclude from candidate
# extraction so we don't try to "match Sai against CRM".
_LEADLE_INTERNAL_NAMES = {
    "sai ganesh subramanian",
    "sai ganesh",
    "revops leadle",
    "akil mohan",
    "suraj seetharaman",
    "bhuvaneswari",
}

_LEADLE_DOMAIN = "@leadle.in"

# Title parsing patterns. Order matters — first match wins.
_TITLE_PATTERNS = [
    # "Company <> Leadle | Discovery meeting"
    re.compile(r"^([^|<>]+?)\s*<>\s*Leadle", re.IGNORECASE),
    # "Leadle <> Company | Discovery meeting"
    re.compile(r"Leadle\s*<>\s*([^|<>]+?)(?:\s*\||$)", re.IGNORECASE),
    # "Leadle x Company - subject"
    re.compile(r"Leadle\s*x\s*([^|\-]+?)(?:\s*[\-|]|$)", re.IGNORECASE),
    # "Person and Sai Ganesh | Discovery meeting"
    re.compile(r"^([^|]+?)\s+and\s+Sai(?:\s+Ganesh)?", re.IGNORECASE),
]

# Words common in titles that are NEVER an entity name. Stops "Discovery" or
# "Catchup" from polluting the candidate set.
_TITLE_STOPWORDS = {
    "discovery", "proposal", "catchup", "review", "sync", "weekly",
    "impromptu", "google", "meet", "meeting", "zoom",
}


def compute(raw: dict, rules: dict, window: WindowSpec) -> dict[str, Any]:
    fathom = raw["sources"].get("fathom", {})
    hubspot = raw["sources"].get("hubspot", {})
    if not fathom.get("available") or not hubspot.get("available"):
        return {
            "fathom_gap": [], "fathom_gap_lead_to_deal": [], "fathom_gap_no_crm": [],
            "gap_count": 0, "gap_count_lead_to_deal": 0, "gap_count_no_crm": 0,
            "unavailable": True,
        }

    meetings = fathom["data"].get("meetings", [])
    deals = hubspot["data"].get("deals", [])
    leads = hubspot["data"].get("leads", [])
    # deals_lookup: permissive index of ALL Sales Pipeline deals (regardless of date)
    # — used ONLY for the "is there a deal at all?" hygiene check. Falls back to
    # the in-window deals if a full lookup wasn't fetched.
    deals_lookup = hubspot["data"].get("deals_lookup") or deals

    # Pre-build searchable indices
    deal_index = _build_deal_index(deals_lookup)
    lead_index = _build_lead_index(leads)

    gap_l2d: list[dict] = []
    gap_no_crm: list[dict] = []

    for m in meetings:
        scheduled = _parse_iso_date(m.get("scheduled_at"))
        if not scheduled or not (window.start <= scheduled <= window.end):
            continue
        # Only call types where a CRM record is actually expected
        if m.get("call_type") not in ("discovery", "proposal"):
            continue
        candidates = _extract_candidates(m)
        if not candidates:
            continue  # Truly opaque meeting — nothing to match against

        match_type, matched = _classify(candidates, deal_index, lead_index)

        if match_type == "deal":
            continue  # Has a deal — no gap

        row_base = {
            "candidate": _format_candidate_summary(candidates),
            "last_call_date": scheduled.isoformat(),
            "call_type": m.get("call_type"),
            "meeting_title": m.get("title"),
            "meeting_url": m.get("url"),
        }

        if match_type in ("lead", "contact"):
            gap_l2d.append({
                **row_base,
                "matched_record_type": match_type,
                "matched_record": _summarize_match(match_type, matched),
                "suggested_action": "Promote Lead → Deal (stage: Discovery)",
            })
        else:  # "none"
            gap_no_crm.append({
                **row_base,
                "suggested_action": "Create Lead + Deal in HubSpot",
            })

    # Backward-compat fields for the existing template/agents
    combined = [_to_legacy_row(r) for r in gap_l2d + gap_no_crm]

    return {
        "fathom_gap_lead_to_deal": gap_l2d,
        "fathom_gap_no_crm": gap_no_crm,
        "gap_count_lead_to_deal": len(gap_l2d),
        "gap_count_no_crm": len(gap_no_crm),
        "fathom_gap": combined,
        "gap_count": len(combined),
    }


def _build_deal_index(deals: list[dict]) -> dict:
    """Returns indices for substring/word matching on dealname."""
    return {
        "by_name_lower": [(d.get("dealname", "").strip().lower(), d) for d in deals if d.get("dealname")],
    }


def _build_lead_index(leads: list[dict]) -> dict:
    """Returns indices for email-exact and name-substring matching on leads."""
    return {
        "by_email": {l["contact_email"].lower(): l for l in leads if l.get("contact_email")},
        "by_name_lower": [
            (_lead_search_text(l), l) for l in leads
        ],
    }


def _lead_search_text(lead: dict) -> str:
    """Concatenated lowercased text searchable for a lead."""
    parts = [lead.get("lead_name") or "", lead.get("contact_name") or ""]
    return " ".join(p for p in parts if p).lower().strip()


def _extract_candidates(meeting: dict) -> list[dict]:
    """Yield {kind, value} candidates for a Fathom meeting.

    Sources:
      - attendee.email when not @leadle.in
      - attendee.name when not in the Leadle internal allowlist
      - title-derived entities (company or person from common patterns)
    """
    out: list[dict] = []
    seen_values: set[str] = set()

    for a in meeting.get("attendees", []):
        email = (a.get("email") or "").strip().lower()
        if email and not email.endswith(_LEADLE_DOMAIN) and email not in seen_values:
            out.append({"kind": "email", "value": email})
            seen_values.add(email)
            # Also extract the domain root as a separate candidate. Leadle's
            # deal-naming follows company-name convention (Colab91, Evitar.ai,
            # Getayna) — and the domain root is usually a clean signal of
            # company: madhur@colab91.com → "colab91" → matches Deal "Colab91".
            domain_root = _email_domain_root(email)
            if domain_root and domain_root not in seen_values:
                out.append({"kind": "domain_root", "value": domain_root})
                seen_values.add(domain_root)
        name = (a.get("name") or "").strip().lower()
        if name and name not in _LEADLE_INTERNAL_NAMES and name not in seen_values:
            out.append({"kind": "name", "value": name})
            seen_values.add(name)

    title = (meeting.get("title") or "").strip()
    for pat in _TITLE_PATTERNS:
        m = pat.search(title)
        if not m:
            continue
        entity = m.group(1).strip()
        # Reject if it's clearly internal/leadle, a stopword, or too short
        entity_lower = entity.lower()
        if (entity_lower in _LEADLE_INTERNAL_NAMES
            or entity_lower.startswith("leadle")
            or all(w in _TITLE_STOPWORDS for w in entity_lower.split())
            or len(entity) < 3
            or entity_lower in seen_values):
            continue
        out.append({"kind": "title", "value": entity_lower})
        seen_values.add(entity_lower)
        break  # one title-derived entity is enough

    return out


def _classify(
    candidates: list[dict],
    deal_index: dict,
    lead_index: dict,
) -> tuple[str, dict | None]:
    """Return (match_type, matched_record) where match_type is one of
    'deal' | 'lead' | 'contact' | 'none'.

    Cascade ordered Deal-first because the typical Lead → Deal promotion path
    means a Deal record's existence is the stronger 'no gap' signal — the
    Lead might still exist alongside the Deal but isn't the active sales
    artifact. If we matched Lead first we'd flag Lead→Deal-promoted records
    as Gap A (false positive).
    """

    # Pass 1: Deal direct match via any non-email candidate.
    for c in candidates:
        if c["kind"] == "email":
            continue
        needle = c["value"]
        if len(needle) < 3:
            continue
        for dname, d in deal_index["by_name_lower"]:
            if _matches(needle, dname):
                return ("deal", d)

    # Pass 2: Try to find a Lead. Email-exact first, then name substring.
    found_lead: dict | None = None
    for c in candidates:
        if c["kind"] != "email":
            continue
        l = lead_index["by_email"].get(c["value"])
        if l:
            found_lead = l
            break
    if not found_lead:
        for c in candidates:
            if c["kind"] == "email":
                continue
            needle = c["value"]
            if len(needle) < 3:
                continue
            for lname, l in lead_index["by_name_lower"]:
                if _matches(needle, lname):
                    found_lead = l
                    break
            if found_lead:
                break

    # Pass 3: If we found a Lead, derive its email-domain-root and re-check
    # Deals. Fathom data is mostly name-only, so the Lead's email is often
    # the ONLY way to discover the company name to match against Deal.dealname.
    # This is what catches Madhur Kabra → Lead madhur@colab91.com → Deal "Colab91".
    if found_lead:
        contact_email = (found_lead.get("contact_email") or "").lower()
        if contact_email:
            root = _email_domain_root(contact_email)
            if root and len(root) >= 3:
                for dname, d in deal_index["by_name_lower"]:
                    if _matches(root, dname):
                        return ("deal", d)
        return ("lead", found_lead)

    return ("none", None)


def _email_domain_root(email: str) -> str | None:
    """Extract the company root from an email domain.

    Strategy: take the part immediately before the TLD, since that's the
    brand component. Handles plain (madhur@colab91.com → 'colab91') and
    subdomain (smritycs@secretary.skoegle.com → 'skoegle') cases.
    """
    if "@" not in email:
        return None
    domain = email.split("@", 1)[1].lower().strip()
    parts = [p for p in domain.split(".") if p]
    if len(parts) >= 2:
        return parts[-2]  # part right before TLD
    return parts[0] if parts else None


def _matches(needle: str, haystack: str) -> bool:
    """Match needle against haystack with two strategies:

    1. Normalized substring — strip whitespace + punctuation from both,
       check if needle is a substring of haystack. Handles "gradientm" vs
       "gradient m" (space variance is common between Fathom title shorthand
       and HubSpot record names).

    2. All-words-present — for multi-word needles, require EVERY 4+ char
       word to appear in haystack. Stops common-surname false positives
       like "saket kumar" matching "piyush kumar".
    """
    if not needle or not haystack:
        return False

    def _norm(s: str) -> str:
        s = re.sub(r"[^a-z0-9]+", "", s.lower())
        return s

    if _norm(needle) and _norm(needle) in _norm(haystack):
        return True

    needle_words = [w for w in re.split(r"\W+", needle.lower()) if len(w) >= 4]
    if len(needle_words) >= 2:
        return all(w in haystack.lower() for w in needle_words)
    return False


def _format_candidate_summary(candidates: list[dict]) -> str:
    """Compact human-readable summary of what we tried to match."""
    parts = []
    for c in candidates:
        kind = {"email": "email", "name": "person", "title": "title", "domain_root": "domain"}[c["kind"]]
        parts.append(f"{kind}={c['value']}")
    return " · ".join(parts)


def _summarize_match(match_type: str, record: dict | None) -> str:
    if not record:
        return "—"
    if match_type == "lead":
        bits = [record.get("lead_name"), record.get("contact_name"), record.get("contact_email")]
        return " / ".join(b for b in bits if b)
    if match_type == "contact":
        return record.get("email") or "?"
    if match_type == "deal":
        return record.get("dealname") or "?"
    return "—"


def _to_legacy_row(row: dict) -> dict:
    """Adapt the new shape to the old template fields (company, contact_email, ...)."""
    cand = row["candidate"]
    contact_email = ""
    for tag in cand.split(" · "):
        if tag.startswith("email="):
            contact_email = tag.removeprefix("email=")
            break
    state = (
        "lead exists, no deal" if row.get("matched_record_type") == "lead"
        else "contact only, no lead/deal" if row.get("matched_record_type") == "contact"
        else "no CRM record"
    )
    return {
        "company": row.get("matched_record") or cand,
        "contact_email": contact_email or "—",
        "last_call_date": row["last_call_date"],
        "call_type": row["call_type"],
        "crm_state": state,
        "suggested_action_default": row["suggested_action"],
    }
