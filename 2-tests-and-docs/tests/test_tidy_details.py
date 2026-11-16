"""The step from a recognised layout to the clean table: which period a value gets, which extra columns appear, how tables are named and where
the titles of the contents sheet land. Each workbook is small and made here, so every expected value is worked out by hand."""

from __future__ import annotations

import pytest

from instatkit.export.xlsx_writer import Style
from instatkit.export.xlsx_writer import Workbook as Writer
from instatkit.semantics.periods import sub_period

from .conftest import process_workbook_bytes

EN_MONTHS = ["January", "February", "March", "April"]
SQ_MONTHS = ["Janar", "Shkurt", "Mars", "Prill"]


def tables(data):
    pf = process_workbook_bytes(data)
    assert pf.ok, pf.errors
    return pf, [pt.table for pt in pf.tables]


def by_ref(table):
    return dict(zip(table.df["src_ref"], zip(table.df["period"], table.df["value"])))


# --- a month or quarter is a fragment of a period ---
@pytest.mark.parametrize("text, expected", [
    ("January", ("M", 1)), ("Janar", ("M", 1)), ("Dhjetor", ("M", 12)), ("Q2", ("Q", 2)), ("Tr.3", ("Q", 3)), ("IV", None), ("T4", ("Q", 4)),
    ("H1", ("H", 1)), ("S2", ("H", 2)), ("2020", None), ("Total", None), ("", None),
    ("Janar/January", ("M", 1)), ("Janar / January", ("M", 1)), ("Shkurt | February", ("M", 2)), ("Tr.1 / Q1", ("Q", 1)),
    ("Janar/February", None), ("Janar/Total", None), ("T1/T2", None), ("/", None),
])
def test_a_month_or_quarter_without_its_year(text, expected):
    assert sub_period(text) == expected


def months_across(header, years=(2022, 2023, 2024)):
    wb = Writer()
    ws = wb.active
    ws["A1"] = "Arrivals of foreign citizens by month"
    ws.cell(4, 1, "Year")
    for j, h in enumerate(header):
        ws.cell(4, 2 + j, h)
    for i, y in enumerate(years):
        ws.cell(5 + i, 1, y)
        for j in range(len(header)):
            ws.cell(5 + i, 2 + j, 1000 * (i + 1) + j + 0.5)
    return wb.save()


@pytest.mark.parametrize("header", [
    EN_MONTHS, SQ_MONTHS, [f"{a}/{b}" for a, b in zip(SQ_MONTHS, EN_MONTHS)], [f"{a} / {b}" for a, b in zip(SQ_MONTHS, EN_MONTHS)],
], ids=["English", "Albanian", "both languages, tight", "both languages, spaced"])
def test_years_down_the_rows_and_months_across_are_a_monthly_series(header):
    _, (t,) = tables(months_across(header))
    assert t.spec.orientation == "month_by_year"
    values = by_ref(t)
    assert values["B5"] == ("2022-01", 1000.5) and values["E5"] == ("2022-04", 1003.5)
    assert values["B6"] == ("2023-01", 2000.5) and values["E7"] == ("2024-04", 3003.5)
    assert set(t.df["freq"]) == {"M"} and t.df["period_start"].min().isoformat()[:10] == "2022-01-01"


def months_down(labels, years=(2022, 2023)):
    wb = Writer()
    ws = wb.active
    ws["A1"] = "Arrivals of foreign citizens by month"
    ws.cell(4, 1, "Month")
    for j, y in enumerate(years):
        ws.cell(4, 2 + j, y)
    for i, label in enumerate(labels):
        ws.cell(5 + i, 1, label)
        for j in range(len(years)):
            ws.cell(5 + i, 2 + j, 100 * (j + 1) + i + 0.5)
    return wb.save()


@pytest.mark.parametrize("labels", [EN_MONTHS, SQ_MONTHS, [f"{a} / {b}" for a, b in zip(SQ_MONTHS, EN_MONTHS)]],
                         ids=["English", "Albanian", "both languages"])
