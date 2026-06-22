"""One-time OAuth consent for the Google Sheets connector.

Run once: `python -m connectors.google_sheets.authorize`. Opens the browser to
sign in as revops@leadle.in, grants spreadsheets.readonly, and writes the token
JSON to GOOGLE_SHEETS_TOKEN. Not on the render hot path.
"""
from __future__ import annotations

import os

from dashboard.client import constants

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


def main() -> int:
    secret_path = os.environ.get(constants.GOOGLE_SHEETS_CLIENT_SECRET_ENV)
    token_path = os.environ.get(constants.GOOGLE_SHEETS_TOKEN_ENV)
    if not secret_path or not os.path.exists(secret_path):
        raise RuntimeError(
            f"Set {constants.GOOGLE_SHEETS_CLIENT_SECRET_ENV} to the OAuth client-secret "
            f"JSON (Desktop app) downloaded from GCP."
        )
    if not token_path:
        raise RuntimeError(
            f"Set {constants.GOOGLE_SHEETS_TOKEN_ENV} to the path where the token "
            f"should be written."
        )

    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(secret_path, _SCOPES)
    creds = flow.run_local_server(port=0)
    with open(token_path, "w", encoding="utf-8") as fh:
        fh.write(creds.to_json())
    print(f"Token written to {token_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
