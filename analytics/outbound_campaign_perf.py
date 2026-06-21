"""Outbound campaign performance — Aimfox (LinkedIn) + Instantly (email). Process #12.

Pulls live campaign metrics from Aimfox and Instantly via their REST connectors.
Lemlist is not yet wired (connector stub only — no API key required yet).

Source availability model:
  Each source returns {available: True, data: {...}} or {available: False, reason: "..."}.
  Missing API keys or server errors produce available=False; the report renders a
  "source unavailable" row so the dashboard degrades cleanly rather than crashing.

Metrics per campaign:
  Aimfox (LinkedIn):  sends, replies, reply_rate_pct
  Instantly (email):  sends, opened, clicked, bounced, replied, reply_rate_pct, open_rate_pct

Required env vars (set in .env):
  AIMFOX_API_KEY      LinkedIn campaigns via Aimfox REST
  INSTANTLY_API_KEY   Email campaigns via Instantly REST

Outputs:
  --json FILE   machine-readable report
  --out  FILE   HTML report

Usage:
    python -m analytics.outbound_campaign_perf
    python -m analytics.outbound_campaign_perf --period last-month
    python -m analytics.outbound_campaign_perf --start 2026-06-01 --end 2026-06-21
    python -m analytics.outbound_campaign_perf --json /tmp/outbound_perf.json
"""
from __future__ import annotations

import argparse
import html as _html
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

from analytics._periods import add_period_args, resolve_args, resolve_period

_REPORTS_DIR = Path(__file__).parent.parent / "reports"
_DEFAULT_PERIOD = "month"


def _fetch_aimfox(key: str, start: date, end: date) -> dict:
    if not key:
        return {"available": False, "reason": "AIMFOX_API_KEY not set"}
    from connectors.aimfox.fetch import fetch
    return fetch(key, start, end)


def _fetch_instantly(key: str, start: date, end: date) -> dict:
    if not key:
        return {"available": False, "reason": "INSTANTLY_API_KEY not set"}
    from connectors.instantly.fetch import fetch
    return fetch(key, start, end)


def _shape_aimfox_campaigns(result: dict) -> list[dict]:
    if not result.get("available"):
        return []
    out = []
    for c in result["data"].get("campaigns", []):
        stats = c.get("stats", {})
        sends = stats.get("sends", 0)
        replies = stats.get("replies", 0)
        out.append({
            "source": "linkedin",
            "name": c.get("name") or "(unnamed)",
            "sends": sends,
            "replies": replies,
            "reply_rate_pct": round(replies / sends * 100, 1) if sends > 0 else 0.0,
            "opened": None,
            "clicked": None,
            "bounced": None,
            "open_rate_pct": None,
        })
    return sorted(out, key=lambda x: x["reply_rate_pct"], reverse=True)


def _shape_instantly_campaigns(result: dict) -> list[dict]:
    if not result.get("available"):
        return []
    out = []
    for c in result["data"].get("campaigns", []):
        sends = c.get("sent", 0)
        opened = c.get("opened", 0)
        clicked = c.get("clicked", 0)
        bounced = c.get("bounced", 0)
        replied = c.get("replied", 0)
        out.append({
            "source": "email",
            "name": c.get("name") or "(unnamed)",
            "sends": sends,
            "replies": replied,
            "reply_rate_pct": round(replied / sends * 100, 1) if sends > 0 else 0.0,
            "opened": opened,
            "clicked": clicked,
            "bounced": bounced,
            "open_rate_pct": round(opened / sends * 100, 1) if sends > 0 else 0.0,
        })
    return sorted(out, key=lambda x: x["reply_rate_pct"], reverse=True)