def test_months_down_the_rows_and_years_across_are_a_monthly_series(labels):
    _, (t,) = tables(months_down(labels))
    values = by_ref(t)
    assert t.spec.orientation == "month_by_year"
    assert values["B5"] == ("2022-01", 100.5) and values["B8"] == ("2022-04", 103.5)
    assert values["C5"] == ("2023-01", 200.5) and values["C8"] == ("2023-04", 203.5)


def test_quarters_across_under_years_down_the_rows():
    wb = Writer()
    ws = wb.active
    ws["A1"] = "Gross domestic product by quarter"
    ws.cell(4, 1, "Year")
    for j, q in enumerate(["Q1", "Q2", "Q3", "Q4"]):
        ws.cell(4, 2 + j, q)
    for i, y in enumerate([2021, 2022, 2023]):
        ws.cell(5 + i, 1, y)
        for j in range(4):
            ws.cell(5 + i, 2 + j, 10 * (i + 1) + j + 0.5)
    _, (t,) = tables(wb.save())
    values = by_ref(t)
    assert values["B5"] == ("2021-Q1", 10.5) and values["E5"] == ("2021-Q4", 13.5) and values["C7"] == ("2023-Q2", 31.5)


# --- a table about one place ---
def scoped(*scopes):
    wb = Writer()
    ws = wb.active
    ws["A1"] = "Resident population by area and sex, 2023"
    for k, line in enumerate(scopes):
        ws.cell(2 + k, 1, line)
    ws.cell(5, 1, "Area")
    for j, h in enumerate(["Total", "Males", "Females"]):
        ws.cell(5, 2 + j, h)
    for i, name in enumerate(["Urban", "Rural"]):
        ws.cell(6 + i, 1, name)
        for j in range(3):
            ws.cell(6 + i, 2 + j, 100.5 + 10 * i + j)
    return wb.save()


def test_a_line_naming_the_place_becomes_a_column_after_the_row_and_header_columns():
    _, (t,) = tables(scoped("Qarku Berat | Prefecture Berat"))
    assert list(t.dim_columns) == ["urban_rural", "sex", "region"]
    assert t.dim_info == {"urban_rural": {"source": "row", "header": "Area"}, "sex": {"source": "column", "header": ""},
                          "region": {"source": "scope", "header": "Prefecture"}}
    assert set(t.df["region"]) == {"Berat"} and set(t.df["urban_rural"]) == {"Urban", "Rural"} and set(t.df["sex"]) == {"Total", "Males", "Females"}
    assert t.df["region"].tolist() == ["Berat"] * 6


def test_two_lines_naming_places_become_two_columns_in_order():
    _, (t,) = tables(scoped("Qarku Berat | Prefecture Berat", "Bashkia Kucove | Municipality Kucove"))
    assert list(t.dim_columns) == ["urban_rural", "sex", "region", "region_2"]
    assert t.dim_info["region"] == {"source": "scope", "header": "Prefecture"}
    assert t.dim_info["region_2"] == {"source": "scope", "header": "Municipality"}
    assert set(t.df["region"]) == {"Berat"} and set(t.df["region_2"]) == {"Kucove"}


def test_the_title_period_applies_to_a_table_without_periods_in_its_header():
    _, (t,) = tables(scoped())
    assert set(t.df["period"]) == {"2023"} and set(t.df["freq"]) == {"A"}
    assert set(t.df["period_start"].astype(str).str[:10]) == {"2023-01-01"} and set(t.df["period_end"].astype(str).str[:10]) == {"2023-12-31"}


