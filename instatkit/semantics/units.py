"""Extract unit, scale, index base and price basis from title/header/note text (Albanian or English).

Examples handled: ``miliardë lekë/billion ALL``, ``(Dhjetor / December 2020 = 100)``,
``(2021 – 2025*, me çmime korente)``, ``Në mijë persona``, ``%``, ``Ndryshimi vjetor (%)``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..i18n import N_, tr
from .periods import month_number
from .textnorm import clean_text, fold

# The words of a unit label ("million ALL", "index (base 2020-12)"), so it can be shown in either language.
_UNIT_WORDS = {
    "thousand": N_("thousand"), "million": N_("million"), "billion": N_("billion"), "ALL": N_("ALL"), "EUR": N_("EUR"),
    "USD": N_("USD"), "persons": N_("persons"), "index": N_("index"), "tonnes": N_("tonnes"), "litres": N_("litres"),
    "years": N_("years"), "count": N_("count"), "households": N_("households"), "dwellings": N_("dwellings"),
    "buildings": N_("buildings"), "visitors": N_("visitors"), "nights": N_("nights"), "base": N_("base"),
    "per 1,000": N_("per 1,000"),
}
_UNIT_WORD = re.compile(r"\b(?:" + "|".join(sorted(map(re.escape, _UNIT_WORDS), key=len, reverse=True)) + r")\b")  # longest first


def unit_text(label: str | None) -> str:
    """A unit label as it is shown: the same words, in the current language."""
    return _UNIT_WORD.sub(lambda m: tr(_UNIT_WORDS[m.group()]), label or "")


@dataclass
class UnitInfo:
    unit: str | None = None  # ALL, EUR, USD, %, index, persons, count, tonnes, ...
    scale: float | None = None  # 1e3 thousand, 1e6 million, 1e9 billion
    scale_label: str | None = None
    base_period: str | None = None  # '2020-12', '2015', 'previous_year', ...
    base_value: float | None = None
    price_basis: str | None = None  # current | previous_year | constant
    unit_weak: bool = False  # unit inferred from a weak cue ("rate", "population"), not stated explicitly
    raw: list[str] = field(default_factory=list)

    def merge(self, other: UnitInfo) -> UnitInfo:
        """Fill gaps in ``self`` from ``other``: first writer wins, except that an explicit unit beats a weak one."""
        for name in ("scale", "scale_label", "base_period", "base_value", "price_basis"):
            if getattr(self, name) is None and getattr(other, name) is not None:
                setattr(self, name, getattr(other, name))
        if other.unit is not None and (self.unit is None or (self.unit_weak and not other.unit_weak)):
            self.unit, self.unit_weak = other.unit, other.unit_weak
        self.raw.extend(r for r in other.raw if r not in self.raw)
        return self

    @property
    def label(self) -> str:
        """Human-readable unit, e.g. ``'million ALL'`` or ``'index (2020-12=100)'``."""
        parts = []
        if self.scale_label:
            parts.append(self.scale_label)
        if self.unit:
            parts.append(self.unit)
        label = " ".join(parts)
        if self.unit == "index" and self.base_period:
            label += f" ({self.base_period}={self.base_value:g})" if self.base_value else f" (base {self.base_period})"
        return label


_SCALES = [
    (re.compile(r"\bmiliard\w*|\bbillions?\b|\bbn\b"), 1e9, "billion"),
    (re.compile(r"\bmilion\w*|\bmillions?\b|\bmln\b|\bmio\b"), 1e6, "million"),
    (re.compile(r"\bmij[eë]\b|\bthousands?\b|\b000\b|\b000s\b"), 1e3, "thousand"),
]

# (pattern, canonical unit) in priority order; the earliest match in the text wins.
_UNITS = [
    (re.compile(r"%|\bper[cç]ind\w*|\bpercent\w*|\bper cent\b|\bpp\b"), "%"),
    (re.compile(r"\blek[eë]\w*|\ball\b"), "ALL"),
    (re.compile(r"\beuro\w*|\beur\b|€"), "EUR"),
    (re.compile(r"\busd\b|\bdollar\w*|\$"), "USD"),
    (re.compile(r"\bindeks\w*|\bindex\b|\bindices\b|\bindexes\b"), "index"),
    (re.compile(r"\bpersona\b|\bpersons?\b|\bpeople\b|\bnjer[eë]z\b|\bbanor[eë]\b|\binhabitants\b"), "persons"),
    (re.compile(r"\bton[eë]?\b|\btonnes?\b|\btons?\b"), "tonnes"),
    (re.compile(r"\bhektar\w*|\bhectares?\b|\bha\b"), "ha"),
    (re.compile(r"\bkwh\b|\bgwh\b|\bmwh\b|\bkilowatt\w*"), "kWh"),
    (re.compile(r"\bm3\b|m³|\bmetra kub\w*|\bcubic met\w*"), "m3"),
    (re.compile(r"\bm2\b|m²|\bmetra katror\w*|\bsquare met\w*"), "m2"),
    (re.compile(r"\bkm\b|\bkilomet\w*"), "km"),
    (re.compile(r"\blitra\b|\blitres?\b|\bliters?\b"), "litres"),
    (re.compile(r"\bkg\b|\bkilogram\w*"), "kg"),
    # "(years)", "in years", "në vite": a duration. "aged 10 years and over" or "15 vjeç e lart" only describe who is counted.
    (re.compile(r"\((?:in\s+|n[eë]\s+)?(?:years?|vite|vjet)\)|\b(?:in|n[eë])\s+(?:years|vite|vjet)\b"), "years"),
    (re.compile(r"\bnumri\b|\bnumber\b|\bnum[eë]r\b|\bcount\b|\bnr\.?\b"), "count"),
]

_BASE_PATTERNS = [
    # "Dhjetor / December 2020 = 100"  |  "December 2020 = 100"
    (re.compile(r"(?:(?P<sq>[a-zëç]+)\s*/\s*)?(?P<en>[a-zëç]{3,})\.?\s*(?P<y>(?:19|20)\d{2})\s*=\s*(?P<v>\d+(?:[.,]\d+)?)"), "month_year"),
    (re.compile(r"(?P<y>(?:19|20)\d{2})\s*=\s*(?P<v>\d+(?:[.,]\d+)?)"), "year"),
    (re.compile(r"(?:base(?:\s+year)?|baza|viti\s+baz[eë]|base\s+period)\s*[:=]?\s*(?P<y>(?:19|20)\d{2})"), "year_nov"),
    (re.compile(r"(?:viti\s+i\s+m[eë]parsh[eë]m|previous\s+year|prev\.?\s+year)\s*=\s*(?P<v>\d+)"), "previous_year"),
    (re.compile(r"(?:periudh\w*\s+p[eë]rkat[eë]se|same\s+(?:month|period|quarter)\b[^=]{0,40}previous\s+year)[^=]{0,40}=\s*(?P<v>\d+)"), "same_period"),
    (re.compile(r"dhjetor[^=]{0,30}m[eë]parsh[eë]m\s*=\s*(?P<v>\d+)|december\s+(?:of\s+)?(?:the\s+)?previous\s+year\s*=\s*(?P<v2>\d+)"), "previous_december"),
]

_WEAK_UNITS = [
    (re.compile(r"\bper\s*1[\s,.]?000\b|\bp[eë]r\s*1[\s,.]?000\b|\bper mille\b|‰|\bmortality\b|\bvdekshm\w*|\bbirth rate\b|\blindshm\w*"), "per 1,000"),
    (re.compile(r"\bshkall\w*|\brate\b|\bratio\b|\bshare\b|\bnd[eë]rtimi\b|\bpjes[eë]marrj\w*|\bkoeficient\w*|"
                r"\bgrowth\b|\brritj\w*|\bstructure\b|\bstruktur\w*|\bcontribution\w*|\bkontribut\w*"), "%"),
    (re.compile(r"\bpopullsi\w*|\bpopulation\b|\bbanor[eë]\w*"), "persons"),
]

_CHANGE_WORDS = re.compile(r"\bndryshim\w*|\bchanges?\b|\bgrowth\b|\brritj\w*|\bvariation\b")

_PRICES = [
    (re.compile(r"[cç]mim\w*\s+korent\w*|current\s+prices?"), "current"),
    (re.compile(r"[cç]mim\w*\s+e\s+vitit\s+t[eë]\s+m[eë]parsh[eë]m|previous\s+year(?:'s)?\s+prices?|prices?\s+of\s+the\s+previous\s+year"), "previous_year"),
    (re.compile(r"[cç]mim\w*\s+konstant\w*|[cç]mim\w*\s+t[eë]\s+pandryshuar\w*|constant\s+prices?|chain[- ]linked"), "constant"),
]


_SUBJECT_UNITS = [
    (re.compile(r"\b(?:households?|families|family)\b|\bnj[eë]sit[eë]? ekonomike\b"), "households"),
    (re.compile(r"\bdwellings?\b|\bhousing units?\b|\bbanesa\w*"), "dwellings"),
    (re.compile(r"\bbuildings?\b|\bnd[eë]rtes\w*"), "buildings"),
    (re.compile(r"\b(?:visitors?|arrivals?|tourists?|vizitor\w*|ardhj\w*)\b"), "visitors"),
    (re.compile(r"\b(?:nights?|net[eë]\w*)\b"), "nights"),
    (re.compile(r"\b(?:population|persons?|people|women|men|children|inhabitants|residents|pupils|students|employees|"
                r"workers|births|deaths|migrants|emigrants|immigrants|popullsi\w*|persona\w*)\b"), "persons"),
]


def subject_unit(title: str | None) -> str | None:
    """What a count in this table counts, from the subject of the title: 'Resident population in private
    households by ...' counts persons, 'Private households by ...' counts households."""
    if not title:
        return None
    head = re.split(r"\s+(?:by|according to|sipas)\s+", fold(title), maxsplit=1)[0]
    head = re.split(r"\s+(?:in|n[eë])\s+", head, maxsplit=1)[0]
    hits = [(m.start(), unit) for pat, unit in _SUBJECT_UNITS if (m := pat.search(head))]
    return min(hits)[1] if hits else None  # the first noun named is the subject


