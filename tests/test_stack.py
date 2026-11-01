"""Repeated tables put back together: a sheet per place, or a block per sex, become one table you can compare across. Each test builds a
workbook whose numbers are known, so the combined table can be checked cell by cell, and the cases where tables must *not* be
combined (different titles, layouts, or blocks that cannot be told apart) are checked too."""

from __future__ import annotations

import pytest

from instatkit.excel.stack import _decode, _make_key
from instatkit.export.xlsx_writer import Workbook

from .conftest import process_workbook_bytes

YEARS = [2022, 2023, 2024]
AGES = ["0-14", "15-64", "65+"]
TITLE = "Resident population by age group"
PLACES = ["Berat", "Durrës", "Tiranë"]


def value(k: int, i: int, j: int) -> float:
    """The number in piece ``k``, row ``i``, year ``j``: never a whole number that could be mistaken for a year."""
    return 300.0 * (k + 1) + 10 * i + j + 0.5


def fill(ws, title: str, scope: str | None, k: int, years=YEARS, corner: str = "Age group") -> None:
    r = 1
    ws.cell(r, 1, title)
    if scope:
        r += 1
        ws.cell(r, 1, scope)
    r += 2
    for c, header in enumerate([corner, *years], 1):
        ws.cell(r, c, header)
    for i, age in enumerate(AGES):
        ws.cell(r + 1 + i, 1, age)
        for j in range(len(years)):
            ws.cell(r + 1 + i, 2 + j, value(k, i, j))


def sheets(names, *, scope: bool, title=lambda k: TITLE, years=lambda k: YEARS) -> bytes:
    book = Workbook()
    book.sheets = []
    for k, name in enumerate(names):
        fill(book.create_sheet(name), title(k), f"Qarku {name} | Prefecture {name}" if scope else None, k, years(k))
    return book.save()


def blocks(keys, *, first_row: bool = False) -> bytes:
    """One sheet, a block per key one under the other. The key is the top-left header cell, or (``first_row``) the label of the
    block's first row, which then holds the block's total."""
    book = Workbook()
    ws = book.active
    ws.title = "Population"
    ws.cell(1, 1, TITLE)
    r = 3
    for k, key in enumerate(keys):
        for c, header in enumerate(["Age group" if first_row else key, *YEARS], 1):
            ws.cell(r, c, header)
        if first_row:
            r += 1
            ws.cell(r, 1, key)
            for j in range(3):
                ws.cell(r, 2 + j, 900.0 * (k + 1) + j + 0.5)
        for i, age in enumerate(AGES):
            ws.cell(r + 1 + i, 1, age)
            for j in range(3):
                ws.cell(r + 1 + i, 2 + j, value(k, i, j))
        r += 6
    return book.save()


def lookup(df, **where):
    """The one value in ``df`` where every column named in ``where`` has the given value."""
    sel = df
    for col, want in where.items():
        sel = sel[sel[col] == want]
    assert len(sel) == 1, (where, len(sel))
    return float(sel["value"].iloc[0])


# sheets, one per place
@pytest.mark.parametrize("scope", [True, False], ids=["scope line under the title", "only the sheet name"])
def test_sheet_per_place_becomes_one_table(scope):
    pf = process_workbook_bytes(sheets(PLACES, scope=scope))
    assert pf.ok and len(pf.tables) == 1
    table = pf.tables[0].table
    assert len(table.parts) == 3 and len(table.df) == 27 and table.df["series_id"].nunique() == 9
    assert table.dim_columns == ["age_group", "region"]
    assert sorted(set(table.df["region"])) == sorted(PLACES)
    for k, place in enumerate(PLACES):
        for i, age in enumerate(AGES):
            for j, year in enumerate(YEARS):
                assert lookup(table.df, region=place, age_group=age, period=str(year)) == value(k, i, j), (place, age, year)


def test_new_dimension_is_named_after_its_source():
    scoped = process_workbook_bytes(sheets(PLACES, scope=True)).tables[0].table
    assert scoped.dim_info["region"] == {"source": "scope", "header": "Prefecture"}
    by_name = process_workbook_bytes(sheets(PLACES, scope=False)).tables[0].table
    assert by_name.dim_info["region"] == {"source": "block", "header": "Sheet"}


def test_every_number_still_points_at_its_own_sheet_and_cell():
    table = process_workbook_bytes(sheets(PLACES, scope=True)).tables[0].table
    row = table.df[(table.df["region"] == "Durrës") & (table.df["age_group"] == "15-64") & (table.df["period"] == "2023")].iloc[0]
    assert row["src_ref"].startswith("Durrës!"), "with several sheets the reference names the sheet"
    assert table.df["src_ref"].str.contains("!").all()


