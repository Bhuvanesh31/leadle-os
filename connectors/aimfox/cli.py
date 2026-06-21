"""CLI entrypoint for /render-dashboard to shell out to.

Reads AIMFOX_API_KEY from env (or .env in repo root), accepts --start/--end
ISO dates, prints the fetch() result as JSON to stdout. Exit code is always 0
because the dashboard treats a degraded source as a normal case, not an error.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date

from dotenv import load_dotenv

from connectors.aimfox.fetch import fetch


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(prog="connectors.aimfox.cli")
    parser.add_argument("--start", required=True, help="Window start (ISO date, e.g. 2026-05-01)")
    parser.add_argument("--end", required=True, help="Window end (ISO date, e.g. 2026-05-31)")
    parser.add_argument(
        "--name-contains",
        default=None,
        help="Case-insensitive substring filter on campaign name (e.g. 'Leadle')",
    )
    args = parser.parse_args(argv)

    api_key = os.environ.get("AIMFOX_API_KEY")
    if not api_key:
        result = {"available": False, "reason": "AIMFOX_API_KEY not set in environment"}
    else:
        result = fetch(
            api_key,
            date.fromisoformat(args.start),
            date.fromisoformat(args.end),
            name_contains=args.name_contains,
        )

    json.dump(result, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