def build_report(aimfox_result: dict, instantly_result: dict,
                 window_start: date, window_end: date, window_label: str) -> dict:
    li_campaigns = _shape_aimfox_campaigns(aimfox_result)
    em_campaigns = _shape_instantly_campaigns(instantly_result)

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "window": {
            "start": window_start.isoformat(),
            "end": window_end.isoformat(),
            "label": window_label,
        },
        "sources": {
            "aimfox": {
                "available": aimfox_result.get("available", False),
                "reason": aimfox_result.get("reason"),
                "campaign_count": len(li_campaigns),
            },
            "instantly": {
                "available": instantly_result.get("available", False),
                "reason": instantly_result.get("reason"),
                "campaign_count": len(em_campaigns),
            },
        },
        "linkedin_campaigns": li_campaigns,
        "email_campaigns": em_campaigns,
        "totals": {
            "linkedin": {
                "sends": sum(c["sends"] for c in li_campaigns),
                "replies": sum(c["replies"] for c in li_campaigns),
            },
            "email": {
                "sends": sum(c["sends"] for c in em_campaigns),
                "replies": sum(c["replies"] for c in em_campaigns),
                "opened": sum(c["opened"] for c in em_campaigns),
                "bounced": sum(c["bounced"] for c in em_campaigns),
            },
        },
    }


# ── HTML render ───────────────────────────────────────────────────────────────

def _pct_cell(val: float | None, warn_below: float = 5.0) -> str:
    if val is None:
        return '<span style="color:#9ca3af">—</span>'
    color = "#9b2226" if val < warn_below else "#374151"
    return f'<span style="color:{color};font-family:\'JetBrains Mono\',monospace;font-size:12px">{val:.1f}%</span>'


def _num_cell(val: int | None) -> str:
    if val is None:
        return '<span style="color:#9ca3af">—</span>'
    return f'<span style="font-family:\'JetBrains Mono\',monospace;font-size:12px">{val:,}</span>'


def _source_status_badge(info: dict) -> str:
    if info["available"]:
        n = info["campaign_count"]
        return f'<span style="background:#f0fdf4;color:#2d6a4f;border-radius:4px;padding:2px 7px;font-size:11px;font-weight:600">{n} campaign{"s" if n != 1 else ""}</span>'
    reason = _html.escape(info.get("reason") or "unavailable")
    return f'<span style="background:#fef2f2;color:#9b2226;border-radius:4px;padding:2px 7px;font-size:11px;font-weight:600" title="{reason}">unavailable</span>'


def _li_table(campaigns: list[dict]) -> str:
    if not campaigns:
        return '<tr><td colspan="4" style="padding:20px;text-align:center;color:#9ca3af;font-size:12px">No LinkedIn campaign data available.</td></tr>'
    rows = ""
    for c in campaigns:
        name = _html.escape(c["name"])
        rows += f"""
        <tr>
          <td style="padding:10px 14px;font-size:13px;font-weight:500">{name}</td>
          <td style="padding:10px 14px">{_num_cell(c['sends'])}</td>
          <td style="padding:10px 14px">{_num_cell(c['replies'])}</td>
          <td style="padding:10px 14px">{_pct_cell(c['reply_rate_pct'])}</td>
        </tr>"""
    return rows


def _em_table(campaigns: list[dict]) -> str:
    if not campaigns:
        return '<tr><td colspan="7" style="padding:20px;text-align:center;color:#9ca3af;font-size:12px">No email campaign data available.</td></tr>'
    rows = ""
    for c in campaigns:
        name = _html.escape(c["name"])
        rows += f"""
        <tr>
          <td style="padding:10px 14px;font-size:13px;font-weight:500">{name}</td>
          <td style="padding:10px 14px">{_num_cell(c['sends'])}</td>
          <td style="padding:10px 14px">{_num_cell(c['opened'])}</td>
          <td style="padding:10px 14px">{_pct_cell(c['open_rate_pct'], warn_below=20.0)}</td>
          <td style="padding:10px 14px">{_num_cell(c['clicked'])}</td>
          <td style="padding:10px 14px">{_num_cell(c['replies'])}</td>
          <td style="padding:10px 14px">{_pct_cell(c['reply_rate_pct'])}</td>
        </tr>"""
    return rows


