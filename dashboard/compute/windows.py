"""Window resolution: window arg + today → concrete WindowSpec.

The dashboard uses an Indian fiscal year (Apr–Mar). FY2026 = Apr 2026 – Mar 2027.
Every window arg resolves to (start, end, prior_start, prior_end) given today.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Final

from ruamel.yaml import YAML

_CONFIG_PATH: Final = Path(__file__).resolve().parents[2] / "config" / "dashboard_windows.yaml"


@dataclass(frozen=True)
class WindowSpec:
    name: str
    label: str
    start: date
    end: date           # inclusive
    prior_start: date
    prior_end: date     # inclusive


def _load_config() -> dict:
    return YAML(typ="safe").load(_CONFIG_PATH.read_text())


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    """Return (first_day, last_day) of a calendar month."""
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def _prior_month(year: int, month: int) -> tuple[int, int]:
    """Return (year, month) of the calendar month before this one."""
    if month == 1:
        return year - 1, 12
    return year, month - 1


def _iso_week_bounds(d: date) -> tuple[date, date]:
    """Return (Monday, Sunday) of the ISO week containing d."""
    monday = d - timedelta(days=d.weekday())
    return monday, monday + timedelta(days=6)


def _current_fy(today: date, fy_start_month: int) -> int:
    """Return the FY label (year of fiscal start) for today.

    Indian FY: Apr–Mar. FY2026 = Apr 2026 – Mar 2027.
    If today is Feb 2026 and FY starts in April, current FY = 2025 (Apr 2025 – Mar 2026).
    """
    if today.month >= fy_start_month:
        return today.year
    return today.year - 1


def _quarter_bounds(fy: int, q: str, quarters_cfg: dict[str, list[int]]) -> tuple[date, date]:
    """Return (start, end) of quarter q in fiscal year fy.

    quarters_cfg maps quarter name to list of calendar months, e.g. {'q4': [1,2,3]}.
    Months belonging to the *next* calendar year (q4 in Indian FY) roll forward.
    """
    months = quarters_cfg[q]
    fy_start = months[0]  # first month of this quarter
    # If quarter starts in or after FY start month, it's in the FY-start year.
    # Otherwise it's in the next calendar year (q4 case).
    quarters_starting_year = fy if fy_start >= 4 else fy + 1
    s_year = quarters_starting_year
    s_month = months[0]
    e_year = quarters_starting_year
    e_month = months[-1]
    s = date(s_year, s_month, 1)
    e_last_day = calendar.monthrange(e_year, e_month)[1]
    e = date(e_year, e_month, e_last_day)
    return s, e


def _which_quarter(today: date, quarters_cfg: dict[str, list[int]]) -> str:
    """Return the quarter name (q1/q2/q3/q4) containing today's calendar month."""
    for qname, months in quarters_cfg.items():
        if today.month in months:
            return qname
    raise RuntimeError(f"No quarter contains month {today.month} — config error")


def _prior_quarter(q: str) -> tuple[str, int]:
    """Return (prior_quarter_name, fy_offset) — fy_offset=-1 if prior is in prior FY."""
    order = ["q1", "q2", "q3", "q4"]
    i = order.index(q)
    if i == 0:
        return "q4", -1
    return order[i - 1], 0


_MONTH_NAMES = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}


