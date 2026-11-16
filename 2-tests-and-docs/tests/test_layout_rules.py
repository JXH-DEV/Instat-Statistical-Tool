"""The small decisions inside the layout reader, one at a time: what kind of row a row is, what a unit line is, how a code, an indentation or a
header pair is read, when a breakdown ends, and what happens when the user forces a layout. Each case is made here so the right answer is known;
the boundaries (one more cell, one less) are the point."""

from __future__ import annotations

import datetime
from types import SimpleNamespace

import pytest

from instatkit import config, demo
from instatkit.excel import grid as grid_mod
from instatkit.excel import layout as L
from instatkit.excel.grid import Grid
from instatkit.excel.layout import ColumnSpec, Overrides, RowSpec
from instatkit.excel.tidy import extract_tables
from instatkit.export.xlsx_writer import Workbook as Writer
from instatkit.semantics.periods import parse_period


def tables(data, overrides=None):
    return extract_tables(grid_mod.read_workbook(data, "t.xlsx"), overrides=overrides).tables


def one_table(data, overrides=None):
    found = tables(data, overrides)
    assert len(found) == 1
    return found[0]


# --- the kind of a row ---
@pytest.mark.parametrize("cells, kind", [
    ([None, None], "E"),
    (["Population of Albania"], "T"), ([5.5], "S"), (["12"], "S"),
    (["Albania", 5.5], "D"),                                        # one number in two cells: density 0.5
    (["Albania", "Tirana", 5.5], "H"),                              # one number in three is a header with a stray number
    (["Albania", 5.5, 6.5], "D"),
    (["alpha", "beta", "gamma", 5.5, 6.5], "D"),                    # two in five: 0.4
    (["alpha", "beta", "gamma", "delta", "epsilon", "zeta", 5.5, 6.5], "H"),   # two in eight: 0.25
    (["alpha", "beta", "gamma", "delta", 5.5, 6.5], "H"),           # two in six: 0.33 is below the 0.34 line
    (["alpha", "beta", "gamma", 5.5, 6.5, 7.5], "D"),
    ([2020, 2021, 2022], "Y"), (["Region", 2023, 2024], "Y"), ([1, 2, 3, 4], "A"),
])
def test_the_kind_of_a_row(cells, kind):
    assert L._row_kind(cells) == kind


# --- small rules ---
@pytest.mark.parametrize("field, value", [("header_rows", [3]), ("first_data_row", 0), ("last_data_row", 0), ("n_label_cols", 0),
                                          ("orientation", "cross_section")])
def test_a_correction_of_any_kind_makes_overrides_not_empty(field, value):
    assert L.Overrides().is_empty()
    assert not Overrides(**{field: value}).is_empty()


def test_overrides_that_say_nothing_are_empty():
    assert Overrides(header_rows=[], orientation="").is_empty()


@pytest.mark.parametrize("text, expected", [
    ("(në lekë)", True), ("miliardë lekë/billion ALL", True), ("percent", True), ("%", True), ("in thousand persons", True),
    ("Index, 2015 = 100", False), ("Index (2015=100)", False), ("Viti bazë 2015 = 100", False), ("Base: 2010=100", False),
    ("Total", False), ("", False), ("x" * 50, False), ("(" + "in thousand persons " * 3 + ")", False),
])
def test_a_line_that_only_states_a_unit(text, expected):
    assert L._is_unit_line(text) is expected


@pytest.mark.parametrize("code, depth", [("01.", 1), ("01.1.", 2), ("01.1.1.", 3), ("1.2.3.4", 4), ("12", 1), ("03.1", 2)])
def test_the_depth_of_a_dotted_code(code, depth):
    assert L._code_level(code, [])[0] == depth


@pytest.mark.parametrize("code", ["123", "A1", "010101", "", "1..2", "1.234", "x.1"])
def test_what_is_not_a_dotted_code_has_no_depth(code):
    assert L._code_level(code, []) == (None, None)


def test_codes_find_their_parents_and_a_sibling_closes_its_branch():
    parents: list = []
    got = [L._code_level(c, parents) for c in ("01.", "01.1.", "01.1.1.", "01.2.", "02.")]
    assert got == [(1, None), (2, "01."), (3, "01.1."), (2, "01."), (1, None)]


