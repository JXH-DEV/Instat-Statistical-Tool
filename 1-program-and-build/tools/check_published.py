"""Compare what the program reads from INSTAT's Excel tables with the figures INSTAT states in its press releases.

    python tools/check_published.py
    python tools/check_published.py --out docs/PUBLISHED_COMPARISON.md
    python tools/check_published.py --only cpi,gdp     # some of: cpi hicp gdp gdp-annual lfs trade wages tourism building births

The program's own checks only show that a table agrees with itself. This takes the numbers INSTAT wrote into the press release of the same
data (the PDF on the topic page) and finds each one in the table as the program reads it, or works it out the way INSTAT does, for example an
annual change from the index. Results: ``match`` (rounds to the published figure), ``match (rounded levels)`` (INSTAT worked a change out from
levels it had already rounded), ``close`` (a figure the program only approximates, within a stated tolerance), ``differ``, and ``missing`` (the
figure was not found: the release changed layout). The quoted text is printed next to each figure. Exit code 0 only if nothing differs and
nothing is missing.

Releases and tables are fetched through the program's own fetcher and cached. The PDFs are named in this file, so a new month needs the names
updated. Needs ``pip install pypdf``.
"""

from __future__ import annotations

import argparse
import io
import re
import sys
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from instatkit import __version__  # noqa: E402
from instatkit.pipeline import ProcessedFile, ProcessedTable, SourceInfo, process_bytes  # noqa: E402
from instatkit.sources.fetch import Fetcher, FetchError  # noqa: E402
from instatkit.sources.page_links import parse_page, pdf_links  # noqa: E402
from instatkit.sources.search import search_topics  # noqa: E402


# reading what INSTAT states
def to_number(text: str) -> tuple[float, int]:
    """``'+0.96'`` / ``'2,648,505'`` / ``'−3.1'`` -> (value, decimals as published)."""
    s = re.sub(r"[\s,]", "", text.replace("−", "-").replace("–", "-").replace("+", ""))
    return float(s), len(s.split(".")[1]) if "." in s else 0


def clean_pdf_text(text: str) -> str:
    """The text of a PDF with its two usual defects repaired: a space inside a number (``0. 54``, ``+0.9 6``) and line breaks."""
    text = re.sub(r"(\d)\.\s+(?=\d)", r"\1.", text)
    text = re.sub(r"(\d\.\d)\s(\d)(?=\s*(?:percentage|%|percent|pp\b))", r"\1\2", text)
    text = re.sub(r"non\s*-\s*alcoholic", "non-alcoholic", text)
    return re.sub(r"\s+", " ", text)


def norm(name: str) -> str:
    """A name reduced to its letters and digits, so ``'Alcoholic beverages. tobacco'`` and ``'Alcoholic beverages, tobacco'`` are equal."""
    return re.sub(r"[^a-z0-9]+", "", unicodedata.normalize("NFKD", name).lower())


def signed(direction: str, value: float) -> float:
    return -abs(value) if direction.lower().startswith(("decreas", "fall", "fell", "declin")) else abs(value)


def growth_after(flat: str, phrase: str) -> tuple[float, int, str] | None:
    """The change that follows ``phrase`` in the text ("“Construction” activity increased by 1.37 %") with its sign, precision and quote."""
    m = re.search(rf"{re.escape(phrase)}[”\"]?[^%]{{0,90}}?(increas\w*|decreas\w*)\D{{0,14}}?(\d+\.\d+)\s*%", flat, re.I)
    if not m:
        return None
    value, decimals = to_number(m.group(2))
    return signed(m.group(1), value), decimals, m.group(0)[-90:]


def cpi_table_rows(raw: str) -> dict[str, tuple[float, float, float, float]]:
    """Table 1 of INSTAT's consumer price release: ``{name: (weight, index vs the 2025 average, monthly %, annual %)}``; the total is ``'total'``."""
    rows = {}
    for m in re.finditer(r"^\s*(?:(\d{2})\.\s+(.+?)|(Gjithsej))\s+(\d+\.\d)\s+(\d+\.\d)\s+(-?\d+\.\d)\s+(-?\d+\.\d)\s*$", raw, re.M):
        name = "total" if m.group(3) else norm(m.group(2))
        rows[name] = tuple(float(m.group(i)) for i in range(4, 8))
    return rows


# the comparison
@dataclass
class Row:
    group: str
    what: str
    published: float | None
    decimals: int
    program: float | None
    verdict: str
    note: str = ""
    quote: str = ""


def judge(published: float, decimals: int, program: float, *, rounded_levels: float | None = None, approx: float | None = None) -> str:
    half = 0.5 * 10 ** -decimals + 1e-9
    if abs(program - published) <= half:
        return "match"
    if rounded_levels is not None and abs(rounded_levels - published) <= half:
        return "match (rounded levels)"
    if approx is not None and abs(program - published) <= approx + 1e-9:
        return "close"
    return "differ"


