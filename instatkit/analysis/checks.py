"""Consistency checks on a table.

They tell the reader how far to trust the numbers, and they catch reading mistakes: if the male and female columns no longer
add up to the total, something was probably misread.
"""

from __future__ import annotations

import re

import pandas as pd

from ..excel.tidy import TidyTable
from ..i18n import N_, mark, num, tn, tr
from ..semantics.glossary import display
from ..semantics.interpret import DatasetProfile
from ..semantics.labels import by_role
from .facts import Check
from .fmt import fmt_pct, human_period, join_list

# why a cell has no value, by the marker the file used (see semantics/numbers.py)
_WHY = {
    "na": N_("not available"), "nil": N_("shown as a dash"), "suppressed": N_("withheld"), "note": N_("marked with a note"),
    "text": N_("text instead of a number"),
}


def run_checks(table: TidyTable, profile: DatasetProfile) -> list[Check]:
    df = table.df
    out: list[Check] = []
    if df.empty:
        return [Check("data present", "fail", tr("No numbers could be read from this table."), name=tr("Data found"))]
    out.append(_completeness(df))
    out.extend(_continuity(profile))
    out.append(_duplicates(df))
    out.extend(_ranges(df, profile))
    out.extend(_parts_sum_to_total(df, table, profile))
    out.extend(_shares(df, table, profile))
    out.extend(_provisional(profile))
    out.append(_parse_quality(table, profile))
    return [c for c in out if c is not None]


def _completeness(df: pd.DataFrame) -> Check:
    name = tr("Completeness")
    n, miss = len(df), int(df["value"].isna().sum())
    share = miss / n if n else 0.0
    if miss == 0:
        return Check("completeness", "pass", tr("All {n} cells have a value.", n=num(n)), name=name)
    by_series = df.groupby("series_id")["value"].apply(lambda s: s.isna().mean())
    heavy = int((by_series >= 0.5).sum())
    flags = df.loc[df["value"].isna(), "flag"].value_counts().to_dict()
    why = ", ".join(f"{tr(_WHY[k]) if k in _WHY else (k or tr('blank'))}: {num(v)}" for k, v in flags.items())
    status = "warn" if share > 0.2 else "info"
    detail = tr("{missing} of {n} cells ({share}) are missing ({why}).", missing=num(miss), n=num(n), share=fmt_pct(share * 100),
                why=why)
    if heavy:
        detail += " " + tn(heavy, "{n} series is at least half empty.", "{n} series are at least half empty.")
    return Check("completeness", status, detail, name=name)


def _continuity(profile: DatasetProfile) -> list[Check]:
    if profile.n_periods < 3 or not profile.freq:
        return []
    name = tr("Gaps between periods")
    if not profile.missing_periods:
        return [Check("period continuity", "pass", tr("No gaps between {first} and {last} ({frequency}).",
                                                      first=human_period(profile.first_period), last=human_period(profile.last_period),
                                                      frequency=tr(profile.freq_name)), name=name)]
    shown = [human_period(p) for p in profile.missing_periods[:5]]
    listed = ", ".join(shown) + ("…" if len(profile.missing_periods) > 5 else "")
    return [Check("period continuity", "warn",
                  tn(len(profile.missing_periods), "{n} period is missing in this range: {list}.",
                     "{n} periods are missing in this range: {list}.", list=listed), shown, name=name)]


def _duplicates(df: pd.DataFrame) -> Check | None:
    if (df["period"] == "").all():
        return None
    name = tr("Duplicates")
    n = int(df.duplicated(["series_id", "period"], keep=False).sum())
    if not n:
        return Check("duplicate observations", "pass", tr("Every series has at most one value per period."), name=name)
    return Check("duplicate observations", "fail",
                 tr("{n} values share the same series and period. The headers or row labels may have been misread.", n=num(n)),
                 name=name)


_SIGNED_OK = re.compile(r"(?i)balance|deficit|surplus|change|growth|variation|difference|net\b|ndryshim|rritj|bilanc")
_MAY_EXCEED_100 = re.compile(r"(?i)ratio|coverage|mbulim|index|indeks|growth|change|rritj|ndryshim")


