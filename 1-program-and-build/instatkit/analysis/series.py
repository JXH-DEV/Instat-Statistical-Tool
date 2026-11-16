"""Time-series statistics with numpy only (no scipy/statsmodels).

Every function works on plain arrays so it is easy to unit test against series with known properties.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from ..semantics.periods import FREQ_LAG, Period, add_periods


@dataclass
class Trend:
    slope: float  # per period, in the fitted scale
    annualised: float | None  # % per year
    r2: float
    t_stat: float
    direction: str  # rising | falling | flat
    log: bool
    n: int


# A seasonal pattern must predict the cycles it was not made from: with three years of noise, the twelve monthly averages "explain" about
# half of the variation by chance alone, so the strength measured on the same data cannot tell a season from noise. Four seasons of three or
# four years give a pattern even less to stand on, hence the higher bar (on made-up noise, 2 % of monthly and 3-7 % of quarterly series pass).
MIN_HELD_OUT = 0.15
MIN_HELD_OUT_SHORT = 0.3  # for quarters and half-years


@dataclass
class Seasonality:
    strength: float  # 0..1 (Hyndman's F_s)
    peak: int  # season index (0-based month / quarter)
    trough: int
    amplitude: float  # peak-to-trough, % of level for multiplicative, absolute for additive
    lag: int
    multiplicative: bool
    held_out: float = 1.0  # share of the variation that the seasonal index of the other cycles predicts in each cycle (1 = all of it)


@dataclass
class Outlier:
    period: str
    value: float
    change: float
    z: float


@dataclass
class Shift:
    period: str  # first period of the new regime
    before: float
    after: float
    t_stat: float
    on_changes: bool
    at: int = 0  # position in the series (of changes when ``on_changes``) where the new regime starts


@dataclass
class SeriesStats:
    n: int
    first: str
    last: str
    latest: float
    latest_period: str
    prev: float | None = None
    prev_period: str | None = None
    change_abs: float | None = None
    change_pct: float | None = None
    yoy: float | None = None
    yoy_period: str | None = None
    yoy_abs: float | None = None
    yoy_pct: float | None = None
    min_value: float = math.nan
    record: str | None = None  # 'high' | 'low' when the latest value is the extreme of the whole history
    highest_since: str | None = None
    lowest_since: str | None = None
    trend: Trend | None = None
    recent_trend: Trend | None = None
    seasonality: Seasonality | None = None
    outliers: list[Outlier] = field(default_factory=list)
    shift: Shift | None = None
    missing: int = 0
    cagr: float | None = None
    freq: str | None = None
    pct_changes: bool = False  # outlier and shift sizes are percent changes (False: plain differences, for series that reach zero or go negative)


def linear_trend(y: np.ndarray, *, log: bool, lag: int | None = None, t: np.ndarray | None = None) -> Trend | None:
    """OLS trend on ``y`` (log-linear when ``log``); direction uses a t-test on the slope.

    ``t`` is the position of each value in time (in periods). Without it the values are taken to be consecutive, which
    is wrong for a series with gaps: its slope would be per observation instead of per period."""
    y = np.asarray(y, dtype=float)
    n = len(y)
    if n < 4:
        return None
    if log and (y <= 0).any():
        log = False
    yy = np.log(y) if log else y
    t = np.arange(n, dtype=float) if t is None else np.asarray(t, dtype=float)
    tm = t.mean()
    sxx = ((t - tm) ** 2).sum()
    if sxx == 0:
        return None
    b = ((t - tm) * (yy - yy.mean())).sum() / sxx
    a = yy.mean() - b * tm
    resid = yy - (a + b * t)
    ss_res = float((resid ** 2).sum())
    ss_tot = float(((yy - yy.mean()) ** 2).sum())
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
    s2 = ss_res / (n - 2)
    se = math.sqrt(s2 / sxx) if s2 > 0 else 0.0
    tstat = b / se if se > 0 else (math.inf if b != 0 else 0.0)
    annual = ((math.exp(b) ** lag) - 1) * 100 if (log and lag) else None
    direction = "flat" if abs(tstat) < 2 else ("rising" if b > 0 else "falling")
    return Trend(float(b), annual, r2, float(tstat), direction, log, n)


def _centered_ma(y: np.ndarray, lag: int) -> np.ndarray:
    w = np.r_[0.5, np.ones(lag - 1), 0.5] / lag if lag % 2 == 0 else np.ones(lag) / lag
    out = np.full(len(y), np.nan)
    half = len(w) // 2
    if len(y) >= len(w):
        out[half: len(y) - half] = np.convolve(y, w, mode="valid")
    return out


def _held_out_strength(detr: np.ndarray, ok: np.ndarray, season: np.ndarray, lag: int) -> float:
    """Leave one cycle out: how much of its variation around the flat line does the seasonal index of the other cycles explain?
    1 is all of it, 0 or less is no better than assuming there are no seasons."""
    cycles = np.arange(len(detr)) // lag
    flat = float(np.nanmean(detr[ok]))
    sse = sst = 0.0
    for c in np.unique(cycles):
        held, rest = (cycles == c) & ok, (cycles != c) & ok
        index = np.array([detr[rest & (season == s)].mean() if (rest & (season == s)).any() else np.nan for s in range(lag)])
        predicted = index[season[held]]
        known = ~np.isnan(predicted)
        sse += float(((detr[held][known] - predicted[known]) ** 2).sum())
        sst += float(((detr[held][known] - flat) ** 2).sum())
    return 1 - sse / sst if sst > 0 else 0.0


def seasonality(y: np.ndarray, season: np.ndarray, lag: int) -> Seasonality | None:
    """Classical decomposition strength on a *regular* series (``season`` is the 0-based position in the cycle). ``None`` when the
    seasonal index does not predict the cycles it was not made from."""
    y = np.asarray(y, dtype=float)
    if lag < 2 or len(y) < 3 * lag or np.isnan(y).any():
        return None
    mult = bool((y > 0).all())
    ma = _centered_ma(y, lag)
    detr = y / ma if mult else y - ma
    ok = ~np.isnan(detr)
    if ok.sum() < 2 * lag:
        return None
    idx = np.array([np.nanmean(detr[(season == s) & ok]) for s in range(lag)])
    if np.isnan(idx).any():
        return None
    idx = idx / idx.mean() if mult else idx - idx.mean()
    resid = detr - idx[season]
    var_d, var_r = np.nanvar(detr[ok]), np.nanvar(resid[ok])
    if var_d <= 0:
        return None
    strength = max(0.0, 1 - var_r / var_d)
    held_out = _held_out_strength(detr, ok, season, lag)
    if held_out < (MIN_HELD_OUT if lag >= 12 else MIN_HELD_OUT_SHORT):
        return None
    amp = (idx.max() - idx.min()) * 100 if mult else idx.max() - idx.min()
    return Seasonality(float(strength), int(idx.argmax()), int(idx.argmin()), float(amp), lag, mult, float(held_out))


def robust_outliers(x: np.ndarray, *, threshold: float = 3.5) -> list[tuple[int, float]]:
    """Indices and modified z-scores (median / MAD) of unusual values in ``x``."""
    x = np.asarray(x, dtype=float)
    ok = ~np.isnan(x)
    if ok.sum() < 10:
        return []
    med = np.nanmedian(x)
    tiny = 1e-9 * float(np.nanmax(np.abs(x[ok])))  # a series that rises by 0.1 a month differs by 1e-16 from month to month: that is not variation
    mad = np.nanmedian(np.abs(x[ok] - med))
    if mad <= tiny:
        mad = 1.253314 * np.nanmean(np.abs(x[ok] - med))  # fall back to mean absolute deviation
        if mad <= tiny:
            return []
        z = (x - med) / mad
    else:
        z = 0.6745 * (x - med) / mad
    out = [(i, float(z[i])) for i in range(len(x)) if ok[i] and abs(z[i]) >= threshold]
    return sorted(out, key=lambda t: -abs(t[1]))


def best_mean_shift(x: np.ndarray, *, min_seg: int = 4, min_t: float = 4.0, min_effect: float = 0.75):
    """Best single split of ``x`` into two regimes. Returns ``(index, mean_before, mean_after, t)`` or ``None``.

    The split is searched on ``x`` with its most extreme 5 % at each end pulled in, so that one wild value cannot hide a lasting
    change; the means returned are those of the values as they are."""
    x = np.asarray(x, dtype=float)
    n = len(x)
    if n < 2 * min_seg + 2 or np.isnan(x).any():
        return None
    low, high = np.percentile(x, [5, 95])
    xs = np.clip(x, low, high)
    best = None
    csum, csq = np.cumsum(xs), np.cumsum(xs ** 2)
    for k in range(min_seg, n - min_seg + 1):
        n1, n2 = k, n - k
        m1, m2 = csum[k - 1] / n1, (csum[-1] - csum[k - 1]) / n2
        v1 = (csq[k - 1] - n1 * m1 ** 2) / (n1 - 1)
        v2 = ((csq[-1] - csq[k - 1]) - n2 * m2 ** 2) / (n2 - 1)
        se = math.sqrt(max(v1, 0) / n1 + max(v2, 0) / n2)
        if se == 0:
            continue
        t = (m2 - m1) / se
        if best is None or abs(t) > abs(best[3]):
            best = (k, float(m1), float(m2), float(t))
    if best is None:
        return None
    k = best[0]
    before, after = float(x[:k].mean()), float(x[k:].mean())
    sd = float(np.std(x, ddof=1))
    if abs(best[3]) < min_t or (sd > 0 and abs(after - before) < min_effect * sd):
        return None
    return k, before, after, best[3]


def _season_index(p: Period, lag: int) -> int:
    if lag == 12:
        return p.start.month - 1
    if lag == 4:
        return (p.start.month - 1) // 3
    if lag == 2:
        return 0 if p.start.month <= 6 else 1
    return 0


def _ordinal(p: Period, lag: int) -> int:
    """Position of ``p`` on a calendar of ``lag`` periods a year: consecutive periods differ by one, a gap shows."""
    return p.start.year * lag + _season_index(p, lag)


def compute_series_stats(periods: list[Period], values: np.ndarray, *, kind: str = "level") -> SeriesStats | None:
    """Everything the narrator needs to know about one series. ``periods`` must be sorted and unique."""
    v_all = np.asarray(values, dtype=float)
    ok = ~np.isnan(v_all)
    if ok.sum() < 2:
        return None
    freqs = {p.freq for p in periods}
    freq = freqs.pop() if len(freqs) == 1 else None  # months next to a yearly total have no calendar to check
    lag = FREQ_LAG.get(freq or "", 0)
    labels = [p.label for p in periods]

    idx = np.flatnonzero(ok)  # positions of the observations that exist
    v = v_all[idx]
    last_i = idx[-1]
    n = len(v)
    st = SeriesStats(n=n, first=labels[idx[0]], last=labels[last_i], latest=float(v[-1]), latest_period=labels[last_i], freq=freq)

    _changes_on_earlier_periods(st, periods, v_all, v, idx, labels, lag)
    _extremes(st, v, idx, labels)
    log = kind in ("level", "index")
    _trends(st, periods, v, idx, lag, log)

    # period-on-period changes: percent for levels and indices, plain differences otherwise
    st.pct_changes = bool(log and (v > 0).all())
    changes = np.diff(v) / v[:-1] * 100 if st.pct_changes else np.diff(v)

    st.missing = _missing_periods(periods, idx, n) if lag else 0
    if lag in (12, 4, 2) and st.missing == 0 and n >= 3 * lag:  # seasonality needs a gap-free series
        season = np.array([_season_index(periods[i], lag) for i in idx])
        st.seasonality = seasonality(v, season, lag)

    if n >= 16:
        _level_shift(st, v, idx, labels, changes, log)
    _unusual_changes(st, v_all, v, idx, labels, lag, changes)
    if log and v[0] > 0 and v[-1] > 0:  # compound annual growth
        years = (periods[last_i].start - periods[idx[0]].start).days / 365.25
        if years >= 2:
            st.cagr = ((v[-1] / v[0]) ** (1 / years) - 1) * 100
    return st


def _changes_on_earlier_periods(st: SeriesStats, periods: list[Period], v_all: np.ndarray, v: np.ndarray, idx: np.ndarray,
                                labels: list[str], lag: int) -> None:
    """The change on the previous observation, and on the same period a year earlier."""
    st.prev, st.prev_period = float(v[-2]), labels[idx[-2]]
    st.change_abs = st.latest - st.prev
    st.change_pct = (st.change_abs / abs(st.prev) * 100) if st.prev not in (0, 0.0) else None
    if lag and st.freq in FREQ_LAG:
        by_label = {p.label: x for p, x in zip(periods, v_all) if not np.isnan(x)}
        try:
            ylab = add_periods(periods[idx[-1]], -lag).label
        except ValueError:
            ylab = None
        if ylab in by_label:
            st.yoy, st.yoy_period = by_label[ylab], ylab
            st.yoy_abs = st.latest - st.yoy
            st.yoy_pct = (st.yoy_abs / abs(st.yoy) * 100) if st.yoy != 0 else None


def _extremes(st: SeriesStats, v: np.ndarray, idx: np.ndarray, labels: list[str]) -> None:
    """Where the latest value sits in the history: a record, or the highest or lowest since some time ago."""
    n = len(v)
    st.min_value = float(v.min())
    if n < 8:
        return
    # a record beats everything before it; a flat series, or a tie with the old maximum, has no record
    if v[-1] > v[:-1].max():
        st.record = "high"
    elif v[-1] < v[:-1].min():
        st.record = "low"
    earlier_ge = np.flatnonzero(v[:-1] >= v[-1])
    earlier_le = np.flatnonzero(v[:-1] <= v[-1])
    if len(earlier_ge) and st.record != "high":
        st.highest_since = labels[idx[earlier_ge[-1]]] if (n - 1 - earlier_ge[-1]) >= 4 else None
    if len(earlier_le) and st.record != "low":
        st.lowest_since = labels[idx[earlier_le[-1]]] if (n - 1 - earlier_le[-1]) >= 4 else None


def _trends(st: SeriesStats, periods: list[Period], v: np.ndarray, idx: np.ndarray, lag: int, log: bool) -> None:
    """The trend over the whole series and over its most recent stretch (positions in time, so a gap does not tilt the line)."""
    t = np.array([_ordinal(periods[i], lag) for i in idx], dtype=float) if lag else None
    st.trend = linear_trend(v, log=log, lag=lag or None, t=t)
    w = {12: 12, 4: 6, 2: 4, 1: 5}.get(lag, 8)
    if len(v) >= max(w, 6) + 4:
        st.recent_trend = linear_trend(v[-w:], log=log, lag=lag or None, t=None if t is None else t[-w:])


def _missing_periods(periods: list[Period], idx: np.ndarray, n: int) -> int:
    """How many periods are missing inside the span of a calendar series."""
    span = 0
    cur, end = periods[idx[0]], periods[idx[-1]]
    guard = 0
    while cur.sort_key < end.sort_key and guard < 10000:
        cur = add_periods(cur, 1)
        span += 1
        guard += 1
    return max(0, span + 1 - n)


def _unusual_changes(st: SeriesStats, v_all: np.ndarray, v: np.ndarray, idx: np.ndarray, labels: list[str], lag: int,
                     changes: np.ndarray) -> None:
    """Unusually large changes: year-on-year when the series is clearly seasonal, else period-on-period."""
    if st.seasonality and st.seasonality.strength >= 0.3 and len(v) > lag + 10 and st.missing == 0:
        base = v[lag:] / v[:-lag] * 100 - 100 if st.pct_changes else v[lag:] - v[:-lag]
        offs = lag
    else:
        base, offs = changes, 1
    # a lasting change of regime is reported as such: its first months are unusual only compared with the regime before, not with their own
    cuts = [0, st.shift.at, len(base)] if (offs == 1 and st.shift and st.shift.on_changes) else [0, len(base)]
    found = [(i + a, z) for a, b in zip(cuts, cuts[1:], strict=False) for i, z in robust_outliers(base[a:b])]
    for i, z in sorted(found, key=lambda t: -abs(t[1]))[:3]:
        pi = idx[i + offs]
        st.outliers.append(Outlier(labels[pi], float(v_all[pi]), float(base[i]), z))


def _fits_better_than_a_line(x: np.ndarray, k: int) -> bool:
    """A steady rise also splits into a low half and a high half. A jump at ``k`` is only reported when two levels describe the
    values at least twice as well (by the sum of squared errors) as a straight line does. The most extreme 5 % at each end are pulled in,
    as in :func:`best_mean_shift`: a single wild value would be most of both errors."""
    x = np.clip(x, *np.percentile(x, [5, 95]))
    t = np.arange(len(x), dtype=float)
    two_levels = np.where(t < k, x[:k].mean(), x[k:].mean())
    slope, intercept = np.polyfit(t, x, 1)
    return float(((x - two_levels) ** 2).sum()) < 0.5 * float(((x - (slope * t + intercept)) ** 2).sum())


def _level_shift(st: SeriesStats, v: np.ndarray, idx: np.ndarray, labels: list[str], changes: np.ndarray, log: bool) -> None:
    """A lasting change in the level (or, for levels and indices, in the typical period-on-period change)."""
    if st.seasonality and st.seasonality.strength >= 0.3:  # the swings of the seasons would be reported as a change of pattern
        return
    on_changes = log
    series = changes if on_changes else v
    res = best_mean_shift(series, min_seg=max(4, len(series) // 6))
    if res and _fits_better_than_a_line(series, res[0]):
        k, mean_before, mean_after, t_stat = res
        pi = idx[k + (1 if on_changes else 0)]
        st.shift = Shift(labels[pi], mean_before, mean_after, t_stat, on_changes, k)
