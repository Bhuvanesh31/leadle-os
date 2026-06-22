"""Period-to-date-range helpers shared by all analytics scripts.

Supported period names:
  week          current week (Mon–today)
  last-week     previous Mon–Sun
  month         current month (1st–today)
  last-month    previous full month
  quarter       current quarter (Q1=Jan, Q2=Apr, Q3=Jul, Q4=Oct)
  last-quarter  previous full quarter
  ytd           Jan 1 of current year through today
  fy            FY Apr 1 – Mar 31 (Indian fiscal year, current)
  last-fy       previous Indian fiscal year

Usage:
    from analytics._periods import resolve_period
    start, end, label = resolve_period("quarter")
"""

from __future__ import annotations

from datetime import date, timedelta


def resolve_period(period: str) -> tuple[date, date, str]:
    """Return (start, end, human_label) for the named period."""
    today = date.today()
    p = period.lower().strip()

    if p == "week":
        start = today - timedelta(days=today.weekday())
        return start, today, f"This week ({start.isoformat()} to {today.isoformat()})"

    if p == "last-week":
        end = today - timedelta(days=today.weekday() + 1)
        start = end - timedelta(days=6)
        return start, end, f"Last week ({start.isoformat()} to {end.isoformat()})"

    if p == "month":
        start = today.replace(day=1)
        return start, today, f"This month ({start.strftime('%b %Y')})"

    if p == "last-month":
        end = today.replace(day=1) - timedelta(days=1)
        start = end.replace(day=1)
        return start, end, f"Last month ({start.strftime('%b %Y')})"

    if p == "quarter":
        q = (today.month - 1) // 3
        start = date(today.year, q * 3 + 1, 1)
        label = f"Q{q + 1} {today.year} ({start.isoformat()} to {today.isoformat()})"
        return start, today, label

    if p == "last-quarter":
        q = (today.month - 1) // 3
        if q == 0:
            start = date(today.year - 1, 10, 1)
            end = date(today.year - 1, 12, 31)
        else:
            start = date(today.year, (q - 1) * 3 + 1, 1)
            end = date(today.year, q * 3, 1) - timedelta(days=1)
        label = f"Last quarter ({start.isoformat()} to {end.isoformat()})"
        return start, end, label

    if p == "ytd":
        start = date(today.year, 1, 1)
        return start, today, f"YTD {today.year} ({start.isoformat()} to {today.isoformat()})"

    if p == "fy":
        # Indian FY: Apr 1 – Mar 31
        fy_start_year = today.year if today.month >= 4 else today.year - 1
        start = date(fy_start_year, 4, 1)
        return (
            start,
            today,
            f"FY {fy_start_year}/{str(fy_start_year + 1)[-2:]} ({start.isoformat()} to {today.isoformat()})",
        )

    if p == "last-fy":
        fy_start_year = (today.year if today.month >= 4 else today.year - 1) - 1
        start = date(fy_start_year, 4, 1)
        end = date(fy_start_year + 1, 3, 31)
        return (
            start,
            end,
            f"FY {fy_start_year}/{str(fy_start_year + 1)[-2:]} ({start.isoformat()} to {end.isoformat()})",
        )

    raise ValueError(
        f"Unknown period '{period}'. Use: week, last-week, month, last-month, "
        "quarter, last-quarter, ytd, fy, last-fy"
    )


def add_period_args(parser) -> None:
    """Add --period / --start / --end to an argparse parser (mutually exclusive)."""
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--period",
        metavar="PERIOD",
        help="Named period: week, last-week, month, last-month, quarter, last-quarter, ytd, fy, last-fy",
    )
    group.add_argument(
        "--start", metavar="DATE", help="Cohort start date (ISO). Use with optional --end."
    )
    parser.add_argument(
        "--end", metavar="DATE", help="Cohort end date (ISO). Defaults to today if --start given."
    )


def resolve_args(args) -> tuple[date | None, date | None, str]:
    """Return (start, end, label) from parsed args with --period / --start / --end."""
    if args.period:
        return resolve_period(args.period)
    if args.start:
        start = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end) if args.end else date.today()
        return start, end, f"{start.isoformat()} to {end.isoformat()}"
    return None, None, "All time"
