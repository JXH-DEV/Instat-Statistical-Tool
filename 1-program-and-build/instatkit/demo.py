"""Synthetic, INSTAT-style sample workbooks, built in memory.

They reproduce the layouts of real INSTAT tables (bilingual titles, text dates, merged headers, cover sheets ...) but
contain *invented numbers*. They power the app's demo mode, so nothing needs to be downloaded to try the tool, and the
tests use them as fixtures. Each builder returns ``(bytes, truth)``; ``truth`` holds the values the parser is expected
to recover.
"""

from __future__ import annotations

import random

from .export.xlsx_writer import Workbook
from .i18n import N_

MONTHS_SQ = ["Janar", "Shkurt", "Mars", "Prill", "Maj", "Qershor", "Korrik", "Gusht", "Shtator", "Tetor", "Nëntor", "Dhjetor"]


def months_from(start_year: int, start_month: int, n: int) -> list[tuple[int, int]]:
    out, y, m = [], start_year, start_month
    for _ in range(n):
        out.append((y, m))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def make_cpi_consistent(n_months: int = 30, start: tuple[int, int] = (2023, 1), seed: int = 17):
    """A CPI table whose total is exactly the weighted average of six top-level groups (plus children), base 2020-12=100.

    Lets tests check inflation contributions: sum of contributions must equal the headline annual inflation."""
    rng = random.Random(seed)
    months = months_from(*start, n_months)
    groups = [("01.", "Ushqime dhe pije", 34.0, 0.0045), ("02.", "Pije alkoolike dhe duhan", 4.0, 0.002),
              ("03.", "Veshje dhe këpucë", 6.0, 0.001), ("04.", "Banesa, uji, energjia elektrike, gazi dhe lëndë të tjera djegëse", 20.0, 0.003),
              ("07.", "Transporti", 16.0, 0.0025), ("12.", "Mallra dhe shërbime të tjera", 20.0, 0.0015)]
    wb = Workbook()
    ws = wb.active
    ws["A1"] = "Indeksi i Çmimeve të Konsumit"
    ws["A2"] = "Consumer Price Index"
    ws["A3"] = "(Dhjetor / December 2020 = 100)"
    for j, h in enumerate(["Kodi", "Grupet", "Peshat"] + [f" {m:02d}-{y % 100:02d}" for y, m in months], 1):
        ws.cell(5, j, h)
    idx = {}
    for code, _n, _w, g in groups:
        level, vals = 105.0, []
        for _ in months:
            level *= 1 + g + rng.uniform(-0.003, 0.004)
            vals.append(level)
        idx[code] = vals
    total = [sum(w * idx[c][t] for c, _n, w, _g in groups) / 100 for t in range(n_months)]
    ws.cell(6, 1, "000000")
    ws.cell(6, 2, "Gjithsej")
    ws.cell(6, 3, 100.0)
    for t, v in enumerate(total):
        ws.cell(6, 4 + t, v)
    for i, (code, name, w, _g) in enumerate(groups):
        r = 7 + i
        ws.cell(r, 1, code)
        ws.cell(r, 2, name)
        ws.cell(r, 3, w)
        for t, v in enumerate(idx[code]):
            ws.cell(r, 4 + t, v)
    truth = {"periods": [f"{y:04d}-{m:02d}" for y, m in months], "total": total, "groups": idx,
             "weights": {c: w for c, _n, w, _g in groups}}
    return wb.save(), truth


LFS_AGES = ["15 vjeç e lart", "15-64 vjeç", "15-29 vjeç", "30-64 vjeç"]
LFS_SEX = ["Total", "Meshkuj", "Femra"]


