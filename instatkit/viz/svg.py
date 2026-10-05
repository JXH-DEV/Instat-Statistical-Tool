"""A small SVG toolkit on the standard library: elements, linear scales, round tick values and number formatting.

A chart is a plain SVG string styled by CSS classes and variables (see :mod:`.theme`), so one drawing serves both the
light and the dark theme, needs no script to render and weighs a few kilobytes.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from xml.sax.saxutils import escape, quoteattr

from ..i18n import mark

MINUS = "−"


def num(x: float) -> str:
    """A compact coordinate: one decimal, no trailing ``.0``."""
    s = f"{x:.1f}"
    return s[:-2] if s.endswith(".0") else s


def el(tag: str, content: str = "", **attrs: object) -> str:
    """``<tag a="b">content</tag>``; ``class_`` -> ``class``, ``data_t`` -> ``data-t``, ``None`` attributes are dropped."""
    a = "".join(f" {k.rstrip('_').replace('_', '-')}={quoteattr(str(v))}" for k, v in attrs.items() if v is not None)
    return f"<{tag}{a}>{content}</{tag}>" if content else f"<{tag}{a}/>"


def text(x: float, y: float, s: str, cls: str = "", anchor: str = "start", **extra: object) -> str:
    return el("text", escape(s), x=num(x), y=num(y), class_=cls or None, text_anchor=None if anchor == "start" else anchor, **extra)


def line(x1: float, y1: float, x2: float, y2: float, cls: str) -> str:
    return el("line", x1=num(x1), y1=num(y1), x2=num(x2), y2=num(y2), class_=cls)


def rect(x: float, y: float, w: float, h: float, cls: str = "", **extra: object) -> str:
    return el("rect", x=num(x), y=num(y), width=num(max(w, 0)), height=num(max(h, 0)), class_=cls or None, **extra)


def polyline(points: Iterable[tuple[float, float]], cls: str) -> str:
    return el("polyline", points=" ".join(f"{num(x)},{num(y)}" for x, y in points), class_=cls)


def text_width(s: str, size: float = 12) -> float:
    """Rough rendered width of ``s`` in a system sans face; good enough to size margins and truncate labels."""
    return len(s) * size * 0.56


def truncate(s: str, limit: int = 34) -> str:
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


class Linear:
    """Map a data interval onto a pixel interval."""

    def __init__(self, d0: float, d1: float, r0: float, r1: float) -> None:
        self.d0, self.r0 = d0, r0
        self.k = (r1 - r0) / (d1 - d0) if d1 != d0 else 0.0

    def __call__(self, v: float) -> float:
        return self.r0 + (v - self.d0) * self.k if self.k else self.r0


def nice_step(raw: float) -> float:
    if raw <= 0 or not math.isfinite(raw):
        return 1.0
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag * 1.0000001:
            return m * mag
    return 10 * mag


def nice_ticks(lo: float, hi: float, n: int = 5) -> list[float]:
    """Round tick values covering ``[lo, hi]`` (always at least two)."""
    if not (math.isfinite(lo) and math.isfinite(hi)):
        return [0.0, 1.0]
    if hi <= lo:
        hi = lo + (abs(lo) * 0.1 or 1.0)
    step = nice_step((hi - lo) / max(n, 1))
    first, last = math.floor(lo / step + 1e-9), math.ceil(hi / step - 1e-9)
    return [round(i * step, 10) for i in range(first, last + 1)]


def decimals_for(ticks: list[float]) -> int:
    """Fewest decimals that show every tick exactly."""
    step = abs(ticks[1] - ticks[0]) if len(ticks) > 1 else 1.0
    for d in range(5):
        if all(abs(round(t, d) - t) < 1e-9 * max(step, 1e-9) for t in ticks):
            return d
    return 4


def fmt_tick(v: float, decimals: int, unit_code: str = "") -> str:
    s = f"{abs(v):,.{decimals}f}"
    negative = v < 0 and float(s.replace(",", "")) != 0
    return f"{MINUS if negative else ''}{mark(s)}{'%' if unit_code == '%' else ''}"


def fmt_val(v: float, unit_code: str = "") -> str:
    """A value for a label or tooltip: two decimals under 1,000, whole numbers above, a percent sign for percentages."""
    a = abs(v)
    s = f"{a:,.2f}" if a < 1000 else f"{a:,.0f}"
    return f"{MINUS if v < 0 else ''}{mark(s)}{'%' if unit_code == '%' else ''}"


def fmt_signed(v: float, digits: int = 2) -> str:
    """``+1.25`` or ``−0.40``."""
    return ("+" if v >= 0 else MINUS) + mark(f"{abs(v):.{digits}f}")
