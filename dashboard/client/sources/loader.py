"""Sources assembler: merges XLSX sheet + Aimfox + Instantly into one ClientData.

load() is the single entry point. All three sources are independent; API sources
degrade silently (empty lists) on any exception rather than crashing the caller.
"""
from __future__ import annotations

import httpx

from connectors.instantly import fetch as instantly_fetch
from dashboard.client.model import ClientData, EmailCampaign
from dashboard.client.sources import aimfox_source, sheet_source


def load(
    xlsx_path: str,
    window: tuple[str, str],
    *,
    aimfox_key: str,
    instantly_key: str,
    name_contains: str,
    aimfox_client: httpx.Client | None = None,
    instantly_client: httpx.Client | None = None,
) -> ClientData:
    """Merge sheet + Aimfox + Instantly into a single ClientData.

    Degrade contract:
    - Aimfox exception → linkedin_campaigns stays []
    - Instantly unavailable/exception → email_campaigns, senders, content_steps stay []
    - Sheet errors propagate (XLSX is the ground truth; failures there are fatal).
    """
    # ── Sheet (ground truth) ──────────────────────────────────────────────────
    data = sheet_source.read_xlsx(xlsx_path)

    # ── Aimfox (LinkedIn campaigns) ───────────────────────────────────────────
    try:
        data.linkedin_campaigns = aimfox_source.read(
            aimfox_key,
            window,
            name_contains=name_contains,
            client=aimfox_client,
        )
    except Exception:
        data.linkedin_campaigns = []

    # ── Instantly (email campaigns) ───────────────────────────────────────────
    try:
        result = instantly_fetch.fetch(
            instantly_key,
            window[0],
            window[1],
            name_contains=name_contains,
            client=instantly_client,
        )
    except Exception:
        result = {"available": False, "reason": "exception"}

    if result.get("available"):
        payload = result["data"]
        data.email_campaigns = [
            EmailCampaign(
                name=c["name"],
                sent=c["sent"],
                opened=c["opened"],
                clicked=c["clicked"],
                bounced=c["bounced"],
                replied=c["replied"],
            )
            for c in payload.get("campaigns", [])
        ]
        data.senders = payload.get("senders", [])
        data.content_steps = payload.get("steps", [])
    else:
        data.email_campaigns = []
        data.senders = []
        data.content_steps = []

    return data
