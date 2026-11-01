"""The spreadsheet readers: every supported format, and files that are broken or hostile.

A bad file must end as an ``UnreadableWorkbook`` (or an error line on the result), never as an unhandled exception, a
hang or a large allocation."""

from __future__ import annotations

import io
import time
import zipfile

import pytest

from instatkit import config
from instatkit.excel.grid import read_workbook, sniff_format
from instatkit.excel.raw import UnreadableWorkbook
from instatkit.export.xlsx_writer import Workbook as Writer
from instatkit.pipeline import process_bytes

from .conftest import process_workbook_bytes


def _xlsx(rows, merges=(), title="Sheet1") -> bytes:
    wb = Writer()
    ws = wb.active
    ws.title = title
    for r, row in enumerate(rows, 1):
        for c, v in enumerate(row, 1):
            ws.cell(r, c, v)
    for ref in merges:
        ws.merge_cells(ref)
    return wb.save()


SIMPLE = [["Title of the table"], [], ["Region", " 01-23", " 02-23", " 03-23"], ["Tirana", 1.5, 2.5, 3.5], ["Durrës", 4, 5, 6]]


def test_xlsx_round_trip():
    wb = read_workbook(_xlsx(SIMPLE), "t.xlsx")
    assert wb.format == "xlsx" and wb.sheets[0].n_rows >= 4
    assert any(v == "Tirana" for row in wb.sheets[0].cells for v in row)


@pytest.mark.parametrize("data, name", [
    (b"", "a.xlsx"),
    (b"not a spreadsheet at all", "a.xlsx"),
    (b"\x00\x01\x02\x03" * 100, "a.xlsx"),
    (b"<html><body>404 Not Found</body></html>", "a.xlsx"),
    (b"PK\x03\x04" + b"\x00" * 50, "a.xlsx"),                  # a zip header and nothing else
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 200, "a.xls"),
])
def test_garbage_is_reported_not_raised(data, name):
    with pytest.raises(UnreadableWorkbook) as info:
        read_workbook(data, name)
    assert str(info.value)                                   # the message is fit to show the user
    pf = process_bytes(data, name)                           # the pipeline turns it into an error line
    assert not pf.ok and pf.errors


def test_truncated_xlsx():
    data = _xlsx(SIMPLE)
    for cut in (len(data) // 2, len(data) - 30, 40):
        pf = process_bytes(data[:cut], "cut.xlsx")
        assert not pf.ok and pf.errors


def test_html_error_page_is_named_as_such():
    with pytest.raises(UnreadableWorkbook, match="(?i)web page"):
        read_workbook(b"<!DOCTYPE html><html><body>Service unavailable</body></html>", "x.xlsx")


def test_unsupported_formats_have_a_clear_message():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("content.xml", "<x/>")
        z.writestr("mimetype", "application/vnd.oasis.opendocument.spreadsheet")
    with pytest.raises(UnreadableWorkbook, match=r"\.ods"):
        read_workbook(buf.getvalue(), "x.ods")
    assert sniff_format(b"PK\x03\x04junk") == "corrupt"


def test_xml_entities_are_refused():
    """A DOCTYPE with entities is the 'billion laughs' attack; the readers refuse any DOCTYPE."""
    bomb = ('<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;">'
            '<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;">]><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>&c;</t></is></c></row></sheetData></worksheet>')
    good = _xlsx(SIMPLE)
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(good)) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            dst.writestr(item.filename, bomb if item.filename == "xl/worksheets/sheet1.xml" else src.read(item.filename))
    t0 = time.perf_counter()
    with pytest.raises(UnreadableWorkbook):
        read_workbook(out.getvalue(), "bomb.xlsx")
    assert time.perf_counter() - t0 < 2


def test_oversized_xml_is_cut_off(monkeypatch):
    monkeypatch.setattr(config, "MAX_XML_BYTES", 200_000)
    good = _xlsx(SIMPLE)
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(good)) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            if item.filename == "xl/worksheets/sheet1.xml":
                filler = '<row r="2"><c r="A2"><v>1</v></c></row>' * 20_000
                dst.writestr(item.filename, '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
                             + filler + "</sheetData></worksheet>")
            else:
                dst.writestr(item.filename, src.read(item.filename))
    with pytest.raises(UnreadableWorkbook):
        read_workbook(out.getvalue(), "big.xlsx")


