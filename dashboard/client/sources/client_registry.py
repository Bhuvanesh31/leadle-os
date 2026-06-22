"""Resolve a client name to its Google Sheets spreadsheet id (config/clients.yaml)."""

from __future__ import annotations

from pathlib import Path

import yaml

from dashboard.client import constants


def _load() -> dict:
    text = Path(constants.CLIENTS_CONFIG).read_text(encoding="utf-8")
    data = yaml.safe_load(text) or {}
    return data.get("clients", {})


def spreadsheet_id_for(client: str) -> str:
    """Return the spreadsheet id for `client`, or raise KeyError listing known clients."""
    clients = _load()
    entry = clients.get(client)
    if not entry or "spreadsheet_id" not in entry:
        known = ", ".join(sorted(clients)) or "(none)"
        raise KeyError(f"Unknown client '{client}'. Known clients: {known}")
    return entry["spreadsheet_id"]
