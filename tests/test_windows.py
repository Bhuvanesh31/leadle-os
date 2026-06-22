from datetime import date, timedelta

from dashboard.compute.windows import WindowSpec, resolve_window


def test_window_spec_is_frozen():
    from dataclasses import FrozenInstanceError

    spec = WindowSpec(
        name="last-7d",
        label="Last 7 days",
        start=date(2026, 5, 2),
        end=date(2026, 5, 9),
        prior_start=date(2026, 4, 25),
        prior_end=date(2026, 5, 1),
    )
    assert spec.name == "last-7d"
    with pytest.raises(FrozenInstanceError):
        spec.name = "modified"  # type: ignore[misc]


def test_resolve_window_unknown_arg_raises():
    import pytest

    with pytest.raises(ValueError, match="Unknown window"):
        resolve_window("nonsense", date(2026, 5, 9))


import pytest  # noqa: E402


@pytest.mark.parametrize(
    "arg, days",
    [
        ("last-7d", 7),
        ("last-30d", 30),
        ("last-60d", 60),
        ("last-90d", 90),
    ],
)
def test_rolling_day_windows(arg, days):
    today = date(2026, 5, 9)
    spec = resolve_window(arg, today)
    assert spec.end == today
    assert (spec.end - spec.start).days == days - 1
    # prior period = same length, ending the day before window start
    assert spec.prior_end == spec.start - timedelta(days=1)
    assert (spec.prior_end - spec.prior_start).days == days - 1


def test_current_month_window():
    spec = resolve_window("current-month", date(2026, 5, 9))
    assert spec.start == date(2026, 5, 1)
    assert spec.end == date(2026, 5, 31)
    assert spec.prior_start == date(2026, 4, 1)
    assert spec.prior_end == date(2026, 4, 30)
    assert "May 2026" in spec.label


def test_last_month_window():
    spec = resolve_window("last-month", date(2026, 5, 9))
    assert spec.start == date(2026, 4, 1)
    assert spec.end == date(2026, 4, 30)
    assert spec.prior_start == date(2026, 3, 1)
    assert spec.prior_end == date(2026, 3, 31)


def test_current_month_january_rolls_back_to_december_prior():
    spec = resolve_window("current-month", date(2026, 1, 15))
    assert spec.start == date(2026, 1, 1)
    assert spec.end == date(2026, 1, 31)
    assert spec.prior_start == date(2025, 12, 1)
    assert spec.prior_end == date(2025, 12, 31)


def test_current_week_iso_monday_to_sunday():
    # 2026-05-09 is a Saturday; ISO week is Mon May 4 – Sun May 10
    spec = resolve_window("current-week", date(2026, 5, 9))
    assert spec.start == date(2026, 5, 4)  # Monday
    assert spec.end == date(2026, 5, 10)  # Sunday
    assert spec.prior_start == date(2026, 4, 27)  # prior Monday
    assert spec.prior_end == date(2026, 5, 3)  # prior Sunday


def test_last_week_iso():
    spec = resolve_window("last-week", date(2026, 5, 9))
    assert spec.start == date(2026, 4, 27)
    assert spec.end == date(2026, 5, 3)
    assert spec.prior_start == date(2026, 4, 20)
    assert spec.prior_end == date(2026, 4, 26)


@pytest.mark.parametrize(
    "today, arg, expected_start, expected_end, expected_label_contains",
    [
        # Today in May 2026 → FY2026 (Apr 2026 – Mar 2027) is current FY
        (date(2026, 5, 9), "q1", date(2026, 4, 1), date(2026, 6, 30), "Q1 FY2026"),
        (date(2026, 5, 9), "q2", date(2026, 7, 1), date(2026, 9, 30), "Q2 FY2026"),
        (date(2026, 5, 9), "q3", date(2026, 10, 1), date(2026, 12, 31), "Q3 FY2026"),
        (date(2026, 5, 9), "q4", date(2027, 1, 1), date(2027, 3, 31), "Q4 FY2026"),
        (date(2026, 5, 9), "current-quarter", date(2026, 4, 1), date(2026, 6, 30), "Q1 FY2026"),
        (date(2026, 5, 9), "last-quarter", date(2026, 1, 1), date(2026, 3, 31), "Q4 FY2025"),
        # Today in Feb 2026 → FY2025 (Apr 2025 – Mar 2026) is current FY
        (date(2026, 2, 15), "current-quarter", date(2026, 1, 1), date(2026, 3, 31), "Q4 FY2025"),
        (date(2026, 2, 15), "q1", date(2025, 4, 1), date(2025, 6, 30), "Q1 FY2025"),
        # Today on FY boundary
        (date(2026, 4, 1), "current-quarter", date(2026, 4, 1), date(2026, 6, 30), "Q1 FY2026"),
        (date(2026, 3, 31), "current-quarter", date(2026, 1, 1), date(2026, 3, 31), "Q4 FY2025"),
    ],
)
def test_quarter_resolution(today, arg, expected_start, expected_end, expected_label_contains):
    spec = resolve_window(arg, today)
    assert spec.start == expected_start
    assert spec.end == expected_end
    assert expected_label_contains in spec.label


@pytest.mark.parametrize(
    "today, arg, expected_year, expected_month",
    [
        # Today in May 2026 (FY2026)
        (date(2026, 5, 9), "month-april", 2026, 4),  # FY2026's April = Apr 2026
        (date(2026, 5, 9), "month-may", 2026, 5),
        (date(2026, 5, 9), "month-march", 2027, 3),  # FY2026's March = Mar 2027
        (date(2026, 5, 9), "month-january", 2027, 1),
        # Today in Feb 2026 (FY2025)
        (date(2026, 2, 15), "month-april", 2025, 4),  # FY2025's April = Apr 2025
        (date(2026, 2, 15), "month-march", 2026, 3),  # FY2025's March = Mar 2026
    ],
)
def test_named_month_resolves_within_current_fy(today, arg, expected_year, expected_month):
    spec = resolve_window(arg, today)
    assert spec.start.year == expected_year
    assert spec.start.month == expected_month
    assert spec.start.day == 1
