"""On-demand client campaign report: source -> compute -> agents -> HTML.

MCP-orchestrated ingestion: the session dumps the Drive workbook to --workbook
before running this. Snapshots use a local JSON store by default.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date, datetime
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

from dashboard.client import compute, snapshots
from dashboard.client.agents import actions as actions_agent
from dashboard.client.agents import narrative as narrative_agent
from dashboard.client.sources import sheet_source

_ROOT = Path(__file__).resolve().parents[2]
_CONFIG = _ROOT / "config"
_TEMPLATES = Path(__file__).parent / "templates"


def _load(name: str) -> dict:
    return yaml.safe_load((_CONFIG / name).read_text())


def visible_blocks(layout: dict, audience: str) -> list[dict]:
    return [b for b in layout["blocks"]
            if b["visibility"] == "both" or b["visibility"] == audience]


def render(data, metrics, deltas_bag, narrative, actions, *, audience, period_label,
           client, layout, rubric, sample=False) -> str:
    env = Environment(loader=FileSystemLoader(str(_TEMPLATES)),
                      autoescape=select_autoescape(["html", "xml"]))
    template = env.get_template("report.html.j2")
    return template.render(
        client=client, period_label=period_label, audience=audience, sample=sample,
        blocks=visible_blocks(layout, audience), metrics=metrics,
        deltas=deltas_bag, narrative=narrative, actions=actions,
        rendered_at=datetime.now().isoformat(timespec="seconds"),
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", required=True)
    ap.add_argument("--workbook", required=True, help="Path to Drive-dumped workbook text")
    ap.add_argument("--period", choices=["weekly", "monthly"], default="monthly")
    ap.add_argument("--period-end", default=date.today().isoformat())
    ap.add_argument("--period-label", default=None)
    ap.add_argument("--audience", choices=["internal", "client"], default="client")
    ap.add_argument("--skip-agents", action="store_true")
    ap.add_argument("--snapshot-store",
                    default=str(_ROOT / "reports" / "client" / "_snapshots.json"))
    ap.add_argument("--output-dir", default=str(_ROOT / "reports" / "client"))
    ap.add_argument("--sample", action="store_true")
    args = ap.parse_args()

    rubric = _load("client_report_rubric.yaml")
    layout = _load("client_report_layout.yaml")

    data = sheet_source.read(args.client, args.workbook)
    if not data.emails and not data.linkedin and not data.warm_leads:
        print(f"No data matched client '{args.client}'. Check the campaign prefix.",
              file=sys.stderr)
        return 2

    metrics = compute.compute_all(data, rubric)

    store = snapshots.LocalJsonStore(args.snapshot_store)
    prior = store.prior(args.client, args.period, before=args.period_end)
    deltas_bag = snapshots.deltas(metrics["kpis"], prior.get("kpis") if prior else None)

    if args.skip_agents:
        narrative = {"degraded": True, "narrative": ""}
        actions = {"degraded": True, "actions": []}
    else:
        narrative = asyncio.run(narrative_agent.synthesize(
            metrics, audience=args.audience, client=args.client))
        actions = asyncio.run(actions_agent.synthesize(metrics, client=args.client))

    label = args.period_label or f"{args.period} ending {args.period_end}"
    html = render(data, metrics, deltas_bag, narrative, actions,
                  audience=args.audience, period_label=label, client=args.client,
                  layout=layout, rubric=rubric, sample=args.sample)

    store.save(args.client, args.period, args.period_end, metrics)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{args.client}-{args.period_end}-{args.period}-{args.audience}.html"
    out.write_text(html, encoding="utf-8")
    print(f"Client report rendered: {out.absolute()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