def _parse_value(text: str | None) -> float | None:
    if text is None:
        return None
    try:
        return float(text.replace(",", "."))
    except ValueError:
        return None


def parse_units(*texts: str) -> UnitInfo:
    """Scan one or more text fragments and return everything unit-like found in them."""
    info = UnitInfo()
    for raw in texts:
        t = clean_text(raw)
        if not t:
            continue
        low = fold(t)
        sub = _scan(low)
        sub.raw = [t]
        info.merge(sub)
    return info


def _scan(low: str) -> UnitInfo:
    info = UnitInfo()

    for pat, kind in _BASE_PATTERNS:
        m = pat.search(low)
        if not m:
            continue
        gd = m.groupdict()
        if kind == "month_year":
            mo = month_number(gd.get("en") or "") or month_number(gd.get("sq") or "")
            if mo:
                info.base_period = f"{gd['y']}-{mo:02d}"
                info.base_value = _parse_value(gd["v"])
                break
            continue
        if kind in ("year", "year_nov"):
            info.base_period = gd["y"]
            info.base_value = _parse_value(gd.get("v")) or 100.0
            break
        info.base_period = kind
        info.base_value = _parse_value(gd.get("v") or gd.get("v2"))
        break

    for pat, basis in _PRICES:
        if pat.search(low):
            info.price_basis = basis
            break

    for pat, factor, label in _SCALES:
        if pat.search(low):
            info.scale, info.scale_label = factor, label
            break

    best = None
    for pat, unit in _UNITS:
        m = pat.search(low)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), unit)
    if best:
        info.unit = best[1]
    else:  # weak cues, only used when nothing explicit was stated
        for pat, unit in _WEAK_UNITS:
            if pat.search(low):
                info.unit, info.unit_weak = unit, True
                break
    if info.base_period and info.unit is None:
        info.unit = "index"
    if info.unit == "index" and _CHANGE_WORDS.search(low) and not info.base_period:
        info.unit = "%"  # "Annual change of the consumer price index" is a percentage change
    return info
