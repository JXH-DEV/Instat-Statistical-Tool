"""Robust number parsing for spreadsheet cells.

Covers real numbers, numbers stored as text (``"1 234,5"``, ``"12,5%"``, ``"(12)"``), missing-value
markers (``..``, ``-``, ``x``) and trailing status letters (``123p``, ``45 e``).
"""

from __future__ import annotations

import math
import re
from typing import NamedTuple

from .textnorm import clean_text

# token -> flag. Values are None in all cases; the flag records *why*.
MARKERS: dict[str, str] = {
    "..": "na", "...": "na", "....": "na", "…": "na", "n/a": "na", "na": "na", "n.a.": "na", "n.a": "na",
    "nd": "na", ":": "na", "#n/a": "na", "#div/0!": "na", "#value!": "na", "#ref!": "na",
    "-": "nil", "–": "nil", "—": "nil", "z": "nil", "--": "nil", "---": "nil",
    "x": "suppressed", "c": "suppressed", "(c)": "suppressed", "conf.": "suppressed",
    "*": "note", "**": "note",
}

_NUM_CORE = re.compile(r"[+-]?(?:\d[\d.,]*|[.,]\d+)(?:[eE][+-]?\d+)?")
_TRAIL_FLAG = re.compile(r"^(?P<num>.*?\d)\s*(?P<flag>\*+|\(\s*[pPeEr]\s*\)|[pPeEr]|sf|SF)\s*$")
_MINUS = str.maketrans({"−": "-", "–": "-", "—": "-", "‐": "-"})


class Num(NamedTuple):
    value: float | None
    flag: str | None = None  # na / nil / suppressed / note / p / e / r / text
    unit_hint: str | None = None  # '%' when a percent sign was present
    is_marker: bool = False


def _decimal_string(s: str, decimal: str | None) -> str | None:
    """Normalise ``s`` (digits with ``.``/``,``) to a string ``float()`` accepts."""
    if "e" in s.lower():
        head, _, exp = s.lower().partition("e")
        inner = _decimal_string(head, decimal)
        return None if inner is None else f"{inner}e{exp}"
    has_dot, has_comma = "." in s, "," in s
    if has_dot and has_comma:
        dec, thou = (".", ",") if s.rfind(".") > s.rfind(",") else (",", ".")
        if not re.fullmatch(rf"[+-]?\d{{1,3}}(?:\{thou}\d{{3}})*\{dec}\d+", s):
            return None  # e.g. 1.2.3,4 - thousands groups must be exactly three digits
        s = s.replace(thou, "").replace(dec, ".")
    elif has_comma:
        if decimal == "," or not re.fullmatch(r"[+-]?\d{1,3}(?:,\d{3})+", s):
            if s.count(",") > 1:
                return None
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    elif has_dot:
        if re.fullmatch(r"[+-]?\d{1,3}(?:\.\d{3}){2,}", s):
            s = s.replace(".", "")  # 1.234.567
        elif decimal == "," and re.fullmatch(r"[+-]?\d{1,3}\.\d{3}", s):
            s = s.replace(".", "")
        elif s.count(".") > 1:
            return None
    return s


def parse_number(value: object, *, decimal: str | None = None) -> Num:
    """Parse any cell value. ``decimal`` may force ``'.'`` or ``','`` for ambiguous strings."""
    if value is None or isinstance(value, bool):
        return Num(None)
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return Num(None, "na")
        return Num(float(value))
    if hasattr(value, "year"):  # dates are not numbers
        return Num(None, "text")

    t = clean_text(value)
    if not t:
        return Num(None)
    flag = MARKERS.get(t.lower())
    if flag:
        return Num(None, flag, is_marker=True)

    t = t.translate(_MINUS)
    # Text that looks like a code, not a quantity: leading zeros ("000000", "01.1"), trailing dot ("01.")
    if re.match(r"^[+-]?0\d", t) or (t.endswith(".") and t[:-1].replace(".", "").isdigit()):
        return Num(None, "text")
    unit_hint = None
    status = None
    if t.endswith("%"):
        unit_hint, t = "%", t[:-1].strip()
    m = _TRAIL_FLAG.match(t)
    if m:
        t = m.group("num").strip()
        f = m.group("flag").lower().strip("() ")
        status = "p" if f.startswith("*") or f in ("p", "sf") else f
    negative = False
    if t.startswith("(") and t.endswith(")"):
        t, negative = t[1:-1].strip(), True
    t = t.replace(" ", "")
    if not t or not _NUM_CORE.fullmatch(t):
        return Num(None, "text")
    s = _decimal_string(t, decimal)
    if s is None:
        return Num(None, "text")
    try:
        x = float(s)
    except ValueError:
        return Num(None, "text")
    if math.isnan(x) or math.isinf(x):
        return Num(None, "text")
    return Num(-x if negative else x, status, unit_hint)


def looks_numeric(value: object) -> bool:
    """True for real numbers, numeric text and missing-value markers (cells that belong in a data grid)."""
    n = parse_number(value)
    return n.value is not None or n.is_marker
