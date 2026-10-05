"""Turns the numbers of a table into sentences.

The wording rules: say what happened, not why; always name the period a number belongs to; say "unchanged" instead of
reporting noise as movement; use percentage points for rates and percent for amounts. Every sentence starts with its
subject ("Exports: ALL 31.6 billion in May 2024.") so it reads the same whatever the subject is.
"""

from __future__ import annotations

import math
import re

import pandas as pd

from ..i18n import N_, num, plain, tr
from ..semantics.glossary import display
from ..semantics.labels import by_role
from ..semantics.periods import FREQ_LAG, parse_period
from ..semantics.units import UnitInfo
from . import crosssection as cs
from .context import events_for
from .facts import Fact
from .fmt import fmt_pct, fmt_pp, fmt_value, human_period, join_list, month_name
from .fmt import risen as fmt_risen
from .series import SeriesStats

EPS_PP = 0.05  # a change smaller than this is "unchanged"

_RISING = {"rising": N_("rising"), "falling": N_("falling")}


def short_measure(name: str, limit: int = 70) -> str:
    """'Gross average monthly wage by economic activity and sex, 2023' -> 'Gross average monthly wage'."""
    s = re.split(r"\s+(?:by|sipas)\s+", name.strip(), maxsplit=1, flags=re.I)[0]
    s = re.sub(r"[,;:\-–]\s*(?:19|20)\d{2}(?:\s*[-–]\s*(?:19|20)\d{2})?\s*$", "", s)
    s = re.sub(r"\s*\((?:19|20)\d{2}[^)]*\)\s*$", "", s).strip(" ,.;:")
    return (s[: limit - 1] + "…") if len(s) > limit else s


def measure_text(profile, name: str) -> str:
    """The short, displayable name of a measure of ``profile``."""
    info = profile.measure(name)
    return short_measure(info.display if info else name)


class Ctx:
    """How to write the values of one measure: its unit, its kind and the frequency of the table."""

    def __init__(self, units: UnitInfo, kind: str, freq: str | None):
        self.units = units
        self.kind = kind
        self.freq = freq

    @property
    def pp(self) -> bool:
        return self.kind in ("rate", "growth", "share")

    def val(self, x: float | None, digits: int | None = None) -> str:
        return fmt_value(x, self.units.unit or "", scale=self.units.scale, digits=digits, unit_label=self._label())

    def _label(self) -> str:
        u = self.units.unit
        return "" if u in (None, "", "ALL", "EUR", "USD", "%", "index", "persons", "count", "per 1,000") else u


def _season_name(lag: int, i: int) -> str:
    if lag == 12:
        return month_name(i + 1)
    if lag == 4:
        return tr("Q{q}", q=i + 1)
    if lag == 2:
        return tr("H{h}", h=i + 1)
    return str(i)


def _events(period_label: str) -> str:
    p = parse_period(period_label)
    events = events_for(p.start, p.end) if p else []
    return tr(" (possible context: {events})", events=join_list(events)) if events else ""


def _delta_phrase(ctx: Ctx, abs_change: float | None, pct_change: float | None, *, allow_pct: bool = True) -> tuple[str, bool] | None:
    """('up 0.4 pp', False) or ('unchanged', True); ``None`` when there is nothing to compare.

    A percent change means nothing for a series that is or was negative (a shrinking deficit is not "up 27%"),
    so with ``allow_pct=False`` the change is given in the series' own unit instead.
    """
    unchanged = (tr("unchanged"), True)
    if abs_change is None:
        return None
    if ctx.pp:
        if abs(abs_change) < EPS_PP:
            return unchanged
        return _up_down(abs_change, fmt_pp(abs(abs_change)))
    if not allow_pct:
        return unchanged if abs_change == 0 else _up_down(abs_change, ctx.val(abs(abs_change)))
    if pct_change is None:
        return None
    if abs(pct_change) < 0.05:
        return unchanged
    return _up_down(pct_change, fmt_pct(abs(pct_change)))


def _up_down(change: float, amount: str) -> tuple[str, bool]:
    if change > 0:
        return tr("up {amount}", amount=amount), False
    return tr("down {amount}", amount=amount), False