def test_combined_table_keeps_its_parts_and_says_so():
    pf = process_workbook_bytes(sheets(PLACES, scope=True))
    table = pf.tables[0].table
    assert any(w.startswith("3 sheets, one per place") for w in table.warnings)
    assert [p.sheet for p in table.parts] == PLACES
    assert sum(float(p.df["value"].sum()) for p in table.parts) == pytest.approx(float(table.df["value"].sum()))


# blocks on a single sheet
def test_blocks_named_in_their_header_cell_become_a_sex_dimension():
    table = process_workbook_bytes(blocks(["Total", "Male", "Female"])).tables[0].table
    assert len(table.parts) == 3 and len(table.df) == 27
    assert table.dim_columns == ["age_group", "sex"] and table.dim_info["sex"] == {"source": "block", "header": "Sex"}
    assert table.dim_info["age_group"]["header"] == "", "the corner cell was the block's name, not the header of the age groups"
    for k, sex in enumerate(["Total", "Male", "Female"]):
        for i, age in enumerate(AGES):
            for j, year in enumerate(YEARS):
                assert lookup(table.df, sex=sex, age_group=age, period=str(year)) == value(k, i, j)
    assert any(w.startswith("3 blocks on the sheet") for w in table.warnings)


def test_blocks_named_by_first_row_keep_it_as_total():
    table = process_workbook_bytes(blocks(["Total", "Male", "Female"], first_row=True)).tables[0].table
    assert len(table.parts) == 3 and len(table.df) == 36
    assert sorted(set(table.df["sex"])) == ["Female", "Male", "Total"]
    for k, sex in enumerate(["Total", "Male", "Female"]):
        for j, year in enumerate(YEARS):
            assert lookup(table.df, sex=sex, age_group="Total", period=str(year)) == 900.0 * (k + 1) + j + 0.5
    total = table.df[(table.df["sex"] == "Male") & (table.df["age_group"] == "Total")]
    assert total["is_total"].all(), "the block's first row is marked as a total"


# when not to combine
def test_sheets_with_different_titles_stay_separate():
    data = sheets(["One", "Two"], scope=False, title=lambda k: [TITLE, "Live births by age of mother"][k])
    pf = process_workbook_bytes(data)
    assert len(pf.tables) == 2 and all(not t.table.parts for t in pf.tables)


def test_sheets_with_different_columns_stay_separate():
    pf = process_workbook_bytes(sheets(["One", "Two"], scope=False, years=lambda k: [YEARS, [2021, *YEARS]][k]))
    assert len(pf.tables) == 2 and all(not t.table.parts for t in pf.tables)


def test_blocks_that_cannot_be_told_apart_stay_separate():
    pf = process_workbook_bytes(blocks(["Total", "Total"]))
    assert len(pf.tables) == 2 and all(not t.table.parts for t in pf.tables)


def test_a_single_table_is_left_alone():
    pf = process_workbook_bytes(sheets(["Berat"], scope=True))
    assert len(pf.tables) == 1 and not pf.tables[0].table.parts


# reading block keys
def test_block_keys_split_into_sex_and_area():
    keys = [_make_key(t) for t in ["Total", "Male", "Female", "Rural", "Male", "Female", "Urban", "Male", "Female"]]
    out = [{header: key.display for header, key in d.items()} for d in _decode(keys)]
    assert out[0] == {"Sex": "Total", "Area": "Total"}
    assert out[1] == {"Sex": "Male", "Area": "Total"}
    assert out[3] == {"Sex": "Total", "Area": "Rural"}, "a new area starts again from the total of both sexes"
    assert out[7] == {"Sex": "Male", "Area": "Urban"}
    assert len({tuple(d.values()) for d in out}) == 9


def test_plain_block_keys_form_one_dimension():
    out = _decode([_make_key("Alpha"), _make_key("Beta")])
    assert [d["Block"].display for d in out] == ["Alpha", "Beta"]
    assert _decode([_make_key("Alpha"), _make_key("Alpha")]) is None
    assert _decode([]) == []


def test_text_that_is_not_a_block_name_is_not_one():
    assert _make_key("") is None and _make_key("x" * 61) is None
    assert _make_key("Gjithsej / Total").tag == "total" and _make_key("Meshkuj / Male").display == "Male"