class Context:
    def __init__(self, fetcher: Fetcher, only: set[str] | None) -> None:
        self.fetcher = fetcher
        self.only = only
        self.rows: list[Row] = []
        self._pages: dict[str, tuple[str, dict[str, str], list]] = {}
        self._files: dict[str, ProcessedFile] = {}
        self._pdfs: dict[str, tuple[str, str]] = {}
        self.sources: list[str] = []

    def wanted(self, key: str) -> bool:
        return not self.only or key in self.only

    def page(self, topic: str):
        if topic not in self._pages:
            url = search_topics(topic)[0].topic.url
            html = self.fetcher.get_html(url)
            self._pages[topic] = (url, pdf_links(html, url), parse_page(html, url).files)
        return self._pages[topic]

    def pdf(self, topic: str, name: str) -> tuple[str, str]:
        """(raw text, cleaned text) of the press release called ``name`` on the page of ``topic``."""
        if name not in self._pdfs:
            try:
                from pypdf import PdfReader
            except ImportError:
                sys.exit("This tool needs the pypdf library to read INSTAT's press releases: python -m pip install pypdf")
            _page_url, pdfs, _files = self.page(topic)
            if name not in pdfs:
                raise LookupError(f"the release {name} is not offered on the page of {topic!r} any more")
            raw = "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(self.fetcher.get_bytes(pdfs[name]))).pages)
            self._pdfs[name] = (raw, clean_pdf_text(raw))
            self.sources.append(f"{name}  ({pdfs[name]})")
        return self._pdfs[name]

    def table(self, topic: str, label: str, *, freq: str | None = None, index: int = 0) -> ProcessedTable:
        """The table, as the program reads it, of the Excel file whose label on the topic page matches the regular expression ``label``."""
        _url, _pdfs, files = self.page(topic)
        link = next((f for f in files if re.search(label, f.label, re.I)), None)
        if link is None:
            raise LookupError(f"no file on the page of {topic!r} is labelled like {label!r}")
        if link.url not in self._files:
            got = self.fetcher.download(link.url)
            self._files[link.url] = process_bytes(got.data, got.filename, source=SourceInfo(got.filename, got.sha256, got.size, "download"))
            self.sources.append(f"{link.label}  ({link.url})")
        tables = self._files[link.url].tables
        if freq:
            tables = [t for t in tables if t.table.df["freq"].iloc[0] == freq]
        return tables[index]

    def add(self, group: str, what: str, published: tuple[float, int] | None, program: float | None, *, quote: str = "", note: str = "",
            rounded_levels: float | None = None, approx: float | None = None) -> None:
        if published is None or program is None:
            self.rows.append(Row(group, what, published[0] if published else None, published[1] if published else 0, program, "missing",
                                 note or ("not found in the release" if published is None else "not found in the table"), quote))
            return
        verdict = judge(published[0], published[1], program, rounded_levels=rounded_levels, approx=approx)
        self.rows.append(Row(group, what, published[0], published[1], program, verdict, note, quote))


def value_at(pt: ProcessedTable, period: str, **where: str) -> float | None:
    """The one value of the table at ``period`` where each named column equals the given text (names compared by letters and digits)."""
    df = pt.table.df
    sel = df[df["period"] == period]
    for col, want in where.items():
        sel = sel[sel[col].astype(str).map(norm) == norm(want)]
    return float(sel["value"].iloc[0]) if len(sel) == 1 else None


def pct_change(new: float | None, old: float | None) -> float | None:
    return None if new is None or old is None or old == 0 else (new / old - 1) * 100


# the checks
CPI_TOPIC, HICP_TOPIC = "consumer price index", "harmonized index"
CPI_LABELS = (r"^consumer price index \(coicop ver", r"^monthly changes of consumer price index \(coicop ver", r"^annual change of consumer price index \(coicop ver")
HICP_LABELS = (r"^harmonised index of consumer price \(coicop ver", r"^monthly changes in harmonised index of consumer price \(coicop",
               r"^annual changes? in harmonised index of consumer price \(coicop")