@pytest.mark.parametrize("values, expected", [
    (["01.1", "01.2", "01.3"], True), (["A", "B", "C"], True), (["Total", "01.1", "01.2"], True),
    (["10", "20", "30"], False), (["12", "13"], False), (["01.1"], False), (["01.1", "total", "x"], False), (["A1", "B2", "text"], False),
    (["01.1", "01.2", "01.3", "01.4", "name"], True), (["01.1", "01.2", "01.3", "name", "other"], False),
])
def test_a_column_that_looks_like_codes(values, expected):
    assert L._looks_like_codes(values) is expected


@pytest.mark.parametrize("values, expected", [
    ([1, 2, 3, 4, 5], [1, 2, 3, 4, 5]), ([0, 1, 2, 3, 4], [0, 1, 2, 3, 4]), ([1, 2, 3, 4, 5, None], [1, 2, 3, 4, 5]),
    ([2, 3, 4, 5, 6], None), ([1, 2, 3], None), ([1, 2, 3, 4, "x"], None), ([1, 3, 5, 7, 9], None), ([1, 2, 3, 4, 200], None),
    ([1.5, 2.5, 3.5, 4.5, 5.5], None), ([True, 2, 3, 4, 5], None), (["1", 2, 3, 4, 5], None),
])
def test_cells_that_count_up_from_zero_or_one(values, expected):
    assert L._int_sequence(values) == expected


@pytest.mark.parametrize("texts, expected", [
    (["0-4", "5-9", "10-14"], True), (["12-19", "20-29", "30-39", "40-49"], True), (["0-4", "5-9", "10-14", "70 +"], True),
    (["1-2", "5-6", "9-10"], False), (["10-5", "11-12", "13-14"], False), (["0-4", "5-9"], False), (["Jan-19", "Feb-19", "Mar-19"], False),
])
def test_class_limits_are_not_month_year_pairs(texts, expected):
    assert L._is_age_band_run(texts) is expected


@pytest.mark.parametrize("value, expected", [
    (2020, True), (2020.0, True), (1900, True), (2100, True), ("2020", True), ("2020*", True), (" 2020 ", True), ("2020**", True),
    (2020.5, False), (1899, False), (2101, False), (True, False), ("20201", False), ("19xx", False), (None, False),
])
def test_a_year_is_a_whole_number_between_1900_and_2100(value, expected):
    assert L._is_year_like(value) is expected


def test_the_year_is_read_from_the_cell():
    assert [L._year_value(v) for v in (2020, 2020.0, "2020*", " 2021 ")] == [2020, 2020, 2020, 2021]


@pytest.mark.parametrize("text, expected", [("(3=1-2)", True), ("6=(3+4-5)", True), ("12-21", False), ("3+4", False), ("(3)", False), (5, False), (None, False)])
def test_column_formulas_are_not_month_headers(text, expected):
    assert L._is_formula_text(text) is expected


@pytest.mark.parametrize("stacks, expected", [
    ([["2022-4"], ["2023-1"], ["2023-2"], ["2023-3"], ["2023-4"], ["2024-1"]], "Q"),
    ([["Jan 2023"], ["Feb 2023"], ["Mar 2023"]], "M"), ([["2020"], ["2021"], ["2022"]], "A"), ([["Q1 2023"], ["Q2 2023"]], "Q"),
    ([["text"]], None), ([], None),
])
def test_the_frequency_the_header_points_to(stacks, expected):
    assert L._hint(stacks) == expected


@pytest.mark.parametrize("stack, label, used", [
    (["2023", "Q1"], "2023-Q1", {0, 1}), (["Q2", "2023"], "2023-Q2", {0, 1}), (["2023"], "2023", {0}), (["2023", "Total"], "2023", {0}),
    (["Mars 2024"], "2024-03", {0}), (["Population", "2023*"], "2023", {1}),
])
def test_the_period_a_header_stack_carries(stack, label, used):
    period, consumed = L._column_period(stack, None)
    assert (period.label, consumed) == (label, used)


def test_a_stack_without_a_period_has_none():
    assert L._column_period(["Total"], None) == (None, set())
    assert L._column_period([], None) == (None, set())


