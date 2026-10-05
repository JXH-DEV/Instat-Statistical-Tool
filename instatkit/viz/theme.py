"""The colours and the stylesheet that every chart, in the app and in the report, is drawn with.

There are eight colours for categories, always in the same order so that a category keeps its colour whatever its rank, one
blue ramp for magnitude and a red-to-blue pair around a neutral grey for values above and below zero. They are set once as
CSS variables, so the same SVG works in the light and in the dark theme.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache


@dataclass(frozen=True)
class Theme:
    mode: str
    surface: str
    text: str
    text2: str
    muted: str
    grid: str
    baseline: str
    series: tuple[str, ...]
    seq: tuple[str, ...]  # light -> dark single-hue ramp for magnitude
    div_neg: str  # diverging poles
    div_pos: str
    div_mid: str
    other: str  # folded "rest" series
    page: str = "#f9f9f7"  # page background and interface colours shared by the app and the report
    border: str = "rgba(11,11,11,.10)"
    accent: str = "#2a78d6"
    good: str = "#0ca30c"
    warning: str = "#fab219"
    critical: str = "#d03b3b"


LIGHT = Theme(
    "light", "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7",
    ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"),
    ("#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"),
    "#e34948", "#2a78d6", "#f0efec", "#b9b8b1")
DARK = Theme(
    "dark", "#1a1a19", "#ffffff", "#c3c2b7", "#898781", "#2c2c2a", "#383835",
    ("#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"),
    ("#0d366b", "#184f95", "#256abf", "#3987e5", "#6da7ec", "#9ec5f4", "#cde2fb"),
    "#e66767", "#3987e5", "#383835", "#55554f", "#0d0d0d", "rgba(255,255,255,.10)", "#3987e5")


def _mix(a: str, b: str, t: float) -> str:
    ca, cb = (int(a[i:i + 2], 16) for i in (1, 3, 5)), (int(b[i:i + 2], 16) for i in (1, 3, 5))
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(ca, cb))


def diverging(t: Theme, bins: int = 7) -> list[str]:
    """Negative pole -> neutral grey -> positive pole in ``bins`` steps (the middle bin is the neutral grey)."""
    half = bins // 2
    return [_mix(t.div_neg, t.div_mid, i / half) for i in range(half)] + [t.div_mid] + \
           [_mix(t.div_mid, t.div_pos, (i + 1) / half) for i in range(half)]


def _vars(t: Theme) -> str:
    v = {"surface": t.surface, "ink": t.text, "ink2": t.text2, "muted": t.muted, "grid": t.grid, "base": t.baseline,
         "other": t.other, "pos": t.div_pos, "neg": t.div_neg, "mid": t.div_mid, "page": t.page, "border": t.border,
         "accent": t.accent, "good": t.good, "warning": t.warning, "critical": t.critical}
    v |= {f"s{i}": c for i, c in enumerate(t.series, 1)} | {f"q{i}": c for i, c in enumerate(t.seq)}
    v |= {f"d{i}": c for i, c in enumerate(diverging(t))}
    return "".join(f"--{k}:{c};" for k, c in v.items())


@cache
def chart_css() -> str:
    """Palette variables for both themes plus the chart classes. ``data-theme`` on ``<html>`` overrides the system theme."""
    series = "".join(f".c{i}{{--c:var(--s{i})}}" for i in range(1, 9)) + ".co{--c:var(--other)}"
    bins = "".join(f".q{i}{{fill:var(--q{i})}}.d{i}{{fill:var(--d{i})}}" for i in range(7))
    return (
        f":root{{color-scheme:light;{_vars(LIGHT)}}}"
        f"@media (prefers-color-scheme:dark){{:root:not([data-theme=light]){{color-scheme:dark;{_vars(DARK)}}}}}"
        f":root[data-theme=dark]{{color-scheme:dark;{_vars(DARK)}}}"
        ".chart{display:block;width:100%;height:auto;font:12px system-ui,-apple-system,'Segoe UI',sans-serif}"
        ".chart text{fill:var(--ink2)}.chart .tm{fill:var(--muted)}.chart .ti{fill:var(--ink)}"
        ".chart .grid{stroke:var(--grid);stroke-width:1;fill:none}.chart .axis{stroke:var(--base);stroke-width:1;fill:none}"
        f"{series}{bins}"
        ".ln{stroke:var(--c);stroke-width:2;fill:none;stroke-linejoin:round;stroke-linecap:round}.ln.thin{stroke-width:1.25}"
        ".ln.prov{stroke-dasharray:1 5}.ln.old{stroke:var(--base);stroke-width:1.25}"
        ".pt{fill:var(--c);stroke:var(--surface);stroke-width:2}.pt.hollow{fill:var(--surface);stroke:var(--c);stroke-width:2}"
        ".bar{fill:var(--c)}.bar.pos{fill:var(--pos)}.bar.neg{fill:var(--neg)}.cell{stroke:none}.cell.m{fill:var(--s2)}"
        ".hit{fill:transparent}.bar:hover,.cell:hover{opacity:.82}.guide{stroke:var(--muted);stroke-width:1}"
        ".key{stroke:var(--c);stroke-width:2;stroke-linecap:round}.sw{fill:var(--c)}"
        ".ctip{position:fixed;z-index:60;max-width:320px;padding:7px 10px;border:1px solid var(--base);border-radius:8px;"
        "background:var(--surface);color:var(--ink);font:13px/1.4 system-ui,-apple-system,'Segoe UI',sans-serif;"
        "box-shadow:0 2px 10px rgba(0,0,0,.14);pointer-events:none}"
        ".ctip b{font-weight:650}.ctip .sub{color:var(--ink2)}.ctip .row{display:flex;align-items:center;gap:7px;margin-top:2px}"
        ".ctip .k{flex:none;width:14px;height:0;border-top:2px solid var(--c);border-radius:2px}")
