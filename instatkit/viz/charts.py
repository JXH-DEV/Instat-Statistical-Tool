"""The charts, drawn as SVG strings: lines, small multiples, bars, population pyramid, heatmap and seasonal lines.

Colours come from a fixed eight-colour palette in a fixed order, so an entity keeps its colour whatever its rank. Each chart
has one axis: series with different units are stacked as small panels instead of sharing two. Everything is styled by CSS
classes (see ``theme.py``), so a chart looks right in the light and the dark theme. Hovering is handled by ``chart.js`` from
the ``data-tips`` and ``data-t`` attributes written here, and every value is also in the tables next to the charts.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd

from ..analysis.fmt import human_period, month_name, short_period
from ..i18n import mark, tn, tr
from . import svg
from .svg import Linear, el, fmt_signed, fmt_tick, fmt_val, line, nice_ticks, num, polyline, rect, text, text_width, truncate

W = 760


class ColorMap:
    """Stable colour class per entity: the first eight distinct labels get ``c1``..``c8`` in order; the rest share grey."""

    def __init__(self, labels: list[str]) -> None:
        self.slots = {lab: i + 1 for i, lab in enumerate(dict.fromkeys(labels)) if i < 8}

    def cls(self, label: str) -> str:
        return f"c{self.slots[label]}" if label in self.slots else "co"

    def is_other(self, label: str) -> bool:
        return label not in self.slots


def _svg(height: float, body: str, label: str, tips: list | None = None) -> str:
    extra = {"data_tips": json.dumps(tips, separators=(",", ":"), ensure_ascii=False)} if tips else {}
    return el("svg", body, class_="chart", viewBox=f"0 0 {W} {num(height)}", role="img", aria_label=label, **extra)


def _empty() -> str:
    message = tr("There is nothing to draw.")
    return _svg(80, text(W / 2, 44, message, "tm", "middle"), message)


def _legend(entries: list[tuple[str, str, str]], y: float) -> tuple[str, float]:
    """Key + label per series, wrapped over rows. Entries are ``(class, label, 'line' | 'swatch')``; returns (svg, height)."""
    x, row, parts = 8.0, 0, []
    for cls, label, kind in entries:
        label = truncate(label, 40)
        w = 24 + text_width(label) + 18
        if x + w > W - 8 and x > 8:
            x, row = 8.0, row + 1
        cy = y + row * 20 + 8
        key = line(x, cy, x + 16, cy, "key") if kind == "line" else rect(x, cy - 5, 14, 10, "sw")
        parts.append(el("g", key, class_=cls) + text(x + 22, cy + 4, label))
        x += w
    return "".join(parts), (row + 1) * 20


def _y_axis(ticks: list[float], ysc: Linear, x0: float, x1: float, unit_code: str) -> tuple[str, int]:
    dec = svg.decimals_for(ticks)
    out = []
    for t in ticks:
        y = ysc(t)
        out.append(line(x0, y, x1, y, "grid") + text(x0 - 8, y + 4, fmt_tick(t, dec, unit_code), "tm", "end"))
    return "".join(out), dec


def _x_labels(periods: list[str], cx, base_y: float, max_ticks: int = 10) -> str:
    step = max(1, math.ceil(len(periods) / max_ticks))
    out = []
    for i in range(0, len(periods), step):
        out.append(line(cx(i), base_y, cx(i), base_y + 4, "axis") + text(cx(i), base_y + 19, short_period(periods[i]), "tm", "middle"))
    return "".join(out)


def _y_domain(values: pd.Series) -> list[float]:
    lo, hi = float(values.min()), float(values.max())
    if lo >= 0 and lo < 0.5 * hi:  # a series that starts near zero is drawn from zero
        lo = 0.0
    return nice_ticks(lo, hi, 5)


def _line_panel(df: pd.DataFrame, labels: list[str], colors: ColorMap, periods: list[str], unit_code: str, *, x0: float,
                y0: float, width: float, height: float, x_labels: bool, end_labels: bool, panel: int = 0) -> tuple[str, list[dict]]:
    """One plot area: grid, axes, a line per label (dotted where provisional), hover bands. Returns (svg, tips)."""
    values = df["value"].dropna()
    ticks = _y_domain(values)
    ysc = Linear(ticks[0], ticks[-1], y0 + height, y0)
    n = len(periods)
    step = width / n
    cx = lambda i: x0 + (i + 0.5) * step
    pos = {p: i for i, p in enumerate(periods)}
    grid, _ = _y_axis(ticks, ysc, x0, x0 + width, unit_code)
    body = [grid, line(x0, y0 + height, x0 + width, y0 + height, "axis")]
    if x_labels:
        body.append(_x_labels(periods, cx, y0 + height))
    markers = df["period"].nunique() <= 24
    ends: list[tuple[float, float, str]] = []
    cells: dict[int, list[list[str]]] = {}
    provisional: set[int] = set()
    for lab in labels:
        g = df[df["label"] == lab].dropna(subset=["value"])
        if g.empty:
            continue
        g = g.assign(i=g["period"].map(pos)).dropna(subset=["i"]).sort_values("i")
        cls, other = colors.cls(lab), colors.is_other(lab)
        prov = g["flag"].eq("p") if "flag" in g else pd.Series(False, index=g.index)
        final = g[~prov] if prov.any() and not prov.all() else g
        pts = [(cx(int(i)), ysc(v)) for i, v in zip(final["i"], final["value"])]
        parts = [polyline(pts, "ln thin" if other else "ln")] if len(pts) > 1 else []
        if markers and not other:
            parts += [el("circle", cx=num(x), cy=num(y), r=4, class_="pt") for x, y in pts]
        if prov.any() and not prov.all():  # provisional tail: dotted continuation from the last final value
            tail = pd.concat([final.tail(1), g[prov]])
            tpts = [(cx(int(i)), ysc(v)) for i, v in zip(tail["i"], tail["value"])]
            parts.append(polyline(tpts, "ln prov"))
            parts += [el("circle", cx=num(x), cy=num(y), r=4, class_="pt hollow") for x, y in tpts[1:]]
        body.append(el("g", "".join(parts), class_=cls))
        for i, v, p in zip(g["i"], g["value"], prov):
            cells.setdefault(int(i), []).append([cls, lab, fmt_val(float(v), unit_code)])
            if p:
                provisional.add(int(i))
        if end_labels and not other:
            last = float(g["value"].iloc[-1])
            ends.append((cx(int(g["i"].iloc[-1])), ysc(last), fmt_val(last, unit_code)))
    ys = sorted(y for _x, y, _t in ends)
    if ends and all(b - a >= 14 for a, b in zip(ys, ys[1:])):  # labels that would collide are left to the legend and tooltip
        body += [text(x + 10, y + 4, t) for x, y, t in ends]
    tips = [{"h": human_period(periods[i]) + (tr(" · provisional") if i in provisional else ""), "r": cells.get(i, [])} for i in range(n)]
    body.append(el("line", x1=0, y1=num(y0), x2=0, y2=num(y0 + height), class_="guide", visibility="hidden"))
    body += [rect(x0 + i * step, y0, step, height, "hit", data_i=i, data_p=panel, data_x=num(cx(i))) for i in range(n)]
    return "".join(body), tips


def line_chart(df: pd.DataFrame, *, label_col: str = "label", unit_code: str = "", unit_label: str = "",
               colors: ColorMap | None = None, height: int = 380, title: str = "") -> str:
    """``df``: one row per observation with ``label``, ``period``, ``period_start``, ``value``, ``flag``."""
    d = df.rename(columns={label_col: "label"}) if label_col != "label" else df
    if d["value"].dropna().empty:
        return _empty()
    labels = list(dict.fromkeys(d["label"]))
    colors = colors or ColorMap(labels)
    periods = d.drop_duplicates("period").sort_values("period_start")["period"].tolist()
    ticks = _y_domain(d["value"].dropna())
    dec = svg.decimals_for(ticks)
    left = 20 + max(text_width(fmt_tick(t, dec, unit_code)) for t in ticks) + 10
    legend, lh = _legend([(colors.cls(lab), lab, "line") for lab in labels], 0) if len(labels) >= 2 else ("", 0)
    top = 10 + (lh + 8 if lh else 0)
    end = len(labels) <= 4
    right = 76 if end else 24
    body, tips = _line_panel(d, labels, colors, periods, unit_code, x0=left, y0=top, width=W - left - right,
                             height=height - top - 40, x_labels=True, end_labels=end)
    if unit_label:
        mid = top + (height - top - 40) / 2
        body += el("text", svg.escape(unit_label), x=12, y=num(mid), transform=f"rotate(-90 12 {num(mid)})", text_anchor="middle", class_="tm")
    label = tr("{title}: {n} series, {first} to {last}", title=title or tr("Line chart"), n=len(labels),
               first=human_period(periods[0]), last=human_period(periods[-1]))
    return _svg(height, legend + body, label, [tips])


def small_multiples(groups: list[tuple[str, str, pd.DataFrame]], *, colors: ColorMap | None = None, height_per: int = 220,
                    title: str = "") -> str:
    """Stacked panels, one per unit, so measures on different scales never share an axis. ``groups`` are (title, unit_code, df)."""
    all_labels = [lab for _t, _u, d in groups for lab in dict.fromkeys(d["label"])]
    colors = colors or ColorMap(all_labels)
    all_periods = pd.concat([g[2] for g in groups]).drop_duplicates("period").sort_values("period_start")["period"].tolist()
    legend, lh = _legend([(colors.cls(lab), lab, "line") for lab in dict.fromkeys(all_labels)], 0) if len(set(all_labels)) >= 2 else ("", 0)
    body, tips = [legend], []
    for k, (ptitle, unit_code, d) in enumerate(groups):
        if d["value"].dropna().empty:
            continue
        ticks = _y_domain(d["value"].dropna())
        left = 20 + max(text_width(fmt_tick(t, svg.decimals_for(ticks), unit_code)) for t in ticks) + 10
        y0 = lh + (8 if lh else 0) + k * height_per + 34
        plot_h = height_per - 34 - (38 if k == len(groups) - 1 else 22)
        part, ptips = _line_panel(d, list(dict.fromkeys(d["label"])), colors, all_periods, unit_code, x0=left, y0=y0, width=W - left - 24,
                                  height=plot_h, x_labels=k == len(groups) - 1, end_labels=False, panel=k)
        body.append(text(8, y0 - 14, ptitle, "ti"))
        body.append(part)
        tips.append(ptips)
    return _svg(lh + (8 if lh else 0) + height_per * len(groups) + 6, "".join(body),
                tr("{title}: {n} panels", title=title or tr("Line charts"), n=len(groups)), tips)


def _bar_path(x0: float, x1: float, y: float, h: float, r: float = 4) -> str:
    """A horizontal bar from the baseline ``x0`` to ``x1``: square at the baseline, rounded at the data end."""
    r = min(r, h / 2, abs(x1 - x0))
    s = 1 if x1 >= x0 else -1
    e = x1 - s * r
    return (f"M{num(x0)} {num(y)}H{num(e)}Q{num(x1)} {num(y)} {num(x1)} {num(y + r)}V{num(y + h - r)}"
            f"Q{num(x1)} {num(y + h)} {num(e)} {num(y + h)}H{num(x0)}Z")


def _hbars(items: list[tuple[str, float]], *, bar_cls, value_text, unit_code: str = "", unit_label: str = "", title: str,
           row_h: int = 30) -> str:
    """Horizontal bars, first item on top. One baseline, value at the bar tip, category names in text ink."""
    if not items:
        return _empty()
    keys = [truncate(str(k)) for k, _ in items]
    vals = [v for _k, v in items]
    ticks = nice_ticks(min(0.0, *vals), max(0.0, *vals), 5)
    dec = svg.decimals_for(ticks)
    left = max(text_width(k) for k in keys) + 18
    right = max(text_width(value_text(v)) for v in vals) + 20
    xsc = Linear(ticks[0], ticks[-1], left, W - right)
    top, bar_h = 8, min(22, row_h - 8)
    plot_h = row_h * len(items)
    zero = xsc(0)
    body = []
    for t in ticks:
        body.append(line(xsc(t), top, xsc(t), top + plot_h, "grid") + text(xsc(t), top + plot_h + 18, fmt_tick(t, dec, unit_code), "tm", "middle"))
    for i, ((k, v), name) in enumerate(zip(items, keys)):
        y = top + i * row_h + (row_h - bar_h) / 2
        x1 = xsc(v)
        tip = f"{k}\n{value_text(v)}"
        body.append(el("path", d=_bar_path(zero, x1, y, bar_h), class_=bar_cls(v), data_t=tip))
        body.append(text(left - 10, y + bar_h / 2 + 4, name, "", "end"))
        body.append(text(x1 + (6 if v >= 0 else -6), y + bar_h / 2 + 4, value_text(v), "", "start" if v >= 0 else "end"))
    body.append(line(zero, top, zero, top + plot_h, "axis"))
    if unit_label:
        body.append(text((left + W - right) / 2, top + plot_h + 36, unit_label, "tm", "middle"))
    return _svg(top + plot_h + (44 if unit_label else 28), "".join(body), tn(len(items), "{title}: {n} bar", "{title}: {n} bars", title=title))


def bars_latest(values: pd.Series, *, unit_code: str = "", unit_label: str = "", top: int = 15, title: str = "") -> str:
    """Largest first. One series: one colour, no legend; the value sits at the bar tip."""
    v = values.dropna()
    v = v.reindex(v.abs().sort_values(ascending=False).index).head(top)
    return _hbars([(str(k), float(x)) for k, x in v.items()], unit_code=unit_code, unit_label=unit_label, title=title or tr("Bar chart"),
                  bar_cls=lambda _x: "bar c1", value_text=lambda x: fmt_val(x, unit_code))


def signed_bars(values: pd.Series, *, unit_label: str = "", top: int = 12, title: str = "") -> str:
    """Contributions and gaps: bars to either side of a zero line, in the two colours for positive and negative."""
    v = values.dropna()
    v = v.reindex(v.abs().sort_values(ascending=False).index).head(top).sort_values(ascending=False)
    return _hbars([(str(k), float(x)) for k, x in v.items()], unit_label=unit_label, title=title or tr("Contributions"),
                  bar_cls=lambda x: "bar pos" if x >= 0 else "bar neg", value_text=fmt_signed)


def pyramid(df: pd.DataFrame, *, age_col: str, sex_col: str, male: str, female: str, unit_label: str = "",
            title: str = "") -> str:
    """Population pyramid for one period: ``df`` has the age groups (youngest first), each with a male and a female value."""
    ages = list(dict.fromkeys(df[age_col]))
    m = df[df[sex_col] == male].set_index(age_col)["value"].reindex(ages).fillna(0.0)
    f = df[df[sex_col] == female].set_index(age_col)["value"].reindex(ages).fillna(0.0)
    ticks = nice_ticks(0.0, max(float(m.max()), float(f.max()), 1.0), 4)
    men, women = tr("Men"), tr("Women")
    legend, lh = _legend([("c1", men, "swatch"), ("c2", women, "swatch")], 0)
    left, right = max(text_width(a) for a in ages) + 16, 44
    mid, k = (left + W - right) / 2, (W - right - left) / 2 / ticks[-1]
    row_h, bar_h, top = 22, 16, lh + 10
    plot_h = row_h * len(ages)
    body = [legend]
    for t in sorted({-t for t in ticks} | set(ticks)):
        x = mid + t * k
        body.append(line(x, top, x, top + plot_h, "axis" if t == 0 else "grid") + text(x, top + plot_h + 18, mark(f"{abs(t):,.0f}"), "tm", "middle"))
    for j, age in enumerate(reversed(ages)):  # oldest at the top
        y = top + j * row_h + (row_h - bar_h) / 2
        mv, fv = float(m[age]), float(f[age])
        body.append(text(left - 10, y + bar_h / 2 + 4, age, "", "end"))
        body.append(el("path", d=_bar_path(mid, mid - mv * k, y, bar_h), class_="bar c1", data_t=f"{age} · {men}\n{mark(f'{mv:,.0f}')}"))
        body.append(el("path", d=_bar_path(mid, mid + fv * k, y, bar_h), class_="bar c2", data_t=f"{age} · {women}\n{mark(f'{fv:,.0f}')}"))
    if unit_label:
        body.append(text(mid, top + plot_h + 36, unit_label, "tm", "middle"))
    return _svg(top + plot_h + (44 if unit_label else 28), "".join(body),
                tn(len(ages), "{title}: {n} age group", "{title}: {n} age groups", title=title or tr("Population pyramid")))


def heatmap(pivot: pd.DataFrame, *, signed: bool = False, unit_code: str = "", max_rows: int = 24, title: str = "") -> str:
    """Categories by periods. Size is shown with one colour getting darker; data with both signs uses two colours around zero."""
    p = pivot.head(max_rows)
    rows, cols = [str(r) for r in p.index], [short_period(str(c)) for c in p.columns]
    z = p.to_numpy(dtype=float)
    if not z.size or not (z == z).any():
        return _empty()
    lo, hi = float(np.nanmin(z)), float(np.nanmax(z))
    lim = max(abs(lo), abs(hi)) or 1.0
    left = max(text_width(truncate(r, 30)) for r in rows) + 18
    cw, ch, top = (W - left - 24) / len(cols), 22, 8
    prefix = "d" if signed else "q"
    body = []
    for i, r in enumerate(rows):
        y = top + i * ch
        body.append(text(left - 10, y + ch / 2 + 4, truncate(r, 30), "", "end"))
        for j, v in enumerate(z[i]):
            if v != v:
                continue
            b = round((v + lim) / (2 * lim) * 6) if signed else round((v - lo) / ((hi - lo) or 1.0) * 6)
            body.append(rect(left + j * cw + 1, y + 1, max(cw - 2, 1), ch - 2, f"cell {prefix}{b}",
                             data_t=f"{r} · {cols[j]}\n{fmt_val(float(v), unit_code)}"))
    base = top + ch * len(rows)
    step = max(1, math.ceil(len(cols) / 12))
    for j in range(0, len(cols), step):
        x = left + (j + 0.5) * cw
        body.append(el("text", svg.escape(cols[j]), x=num(x), y=num(base + 16), class_="tm", text_anchor="end" if len(cols) > 8 else "middle",
                       transform=f"rotate(-45 {num(x)} {num(base + 16)})" if len(cols) > 8 else None))
    ly = base + (58 if len(cols) > 8 else 36)
    body.append(text(left, ly + 9, fmt_val(-lim if signed else lo, unit_code), "tm"))
    body += [rect(left + 60 + i * 22, ly, 20, 10, f"cell {prefix}{i}") for i in range(7)]
    body.append(text(left + 60 + 7 * 22 + 6, ly + 9, fmt_val(lim if signed else hi, unit_code), "tm"))
    return _svg(ly + 24, "".join(body), tr("{title}: {rows} rows by {columns} periods", title=title or tr("Heatmap"), rows=len(rows),
                                           columns=len(cols)))


def seasonal_chart(df: pd.DataFrame, *, freq: str, unit_code: str = "", unit_label: str = "", title: str = "") -> str:
    """One line per year across the months or quarters: the latest year stands out, earlier years are grey."""
    d = df.dropna(subset=["value"]).copy()
    if d.empty:
        return _empty()
    d["year"] = d["period_start"].dt.year
    d["pos"] = d["period_start"].dt.month if freq == "M" else (d["period_start"].dt.month - 1) // 3 + 1
    names = [month_name(m, short=True) for m in range(1, 13)] if freq == "M" else [tr("Q{q}", q=q) for q in range(1, 5)]
    latest = int(d["year"].max())
    ticks = _y_domain(d["value"])
    left = 20 + max(text_width(fmt_tick(t, svg.decimals_for(ticks), unit_code)) for t in ticks) + 10
    legend, lh = _legend([("c1", str(latest), "line"), ("co", tr("Earlier years"), "line")], 0)
    top, height = lh + 10, 340
    width, plot_h = W - left - 24, height - lh - 10 - 40
    ysc = Linear(ticks[0], ticks[-1], top + plot_h, top)
    step = width / len(names)
    cx = lambda i: left + (i - 0.5) * step
    grid, _ = _y_axis(ticks, ysc, left, left + width, unit_code)
    body = [legend, grid, line(left, top + plot_h, left + width, top + plot_h, "axis")]
    body += [text(cx(i + 1), top + plot_h + 19, n, "tm", "middle") for i, n in enumerate(names)]
    by_year = {int(y): g.sort_values("pos") for y, g in d.groupby("year")}
    for y in sorted(by_year):
        g = by_year[y]
        pts = [(cx(int(p)), ysc(float(v))) for p, v in zip(g["pos"], g["value"])]
        if y == latest:
            continue
        body.append(polyline(pts, "ln old") if len(pts) > 1 else "")
    g = by_year[latest]
    pts = [(cx(int(p)), ysc(float(v))) for p, v in zip(g["pos"], g["value"])]
    body.append(el("g", (polyline(pts, "ln") if len(pts) > 1 else "") + "".join(el("circle", cx=num(x), cy=num(y), r=4, class_="pt") for x, y in pts), class_="c1"))
    tips = []
    for i in range(1, len(names) + 1):
        rows = [["c1" if y == latest else "co", str(y), fmt_val(float(by_year[y].loc[by_year[y]["pos"] == i, "value"].iloc[0]), unit_code)]
                for y in sorted(by_year, reverse=True) if (by_year[y]["pos"] == i).any()][:8]
        tips.append({"h": names[i - 1], "r": rows})
    body.append(el("line", x1=0, y1=num(top), x2=0, y2=num(top + plot_h), class_="guide", visibility="hidden"))
    body += [rect(left + i * step, top, step, plot_h, "hit", data_i=i, data_p=0, data_x=num(cx(i + 1))) for i in range(len(names))]
    if unit_label:
        mid = top + plot_h / 2
        body.append(el("text", svg.escape(unit_label), x=12, y=num(mid), transform=f"rotate(-90 12 {num(mid)})", text_anchor="middle", class_="tm"))
    return _svg(height, "".join(body), tn(len(by_year), "{title}: {n} year", "{title}: {n} years", title=title or tr("Seasonal pattern")),
                [tips])


def missing_map(missing: pd.DataFrame, labels: list[str], title: str = "") -> str:
    """Series by periods. Only the missing cells are drawn, so gaps stand out against an empty field."""
    rows, cols = [truncate(label, 30) for label in labels], [short_period(str(c)) for c in missing.columns]
    z = missing.to_numpy(dtype=bool)
    left = max(text_width(r) for r in rows) + 18
    cw, ch, top = (W - left - 24) / len(cols), 18, 8
    body = []
    for i, r in enumerate(rows):
        y = top + i * ch
        body.append(text(left - 10, y + ch / 2 + 4, r, "", "end"))
        body += [rect(left + j * cw + 1, y + 1, max(cw - 2, 1), ch - 2, "cell m", data_t=f"{labels[i]} · {cols[j]}\n{tr('missing')}")
                 for j in range(len(cols)) if z[i, j]]
    base = top + ch * len(rows)
    step = max(1, math.ceil(len(cols) / 12))
    for j in range(0, len(cols), step):
        x = left + (j + 0.5) * cw
        body.append(el("text", svg.escape(cols[j]), x=num(x), y=num(base + 16), class_="tm", text_anchor="end",
                       transform=f"rotate(-45 {num(x)} {num(base + 16)})"))
    return _svg(base + 56, "".join(body), tr("{title}: {n} series", title=title or tr("Missing values"), n=len(rows)))