def check_cpi(c: Context) -> None:
    g, month, prev_month, year_ago = "Consumer price index, September 2026", "2026-09", "2026-08", "2025-09"
    raw, flat = c.pdf(CPI_TOPIC, "cpi_september_2026.pdf")
    idx, mon, ann = (c.table(CPI_TOPIC, label) for label in CPI_LABELS)
    rows = cpi_table_rows(raw)
    m = re.search(r"was (\d+\.\d) percent in September 2026", flat)
    headline = to_number(m.group(1)) if m else None
    quote = m.group(0) if m else ""
    c.add(g, "annual inflation, the total (read from the annual-change table)", headline, value_at(ann, month, product="Total"), quote=quote)
    c.add(g, "annual inflation, the total (worked out from the index: Sep 2026 / Sep 2025)", headline,
          pct_change(value_at(idx, month, product="Total"), value_at(idx, year_ago, product="Total")), quote=quote)
    if "total" not in rows:
        c.add(g, "Table 1 of the release", None, None, note="the table of divisions could not be read from the release")
    average_2025 = {}
    df = idx.table.df
    for name in [*rows, ]:
        sel = df[df["period"].str.startswith("2025-")]
        sel = sel[sel["product"].map(norm) == ("total" if name == "total" else name)]
        average_2025[name] = float(sel["value"].mean()) if len(sel) == 12 else None
    for name, (weight, vs_2025, monthly, annual) in rows.items():
        label = "the total" if name == "total" else next((p for p in df["product"].unique() if norm(p) == name), name)
        product = "Total" if name == "total" else label
        quote = f"{label}: weight {weight}, index {vs_2025}, month {monthly}, year {annual}"
        level = value_at(idx, month, product=product)
        avg = average_2025.get(name)
        c.add(g, f"{label}: index, Sep 2026 relative to the 2025 average", (vs_2025, 1), level / avg * 100 if level and avg else None, quote=quote)
        c.add(g, f"{label}: change on the month before (read from the monthly-change table)", (monthly, 1), value_at(mon, month, product=product))
        c.add(g, f"{label}: change on the same month a year before (read from the annual-change table)", (annual, 1), value_at(ann, month, product=product))
        if name != "total":
            c.add(g, f"{label}: annual change worked out from the index", (annual, 1), pct_change(level, value_at(idx, year_ago, product=product)))
    c.add(g, "total: change on the month before, worked out from the index", (rows["total"][2], 1) if "total" in rows else None,
          pct_change(value_at(idx, month, product="Total"), value_at(idx, prev_month, product="Total")))
    # contributions to the annual change, in percentage points: INSTAT's figure is in the chart of the release, listed value by value
    # above the group names, which follow in the same order
    contributions = idx.analysis.extras.get("cpi_contributions")
    block = re.search(r"CONTRIBUTION OF GROUPS TO THE ANNUAL CHANGE\s*\n(.*?)\n[ \t]*(?:-?\d\.\d\d[ \t]+){3,}.*?\n(.*?)Page 3", raw, re.S)
    published = []
    if block:
        values = [to_number(v) for v in re.findall(r"^\s*(-?\d\.\d\d)\s*$", block.group(1), re.M)]
        names = [n.strip() for n in block.group(2).splitlines() if n.strip()]
        published = list(zip(names, values, strict=False)) if len(values) == len(names) == 13 else []
    if contributions is None or not published:
        c.add(g, "contributions of the 13 groups to the annual change (pp)", None, None, note="the contributions or the chart could not be read")
        return
    by_norm = {norm(k): v for k, v in contributions.items()}
    aliases = {"alcoholicbeveragestobaccoandnarcotics": "alcoholicbeveragestobaccoandnarcotics", "alcoholicbeveragesandtobacco": "alcoholicbeveragestobaccoandnarcotics",
               "furnishingshouseholdequipmentandroutinehousehold": "furnishingshouseholdequipmentandroutinehouseholdmaintenance"}
    for name, value in published:
        key = norm(name.replace("…", ""))
        key = aliases.get(key, key)
        program = next((v for k, v in by_norm.items() if k == key or k.startswith(key)), None)
        c.add(g, f"contribution of {name} to the annual change (pp)", value, float(program) if program is not None else None, approx=0.02,
              quote=f"{name}: {value[0]:+.2f}", note="the program's contributions are approximate (published weights, no chain-linking): within 0.02 pp counts as close")