@pytest.mark.parametrize("path, band, tail, expected", [
    (["Meshkuj", "Male"], (0, 1), None, (["Meshkuj"], ["Male"])),
    (["Male", "Meshkuj"], (1, 0), None, (["Meshkuj"], ["Male"])),
    (["Population", "Meshkuj", "Male"], None, (0, 1), (["Population", "Meshkuj"], ["Population", "Male"])),
    (["Population", "Male", "Meshkuj"], None, (1, 0), (["Population", "Meshkuj"], ["Population", "Male"])),
    (["Meshkuj", "Male"], None, None, (["Meshkuj"], ["Male"])),
    (["Meshkuj", "Male", "Femra", "Female"], None, None, (["Meshkuj", "Femra"], ["Male", "Female"])),
    (["Gjithsej/Total"], None, None, (["Gjithsej"], ["Total"])),
    (["Population", "Households"], None, None, (["Population", "Households"], ["Population", "Households"])),
    (["Total"], None, None, (["Total"], ["Total"])),
])
def test_two_levels_in_two_languages_are_one_label(path, band, tail, expected):
    assert L._bilingual_path(path, band, tail) == expected


# --- indentation ---
def indent_levels(labels):
    specs = [RowSpec(row=i, labels=[str(x).strip()]) for i, x in enumerate(labels)]
    L._indent_levels(SimpleNamespace(raw=[[x] for x in labels]), specs, name_col=0)
    return [(s.level, s.parent_code) for s in specs]


def test_indentation_written_with_spaces_makes_a_hierarchy():
    assert indent_levels(["Food", "  Milk", "    Cheese", "  Bread", "Fuel"]) == [(1, None), (2, "Food"), (3, "Milk"), (2, "Food"), (1, None)]


def test_tabs_and_non_breaking_spaces_indent_too():
    assert indent_levels(["Food", "  Milk", "\tCheese", "Fuel"]) == [(1, None), (3, "Food"), (2, "Food"), (1, None)]
    levels = [lvl for lvl, _p in indent_levels(["Food", " Milk", "  Cheese", "Fuel"])]
    assert levels == [1, 2, 3, 1]
    levels = [lvl for lvl, _p in indent_levels(["Food", "\tMilk", "\t\tCheese", "Fuel"])]
    assert levels == [1, 2, 3, 1]


def test_a_number_in_the_label_column_is_not_indented():
    """Numbers carry no indentation: a column of names and numbers is not a hierarchy."""
    assert indent_levels(["Total", 5, "Other", 7]) == [(None, None)] * 4


def test_no_hierarchy_without_two_depths_or_four_rows():
    assert indent_levels(["A", "B", "C", "D"]) == [(None, None)] * 4
    assert indent_levels(["A", " B", "C"]) == [(None, None)] * 3


def test_no_name_column_no_hierarchy():
    specs = [RowSpec(row=i) for i in range(4)]
    L._indent_levels(SimpleNamespace(raw=[["A"], [" B"], ["C"], [" D"]]), specs, name_col=None)
    assert [s.level for s in specs] == [None] * 4


# --- when a breakdown ends ---
def breakdown(positions, first, values):
    return L._breakdown_end([SimpleNamespace(row=p) for p in positions], first, lambda j: values[j])


def test_a_breakdown_ends_where_the_parts_add_up_to_the_row_above():
    assert breakdown([0, 1, 2, 3], 1, {0: 100, 1: 60, 2: 40, 3: 999}) == 2


def test_the_parts_may_differ_from_the_whole_by_rounding():
    assert breakdown([0, 1, 2], 1, {0: 100, 1: 60, 2: 40.9}) == 2                       # within 1
    assert breakdown([0, 1, 2], 1, {0: 10000, 1: 6000, 2: 3991}) == 2                   # within 0.1 %
    assert breakdown([0, 1, 2], 1, {0: 10000, 1: 6000, 2: 3980}) is None


def test_a_breakdown_gives_up_once_it_overshoots_and_does_not_come_back():
    assert breakdown([0, 1, 2, 3], 1, {0: 100, 1: 60, 2: 41.5, 3: -1.5}) is None


@pytest.mark.parametrize("first, values, positions", [
    (0, {0: 1, 1: 1}, [0, 1]),                                      # nothing above to add up to
    (1, {0: None, 1: 1}, [0, 1]), (1, {0: 0, 1: 1}, [0, 1]), (1, {0: -5, 1: 1}, [0, 1]),
    (1, {0: 100, 1: 60, 2: None}, [0, 1, 2]),                       # a gap in the figures
    (1, {0: 100, 1: 60, 2: 40, 3: 40}, [0, 1, 3]),                  # a blank row between the parts
    (1, {0: 100, 1: 10, 2: 10}, [0, 1, 2]),                         # the parts never reach the whole
])
def test_a_breakdown_that_does_not_exist(first, values, positions):
    assert breakdown(positions, first, values) is None


