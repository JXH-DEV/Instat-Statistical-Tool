"""The tool that compares the program with the figures INSTAT states in its press releases: how it reads those figures and how it judges them.
(The comparison itself needs the internet; these tests need nothing.)"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "tools" / "check_published.py"


@pytest.fixture(scope="module")
def tool():
    spec = importlib.util.spec_from_file_location("instat_check_published", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # a dataclass looks its module up here
    spec.loader.exec_module(module)
    yield module
    del sys.modules[spec.name]


@pytest.mark.parametrize("text, value, decimals", [("+0.96", 0.96, 2), ("2,648,505", 2648505.0, 0), ("−3.1", -3.1, 1), ("12.14", 12.14, 2), ("0. 5", 0.5, 1)])
def test_published_numbers_are_read_with_their_precision(tool, text, value, decimals):
    assert tool.to_number(text) == (value, decimals)


def test_the_defects_of_pdf_text_are_repaired(tool):
    cleaned = tool.clean_pdf_text("contribution of +0. 54 percentage points, +0.9 6\npercentage points, “Food and non -alcoholic beverages” 2.8 %. Next 2.9 2025")
    assert "+0.54 percentage" in cleaned and "+0.96 percentage" in cleaned and "non-alcoholic" in cleaned
    assert "2.9 2025" in cleaned, "a number followed by a year is not glued together"


def test_names_are_compared_by_their_letters_only(tool):
    assert tool.norm("Alcoholic beverages. tobacco and narcotics") == tool.norm("Alcoholic beverages, tobacco and narcotics")


def test_the_table_of_the_consumer_price_release_is_read(tool):
    raw = ("TAB. 1 CONSUMER PRICE INDEX\nCode Divisions\n  Gjithsej 100.0 103.4 0.4 2.9 \n01. Food and non-alcoholic beverages 34.1 102.4 0.8 2.8 \n"
           "03. Clothing and footwear 3.8 97.2 1.1 -3.1 \n04. Housing. water. electricity. gas and other fuels 20.2 104.6 0.0 2.7 \nNote to users:\n")
    rows = tool.cpi_table_rows(raw)
    assert rows["total"] == (100.0, 103.4, 0.4, 2.9)
    assert rows[tool.norm("Clothing and footwear")] == (3.8, 97.2, 1.1, -3.1)
    assert rows[tool.norm("Housing, water, electricity, gas and other fuels")] == (20.2, 104.6, 0.0, 2.7)


def test_a_change_is_read_with_its_sign_from_the_sentence(tool):
    text = "“Construction” activity increased by 1.37 %. The group of “Agriculture, Forestry and Fishing” activity decreased by 2.29 %."
    assert tool.growth_after(text, "Construction")[:2] == (1.37, 2)
    assert tool.growth_after(text, "Agriculture, Forestry and Fishing")[:2] == (-2.29, 2)
    assert tool.growth_after(text, "Mining") is None


def test_a_figure_matches_when_it_rounds_to_the_published_one(tool):
    assert tool.judge(2.9, 1, 2.9236) == "match" and tool.judge(2.9, 1, 2.96) == "differ" and tool.judge(0.4, 1, 0.376) == "match"


def test_a_change_worked_out_from_rounded_levels_is_recognised(tool):
    """8.5 -> 8.3 is published as -0.2; the unrounded levels (8.536 -> 8.275) give -0.26."""
    assert tool.judge(-0.2, 1, -0.2604) == "differ"
    assert tool.judge(-0.2, 1, -0.2604, rounded_levels=-0.2) == "match (rounded levels)"


def test_approximate_figure_is_close_only_within_tolerance(tool):
    assert tool.judge(0.81, 2, 0.795, approx=0.02) == "close"
    assert tool.judge(0.81, 2, 0.75, approx=0.02) == "differ"
    assert tool.judge(0.81, 2, 0.81) == "match"


def test_a_figure_that_cannot_be_found_is_reported_not_skipped(tool):
    ctx = tool.Context(fetcher=None, only=None)
    ctx.add("group", "something", None, 1.0)
    ctx.add("group", "something else", (1.0, 1), None)
    assert [r.verdict for r in ctx.rows] == ["missing", "missing"]


def test_percentage_changes_need_two_numbers(tool):
    assert tool.pct_change(110, 100) == pytest.approx(10.0)
    assert tool.pct_change(None, 100) is None and tool.pct_change(1, 0) is None
