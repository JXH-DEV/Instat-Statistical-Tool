"""Parse the many ways INSTAT writes a period into a canonical :class:`Period`.

Seen in real files: ``" 01-17"`` (leading space), ``12 - 21`` next to ``2 - 22`` (unpadded),
``Tr.1.2023 Q1.2023`` (Albanian and English label in one cell), ``2025*`` (provisional),
``" 01-17  01-16"`` (value period plus its comparison base), plain numeric years, Excel dates.
"""

from __future__ import annotations

import calendar
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from ..config import TWO_DIGIT_YEAR_PIVOT
from ..i18n import N_
from .textnorm import clean_text, fold

FREQ_LAG = {"M": 12, "Q": 4, "H": 2, "A": 1}
FREQ_NAME = {"M": N_("monthly"), "Q": N_("quarterly"), "H": N_("half-yearly"), "A": N_("annual"), "D": N_("daily"),
             "R": N_("multi-year")}

_MONTH_NAMES_EN = ["january", "february", "march", "april", "may", "june", "july", "august", "september",
                   "october", "november", "december"]
_MONTH_NAMES_SQ = ["janar", "shkurt", "mars", "prill", "maj", "qershor", "korrik", "gusht", "shtator",
                   "tetor", "nentor", "dhjetor"]
_MONTH_ABBR_EN = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
_MONTH_ABBR_SQ = ["jan", "shk", "mar", "pri", "maj", "qer", "kor", "gus", "sht", "tet", "nen", "dhj"]

_MONTHS: dict[str, int] = {}
for _i in range(12):
    for _name in (_MONTH_NAMES_EN[_i], _MONTH_NAMES_SQ[_i], _MONTH_ABBR_EN[_i], _MONTH_ABBR_SQ[_i]):
        _MONTHS[_name] = _i + 1
_MONTHS["sept"] = 9

_MONTH_RE = "|".join(sorted(_MONTHS, key=len, reverse=True))
_YEAR4 = r"(?:19|20)\d{2}"
_ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4}


@dataclass(frozen=True)
class Period:
    label: str  # canonical: 2017-01, 2023-Q1, 2024-H2, 2025, 2019-2023, 2024-03-31
    freq: str  # A, H, Q, M, D or R (multi-year range)
    start: date
    end: date
    provisional: bool = False
    base: Period | None = None  # comparison base, e.g. the ``01-16`` in ``" 01-17  01-16"``
    raw: str = ""

    @property
    def year(self) -> int:
        return self.start.year

    @property
    def sort_key(self) -> tuple[date, date]:
        return (self.start, self.end)


def _year2(y: int) -> int:
    return 2000 + y if y <= TWO_DIGIT_YEAR_PIVOT else 1900 + y


def make_month(y: int, m: int, **kw) -> Period:
    return Period(f"{y:04d}-{m:02d}", "M", date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1]), **kw)


def make_quarter(y: int, q: int, **kw) -> Period:
    m0 = (q - 1) * 3 + 1
    return Period(f"{y:04d}-Q{q}", "Q", date(y, m0, 1), date(y, m0 + 2, calendar.monthrange(y, m0 + 2)[1]), **kw)


def make_half(y: int, h: int, **kw) -> Period:
    m0 = 1 if h == 1 else 7
    return Period(f"{y:04d}-H{h}", "H", date(y, m0, 1), date(y, m0 + 5, calendar.monthrange(y, m0 + 5)[1]), **kw)


def make_year(y: int, **kw) -> Period:
    return Period(f"{y:04d}", "A", date(y, 1, 1), date(y, 12, 31), **kw)


def make_range(y1: int, y2: int, **kw) -> Period:
    return Period(f"{y1:04d}-{y2:04d}", "R", date(y1, 1, 1), date(y2, 12, 31), **kw)


def make_day(d: date, **kw) -> Period:
    return Period(d.isoformat(), "D", d, d, **kw)


def month_number(text: str) -> int | None:
    """``'Janar'`` / ``'Jan.'`` / ``'March'`` -> month number, else ``None``."""
    key = fold(clean_text(text)).rstrip(".")
    return _MONTHS.get(key)