def test_one_part_may_be_the_whole_but_the_first_row_alone_does_not_end_it():
    assert breakdown([0, 1, 2], 1, {0: 100, 1: 100, 2: 100}) is None                    # the first part alone is not a breakdown


# --- repeated periods ---
def cols(*items):
    return [ColumnSpec(i, "value", path_sq=list(p), path_en=list(p), period=parse_period(label) if label else None)
            for i, (p, label) in enumerate(items)]


def test_a_period_that_comes_twice_stays_an_attribute_the_second_time():
    specs = cols(([], "2022"), ([], "2023"), ([], "2023"), (["Total"], "2023"), (["Total"], "2023"))
    warnings: list[str] = []
    L._demote_repeated_periods(specs, warnings)
    assert [c.kind for c in specs] == ["value", "value", "attr", "value", "attr"]
    assert warnings == ["Column C repeats the period 2023, so it was kept as an attribute.",
                        "Column E repeats the period 2023, so it was kept as an attribute."]


def test_columns_without_a_period_are_left_alone():
    specs = cols(([], None), ([], None), ([], "2023"), ([], None))
    L._demote_repeated_periods(specs, [])
    assert [c.kind for c in specs] == ["value"] * 4


def test_a_repeated_period_in_a_sheet_is_named_by_its_column_letter():
    wb = Writer()
    ws = wb.active
    ws["A1"] = "Turnover of enterprises"
    ws.cell(3, 1, "Sector")
    for j, y in enumerate(["2022", "2023", "2023"]):
        ws.cell(3, 2 + j, y)
    for i, n in enumerate(["Industry", "Trade", "Transport", "Services"]):
        ws.cell(4 + i, 1, n)
        for j in range(3):
            ws.cell(4 + i, 2 + j, 100.5 + 10 * i + j)
    t = one_table(wb.save())
    assert [c.kind for c in t.spec.columns] == ["label", "value", "value", "attr"]
    assert t.spec.warnings == ["Column D repeats the period 2023, so it was kept as an attribute."]


def test_the_letter_is_the_one_in_the_sheet_even_when_the_table_starts_further_right():
    wb = Writer()
    ws = wb.active
    ws.cell(3, 3, "Sector")                                                              # nothing in columns A and B
    for j, y in enumerate(["2022", "2023", "2023"]):
        ws.cell(3, 4 + j, y)
    for i, n in enumerate(["Industry", "Trade", "Transport", "Services"]):
        ws.cell(4 + i, 3, n)
        for j in range(3):
            ws.cell(4 + i, 4 + j, 100.5 + 10 * i + j)
    t = one_table(wb.save())
    assert t.spec.warnings == ["Column F repeats the period 2023, so it was kept as an attribute."]


# --- a layout asked for by the user ---
@pytest.mark.parametrize("maker, asked, result, honoured", [
    (demo.make_cpi_consistent, "cross_section", "cross_section", True),
    (demo.make_lfs_quarterly, "cross_section", "cross_section", True),
    (demo.make_month_by_year, "periods_in_columns", "periods_in_columns", True),
    (demo.make_month_by_year, "cross_section", "cross_section", True),
    (demo.make_month_by_year, "month_by_year", "month_by_year", True),
    (demo.make_cpi_consistent, "periods_in_columns", "periods_in_columns", True),
    (demo.make_cpi_consistent, "periods_in_rows", "periods_in_columns", False),
    (demo.make_cpi_consistent, "month_by_year", "periods_in_columns", False),
    (demo.make_cross_section, "periods_in_columns", "cross_section", False),
    (demo.make_cross_section, "periods_in_rows", "cross_section", False),
    (demo.make_cross_section, "month_by_year", "cross_section", False),
    (demo.make_gdp_workbook, "periods_in_columns", "periods_in_rows", False),
])
def test_a_layout_is_taken_when_the_table_allows_it_and_refused_with_a_reason_when_it_does_not(maker, asked, result, honoured):
    data = maker()[0]
    book = grid_mod.read_workbook(data, "t.xlsx")
    found = extract_tables(book, overrides={g.name: Overrides(orientation=asked) for g in book.sheets}).tables[0]
    assert found.spec.orientation == result
    refusal = [w for w in found.spec.warnings if "does not fit this table" in w]
    if honoured:
        assert not refusal
    else:
        assert refusal == [f"The layout you asked for ('{asked}') does not fit this table, so the automatic reading was kept."]


