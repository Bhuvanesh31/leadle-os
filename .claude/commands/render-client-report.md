---
description: Render the UPSTA client campaign report (4 outputs) from the Drive workbook + live APIs
allowed-tools: Bash, mcp__claude_ai_Google_Drive__download_file_content, mcp__claude_ai_Google_Drive__get_file_metadata
---

# /render-client-report

You are rendering the UPSTA client campaign dashboard. Follow this protocol exactly.

## Step 1 — Resolve today's date

```bash
date "+%Y-%m-%d"
```

Save the output as `<today>`.

## Step 2 — Download the workbook

Download the UPSTA prospect-list workbook from Drive as a raw XLSX (not the text flatten — the text flatten silently truncates rows and produces wrong numbers).

Use `mcp__claude_ai_Google_Drive__download_file_content` with:
- `fileId`: `1GgFeDdXpy1ZlDjH8bTWNL_c7m0ihSSO_-iYNyzadCQg` (this is `constants.SHEET_DRIVE_ID`)
- `exportMimeType`: `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`

Save the result to `/tmp/upsta_workbook.xlsx`.

## Step 3 — Confirm live API keys

Check that `AIMFOX_API_KEY` and `INSTANTLY_API_KEY` are set in the environment:

```bash
echo "AIMFOX: ${AIMFOX_API_KEY:+set}" && echo "INSTANTLY: ${INSTANTLY_API_KEY:+set}"
```

If either is absent, note it. The render will continue but the corresponding campaign numbers block degrades to empty rather than crashing.

## Step 4 — Run the render

```bash
source .venv/bin/activate && python -m dashboard.client.render \
  --xlsx /tmp/upsta_workbook.xlsx --all-periods --audience both --period-end <today>
```

This writes 4 HTML files to `reports/client/`:
- `UPSTA-<today>-monthly-internal.html`
- `UPSTA-<today>-monthly-client.html`
- `UPSTA-<today>-weekly-internal.html`
- `UPSTA-<today>-weekly-client.html`

The CLI prints each absolute path as it writes it.

## Step 5 — Report

Print the 4 output paths from the CLI to chat. If any source degraded (Aimfox or Instantly key absent, or the CLI warned about no data matching), note it alongside the affected period.