def _ranges(df: pd.DataFrame, profile: DatasetProfile) -> list[Check]:
    """Percentages of a whole stay within 0 to 100, and counts and amounts are not negative (unless the measure is signed)."""
    flagged: list[str] = []
    n_bad = 0
    examined = 0
    for m in profile.measures:
        sub = df[df["measure"] == m.name].dropna(subset=["value"])
        if sub.empty:
            continue
        if m.unit_code == "%" and m.kind in ("rate", "share") and not _MAY_EXCEED_100.search(m.name):
            examined += 1
            bad = sub[(sub["value"] < 0) | (sub["value"] > 100)]
            if len(bad):
                n_bad += len(bad)
                flagged += [f"{r.src_ref}: {mark(f'{r.value:g}')}" for r in bad.head(3).itertuples()]
        elif m.additive and not _SIGNED_OK.search(m.name):
            examined += 1
            neg = sub[sub["value"] < 0]
            if 0 < len(neg) / len(sub) < 0.2:  # a few negatives in an otherwise non-negative measure
                n_bad += len(neg)
                flagged += [f"{r.src_ref}: {mark(f'{r.value:g}')}" for r in neg.head(3).itertuples()]
    if not examined:
        return []
    name = tr("Plausible values")
    if n_bad:
        return [Check("plausible range", "warn",
                      tn(n_bad, "{n} value looks implausible (a percentage outside 0-100, or an unexpected negative).",
                         "{n} values look implausible (percentages outside 0-100, or unexpected negatives)."), flagged[:4], name=name)]
    return [Check("plausible range", "pass", tr("Percentages lie between 0 and 100 and amounts are not negative."), name=name)]


def _parts_sum_to_total(df: pd.DataFrame, table: TidyTable, profile: DatasetProfile) -> list[Check]:
    """For additive measures: do the categories of a dimension add up to the dimension's own total row?"""
    if not any(m.additive for m in profile.measures):
        return []
    out: list[Check] = []
    dims = table.dim_columns
    for d in profile.dims:
        if not d.total_values or d.role in ("period_label", "month"):
            continue
        other = [c for c in dims if c != d.name] + ["measure", "period"]
        is_total = df[d.name].isin(d.total_values)
        parts = df[~is_total].groupby(other, dropna=False)["value"].agg(["sum", "count"])
        tot = df[is_total].groupby(other, dropna=False)["value"].first()
        j = parts.join(tot.rename("total"), how="inner")
        j = j[(j["count"] >= 2) & j["total"].notna() & (j["total"] != 0)]
        if j.empty:
            continue
        diff = (j["sum"] - j["total"]).abs()
        dev = diff / j["total"].abs()
        # rounding allowance: 0.5% of the total, and one unit when the published totals are whole numbers
        whole = (j["total"] % 1 == 0) & (j["sum"] % 1 == 0)
        allowance = 0.005 * j["total"].abs()
        tol = allowance.where(~whole, allowance.clip(lower=1.0))
        ok = diff <= tol
        key = f"parts add up: {d.role}"
        by = by_role(d.role)
        name = tr("Parts {by} add up to the total", by=by)
        nested = None if ok.all() else _nested_subtotals(df, d.name, other, j, ok, tol, is_total)
        if ok.all():
            out.append(Check(key, "pass", tr("In all {n} groups the parts {by} add up to the stated total (largest difference {dev}).",
                                             n=num(len(j)), by=by, dev=fmt_pct(dev.max() * 100, 2)), name=name))
        elif nested:
            names = join_list([f"'{display(n)}'" for n in nested])
            detail = (tr("The parts {by} add up to the stated total once the subtotal {names} is left out; it contains other rows of "
                         "the same table.", by=by, names=names) if len(nested) == 1 else
                      tr("The parts {by} add up to the stated total once the subtotals {names} are left out; they contain other rows "
                         "of the same table.", by=by, names=names))
            out.append(Check(key, "pass", detail, name=name))
        else:
            worst = dev[~ok].sort_values(ascending=False).head(3)
            examples = [tr("{where}: off by {pct}", where=", ".join(map(str, k)) if isinstance(k, tuple) else str(k),
                           pct=fmt_pct(v * 100)) for k, v in worst.items()]
            overlap = float((j["sum"] / j["total"]).median())
            hint = (tr("The categories may overlap (for example broad and narrow age bands).") if overlap > 1.05
                    else tr("Either a total or some of the categories may be wrong or missing."))
            n_bad = int((~ok).sum())
            out.append(Check(key, "fail" if n_bad > 0.2 * len(j) else "warn",
                             tr("{bad} of {n} groups are off from the stated total by more than rounding can explain.",
                                bad=num(n_bad), n=num(len(j))) + " " + hint, examples, name=name))
    return out