def check_hicp(c: Context) -> None:
    g = "Harmonised index of consumer prices, September 2026"
    raw, flat = c.pdf(HICP_TOPIC, "hicp-september-2026.pdf")
    idx, mon, ann = (c.table(HICP_TOPIC, label) for label in HICP_LABELS)
    month = "2026-09"
    m = re.search(r"in September 2026 was (\d+\.\d) ?%", flat)
    c.add(g, "annual inflation, the total", to_number(m.group(1)) if m else None, value_at(ann, month, product="Total"), quote=m.group(0) if m else "")
    m = re.search(r"consumer p ?rices increased by (\d+\.\d) ?% compared with the previous month", flat)  # the PDF has "p rices"
    c.add(g, "change on the month before, the total", to_number(m.group(1)) if m else None, value_at(mon, month, product="Total"), quote=m.group(0) if m else "")
    contributions = idx.analysis.extras.get("cpi_contributions")
    names = {"Food and non-alcoholic beverages": "Food and non-alcoholic beverages", "Transport": "Transport", "Recreation, sport and culture": "Recreation, sport and culture",
             "Restaurants and accommodation services": "Restaurants and accommodation services", "Alcoholic beverages and tobacco": "Alcoholic beverages, tobacco and narcotics",
             "Education services": "Education services", "Health": "Health"}
    for text_name, product in names.items():
        m = re.search(rf"[“\"]{re.escape(text_name)}[”\"][^+\-]{{0,40}}?([+-]\d\.\d\d) percentage points?,? (?:and )?(?:an |with an )?[^%]{{0,30}}?annual increase of (\d+\.\d) ?%", flat)
        if not m:
            c.add(g, f"{text_name}: annual change and contribution", None, None, note="the sentence was not found in the release")
            continue
        c.add(g, f"{text_name}: annual change", to_number(m.group(2)), value_at(ann, month, product=product), quote=m.group(0)[:110])
        if contributions is not None:
            program = {norm(k): v for k, v in contributions.items()}.get(norm(product))
            c.add(g, f"{text_name}: contribution to the annual change (pp)", to_number(m.group(1)), float(program) if program is not None else None, approx=0.02,
                  quote=m.group(0)[:110], note="the program's contributions are approximate: within 0.02 pp counts as close")
    for text_name, product, word in [("Education services", "Education services", "rose"), ("Recreation, sport and culture", "Recreation, sport and culture", "an increase of"),
                                     ("Food and non-alcoholic beverages", "Food and non-alcoholic beverages", "with"), ("Clothing and footwear", "Clothing and footwear", "with"),
                                     ("Furnishings, household equipment and routine household maintenance", "Furnishings, household equipment and routine household maintenance", "decreased by"),
                                     ("Restaurants and accommodation services", "Restaurants and accommodation services", "decrease of"),
                                     ("Information and communication", "Information and communication", "decrease of")]:
        m = re.search(rf"[“\"]{re.escape(text_name)}[”\"],? (?:which |with )?(?:rose |an |a )?(?:by |increase of |decrease of |decreased by )?(\d+\.\d) ?%", flat)
        if not m:
            c.add(g, f"{text_name}: change on the month before", None, None, note="the sentence was not found in the release")
            continue
        sign = -1 if word in ("decreased by", "decrease of") else 1
        c.add(g, f"{text_name}: change on the month before", (sign * to_number(m.group(1))[0], 1), value_at(mon, month, product=product), quote=m.group(0)[:110])


GDP_TOPIC = "gross domestic product"
GDP_ACTIVITIES = [("Public administration, Education and Health", "Public administration and defence"), ("Real estate", "Real estate activities"),
                  ("Trade, Transport, Accommodation and Food Services", "Wholesale and retail trade"), ("Financial and insurance", "Financial and insurance activities"),
                  ("Information and Communications", "Information and communication"), ("Construction", "Construction"),
                  ("Industry, Electricity and Water", "Mining and quarrying; manufacturing; electricity, gas, steam and air conditioning supply; water supply; sewerage, waste management and remediation activities – Total"),
                  ("Agriculture, Forestry and Fishing", "Agriculture, forestry and fishing"), ("Professional services and Administrative services", "Professional, scientific"),
                  ("Arts, entertainment and recreation services, other services", "Arts, entertainment"), ("Net Taxes on products", "Taxes on products")]


def check_gdp(c: Context) -> None:
    g = "Quarterly GDP, second quarter of 2026 (real growth on the same quarter of 2025)"
    _raw, flat = c.pdf(GDP_TOPIC, "gdp-q2-2026.pdf")
    pt = c.table(GDP_TOPIC, r"^quarterly gross domestic product by production approach$", freq="Q")
    df = pt.table.df
    m = re.search(r"in volume terms has increased by (\d+\.\d+) ?%, compared with the second quarter of 2025", flat)
    c.add(g, "GDP", to_number(m.group(1)) if m else None, value_at(pt, "2026-Q2", measure="Gross domestic product"), quote=m.group(0)[-80:] if m else "")
    start = flat.find("The trends in the main economic activities")
    end = flat.find("Regarding the changes to the previous quarter")
    segment = flat[start:end] if 0 <= start < end else ""
    for phrase, prefix in GDP_ACTIVITIES:
        found = growth_after(segment, phrase)
        measure = next((m_ for m_ in df["measure"].unique() if m_.lower().startswith(prefix.lower())), None)
        program = value_at(pt, "2026-Q2", measure=measure) if measure else None
        c.add(g, f"{phrase}", (found[0], found[1]) if found else None, program, quote=found[2] if found else "")


