"""Numbers and periods written for people, in the language that is switched on."""

from __future__ import annotations

import math

from ..i18n import N_, mark, num, tr
from ..i18n import join as join_list  # noqa: F401  (the analysis modules import it from here)
from ..semantics.units import unit_text

_MONTHS = [N_("January"), N_("February"), N_("March"), N_("April"), N_("May"), N_("June"), N_("July"), N_("August"),
           N_("September"), N_("October"), N_("November"), N_("December")]
_SHORT_MONTHS = [N_("Jan"), N_("Feb"), N_("Mar"), N_("Apr"), N_("May"), N_("Jun"), N_("Jul"), N_("Aug"), N_("Sep"), N_("Oct"),
                 N_("Nov"), N_("Dec")]
_CURRENCIES = {"ALL": N_("ALL {amount}"), "EUR": N_("EUR {amount}"), "USD": N_("USD {amount}")}
_BIG = ((1e12, N_("{value} trillion")), (1e9, N_("{value} billion")), (1e6, N_("{value} million")))


def month_name(month: int, *, short: bool = False) -> str:
    return tr((_SHORT_MONTHS if short else _MONTHS)[month - 1])


def human_period(label: str) -> str:
    """``2023-Q2`` -> ``Q2 2023``; ``2017-01`` -> ``January 2017``; ``2019-2023`` stays."""
    if not label:
        return ""
    if "-Q" in label:
        year, q = label.split("-Q")
        return tr("Q{q} {year}", q=q, year=year)
    if "-H" in label:
        year, h = label.split("-H")
        return tr("H{h} {year}", h=h, year=year)
    parts = label.split("-")
    if len(parts) == 2 and len(parts[0]) == 4 and len(parts[1]) == 2 and parts[1].isdigit() and 1 <= int(parts[1]) <= 12:
        return tr("{month} {year}", month=month_name(int(parts[1])), year=parts[0])
    if len(parts) == 3 and len(parts[0]) == 4:
        return tr("{day} {month} {year}", day=int(parts[2]), month=month_name(int(parts[1])), year=parts[0])
    return label


def short_period(label: str) -> str:
    """``2017-01`` -> ``Jan 2017`` for tight spaces."""
    parts = label.split("-")
    if len(parts) == 2 and len(parts[0]) == 4 and len(parts[1]) == 2 and parts[1].isdigit() and 1 <= int(parts[1]) <= 12:
        return tr("{month} {year}", month=month_name(int(parts[1]), short=True), year=parts[0])
    return human_period(label)


def _missing(x: float | None) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


def fmt_number(x: float | None, *, digits: int | None = None) -> str:
    """As many decimals as the size of the number calls for: 12,345 / 123.4 / 1.23."""
    if _missing(x):
        return tr("n/a")
    a = abs(x)
    if digits is None:
        digits = 0 if a >= 1000 else 1 if a >= 10 else 2 if a >= 1 else 3 if a >= 0.01 else 4
    return num(x, digits)


def _compact(x: float) -> str:
    a = abs(x)
    for limit, words in _BIG:
        if a >= limit:
            return tr(words, value=mark(f"{x / limit:,.2f}".rstrip("0").rstrip(".")))
    return fmt_number(x)


def fmt_pct(x: float, digits: int = 1, *, signed: bool = False) -> str:
    """``4.3%``, or ``+4.3%`` with ``signed``."""
    return _sign(x, signed) + num(abs(x), digits) + "%"


def fmt_pp(x: float, digits: int = 1, *, signed: bool = False) -> str:
    """``0.4 pp`` (percentage points), or ``+0.4 pp`` with ``signed``."""
    return tr("{value} pp", value=_sign(x, signed) + num(abs(x), digits))


def risen(up: bool) -> str:
    """"risen" or "fallen", for sentences like "has risen by 2 pp"."""
    return tr("risen") if up else tr("fallen")


def _sign(x: float, signed: bool) -> str:
    if not signed:
        return "−" if x < 0 else ""
    return "+" if x > 0 else "−" if x < 0 else ""


def fmt_value(x: float | None, unit_code: str = "", *, scale: float | None = None, digits: int | None = None,
              unit_label: str = "") -> str:
    """A value with its unit; table-level "million ALL" is scaled back to absolute amounts for reading."""
    if _missing(x):
        return tr("n/a")
    if unit_code == "%":
        return num(x, 1 if digits is None else digits) + "%"
    if unit_code in _CURRENCIES:
        absolute = x * (scale or 1.0)
        return ("−" if absolute < 0 else "") + tr(_CURRENCIES[unit_code], amount=_compact(abs(absolute)))
    if unit_code == "persons":
        absolute = x * (scale or 1.0)
        return tr("{amount} people", amount=_compact(absolute) if abs(absolute) >= 1e7 else fmt_number(absolute, digits=0))
    if unit_code == "index":
        return fmt_number(x, digits=1 if digits is None else digits)
    if unit_code == "per 1,000":
        return tr("{value} per 1,000", value=num(x, 1))
    base = fmt_number(x, digits=digits)
    return f"{base} {unit_text(unit_label)}".strip() if unit_label else base