def test_a_table_with_no_period_anywhere_has_none():
    wb = Writer()
    ws = wb.active
    ws["A1"] = "Resident population by area and sex"
    ws.cell(4, 1, "Area")
    for j, h in enumerate(["Total", "Males", "Females"]):
        ws.cell(4, 2 + j, h)
    for i, name in enumerate(["Urban", "Rural"]):
        ws.cell(5 + i, 1, name)
        for j in range(3):
            ws.cell(5 + i, 2 + j, 100.5 + 10 * i + j)
    _, (t,) = tables(wb.save())
    assert set(t.df["period"]) == {""} and set(t.df["freq"]) == {""} and t.df["period_start"].isna().all()


# --- numbers stored as fractions ---
def test_percent_fractions_keep_ten_digits_and_plain_numbers_keep_all():
    wb = Writer()
    ws = wb.active
    ws["A1"], ws["A2"] = "Familjet me internet (%)", "Share of households with internet (%)"
    ws.cell(4, 1, "Rajoni / Region")
    ws.cell(4, 2, 2022)
    ws.cell(4, 3, 2023)
    for i, (name, a, b) in enumerate([("Tirana", 0.1234567890123, 0.5), ("Durres", 0.07, 0.25)]):
        ws.cell(5 + i, 1, name)
        ws.cell(5 + i, 2, a).style = Style(fmt="0.0%")
        ws.cell(5 + i, 3, b).style = Style(fmt="0.0%")
    _, (t,) = tables(wb.save())
    values = {ref: v for ref, (_p, v) in by_ref(t).items()}
    assert values["B5"] == 12.3456789012 and values["B6"] == 7.0 and values["C5"] == 50.0

    wb = Writer()
    ws = wb.active
    ws["A1"], ws["A2"] = "Indeksi", "Index"
    ws.cell(4, 1, "Rajoni / Region")
    ws.cell(4, 2, 2022)
    ws.cell(4, 3, 2023)
    for i, (name, a, b) in enumerate([("Tirana", 1.123456789012345, 2.5), ("Durres", 3.0, 4.5)]):
        ws.cell(5 + i, 1, name)
        ws.cell(5 + i, 2, a)
        ws.cell(5 + i, 3, b)
    _, (t,) = tables(wb.save())
    assert by_ref(t)["B5"][1] == 1.123456789012345


# --- how a table is named ---
def test_two_tables_on_one_sheet_are_numbered_from_one():
    wb = Writer()
    ws = wb.active
    ws.title = "Population"
    ws["A1"] = "Resident population by age group"
    ws.cell(3, 1, "Age")
    for j, y in enumerate([2021, 2022, 2023]):
        ws.cell(3, 2 + j, y)
    for i, name in enumerate(["0-14", "15-64", "65+"]):
        ws.cell(4 + i, 1, name)
        for j in range(3):
            ws.cell(4 + i, 2 + j, 100.5 + 10 * i + j)
    ws["A10"] = "Live births by age of mother"
    ws.cell(12, 1, "Age of mother")
    for j, y in enumerate([2021, 2022, 2023]):
        ws.cell(12, 2 + j, y)
    for i, name in enumerate(["15-19", "20-24", "25-29"]):
        ws.cell(13 + i, 1, name)
        for j in range(3):
            ws.cell(13 + i, 2 + j, 50.5 + 10 * i + j)
    pf, _ = tables(wb.save())
    assert [pt.table.table_id for pt in pf.tables] == ["Population_1", "Population_2"]
    assert [pt.table.title for pt in pf.tables] == ["Resident population by age group", "Live births by age of mother"]


def test_a_single_table_takes_the_name_of_its_sheet_and_sheets_that_clash_are_numbered():
    wb = Writer()
    wb.sheets = []
    for name in ["Tab 1", "Tab-1", "Tab_1", "Other"]:
        ws = wb.create_sheet(name)
        ws["A1"] = f"Resident population by age group ({name})"
        ws.cell(3, 1, "Age")
        for j, y in enumerate([2021, 2022, 2023]):
            ws.cell(3, 2 + j, y)
        for i, age in enumerate(["0-14", "15-64", "65+"]):
            ws.cell(4 + i, 1, age)
            for j in range(3):
                ws.cell(4 + i, 2 + j, 100.5 + 10 * i + j)
    pf, _ = tables(wb.save())
    ids = [pt.table.table_id for pt in pf.tables]
    assert ids == ["Tab_1", "Tab_1_2", "Tab_1_3", "Other"] and len(set(ids)) == 4