def check_gdp_annual(c: Context) -> None:
    g = "Annual GDP, 2025 (current prices, million ALL)"
    _raw, flat = c.pdf(GDP_TOPIC, "gross-domestic-product-2025.pdf")
    pt = c.table(GDP_TOPIC, r"production approach.*2021", index=0)
    m = re.search(r"ALL ([\d,]+) million in 2025 and ALL ([\d,]+) million in 2024", flat)
    quote = m.group(0) if m else ""
    c.add(g, "GDP at market prices, 2025", to_number(m.group(1)) if m else None, value_at(pt, "2025", measure="GDP at market prices"), quote=quote)
    c.add(g, "GDP at market prices, 2024", to_number(m.group(2)) if m else None, value_at(pt, "2024", measure="GDP at market prices"), quote=quote)


LFS_TOPIC = "employment and unemployment from LFS"


def check_lfs(c: Context) -> None:
    g = "Labour force survey, second quarter of 2026"
    _raw, flat = c.pdf(LFS_TOPIC, "pressrelease-lfs_t2_2026-new-format_english.pdf")
    for title, label, age, heading in [("unemployment rate (15 and over)", r"^labour force survey, unemployment rate", "15 years and above", "Unemployment"),
                                       ("employment rate (15 and over)", r"^labour force survey, employment rate", "15 years and above", "Employment"),
                                       ("labour force participation rate (15-64)", r"^labour force survey, labour force participation rate", "15-64 years", "Labour force participation")]:
        pt = c.table(LFS_TOPIC, label)
        now, year, quarter = (value_at(pt, p, age_group=age, sex="Total") for p in ("2026-Q2", "2025-Q2", "2026-Q1"))
        block = re.search(rf"{heading} In the second quarter of 2026, .*?is (\d+\.\d) ?%\. (.*?)(?= (?:Employment|Unemployment|FIG\.|Labour force participation) )", flat)
        if not block:
            c.add(g, title, None, now, note="the paragraph was not found in the release")
            continue
        changes = re.findall(r"(increased|decreased) by (\d+\.\d) percentage points", block.group(2))
        c.add(g, f"{title}: level", to_number(block.group(1)), now, quote=block.group(0)[:100])
        for (direction, number), label_, other in zip(changes[:2], ("on the same quarter of 2025", "on the previous quarter"), (year, quarter), strict=False):
            published = (signed(direction, to_number(number)[0]), to_number(number)[1])
            unrounded = None if now is None or other is None else now - other
            rounded = None if now is None or other is None else round(round(now, 1) - round(other, 1), 1)
            c.add(g, f"{title}: change {label_} (pp)", published, unrounded, rounded_levels=rounded, quote=f"{direction} by {number} percentage points")


TRADE_TOPIC = "international trade"


def check_trade(c: Context) -> None:
    g = "Foreign trade in goods, September 2026 (billion ALL)"
    _raw, flat = c.pdf(TRADE_TOPIC, "foreign-trade-in-goods-shtator-2026.pdf")
    pt = c.table(TRADE_TOPIC, r"^flow of goods in foreign trade, monthly$")
    m = re.search(r"value of exports was ALL (\d+\.\d) billion, (increasing|decreasing) by (\d+\.\d) ?% compared with the same period of the previous year and by (\d+\.\d) ?% "
                  r"compared with August 2026\. The value of imports was ALL (\d+\.\d) billion, (increasing|decreasing) by (\d+\.\d) ?% compared with the same period of the previous year and "
                  r"by (\d+\.\d) ?% compared with August 2026\. This month, the trade deficit is ALL (\d+\.\d) billion, (increasing|decreasing) by (\d+\.\d) ?% compared with the same period of the previous year and by (\d+\.\d) ?% compared with August", flat)
    if not m:
        c.add(g, "the sentence on exports, imports and the deficit", None, None, note="the sentence was not found in the release (its wording changed)")
        return
    v = m.groups()
    # one verb ("increasing" / "decreasing") covers both changes of a sentence; the deficit is compared by its size
    for what, measure, level, direction, year_change, month_change in [("exports", "Exports", *v[0:4]), ("imports", "Imports", *v[4:8]), ("trade deficit", "Trade balance", *v[8:12])]:
        now, last_year, last_month = (abs(x) if x is not None else None for x in (value_at(pt, p, measure=measure) for p in ("2026-09", "2025-09", "2026-08")))
        c.add(g, f"{what}: value", to_number(level), now, quote=f"{what} ALL {level} billion")
        c.add(g, f"{what}: change on September 2025 (%)", (signed(direction, to_number(year_change)[0]), to_number(year_change)[1]), pct_change(now, last_year),
              quote=f"{direction} by {year_change} % compared with the same period of the previous year")
        c.add(g, f"{what}: change on August 2026 (%)", (signed(direction, to_number(month_change)[0]), to_number(month_change)[1]), pct_change(now, last_month),
              quote=f"and by {month_change} % compared with August 2026")