def sub_period(text: str) -> tuple[str, int] | None:
    """A period fragment without a year: ``'Q2'`` -> ``('Q', 2)``, ``'Shkurt'`` -> ``('M', 2)``."""
    s = clean_text(text)
    m = re.fullmatch(r"(?i)(?:tr|t|q)\.?\s*([1-4]|iv|iii|ii|i)\.?", s)
    if m:
        tok = m.group(1).lower()
        return "Q", int(tok) if tok.isdigit() else _ROMAN[tok]
    m = re.fullmatch(r"(?i)(?:h|s|gj)\.?\s*([12])\.?", s)
    if m:
        return "H", int(m.group(1))
    mo = month_number(s)
    if mo:
        return "M", mo
    return None


def combine_year_sub(year: int, sub: tuple[str, int], **kw) -> Period | None:
    kind, n = sub
    if kind == "Q":
        return make_quarter(year, n, **kw)
    if kind == "H":
        return make_half(year, n, **kw)
    if kind == "M":
        return make_month(year, n, **kw)
    return None


_PROV_TAIL = re.compile(r"(?:\s*(?:\*+|\(\s*[pP]\s*\)|\(\s*sf\s*\)|\(\s*e\s*\)|[¹²³⁴⁵⁶⁷⁸⁹⁰]+))+\s*$")
_PROV_LETTER = re.compile(r"(?<=\d)\s*(?:[pPeE]|sf|SF)\s*$")


def _strip_provisional(text: str) -> tuple[str, bool]:
    prov = False
    m = _PROV_TAIL.search(text)
    if m and m.start() > 0:
        text, prov = text[: m.start()].rstrip(), True
    m = _PROV_LETTER.search(text)
    if m and m.start() > 0:
        text, prov = text[: m.start()].rstrip(), True
    return text, prov


_MY = re.compile(r"(?<![\d])(\d{1,2})\s*[-./]\s*(\d{4}|\d{2})(?![\d])")
_YM = re.compile(r"(?<![\d])((?:19|20)\d{2})\s*[-./]\s*(\d{1,2})(?![\d])")


def _month_year_from_tokens(a: str, b: str) -> Period | None:
    m, y = int(a), int(b)
    if not 1 <= m <= 12:
        return None
    return make_month(y if len(b) == 4 else _year2(y), m)


def _try_pair(text: str) -> Period | None:
    """Two month-year tokens in one cell: the first is the period, the second its comparison base."""
    tokens = list(_MY.finditer(text))
    if len(tokens) == 2 and not _MY.sub(" ", text).strip(" -/.,"):
        first = _month_year_from_tokens(*tokens[0].groups())
        second = _month_year_from_tokens(*tokens[1].groups())
        if first and second:
            return Period(first.label, first.freq, first.start, first.end, base=second, raw=text)
    tokens = list(_YM.finditer(text))
    if len(tokens) == 2 and not _YM.sub(" ", text).strip(" -/.,"):
        parts = []
        for t in tokens:
            y, m = int(t.group(1)), int(t.group(2))
            if not 1 <= m <= 12:
                return None
            parts.append(make_month(y, m))
        return Period(parts[0].label, "M", parts[0].start, parts[0].end, base=parts[1], raw=text)
    return None