def test_forcing_a_cross_section_ignores_the_periods_in_the_header():
    data = demo.make_cpi_consistent()[0]
    book = grid_mod.read_workbook(data, "t.xlsx")
    auto = extract_tables(book).tables[0]
    forced = extract_tables(book, overrides={g.name: Overrides(orientation="cross_section") for g in book.sheets}).tables[0]
    assert auto.spec.orientation == "periods_in_columns" and forced.spec.orientation == "cross_section"
    assert "The layout was set by hand." in forced.spec.reasons
    assert all(c.period is None for c in forced.spec.columns) and not auto.df["period"].isna().all()


def test_years_in_most_but_not_all_rows_are_a_time_axis_when_the_user_says_so():
    wb = Writer()
    ws = wb.active
    ws["A1"] = "Indicators"
    ws.cell(3, 1, "Year")
    ws.cell(3, 2, "Value")
    for i, v in enumerate([2019, 2020, 2021, "n/a", "n/a"]):
        ws.cell(4 + i, 1, v)
        ws.cell(4 + i, 2, 10.5 + i)
    data = wb.save()
    assert one_table(data).spec.orientation == "cross_section"                          # three rows in five are not enough on their own
    forced = one_table(data, {"Sheet": Overrides(orientation="periods_in_rows")})
    assert forced.spec.orientation == "periods_in_rows" and "The layout was set by hand." in forced.spec.reasons
    assert [c.kind for c in forced.spec.columns] == ["period", "value"]


# --- whole tables ---
def test_a_lone_text_above_the_numbers_of_a_column_is_that_column_s_header():
    """``Census, 2001`` over 3,069,275: the cell is to the right of the labels and straight above the first data row."""
    wb = Writer()
    ws = wb.active
    ws["A1"] = "Population of Albania"
    ws.cell(3, 2, "Census, 2001")
    for i, (n, v) in enumerate([("Resident population", 3069275), ("Households", 727000), ("Dwellings", 800000)]):
        ws.cell(4 + i, 1, n)
        ws.cell(4 + i, 2, v)
    t = one_table(wb.save())
    assert t.spec.header_rows == [2] and t.spec.title_rows == [0]
    assert [(c.kind, c.name) for c in t.spec.columns] == [("label", ""), ("value", "Census, 2001")]


def groups(names):
    wb = Writer()
    ws = wb.active
    ws["A1"] = "Population by age group and sex"
    ws.cell(3, 1, "Age group")
    ws.cell(3, 2, "Number")
    r = 4
    for g in names:
        ws.cell(r, 1, g)
        r += 1
        for i, a in enumerate(["0-14", "15-64", "65+"]):
            ws.cell(r, 1, a)
            ws.cell(r, 2, 100.5 + 10 * i + r)
            r += 1
    return wb.save()


@pytest.mark.parametrize("names", [["Males", "Females"], ["Total", "Males", "Females"]])
def test_two_or_more_group_headings_are_a_dimension_of_their_own(names):
    t = one_table(groups(names))
    assert len(t.df) == 3 * len(names) and list(t.dim_columns) == ["dim_1", "dim_2"]
    assert set(t.df["dim_2"]) == set(names)


def test_one_group_heading_is_not_a_dimension():
    t = one_table(groups(["Males"]))
    assert list(t.dim_columns) == ["dim_1"] and len(t.df) == 3


