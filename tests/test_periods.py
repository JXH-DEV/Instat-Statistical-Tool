"""Period parsing: the many ways INSTAT writes a month, quarter or year."""

from __future__ import annotations

import time
from datetime import date

import pytest

from instatkit.semantics.periods import (
    add_periods,
    from_label,
    infer_date_freq,
    make_month,
    missing_periods,
    parse_period,
)


@pytest.mark.parametrize("text, label, freq", [
    (" 01-17", "2017-01", "M"),                  # a leading space and a two-digit year, as INSTAT writes them
    ("12 - 21", "2021-12", "M"),
    ("2 - 22", "2022-02", "M"),                  # unpadded in the same row
    ("03.2024", "2024-03", "M"),
    ("Janar 2024", "2024-01", "M"),
    ("Nëntor 2023", "2023-11", "M"),
    ("Jan-24", "2024-01", "M"),
    ("Tr.1.2023 Q1.2023", "2023-Q1", "Q"),       # Albanian and English label in one cell
    ("Q2 2024", "2024-Q2", "Q"),
    ("Tr. II 2023", "2023-Q2", "Q"),
    ("tremujori i dytë 2023", "2023-Q2", "Q"),
    ("3 tremujor 2023", "2023-Q3", "Q"),
    ("H1 2023", "2023-H1", "H"),
    ("2023 H2", "2023-H2", "H"),
    ("2025", "2025", "A"),
    ("Viti 2023", "2023", "A"),
    ("2019-2023", "2019-2023", "R"),
    ("2019/20", "2019-2020", "R"),
    ("1999/00", "1999-2000", "R"),               # crosses the century
])
def test_recognised_forms(text, label, freq):
    p = parse_period(text)
    assert p is not None, text
    assert (p.label, p.freq) == (label, freq)


def test_provisional_marker():
    p = parse_period("2025*")
    assert p.label == "2025" and p.provisional
    assert parse_period("2024 (p)").provisional
    assert not parse_period("2024").provisional


def test_value_period_with_comparison_base():
    p = parse_period(" 01-17  01-16")
    assert p.label == "2017-01"
    assert p.base is not None and p.base.label == "2016-01"


def test_numeric_and_date_cells():
    assert parse_period(2023).label == "2023"
    assert parse_period(2023.0).label == "2023"
    assert parse_period(7) is None and parse_period(12345) is None
    assert parse_period(date(2024, 3, 31), hint="M").label == "2024-03"
    assert parse_period(True) is None and parse_period(None) is None


@pytest.mark.parametrize("text", [
    "5 tremujor 2023",      # there is no fifth quarter
    "0 tremujor 2023",
    "01-0000",              # year 0
    "12.0000",
    "5-1000",               # a class interval, not May of the year 1000
    "1-1999999",
    "Total", "", "   ", "n/a", "13-2020", "Q5 2020",
])
def test_not_a_period(text):
    assert parse_period(text) is None


def test_comparison_year_is_not_a_hundred_year_range():
    p = parse_period("2025/24")                  # not the range 2025-2124
    assert p.label == "2025" and p.base is not None and p.base.label == "2024"
    p = parse_period("2024/2023")
    assert p.label == "2024" and p.base.label == "2023"
    assert parse_period("2024/25").label == "2024-2025"


def test_asterisk_runs_do_not_blow_up():
    """A long run of asterisks is parsed in linear time."""
    for stars in (24, 40, 59):
        t0 = time.perf_counter()
        assert parse_period("2020" + "*" * stars + "x") is None
        parse_period("2020" + "*" * stars)
        assert time.perf_counter() - t0 < 0.5, stars


def test_canonical_labels_round_trip_without_guessing():
    """2005-06 is June 2005 in a canonical label; parse_period must guess because a header can mean the school year."""
    for y in range(2000, 2012):
        label = f"{y}-{(y + 1) % 100:02d}"
        p = from_label(label)
        assert p.freq == "M" and p.label == label, label
    assert parse_period("2005-06").freq == "R"            # the documented guess for a header cell
    assert parse_period("2005-06", hint="M").freq == "M"
    for label, freq in [("2023-Q1", "Q"), ("2024-H2", "H"), ("2025", "A"), ("2019-2023", "R"), ("2024-03-31", "D")]:
        assert from_label(label).freq == freq


def test_monthly_run_through_a_school_year_look_alike_has_no_gaps():
    months = [from_label(f"{y}-{m:02d}") for y in range(2004, 2007) for m in range(1, 13)]
    assert all(p.freq == "M" for p in months)
    assert missing_periods(months) == []


def test_add_periods_and_gaps():
    p = make_month(2023, 11)
    assert add_periods(p, 3).label == "2024-02"
    assert add_periods(p, -11).label == "2022-12"
    present = [make_month(2023, m) for m in (1, 2, 4, 5)]
    assert [g.label for g in missing_periods(present)] == ["2023-03"]


def test_infer_date_freq():
    assert infer_date_freq([date(2023, m, 1) for m in (1, 2, 3, 4)]) == "M"
    assert infer_date_freq([date(2023, 3, 31), date(2023, 6, 30), date(2023, 9, 30)]) == "Q"
    assert infer_date_freq([date(2023, 3, 14), date(2023, 6, 2)]) is None


def test_year_dash_digit_is_a_quarter_only_with_a_quarter_hint():
    assert parse_period("2018-3").label == "2018-03"                        # alone, it is March
    assert parse_period("2018-3", hint="Q").label == "2018-Q3"
    assert parse_period("2018-12", hint="Q").label == "2018-12"             # two digits cannot be a quarter


@pytest.mark.parametrize("text, label", [
    ("II/23", "2023-Q2"), ("III/23", "2023-Q3"), ("I/24", "2024-Q1"), ("IV/25", "2025-Q4"),   # INSTAT's wage table: the columns of 13 quarters
    ("II/2023", "2023-Q2"), ("II-2023", "2023-Q2"), ("IV 2023", "2023-Q4"), ("I.2024", "2024-Q1"),
    ("2023/II", "2023-Q2"), ("2024-IV", "2024-Q4"),
    ("T.II-23", "2023-Q2"), ("Quarter II 2026", "2026-Q2"), ("Tremujori II 2024", "2024-Q2"),
])
def test_quarters_written_as_roman_numerals(text, label):
    p = parse_period(text)
    assert p is not None and (p.label, p.freq) == (label, "Q")


@pytest.mark.parametrize("text", ["II", "IV", "I", "III", "II/", "V 2023", "VI/23", "XI/23", "I/2", "I - II", "Total"])
def test_a_roman_numeral_alone_or_a_non_quarter_is_not_a_period(text):
    assert parse_period(text) is None, "a numbered row label must not turn into a period"