def test_row_and_column_caps(monkeypatch):
    monkeypatch.setattr(config, "MAX_ROWS", 30)
    monkeypatch.setattr(config, "MAX_COLS", 8)
    rows = [["Region"] + [f" {m:02d}-23" for m in range(1, 13)]] + [[f"R{i}"] + [float(i + j) for j in range(12)] for i in range(100)]
    wb = read_workbook(_xlsx(rows), "wide.xlsx")
    g = wb.sheets[0]
    assert g.n_rows <= 30 and g.n_cols <= 8 and g.truncated


def test_many_merged_ranges_stay_bounded(monkeypatch):
    """A sheet with a huge number of merged ranges is read in bounded time."""
    monkeypatch.setattr(config, "MAX_MERGES", 50)
    rows = [["Title"], [], ["Region", " 01-23", " 02-23"]] + [[f"R{i}", 1.0 + i, 2.0 + i] for i in range(300)]
    merges = [f"E{r}:F{r}" for r in range(1, 301)]
    wb = read_workbook(_xlsx(rows, merges), "merges.xlsx")
    assert len(wb.sheets[0].merged) <= 50 and wb.sheets[0].truncated
    t0 = time.perf_counter()
    pf = process_bytes(_xlsx(rows, merges), "merges.xlsx")
    assert time.perf_counter() - t0 < 5
    assert pf.ok, pf.errors


def test_odd_header_cells_do_not_lose_the_file():
    """Header cells such as '5 tremujor 2023' or '01-0000' are not periods and do not abort the file."""
    rows = [["Title of the table"], [], ["Region", "5 tremujor 2023", "01-0000", "5-1000", "2025/24"],
            ["Tirana", 1.0, 2.0, 3.0, 4.0], ["Durrës", 5.0, 6.0, 7.0, 8.0], ["Vlorë", 9.0, 8.0, 7.0, 6.0]]
    pf = process_workbook_bytes(_xlsx(rows))
    assert not any("Error" in e for e in pf.errors), pf.errors


def test_asterisk_header_does_not_hang():
    rows = [["T"], [], ["Region", "2020" + "*" * 50 + "x", "2021", "2022"], ["Tirana", 1.0, 2.0, 3.0], ["Durrës", 4.0, 5.0, 6.0]]
    t0 = time.perf_counter()
    process_workbook_bytes(_xlsx(rows))
    assert time.perf_counter() - t0 < 5


def test_csv_with_semicolons_and_decimal_commas():
    text = "Rajoni;2020;2021;2022\nTirana;1,5;2,5;3,5\nDurrës;4,5;5,5;6,5\nVlorë;7,5;8,5;9,5\n"
    pf = process_workbook_bytes(text.encode("utf-8"), "t.csv")
    assert pf.ok, pf.errors
    vals = sorted(pf.tables[0].table.df["value"].dropna().tolist())
    assert vals[0] == pytest.approx(1.5) and vals[-1] == pytest.approx(9.5)


def test_csv_with_bom_and_cp1250():
    text = "Rajoni,2020,2021,2022\nShkodër,1,2,3\nDurrës,4,5,6\nVlorë,7,8,9\n"
    for payload in (b"\xef\xbb\xbf" + text.encode("utf-8"), text.encode("cp1250")):
        pf = process_workbook_bytes(payload, "t.csv")
        assert pf.ok, pf.errors
        assert "Shkodër" in set(pf.tables[0].table.df["region_orig"])        # the label as written, ë intact


