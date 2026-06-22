# UPSTA client identifiers and environment variable names.
# All values are hard-coded for the single UPSTA deployment (no multi-client machinery).

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]

SHEET_DRIVE_ID = "1GgFeDdXpy1ZlDjH8bTWNL_c7m0ihSSO_-iYNyzadCQg"

SPINE_TABS = ["Prospect Data-US", "Prospect Data- Singapore"]

WEBHOOK_LI = "Webhook - LinkedIn"
WEBHOOK_EMAIL = "Webhook - Email"
RESPONSE_TRACKER = "Response Tracker"

CAMPAIGN_FILTER = "upsta"
TIMEZONE = "America/New_York"

AIMFOX_ENV = "AIMFOX_API_KEY"
INSTANTLY_ENV = "INSTANTLY_API_KEY"

# Google Sheets connector (OAuth as revops@leadle.in, scope spreadsheets.readonly)
GOOGLE_SHEETS_CLIENT_SECRET_ENV = "GOOGLE_SHEETS_CLIENT_SECRET"
GOOGLE_SHEETS_TOKEN_ENV = "GOOGLE_SHEETS_TOKEN"
CLIENTS_CONFIG = str(_ROOT / "config" / "clients.yaml")