def render_html(report: dict) -> str:
    window = report["window"]
    src = report["sources"]
    tot = report["totals"]
    li_total_sends = tot["linkedin"]["sends"]
    li_total_replies = tot["linkedin"]["replies"]
    li_reply_pct = round(li_total_replies / li_total_sends * 100, 1) if li_total_sends > 0 else 0.0
    em_total_sends = tot["email"]["sends"]
    em_total_replies = tot["email"]["replies"]
    em_reply_pct = round(em_total_replies / em_total_sends * 100, 1) if em_total_sends > 0 else 0.0
    em_total_opened = tot["email"]["opened"]
    em_open_pct = round(em_total_opened / em_total_sends * 100, 1) if em_total_sends > 0 else 0.0

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Outbound Campaign Performance — Leadle</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Fraunces:ital,wght@0,400;0,600;1,400&family=Inter+Tight:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');
  :root{{--bg:#fafaf7;--surface:#fff;--ink:#15171a;--red:#9b2226;--amber:#b45309;--blue:#1e40af;--green:#2d6a4f;--muted:#6b7280;--border:#e5e7eb}}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:var(--bg);color:var(--ink);font-family:'Inter Tight',sans-serif;font-size:14px;line-height:1.5;padding:32px 24px}}
  .wrap{{max-width:1100px;margin:0 auto}}
  h1{{font-family:'Fraunces',serif;font-size:26px;font-weight:600;margin-bottom:4px}}
  h2{{font-family:'Inter Tight',sans-serif;font-size:14px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin-bottom:12px}}
  .meta{{color:var(--muted);font-size:12px;margin-bottom:28px}}
  .stat-row{{display:flex;gap:16px;margin-bottom:20px}}
  .stat{{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:14px 18px;flex:1}}
  .stat-n{{font-family:'JetBrains Mono',monospace;font-size:22px;font-weight:500}}
  .stat-l{{font-size:11px;color:var(--muted);margin-top:2px;text-transform:uppercase;letter-spacing:.04em}}
  .card{{background:var(--surface);border-radius:10px;border:1px solid var(--border);overflow:hidden;margin-bottom:24px}}
  .card-header{{padding:12px 16px;font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.05em;border-bottom:1px solid var(--border);background:#f9fafb;color:var(--muted);display:flex;justify-content:space-between;align-items:center}}
  table{{width:100%;border-collapse:collapse}}
  thead th{{background:#f3f4f6;padding:9px 14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);font-weight:600}}
  tbody tr:not(:last-child){{border-bottom:1px solid var(--border)}}
  tbody tr:hover{{background:#f9fafb}}
</style>
</head>
<body>
<div class="wrap">
  <h1>Outbound Campaign Performance</h1>
  <div class="meta">Leadle RevOps &bull; {_html.escape(window['label'])} &bull; Generated {report['generated_at']}</div>

  <div class="stat-row">
    <div class="stat">
      <div class="stat-n">{li_total_sends:,}</div>
      <div class="stat-l">LinkedIn Sends</div>
    </div>
    <div class="stat">
      <div class="stat-n" style="color:{'var(--red)' if li_reply_pct < 5 and li_total_sends > 0 else 'var(--ink)'}">{li_reply_pct:.1f}%</div>
      <div class="stat-l">LinkedIn Reply Rate</div>
    </div>
    <div class="stat">
      <div class="stat-n">{em_total_sends:,}</div>
      <div class="stat-l">Email Sends</div>
    </div>
    <div class="stat">
      <div class="stat-n" style="color:{'var(--red)' if em_open_pct < 20 and em_total_sends > 0 else 'var(--ink)'}">{em_open_pct:.1f}%</div>
      <div class="stat-l">Email Open Rate</div>
    </div>
    <div class="stat">
      <div class="stat-n" style="color:{'var(--red)' if em_reply_pct < 5 and em_total_sends > 0 else 'var(--ink)'}">{em_reply_pct:.1f}%</div>
      <div class="stat-l">Email Reply Rate</div>
    </div>
  </div>

  <div class="card">
    <div class="card-header">
      <span>LinkedIn Campaigns (Aimfox)</span>
      {_source_status_badge(src['aimfox'])}
    </div>
    <table>
      <thead>
        <tr>
          <th>Campaign</th><th>Sends</th><th>Replies</th><th>Reply Rate</th>
        </tr>
      </thead>
      <tbody>{_li_table(report['linkedin_campaigns'])}</tbody>
    </table>
  </div>

  <div class="card">
    <div class="card-header">
      <span>Email Campaigns (Instantly)</span>
      {_source_status_badge(src['instantly'])}
    </div>
    <table>
      <thead>
        <tr>
          <th>Campaign</th><th>Sends</th><th>Opened</th><th>Open Rate</th>
          <th>Clicked</th><th>Replied</th><th>Reply Rate</th>
        </tr>
      </thead>
      <tbody>{_em_table(report['email_campaigns'])}</tbody>
    </table>
  </div>
</div>
</body>
</html>"""


# ── main ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="analytics.outbound_campaign_perf")
    add_period_args(parser)
    parser.add_argument("--json", metavar="FILE", help="Dump report JSON to this path")
    parser.add_argument("--out", metavar="FILE", help="Output HTML path")
    args = parser.parse_args(argv)

    start, end, label = resolve_args(args)
    if start is None:
        start, end, label = resolve_period(_DEFAULT_PERIOD)

    aimfox_key = os.environ.get("AIMFOX_API_KEY", "")
    instantly_key = os.environ.get("INSTANTLY_API_KEY", "")

    print(f"Window: {label}", file=sys.stderr)
    print("Fetching Aimfox (LinkedIn)...", file=sys.stderr)
    aimfox_result = _fetch_aimfox(aimfox_key, start, end)
    print(f"  available={aimfox_result.get('available')} "
          f"{'(' + aimfox_result.get('reason','') + ')' if not aimfox_result.get('available') else ''}",
          file=sys.stderr)

    print("Fetching Instantly (email)...", file=sys.stderr)
    instantly_result = _fetch_instantly(instantly_key, start, end)
    print(f"  available={instantly_result.get('available')} "
          f"{'(' + instantly_result.get('reason','') + ')' if not instantly_result.get('available') else ''}",
          file=sys.stderr)

    report = build_report(aimfox_result, instantly_result, start, end, label)
    src = report["sources"]
    tot = report["totals"]

    print(f"\nOutbound Campaign Performance — {label}")
    if src["aimfox"]["available"]:
        li = tot["linkedin"]
        rr = round(li['replies'] / li['sends'] * 100, 1) if li['sends'] else 0
        print(f"  LinkedIn: {li['sends']:,} sends  {li['replies']} replies  {rr:.1f}% reply rate"
              f"  ({src['aimfox']['campaign_count']} campaigns)")
    else:
        print(f"  LinkedIn: UNAVAILABLE — {src['aimfox']['reason']}")

    if src["instantly"]["available"]:
        em = tot["email"]
        rr = round(em['replies'] / em['sends'] * 100, 1) if em['sends'] else 0
        op = round(em['opened'] / em['sends'] * 100, 1) if em['sends'] else 0
        print(f"  Email:    {em['sends']:,} sends  {em['opened']} opened ({op:.1f}%)  "
              f"{em['replies']} replied ({rr:.1f}%)"
              f"  ({src['instantly']['campaign_count']} campaigns)")
    else:
        print(f"  Email:    UNAVAILABLE — {src['instantly']['reason']}")

    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Report JSON → {args.json}", file=sys.stderr)

    html = render_html(report)
    out_path = args.out
    if not out_path:
        slug = date.today().isoformat()
        _REPORTS_DIR.mkdir(exist_ok=True)
        out_path = str(_REPORTS_DIR / f"outbound-campaign-perf-{slug}.html")
    Path(out_path).write_text(html, encoding="utf-8")
    print(f"Report → {out_path}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
