"""On-demand client campaign report: source -> compute -> agents -> HTML.

The session loads the Drive-dumped workbook with --xlsx; the loader assembles
sheet + Aimfox + Instantly into a ClientData. Snapshots use a local JSON store
by default. One run emits up to 4 files (period × audience).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader

from dashboard.client import compute, constants, snapshots
from dashboard.client.agents import actions as actions_agent
from dashboard.client.agents import narrative as narrative_agent
from dashboard.client.sources import loader

_ROOT = Path(__file__).resolve().parents[2]
_CONFIG = _ROOT / "config"
_TEMPLATES = Path(__file__).parent / "templates"


def _load(name: str) -> dict:
    return yaml.safe_load((_CONFIG / name).read_text())


def _window(period: str, period_end_iso: str) -> tuple[str, str]:
    """Return (start_iso, end_iso) for the given period kind and end date.

    monthly: first day of period_end's month → period_end
    weekly:  period_end minus 6 days → period_end
    """
    end = date.fromisoformat(period_end_iso)
    start = end.replace(day=1) if period == "monthly" else end - timedelta(days=6)
    return start.isoformat(), end.isoformat()


def visible_blocks(layout: dict, audience: str) -> list[dict]:
    return [b for b in layout["blocks"] if b["visibility"] == "both" or b["visibility"] == audience]


def render(
    data,
    metrics,
    deltas_bag,
    narrative,
    actions,
    *,
    audience,
    period_label,
    client,
    layout,
    rubric,
    sample=False,
    rendered_at: str | None = None,
) -> str:
    env = Environment(loader=FileSystemLoader(str(_TEMPLATES)), autoescape=True)
    template = env.get_template("report.html.j2")
    if rendered_at is None:
        rendered_at = datetime.now().isoformat(timespec="seconds")
    return template.render(
        client=client,
        period_label=period_label,
        audience=audience,
        sample=sample,
        blocks=visible_blocks(layout, audience),
        metrics=metrics,
        deltas=deltas_bag,
        narrative=narrative,
        actions=actions,
        rendered_at=rendered_at,
        rubric=rubric,
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", default="UPSTA")
    ap.add_argument(
        "--xlsx",
        default=None,
        help="Optional offline workbook (.xlsx). Omit to read live from the "
        "configured Google Sheet for --client.",
    )
    # Period selection: --period XOR --all-periods; default is all-periods
    period_group = ap.add_mutually_exclusive_group()
    period_group.add_argument("--period", choices=["weekly", "monthly"])
    period_group.add_argument("--all-periods", action="store_true", default=False)
    ap.add_argument("--audience", choices=["internal", "client", "both"], default="both")
    ap.add_argument("--period-end", default=date.today().isoformat())
    ap.add_argument("--skip-agents", action="store_true")
    ap.add_argument(
        "--snapshot-store", default=str(_ROOT / "reports" / "client" / "_snapshots.json")
    )
    ap.add_argument("--output-dir", default=str(_ROOT / "reports" / "client"))
    ap.add_argument("--sample", action="store_true")
    args = ap.parse_args(argv)

    rubric = _load("client_report_rubric.yaml")
    layout = _load("client_report_layout.yaml")

    # Resolve period list
    if args.all_periods or (not args.period and not args.all_periods):
        periods = ["monthly", "weekly"]
    else:
        periods = [args.period]

    # Resolve audience list
    audiences = ["internal", "client"] if args.audience == "both" else [args.audience]

    store = snapshots.LocalJsonStore(args.snapshot_store)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    client_name = args.client

    for period in periods:
        window = _window(period, args.period_end)

        data = loader.load(
            window,
            client=client_name,
            xlsx_path=args.xlsx,
            aimfox_key=os.environ.get(constants.AIMFOX_ENV, ""),
            instantly_key=os.environ.get(constants.INSTANTLY_ENV, ""),
            name_contains=constants.CAMPAIGN_FILTER,
        )

        # Guard: no campaign/spine signal at all
        if (
            not data.email_campaigns
            and not data.linkedin_campaigns
            and not data.warm_leads
            and not data.targets
        ):
            print(
                f"No data matched client '{client_name}' for {period} window "
                f"{window[0]}..{window[1]}. Check the workbook or campaign prefix.",
                file=sys.stderr,
            )
            return 2

        metrics = compute.compute_all(data, rubric)

        prior = store.prior(client_name, period, before=args.period_end)
        deltas_bag = snapshots.box_deltas(metrics, prior)

        for audience in audiences:
            if args.skip_agents:
                narrative = {"degraded": True, "narrative": ""}
                actions = {"degraded": True, "actions": []}
            else:
                narrative = asyncio.run(
                    narrative_agent.synthesize(metrics, audience=audience, client=client_name)
                )
                actions = asyncio.run(
                    actions_agent.synthesize(metrics, client=client_name, rubric=rubric)
                )

            label = f"{period} ending {args.period_end}"
            html = render(
                data,
                metrics,
                deltas_bag,
                narrative,
                actions,
                audience=audience,
                period_label=label,
                client=client_name,
                layout=layout,
                rubric=rubric,
                sample=args.sample,
            )

            out = out_dir / f"{client_name}-{args.period_end}-{period}-{audience}.html"
            out.write_text(html, encoding="utf-8")
            print(str(out.absolute()))

        store.save(client_name, period, args.period_end, metrics)

    return 0


if __name__ == "__main__":
    sys.exit(main())