def _nested_subtotals(df: pd.DataFrame, dim: str, other: list[str], j: pd.DataFrame, ok: pd.Series, tol: pd.Series,
                      is_total: pd.Series) -> list[str] | None:
    """Categories that are themselves subtotals of other categories (``Other districts`` above the districts, a
    ``Population in private households`` row above its members) make a naive sum overshoot. If leaving one or two
    categories out makes the groups add up, say which."""
    cats = df[~is_total].groupby(other + [dim], dropna=False)["value"].first().unstack(dim)
    cats = cats.reindex(j.index)
    if cats.shape[1] > 60 or cats.shape[1] < 3:
        return None
    bad = ~ok
    excess = (j["sum"] - j["total"])[bad]
    t = tol[bad]
    values = cats[bad].fillna(0.0)
    for c in values.columns:
        if ((excess - values[c]).abs() <= t).mean() >= 0.9:
            return [str(c)]
    cols = list(values.columns)
    for a in range(len(cols)):
        for b in range(a + 1, len(cols)):
            if ((excess - values[cols[a]] - values[cols[b]]).abs() <= t).mean() >= 0.9:
                return [str(cols[a]), str(cols[b])]
    return None


def _shares(df: pd.DataFrame, table: TidyTable, profile: DatasetProfile) -> list[Check]:
    if not profile.measures or not all(m.kind == "share" for m in profile.measures):
        return []
    out: list[Check] = []
    for d in profile.dims:
        is_total = df[d.name].isin(d.total_values) if d.total_values else pd.Series(False, index=df.index)
        other = [c for c in table.dim_columns if c != d.name] + ["measure", "period"]
        s = df[~is_total].groupby(other, dropna=False)["value"].agg(["sum", "count"])
        s = s[s["count"] >= 3]
        if s.empty:
            continue
        near = ((s["sum"] - 100).abs() <= 1.0).mean()
        if near >= 0.5:
            out.append(Check("shares add up to 100%", "pass" if near >= 0.98 else "warn",
                             tr("In {share} of the groups {by} the shares add up to 100% (give or take 1).",
                                share=fmt_pct(near * 100, 0), by=by_role(d.role)), name=tr("Shares add up to 100%")))
            break
    return out


def _provisional(profile: DatasetProfile) -> list[Check]:
    if not profile.provisional_periods:
        return []
    periods = ", ".join(human_period(p) for p in profile.provisional_periods[:4])
    return [Check("provisional data", "info", tr("Figures for {periods} are provisional and may be revised.", periods=periods),
                  profile.provisional_periods[:4], name=tr("Provisional figures"))]


def _parse_quality(table: TidyTable, profile: DatasetProfile) -> Check:
    c = profile.confidence
    status = "pass" if c >= 0.85 else "warn" if c >= 0.6 else "fail"
    bits = list(table.spec.reasons) + list(table.warnings)
    detail = tr("The layout was recognised with {confidence} confidence.", confidence=fmt_pct(c * 100, 0))
    if bits:
        detail += " " + " ".join(b if b.endswith(".") else b + "." for b in bits[:4])
    return Check("layout detection", status, detail, bits[:4], name=tr("Layout recognition"))