# --- the contents sheet gives the Albanian titles ---
def test_the_contents_sheet_names_the_tables_that_have_no_title_of_their_own():
    wb = Writer()
    wb.sheets = []
    contents = wb.create_sheet("Përmbajtja")
    contents["A1"] = "Përmbajtja / Contents"
    contents.cell(3, 1, "Tabela 1")
    contents.cell(3, 2, "Popullsia sipas grupmoshës")
    contents.cell(4, 1, "Tab 2")
    contents.cell(4, 2, "Lindjet e gjalla sipas moshës së nënës")
    contents.cell(5, 1, "Tabela 3")
    contents.cell(5, 2, "Ky titull nuk perdoret")
    for k, name in enumerate(["Tabela 1", "Tabela 2", "Tabela 3"]):
        ws = wb.create_sheet(name)
        r = 1
        if k == 2:
            ws["A1"] = "Households by size"
            r = 3
        ws.cell(r, 1, "Age")
        for j, y in enumerate([2021, 2022, 2023]):
            ws.cell(r, 2 + j, y)
        for i, age in enumerate(["0-14", "15-64", "65+"]):
            ws.cell(r + 1 + i, 1, age)
            for j in range(3):
                ws.cell(r + 1 + i, 2 + j, 100.5 + 10 * i + j + k)
    pf, found = tables(wb.save())
    assert [pt.table.sheet for pt in pf.tables] == ["Tabela 1", "Tabela 2", "Tabela 3"]
    assert [t.title_sq for t in found] == ["Popullsia sipas grupmoshës", "Lindjet e gjalla sipas moshës së nënës", None]
    assert found[2].title_en == "Households by size"
    assert pf.meta["contents"] == {1: "Popullsia sipas grupmoshës", 2: "Lindjet e gjalla sipas moshës së nënës",
                                    3: "Ky titull nuk perdoret"}


# --- boundaries: counts, caps and the columns that appear only when there is something to put in them ---
def small_table(rows, header=("Category", 2021, 2022, 2023), title="Number of enterprises"):
    wb = Writer()
    ws = wb.active
    ws["A1"] = title
    for j, h in enumerate(header):
        ws.cell(3, 1 + j, h)
    for i, row in enumerate(rows):
        for j, v in enumerate(row):
            ws.cell(4 + i, 1 + j, v)
    return wb.save()


def test_a_row_without_a_year_among_years_down_the_rows_gives_no_values():
    """An 'Average' row under the years has no month to belong to; it is left out, and the years are still read."""
    wb = Writer()
    ws = wb.active
    ws["A1"] = "Arrivals of foreign citizens by month"
    ws.cell(4, 1, "Year")
    for j, h in enumerate(EN_MONTHS):
        ws.cell(4, 2 + j, h)
    for i, label in enumerate([2019, 2020, 2021, 2022, 2023, "Average"]):
        ws.cell(5 + i, 1, label)
        for j in range(len(EN_MONTHS)):
            ws.cell(5 + i, 2 + j, 1000 * (i + 1) + j + 0.5)
    _, (t,) = tables(wb.save())
    assert t.spec.orientation == "month_by_year"
    assert sorted(set(t.df["period"])) == sorted(f"{y}-{m:02d}" for y in range(2019, 2024) for m in range(1, 5))
    assert len(t.df) == 20 and not t.df["value"].isna().any()


