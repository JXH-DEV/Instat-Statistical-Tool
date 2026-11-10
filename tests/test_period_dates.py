"""The first and last day of every kind of period, which end up in the ``period_start`` and ``period_end`` columns of every export."""

from __future__ import annotations

from datetime import date

import pytest

from instatkit.semantics.periods import (
    add_periods,
    from_label,
    make_day,
    make_half,
    make_month,
    make_quarter,
    make_range,
    make_year,
    parse_period,
)

D = date


@pytest.mark.parametrize("period, label, start, end", [
    (make_month(2023, 1), "2023-01", D(2023, 1, 1), D(2023, 1, 31)),
    (make_month(2023, 2), "2023-02", D(2023, 2, 1), D(2023, 2, 28)),
    (make_month(2024, 2), "2024-02", D(2024, 2, 1), D(2024, 2, 29)),            # a leap year
    (make_month(2023, 4), "2023-04", D(2023, 4, 1), D(2023, 4, 30)),
    (make_month(2023, 12), "2023-12", D(2023, 12, 1), D(2023, 12, 31)),
    (make_quarter(2023, 1), "2023-Q1", D(2023, 1, 1), D(2023, 3, 31)),
    (make_quarter(2023, 2), "2023-Q2", D(2023, 4, 1), D(2023, 6, 30)),
    (make_quarter(2023, 3), "2023-Q3", D(2023, 7, 1), D(2023, 9, 30)),
    (make_quarter(2023, 4), "2023-Q4", D(2023, 10, 1), D(2023, 12, 31)),
    (make_half(2023, 1), "2023-H1", D(2023, 1, 1), D(2023, 6, 30)),
    (make_half(2023, 2), "2023-H2", D(2023, 7, 1), D(2023, 12, 31)),
    (make_year(2023), "2023", D(2023, 1, 1), D(2023, 12, 31)),
    (make_range(2019, 2023), "2019-2023", D(2019, 1, 1), D(2023, 12, 31)),
    (make_day(D(2024, 3, 31)), "2024-03-31", D(2024, 3, 31), D(2024, 3, 31)),
])
def test_first_and_last_day(period, label, start, end):
    assert (period.label, period.start, period.end) == (label, start, end)
    assert period.year == start.year and period.sort_key == (start, end)


@pytest.mark.parametrize("text, start, end", [
    (" 01-17", D(2017, 1, 1), D(2017, 1, 31)),
    ("Shkurt 2024", D(2024, 2, 1), D(2024, 2, 29)),
    ("2024 March", D(2024, 3, 1), D(2024, 3, 31)),                 # the year first
    ("2023 Nëntor", D(2023, 11, 1), D(2023, 11, 30)),
    ("Tr. II 2023", D(2023, 4, 1), D(2023, 6, 30)),
    ("2023 Q4", D(2023, 10, 1), D(2023, 12, 31)),
    ("2023/III", D(2023, 7, 1), D(2023, 9, 30)),
    ("H2 2023", D(2023, 7, 1), D(2023, 12, 31)),
    ("S1 2022", D(2022, 1, 1), D(2022, 6, 30)),
    ("2025", D(2025, 1, 1), D(2025, 12, 31)),
    ("2019/20", D(2019, 1, 1), D(2020, 12, 31)),
    ("1999/00", D(1999, 1, 1), D(2000, 12, 31)),
    ("2024/2023", D(2024, 1, 1), D(2024, 12, 31)),                 # a year and its comparison base: the year itself
])
def test_parsed_text_has_the_right_dates(text, start, end):
    p = parse_period(text)
    assert p is not None and (p.start, p.end) == (start, end)


@pytest.mark.parametrize("text, quarter", [
    ("first quarter 2023", 1), ("1st quarter 2023", 1), ("I quarter 2023", 1), ("tremujori i parë 2023", 1), ("tremujori i pare 2023", 1),
    ("second quarter 2023", 2), ("2nd quarter 2023", 2), ("II quarter 2023", 2), ("tremujori i dytë 2023", 2), ("tremujori i dyte 2023", 2),
    ("third quarter 2023", 3), ("3rd quarter 2023", 3), ("III quarter 2023", 3), ("tremujori i tretë 2023", 3), ("tremujori i trete 2023", 3),
    ("fourth quarter 2023", 4), ("4th quarter 2023", 4), ("IV quarter 2023", 4), ("tremujori i katërt 2023", 4), ("tremujori i katert 2023", 4),
    ("1 tremujor 2023", 1), ("2 tremujor 2023", 2), ("3 tremujor 2023", 3), ("4 tremujor 2023", 4),
    ("fourth quarter of 2023", 4),
])
def test_every_way_of_naming_a_quarter(text, quarter):
    p = parse_period(text)
    assert p is not None and p.label == f"2023-Q{quarter}" and p.start == D(2023, 3 * quarter - 2, 1)