def resolve_window(arg: str, today: date) -> WindowSpec:
    """Map a window arg to a concrete WindowSpec.

    Raises ValueError if arg is not in supported_windows.
    """
    cfg = _load_config()
    if arg not in cfg["supported_windows"]:
        raise ValueError(f"Unknown window: {arg!r}. See config/dashboard_windows.yaml.")

    quarters_cfg = cfg["quarters"]
    fy_start_month = cfg["fiscal_year"]["start_month"]
    current_fy = _current_fy(today, fy_start_month)

    if arg.startswith("month-"):
        name = arg[len("month-"):]
        if name not in _MONTH_NAMES:
            raise ValueError(f"Bad named-month arg: {arg!r}")
        target_month = _MONTH_NAMES[name]
        # Resolve within current FY: months in [fy_start..12] live in calendar year = fy
        #                            months in [1..fy_start-1] live in calendar year = fy + 1
        if target_month >= fy_start_month:
            target_year = current_fy
        else:
            target_year = current_fy + 1
        s, e = _month_bounds(target_year, target_month)
        # Prior period = same month in prior FY
        if target_month >= fy_start_month:
            prior_year = current_fy - 1
        else:
            prior_year = current_fy   # since prior FY's same-month is one year earlier in calendar
        ps, pe = _month_bounds(prior_year, target_month)
        return WindowSpec(
            name=arg,
            label=f"{s:%B %Y}",
            start=s, end=e,
            prior_start=ps, prior_end=pe,
        )

    # Specific quarter args (q1, q2, q3, q4) → that quarter of *current* FY
    if arg in quarters_cfg:
        s, e = _quarter_bounds(current_fy, arg, quarters_cfg)
        ps, pe = _quarter_bounds(current_fy - 1, arg, quarters_cfg)
        return WindowSpec(
            name=f"{arg}-fy{current_fy}",
            label=f"{arg.upper()} FY{current_fy} ({s:%b}–{e:%b %Y})",
            start=s, end=e,
            prior_start=ps, prior_end=pe,
        )

    if arg == "current-quarter":
        q = _which_quarter(today, quarters_cfg)
        q_fy = current_fy
        s, e = _quarter_bounds(q_fy, q, quarters_cfg)
        prior_q, fy_offset = _prior_quarter(q)
        ps, pe = _quarter_bounds(q_fy + fy_offset, prior_q, quarters_cfg)
        return WindowSpec(
            name=f"{q}-fy{q_fy}",
            label=f"{q.upper()} FY{q_fy} ({s:%b}–{e:%b %Y})",
            start=s, end=e,
            prior_start=ps, prior_end=pe,
        )

    if arg == "last-quarter":
        q_now = _which_quarter(today, quarters_cfg)
        prior_q, fy_offset = _prior_quarter(q_now)
        prior_q_fy = current_fy + fy_offset
        s, e = _quarter_bounds(prior_q_fy, prior_q, quarters_cfg)
        prior_prior_q, fy_offset2 = _prior_quarter(prior_q)
        ps, pe = _quarter_bounds(prior_q_fy + fy_offset2, prior_prior_q, quarters_cfg)
        return WindowSpec(
            name=f"{prior_q}-fy{prior_q_fy}",
            label=f"{prior_q.upper()} FY{prior_q_fy} ({s:%b}–{e:%b %Y})",
            start=s, end=e,
            prior_start=ps, prior_end=pe,
        )

    if arg == "current-week":
        s, e = _iso_week_bounds(today)
        ps = s - timedelta(days=7)
        pe = e - timedelta(days=7)
        return WindowSpec(
            name=arg,
            label=f"Week of {s:%b %-d, %Y}",
            start=s, end=e,
            prior_start=ps, prior_end=pe,
        )

    if arg == "last-week":
        cs, _ = _iso_week_bounds(today)
        s = cs - timedelta(days=7)
        e = s + timedelta(days=6)
        ps = s - timedelta(days=7)
        pe = e - timedelta(days=7)
        return WindowSpec(
            name=arg,
            label=f"Week of {s:%b %-d, %Y}",
            start=s, end=e,
            prior_start=ps, prior_end=pe,
        )

    if arg == "current-month":
        s, e = _month_bounds(today.year, today.month)
        py, pm = _prior_month(today.year, today.month)
        ps, pe = _month_bounds(py, pm)
        return WindowSpec(
            name=arg,
            label=f"{s:%B %Y}",
            start=s, end=e,
            prior_start=ps, prior_end=pe,
        )

    if arg == "last-month":
        py, pm = _prior_month(today.year, today.month)
        s, e = _month_bounds(py, pm)
        ppy, ppm = _prior_month(py, pm)
        ps, pe = _month_bounds(ppy, ppm)
        return WindowSpec(
            name=arg,
            label=f"{s:%B %Y}",
            start=s, end=e,
            prior_start=ps, prior_end=pe,
        )

    # Rolling N-day windows: last-7d, last-30d, last-60d, last-90d
    if arg.startswith("last-") and arg.endswith("d"):
        try:
            days = int(arg[5:-1])
        except ValueError:
            raise ValueError(f"Bad rolling-day arg: {arg!r}")
        end = today
        start = today - timedelta(days=days - 1)
        prior_end = start - timedelta(days=1)
        prior_start = prior_end - timedelta(days=days - 1)
        return WindowSpec(
            name=arg,
            label=f"Last {days} days ({start:%b %-d} – {end:%b %-d, %Y})",
            start=start, end=end,
            prior_start=prior_start, prior_end=prior_end,
        )

    raise NotImplementedError(f"Window {arg} not yet implemented")
