"""What a cell's content means as a number: real numbers, numbers typed as text in several conventions, the markers INSTAT uses for
"no value", and the things that look like numbers but are codes. Every row is a case that was run and judged by eye once."""

from __future__ import annotations

import datetime
import math

import pytest

from instatkit.semantics.numbers import Num, looks_numeric, parse_number


@pytest.mark.parametrize("value, expected", [
    (None, Num(None)), (True, Num(None)), (False, Num(None)),
    (5, Num(5.0)), (0, Num(0.0)), (-3, Num(-3.0)), (5.5, Num(5.5)), (-0.25, Num(-0.25)),
    (float("nan"), Num(None, "na")), (float("inf"), Num(None, "na")), (float("-inf"), Num(None, "na")),
    (datetime.date(2020, 1, 1), Num(None, "text")), (datetime.datetime(2020, 1, 1, 12), Num(None, "text")),
    ("", Num(None)), ("   ", Num(None)),
])
def test_values_that_are_not_text(value, expected):
    assert parse_number(value) == expected


@pytest.mark.parametrize("text, value", [
    ("0", 0.0), ("5", 5.0), ("+5", 5.0), ("-5", -5.0), ("−5", -5.0), ("–5", -5.0), ("0.5", 0.5), (".5", 0.5), (",5", 0.5), ("0,5", 0.5),
    ("1 234,5", 1234.5), ("1 000", 1000.0), (" 1 000 ", 1000.0),
    ("1,234", 1234.0), ("1.234", 1.234), ("1,234.5", 1234.5), ("1.234,5", 1234.5), ("12,345,678", 12345678.0), ("1.234.567", 1234567.0),
    ("1e3", 1000.0), ("1E-2", 0.01), ("1.5e3", 1500.0),
    ("(12)", -12.0), ("(12,5)", -12.5),                                           # an accountant's negative
])
def test_numbers_typed_as_text(text, value):
    n = parse_number(text)
    assert n.value == pytest.approx(value) and n.flag is None and not n.is_marker


@pytest.mark.parametrize("text, value, flag", [
    ("123p", 123.0, "p"), ("45 e", 45.0, "e"), ("12 (p)", 12.0, "p"), ("12*", 12.0, "p"), ("12**", 12.0, "p"), ("5 sf", 5.0, "p"), ("12r", 12.0, "r"),
])
def test_a_status_letter_after_the_number_is_kept_as_a_flag(text, value, flag):
    n = parse_number(text)
    assert (n.value, n.flag) == (value, flag)


@pytest.mark.parametrize("text, flag", [
    ("..", "na"), ("...", "na"), ("…", "na"), ("n/a", "na"), ("N/A", "na"), ("#DIV/0!", "na"), (":", "na"),
    ("-", "nil"), ("—", "nil"), ("--", "nil"),
    ("x", "suppressed"), ("C", "suppressed"), ("(c)", "suppressed"), ("conf.", "suppressed"),
    ("*", "note"), ("**", "note"),
])
def test_markers_for_no_value_say_why(text, flag):
    n = parse_number(text)
    assert (n.value, n.flag, n.is_marker) == (None, flag, True)


@pytest.mark.parametrize("text", [
    "00", "07", "000000", "01.1", "01.", "5.", "12.", "1.", "1.2.3", "1,2,3", "1,234.567.8", "abc", "12abc", "1e999", "-1e999", "- 5 -", "1_000", "infinity", "nan",
])
def test_codes_and_malformed_numbers_are_text_and_never_a_value(text):
    n = parse_number(text)
    assert (n.value, n.flag) == (None, "text")


def test_a_percent_sign_is_a_unit_hint_not_part_of_the_value():
    assert parse_number("12,5%") == Num(12.5, None, "%")
    assert parse_number("12.5 %") == Num(12.5, None, "%")
    assert parse_number("12.5").unit_hint is None


def test_the_decimal_mark_can_be_forced():
    assert parse_number("1,234", decimal=",").value == pytest.approx(1.234)
    assert parse_number("1.234", decimal=".").value == pytest.approx(1.234)
    assert parse_number("1.234", decimal=",").value == pytest.approx(1234.0)
    assert parse_number("1,234", decimal=".").value == pytest.approx(1234.0)


def test_no_number_comes_back_as_nan_or_infinity():
    for text in ["1e999", "nan", "inf", "-inf", "1e-999x"]:
        v = parse_number(text).value
        assert v is None or math.isfinite(v), text
    assert parse_number(1e308 * 10).value is None


@pytest.mark.parametrize("value, answer", [
    (5, True), (5.5, True), ("12", True), ("1 234,5", True), ("12*", True), ("(12)", True),
    ("..", True), ("-", True), ("x", True), ("abc", False), ("", False), (None, False), (True, False), ("000", False),
])
def test_looks_numeric(value, answer):
    assert looks_numeric(value) is answer


@pytest.mark.parametrize("text, value", [("(5%)", -5.0), ("(5 %)", -5.0), ("(12,5%)", -12.5), ("5%", 5.0), ("−5 %", -5.0)])
def test_a_percentage_in_brackets_is_negative_like_any_number_in_brackets(text, value):
    n = parse_number(text)
    assert (n.value, n.unit_hint) == (pytest.approx(value), "%")


@pytest.mark.parametrize("text", ["(5%", "5%)", "(%)", "(a%)", "()", "(5)%x"])
def test_unbalanced_or_empty_brackets_are_text(text):
    assert parse_number(text).value is None


@pytest.mark.parametrize("text, value, hint", [("(-5)", -5.0, None), ("(\u22125)", -5.0, None), ("(- 5)", -5.0, None), ("(-12,5)", -12.5, None),
                                               ("(-5%)", -5.0, "%"), ("(+5)", -5.0, None)])
def test_a_negative_in_brackets_is_negative_once(text, value, hint):
    """Brackets and a minus sign both say 'negative'; the number is -5, not the negative of -5."""
    n = parse_number(text)
    assert (n.value, n.unit_hint) == (pytest.approx(value), hint)


@pytest.mark.parametrize("text", ["(--5)", "(-+5)", "(- -5)", "(-)", "(-a)"])
def test_signs_that_contradict_each_other_are_not_a_number(text):
    assert parse_number(text).value is None


@pytest.mark.parametrize("text, flag", [("12*", "p"), ("12 *", "p"), ("12 (p)", "p"), ("12 p", "p"), ("12 sf", "p"), ("12(e)", "e"), ("12 r", "r")])
def test_a_provisional_mark_is_a_flag_of_its_own_whichever_way_it_is_written(text, flag):
    n = parse_number(text)
    assert (n.value, n.flag) == (12.0, flag)


@pytest.mark.parametrize("text, decimal, expected", [
    ("1.2.3", None, None), ("1.2.3", ",", None), ("1.2.3.4", None, None), ("1,2,3", None, None), ("1,2,3", ",", None), ("1.2", None, "1.2"),
    ("1.234", None, "1.234"), ("1.234", ".", "1.234"), ("1.234", ",", "1234"), ("1.234.567", None, "1234567"), ("1,234", None, "1234"),
    ("1,234", ",", "1.234"), ("0,500", None, "0.500"), ("1,234.5", None, "1234.5"), ("1.234,5", None, "1234.5"), ("1.2.3,4", None, None),
    ("1,234,5", None, None), ("12,5", None, "12.5"), ("1,5e3", None, "1.5e3"),
])
def test_the_separators_of_a_number_are_told_apart(text, decimal, expected):
    from instatkit.semantics.numbers import _decimal_string

    assert _decimal_string(text, decimal) == expected