def test_a_group_above_a_pair_of_header_rows_in_two_languages():
    wb = Writer()
    ws = wb.active
    ws["A1"] = "Population by sex and municipality"
    ws.cell(3, 1, "Municipality")
    ws.cell(3, 2, "Population")
    ws.merge_cells("B3:F3")
    ws.cell(3, 7, "Area")
    for j, (sq, en) in enumerate([("Meshkuj", "Male"), ("Femra", "Female"), ("Gjithsej", "Total"), ("Qytet", "Urban"), ("Fshat", "Rural")]):
        ws.cell(4, 2 + j, sq)
        ws.cell(5, 2 + j, en)
    ws.cell(4, 7, "Km2")
    for i, n in enumerate(["Tirane", "Durres", "Vlore", "Shkoder"]):
        ws.cell(6 + i, 1, n)
        for j in range(6):
            ws.cell(6 + i, 2 + j, 1000.5 + i + j)
    t = one_table(wb.save())
    assert "The last two header rows are a pair, one in Albanian and one in English." in t.spec.reasons
    got = [(c.name, c.path_sq, c.path_en) for c in t.spec.columns if c.kind == "value"]
    assert got == [("Population | Male", ["Population", "Meshkuj"], ["Population", "Male"]),
                   ("Population | Female", ["Population", "Femra"], ["Population", "Female"]),
                   ("Population | Total", ["Population", "Gjithsej"], ["Population", "Total"]),
                   ("Population | Urban", ["Population", "Qytet"], ["Population", "Urban"]),
                   ("Population | Rural", ["Population", "Fshat"], ["Population", "Rural"]),
                   ("Area | Km2", ["Area", "Km2"], ["Area", "Km2"])]                   # the column with two levels is not a pair


# --- the working copy of the grid ---
def work(cells, **kwargs):
    return L._Work(Grid("S", cells, **kwargs))


def test_hidden_rows_and_columns_are_masked_out():
    w = work([["a", "b", "c"], ["d", "e", "f"], ["g", "h", "i"]], hidden_rows=frozenset({1}), hidden_cols=frozenset({2}))
    assert w.raw == [["a", "b", None], [None, None, None], ["g", "h", None]]
    assert w.hidden_count == 2


def test_a_merged_cell_spreads_its_text_over_the_empty_cells_it_covers():
    w = work([["Group", None, None, "Down", None, None], ["x", "y", "z", None, "v", "w"]], merged=[(0, 0, 0, 2), (0, 3, 1, 3)])
    assert w.spread[0] == ["Group", "Group", "Group", "Down", None, None]
    assert w.spread[1][3] == "Down"                                                      # down as well as across
    assert w.raw[0] == ["Group", None, None, "Down", None, None]                         # the text is kept where it was written
    assert w.merge_anchor == {(0, 0): (0, 2), (0, 3): (1, 3)}
    assert [w.inside_merge(r) for r in (0, 1, 2)] == [False, True, False]                 # the rows below the first one of a merge


def test_a_title_merged_over_the_whole_width_is_a_banner_and_is_not_spread():
    w = work([["A title over the table", None, None, None], ["a", "b", "c", "d"]], merged=[(0, 0, 0, 3)])
    assert w.banner_rows == {0} and w.spread[0] == ["A title over the table", None, None, None]
    narrow = work([["A group", None, None, None], ["a", "b", "c", "d"]], merged=[(0, 0, 0, 1)])
    assert narrow.banner_rows == set() and narrow.spread[0][:2] == ["A group", "A group"]
    start = work([[None, "A group", None, None], ["a", "b", "c", "d"]], merged=[(0, 1, 0, 3)])
    assert start.banner_rows == set()                                                    # a banner starts in the first column
    with_more = work([["Title", "other", None, None], ["a", "b", "c", "d"]], merged=[(0, 0, 0, 3)])
    assert with_more.banner_rows == set()                                                # and is alone on its row


def test_a_merge_with_nothing_in_it_or_outside_the_grid_changes_nothing():
    w = work([[None, "x"], ["y", None]], merged=[(0, 0, 0, 1), (5, 5, 6, 6), (0, 9, 0, 12)])
    assert w.spread == w.raw


def test_a_hostile_number_of_merges_is_cut_off(monkeypatch):
    monkeypatch.setattr(config, "MAX_MERGE_CELLS", 4)
    cells = [[f"g{r}", None, None, None] for r in range(6)]
    w = work(cells, merged=[(r, 0, r, 1) for r in range(6)])
    spread = sum(row[1] is not None for row in w.spread)
    assert 0 < spread < 6


def test_a_merge_over_more_than_five_thousand_cells_is_not_spread():
    cells = [["group"] + [None] * 99 for _ in range(60)]
    w = work(cells, merged=[(0, 0, 59, 99)])
    assert w.spread == w.raw


@pytest.mark.parametrize("value, text", [
    (datetime.datetime(2024, 3, 1), "2024-03-01"), (datetime.datetime(2024, 3, 1, 10, 30), "2024-03-01 10:30:00"),
    (datetime.date(2024, 3, 1), "2024-03-01"), (None, ""), ("Perqindja\nCoverage ratio", "Perqindja\nCoverage ratio"), (5, "5"),
])
def test_the_text_of_a_cell(value, text):
    assert work([[value]]).txt(0, 0) == text


