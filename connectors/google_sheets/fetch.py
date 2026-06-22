"""Raw Google Sheets fetch: spreadsheet_id + tab names -> {tab: rows}.

Authorizes as the operator (OAuth, scope spreadsheets.readonly). The gspread
client is injectable so tests never hit the network or auth. The Google
libraries are imported lazily inside _authorized_client so the injected-client
path needs neither installed.
"""
from __future__ import annotations

import os

from dashboard.client import constants

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


def _authorized_client():
    """Build an authorized gspread client from the cached OAuth token.

    The token JSON (written once by connectors.google_sheets.authorize) carries
    the refresh token and client id/secret, so refresh needs no extra files.
    Raises RuntimeError with an actionable message when the token is
    missing/invalid.
    """
    token_path = os.environ.get(constants.GOOGLE_SHEETS_TOKEN_ENV)
    if not token_path or not os.path.exists(token_path):
        raise RuntimeError(
            f"Google Sheets token missing. Set {constants.GOOGLE_SHEETS_TOKEN_ENV} to the "
            f"OAuth token path and run once: python -m connectors.google_sheets.authorize"
        )

    import gspread
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    creds = Credentials.from_authorized_user_file(token_path, _SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(token_path, "w", encoding="utf-8") as fh:
                fh.write(creds.to_json())
        else:
            raise RuntimeError(
                "Google Sheets token invalid and cannot refresh. Re-run once: "
                "python -m connectors.google_sheets.authorize"
            )
    return gspread.authorize(creds)


def fetch(spreadsheet_id: str, tab_names, *, client=None) -> dict[str, list]:
    """Return {tab_name: rows} for each requested tab that exists in the sheet.

    rows = worksheet.get_all_values() (list of row-lists, header first). Tabs
    absent from the spreadsheet are omitted. Inject `client` in tests to skip
    auth and network.
    """
    gc = client or _authorized_client()
    sh = gc.open_by_key(spreadsheet_id)
    existing = {ws.title for ws in sh.worksheets()}
    out: dict[str, list] = {}
    for name in tab_names:
        if name in existing:
            out[name] = sh.worksheet(name).get_all_values()
    return out
