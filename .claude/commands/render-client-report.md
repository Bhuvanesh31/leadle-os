---
description: Render the UPSTA client campaign report (4 outputs) live from Google Sheets + APIs
allowed-tools: Bash
---

Render the CLIENT campaign dashboard (`dashboard.client.render`) for `$1` (default UPSTA).

1. Resolve today's date: `date "+%Y-%m-%d"`.
2. Confirm the Google Sheets token exists: `test -f "$GOOGLE_SHEETS_TOKEN" && echo ok`.
   If missing, tell the user to run `python -m connectors.google_sheets.authorize` once
   (see `docs/data-shape/prospect-list-sheet.md`).
3. Confirm `AIMFOX_API_KEY` and `INSTANTLY_API_KEY` are in env (absence degrades campaign
   blocks to empty, not a crash).
4. Run (reads live from the sheet configured in `config/clients.yaml` for the client):
   ```bash
   source .venv/bin/activate && python -m dashboard.client.render \
     --client ${1:-UPSTA} --all-periods --audience both --period-end <today>
   ```
   Offline fallback: add `--xlsx /tmp/upsta_workbook.xlsx` to read a downloaded workbook.
5. Report the 4 output paths printed by the CLI. If any source degraded, note it.