def make_lfs_quarterly(n_quarters: int = 14, start: tuple[int, int] = (2023, 1), seed: int = 3):
    rng = random.Random(seed)
    qs, (y, q) = [], start
    for _ in range(n_quarters):
        qs.append((y, q))
        q += 1
        if q == 5:
            y, q = y + 1, 1
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws["A1"] = "Anketa Tremujore e Forcave të Punës, Tr.1 2023 - Tr.2 2026"
    ws["A2"] = "Labour Force Survey, Q1 2023 - Q2 2026"
    ws["A4"] = "Shkalla e papunësisë"
    ws["A5"] = "Unemployment rate"
    ws.cell(6, 1, "Mosha")
    ws.cell(6, 2, "Gjinia")
    for j, (yy, qq) in enumerate(qs):
        ws.cell(6, 3 + j, f"Tr.{qq}.{yy} Q{qq}.{yy}")
    truth = {}
    r = 7
    for age in LFS_AGES:
        base = rng.uniform(6, 22)
        for k, sex in enumerate(LFS_SEX):
            if k == 0:
                ws.cell(r, 1, age)
            ws.cell(r, 2, sex)
            vals = [base + rng.uniform(-1.5, 1.5) + (0.5 if sex == "Femra" else 0) for _ in qs]
            for t, v in enumerate(vals):
                ws.cell(r, 3 + t, v)
            truth[(age, sex)] = vals
            r += 1
    for rr in range(r, r + 6):
        ws.cell(rr, 1).fill = "FFFFFF"
    return wb.save(), {"periods": [f"{yy:04d}-Q{qq}" for yy, qq in qs], "rows": truth}


GDP_YEARS = [2021, 2022, 2023, 2024]


def make_gdp_workbook(seed: int = 5):
    rng = random.Random(seed)
    wb = Workbook()
    cover = wb.active
    cover.title = "Kapaku-Cover"
    cover["C4"] = "Instituti i Statistikave"
    cover.merge_cells("C4:I4")
    cover["B18"] = "Llogaritë Kombëtare Vjetore (Metoda e Prodhimit)"
    cover.merge_cells("B18:H18")
    cover["B20"] = "Produkti i Brendshëm Bruto 2025"
    cover["B24"] = "Publikuar: 29.06.2026"
    cover["B25"] = "Përditësimi i fundit: Qershor 2026"
    cover["B47"] = "© Instituti i Statistikave, Tiranë 2026"
    cover["B48"] = "Riprodhimi dhe shpërndarja e plotë apo e pjesëshme janë të lejuara duke marrë të mirëqënë referimin si burim."
    content = wb.create_sheet("Permbajtja-Content")
    content["A1"] = 1
    content["A3"] = "PËRMBAJTJA"
    content["A6"], content["B6"] = "tab 1", "PRODHIMI I BRENDSHËM BRUTO SIPAS METODËS SË PRODHIMIT"
    content["A7"], content["B7"] = "tab 6", "RRITJA REALE VJETORE E PRODHIMIT TË BRENDSHËM BRUTO SIPAS AKTIVITETIT EKONOMIK"

    t1 = wb.create_sheet("_tab_1")
    t1["A1"] = "PRODHIMI I BRENDSHËM BRUTO SIPAS METODËS SË PRODHIMIT"
    t1["A2"] = "GROSS DOMESTIC PRODUCT BY PRODUCTION APPROACH"
    t1["A3"] = "(2021 – 2025*, me çmime korente, në milion lekë)"
    sq = ["Viti", "Prodhimi", "Konsumi Ndërmjetës", "Vlera e Shtuar Bruto ", "Taksa neto mbi produktet", "PBB me çmimet e tregut "]
    en = ["Year", "Output", "Intermediate Consumption", "Gross Value Added ", "Net taxes on products", "GDP at market prices "]
    for j, (a, b) in enumerate(zip(sq, en), 1):
        t1.cell(5, j, a)
        t1.cell(6, j, b)
    t1["D7"], t1["E7"], t1["F7"] = "(3=1-2)", 4, " 6=(3+4-5)"
    gdp_truth = {}
    for i, yr in enumerate(GDP_YEARS + ["2025*"]):
        r = 8 + i
        out = 2_800_000 + 180_000 * i + rng.uniform(-5000, 5000)
        ic = out * 0.44
        gva = out - ic
        tax = 270_000 + 18_000 * i
        gdp = gva + tax
        t1.cell(r, 1, yr)
        for j, v in enumerate([out, ic, gva, tax, gdp], 2):
            t1.cell(r, j, v)
        gdp_truth[str(yr).rstrip("*")] = {"output": out, "ic": ic, "gva": gva, "tax": tax, "gdp": gdp}
    t1["A14"] = "2025* Gjysëm-finale / Semi-final"

    t6 = wb.create_sheet("_tab_6")
    t6["B2"] = "RRITJA REALE VJETORE E PRODHIMIT TË BRENDSHËM BRUTO SIPAS AKTIVITETIT EKONOMIK"
    t6["B3"] = "ANNUAL REAL GROWTH OF GROSS DOMESTIC PRODUCT BY ECONOMIC ACTIVITY"
    t6["B4"] = "(2021 – 2025*, me çmimet e vitit të mëparshëm)"
    t6["B6"], t6["C6"], t6["D6"] = "Kodi", "NVE Rev.2", "Aktiviteti ekonomik"
    t6["B7"], t6["C7"] = "Code", "Nace Rev.2"
    t6.merge_cells("D6:D7")
    t6["E6"] = "Rritja reale vjetore (%)"
    t6.merge_cells("E6:H6")
    for j, yr in enumerate(GDP_YEARS):
        t6.cell(7, 5 + j, yr)
    t6["I6"] = "Aktiviteti (anglisht)"
    t6.merge_cells("I6:I7")
    acts = [("A1", "01-03", "Bujqësia, pyjet dhe peshku", "Agriculture, forestry and fishing"),
            ("A2", "05-09", "Industria nxjerrëse", "Mining and quarrying"),
            ("A3", "10-33", "Industria përpunuese", "Manufacturing"),
            ("A4", 35, "Energjia elektrike, gazi, avulli", "Electricity, gas, steam"),
            ("A5", "36-39", "Furnizimi me ujë, aktivitete të kanalizimeve", "Water supply, sewerage")]
    growth_truth = {}
    for i, (code, nace, sqn, enn) in enumerate(acts):
        r = 8 + i
        t6.cell(r, 2, code)
        t6.cell(r, 3, nace)
        t6.cell(r, 4, sqn)
        vals = [rng.uniform(-8, 12) for _ in GDP_YEARS]
        for j, v in enumerate(vals):
            t6.cell(r, 5 + j, v)
        t6.cell(r, 9, enn)
        growth_truth[code] = vals
    return wb.save(), {"gdp": gdp_truth, "growth": growth_truth, "years": GDP_YEARS}