def test_spreadsheetml_2003():
    xml = ('<?xml version="1.0"?><Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" '
           'xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet"><Worksheet ss:Name="Tabela"><Table>'
           '<Row><Cell><Data ss:Type="String">Titulli i tabelës</Data></Cell></Row>'
           '<Row><Cell><Data ss:Type="String">Rajoni</Data></Cell><Cell><Data ss:Type="String"> 01-23</Data></Cell>'
           '<Cell><Data ss:Type="String"> 02-23</Data></Cell><Cell><Data ss:Type="String"> 03-23</Data></Cell></Row>'
           '<Row><Cell><Data ss:Type="String">Tiranë</Data></Cell><Cell><Data ss:Type="Number">1.5</Data></Cell>'
           '<Cell><Data ss:Type="Number">2.5</Data></Cell><Cell><Data ss:Type="Number">3.5</Data></Cell></Row>'
           '<Row><Cell><Data ss:Type="String">Durrës</Data></Cell><Cell><Data ss:Type="Number">4</Data></Cell>'
           '<Cell><Data ss:Type="Number">5</Data></Cell><Cell><Data ss:Type="Number">6</Data></Cell></Row>'
           '</Table></Worksheet></Workbook>')
    assert sniff_format(xml.encode(), "t.xls") == "spreadsheetml"
    pf = process_workbook_bytes(xml.encode("utf-8"), "t.xls")
    assert pf.ok, pf.errors
    assert pf.tables[0].table.df["value"].dropna().sum() == pytest.approx(22.5)


def test_legacy_xls_files():
    xlwt = pytest.importorskip("xlwt")
    book = xlwt.Workbook(encoding="utf-8")
    sh = book.add_sheet("Tabela")
    sh.write(0, 0, "Titulli i tabelës")
    for c, h in enumerate(["Rajoni", " 01-23", " 02-23", " 03-23"]):
        sh.write(2, c, h)
    for r, (name, vals) in enumerate([("Tiranë", (1.5, 2.5, 3.5)), ("Durrës", (4, 5, 6)), ("Vlorë", (7, 8, 9))], 3):
        sh.write(r, 0, name)
        for c, v in enumerate(vals, 1):
            sh.write(r, c, v)
    buf = io.BytesIO()
    book.save(buf)
    assert sniff_format(buf.getvalue(), "t.xls") == "xls"
    pf = process_workbook_bytes(buf.getvalue(), "t.xls")
    assert pf.ok, pf.errors
    assert pf.tables[0].table.df["value"].dropna().sum() == pytest.approx(1.5 + 2.5 + 3.5 + 4 + 5 + 6 + 7 + 8 + 9)
    assert set(pf.tables[0].table.df["period"]) == {"2023-01", "2023-02", "2023-03"}


def test_xls_without_xlrd_is_explained(monkeypatch):
    import builtins

    real = builtins.__import__

    def fake(name, *a, **k):
        if name == "xlrd":
            raise ImportError("no xlrd")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake)
    with pytest.raises(UnreadableWorkbook, match="xlrd"):
        read_workbook(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 600, "t.xls")


def test_footnote_inside_the_table_is_not_a_section():
    """A one-cell footnote between data rows is not a section heading."""
    rows = [["Title"], [], ["Region", " 01-23", " 02-23", " 03-23"], ["Tirana", 1.5, 2.5, 3.5], ["(*) preliminary data"],
            ["Durrës", 4.0, 5.0, 6.0], ["Vlorë", 7.0, 8.0, 9.0]]
    pf = process_workbook_bytes(_xlsx(rows))
    assert pf.ok, pf.errors
    sections = {s for s in pf.tables[0].table.df.get("section", []) if s}
    assert not any("preliminary" in s for s in sections)


def test_quarter_columns_with_years_down_the_rows_are_quarterly():
    """freq came out as 'M' when quarters were the column headers and years ran down the rows."""
    rows = [["Title of the table"], [], ["Year", "Q1", "Q2", "Q3", "Q4"], [2021, 1.0, 2.0, 3.0, 4.0], [2022, 5.0, 6.0, 7.0, 8.0],
            [2023, 9.0, 10.0, 11.0, 12.0]]
    pf = process_workbook_bytes(_xlsx(rows))
    assert pf.ok, pf.errors
    t = pf.tables[0]
    assert t.profile.freq == "Q", (t.profile.freq, t.table.spec.orientation)
    assert set(t.table.df["freq"]) == {"Q"} and len(t.table.df) == 12