@pytest.mark.parametrize("start_label, steps, label, start, end", [
    ("2023-11", 3, "2024-02", D(2024, 2, 1), D(2024, 2, 29)),
    ("2023-01", -1, "2022-12", D(2022, 12, 1), D(2022, 12, 31)),
    ("2023-Q4", 1, "2024-Q1", D(2024, 1, 1), D(2024, 3, 31)),
    ("2023-Q1", -1, "2022-Q4", D(2022, 10, 1), D(2022, 12, 31)),
    ("2023-Q2", 5, "2024-Q3", D(2024, 7, 1), D(2024, 9, 30)),
    ("2023-H2", 1, "2024-H1", D(2024, 1, 1), D(2024, 6, 30)),
    ("2023-H1", -1, "2022-H2", D(2022, 7, 1), D(2022, 12, 31)),
    ("2023-H1", 3, "2024-H2", D(2024, 7, 1), D(2024, 12, 31)),
    ("2023", 2, "2025", D(2025, 1, 1), D(2025, 12, 31)),
    ("2023", -3, "2020", D(2020, 1, 1), D(2020, 12, 31)),
    ("2024-02-28", 2, "2024-03-01", D(2024, 3, 1), D(2024, 3, 1)),     # over the 29th of February
    ("2024-03-01", -1, "2024-02-29", D(2024, 2, 29), D(2024, 2, 29)),
])
def test_stepping_forwards_and_backwards(start_label, steps, label, start, end):
    p = add_periods(from_label(start_label), steps)
    assert (p.label, p.start, p.end) == (label, start, end)


def test_a_multi_year_range_cannot_be_stepped():
    with pytest.raises(ValueError):
        add_periods(make_range(2019, 2023), 1)


# --- the edges of what counts as a date ---
@pytest.mark.parametrize("text, label", [
    ("01.01.2020", "2020-01-01"), ("2020-01-01", "2020-01-01"), ("31/12/2020", "2020-12-31"), ("2020-12-31", "2020-12-31"),
    ("2020-01-31", "2020-01-31"), ("29.02.2020", "2020-02"), ("2020-03-01", "2020-03"), ("2020-03-15", "2020-03-15"), ("15-03-2020", "2020-03-15"),
])
def test_a_date_is_a_day_unless_it_is_the_first_or_last_of_a_mid_year_month(text, label):
    assert parse_period(text).label == label


@pytest.mark.parametrize("text", ["29.02.2021", "2021-02-29", "31.04.2020", "2020-13-01", "13.13.2020", "2020-00-10", "00.01.2020", "2020-01-00", "32.01.2020"])
def test_a_date_that_does_not_exist_is_not_a_period(text):
    assert parse_period(text) is None


@pytest.mark.parametrize("text, label", [
    ("1999/00", "1999-2000"), ("1999-00", "1999-2000"), ("1998/99", "1998-1999"), ("2019/20", "2019-2020"), ("1950/51", "1950-1951"),
    ("1980/00", "1980-2000"),                                                           # twenty years: the longest a two-digit end may reach
    ("2019-2023", "2019-2023"),
])
def test_year_ranges_with_a_two_digit_end_may_cross_a_century(text, label):
    assert parse_period(text).label == label


@pytest.mark.parametrize("text", ["2005-00", "1979/00", "2023/2023"])
def test_a_range_that_would_run_backwards_or_for_decades_is_not_one(text):
    assert parse_period(text) is None


@pytest.mark.parametrize("text, year, base", [("2024/2023", 2024, 2023), ("2025/24", 2025, 2024)])
def test_a_year_compared_with_the_year_before_is_that_year(text, year, base):
    p = parse_period(text)
    assert (p.label, p.freq, p.base.label) == (str(year), "A", str(base))


@pytest.mark.parametrize("value, label", [(1800, "1800"), (2200, "2200"), (2023.0, "2023"), ("1900", "1900"), ("2099", "2099"), ("1900-05", "1900-05")])
def test_the_limits_of_what_is_a_year(value, label):
    assert parse_period(value).label == label


@pytest.mark.parametrize("value", [1799, 2201, 2023.5, "1899", "2100", "5-1000"])
def test_a_number_outside_the_years_is_not_a_period(value):
    assert parse_period(value) is None


@pytest.mark.parametrize("text", ["Sept 2023", "Sept-23", "sep 2023", "Shtator 2023", "Sep. 2023"])
def test_september_in_every_spelling(text):
    p = parse_period(text)
    assert (p.label, p.freq) == ("2023-09", "M")


# --- a month written with its comparison base, and a date read as a period ---
@pytest.mark.parametrize("text", ["2024-03/2023-03", "2024-3 / 2023-3", "2024.03-2023.03", "03-2024/03-2023"])
def test_a_month_and_its_comparison_base_in_one_cell_are_the_month_and_its_base(text):
    p = parse_period(text)
    assert (p.label, p.freq, p.base.label) == ("2024-03", "M", "2023-03")


@pytest.mark.parametrize("text", ["2024-13/2023-03", "2024-03/2023-13", "2024-03 2023-03 2022-03", "2024-00/2023-03"])
def test_a_pair_that_is_not_two_months_is_not_a_period_with_a_base(text):
    p = parse_period(text)
    assert p is None or p.base is None


@pytest.mark.parametrize("month, quarter", [(1, 1), (2, 1), (3, 1), (4, 2), (5, 2), (6, 2), (7, 3), (8, 3), (9, 3), (10, 4), (11, 4), (12, 4)])
def test_a_date_under_a_quarterly_header_is_in_its_quarter(month, quarter):
    assert parse_period(D(2024, month, 15), hint="Q").label == f"2024-Q{quarter}"


def test_a_date_is_a_month_a_year_or_a_day_as_the_header_says():
    assert parse_period(D(2024, 3, 31), hint="M").label == "2024-03"
    assert parse_period(D(2024, 3, 31), hint="A").label == "2024"
    assert parse_period(D(2024, 3, 31)).label == "2024-03"                              # a month-end with nothing else to go on is the month
    assert parse_period(D(2024, 3, 15)).label == "2024-03-15"
    assert parse_period(D(2024, 1, 31)).label == "2024-01-31" and parse_period(D(2024, 12, 1)).label == "2024-12-01"          # January and December: ambiguous