def _from_date(value: date | datetime, hint: str | None) -> Period:
    d = value.date() if isinstance(value, datetime) else value
    last = calendar.monthrange(d.year, d.month)[1]
    if hint == "M" or (hint is None and d.day in (1, last) and d.month not in (1, 12)):
        return make_month(d.year, d.month)
    if hint == "A":
        return make_year(d.year)
    if hint == "Q":
        return make_quarter(d.year, (d.month - 1) // 3 + 1)
    return make_day(d)


def infer_date_freq(dates: list[date | datetime]) -> str | None:
    """Frequency hint for a header row of real dates (all 1st-of-month or month-end -> monthly...)."""
    ds = [d.date() if isinstance(d, datetime) else d for d in dates]
    if len(ds) < 2:
        return None
    if all(d.day == 1 or d.day == calendar.monthrange(d.year, d.month)[1] for d in ds):
        months = sorted({(d.year, d.month) for d in ds})
        gaps = Counter((b[0] * 12 + b[1]) - (a[0] * 12 + a[1]) for a, b in zip(months, months[1:]))
        if not gaps:
            return None
        gap = gaps.most_common(1)[0][0]
        return {1: "M", 3: "Q", 6: "H", 12: "A"}.get(gap)
    return None


def _quarter_number(tok: str) -> int:
    return int(tok) if tok.isdigit() else _ROMAN[tok.lower()]


def parse_period(value: object, *, hint: str | None = None) -> Period | None:
    """Best-effort parse of a header/label cell into a :class:`Period`; ``None`` if it is not a period.

    ``hint`` (``'M'``, ``'Q'``, ``'A'``...) resolves ambiguities such as ``2019-12`` (December 2019 vs a
    2019/2012 range) using what the rest of the header row looks like.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (datetime, date)):
        return _from_date(value, hint)
    if isinstance(value, (int, float)):
        if float(value).is_integer() and 1800 <= value <= 2200:
            return make_year(int(value))
        return None

    raw = clean_text(value)
    if not raw or len(raw) > 60:
        return None
    text, prov = _strip_provisional(raw)
    if not text:
        return None
    p = _parse_text(text, hint)
    if p is None:
        return None
    return Period(p.label, p.freq, p.start, p.end, provisional=prov or p.provisional, base=p.base, raw=raw)


def _parse_text(text: str, hint: str | None) -> Period | None:
    t = text.strip()

    pair = _try_pair(t)
    if pair:
        return pair

    # Quarter: Tr.1.2023 / Q1 2023 / T1-23 / Tr. II 2023 (first match wins, so "Tr.1.2023 Q1.2023" is fine)
    m = re.search(rf"(?i)(?<![a-z])(?:tr|t|q)\.?\s*([1-4]|iv|iii|ii|i)\b\.?\s*[-./ ]?\s*({_YEAR4})(?!\d)", t)
    if m:
        return make_quarter(int(m.group(2)), _quarter_number(m.group(1)))
    m = re.fullmatch(r"(?i)(?:tr|t|q)\.?\s*([1-4])\s*[-./ ]\s*(\d{2})", t)
    if m:
        return make_quarter(_year2(int(m.group(2))), int(m.group(1)))
    m = re.fullmatch(rf"(?i)({_YEAR4})\s*[-./ ]?\s*(?:tr|t|q)\.?\s*([1-4]|iv|iii|ii|i)", t)
    if m:
        return make_quarter(int(m.group(1)), _quarter_number(m.group(2)))
    m = re.fullmatch(
        rf"(?i)(?:(1st|first|2nd|second|3rd|third|4th|fourth|i|ii|iii|iv)\s+quarter|"
        rf"tremujori\s+i\s+(par[ëe]|dyt[ëe]|tret[ëe]|kat[ëe]rt)|(\d)\s*tremujor)\s*,?\s*(?:of\s+)?({_YEAR4})", t)
    if m:
        word = (m.group(1) or m.group(2) or m.group(3) or "").lower()
        order = {"1st": 1, "first": 1, "i": 1, "parë": 1, "pare": 1, "2nd": 2, "second": 2, "ii": 2,
                 "dytë": 2, "dyte": 2, "3rd": 3, "third": 3, "iii": 3, "tretë": 3, "trete": 3, "4th": 4,
                 "fourth": 4, "iv": 4, "katërt": 4, "katert": 4}
        q = int(word) if word.isdigit() else order.get(word)
        if q:
            return make_quarter(int(m.group(4)), q)

    # Half year: H1 2023 / S2 2023 / 2023 H1
    m = re.fullmatch(rf"(?i)(?:h|s|gj)\.?\s*([12])\s*[-./ ]?\s*({_YEAR4})", t)
    if m:
        return make_half(int(m.group(2)), int(m.group(1)))
    m = re.fullmatch(rf"(?i)({_YEAR4})\s*[-./ ]?\s*(?:h|s|gj)\.?\s*([12])", t)
    if m:
        return make_half(int(m.group(1)), int(m.group(2)))

    # Month name + year: "Janar 2024", "Jan-24", "March, 2024", "2024 March"
    ta = _ascii_months(t)
    m = re.fullmatch(rf"(?i)({_MONTH_RE})\.?\s*[-./, ]?\s*({_YEAR4}|\d{{2}})", ta)
    if m:
        ys = m.group(2)
        return make_month(int(ys) if len(ys) == 4 else _year2(int(ys)), _MONTHS[m.group(1).lower()])
    m = re.fullmatch(rf"(?i)({_YEAR4})\s*[-./, ]?\s*({_MONTH_RE})\.?", ta)
    if m:
        return make_month(int(m.group(1)), _MONTHS[m.group(2).lower()])

    # Numeric month-year: "01-17", "12 - 21", "2 - 22", "03.2024", "2024-03"
    m = re.fullmatch(r"(\d{1,2})\s*[-./]\s*(\d{4}|\d{2})", t)
    if m:
        p = _month_year_from_tokens(m.group(1), m.group(2))
        if p:
            return p
    m = re.fullmatch(rf"({_YEAR4})\s*[-./]\s*(\d{{1,2}})", t)
    if m:
        y, n = int(m.group(1)), int(m.group(2))
        consecutive_years = len(m.group(2)) == 2 and n == (y + 1) % 100  # 2011-12 reads as a school year
        if 1 <= n <= 12 and not (consecutive_years and hint != "M"):
            return make_month(y, n)
        if consecutive_years:
            return make_range(y, y + 1)

    # Full dates: 31.12.2023 / 31/12/2023 / 2023-12-31
    m = re.fullmatch(rf"(\d{{1,2}})[./-](\d{{1,2}})[./-]({_YEAR4})", t)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= d <= calendar.monthrange(y, mo)[1]:
            return _from_date(date(y, mo, d), hint)
    m = re.fullmatch(rf"({_YEAR4})-(\d{{1,2}})-(\d{{1,2}})", t)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= d <= calendar.monthrange(y, mo)[1]:
            return _from_date(date(y, mo, d), hint)

    # Year ranges and comparisons: 2019-2023, 2019/20, 2024/2023
    m = re.fullmatch(rf"({_YEAR4})\s*[-–—/]\s*({_YEAR4}|\d{{2}})", t)
    if m:
        y1 = int(m.group(1))
        y2 = int(m.group(2)) if len(m.group(2)) == 4 else (y1 // 100) * 100 + int(m.group(2))
        if y2 < y1 and len(m.group(2)) == 2:
            y2 += 100
        if y2 == y1 - 1 and len(m.group(2)) == 4:
            return Period(f"{y1:04d}", "A", date(y1, 1, 1), date(y1, 12, 31), base=make_year(y2))
        if y2 > y1:
            return make_range(y1, y2)
        return None

    # A year, optionally prefixed: "2023", "Viti 2023", "Year 2023", "Regjistrimi Census, 2001"
    m = re.fullmatch(rf"(?i)(?:(?:viti|vit|year|yr\.?|census|regjistrimi)[\s,:]*)*({_YEAR4})", t)
    if m:
        return make_year(int(m.group(1)))
    return None


def _ascii_months(text: str) -> str:
    """Replace ``Nëntor`` with ``Nentor`` so month-name regexes need only ASCII."""
    return text.replace("ë", "e").replace("Ë", "E")


def add_periods(p: Period, n: int) -> Period:
    """The period ``n`` steps after ``p`` (negative for before), same frequency."""
    if p.freq == "M":
        idx = p.start.year * 12 + (p.start.month - 1) + n
        return make_month(idx // 12, idx % 12 + 1)
    if p.freq == "Q":
        idx = p.start.year * 4 + (p.start.month - 1) // 3 + n
        return make_quarter(idx // 4, idx % 4 + 1)
    if p.freq == "H":
        idx = p.start.year * 2 + (0 if p.start.month == 1 else 1) + n
        return make_half(idx // 2, idx % 2 + 1)
    if p.freq == "A":
        return make_year(p.start.year + n)
    if p.freq == "D":
        return make_day(p.start + timedelta(days=n))
    raise ValueError(f"cannot step a {p.freq!r} period")


def infer_frequency(periods: list[Period]) -> str | None:
    """Dominant frequency of a sequence of periods (``'M'``, ``'Q'``, ``'A'``...)."""
    if not periods:
        return None
    return Counter(p.freq for p in periods).most_common(1)[0][0]


def missing_periods(periods: list[Period]) -> list[Period]:
    """Periods absent between the first and last of a regular series."""
    freq = infer_frequency(periods)
    if freq not in FREQ_LAG or len(periods) < 2:
        return []
    present = {p.label for p in periods if p.freq == freq}
    ordered = sorted((p for p in periods if p.freq == freq), key=lambda p: p.sort_key)
    out, cur = [], ordered[0]
    guard = 0
    while cur.sort_key < ordered[-1].sort_key and guard < 5000:
        cur = add_periods(cur, 1)
        if cur.label not in present:
            out.append(cur)
        guard += 1
    return out
