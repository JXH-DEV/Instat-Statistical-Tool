"""Comparisons across categories at one point in time: composition, ranking, gaps."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..i18n import N_


@dataclass
class Composition:
    shares: pd.Series  # category -> share of the total (0..1), sorted descending
    total: float
    hhi: float  # Herfindahl-Hirschman index, 0..10000
    n: int

    @property
    def concentration(self) -> str:
        if self.n < 3:
            return N_("n/a")
        equal = 10000 / self.n
        if self.hhi >= max(2500, 2.2 * equal):
            return N_("highly concentrated")
        if self.hhi >= max(1500, 1.4 * equal):
            return N_("moderately concentrated")
        return N_("evenly spread")


def composition(values: pd.Series) -> Composition | None:
    """Shares of non-negative categories. ``values`` must exclude any total row."""
    v = values.dropna()
    v = v[v > 0]
    if len(v) < 2 or v.sum() <= 0:
        return None
    total = float(v.sum())
    shares = (v / total).sort_values(ascending=False)
    hhi = float(((shares * 100) ** 2).sum())
    return Composition(shares, total, hhi, len(shares))


@dataclass
class Spread:
    top: list[tuple[str, float]]
    bottom: list[tuple[str, float]]
    ratio: float | None  # max / min when both positive
    cv: float | None  # coefficient of variation
    mean: float
    median: float
    n: int


def spread(values: pd.Series, k: int = 3) -> Spread | None:
    v = values.dropna()
    if len(v) < 3:
        return None
    srt = v.sort_values(ascending=False)
    mean = float(v.mean())
    cv = float(v.std(ddof=1) / abs(mean)) if mean else None
    ratio = float(srt.iloc[0] / srt.iloc[-1]) if srt.iloc[-1] > 0 and srt.iloc[0] > 0 else None
    return Spread(list(srt.head(k).items()), list(srt.tail(k).iloc[::-1].items()), ratio, cv, mean, float(v.median()), len(v))


@dataclass
class Gap:
    category: str
    a: float
    b: float
    abs_gap: float  # a - b
    ratio: float | None  # a / b


def gaps(a: pd.Series, b: pd.Series) -> list[Gap]:
    """Pairwise differences ``a - b`` per category (for example women minus men), largest absolute gap first."""
    idx = a.index.intersection(b.index)
    out = []
    for c in idx:
        x, y = a[c], b[c]
        if pd.isna(x) or pd.isna(y):
            continue
        out.append(Gap(str(c), float(x), float(y), float(x - y), float(x / y) if y else None))
    return sorted(out, key=lambda g: -abs(g.abs_gap))


def growth_between(first: pd.Series, last: pd.Series) -> pd.Series:
    """Percent change per category between two snapshots; categories with a zero or missing base are dropped."""
    idx = first.index.intersection(last.index)
    base, now = first[idx], last[idx]
    out = (now / base - 1) * 100
    return out.replace([np.inf, -np.inf], np.nan).dropna()