def test_a_hierarchy_written_as_indentation_has_a_level_column_without_any_codes():
    rows = [("Food", 10.5, 11.5, 12.5), ("  Milk", 4.5, 5.5, 6.5), ("    Cheese", 1.5, 2.5, 3.5), ("  Bread", 2.5, 3.5, 4.5), ("Fuel", 8.5, 9.5, 10.5)]
    _, (t,) = tables(small_table(rows))
    assert "level" in t.df.columns and "code" not in t.df.columns
    assert sorted(set(zip(t.df["category"], t.df["level"].astype(int)))) == [("Bread", 2), ("Cheese", 3), ("Food", 1), ("Fuel", 1), ("Milk", 2)]


def test_a_table_without_any_hierarchy_has_no_level_column():
    rows = [("Industry", 10.5, 11.5, 12.5), ("Trade", 4.5, 5.5, 6.5), ("Transport", 1.5, 2.5, 3.5), ("Services", 2.5, 3.5, 4.5)]
    _, (t,) = tables(small_table(rows))
    assert "level" not in t.df.columns and "section" not in t.df.columns


def test_cells_with_text_are_counted_one_by_one():
    rows = [("Industry", 10.5, "see table 2", 12.5), ("Trade", 4.5, 5.5, "see note"), ("Transport", 1.5, 2.5, 3.5), ("Services", 2.5, 3.5, 4.5)]
    _, (t,) = tables(small_table(rows))
    assert "2 value cells contained text instead of a number and were set to missing." in t.warnings
    one = tables(small_table([("Industry", 10.5, "see note", 12.5)] + rows[2:]))[1][0]
    assert "1 value cell contained text instead of a number and was set to missing." in one.warnings


def test_a_table_with_only_numbers_has_no_text_warning():
    rows = [("Industry", 10.5, 11.5, 12.5), ("Trade", 4.5, 5.5, 6.5), ("Transport", 1.5, 2.5, 3.5), ("Services", 2.5, 3.5, 4.5)]
    _, (t,) = tables(small_table(rows))
    assert not [w for w in t.warnings if "contained text" in w]


def test_a_very_large_table_keeps_the_first_rows_that_fit(monkeypatch):
    from instatkit import config

    monkeypatch.setattr(config, "MAX_OBSERVATIONS", 10)
    rows = [(f"Place {i:02d}", 10.5 + i) for i in range(30)]
    _, (t,) = tables(small_table(rows, header=("Category", "Enterprises")))
    assert len(t.df) == 10 and set(t.df["category"]) == {f"Place {i:02d}" for i in range(10)}
    assert "This table is very large: only the first 10 of 30 rows were processed." in t.warnings


def test_the_row_cap_is_shared_between_the_value_columns(monkeypatch):
    from instatkit import config

    monkeypatch.setattr(config, "MAX_OBSERVATIONS", 8)
    rows = [(f"Place {i:02d}", 10.5 + i, 20.5 + i, 30.5 + i, 40.5 + i) for i in range(10)]
    _, (t,) = tables(small_table(rows, header=("Category", 2020, 2021, 2022, 2023)))
    assert len(t.df) == 8 and set(t.df["category"]) == {"Place 00", "Place 01"}            # 8 observations: two rows of four
    monkeypatch.setattr(config, "MAX_OBSERVATIONS", 3)
    _, (t,) = tables(small_table(rows, header=("Category", 2020, 2021, 2022, 2023)))
    assert len(t.df) == 4 and set(t.df["category"]) == {"Place 00"}                        # never fewer than one row


def test_a_single_group_heading_is_kept_in_a_section_column():
    wb = Writer()
    ws = wb.active
    ws["A1"] = "Population by age group and sex"
    ws.cell(3, 1, "Age group")
    ws.cell(3, 2, "Number")
    ws.cell(4, 1, "Males")
    for i, a in enumerate(["0-14", "15-64", "65+"]):
        ws.cell(5 + i, 1, a)
        ws.cell(5 + i, 2, 100.5 + 10 * i)
    _, (t,) = tables(wb.save())
    assert set(t.df["section"]) == {"Males"} and t.dim_info["section"] == {"source": "section", "header": "Section"}