def test_percent_fractions_have_no_float_noise():
    """A value stored as 7% reads as 7, not 7.000000000000001."""
    from instatkit.export.xlsx_writer import Style

    wb = Writer()
    ws = wb.active
    for r, row in enumerate([["Share of imports, %"], [], ["Region", "2020", "2021", "2022"]], 1):
        for c, v in enumerate(row, 1):
            ws.cell(r, c, v)
    data = [("Tirana", 0.07, 0.29, 0.58), ("Durrës", 0.14, 0.21, 0.35), ("Vlorë", 0.28, 0.07, 0.43)]
    pct = Style(fmt="0.0%")
    for r, (name, *vals) in enumerate(data, 4):
        ws.cell(r, 1, name)
        for c, v in enumerate(vals, 2):
            ws.cell(r, c, v).style = pct
    pf = process_workbook_bytes(wb.save())
    assert pf.ok, pf.errors
    got = sorted(pf.tables[0].table.df["value"].dropna().tolist())
    assert got == sorted(round(v * 100, 10) for _n, *vs in data for v in vs)


def _prices_by_code(header, code_style="mixed"):
    rows = [["Indekset tremujore të çmimeve", "Quarterly price indices"], [], ["NVE", "Përshkrimi", *header]]
    names = [("", "Gjithsej"), ("B", "Industri Nxjerrëse"), ("06", "Nxjerrja e naftës"), ("07", "Nxjerrja e mineraleve"),
             ("C", "Industria Përpunuese"), ("10", "Përpunimi i produkteve ushqimore"), ("11", "Prodhimi i pijeve"), ("21", "Farmaceutike")]
    for k, (code, name) in enumerate(names):
        rows.append([code or None, name, *[100.0 + k + j * 0.5 for j in range(len(header))]])
    return rows


def test_quarters_written_year_dash_number_are_quarters():
    """'2017-4' and '2018-1' in a header were read as April 2017 and January 2018: a "quarterly" table that came out monthly."""
    header = [f"{y}-{q}" for y in (2018, 2019, 2020) for q in (1, 2, 3, 4)]
    pf = process_workbook_bytes(_xlsx(_prices_by_code(header)))
    assert pf.ok, pf.errors
    t = pf.tables[0]
    assert t.profile.freq == "Q" and t.profile.n_periods == 12
    assert set(t.table.df["freq"]) == {"Q"} and "2019-Q3" in set(t.table.df["period"])


def test_code_columns_beside_the_names_do_not_swallow_the_rows():
    """Codes kept as text ('06', '10') with a few stored as numbers (21) stopped the label columns, so every name was lost."""
    header = [f"{y}" for y in (2018, 2019, 2020, 2021)]
    pf = process_workbook_bytes(_xlsx(_prices_by_code(header)))
    assert pf.ok, pf.errors
    df = pf.tables[0].table.df
    assert not df.duplicated(["series_id", "period"]).any()
    assert df["series_id"].nunique() == 8
    assert not any("duplicate" in c.key and c.status == "fail" for c in pf.tables[0].analysis.checks)


# --- layouts found in real INSTAT files (each of these was read wrongly before) ---------------------------------------------

def _no_collisions(pf):
    assert pf.ok, pf.errors
    for pt in pf.tables:
        assert not pt.table.df.duplicated(["series_id", "period"]).any(), pt.table.sheet
        assert not any(c.key == "duplicate observations" and c.status == "fail" for c in pt.analysis.checks)


def test_a_stray_number_in_a_title_row_is_not_a_table():
    """A page number left in a title row of INSTAT's own CPI file became a second, one-value 'table'."""
    rows = [["Ndryshimet vjetore të indeksit", *[None] * 49, "25"], ["Annual change of the index"], [],
            ["Kodi", "Grupet", " 01-17  01-16", " 02-17  02-16", " 03-17  03-16", " 04-17  04-16"], []]
    rows += [[f"0{i}.", f"Grupi {i}", *[1.0 + i + j * 0.1 for j in range(4)]] for i in range(1, 7)]
    pf = process_workbook_bytes(_xlsx(rows))
    assert pf.ok, pf.errors
    assert len(pf.tables) == 1 and pf.tables[0].profile.n_obs == 24


