"""CLI entrypoint for /render-dashboard to fetch HubSpot Leads.

Usage:
  python -m connectors.hubspot.cli --start 2026-04-01 --end 2026-06-30 \\
         --owner 80765353 --owner 77758216 --owner 82016648 --owner 77502812

Reads HUBSPOT_PRIVATE_TOKEN from env (or .env). Prints the fetch() JSON to
stdout. Exit code 0 even on API errors (the dashboard treats degraded sources
as a normal case).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date

from dotenv import load_dotenv

from connectors.hubspot.leads import fetch


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(prog="connectors.hubspot.cli")
    parser.add_argument("--start", required=True, help="Window start (ISO date)")
    parser.add_argument("--end", required=True, help="Window end (ISO date)")
    parser.add_argument(
        "--owner",
        action="append",
        default=None,
        help="Restrict to this hubspot_owner_id. Pass multiple times for an allowlist.",
    )
    args = parser.parse_args(argv)

    token = os.environ.get("HUBSPOT_PRIVATE_TOKEN")
    if not token:
        result = {"available": False, "reason": "HUBSPOT_PRIVATE_TOKEN not set in environment"}
    else:
        result = fetch(
            token,
            date.fromisoformat(args.start),
            date.fromisoformat(args.end),
            owner_allowlist=args.owner,
        )

    json.dump(result, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
