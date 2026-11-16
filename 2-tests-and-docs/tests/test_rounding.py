"""Rounding as a person does it: a half goes up, in every place the program writes a number (text, charts, both languages)."""

from __future__ import annotations

import pytest

from instatkit import i18n
from instatkit.analysis.fmt import fmt_number, fmt_pct, fmt_pp, fmt_value
from instatkit.i18n import fixed, num, plain
from instatkit.viz.svg import fmt_signed, fmt_tick, fmt_val


@pytest.mark.parametrize("x, digits, expected", [
    (6.25, 1, "6.3"), (0.125, 2, "0.13"), (2.675, 2, "2.68"), (1.005, 2, "1.01"), (0.5, 0, "1"), (1.5, 0, "2"), (2.5, 0, "3"),
    (-6.25, 1, "-6.3"), (-0.5, 0, "-1"), (6.24, 1, "6.2"), (6.26, 1, "6.3"), (999.5, 0, "1,000"), (1234567.895, 2, "1,234,567.90"),
])
def test_a_half_goes_up(x, digits, expected):
    assert fixed(x, digits) == expected


def test_it_is_the_value_as_written_that_counts_not_the_binary_float_behind_it():
    assert f"{2.675:.2f}" == "2.67"                                                       # what format() gives, because 2.675 is 2.67499999...
    assert fixed(2.675, 2) == "2.68"


def test_numbers_that_cannot_be_rounded_this_way_are_still_written():
    assert fixed(float("inf")) == "inf" and fixed(float("nan")) == "nan"
    assert fixed(1e30, 1) == f"{1e30:,.1f}"                                              # more digits than a decimal context holds
    assert fixed(5, 0) == "5" and fixed(True, 0) == "1"


def test_without_grouping():
    assert fixed(1234.565, 2, grouped=False) == "1234.57"


def test_in_english_and_in_albanian():
    assert (num(6.25, 1), plain(6.25, 1), num(1234.5, 0)) == ("6.3", "6.3", "1,235")
    with i18n.using("sq"):
        assert (num(6.25, 1), plain(6.25, 1), num(1234.5, 0)) == ("6,3", "6,3", "1\u00a0235")


def test_something_that_rounds_to_zero_has_no_sign_and_a_negative_half_keeps_it():
    assert num(-0.04, 1) == "0.0" and num(-0.05, 1) == "−0.1"


def test_the_findings_use_it():
    assert fmt_pct(6.25) == "6.3%" and fmt_pct(-2.675, 2) == "−2.68%" and fmt_pp(0.125, 2) == "0.13 pp"
    assert fmt_number(6.25) == "6.25" and fmt_number(12.25) == "12.3" and fmt_number(1000.5) == "1,001" and fmt_number(0.0125) == "0.013"
    assert fmt_value(2.5, "index") == "2.5" and fmt_value(0.125, "index", digits=2) == "0.13"
    assert fmt_value(1.25e9, "ALL") == "ALL 1.25 billion" and fmt_value(1.255e9, "ALL") == "ALL 1.26 billion"


def test_the_charts_use_it():
    assert fmt_val(2.675) == "2.68" and fmt_val(1000.5) == "1,001" and fmt_val(-0.125, "%") == "−0.13%"
    assert fmt_tick(2.5, 0) == "3" and fmt_tick(-2.5, 0) == "−3" and fmt_tick(0.04, 1) == "0.0"
    assert fmt_signed(0.125, 2) == "+0.13" and fmt_signed(-0.125, 2) == "−0.13"