WAGES_TOPIC = "average wage"


def check_wages(c: Context) -> None:
    g = "Wages, second quarter of 2026"
    _raw, flat = c.pdf(WAGES_TOPIC, "pressrelease-pagat_t2_2026_en.pdf")
    pt = c.table(WAGES_TOPIC, r"average monthly wage per employee and approved minimum wage")
    m = re.search(r"average monthly gross wage per employee in Albania was ([\d,]+) ALL\. Compared to the second quarter of 2025, the average monthly gross wage increased by (\d+\.\d) ?%", flat)
    measure = "Average monthly wage gross per employee"
    now, last_year = (value_at(pt, p, category=measure) for p in ("2026-Q2", "2025-Q2"))
    c.add(g, "average monthly gross wage per employee (ALL)", to_number(m.group(1)) if m else None, now, quote=m.group(0)[:100] if m else "")
    c.add(g, "change on the second quarter of 2025 (%)", to_number(m.group(2)) if m else None, pct_change(now, last_year), quote=m.group(0)[-60:] if m else "")


TOURISM_TOPIC = "tourism"


def check_tourism(c: Context) -> None:
    g = "Accommodation establishments, August 2026 (change on August 2025, %)"
    _raw, flat = c.pdf(TOURISM_TOPIC, "accommodation-establishments-august-2026docx.pdf")
    arrivals = c.table(TOURISM_TOPIC, r"^monthly arrivals of resident and non[- ]resident$")
    nights = c.table(TOURISM_TOPIC, r"^monthly nights spent of resident and non[- ]resident$")
    m = re.search(r"visitors accommodated in accommodation establishments in Albania increased by (\d+\.\d) ?% compared with the same month of the previous year\. "
                  r"Resident visitors increased by (\d+\.\d) ?%, while non-resident visitors increased by (\d+\.\d) ?%", flat)
    n = re.search(r"Total nights spent increased by (\d+\.\d) ?%; .*?by resident visitors increased by (\d+\.\d) ?%; .*?by non-resident visitors increased by (\d+\.\d) ?%", flat)
    for k, (title, category) in enumerate([("visitors, total", "Total arrivals"), ("resident visitors", "Arrivals of residents"), ("non-resident visitors", "Arrivals of non-residents")]):
        c.add(g, title, to_number(m.group(k + 1)) if m else None, pct_change(value_at(arrivals, "2026-08", category=category), value_at(arrivals, "2025-08", category=category)),
              quote=m.group(0)[:100] if m else "")
    for k, (title, category) in enumerate([("nights spent, total", "Total nights spent"), ("nights spent by residents", "Nights spent of residents"),
                                           ("nights spent by non-residents", "Nights spent of non-residents")]):
        c.add(g, title, to_number(n.group(k + 1)) if n else None, pct_change(value_at(nights, "2026-08", category=category), value_at(nights, "2025-08", category=category)),
              quote=n.group(0)[:100] if n else "")


CONSTRUCTION_TOPIC = "construction"


def absolute(pt: ProcessedTable, period: str, **where: str) -> float | None:
    """A value in the unit it is stated in (thousand lek times 1,000), so a table read with the wrong unit cannot match."""
    value = value_at(pt, period, **where)
    scale = pt.profile.measures[0].scale or 1.0
    return None if value is None else value * scale


