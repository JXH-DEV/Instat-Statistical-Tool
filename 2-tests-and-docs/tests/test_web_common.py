"""What the web layer accepts from the page (whole numbers) and how it writes replies (valid JSON whatever the values are)."""

from __future__ import annotations

import json
import math
from datetime import date, datetime
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from instatkit import i18n
from instatkit.web.common import ApiError, dumps, whole_number


def strict(token):
    raise AssertionError(f"not JSON: {token}")


def back(obj):
    return json.loads(dumps(obj), parse_constant=strict)


# --- whole numbers from the page ---
@pytest.mark.parametrize("value,expected", [(5, 5), ("5", 5), (" 7 ", 7), (-3, -3), ("-3", -3), (4.0, 4), ("0", 0), (0, 0), (1e3, 1000)])
def test_whole_numbers_are_accepted_in_every_form_the_page_may_send(value, expected):
    assert whole_number(value, "Page") == expected


@pytest.mark.parametrize("value", ["", "abc", "1.5", 1.5, True, False, None, [], {}, "1e3", float("nan"), float("inf")])
def test_anything_else_is_refused_with_the_name_of_the_field(value):
    with pytest.raises(ApiError) as caught:
        whole_number(value, "Page")
    assert str(caught.value) == "Page must be a whole number." and caught.value.status == 400


def test_a_minimum_is_enforced_and_named():
    assert whole_number(3, "Page", minimum=3) == 3
    with pytest.raises(ApiError) as caught:
        whole_number(2, "Page", minimum=3)
    assert str(caught.value) == "Page must be 3 or more."
    assert whole_number(-5, "Offset") == -5                                                  # without a minimum, negative is allowed


def test_the_refusal_is_in_the_language_of_the_page():
    with i18n.using("sq"), pytest.raises(ApiError) as caught:
        whole_number("x", "Faqja")
    assert "must be a whole number" not in str(caught.value) and "Faqja" in str(caught.value)


def test_an_error_has_a_status_the_server_can_use():
    assert ApiError("x").status == 400 and ApiError("x", 404).status == 404 and str(ApiError("x", 404)) == "x"


# --- replies ---
def test_numpy_numbers_become_plain_json_numbers():
    assert back({"i": np.int64(3), "f": np.float32(2.5), "b": np.bool_(True), "u": np.uint8(7)}) == {"i": 3, "f": 2.5, "b": True, "u": 7}


def test_dates_and_timestamps_are_written_as_iso_text():
    assert back({"d": date(2024, 3, 1), "t": datetime(2024, 3, 1, 12, 30), "p": pd.Timestamp("2024-03-01")}) == {
        "d": "2024-03-01", "t": "2024-03-01T12:30:00", "p": "2024-03-01T00:00:00"}


def test_sets_become_lists_and_other_objects_become_text():
    assert back({"s": {"only"}, "f": frozenset({1}), "x": Decimal("1.50"), "o": object}) == {
        "s": ["only"], "f": [1], "x": "1.50", "o": "<class 'object'>"}


def test_albanian_letters_are_written_as_they_are_not_as_escapes():
    assert dumps({"k": "ë ç"}) == '{"k":"ë ç"}'.encode()


def test_a_nan_inside_a_set_a_tuple_or_a_numpy_scalar_becomes_null():
    assert back({"a": (1.0, float("nan")), "b": np.float64("inf"), "c": [np.float32("nan")], "d": {"e": (float("-inf"),)}}) == {
        "a": [1.0, None], "b": None, "c": [None], "d": {"e": [None]}}


def test_the_reply_is_compact():
    assert dumps({"a": [1, 2], "b": {"c": None}}) == b'{"a":[1,2],"b":{"c":null}}'


def test_a_number_that_is_not_finite_is_never_written_as_nan_or_infinity():
    for bad in (float("nan"), float("inf"), -math.inf):
        out = dumps({"x": bad}).decode()
        assert out == '{"x":null}'