def series_facts(subject: str, st: SeriesStats, ctx: Ctx, *, headline: bool, series_id: int | None = None,
                 prefix: bool = False) -> list[Fact]:
    """The facts about one series. A headline series gets all of them, the others only the essentials.

    ``prefix`` puts the subject in front of every sentence, which is needed when several series are discussed together.
    """
    facts: list[Fact] = []
    w = 1.0 if headline else 0.45
    lag = FREQ_LAG.get(st.freq or "", 0)
    lead = f"{subject}: " if prefix else ""

    # the latest value
    values = {"subject": subject, "value": ctx.val(st.latest), "period": human_period(st.latest_period)}
    if ctx.kind == "index" and ctx.units.base_period:
        text = tr("{subject}: {value} in {period} (base {base} = {base_value}).", **values, base=human_period(ctx.units.base_period),
                  base_value=plain(ctx.units.base_value or 100, 0 if (ctx.units.base_value or 100) % 1 == 0 else 1))
    else:
        text = tr("{subject}: {value} in {period}.", **values)
    facts.append(Fact("latest", "headline", subject, text, 0.95 * w, {"value": st.latest, "period": st.latest_period},
                      series_id, st.latest_period))

    # the change on the previous period and on a year earlier
    positive = st.min_value > 0
    prev = _delta_phrase(ctx, st.change_abs, st.change_pct, allow_pct=positive)
    yoy = _delta_phrase(ctx, st.yoy_abs, st.yoy_pct, allow_pct=positive) if lag > 1 else None
    parts = []
    if prev:
        parts.append(tr("{change} on {period}", change=prev[0], period=human_period(st.prev_period)))
    if yoy:
        parts.append(tr("{change} on {period}", change=yoy[0], period=human_period(st.yoy_period)))
    if parts:
        if prev and prev[1] and (not yoy or yoy[1]):
            sentence = tr("{subject}: unchanged on {period}.", subject=subject, period=human_period(st.prev_period))
        else:
            sentence = tr("{subject}: {changes}.", subject=subject, changes=join_list(parts))
        facts.append(Fact("change", "change", subject, sentence, 0.9 * w,
                          {"prev": st.prev, "prev_period": st.prev_period, "change_abs": st.change_abs,
                           "change_pct": st.change_pct, "yoy": st.yoy, "yoy_period": st.yoy_period,
                           "yoy_abs": st.yoy_abs, "yoy_pct": st.yoy_pct}, series_id, st.latest_period))

    # where the latest value sits in the history
    if st.n >= 8:
        if st.record:
            word = tr("highest") if st.record == "high" else tr("lowest")
            facts.append(Fact("extreme", "change", subject,
                              tr("{lead}The latest value is the {word} of all {n} observations, going back to {first}.",
                                 lead=lead, word=word, n=num(st.n), first=human_period(st.first)),
                              0.85 * w, {"record": st.record, "n": st.n}, series_id, st.latest_period))
        elif st.lowest_since or st.highest_since:
            if st.lowest_since and (not st.highest_since or st.lowest_since <= st.highest_since):
                since = tr("the lowest since {period}", period=human_period(st.lowest_since))
            else:
                since = tr("the highest since {period}", period=human_period(st.highest_since))
            facts.append(Fact("extreme", "change", subject, tr("{lead}The latest value is {since}.", lead=lead, since=since), 0.75 * w,
                              {"lowest_since": st.lowest_since, "highest_since": st.highest_since}, series_id, st.latest_period))

    # the trend
    trend, recent = st.trend, st.recent_trend
    first, last = human_period(st.first), human_period(st.last)
    if trend and trend.direction != "flat" and st.n >= 8:
        risen = fmt_risen(trend.direction == "rising")
        if trend.log and trend.annualised is not None and lag:
            text = tr("{lead}From {first} to {last} the series has {risen} by about {amount} a year.", lead=lead, first=first,
                      last=last, risen=risen, amount=fmt_pct(abs(trend.annualised)))
            if st.cagr is not None:
                text += " " + tr("The compound annual rate is {rate}.", rate=fmt_pct(st.cagr))
        elif lag:
            amount = fmt_pp(abs(trend.slope * lag), 2) if ctx.pp else ctx.val(abs(trend.slope * lag), 2)
            text = tr("{lead}From {first} to {last} the series has {risen} by about {amount} a year.", lead=lead, first=first,
                      last=last, risen=risen, amount=amount)
        else:
            text = tr("{lead}Over the whole series the trend is {way}.", lead=lead, way=tr(_RISING[trend.direction]))
        if recent and recent.direction not in ("flat", trend.direction):
            text += " " + tr("Over the last {n} observations, though, it has {risen}.", n=num(recent.n), risen=fmt_risen(recent.direction == "rising"))
        facts.append(Fact("trend", "pattern", subject, text, 0.7 * w,
                          {"direction": trend.direction, "annualised": trend.annualised, "slope": trend.slope, "r2": trend.r2,
                           "recent_direction": recent.direction if recent else None}, series_id))
    elif trend and trend.direction == "flat" and st.n >= 12 and headline:
        facts.append(Fact("trend", "pattern", subject,
                          tr("{lead}There is no clear long-term trend between {first} and {last}.", lead=lead, first=first, last=last),
                          0.45, {"direction": "flat"}, series_id))

    # seasonality
    sea = st.seasonality
    if sea and sea.strength >= 0.4 and headline:
        peak, trough = _season_name(sea.lag, sea.peak), _season_name(sea.lag, sea.trough)
        if sea.multiplicative:
            gap = tr("{value} of the usual level", value=fmt_pct(sea.amplitude, 0))
        else:
            gap = fmt_pp(sea.amplitude, 1) if ctx.pp else ctx.val(sea.amplitude)
        facts.append(Fact("seasonality", "pattern", subject,
                          tr("{lead}The numbers follow a seasonal pattern: {peak} is usually the highest and {trough} the lowest, "
                             "a gap of about {gap}.", lead=lead, peak=peak, trough=trough, gap=gap), 0.65,
                          {"strength": sea.strength, "peak": peak, "trough": trough, "amplitude": sea.amplitude}, series_id))

    # unusual periods
    for o in st.outliers[:2] if headline else st.outliers[:1]:
        basis = tr("a year earlier") if (sea and sea.strength >= 0.3) else tr("the previous period")
        change = fmt_pct(o.change, 1, signed=True) if ctx.kind in ("level", "index") else fmt_pp(o.change, 1, signed=True)
        facts.append(Fact("anomaly", "pattern", subject,
                          tr("{lead}{period} stands out: the change on {basis} was {change}, unusually large for this series{events}.",
                             lead=lead, period=human_period(o.period), basis=basis, change=change, events=_events(o.period)),
                          0.6 * w, {"period": o.period, "change": o.change, "z": o.z}, series_id, o.period))

    # a lasting change in level or growth
    sh = st.shift
    if sh and headline:
        if sh.on_changes:
            what, before, after = tr("typical change from one period to the next"), fmt_pct(sh.before), fmt_pct(sh.after)
        else:
            what, before, after = tr("average level"), ctx.val(sh.before), ctx.val(sh.after)
        facts.append(Fact("shift", "pattern", subject,
                          tr("{lead}Around {period} the pattern changed: the {what} went from {before} to {after}{events}.",
                             lead=lead, period=human_period(sh.period), what=what, before=before, after=after, events=_events(sh.period)),
                          0.6, {"period": sh.period, "before": sh.before, "after": sh.after, "t": sh.t_stat}, series_id, sh.period))
    return facts