def make_trade_monthly(n_months: int = 14, start: tuple[int, int] = (2021, 12), seed: int = 9):
    rng = random.Random(seed)
    months = months_from(*start, n_months)
    wb = Workbook()
    ws = wb.active
    ws.title = "Tabela 5 "
    ws["A1"] = "Qarkullimi i mallrave në tregtinë e jashtme"
    ws["A2"] = "Flow of goods in foreign trade"
    ws["A4"] = "miliardë lekë/billion ALL"
    for j, (y, m) in enumerate(months):
        if j == 0:
            lab = f"{m:02d} - {y % 100:02d}"
        elif m >= 2 and y == 2022 and j < 6:
            lab = f"{m} - {y % 100:02d}"  # unpadded, as in the real file
        else:
            lab = f"{m:02d} - {y % 100:02d}"
        ws.cell(5, 2 + j, lab)
    exp = [30 + rng.uniform(0, 18) for _ in months]
    imp = [80 + rng.uniform(-20, 12) for _ in months]
    rows = [("Eksporte", exp), ("Importe", imp), ("Bilanci tregtar", [a - b for a, b in zip(exp, imp)]),
            ("Përqindja e mbulimit \nCoverage ratio (%)", [100 * a / b for a, b in zip(exp, imp)])]
    for i, (lab, vals) in enumerate(rows):
        ws.cell(6 + i, 1, lab)
        for j, v in enumerate(vals):
            ws.cell(6 + i, 2 + j, v)
    return wb.save(), {"periods": [f"{y:04d}-{m:02d}" for y, m in months], "exports": exp, "imports": imp}


AGE_GROUPS = [f"{a}-{a + 4}" for a in range(0, 85, 5)] + ["85+"]