def test_the_text_of_a_row_and_its_filled_columns():
    w = work([[" Tirana ", None, 5, "a  b"]])
    assert w.nonempty_cols(0) == [0, 2, 3] and w.row_text(0) == "Tirana 5 a b"
    assert w.raw_txt(0, 0) == "Tirana" and w.raw_txt(0, 1) == ""


# --- decisions that were only exercised by accident ---
def regions_and_years(years):
    wb = Writer()
    ws = wb.active
    ws["A1"] = "Registered businesses by region (number)"
    ws.cell(3, 1, "Region")
    for j, y in enumerate(years):
        ws.cell(3, 2 + j, y)
    for i, name in enumerate(["Tirana", "Durres", "Vlore"]):
        ws.cell(4 + i, 1, name)
        for j in range(len(years)):
            ws.cell(4 + i, 2 + j, 100 + 10 * i + j)
    return wb.save()


@pytest.mark.parametrize("years", [(2019, 2020), (2019, 2020, 2021)])
def test_two_years_across_are_enough_to_make_a_table_of_periods_in_columns(years):
    t = one_table(regions_and_years(years))
    assert t.spec.orientation == "periods_in_columns"
    assert sorted(set(t.df["period"])) == [str(y) for y in years] and len(t.df) == 3 * len(years)


def test_one_year_across_is_not_a_series():
    assert one_table(regions_and_years((2019,))).spec.orientation != "periods_in_columns"


def ranged_title(title):
    wb = Writer()
    ws = wb.active
    ws["A1"] = title
    ws.cell(3, 1, "Region")
    ws.cell(3, 2, "Businesses")
    ws.cell(3, 3, "Employees")
    for i, name in enumerate(["Tirana", "Durres", "Vlore"]):
        ws.cell(4 + i, 1, name)
        ws.cell(4 + i, 2, 100 + i)
        ws.cell(4 + i, 3, 1100 + i)
    return wb.save()


def test_a_table_of_categories_takes_its_period_from_a_year_range_in_the_title():
    t = one_table(ranged_title("Businesses by region, 2018-2019"))
    assert t.spec.orientation == "cross_section" and t.spec.period_hint.label == "2018-2019"
    assert set(t.df["period"]) == {"2018-2019"}


def test_a_table_of_categories_takes_its_period_from_a_single_year_in_the_title():
    t = one_table(ranged_title("Businesses by region 2021"))
    assert t.spec.period_hint.label == "2021" and set(t.df["period"]) == {"2021"}
    assert one_table(ranged_title("Businesses by region")).spec.period_hint is None


def test_zero_label_columns_by_hand_leaves_no_label_column():
    wb = Writer()
    ws = wb.active
    ws["A1"] = "Turnover"
    for j, h in enumerate(["Sector", 2020, 2021, 2022]):
        ws.cell(3, 1 + j, h)
    for i, name in enumerate(["Industry", "Trade", "Services"]):
        ws.cell(4 + i, 1, name)
        for j in range(3):
            ws.cell(4 + i, 2 + j, 100.5 + 10 * i + j)
    data = wb.save()
    for n, dims in ((0, []), (1, ["dim_1"]), (2, ["dim_1", "dim_2"])):
        t = one_table(data, {"Sheet": Overrides(n_label_cols=n)})
        assert list(t.dim_columns) == dims, n
    assert one_table(data, {"Sheet": Overrides(n_label_cols=-3)}).dim_columns == []                  # below zero is zero, not one


def women_by_age(first_column):
    """A column whose header is one cell tall (merged down) next to a group whose header has two levels."""
    wb = Writer()
    ws = wb.active
    ws["A1"] = "Women by age group"
    ws.cell(3, 1, first_column)
    ws.cell(3, 2, "Total women")
    ws.cell(3, 3, "Women by age group")
    ws.merge_cells("A3:A4")
    ws.merge_cells("B3:B4")
    ws.merge_cells("C3:E3")
    for j, h in enumerate(["15-24", "25-34", "35-44"]):
        ws.cell(4, 3 + j, h)
    rows = [2019, 2020, 2021, 2022] if first_column == "Year" else ["Tirana", "Durres", "Vlore", "Kukes"]
    for i, name in enumerate(rows):
        ws.cell(5 + i, 1, name)
        for j in range(4):
            ws.cell(5 + i, 2 + j, 10.5 + 7 * i + j)
    return wb.save()


