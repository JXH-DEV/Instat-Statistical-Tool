"""The consistency checks, one scenario at a time, with the exact status and wording they must give.

Each table is a small workbook made here, so the expected result can be worked out by hand: a missing cell, a total that is wrong by a known
amount, a percentage of 120. A check that always says "pass" would fail most of these.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from instatkit.analysis.checks import _parse_quality
from instatkit.export.xlsx_writer import Workbook as Writer

from .conftest import process_workbook_bytes

YEARS = [2018, 2019, 2020, 2021, 2022]


def workbook(title_en, header, rows, first_col="Kategoria / Category", title_sq="Popullsia sipas kategorisë"):
    wb = Writer()
    ws = wb.active
    ws["A1"], ws["A2"] = title_sq, title_en
    ws.cell(4, 1, first_col)
    for j, h in enumerate(header):
        ws.cell(4, 2 + j, h)
    for i, (name, values) in enumerate(rows):
        ws.cell(5 + i, 1, name)
        for j, v in enumerate(values):
            ws.cell(5 + i, 2 + j, v)
    return wb.save()


def checks(data):
    pf = process_workbook_bytes(data)
    assert pf.ok and len(pf.tables) == 1, pf.errors
    return {c.key: c for c in pf.tables[0].analysis.checks}


def population(rows, years=YEARS, title="Population (persons)"):
    return checks(workbook(title, years, rows))


# --- completeness ---
def test_a_complete_table_passes():
    c = population([("Total", [600, 630, 660, 690, 720]), ("Male", [300, 315, 330, 345, 360])])["completeness"]
    assert (c.status, c.detail) == ("pass", "All 10 cells have a value.")


def test_missing_cells_are_counted_and_explained():
    c = population([("Total", [600, 630, 660, 690, 720]), ("Male", [300, "..", "..", 345, 360]), ("Female", [300, 315, 330, 345, 360])])["completeness"]
    assert (c.status, c.detail) == ("info", "2 of 15 cells (13.3%) are missing (not available: 2).")


def test_a_dash_is_reported_as_a_dash():
    c = population([("Total", [600, 630, 660, 690, 720]), ("Male", [300, "-", 330, 345, 360]), ("Female", [300, 315, 330, 345, 360])])["completeness"]
    assert c.detail == "1 of 15 cells (6.7%) are missing (shown as a dash: 1)."


def test_a_fifth_of_the_cells_is_still_only_information_and_more_is_a_warning():
    rows = [("Total", [600, 630, 660, 690, 720]), ("Male", ["..", "..", "..", 345, 360]), ("Female", [300, 315, 330, 345, 360])]
    assert population(rows)["completeness"].status == "info"                            # 3 of 15 is exactly 20 %
    rows[2] = ("Female", [300, 315, 330, 345, ".."])
    c = population(rows)["completeness"]
    assert (c.status, c.detail) == ("warn", "4 of 15 cells (26.7%) are missing (not available: 4). 1 series is at least half empty.")


def test_a_series_that_is_exactly_half_empty_counts_as_half_empty():
    rows = [("Total", [600, 630, 660, 690]), ("Male", [300, "..", "..", 345]), ("Female", [300, 315, 330, 345])]
    assert population(rows, [2019, 2020, 2021, 2022])["completeness"].detail.endswith("1 series is at least half empty.")


def test_several_empty_series_are_counted_in_the_plural():
    rows = [("Total", [600, 630, 660, 690, 720]), ("Male", ["..", "..", "..", "..", 360]), ("Female", ["..", "..", "..", 345, 360])]
    assert population(rows)["completeness"].detail.endswith("2 series are at least half empty.")


# --- gaps in time ---
def _monthly(labels):
    return checks(workbook("Consumer prices index", labels, [("Total", list(range(100, 100 + len(labels)))), ("Food", list(range(101, 101 + len(labels))))]))


def test_a_gap_of_five_months_is_listed_in_full():
    c = _monthly([" 01-22", " 02-22", " 03-22", " 09-22", " 10-22", " 11-22", " 12-22"])["period continuity"]
    assert c.status == "warn"
    assert c.detail == "5 periods are missing in this range: April 2022, May 2022, June 2022, July 2022, August 2022."
    assert c.examples == ["April 2022", "May 2022", "June 2022", "July 2022", "August 2022"]


def test_a_longer_gap_lists_five_and_says_there_are_more():
    c = _monthly([" 01-22", " 02-22", " 03-22", " 01-23", " 02-23", " 03-23"])["period continuity"]
    assert c.detail == "9 periods are missing in this range: April 2022, May 2022, June 2022, July 2022, August 2022…."
    assert len(c.examples) == 5


def test_one_missing_month_is_singular():
    c = _monthly([" 01-22", " 02-22", " 04-22", " 05-22"])["period continuity"]
    assert c.detail == "1 period is missing in this range: March 2022."


def test_three_periods_are_enough_to_look_for_gaps_and_two_are_not():
    c = population([("Total", [1, 2, 3]), ("Male", [1, 1, 1])], [2020, 2021, 2022])["period continuity"]
    assert (c.status, c.detail) == ("pass", "No gaps between 2020 and 2022 (annual).")
    assert "period continuity" not in population([("Total", [1, 2]), ("Male", [1, 1])], [2020, 2021])


# --- values that cannot be right ---
def rates(rows, title="Unemployment rate (%)"):
    return checks(workbook(title, YEARS, rows))


def test_a_percentage_outside_zero_to_hundred_is_flagged_with_its_cell():
    c = rates([("Total", [10, 11, 120, 9, 8]), ("Male", [10, 11, 9, -3, 8])])["plausible range"]
    assert c.status == "warn"
    assert c.detail == "2 values look implausible (percentages outside 0-100, or unexpected negatives)."
    assert c.examples == ["D5: 120", "E6: -3"]


def test_zero_and_a_hundred_are_fine_and_a_little_more_is_not():
    assert rates([("Total", [0, 100, 50, 9, 8]), ("Male", [10, 11, 9, 8, 100])])["plausible range"].status == "pass"
    c = rates([("Total", [0, 100.5, 50, 9, 8]), ("Male", [10, 11, 9, 8, 7])])["plausible range"]
    assert c.status == "warn" and c.examples == ["C5: 100.5"]


def test_only_three_examples_are_shown_however_many_values_are_wrong():
    c = rates([("Total", [101, 102, 103, 104, 105])])["plausible range"]
    assert c.detail.startswith("5 values look implausible") and c.examples == ["B5: 101", "C5: 102", "D5: 103"]


def test_a_ratio_may_exceed_a_hundred_percent_so_it_is_not_range_checked():
    assert "plausible range" not in rates([("Total", [10, 11, 120, 9, 8]), ("Male", [10, 11, 9, 8, 8])], "Coverage ratio (%)")
    assert "plausible range" in rates([("Total", [10, 11, 120, 9, 8]), ("Male", [10, 11, 9, 8, 8])], "Unemployment rate (%)")


def test_one_negative_count_among_many_is_flagged():
    c = population([("Total", [10, 11, 12, 9, 8]), ("Male", [10, 11, 9, 8, -8]), ("Female", [1, 2, 3, 4, 5])])["plausible range"]
    assert (c.status, c.examples) == ("warn", ["F6: -8"])


def test_a_measure_that_is_often_negative_is_taken_as_signed():
    assert population([("Total", [10, 11, -12, 9, -8]), ("Male", [10, -11, 9, 8, -8]), ("Female", [1, 2, 3, 4, 5])])["plausible range"].status == "pass"
    two_in_ten = [("Total", [10, 11, 12, 9, 8]), ("Male", [10, -11, 9, 8, -8])]
    assert population(two_in_ten)["plausible range"].status == "pass"                  # a fifth is the limit


def test_a_balance_may_be_negative_so_it_is_not_range_checked():
    rows = [("Total", [10, 11, 12, 9, 8]), ("Male", [10, 11, 9, 8, -8]), ("Female", [1, 2, 3, 4, 5])]
    assert "plausible range" not in population(rows, title="Trade balance (persons)")
    assert population(rows, title="Population (persons)")["plausible range"].status == "warn"      # the same numbers, but a count


def test_a_table_with_nothing_to_range_check_has_no_such_check():
    assert "plausible range" not in checks(workbook("Consumer prices index (2015=100)", YEARS, [("Total", [100, 101, 102, 103, 104]), ("Food", [100, 102, 103, 104, 105])]))


# --- parts that must add up to the total ---
def parts(total_offset=0, years=(2021, 2022, 2023), values=((100, 200, 300), (110, 210, 310), (120, 220, 320))):
    """The total of each period is the sum of the parts plus ``total_offset`` (one number, or one per period)."""
    offsets = total_offset if isinstance(total_offset, (list, tuple)) else [total_offset] * len(years)
    rows = [("Total", [sum(v[j] for v in values) + offsets[j] for j in range(len(years))])]
    rows += [(name, list(v)) for name, v in zip(("0-14", "15-64", "65+"), values)]
    return checks(workbook("Population by age group (persons)", list(years), rows, first_col="Grupmosha / Age group"))["parts add up: age_group"]


def test_parts_that_add_up_pass():
    c = parts()
    assert (c.status, c.detail) == ("pass", "In all 3 groups the parts by age group add up to the stated total (largest difference 0.00%).")


def test_parts_that_do_not_add_up_fail_and_say_by_how_much():
    c = parts(total_offset=10)
    assert c.status == "fail"
    assert c.detail == ("3 of 3 groups are off from the stated total by more than rounding can explain. "
                        "Either a total or some of the categories may be wrong or missing.")
    assert c.examples == ["Population by age group (persons), 2021: off by 2.9%", "Population by age group (persons), 2022: off by 1.6%",
                          "Population by age group (persons), 2023: off by 1.1%"]


def test_only_the_three_worst_groups_are_named_and_the_worst_comes_first():
    years = (2018, 2019, 2020, 2021, 2022)
    values = tuple((100 + 10 * i,) * 5 for i in range(3))                  # the parts add up to 330 in every year
    c = parts(years=years, values=values, total_offset=[10, 50, 30, 20, 40])    # totals of 340, 380, 360, 350 and 370
    assert c.status == "fail"
    assert [e.split(", ")[-1] for e in c.examples] == ["2019: off by 13.2%", "2022: off by 10.8%", "2020: off by 8.3%"]


def test_a_total_that_is_wrong_by_less_than_half_a_percent_is_rounding():
    big = ((10000, 20000, 30000), (11000, 21000, 31000), (12000, 22000, 32000))
    c = parts(total_offset=130, values=big)
    assert c.status == "pass" and "largest difference 0.39%" in c.detail
    assert parts(total_offset=170, values=big).status == "fail"                        # 0.52 %


def test_whole_numbers_may_be_one_unit_off_even_when_that_is_more_than_half_a_percent():
    total_200 = ((50, 60, 70), (50, 60, 70), (100, 120, 140))
    assert parts(total_offset=-1, values=total_200).status == "pass"                   # 199 against 200: one unit and exactly 0.5 %
    assert parts(total_offset=-2, values=total_200).status == "fail"


def test_a_few_groups_off_is_a_warning_and_many_is_a_failure():
    years = tuple(range(2010, 2020))
    values = tuple((1000,) * 10 for _ in range(3))
    def with_bad(n):
        rows = [("Total", [3000 + (500 if j < n else 0) for j in range(10)])] + [(f"p{i}", list(v)) for i, v in enumerate(values)]
        return checks(workbook("Population by age group (persons)", list(years), rows, first_col="Grupmosha / Age group"))["parts add up: age_group"]
    assert with_bad(2).status == "warn"                                                # a fifth of the groups
    assert with_bad(3).status == "fail"


def test_parts_that_exceed_the_total_by_a_lot_suggest_overlapping_categories():
    rows = [("Total", [100, 110, 120]), ("0-14", [70, 75, 80]), ("0-64", [45, 50, 55]), ("65+", [35, 35, 35])]      # 150, 160, 170 against 100, 110, 120
    c = checks(workbook("Population by age group (persons)", [2021, 2022, 2023], rows, first_col="Grupmosha / Age group"))["parts add up: age_group"]
    assert c.status == "fail" and c.detail.endswith("The categories may overlap (for example broad and narrow age bands).")


def test_a_total_that_is_too_high_suggests_something_missing():
    rows = [("Total", [100, 110, 120]), ("0-14", [30, 35, 40]), ("0-64", [20, 20, 20]), ("65+", [10, 10, 10])]
    c = checks(workbook("Population by age group (persons)", [2021, 2022, 2023], rows, first_col="Grupmosha / Age group"))["parts add up: age_group"]
    assert c.status == "fail" and c.detail.endswith("Either a total or some of the categories may be wrong or missing.")


def test_a_subtotal_among_the_parts_is_named():
    rows = [("Total", [300, 310, 320, 330, 340]), ("Tirana", [100] * 5), ("Durres", [50] * 5), ("Other", [150, 160, 170, 180, 190]),
            ("Of which Kamez", [30] * 5)]
    c = checks(workbook("Population (persons)", YEARS, rows))["parts add up: category"]
    assert c.status == "pass"
    assert c.detail == ("The parts by category add up to the stated total once the subtotal 'Of which Kamez' is left out; "
                        "it contains other rows of the same table.")


def test_two_subtotals_among_the_parts_are_named_together():
    rows = [("Total", [300, 310, 320, 330, 340]), ("Tirana", [100] * 5), ("Durres", [55] * 5), ("Other", [145, 155, 165, 175, 185]),
            ("Of which Kamez", [30] * 5), ("Of which Vora", [20] * 5)]
    c = checks(workbook("Population (persons)", YEARS, rows))["parts add up: category"]
    assert c.status == "pass"
    assert c.detail == ("The parts by category add up to the stated total once the subtotals 'Of which Kamez' and 'Of which Vora' are "
                        "left out; they contain other rows of the same table.")


# --- shares ---
def shares(columns, last_column_values=None):
    """Three regions whose shares add up to ``columns`` in every period (a list of sums, one per period)."""
    years = list(range(2000, 2000 + len(columns)))
    rows = [("Tirana", [s - 60 for s in columns]), ("Durres", [30] * len(columns)), ("Vlora", [30] * len(columns))]
    return checks(workbook("Share of population by region (%)", years, rows, first_col="Rajoni / Region",
                           title_sq="Struktura e popullsisë sipas rajonit (%)")).get("shares add up to 100%")


def test_shares_that_add_up_to_a_hundred_pass():
    c = shares([100] * 5)
    assert (c.status, c.detail) == ("pass", "In 100% of the groups by region the shares add up to 100% (give or take 1).")


def test_shares_may_be_one_point_off_but_not_more():
    assert shares([101] * 5).status == "pass"
    assert shares([99] * 5).status == "pass"
    assert shares([102] * 5) is None                                                    # nothing here looks like shares of a whole


def test_shares_that_mostly_add_up_are_a_warning_with_the_share_of_groups():
    c = shares([100, 100, 100, 130, 130])
    assert (c.status, c.detail) == ("warn", "In 60% of the groups by region the shares add up to 100% (give or take 1).")


def test_half_of_the_groups_is_enough_to_say_something_and_less_is_not():
    assert shares([100, 100, 130, 130]).status == "warn"
    assert shares([100, 130, 130, 130]) is None


def test_ninety_eight_percent_of_the_groups_is_still_a_pass():
    assert shares([100] * 49 + [130]).status == "pass"
    assert shares([100] * 48 + [130, 130]).status == "warn"


# --- more boundaries: where the explanations of a wrong total begin and end ---
def age_parts(total, *parts_, years=(2021, 2022, 2023)):
    rows = [("Total", [total] * len(years))] + [(name, [v] * len(years)) for name, v in zip(("0-14", "0-64", "65+", "all ages"), parts_)]
    return checks(workbook("Population by age group (persons)", list(years), rows, first_col="Grupmosha / Age group"))["parts add up: age_group"]


def test_parts_five_percent_over_the_total_are_not_yet_overlapping_categories():
    just = age_parts(200, 100, 70, 40)                                                  # 210 against 200: exactly 1.05
    assert just.status == "fail" and just.detail.endswith("Either a total or some of the categories may be wrong or missing.")
    more = age_parts(200, 100, 72, 40)                                                  # 212 against 200: 1.06
    assert more.detail.endswith("The categories may overlap (for example broad and narrow age bands).")
    below = age_parts(200, 100, 50, 40)                                                 # 190 against 200: the parts fall short
    assert below.detail.endswith("Either a total or some of the categories may be wrong or missing.")


def parts_check(rows, years=YEARS):
    """The one 'parts add up' check of a table of places (its key names the kind of dimension the labels make up)."""
    found = [c for k, c in checks(workbook("Population (persons)", years, rows)).items() if k.startswith("parts add up")]
    assert len(found) == 1
    return found[0]


def test_a_subtotal_is_found_even_when_only_three_categories_are_listed():
    c = parts_check([("Total", [150] * 5), ("Tirana", [100] * 5), ("Durres", [50] * 5), ("Of which Kamez", [30] * 5)])
    assert c.status == "pass" and "once the subtotal 'Of which Kamez' is left out" in c.detail


def test_two_categories_and_a_total_cannot_name_a_subtotal():
    c = parts_check([("Total", [150] * 5), ("Tirana", [100] * 5), ("Of which Kamez", [80] * 5)])
    assert c.status == "fail" and "subtotal" not in c.detail


def test_a_subtotal_must_explain_nine_in_ten_of_the_wrong_groups():
    years = list(range(2010, 2020))

    def result(n_explained):
        total = [150 if j < n_explained else 50 for j in range(10)]                     # the other groups are off by more than the subtotal
        rows = [("Total", total), ("Tirana", [100] * 10), ("Durres", [50] * 10), ("Of which Kamez", [30] * 10)]
        return parts_check(rows, years)

    assert result(9).status == "pass" and "subtotal 'Of which Kamez'" in result(9).detail
    assert result(8).status == "fail"


def test_counts_that_happen_to_add_up_to_a_hundred_are_not_shares():
    rows = [("Tirana", [40] * 5), ("Durres", [30] * 5), ("Vlora", [30] * 5)]
    assert "shares add up to 100%" not in checks(workbook("Population by region (persons)", YEARS, rows, first_col="Rajoni / Region"))
    assert "shares add up to 100%" in checks(workbook("Share of population by region (%)", YEARS, rows, first_col="Rajoni / Region"))


# --- boundaries the first version of these tests left open ---
def test_an_odd_whole_total_may_be_one_unit_off_like_an_even_one():
    small = ((10, 10, 10), (20, 20, 20), (30, 30, 30))                                  # the parts add up to 60
    assert parts(total_offset=1, values=small).status == "pass"                         # a total of 61 against 60: one unit
    assert parts(total_offset=2, values=small).status == "fail"


def test_a_total_with_only_two_parts_is_checked_and_one_part_is_not_enough():
    two = checks(workbook("Population (persons)", YEARS, [("Total", [600, 630, 660, 690, 720]), ("Male", [300, 315, 330, 345, 360]),
                                                         ("Female", [300, 315, 330, 345, 360])]))
    assert two["parts add up: sex"].status == "pass"
    one = checks(workbook("Population (persons)", YEARS, [("Total", [300, 315, 330, 345, 360]), ("Male", [300, 315, 330, 345, 360])]))
    assert not [key for key in one if key.startswith("parts add up")]


def test_only_three_negative_counts_are_named_whatever_their_number():
    def series(*negatives):
        values = [10] * 20
        for position, value in negatives:
            values[position] = value
        return values

    rows = [("Total", series((1, -1))), ("Male", series((4, -5))), ("Female", series((9, -9))), ("Other", series((16, -13))),
            ("Unknown", series((14, -17)))]
    c = population(rows, years=list(range(2000, 2020)))["plausible range"]
    assert c.detail.startswith("5 values look implausible") and c.examples == ["C5: -1", "F6: -5", "K7: -9"]


@pytest.mark.parametrize("confidence, status", [(1.0, "pass"), (0.85, "pass"), (0.8499, "warn"), (0.6, "warn"), (0.5999, "fail"), (0.0, "fail")])
def test_the_layout_check_passes_from_eighty_five_percent_and_fails_below_sixty(confidence, status):
    pf = process_workbook_bytes(workbook("Population (persons)", YEARS, [("Total", [600, 630, 660, 690, 720]), ("Male", [300, 315, 330, 345, 360])]))
    c = _parse_quality(pf.tables[0].table, SimpleNamespace(confidence=confidence))
    assert c.status == status and c.detail.startswith(f"The layout was recognised with {confidence * 100:.0f}% confidence.")


def test_a_subtotal_is_searched_among_at_most_sixty_categories():
    def result(n_plain):
        names = [(f"Place {i:02d}", [1] * 5) for i in range(n_plain)]
        return parts_check([("Total", [n_plain] * 5), *names, ("Of which Place 00 and 01", [2] * 5)])

    assert "subtotal 'Of which Place 00 and 01'" in result(59).detail                   # sixty categories in all
    assert result(60).status == "fail" and "subtotal" not in result(60).detail           # sixty-one are too many to try every one