def test_group_heading_rows_become_a_dimension():
    """'Gjithsej / Meshkuj / Femra' rows with the same age groups under each split the sheet into pieces and lost the sex."""
    rows = [["Shkalla e papunësisë"], ["Unemployment rate"], [], ["Grupmosha", "2018", "2019", "2020", None, "Age group"]]
    for sq, en in (("Gjithsej", "Total"), ("Meshkuj", "Male"), ("Femra", "Female")):
        rows.append([sq, None, None, None, None, en])
        for k, age in enumerate(["15-29", "30-64", "15-64", "15+"]):
            rows.append([age, 10.0 + k, 11.0 + k, 12.0 + k, None, age])
    pf = process_workbook_bytes(_xlsx(rows))
    _no_collisions(pf)
    assert len(pf.tables) == 1
    t = pf.tables[0]
    assert t.profile.n_obs == 36 and {d.role for d in t.profile.dims} >= {"age_group", "sex"}
    assert set(t.table.df["sex"]) == {"Total", "Males", "Females"} or set(t.table.df["sex"]) == {"Total", "Male", "Female"}


def test_a_breakdown_under_its_parent_is_kept_apart():
    """'Other citizenship 671' followed by its own breakdown (Greece, Turkey ...) repeated the countries listed above, and the two
    values for Greece were merged into one series without a word."""
    rows = [["DURRËS"], [], ["Shtetësia", "Gjithsej", "Meshkuj", "Femra"],
            ["Gjithsej Total", 1000, 600, 400], ["Greqi Greece", 100, 60, 40], ["Itali Italy", 200, 120, 80],
            ["Shtetësi tjetër", 300, 180, 120], ["Greqi Greece", 90, 55, 35], ["Itali Italy", 110, 65, 45], ["Shtet tjetër", 100, 60, 40],
            ["Pa shtetësi", 400, 240, 160]]
    pf = process_workbook_bytes(_xlsx(rows))
    _no_collisions(pf)
    t = pf.tables[0].table
    df, label = t.df, t.dim_columns[0]
    df = df[df["sex"] == "Total"]
    greece = df[df[label].str.contains("Greece")]
    assert sorted(greece["value"]) == [90.0, 100.0], "both values for Greece are kept, as two series"
    assert sorted(greece["block"]) == ["", "Other citizenship"] or sorted(greece["block"]) == ["", "Shtetësi tjetër"]
    main = df[df["block"] == ""]
    assert main["value"].sum() == 1000 + 100 + 200 + 300 + 400   # the main list still adds up: the breakdown is not in it
    assert main[label].str.contains("Without|Pa shtet").any(), "'Pa shtetësi' comes after the breakdown and is back in the main list"


def test_the_same_rows_twice_on_a_sheet_are_two_blocks():
    """Counts, then the same rows as percentages: both were read as one series with two values for every year."""
    rows = [["Të huajt me leje qëndrimi"], ["Foreigners with residence permits"], [], ["Vitet", "2021", "2022", "2023"], [],
            ["Gjithsej", 100.0, 120.0, 140.0], [], ["Punësim", 50.0, 60.0, 70.0], ["Studim", 50.0, 60.0, 70.0], [], [],
            ["Gjithsej", 100.0, 100.0, 100.0], ["Punësim", 50.0, 50.0, 50.0], ["Studim", 50.0, 50.0, 50.0]]
    pf = process_workbook_bytes(_xlsx(rows))
    _no_collisions(pf)
    t = pf.tables[0]
    assert t.table.df["block"].nunique() == 2 and any("repeat" in x for x in t.table.warnings)
    assert t.profile.n_obs == 18
    assert "block" not in {c.params.get("dim") for c in t.analysis.charts}      # counts next to shares are not compared


