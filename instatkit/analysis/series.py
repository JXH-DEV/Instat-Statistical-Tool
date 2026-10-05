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


@dataclass
class Seasonality:
    strength: float  # 0..1 (Hyndman's F_s)
    peak: int  # season index (0-based month / quarter)
    trough: int
    amplitude: float  # peak-to-trough, % of level for multiplicative, absolute for additive
    lag: int
    multiplicative: bool


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


def linear_trend(y: np.ndarray, *, log: bool, lag: int | None = None) -> Trend | None:
    """OLS trend on ``y`` (log-linear when ``log``); direction uses a t-test on the slope."""
    y = np.asarray(y, dtype=float)
    n = len(y)
    if n < 4:
        return None
    if log and (y <= 0).any():
        log = False
    yy = np.log(y) if log else y
    t = np.arange(n, dtype=float)
    tm = t.mean()
    sxx = ((t - tm) ** 2).sum()
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


def seasonality(y: np.ndarray, season: np.ndarray, lag: int) -> Seasonality | None:
    """Classical decomposition strength on a *regular* series (``season`` is the 0-based position in the cycle)."""
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
    amp = (idx.max() - idx.min()) * 100 if mult else idx.max() - idx.min()
    return Seasonality(float(strength), int(idx.argmax()), int(idx.argmin()), float(amp), lag, mult)


def robust_outliers(x: np.ndarray, *, threshold: float = 3.5) -> list[tuple[int, float]]:
    """Indices and modified z-scores (median / MAD) of unusual values in ``x``."""
    x = np.asarray(x, dtype=float)
    ok = ~np.isnan(x)
    if ok.sum() < 10:
        return []
    med = np.nanmedian(x)
    mad = np.nanmedian(np.abs(x[ok] - med))
    if mad == 0:
        mad = 1.253314 * np.nanmean(np.abs(x[ok] - med))  # fall back to mean absolute deviation
        if mad == 0:
            return []
        z = (x - med) / mad
    else:
        z = 0.6745 * (x - med) / mad
    out = [(i, float(z[i])) for i in range(len(x)) if ok[i] and abs(z[i]) >= threshold]
    return sorted(out, key=lambda t: -abs(t[1]))


def best_mean_shift(x: np.ndarray, *, min_seg: int = 4, min_t: float = 4.0, min_effect: float = 0.75):
    """Best single split of ``x`` into two regimes. Returns ``(index, mean_before, mean_after, t)`` or ``None``."""
    x = np.asarray(x, dtype=float)
    n = len(x)
    if n < 2 * min_seg + 2 or np.isnan(x).any():
        return None
    best = None
    csum = np.cumsum(x)
    csq = np.cumsum(x ** 2)
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
    sd = float(np.std(x, ddof=1))
    if abs(best[3]) < min_t or (sd > 0 and abs(best[2] - best[1]) < min_effect * sd):
        return None
    return best


def _season_index(p: Period, lag: int) -> int:
    if lag == 12:
        return p.start.month - 1
    if lag == 4:
        return (p.start.month - 1) // 3
    if lag == 2:
        return 0 if p.start.month <= 6 else 1
    return 0


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
    by_label = {p.label: v for p, v in zip(periods, v_all) if not np.isnan(v)}

    idx = np.flatnonzero(ok)
    v = v_all[idx]
    last_i = idx[-1]
    n = len(v)
    st = SeriesStats(n=n, first=labels[idx[0]], last=labels[last_i], latest=float(v[-1]), latest_period=labels[last_i],
                     freq=freq)

    # change vs the previous observation
    st.prev, st.prev_period = float(v[-2]), labels[idx[-2]]
    st.change_abs = st.latest - st.prev
    st.change_pct = (st.change_abs / abs(st.prev) * 100) if st.prev not in (0, 0.0) else None

    # change vs the same period a year earlier
    if lag and freq in FREQ_LAG:
        try:
            ylab = add_periods(periods[last_i], -lag).label
        except ValueError:
            ylab = None
        if ylab in by_label:
            st.yoy, st.yoy_period = by_label[ylab], ylab
            st.yoy_abs = st.latest - st.yoy
            st.yoy_pct = (st.yoy_abs / abs(st.yoy) * 100) if st.yoy != 0 else None

    # extremes and context
    st.min_value = float(v.min())
    if n >= 8:
        if v[-1] >= v.max():
            st.record = "high"
        elif v[-1] <= v.min():
            st.record = "low"
        earlier_ge = np.flatnonzero(v[:-1] >= v[-1])
        earlier_le = np.flatnonzero(v[:-1] <= v[-1])
        if len(earlier_ge) and st.record != "high":
            st.highest_since = labels[idx[earlier_ge[-1]]] if (n - 1 - earlier_ge[-1]) >= 4 else None
        if len(earlier_le) and st.record != "low":
            st.lowest_since = labels[idx[earlier_le[-1]]] if (n - 1 - earlier_le[-1]) >= 4 else None

    # trend
    log = kind in ("level", "index")
    st.trend = linear_trend(v, log=log, lag=lag or None)
    w = {12: 12, 4: 6, 2: 4, 1: 5}.get(lag, 8)
    if n >= max(w, 6) + 4:
        st.recent_trend = linear_trend(v[-w:], log=log, lag=lag or None)

    # period-on-period changes: percent for levels and indices, plain differences otherwise
    changes = np.diff(v) / v[:-1] * 100 if log and (v > 0).all() else np.diff(v)

    # calendar regularity: how many periods are missing inside the span
    if lag:
        span = 0
        cur = periods[idx[0]]
        end = periods[last_i]
        guard = 0
        while cur.sort_key < end.sort_key and guard < 10000:
            cur = add_periods(cur, 1)
            span += 1
            guard += 1
        st.missing = max(0, span + 1 - n)

    # seasonality needs a gap-free series
    if lag in (12, 4, 2) and st.missing == 0 and n >= 3 * lag:
        season = np.array([_season_index(periods[i], lag) for i in idx])
        st.seasonality = seasonality(v, season, lag)

    # unusual changes: year-on-year when the series is clearly seasonal, else period-on-period
    if st.seasonality and st.seasonality.strength >= 0.3 and n > lag + 10 and st.missing == 0:
        base = v[lag:] / v[:-lag] * 100 - 100 if (log and (v > 0).all()) else v[lag:] - v[:-lag]
        offs = lag
    else:
        base, offs = changes, 1
    for i, z in robust_outliers(base)[:3]:
        pi = idx[i + offs]
        st.outliers.append(Outlier(labels[pi], float(v_all[pi]), float(base[i]), z))

    # level shift
    if n >= 16:
        series_for_shift = v if not log else changes
        res = best_mean_shift(series_for_shift, min_seg=max(4, len(series_for_shift) // 6))
        if res:
            k, m1, m2, t = res
            pi = idx[k + (1 if series_for_shift is changes else 0)]
            st.shift = Shift(labels[pi], m1, m2, t, series_for_shift is changes)

    # compound annual growth
    if log and v[0] > 0 and v[-1] > 0:
        years = (periods[last_i].start - periods[idx[0]].start).days / 365.25
        if years >= 2:
            st.cagr = ((v[-1] / v[0]) ** (1 / years) - 1) * 100
    return st