def when(period: str) -> str:
    """", December 2025", or nothing for a table that has no periods."""
    return f", {human_period(period)}" if period else ""


def versus_men(same: bool, above: bool, amount: str) -> str:
    """How the value for women compares with the value for men, as a phrase."""
    if same:
        return tr("about the same as the value for men")
    if above:
        return tr("{amount} above the value for men", amount=amount)
    return tr("{amount} below the value for men", amount=amount)


def _named(names_values: list[tuple[str, str]]) -> str:
    return join_list([f"{display(str(n))} ({v})" for n, v in names_values])


def movers_fact(label: str, changes: pd.Series, ctx: Ctx, period: str, basis: str, from_period: str | None = None,
                *, k: int = 3) -> Fact | None:
    """The biggest risers and fallers among series that can be compared, such as inflation by product group."""
    ch = changes.dropna()
    if len(ch) < 4:
        return None
    eps = EPS_PP if ctx.pp else 0.05
    up = ch[ch > eps].sort_values(ascending=False).head(k)
    down = ch[ch < -eps].sort_values().head(k)
    if up.empty and down.empty:
        return None
    show = (lambda v: fmt_pp(v, 1, signed=True)) if ctx.pp else (lambda v: fmt_pct(v, 1, signed=True))
    since = human_period(from_period) if from_period else tr(basis)
    text = tr("{label}, {period} compared with {since}.", label=label, period=human_period(period), since=since)
    if not up.empty:
        text += " " + tr("Biggest increases: {items}.", items=_named([(n, show(v)) for n, v in up.items()]))
    if not down.empty:
        text += " " + tr("Biggest decreases: {items}.", items=_named([(n, show(v)) for n, v in down.items()]))
    return Fact("movers", "comparison", label, text, 0.8,
                {"up": up.to_dict(), "down": down.to_dict(), "basis": basis, "period": period}, None, period)