def test_an_annual_block_above_a_quarterly_block_is_two_tables():
    """The annual figures and, below them, the same figures by quarter (year only on the first quarter's row) were one table
    with periods that did not make sense."""
    rows = [["Rritja reale"], ["Real growth"], [], ["Viti", None, "Bujqësia", "Industria", "Ndërtimi"]]
    rows += [[y, None, 1.0 + k, 2.0 + k, 3.0 + k] for k, y in enumerate(range(2019, 2023))]
    rows.append([])
    for k, y in enumerate(range(2019, 2022)):
        for q in range(1, 5):
            rows.append([y if q == 1 else None, f"T{q}", 4.0 + k + q * 0.1, 5.0 + k + q * 0.1, 6.0 + k + q * 0.1])
    pf = process_workbook_bytes(_xlsx(rows))
    _no_collisions(pf)
    assert len(pf.tables) == 2
    annual, quarterly = sorted(pf.tables, key=lambda t: t.profile.n_periods)
    assert annual.profile.freq == "A" and annual.profile.n_periods == 4
    assert quarterly.profile.freq == "Q" and quarterly.profile.n_periods == 12 and quarterly.profile.first_period == "2019-Q1"
    assert annual.table.title != quarterly.table.title            # the two are told apart in the table list


def test_a_period_written_once_applies_to_the_rows_below_it():
    """'T1.2023' on the first of three rows (Total, Male, Female) left the other two rows without a period."""
    rows = [["Struktura"], ["Structure"], [], ["Periudha", "Gjinia", "Punësuar", "Të papunë"]]
    for q in range(1, 5):
        for k, sex in enumerate(["Gjithsej / Total", "Meshkuj / Male", "Femra / Female"]):
            rows.append([f"T{q}.2023 / Q{q}.2023" if k == 0 else None, sex, 50.0 + q + k, 5.0 + q + k])
    pf = process_workbook_bytes(_xlsx(rows))
    _no_collisions(pf)
    t = pf.tables[0]
    assert t.table.spec.orientation == "periods_in_rows" and t.profile.freq == "Q"
    assert set(t.table.df["period"]) == {f"2023-Q{q}" for q in range(1, 5)} and t.profile.n_obs == 4 * 3 * 2


def test_roman_numeral_quarters_make_a_quarterly_series():
    """INSTAT's wage table labels its columns II/23, III/23, I/24 ... Read as one year each (2023) they were 13 one-point series."""
    quarters = [f"{r}/{y}" for y in (23, 24, 25, 26) for r in ("I", "II", "III", "IV")][1:13]  # II/23 ... I/26: twelve quarters
    rows = [["Average monthly gross wage per employee"], [], ["Category", *quarters],
            ["All employees", *[70000.5 + 1000 * i for i in range(12)]], ["Public sector", *[82000.5 + 900 * i for i in range(12)]]]
    pf = process_workbook_bytes(_xlsx(rows))
    assert pf.ok, pf.errors
    df = pf.tables[0].table.df
    assert pf.tables[0].profile.freq == "Q" and df["period"].nunique() == 12 and df["series_id"].nunique() == 2
    assert df["period"].min() == "2023-Q2" and df["period"].max() == "2026-Q1"
    first = df[(df["period"] == "2023-Q2") & (df["category"] == "All employees")]["value"].iloc[0]
    last = df[(df["period"] == "2026-Q1") & (df["category"] == "All employees")]["value"].iloc[0]
    assert (first, last) == (70000.5, 81000.5)


def test_permit_values_are_thousand_lek_not_buildings():
    """The sheet says "000Lekë / 000ALL" under a title about building permits: the subject of the title must not win over the stated unit."""
    rows = [["Vlera e përafërt e lejeve të ndërtimit të lëshuara"], ["Approximate value of building permits issued"], ["000Lekë / 000ALL"], [],
            ["Kategoria", "IV - 22", "I - 23", "II - 23", "III - 23"],
            ["Gjithsej", 11744012, 26607270, 23108183, 19000000], ["I. Ndërtesa", 9515472, 20006920, 19122014, 15000000],
            ["II. Inxhinieri civile", 2228540, 6600350, 3986169, 4000000]]
    pf = process_workbook_bytes(_xlsx(rows))
    assert pf.ok, pf.errors
    pt = pf.tables[0]
    info = pt.profile.measures[0]
    assert (info.unit_code, info.scale) == ("ALL", 1000.0), (info.unit_code, info.scale)
    assert pt.table.df["period"].min() == "2022-Q4" and pt.profile.freq == "Q"