def make_population(years=(2024, 2025, 2026), seed: int = 13):
    rng = random.Random(seed)
    wb = Workbook()
    ws = wb.active
    ws.title = "Popull. sp. grm. gjin. 1 janar"
    ws["A1"] = "* Popullsia më 1 janar sipas grupmoshës dhe gjinisë"
    ws["A2"] = "* Population on first January by age group and sex"
    ws["A4"] = "Grupmosha/ Age group"
    ws.merge_cells("A4:A5")
    truth = {}
    for k, yr in enumerate(years):
        c0 = 2 + 3 * k
        ws.cell(4, c0, str(yr))
        ws.merge_cells(start_row=4, start_column=c0, end_row=4, end_column=c0 + 2)
        ws.cell(5, c0, "M")
        ws.cell(5, c0 + 1, "F")
        ws.cell(5, c0 + 2, "Gjithsej/Total")
    n = len(AGE_GROUPS)
    for i, age in enumerate(AGE_GROUPS):
        r = 6 + i
        ws.cell(r, 1, age)
    tot = {}
    for k, yr in enumerate(years):
        c0 = 2 + 3 * k
        m_tot = f_tot = 0
        for i, age in enumerate(AGE_GROUPS):
            m = int(rng.uniform(25000, 85000))
            f = int(rng.uniform(25000, 90000))
            ws.cell(6 + i, c0, m)
            ws.cell(6 + i, c0 + 1, f)
            ws.cell(6 + i, c0 + 2, m + f)
            truth[(yr, age)] = (m, f, m + f)
            m_tot, f_tot = m_tot + m, f_tot + f
        ws.cell(6 + n, c0, m_tot)
        ws.cell(6 + n, c0 + 1, f_tot)
        ws.cell(6 + n, c0 + 2, m_tot + f_tot)
        tot[yr] = (m_tot, f_tot, m_tot + f_tot)
    ws.cell(6 + n, 1, "Gjithsej/Total")
    ws.cell(6 + n + 3, 1, "*Shënim: Vlerësime të popullsisë sipas regjistrimit 2023.")
    ws.cell(6 + n + 5, 1, "*Note: Population estimates based on the 2023 census.")
    return wb.save(), {"rows": truth, "totals": tot, "years": list(years)}


def make_month_by_year(years=(2022, 2023, 2024), seed: int = 21):
    rng = random.Random(seed)
    wb = Workbook()
    ws = wb.active
    ws["A1"] = "Ardhjet e shtetasve të huaj sipas muajve"
    ws["A2"] = "Arrivals of foreign citizens by month"
    ws.cell(4, 1, "Muaji/Month")
    for j, y in enumerate(years):
        ws.cell(4, 2 + j, y)
    truth = {}
    for i, name in enumerate(MONTHS_SQ):
        ws.cell(5 + i, 1, name)
        for j, y in enumerate(years):
            v = int(rng.uniform(100_000, 900_000))
            ws.cell(5 + i, 2 + j, v)
            truth[(y, i + 1)] = v
    return wb.save(), {"rows": truth, "years": list(years)}


def make_cross_section():
    wb = Workbook()
    ws = wb.active
    ws["A1"] = "Paga mesatare mujore bruto sipas aktiviteteve ekonomike dhe gjinisë, 2023"
    ws["A2"] = "Gross average monthly wage by economic activity and sex, 2023"
    ws["A3"] = "(në lekë)"
    for j, h in enumerate(["Aktiviteti ekonomik/ Economic activity", "Gjithsej/Total", "Meshkuj/Males", "Femra/Females"], 1):
        ws.cell(5, j, h)
    data = [("Bujqësia", 52000, 54000, 48500), ("Industria", 65000, 68000, 57000), ("Ndërtimi", "..", 71000, "-"),
            ("Tregtia", "61 500", "64 200", "58 800"), ("Transporti", 70500, 72000, 66000), ("Arsimi", 79000, 76000, 80500)]
    for i, row in enumerate(data):
        for j, v in enumerate(row, 1):
            ws.cell(6 + i, j, v)
    ws.cell(13, 1, "Burimi: INSTAT")
    return wb.save(), {"rows": data}


DEMOS = {
    "cpi": (N_("Consumer Price Index: monthly, by COICOP group"), "demo-consumer-price-index.xlsx",
            lambda: make_cpi_consistent(48, (2022, 1))[0]),
    "lfs": (N_("Labour Force Survey: quarterly unemployment rate"), "demo-labour-force-survey.xlsx",
            lambda: make_lfs_quarterly(20, (2021, 1))[0]),
    "gdp": (N_("National accounts: a workbook with a cover, contents and several tabs"), "demo-national-accounts.xlsx",
            lambda: make_gdp_workbook()[0]),
    "trade": (N_("Foreign trade: monthly flows (transposed layout)"), "demo-foreign-trade.xlsx",
              lambda: make_trade_monthly(36, (2021, 12))[0]),
    "population": (N_("Population by age group and sex (two-level header)"), "demo-population.xlsx",
                   lambda: make_population()[0]),
    "tourism": (N_("Tourist arrivals: months down the rows, years across"), "demo-tourism.xlsx",
                lambda: make_month_by_year()[0]),
    "wages": (N_("Average wage by activity and sex: one period, with '..' markers"), "demo-wages.xlsx",
              lambda: make_cross_section()[0]),
}