def check_building_permits(c: Context) -> None:
    g = "Building permits issued, second quarter of 2026"
    _raw, flat = c.pdf(CONSTRUCTION_TOPIC, "building-permits-issued-q2-2026docx.pdf")
    count = c.table(CONSTRUCTION_TOPIC, r"^number of building permits issued for new buildings")
    area = c.table(CONSTRUCTION_TOPIC, r"^total area of building permits issued for new buildings")
    worth = c.table(CONSTRUCTION_TOPIC, r"^approximate value of building permits issued")
    m = re.search(r"(\d[\d,]*) building permits for new buildings have been approved ?, (increas\w+|decreas\w+) this indicator by (\d+\.\d) ?%, compared to (\d[\d,]*) permits", flat)
    now, before = value_at(count, "2026-Q2", category="I. Buildings"), value_at(count, "2025-Q2", category="I. Buildings")
    c.add(g, "permits for new buildings, 2026 Q2", to_number(m.group(1)) if m else None, now, quote=m.group(0)[:100] if m else "")
    c.add(g, "permits for new buildings, 2025 Q2", to_number(m.group(4)) if m else None, before, quote=m.group(0)[-40:] if m else "")
    c.add(g, "permits for new buildings: change on 2025 Q2 (%)", (signed(m.group(2), to_number(m.group(3))[0]), to_number(m.group(3))[1]) if m else None, pct_change(now, before))
    m = re.search(r"total area for new buildings in the second quarter 2026 is ([\d,]+) m², (increas\w+|decreas\w+) this indicator by (\d+\.\d) ?%, compared to the second quarter 20\d\d \(([\d,]+) m²\)", flat)
    now, before = value_at(area, "2026-Q2", category="I. Buildings"), value_at(area, "2025-Q2", category="I. Buildings")
    c.add(g, "total area, 2026 Q2 (m²)", to_number(m.group(1)) if m else None, now, quote=m.group(0)[:100] if m else "")
    c.add(g, "total area, 2025 Q2 (m²)", to_number(m.group(4)) if m else None, before, quote=m.group(0)[-50:] if m else "")
    c.add(g, "total area: change on 2025 Q2 (%)", (signed(m.group(2), to_number(m.group(3))[0]), to_number(m.group(3))[1]) if m else None, pct_change(now, before))
    m = re.search(r"value of building permits issued for buildings and civil engineering works is (\d+\.\d) billion ALL, (increas\w+|decreas\w+) this indicator by (\d+\.\d) ?%, compared to the second quarter 20\d\d \((\d+\.\d) billion ALL\)", flat)
    now, before = absolute(worth, "2026-Q2", category="Total"), absolute(worth, "2025-Q2", category="Total")
    c.add(g, "approximate value, 2026 Q2 (billion ALL; the table is in thousand lek)", to_number(m.group(1)) if m else None, None if now is None else now / 1e9, quote=m.group(0)[:110] if m else "")
    c.add(g, "approximate value, 2025 Q2 (billion ALL)", to_number(m.group(4)) if m else None, None if before is None else before / 1e9, quote=m.group(0)[-45:] if m else "")
    c.add(g, "approximate value: change on 2025 Q2 (%)", (signed(m.group(2), to_number(m.group(3))[0]), to_number(m.group(3))[1]) if m else None, pct_change(now, before))
    m = re.search(r"with (\d+) building permit and a total building area of ([\d,]+) m². .*?with (\d+) building permits and ([\d,]+) m² of building area", flat)
    residential = value_at(count, "2026-Q2", category="1. Residential buildings"), value_at(area, "2026-Q2", category="1. Residential buildings")
    other = next((v for k, v in ((k, value_at(count, "2026-Q2", category=k)) for k in count.table.df["category"].unique() if k.startswith("2.")) if v is not None), None)
    other_area = next((v for k, v in ((k, value_at(area, "2026-Q2", category=k)) for k in area.table.df["category"].unique() if k.startswith("2.")) if v is not None), None)
    for title, published, program in [("residential permits", m and to_number(m.group(1)), residential[0]), ("residential area (m²)", m and to_number(m.group(2)), residential[1]),
                                      ("non-residential permits", m and to_number(m.group(3)), other), ("non-residential area (m²)", m and to_number(m.group(4)), other_area)]:
        c.add(g, title, published or None, program, quote=m.group(0)[:100] if m else "")


DEMOGRAPHY_TOPIC = "births deaths marriages"


def check_births(c: Context) -> None:
    g = "Births, second quarter of 2026"
    _raw, flat = c.pdf(DEMOGRAPHY_TOPIC, "demographic-indicators-q2-2026.pdf")
    pt = c.table(DEMOGRAPHY_TOPIC, r"^births by prefectures")
    df = pt.table.df
    m = re.search(r"the number of births for the second quarter of 2026 is ([\d,]+), marking a (increase|decrease) by (\d+\.\d) ?%, compared to the second quarter of 2025", flat)
    parts = df[~df["is_total"].astype(bool)] if "is_total" in df.columns else df
    now = float(parts[parts["period"] == "2026-Q2"]["value"].sum()) if len(parts) else None
    before = float(parts[parts["period"] == "2025-Q2"]["value"].sum()) if len(parts) else None
    c.add(g, "births in Albania, 2026 Q2 (the sum of the 12 prefectures)", to_number(m.group(1)) if m else None, now, quote=m.group(0)[:100] if m else "")
    c.add(g, "births: change on 2025 Q2 (%)", (signed(m.group(2), to_number(m.group(3))[0]), to_number(m.group(3))[1]) if m else None, pct_change(now, before),
          quote=m.group(0)[-60:] if m else "")


