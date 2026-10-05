"""The Albanian and English words for the labels INSTAT tables use over and over (sexes, regions, age bands, totals).

The CSV (``data/glossary_sq_en.csv``) is plain ``sq,en,tag`` so it can be extended without touching code. It translates
Albanian labels to English when a table is read, and gives the Albanian back when the program is shown in Albanian.
"""

from __future__ import annotations

import csv
import re
from collections import Counter
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path

from ..i18n import language
from .textnorm import clean_text, fold

_CSV = Path(__file__).resolve().parent.parent / "data" / "glossary_sq_en.csv"
_file_words: ContextVar[dict[str, str] | None] = ContextVar("instat_file_words", default=None)

_NATIONAL_NAMES = ("shqipëria", "shqipëri", "albania", "gjithsej shqipëria", "total albania")
NATIONAL_NAMES = frozenset(fold(w) for w in _NATIONAL_NAMES)
TOTAL_WORDS = frozenset(
    fold(w) for w in ("total", "gjithsej", "totali", "të gjitha", "të gjithë", "all", "both sexes", "të dy gjinitë", *_NATIONAL_NAMES)
)


@lru_cache(maxsize=1)
def _load() -> tuple[dict[str, tuple[str, str]], dict[str, tuple[str, str]], dict[str, str]]:
    by_sq: dict[str, tuple[str, str]] = {}
    by_en: dict[str, tuple[str, str]] = {}
    to_sq: dict[str, str] = {}  # the first Albanian form listed for an English term
    with open(_CSV, encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            sq, en, tag = row["sq"].strip(), row["en"].strip(), row["tag"].strip()
            by_sq.setdefault(fold(sq), (en, tag))
            by_en.setdefault(fold(en), (en, tag))
            to_sq.setdefault(fold(en), sq)
    return by_sq, by_en, to_sq


_AGE_PATTERNS = [
    (re.compile(r"^(\d+)\s*vje[cç]\s*e\s*lart$", re.I), r"\1 years and over"),
    (re.compile(r"^(\d+)\s*vje[cç]\s*dhe\s*m[eë]\s*shum[eë]$", re.I), r"\1 years and over"),
    (re.compile(r"^(\d+)\s*[-–]\s*(\d+)\s*vje[cç]$", re.I), r"\1-\2 years"),
    (re.compile(r"^(\d+)\s*vje[cç]$", re.I), r"\1 years"),
    (re.compile(r"^mbi\s*(\d+)\s*vje[cç]$", re.I), r"over \1 years"),
    (re.compile(r"^deri\s*n[eë]\s*(\d+)\s*vje[cç]$", re.I), r"up to \1 years"),
    (re.compile(r"^m[eë]\s*pak\s*se\s*(\d+)\s*vje[cç]$", re.I), r"under \1 years"),
]


_AGE_PATTERNS_SQ = [
    (re.compile(r"^(\d+) years and over$"), r"\1 vjeç e lart"),
    (re.compile(r"^(\d+)-(\d+) years$"), r"\1-\2 vjeç"),
    (re.compile(r"^(\d+) years$"), r"\1 vjeç"),
    (re.compile(r"^over (\d+) years$"), r"mbi \1 vjeç"),
    (re.compile(r"^up to (\d+) years$"), r"deri në \1 vjeç"),
    (re.compile(r"^under (\d+) years$"), r"më pak se \1 vjeç"),
]

_WITH_BRACKET = re.compile(r"^(.+?)\s*(\([^()]*\))$")

_AGE_BAND = re.compile(r"^(?:[1-9]?\d{1,2}\s*[-–]\s*\d{1,3}|\d{1,3}\s*\+|(?:under|over|below)\s+\d+.*|\d+\s*(?:years?|vje[cç]).*)$", re.I)


def looks_like_age_band(values: Iterable[str]) -> bool:
    """Do these labels look like age bands (``0-14``, ``65+``, ``15 years and over``)? Leading zeros rule out codes."""
    vs = [clean_text(v) for v in values if v and not is_total_label(v)]
    if len(vs) < 2 or any(re.match(r"^0\d", v) for v in vs):
        return False
    return sum(1 for v in vs if _AGE_BAND.match(v)) / len(vs) >= 0.7


def translate(text: str) -> str | None:
    """English for an Albanian term, or ``None`` when the glossary has no entry."""
    t = clean_text(text)
    hit = _load()[0].get(fold(t))
    if hit:
        return hit[0]
    for pat, repl in _AGE_PATTERNS:
        if pat.match(t):
            return pat.sub(repl, t)
    return None


@contextmanager
def file_words(words: dict[str, str]) -> Iterator[None]:
    """While this is active, ``display`` uses the Albanian wording the file itself has for a label ({'Male': 'Meshkuj'})."""
    token = _file_words.set(words)
    try:
        yield
    finally:
        _file_words.reset(token)


def display(text: str) -> str:
    """A label as it should be shown: with Albanian switched on, the file's own Albanian for it, else the glossary's for a
    standard English term ("Males" becomes "Meshkuj", "15-64 years" becomes "15-64 vjeç"); anything else, and everything in
    English, stays as it is."""
    if language() != "sq" or not text:
        return text
    t = clean_text(text)
    if hit := (_file_words.get() or {}).get(t) or _load()[2].get(fold(t)):
        return hit
    for pat, repl in _AGE_PATTERNS_SQ:
        if pat.match(t):
            return pat.sub(repl, t)
    if m := _WITH_BRACKET.match(t):  # "Coverage ratio (%)": the name is translated, the bracket stays
        if hit := _load()[2].get(fold(m[1])):
            return f"{hit} {m[2]}"
    return text


def age_label(text: str) -> str:
    """An age band to put after the word "ages": "15 years and over" is "15 and over" in English, "15 vjeç e lart" in Albanian."""
    return display(text) if language() == "sq" else text.replace(" years", "")


def tag_of(text: str) -> str | None:
    """Glossary category of a term (``county``, ``sex``, ``month``, ...), in either language."""
    key = fold(clean_text(text))
    by_sq, by_en, _to_sq = _load()
    hit = by_sq.get(key) or by_en.get(key)
    if hit:
        return hit[1]
    t = clean_text(text)
    return "age" if any(p.match(t) for p, _ in _AGE_PATTERNS) else None


_TOTAL_SINGLES = frozenset(w for w in TOTAL_WORDS if " " not in w)


def is_total_label(text: str) -> bool:
    """``Total``, ``Gjithsej``, and the two written together (``Gjithsej Total``, ``Gjithsej - Total``)."""
    key = fold(clean_text(text))
    if key in TOTAL_WORDS:
        return True
    parts = [p for p in re.split(r"[\s\-–/|]+", key) if p]
    return len(parts) == 2 and all(p in _TOTAL_SINGLES for p in parts)


def is_generic_total(text: str) -> bool:
    """A total that is not the country's own name: in a table of birth, residence or citizenship, "Albania" is a category."""
    return is_total_label(text) and fold(clean_text(text)) not in NATIONAL_NAMES


def dominant_tag(values: Iterable[str], *, min_share: float = 0.6) -> tuple[str | None, float]:
    """Most common glossary tag among ``values`` (ignoring totals), and the share it covers."""
    tags: list[str | None] = []
    for v in values:
        if is_total_label(v):
            continue
        tags.append(tag_of(v))
    if not tags:
        return None, 0.0
    counts = Counter(t for t in tags if t)
    if not counts:
        return None, 0.0
    tag, n = counts.most_common(1)[0]
    share = n / len(tags)
    return (tag if share >= min_share else None), share