def ranking_fact(label: str, values: pd.Series, ctx: Ctx, period: str, dim_role: str) -> Fact | None:
    sp = cs.spread(values)
    if sp is None:
        return None
    top = _named([(n, ctx.val(v)) for n, v in sp.top[:2]])
    bottom = _named([(n, ctx.val(v)) for n, v in sp.bottom[:2]])
    text = tr("{label} {by}{when}: highest in {top}, lowest in {bottom}.", label=label, by=by_role(dim_role), when=when(period),
              top=top, bottom=bottom)
    if sp.ratio and sp.ratio >= 1.5 and not ctx.pp:
        text += " " + tr("The highest is {ratio} times the lowest.", ratio=plain(sp.ratio, 1))
    return Fact("ranking", "comparison", label, text, 0.75,
                {"top": sp.top, "bottom": sp.bottom, "ratio": sp.ratio, "cv": sp.cv, "n": sp.n, "period": period})


def composition_fact(label: str, values: pd.Series, period: str, dim_role: str) -> Fact | None:
    comp = cs.composition(values)
    if comp is None or comp.n < 3:
        return None
    top = comp.shares.head(3)
    names = join_list([f"{display(str(n))} ({fmt_pct(s * 100, 0)})" for n, s in top.items()])
    return Fact("composition", "composition", label,
                tr("{label} {by}{when}: the biggest shares are {names}. The top three add up to {share} of the total, so it is "
                   "{how}.", label=label, by=by_role(dim_role), when=when(period), names=names,
                   share=fmt_pct(top.sum() * 100, 0), how=tr(comp.concentration)),
                0.7, {"shares": comp.shares.head(8).to_dict(), "hhi": comp.hhi, "n": comp.n, "period": period})


def gap_fact(label: str, pair: list[cs.Gap], ctx: Ctx, period: str, dim_role: str) -> Fact | None:
    """Women's values against men's across the categories of one dimension."""
    if len(pair) < 2:
        return None
    higher = sum(1 for g in pair if g.abs_gap > 0)
    big = pair[0]
    avg = sum(g.abs_gap for g in pair) / len(pair)
    widest = tr("{category} (women {a}, men {b})", category=display(big.category), a=ctx.val(big.a), b=ctx.val(big.b))
    if ctx.pp:
        same, above, amount = abs(avg) < EPS_PP, avg > 0, fmt_pp(abs(avg))
    else:
        ratios = [g.ratio for g in pair if g.ratio]
        mean_ratio = sum(ratios) / len(ratios) if ratios else math.nan
        same, above = not ratios or abs(mean_ratio - 1) < 0.005, mean_ratio > 1
        amount = "" if same else fmt_pct(abs(mean_ratio - 1) * 100, 0)
    relation = versus_men(same, above, amount)
    return Fact("gap", "comparison", label,
                tr("{label}{when}: across {n} categories {by}, the value for women is {relation} on average, and higher in "
                   "{higher} of them. The widest gap is in {widest}.", label=label, when=when(period), n=num(len(pair)),
                   by=by_role(dim_role), relation=relation, higher=num(higher), widest=widest),
                0.72, {"avg_gap": avg, "n": len(pair), "higher_for_women": higher, "widest": big.category, "period": period})


def growth_fact(label: str, growth: pd.Series, first: str, last: str, dim_role: str, *, k: int = 2) -> Fact | None:
    g = growth.dropna()
    if len(g) < 4:
        return None
    srt = g.sort_values(ascending=False)
    fast = _named([(n, fmt_pct(v, 1, signed=True)) for n, v in srt.head(k).items()])
    slow = _named([(n, fmt_pct(v, 1, signed=True)) for n, v in srt.tail(k).iloc[::-1].items()])
    return Fact("growth", "comparison", label,
                tr("{label} {by}, {first} to {last}: grew fastest in {fast} and slowest in {slow}.", label=label,
                   by=by_role(dim_role), first=human_period(first), last=human_period(last), fast=fast, slow=slow),
                0.7, {"fastest": srt.head(k).to_dict(), "slowest": srt.tail(k).to_dict()})