@pytest.mark.parametrize("first_column, orientation, dims", [("Year", "periods_in_rows", ["dim_1"]),
                                                              ("Region", "cross_section", ["dim_1", "dim_2"])])
def test_a_column_with_a_shorter_header_than_its_neighbours_is_a_measure_of_its_own(first_column, orientation, dims):
    t = one_table(women_by_age(first_column))
    assert t.spec.orientation == orientation and list(t.dim_columns) == dims
    assert t.df.groupby("measure").size().to_dict() == {"Total women": 4, "Women by age group": 12}
    assert sorted(set(t.df[dims[-1]])) == ["", "15-24", "25-34", "35-44"]                       # the age groups are categories, "Total women" has none


def test_a_ragged_header_is_left_alone_when_most_columns_are_short():
    short = [ColumnSpec(col=i, kind="value", name=n, path_en=p, path_sq=p) for i, (n, p) in enumerate(
        [("a", ["A"]), ("b", ["B"]), ("c", ["C", "x"]), ("d", ["D", "y"])])]
    L._mark_ragged_measures(short)                                  # two of four are short: more than a third
    assert [c.measure for c in short] == [None] * 4
    few = [ColumnSpec(col=i, kind="value", name=str(i), path_en=["G", str(i)], path_sq=["G", str(i)]) for i in range(5)]
    few.append(ColumnSpec(col=5, kind="value", name="T", path_en=["Total"], path_sq=["Total"]))
    L._mark_ragged_measures(few)                                    # one of six: a third or less
    assert [c.measure for c in few] == [None] * 5 + ["Total"]
    one_level = [ColumnSpec(col=i, kind="value", name=str(i), path_en=["G"], path_sq=["G"]) for i in range(3)]
    L._mark_ragged_measures(one_level)                              # nothing is shorter than the rest
    assert [c.measure for c in one_level] == [None] * 3


def test_a_column_without_any_header_is_not_a_short_header():
    cols = [ColumnSpec(col=0, kind="value", name="a", path_en=["G", "1"], path_sq=["G", "1"]),
            ColumnSpec(col=1, kind="value", name="b", path_en=["G", "2"], path_sq=["G", "2"]),
            ColumnSpec(col=2, kind="value", name="c", path_en=["G", "3"], path_sq=["G", "3"]),
            ColumnSpec(col=3, kind="value", name="d", path_en=[], path_sq=[])]
    L._mark_ragged_measures(cols)
    assert [c.measure for c in cols] == [None] * 4


def titles_of(*texts):
    return L._titles_and_scope(SimpleNamespace(row_text=lambda r: texts[r]), list(range(len(texts))))


def test_a_line_that_names_the_place_is_the_scope_and_not_a_title():
    assert titles_of("Population by age", "Qarku Berat | Prefecture Berat", "In persons") == (
        ["Population by age", "In persons"], [("Prefecture", "Berat")])


def test_the_first_line_is_the_title_even_when_it_looks_like_a_place():
    titles, scope = titles_of("Qarku Berat | Prefecture Berat", "Population by age", "Qarku Vlore | Prefecture Vlore")
    assert titles == ["Qarku Berat | Prefecture Berat", "Population by age"] and scope == [("Prefecture", "Vlore")]


def test_without_a_scope_line_the_titles_are_untouched():
    assert titles_of("Population by age", "In persons") == (["Population by age", "In persons"], [])


def test_months_down_the_rows_carry_a_month_marker_with_their_frequency():
    t = one_table(demo.make_month_by_year()[0])
    assert t.spec.orientation == "month_by_year"
    marks = [(r.period.label, r.period.freq) for r in t.spec.rows[:3]]
    assert marks == [("sub:M1", "M"), ("sub:M2", "M"), ("sub:M3", "M")]


def test_quarters_down_the_rows_carry_a_quarter_marker():
    rows = [SimpleNamespace(row=5, period=None), SimpleNamespace(row=6, period=None), SimpleNamespace(row=7, period=None)]
    L._attach_sub_periods(rows, {5: ("Q", 1), 6: ("Q", 4)})
    assert [(r.period.label, r.period.freq) if r.period else None for r in rows] == [("sub:Q1", "Q"), ("sub:Q4", "Q"), None]
