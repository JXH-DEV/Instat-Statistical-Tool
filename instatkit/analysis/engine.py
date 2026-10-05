"""Orchestrates the analysis of one tidy table: statistics, findings, checks, tiles and chart suggestions."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

import numpy as np
import pandas as pd

from ..excel.tidy import TidyTable
from ..i18n import N_, num, tn, tr
from ..semantics.glossary import display
from ..semantics.interpret import DatasetProfile, DimInfo
from ..semantics.labels import by_role
from ..semantics.periods import Period, parse_period
from ..semantics.units import UnitInfo
from . import crosssection as cs
from .checks import run_checks
from .facts import Check, Fact, sort_facts
from .fmt import fmt_pct, fmt_pp, human_period
from .insights import (
    Ctx,
    composition_fact,
    gap_fact,
    growth_fact,
    movers_fact,
    ranking_fact,
    measure_text,
    series_facts,
    versus_men,
    when,
)
from .series import SeriesStats, compute_series_stats

MAX_HEADLINE_MEASURES = 3
MAX_CATEGORY_DIMS = 2
_NOT_CATEGORIES = ("sex", "period_label", "month", "year")


@dataclass
class Tile:
    label: str
    value: str
    delta: str = ""


@dataclass
class ChartSpec:
    kind: str  # lines | bars | heatmap | pyramid | seasonal
    title: str
    series_ids: list[int] = field(default_factory=list)
    params: dict = field(default_factory=dict)


@dataclass
class Analysis:
    profile: DatasetProfile
    facts: list[Fact]
    checks: list[Check]
    stats: dict[int, SeriesStats]
    labels: dict[int, str]
    headline_ids: list[int]
    tiles: list[Tile]
    charts: list[ChartSpec]
    warnings: list[str] = field(default_factory=list)
    extras: dict = field(default_factory=dict)  # recipe outputs (e.g. contribution tables)

    def facts_by_section(self) -> dict[str, list[Fact]]:
        out: dict[str, list[Fact]] = {}
        for f in self.facts:
            out.setdefault(f.section, []).append(f)
        return out


# the grand total of a national-accounts table is not called "Total"
_GRAND_TOTAL = re.compile(r"(?i)^(?:gdp|gross domestic product)(?:\s+at\s+market\s+prices)?$")


def _is_total_value(d: DimInfo, v: object) -> bool:
    return v == "" or v in d.total_values or bool(_GRAND_TOTAL.match(str(v)))


def _series_table(df: pd.DataFrame, profile: DatasetProfile, dim_names: list[str]) -> pd.DataFrame:
    """One row per series with its dimension values, label and whether it is an 'all categories' series."""
    cols = ["series_id", "measure"] + dim_names + [c for c in ("code", "level", "section") if c in df.columns]
    st = df.drop_duplicates("series_id")[cols].set_index("series_id")
    dimmap = {d.name: d for d in profile.dims}
    totalish = pd.Series(True, index=st.index)
    for name in dim_names:
        d = dimmap[name]
        totalish &= st[name].map(lambda v, d=d: _is_total_value(d, v))
    st["is_total_series"] = totalish
    st["n_obs"] = df.groupby("series_id")["value"].count()
    labels = {}
    label_dims = [n for n in dim_names if not dimmap[n].alias_of]  # a duplicating code column adds nothing
    for sid, row in st.iterrows():
        parts = [display(str(row[n])) for n in label_dims if row[n] != "" and not _is_total_value(dimmap[n], row[n])]
        base = measure_text(profile, row["measure"])
        labels[sid] = (f"{base} ({', '.join(parts)})" if base else ", ".join(parts)) if parts else (base or tr("Total"))
    st["label"] = pd.Series(labels)
    return st


def _units_for(profile: DatasetProfile, measure: str, base: UnitInfo) -> UnitInfo:
    """Table-level units, overridden by a unit the measure states itself (for example 'Coverage ratio (%)')."""
    mi = profile.measure(measure)
    if mi is None:
        return base
    return replace(base, unit=mi.unit_code or base.unit, scale=mi.scale, scale_label=mi.scale_label)


def _arrays(df: pd.DataFrame) -> dict[int, tuple[list[Period], np.ndarray]]:
    dated = df[df["period"] != ""]
    parsed = {lab: parse_period(lab) for lab in dated["period"].unique()}
    out = {}
    for sid, g in dated.groupby("series_id", sort=False):
        g = g.drop_duplicates("period").sort_values("period_start")
        ps = [parsed[lab] for lab in g["period"]]
        if any(p is None for p in ps):
            continue
        out[sid] = (ps, g["value"].to_numpy(dtype=float))
    return out


def _measure_kind(profile: DatasetProfile, measure: str) -> str:
    mi = profile.measure(measure)
    if mi:
        return mi.kind
    return profile.measures[0].kind if profile.measures else "level"


def _top_level(df: pd.DataFrame) -> int | None:
    if "level" not in df.columns or not df["level"].notna().any():
        return None
    return int(df["level"].dropna().astype(int).min())


def _rank_measures(measures: list[str], profile: DatasetProfile) -> list[str]:
    title = (profile.title or "").lower()

    def score(m: str) -> tuple[int, int]:
        ml = m.lower()
        hit = 0 if any(k in ml for k in ("gdp", "total", "gjithsej", "gross domestic")) else 1
        return (0 if ml and ml in title else hit, measures.index(m))

    return sorted(measures, key=score)


def _category_dims(profile: DatasetProfile) -> list[DimInfo]:
    """Dimensions worth comparing across: at least three real categories (totals excluded), never codes."""
    out = []
    for d in profile.dims:
        if d.role in _NOT_CATEGORIES or d.role == "code" or d.role.endswith("_code"):
            continue
        n = d.n_values - len(d.total_values)
        if n >= 3:
            out.append((n, d))
    out.sort(key=lambda t: (-(t[1].role in ("region", "activity", "product", "country", "age_group")), -t[0]))
    return [d for _, d in out]


def analyze(table: TidyTable, profile: DatasetProfile, *, recipes: bool = True) -> Analysis:
    df = table.df
    dim_names = table.dim_columns
    warnings: list[str] = []
    facts: list[Fact] = []
    charts: list[ChartSpec] = []
    tiles: list[Tile] = []
    stats: dict[int, SeriesStats] = {}

    checks = run_checks(table, profile)
    if df.empty:
        return Analysis(profile, [], checks, {}, {}, [], [], [], [tr("There are no observations to analyse.")])

    st_tab = _series_table(df, profile, dim_names)
    labels = st_tab["label"].to_dict()
    arrays = _arrays(df) if profile.n_periods >= 3 else {}
    for sid, (ps, vals) in arrays.items():
        s = compute_series_stats(ps, vals, kind=_measure_kind(profile, st_tab.loc[sid, "measure"]))
        if s is not None:
            stats[sid] = s

    measures = _rank_measures(list(dict.fromkeys(st_tab["measure"])), profile)
    ctx_by_measure = {m: Ctx(_units_for(profile, m, table.spec.units), _measure_kind(profile, m), profile.freq) for m in measures}
    cat_dims = _category_dims(profile)

    # headline series: one per measure, preferring 'all categories' series with the longest history
    headline_ids: list[int] = []
    for m in measures:
        cand = st_tab[st_tab["measure"] == m]
        pref = cand[cand["is_total_series"]]
        if _measure_kind(profile, m) == "share" and len(cand) > len(pref):
            # the total of a table of shares is always 100%: lead with the biggest part instead
            parts = cand[~cand["is_total_series"]].index
            headline_ids.append(int(max(parts, key=lambda sid: np.nan_to_num(stats[sid].latest, nan=-1.0) if sid in stats else -1.0)))
            continue
        pool = pref if len(pref) else cand
        if not len(pref) and "level" in pool.columns and pool["level"].notna().any():
            pool = pool[pool["level"] == pool["level"].min()]
        headline_ids.append(int(pool.sort_values("n_obs", ascending=False).index[0]))

    main_measure = measures[0]
    mctx = ctx_by_measure[main_measure]
    latest = profile.last_period

    if profile.kind == "cross_section":
        head_facts, tiles = _cross_headline(df, st_tab, profile, ctx_by_measure, main_measure, cat_dims)
        facts += head_facts
    else:
        multi = len(headline_ids) > 1
        for rank, sid in enumerate(headline_ids):
            m = st_tab.loc[sid, "measure"]
            ctx = ctx_by_measure[m]
            is_main = rank < MAX_HEADLINE_MEASURES
            if sid in stats:
                facts += series_facts(labels[sid], stats[sid], ctx, headline=is_main, series_id=sid, prefix=multi)
            else:
                snap = _snapshot_fact(df, sid, labels[sid], ctx)
                if snap:
                    facts.append(snap)
            if is_main:
                tiles.append(_tile(labels[sid], sid, stats.get(sid), ctx, df))
        tiles = tiles[:4]

    # comparisons across categories
    for d in cat_dims[:MAX_CATEGORY_DIMS]:
        facts += _category_facts(df, stats, d, profile, main_measure, mctx, latest)
    facts += _sex_gap_facts(df, profile, main_measure, mctx, latest)

    _default_charts(charts, headline_ids, stats, profile, cat_dims, labels)
    analysis = Analysis(profile, [], checks, stats, labels, headline_ids, tiles, charts, warnings)
    if recipes:
        from .recipes import apply_recipes

        apply_recipes(table, profile, analysis, facts)  # isolates each recipe's failures itself
    facts += _caveat_facts(profile, checks)
    analysis.facts = sort_facts(_dedupe(facts))
    return analysis


def _reference_slice(df: pd.DataFrame, profile: DatasetProfile, dim: DimInfo, measure: str) -> pd.DataFrame:
    """Rows of ``measure`` where every *other* dimension is held at its total (or, lacking one, its most common value)."""
    sel = df[df["measure"] == measure]
    for d in profile.dims:
        if d.name == dim.name or sel.empty or d.alias_of == dim.name or dim.alias_of == d.name:
            continue
        present = set(sel[d.name])
        totals = [v for v in d.total_values if v in present]
        if "" in present and not totals:
            totals = [""]
        sel = sel[sel[d.name].isin(totals)] if totals else sel[sel[d.name] == sel[d.name].mode().iloc[0]]
    return sel


def _category_rows(sel: pd.DataFrame, dim: DimInfo) -> pd.DataFrame:
    totals = {*dim.total_values, "", *(v for v in sel[dim.name].unique() if _GRAND_TOTAL.match(str(v)))}
    sel = sel[~sel[dim.name].isin(totals)]
    lv = _top_level(sel)
    if lv is not None:
        sel = sel[sel["level"] == lv]
    return sel


def snapshot_by_dim(df: pd.DataFrame, profile: DatasetProfile, dim_name: str, measure: str | None = None,
                    period: str | None = None) -> tuple[pd.Series, str]:
    """Value of each category of ``dim_name`` at ``period`` (default: the latest), with every other dimension held
    at its total. Returns ``(values indexed by category, period used)``; used by charts and the Explore view."""
    dim = next(d for d in profile.dims if d.name == dim_name)
    measure = measure or profile.measures[0].name
    sel = _category_rows(_reference_slice(df, profile, dim, measure), dim)
    if sel.empty:
        return pd.Series(dtype=float), ""
    period = period if period in set(sel["period"]) else (profile.last_period if profile.last_period in set(sel["period"]) else sel["period"].iloc[-1])
    snap = sel[sel["period"] == period].drop_duplicates(dim.name).set_index(dim.name)["value"]
    return snap, period


def category_matrix(df: pd.DataFrame, profile: DatasetProfile, dim_name: str, measure: str | None = None,
                    max_rows: int = 24, max_cols: int = 40) -> pd.DataFrame:
    """Categories (rows) x periods (columns) for one measure, other dimensions held at their totals."""
    dim = next(d for d in profile.dims if d.name == dim_name)
    measure = measure or profile.measures[0].name
    sel = _category_rows(_reference_slice(df, profile, dim, measure), dim)
    sel = sel[sel["period"] != ""]
    if sel.empty:
        return pd.DataFrame()
    order = sel.drop_duplicates("period").sort_values("period_start")["period"].tolist()[-max_cols:]
    pivot = sel.drop_duplicates([dim.name, "period"]).pivot(index=dim.name, columns="period", values="value")[order]
    return pivot.reindex(pivot.iloc[:, -1].abs().sort_values(ascending=False).index).head(max_rows)


def _cross_headline(df, st_tab, profile: DatasetProfile, ctx_by_measure, measure, cat_dims):
    """A cross-section has no 'latest value'; state the total if there is one, otherwise the range."""
    ctx = ctx_by_measure[measure]
    period = profile.last_period or ""
    rows = st_tab[(st_tab["measure"] == measure) & st_tab["is_total_series"]]
    if len(rows):
        sid = int(rows.index[0])
        g = df[df["series_id"] == sid].dropna(subset=["value"])
        if len(g):
            v = float(g["value"].iloc[-1])
            label = st_tab.loc[sid, "label"]
            text = (tr("{subject}: {value} in {period}.", subject=label, value=ctx.val(v), period=human_period(period)) if period
                    else tr("{subject}: {value}.", subject=label, value=ctx.val(v)))
            return ([Fact("latest", "headline", st_tab.loc[sid, "label"], text, 0.95, {"value": v, "period": period}, sid, period or None)],
                    [Tile(st_tab.loc[sid, "label"], ctx.val(v), human_period(period))])
    if not cat_dims:
        return [], []
    d = cat_dims[0]
    sel = _category_rows(_reference_slice(df, profile, d, measure), d)
    snap = sel.drop_duplicates(d.name).set_index(d.name)["value"].dropna()
    sp = cs.spread(snap)
    if sp is None:
        return [], []
    hi, lo = sp.top[0], sp.bottom[0]
    values = {"measure": measure_text(profile, measure), "by": by_role(d.role), "period": human_period(period), "lo": ctx.val(lo[1]),
              "lo_name": display(str(lo[0])), "hi": ctx.val(hi[1]), "hi_name": display(str(hi[0])), "n": num(sp.n),
              "median": ctx.val(sp.median)}
    text = (tr("{measure} {by}, {period}: from {lo} ({lo_name}) to {hi} ({hi_name}) across {n} categories. The median is {median}.", **values)
            if period else
            tr("{measure} {by}: from {lo} ({lo_name}) to {hi} ({hi_name}) across {n} categories. The median is {median}.", **values))
    tiles = [Tile(tr("Highest: {name}", name=values["hi_name"]), values["hi"], human_period(period)),
             Tile(tr("Lowest: {name}", name=values["lo_name"]), values["lo"], human_period(period)),
             Tile(tr("Median"), values["median"], tn(sp.n, "{n} category", "{n} categories"))]
    return [Fact("range", "headline", values["measure"], text, 0.95, {"high": hi, "low": lo, "median": sp.median}, None, period or None)], tiles


def _category_facts(df, stats, dim: DimInfo, profile, measure, ctx: Ctx, latest) -> list[Fact]:
    out: list[Fact] = []
    sel = _category_rows(_reference_slice(df, profile, dim, measure), dim)
    if sel.empty:
        return out
    label = measure_text(profile, measure)
    snap_period = latest if latest in set(sel["period"]) else sel["period"].iloc[-1]
    snap = sel[sel["period"] == snap_period].drop_duplicates(dim.name).set_index(dim.name)["value"]
    mi = profile.measure(measure)
    if len(snap.dropna()) >= 3:
        f = ranking_fact(label, snap.dropna(), ctx, snap_period, dim.role)
        if f:
            out.append(f)
        if mi and mi.additive:
            f = composition_fact(label, snap, snap_period, dim.role)
            if f:
                out.append(f)
    # who is moving fastest: year on year (or on the previous period) per category
    if stats:
        chg: dict[str, float] = {}
        basis, from_period = None, None
        for sid in sel["series_id"].unique():
            s = stats.get(int(sid))
            if not s:
                continue
            name = sel.loc[sel["series_id"] == sid, dim.name].iloc[0]
            if s.yoy_abs is not None and ctx.freq in ("M", "Q", "H"):
                chg[name] = s.yoy_abs if ctx.pp else s.yoy_pct
                basis, from_period = N_("a year earlier"), s.yoy_period
            elif s.change_abs is not None:
                chg[name] = s.change_abs if ctx.pp else s.change_pct
                basis, from_period = N_("the previous period"), s.prev_period
        if chg and basis:
            f = movers_fact(label, pd.Series(chg).dropna(), ctx, profile.last_period or "", basis, from_period)
            if f:
                out.append(f)
    if profile.n_periods >= 2 and ctx.kind in ("level", "index"):
        first_p = profile.first_period
        a = sel[sel["period"] == first_p].drop_duplicates(dim.name).set_index(dim.name)["value"]
        b = sel[sel["period"] == snap_period].drop_duplicates(dim.name).set_index(dim.name)["value"]
        f = growth_fact(label, cs.growth_between(a, b), first_p, snap_period, dim.role)
        if f:
            out.append(f)
    return out


def _sex_gap_facts(df, profile, measure, ctx: Ctx, latest) -> list[Fact]:
    sex = profile.dim("sex")
    if sex is None:
        return []
    vals = set(df[sex.name])
    female = next((v for v in vals if v in ("Females", "Female", "Women", "Girls")), None)
    male = next((v for v in vals if v in ("Males", "Male", "Men", "Boys")), None)
    if not female or not male:
        return []
    sel = df[df["measure"] == measure]
    if sel.empty:
        return []
    period = latest if latest in set(sel["period"]) else sel["period"].iloc[-1]
    sel = sel[sel["period"] == period]
    others = [d for d in profile.dims if d.name != sex.name and d.role not in ("period_label",)]
    cats = [d for d in others if d.n_values - len(d.total_values) >= 2 and d.role != "code" and not d.role.endswith("_code")]
    label = measure_text(profile, measure)
    if not cats:
        a = sel.loc[sel[sex.name] == female, "value"].dropna()
        b = sel.loc[sel[sex.name] == male, "value"].dropna()
        if len(a) == 1 and len(b) == 1:
            x, y = float(a.iloc[0]), float(b.iloc[0])
            rel = fmt_pp(abs(x - y)) if ctx.pp else (fmt_pct(abs(x / y - 1) * 100, 0) if y else "")
            if rel:
                txt = tr("{label}{when}: women {a}, men {b}. The value for women is {relation}.", label=label, when=when(period),
                         a=ctx.val(x), b=ctx.val(y), relation=versus_men(False, x > y, rel))
                return [Fact("gap", "comparison", label, txt, 0.72, {"female": x, "male": y, "period": period})]
        return []
    d = cats[0]
    for od in others:
        if od.name == d.name or od.alias_of == d.name or d.alias_of == od.name:
            continue
        tv = [v for v in od.total_values if v in set(sel[od.name])]
        sel = sel[sel[od.name].isin(tv)] if tv else sel[sel[od.name] == sel[od.name].mode().iloc[0]]
    sel = _category_rows(sel, d)
    a = sel[sel[sex.name] == female].drop_duplicates(d.name).set_index(d.name)["value"]
    b = sel[sel[sex.name] == male].drop_duplicates(d.name).set_index(d.name)["value"]
    f = gap_fact(label, cs.gaps(a, b), ctx, period, d.role)
    return [f] if f else []


def _snapshot_fact(df: pd.DataFrame, sid: int, subject: str, ctx: Ctx) -> Fact | None:
    g = df[df["series_id"] == sid].dropna(subset=["value"])
    if g.empty:
        return None
    r = g.iloc[-1]
    value = ctx.val(float(r["value"]))
    text = (tr("{subject}: {value} in {period}.", subject=subject, value=value, period=human_period(r["period"])) if r["period"]
            else tr("{subject}: {value}.", subject=subject, value=value))
    return Fact("latest", "headline", subject, text, 0.9, {"value": float(r["value"]), "period": r["period"]}, sid, r["period"] or None)


def _tile(subject: str, sid: int, st: SeriesStats | None, ctx: Ctx, df: pd.DataFrame) -> Tile:
    if st is None:
        g = df[df["series_id"] == sid].dropna(subset=["value"])
        return Tile(subject, ctx.val(float(g["value"].iloc[-1])) if len(g) else tr("n/a"), "")
    delta_abs = st.yoy_abs if st.yoy_abs is not None else st.change_abs
    since = human_period(st.yoy_period if st.yoy_abs is not None else st.prev_period)
    if delta_abs is None:
        return Tile(subject, ctx.val(st.latest), human_period(st.latest_period))
    sign = "+" if delta_abs > 0 else "−" if delta_abs < 0 else ""
    if ctx.pp:
        magnitude = fmt_pp(abs(delta_abs))
    elif st.min_value <= 0:  # a percent change means nothing for a series that is or was negative
        magnitude = ctx.val(abs(delta_abs))
    else:
        base = st.yoy if st.yoy_abs is not None else st.prev
        magnitude = fmt_pct(abs(delta_abs / abs(base) * 100 if base else 0))
    change = sign + magnitude if sign else tr("unchanged")
    delta = tr("{change} vs {period}", change=change, period=since)
    return Tile(subject, ctx.val(st.latest), f"{delta} · {human_period(st.latest_period)}")


def _caveat_facts(profile: DatasetProfile, checks: list[Check]) -> list[Fact]:
    out = []
    if profile.provisional_periods:
        periods = ", ".join(human_period(p) for p in profile.provisional_periods[:3])
        out.append(Fact("caveat", "caveat", "data", tr("Figures for {periods} are provisional and may be revised.", periods=periods), 0.6))
    for c in checks:
        if c.status in ("warn", "fail") and c.key in ("completeness", "period continuity", "layout detection"):
            out.append(Fact("caveat", "caveat", c.name, c.detail, 0.55 if c.status == "warn" else 0.8, {"check": c.key}))
    return out


def _dedupe(facts: list[Fact]) -> list[Fact]:
    seen, out = set(), []
    for f in facts:
        key = (f.kind, f.subject, f.text)
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


def _default_charts(charts: list[ChartSpec], headline_ids, stats, profile, cat_dims, labels) -> None:
    if profile.kind == "time_series" and headline_ids:
        charts.append(ChartSpec("lines", tr("Main series"), list(headline_ids[:4]), {"markers": profile.n_periods <= 24}))
        s = stats.get(headline_ids[0])
        if s and s.seasonality and s.seasonality.strength >= 0.4:
            charts.append(ChartSpec("seasonal", tr("Seasonal pattern: {series}", series=labels[headline_ids[0]]), [headline_ids[0]]))
    if cat_dims:
        d = cat_dims[0]
        charts.append(ChartSpec("bars", tr("Latest values {by}", by=by_role(d.role)), [], {"dim": d.name}))
        if profile.kind == "time_series":
            charts.append(ChartSpec("heatmap", tr("Over time, {by}", by=by_role(d.role)), [], {"dim": d.name}))
    if profile.dim("age_group") and profile.dim("sex"):
        charts.append(ChartSpec("pyramid", tr("Population pyramid"), [], {}))
