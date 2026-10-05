"""English and Albanian.

The program text is written in English. With Albanian selected, ``tr()`` looks the sentence up in ``data/sq.json`` and
falls back to the English when there is no entry. Numbers follow the language too: 1,234.5 in English, 1 234,5 in Albanian.
"""

from __future__ import annotations

import json
import os
import sys
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from functools import cache
from importlib.resources import files

LANGUAGES = {"en": "English", "sq": "Shqip"}
_language: ContextVar[str] = ContextVar("instat_language", default="en")
_ALBANIAN_MARKS = str.maketrans({",": "\u00a0", ".": ","})  # thousands separator, decimal mark


def language() -> str:
    return _language.get()


def set_language(code: str | None) -> str:
    """Use ``code`` for everything this thread of work writes from now on; anything unknown means English."""
    code = code if code in LANGUAGES else "en"
    _language.set(code)
    return code


@contextmanager
def using(code: str | None):
    token = _language.set(code if code in LANGUAGES else "en")
    try:
        yield
    finally:
        _language.reset(token)


def pick(english: str | None, albanian: str | None, fallback: str = "") -> str:
    """The version of a text that is in the language switched on, or else the other version, or else ``fallback``."""
    first, second = (albanian, english) if _language.get() == "sq" else (english, albanian)
    return first or second or fallback


def guess(preferred: str | None) -> str:
    """The language for a browser's ``Accept-Language`` or a locale name such as ``sq-AL``; English when unsure."""
    first = (preferred or "").split(",")[0].strip().lower()
    return "sq" if first.startswith("sq") else "en"


def system_language() -> str:
    """The language of this computer's own interface, for what is printed in a console."""
    if sys.platform == "win32":
        with suppress(Exception):
            import ctypes

            primary = ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF
            return "sq" if primary == 0x1C else "en"  # 0x1C is Albanian
        return "en"
    return guess(os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG"))


@cache
def catalog(code: str) -> dict[str, str]:
    """English sentence -> its translation. English itself needs none."""
    if code not in LANGUAGES or code == "en":
        return {}
    return json.loads(files("instatkit").joinpath("data", f"{code}.json").read_text(encoding="utf-8"))


def tr(text: str, /, **values: object) -> str:
    """``text`` in the current language, with its ``{placeholders}`` filled in."""
    out = catalog(_language.get()).get(text, text)
    return out.format(**values) if values else out


def N_(text: str) -> str:
    """Mark ``text`` as translatable where it is written down, to be passed to ``tr()`` later (tables of words)."""
    return text


def tn(n: int, one: str, other: str, /, **values: object) -> str:
    """Pick the singular or plural sentence for ``n``; both use ``{n}`` for the count."""
    return tr(one if n == 1 else other, n=num(n), **values)


def mark(text: str) -> str:
    """Swap the English thousands and decimal marks in an already formatted number for the current language's."""
    return text.translate(_ALBANIAN_MARKS) if _language.get() == "sq" else text


def _format(x: float, digits: int, grouped: bool) -> str:
    text = f"{x:,.{digits}f}" if grouped else f"{x:.{digits}f}"
    if text.startswith("-"):  # a true minus sign, and no sign at all for something that rounds to zero
        text = text[1:] if not text.strip("-0.,") else "−" + text[1:]
    return mark(text)


def num(x: float, digits: int = 0) -> str:
    """A number with thousands separators and ``digits`` decimals, written the way the current language writes it."""
    return _format(x, digits, True)


def plain(x: float, digits: int = 1) -> str:
    """The same without thousands separators (for shares, rates and signed changes)."""
    return _format(x, digits, False)


def join(items: list[str]) -> str:
    """``a, b and c`` / ``a, b dhe c``."""
    items = [i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return tr("{head} and {last}", head=", ".join(items[:-1]), last=items[-1])
