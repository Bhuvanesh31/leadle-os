"""Dashboard render CLI: python -m dashboard.render --input <raw.json>."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
import yaml

from dashboard.agents import fathom_gap, forward_motion, funnel_leak, hygiene
from dashboard.compute import page1_revenue, page2_activity, page3_actions, page4_outreach
from dashboard.compute.windows import WindowSpec

_ROOT = Path(__file__).resolve().parents[1]
_CONFIG = _ROOT / "config"
_TEMPLATES = _ROOT / "dashboard" / "templates"


def _load_yaml(name: str) -> dict:
    return yaml.safe_load((_CONFIG / name).read_text())


def _window_from_raw(raw: dict) -> WindowSpec:
    w = raw["window"]
    return WindowSpec(
        name=w["name"], label=w["label"],
        start=date.fromisoformat(w["start"]),
        end=date.fromisoformat(w["end"]),
        prior_start=date.fromisoformat(w["prior_start"]),
        prior_end=date.fromisoformat(w["prior_end"]),
    )


async def _narrate(analytics: dict) -> dict:
    fm, fl, hy, fg = await asyncio.gather(
        forward_motion.synthesize(analytics),
        funnel_leak.synthesize(analytics),
        hygiene.synthesize(analytics),
        fathom_gap.synthesize(analytics),
    )
    return {"forward_motion": fm, "funnel_leak": fl, "hygiene": hy, "fathom_gap": fg}


def _degraded_sections(narratives: dict) -> list[str]:
    return [k for k, v in narratives.items() if v.get("degraded")]


def render(raw: dict, *, skip_agents: bool = False) -> str:
    rules = _load_yaml("dashboard_rules.yaml")
    targets = _load_yaml("dashboard_targets.yaml")
    layout = _load_yaml("dashboard_layout.yaml")
    window = _window_from_raw(raw)

    # Clamp to real today when window.end is in the future (e.g. current-quarter).
    # Using window.end blindly makes every deal look ~weeks stale, since
    # days_stale = today - last_activity.
    today = min(date.fromisoformat(raw["window"]["end"]), date.today())

    analytics = {
        "page1": page1_revenue.compute(raw, rules, targets, window, today=today),
        "page2": page2_activity.compute(raw, rules, today=today),
        "page3": page3_actions.compute(raw, rules, window),
        "page4": page4_outreach.compute(raw, rules, window, today=today),
    }

    if skip_agents:
        narratives = {k: {"degraded": True} for k in
                      ["forward_motion", "funnel_leak", "hygiene", "fathom_gap"]}
    else:
        narratives = asyncio.run(_narrate(analytics))

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template("base.html.j2")
    html = template.render(
        analytics=analytics,
        narratives=narratives,
        window={"label": window.label, "name": window.name,
                "start": window.start.isoformat(), "end": window.end.isoformat()},
        rendered_at=datetime.now().isoformat(timespec="seconds"),
        degraded_sections=_degraded_sections(narratives),
        layout=layout,
    )
    return html


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Path to dashboard_raw_*.json")
    parser.add_argument("--skip-agents", action="store_true",
                        help="Skip Anthropic SDK calls (CI/test mode)")
    parser.add_argument("--output-dir", default=str(_ROOT / "reports"))
    args = parser.parse_args()

    raw = json.loads(Path(args.input).read_text())
    html = render(raw, skip_agents=args.skip_agents)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    end_date = raw["window"]["end"]
    window_name = raw["window"]["name"]
    out_path = out_dir / f"dashboard_{end_date}_{window_name}.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"Dashboard rendered: {out_path.absolute()}")
    print(f"   Window: {raw['window']['label']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