CHECKS: dict[str, Callable[[Context], None]] = {"cpi": check_cpi, "hicp": check_hicp, "gdp": check_gdp, "gdp-annual": check_gdp_annual, "lfs": check_lfs,
                                                "trade": check_trade, "wages": check_wages, "tourism": check_tourism, "building": check_building_permits, "births": check_births}


# report
def fmt(x: float | None, decimals: int) -> str:
    return "–" if x is None else f"{x:,.{max(decimals, 0)}f}"


def render(rows: list[Row], sources: list[str]) -> str:
    out = [f"# INSTAT Explorer {__version__} against INSTAT's own published figures", "",
           "Generated by `tools/check_published.py`. For each figure that an INSTAT press release states, the program's number from the Excel table of the "
           "same data. A figure *matches* when the program's number, rounded as INSTAT rounded it, is the published one.", ""]
    groups: dict[str, list[Row]] = {}
    for r in rows:
        groups.setdefault(r.group, []).append(r)
    total = {v: sum(1 for r in rows if r.verdict == v) for v in ("match", "match (rounded levels)", "close", "differ", "missing")}
    out += [f"**{len(rows)} figures compared: {total['match']} match, {total['match (rounded levels)']} match when INSTAT's rounded levels are used, "
            f"{total['close']} close (approximate by design), {total['differ']} differ, {total['missing']} could not be compared.**", ""]
    out += ["**How to read it.** *match*: the program's number, rounded as INSTAT rounded it, is the published one. *match (rounded levels)*: INSTAT worked a change "
            "out from levels it had already rounded (8.5 to 8.3 is published as -0.2, the unrounded levels give -0.26). *close*: the figure is one the program "
            "only approximates (the contributions of groups to inflation use the published weights and ignore chain-linking), accepted within 0.02 percentage points; "
            "the largest deviation is in the table. *differ*: a real difference, to be explained.", "",
            "**What it shows, and what it does not.** It shows that for these figures, which INSTAT chose to state in the press releases of ten data sets, the program "
            "reads or works out the same numbers from the Excel tables. It does not show that every cell of every table is read right: INSTAT publishes about 640 "
            "files and these are the headline figures of the latest releases. The tables on the site can be revised after a release, and a release can contain a typing "
            "slip, so a difference may be on either side.", ""]
    for group, items in groups.items():
        counts = {v: sum(1 for r in items if r.verdict == v) for v in ("match", "match (rounded levels)", "close", "differ", "missing")}
        out += [f"## {group}", "", f"{len(items)} figures: " + ", ".join(f"{n} {v}" for v, n in counts.items() if n), "",
                "| Figure | INSTAT states | Program reads | Result |", "|---|---:|---:|---|"]
        for r in items:
            mark = {"match": "✓ match", "match (rounded levels)": "✓ match (rounded levels)", "close": "≈ close", "differ": "✗ DIFFERS", "missing": "? not compared"}[r.verdict]
            out.append(f"| {r.what} | {fmt(r.published, r.decimals)} | {fmt(r.program, max(r.decimals + 1, 2))} | {mark}{' – ' + r.note if r.verdict in ('differ', 'missing', 'close') and r.note else ''} |")
        out.append("")
    out += ["## Sources", "", *(f"* {s}" for s in dict.fromkeys(sources)), ""]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--only", help="comma-separated: " + " ".join(CHECKS))
    ap.add_argument("--out", type=Path, help="write the report here (Markdown)")
    args = ap.parse_args()
    only = {k.strip() for k in args.only.split(",")} if args.only else None
    ctx = Context(Fetcher(), only)
    for key, check in CHECKS.items():
        if not ctx.wanted(key):
            continue
        try:
            check(ctx)
            print(f"  done  {key}", flush=True)
        except (LookupError, FetchError) as exc:
            ctx.rows.append(Row(key, f"the check could not run: {exc}", None, 0, None, "missing", str(exc)))
            print(f"  FAILED to run {key}: {exc}", flush=True)
    report = render(ctx.rows, ctx.sources)
    (args.out.write_text(report, encoding="utf-8", newline="\n") if args.out else print(report))
    bad = [r for r in ctx.rows if r.verdict in ("differ", "missing")]
    print(f"\n{len(ctx.rows)} figures compared; {sum(r.verdict.startswith('match') for r in ctx.rows)} match, "
          f"{sum(r.verdict == 'close' for r in ctx.rows)} close, {sum(r.verdict == 'differ' for r in ctx.rows)} differ, {sum(r.verdict == 'missing' for r in ctx.rows)} not compared")
    for r in bad[:25]:
        print(f"   {r.verdict.upper():8} {r.group[:40]:40} | {r.what[:70]} | published {fmt(r.published, r.decimals)} program {fmt(r.program, r.decimals + 1)} {r.note}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
