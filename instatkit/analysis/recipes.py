"""Extra findings for the statistics people ask about most: prices, labour, GDP, trade, population and wages.

A recipe only runs when the table is recognised. It adds facts (and sometimes checks) and never raises into the caller;
``apply_recipes`` catches whatever goes wrong inside one so the others still run.
"""

from __future__ import annotations

import re
from collections.abc import Callable

import pandas as pd

from ..excel.tidy import TidyTable
from ..i18n import num, tr
from ..semantics.glossary import age_label, display
from ..semantics.interpret import DatasetProfile
from ..semantics.labels import by_role
from ..semantics.periods import FREQ_LAG, add_periods, parse_period
from .facts import Check, Fact
from .fmt import fmt_pct, fmt_pp, fmt_value, human_period, join_list, risen


def apply_recipes(table: TidyTable, profile: DatasetProfile, analysis, facts: list[Fact]) -> None:
    for recipe in RECIPES:
        try:
            recipe(table, profile, analysis, facts)
        except Exception as exc:  # one broken recipe must not hide the others
            analysis.warnings.append(tr("The {recipe} analysis was skipped ({error}).", recipe=recipe.__name__.replace("_", " "),
                                        error=f"{type(exc).__name__}: {exc}"))


def _val(df: pd.DataFrame, period: str, **match) -> float | None:
    sel = df[df["period"] == period]
    for col, v in match.items():
        sel = sel[sel[col] == v]
    sel = sel["value"].dropna()
    return float(sel.iloc[0]) if len(sel) else None


def _prior(period: str, n: int) -> str | None:
    p = parse_period(period)
    if not p or p.freq not in FREQ_LAG:
        return None
    return add_periods(p, -n).label


def _find_measure(df: pd.DataFrame, *needles: str) -> str | None:
    for m in df["measure"].unique():
        if any(n in m.lower() for n in needles):
            return m
    return None


def _hold_others(df: pd.DataFrame, profile: DatasetProfile, keep: set[str]) -> pd.DataFrame:
    """Hold every dimension not in ``keep`` at its total (or most common value) so a slice is comparable."""
    sel = df
    by_name = {d.name: d for d in profile.dims}
    for d in profile.dims:
        aliased = d.alias_of in keep or any(o.alias_of == d.name and o.name in keep for o in by_name.values())
        if d.name in keep or aliased or sel.empty:
            continue
        present = set(sel[d.name])
        totals = [v for v in d.total_values if v in present]
        if "" in present and not totals:
            totals = [""]
        sel = sel[sel[d.name].isin(totals)] if totals else sel[sel[d.name] == sel[d.name].mode().iloc[0]]
    return sel


def _age_bounds(label: str) -> tuple[int, int | None] | None:
    t = label.strip().lower()
    m = re.match(r"^(\d{1,3})\s*[-–]\s*(\d{1,3})(?:\s*years?)?$", t)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.match(r"^(\d{1,3})\s*(?:\+|years? and over|years? and more|and over)$", t)
    if m:
        return int(m.group(1)), None
    m = re.match(r"^(?:under|below|up to)\s+(\d{1,3})(?:\s*years?)?$", t)
    if m:
        return 0, int(m.group(1)) - 1
    m = re.match(r"^(\d{1,3})(?:\s*years?)?$", t)
    if m:
        return int(m.group(1)), int(m.group(1))
    return None


def cpi_contributions(table, profile, analysis, facts) -> None:
    """How much each top-level COICOP group added to annual inflation (needs the index and the weights)."""
    df = table.df
    if "prices" not in profile.topics or profile.code_system != "COICOP" or "attr_weights" not in df.columns:
        return
    if not profile.measures or profile.measures[0].kind != "index" or not profile.last_period:
        return
    lag = FREQ_LAG.get(profile.freq or "", 0)
    prev = _prior(profile.last_period, lag) if lag else None
    prod = profile.dim("product")
    if not prev or prod is None:
        return
    total_rows = df[df[prod.name].isin(prod.total_values)]
    cpi_t, cpi_p = _val(total_rows, profile.last_period), _val(total_rows, prev)
    if not cpi_t or not cpi_p:
        return
    body = df[~df[prod.name].isin(prod.total_values)]
    if "level" not in body.columns or not body["level"].notna().any():
        return
    top = body[body["level"] == body["level"].min()]
    rows = []
    for name, g in top.groupby(prod.name, sort=False):
        a, b = _val(g, profile.last_period), _val(g, prev)
        w = g["attr_weights"].dropna()
        if a is not None and b is not None and not w.empty:
            rows.append((str(name), float(w.iloc[0]), a, b))
    if len(rows) < 3:
        return
    wsum = sum(r[1] for r in rows)
    scale = 1.0 if 99.0 <= wsum <= 101.0 else 100.0 / wsum
    contrib = pd.Series({n: (w * scale / 100) * (a - b) / cpi_p * 100 for n, w, a, b in rows}).sort_values(ascending=False)
    headline = (cpi_t / cpi_p - 1) * 100
    total = float(contrib.sum())
    analysis.extras["cpi_contributions"] = contrib
    analysis.extras["cpi_headline_yoy"] = headline
    lead = join_list([f"{display(n)} ({fmt_pp(v, 2, signed=True)})" for n, v in contrib.head(2).items()])
    facts.append(Fact(
        "contribution", "composition", tr("Consumer prices"),
        tr("Annual inflation in {period} was {headline}. The biggest contributions came from {lead} (approximate, based on the "
           "published weights). Together the {n} main groups account for {total}.", period=human_period(profile.last_period),
           headline=fmt_pct(headline), lead=lead, n=num(len(contrib)), total=fmt_pp(total, 2)),
        0.88, {"contributions": contrib.to_dict(), "headline": headline, "sum": total}, None, profile.last_period))
    gap = abs(total - headline)
    detail = tr("The weighted contributions add up to {total}, against {headline} for the total index.", total=fmt_pp(total, 2),
                headline=fmt_pct(headline, 2))
    if gap > 0.3:
        detail += " " + tr("A small difference is normal when INSTAT changes the weights or chain-links the index.")
    analysis.checks.append(Check("contributions add up to headline inflation", "pass" if gap <= 0.3 else "info", detail,
                                 name=tr("Contributions add up to headline inflation")))


def _holds(bad: pd.Series, total: int, worst: float | None = None) -> str:
    """"It holds in all 12 periods (largest gap 0.1%)." or "It fails in 3 of 12 periods."."""
    if bad.empty:
        if worst is None:
            return tr("It holds in all {n} periods.", n=num(total))
        return tr("It holds in all {n} periods (largest gap {gap}).", n=num(total), gap=fmt_pct(worst * 100, 3))
    return tr("It fails in {bad} of {n} periods.", bad=num(len(bad)), n=num(total))


def gdp_identities(table, profile, analysis, facts) -> None:
    df = table.df
    if "national_accounts" not in profile.topics:
        return
    out_m, ic_m = _find_measure(df, "output"), _find_measure(df, "intermediate")
    gva_m = _find_measure(df, "gross value added", "value added")
    tax_m = _find_measure(df, "net taxes", "taxes on products")
    gdp_m = _find_measure(df, "gdp at market", "gross domestic product", "gdp")
    if not (out_m and ic_m and gva_m):
        return
    piv = df.pivot_table(index="period", columns="measure", values="value", aggfunc="first")
    err = ((piv[out_m] - piv[ic_m]) - piv[gva_m]).abs() / piv[gva_m].abs()
    bad = err[err > 0.005]
    analysis.checks.append(Check(
        "output minus intermediate consumption equals gross value added", "pass" if bad.empty else "fail",
        _holds(bad, len(err), err.max()), [human_period(p) for p in bad.index[:3]],
        name=tr("Output minus intermediate consumption equals gross value added")))
    if tax_m and gdp_m and gdp_m != gva_m:
        err2 = ((piv[gva_m] + piv[tax_m]) - piv[gdp_m]).abs() / piv[gdp_m].abs()
        bad2 = err2[err2 > 0.005]
        analysis.checks.append(Check(
            "gross value added plus net taxes equals GDP", "pass" if bad2.empty else "fail", _holds(bad2, len(err2)),
            name=tr("Gross value added plus net taxes on products equals GDP")))
        last = piv.index[-1]
        share = piv.loc[last, tax_m] / piv.loc[last, gdp_m] * 100
        facts.append(Fact("share", "composition", tr("GDP"),
                          tr("In {period}, net taxes on products were {share} of GDP at market prices. The rest is gross value added.",
                             period=human_period(last), share=fmt_pct(share)),
                          0.6, {"share": share, "period": last}, None, last))


def trade_balance(table, profile, analysis, facts) -> None:
    df = table.df
    if "trade" not in profile.topics:
        return

    def has(col: str) -> bool:
        vals = [str(v) for v in df[col].unique()]
        return any(re.search("export", v, re.I) for v in vals) and any(re.search("import", v, re.I) for v in vals)

    # the indicators are normally measures by now; otherwise look in a category dimension
    col = "measure" if has("measure") else next((d.name for d in profile.dims if has(d.name)), None)
    if col is None:
        return
    names = {str(v): v for v in df[col].unique()}

    def pick(pattern: str):
        return next((v for k, v in names.items() if re.search(pattern, k, re.I)), None)

    exp, imp, bal, cov = pick("export"), pick("import"), pick("balance|deficit"), pick("coverage")
    if not (exp and imp):
        return
    sel = _hold_others(df, profile, {col})
    piv = sel.pivot_table(index="period", columns=col, values="value", aggfunc="first").sort_index()
    if bal:
        err = ((piv[exp] - piv[imp]) - piv[bal]).abs()
        tol = max(1e-6, 0.005 * piv[imp].abs().median())
        bad = err[err > tol]
        analysis.checks.append(Check("trade balance equals exports minus imports", "pass" if bad.empty else "fail",
                                     _holds(bad, len(err)), name=tr("Trade balance equals exports minus imports")))
    if cov:
        err = (piv[exp] / piv[imp] * 100 - piv[cov]).abs()
        bad = err[err > 0.5]
        detail = (tr("It holds in all {n} periods.", n=num(len(err))) if bad.empty
                  else tr("It differs by more than 0.5 pp in {bad} periods.", bad=num(len(bad))))
        analysis.checks.append(Check("coverage ratio equals exports divided by imports", "pass" if bad.empty else "warn", detail,
                                     name=tr("Coverage ratio equals exports divided by imports")))
    last = piv.index[-1]
    e, i = piv.loc[last, exp], piv.loc[last, imp]
    mi = profile.measure(str(exp)) if col == "measure" else None
    code, scale = (mi.unit_code, mi.scale) if mi else (table.spec.units.unit or "", table.spec.units.scale)

    def money(x: float) -> str:
        return fmt_value(x, code, scale=scale)

    values = {"period": human_period(last), "exports": money(e), "imports": money(i), "gap": money(abs(e - i)), "cover": fmt_pct(e / i * 100, 0)}
    text = (tr("In {period} exports were {exports} and imports {imports}, a trade deficit of {gap}. Exports covered {cover} of imports.", **values)
            if i > e else
            tr("In {period} exports were {exports} and imports {imports}, a trade surplus of {gap}. Exports covered {cover} of imports.", **values))
    facts.append(Fact("trade", "headline", tr("Foreign trade"), text, 0.9, {"exports": float(e), "imports": float(i), "period": last}, None, last))
    if profile.freq == "M" and len(piv) >= 24:
        a, b = piv.tail(12), piv.iloc[-24:-12]
        ge, gi = (a[exp].sum() / b[exp].sum() - 1) * 100, (a[imp].sum() / b[imp].sum() - 1) * 100
        facts.append(Fact("trade", "change", tr("Foreign trade"),
                          tr("In the twelve months to {period}, exports {exports} and imports {imports}, compared with the twelve months "
                             "before.", period=human_period(last), exports=_moved(ge), imports=_moved(gi)), 0.8,
                          {"exports_growth": ge, "imports_growth": gi}, None, last))


def _moved(change: float) -> str:
    """"rose 5.1%" or "fell 2.3%"."""
    if change >= 0:
        return tr("rose {amount}", amount=fmt_pct(abs(change)))
    return tr("fell {amount}", amount=fmt_pct(abs(change)))


def age_structure(table, profile, analysis, facts) -> None:
    df = table.df
    age = profile.dim("age_group")
    if age is None or "population" not in profile.topics or not profile.last_period:
        return
    sel = _hold_others(df, profile, {age.name})
    if sel.empty:
        return

    def shares(period: str) -> dict | None:
        g = sel[(sel["period"] == period) & ~sel[age.name].isin(age.total_values)]
        groups: dict[tuple[int, int | None], float] = {}
        for label, v in zip(g[age.name], g["value"]):
            b = _age_bounds(str(label))
            if b is None or pd.isna(v):
                return None
            groups[b] = groups.get(b, 0) + float(v)
        if len(groups) < 6:
            return None
        young = sum(v for (lo, hi), v in groups.items() if hi is not None and hi <= 14)
        work = sum(v for (lo, hi), v in groups.items() if lo >= 15 and hi is not None and hi <= 64)
        old = sum(v for (lo, hi), v in groups.items() if lo >= 65)
        total = young + work + old
        if total <= 0 or work <= 0:
            return None
        return {"young": young / total * 100, "work": work / total * 100, "old": old / total * 100,
                "old_dep": old / work * 100, "young_dep": young / work * 100,
                "aging": (old / young * 100) if young else float("nan"), "total": total}

    last = shares(profile.last_period)
    if not last:
        return
    analysis.extras["age_structure"] = last
    facts.append(Fact(
        "age_structure", "composition", tr("Population"),
        tr("In {period}, {young} of the population is under 15, {work} is of working age (15 to 64) and {old} is 65 or older. For every "
           "100 people of working age there are {old_dep} aged 65 and over, and for every 100 children there are {aging} older people.",
           period=human_period(profile.last_period), young=fmt_pct(last["young"], 0), work=fmt_pct(last["work"], 0),
           old=fmt_pct(last["old"], 0), old_dep=num(last["old_dep"]), aging=num(last["aging"])), 0.9, last, None, profile.last_period))
    if profile.first_period and profile.first_period != profile.last_period:
        first = shares(profile.first_period)
        if first:
            d_old, d_young = last["old"] - first["old"], last["young"] - first["young"]
            facts.append(Fact(
                "age_structure", "change", tr("Population"),
                tr("Since {first}, the share aged 65 and over has {old_move} by {old_by}, and the share under 15 has {young_move} by "
                   "{young_by}.", first=human_period(profile.first_period), old_move=risen(d_old > 0), old_by=fmt_pp(abs(d_old)),
                   young_move=risen(d_young > 0), young_by=fmt_pp(abs(d_young))), 0.78,
                {"first": first, "last": last}, None, profile.last_period))


def youth_unemployment(table, profile, analysis, facts) -> None:
    df = table.df
    if "labour" not in profile.topics or profile.unit != "%":
        return
    age = profile.dim("age_group")
    if age is None or not profile.last_period:
        return
    sel = _hold_others(df[df["period"] == profile.last_period], profile, {age.name})
    by = sel.drop_duplicates(age.name).set_index(age.name)["value"]
    youth = next((k for k in by.index if _age_bounds(str(k)) == (15, 29)), None)
    base = next((k for k in by.index if _age_bounds(str(k)) in ((15, None), (15, 64))), None)
    if youth is None or base is None or pd.isna(by[youth]) or pd.isna(by[base]) or by[base] <= 0:
        return
    facts.append(Fact(
        "youth", "comparison", table.measure or tr("rate"),
        tr("In {period} the rate for ages 15 to 29 ({youth}) is {ratio} times the rate for ages {base} ({base_rate}).",
           period=human_period(profile.last_period), youth=fmt_pct(by[youth]), ratio=num(by[youth] / by[base], 1),
           base=age_label(str(base)), base_rate=fmt_pct(by[base])), 0.82,
        {"youth": float(by[youth]), "base": float(by[base])}, None, profile.last_period))


def gender_pay_gap(table, profile, analysis, facts) -> None:
    df = table.df
    sex = profile.dim("sex")
    if "wages" not in profile.topics or sex is None or profile.unit.endswith("%") or not profile.last_period:
        return
    female = next((v for v in df[sex.name].unique() if v in ("Females", "Female", "Women")), None)
    male = next((v for v in df[sex.name].unique() if v in ("Males", "Male", "Men")), None)
    if not female or not male:
        return
    period = profile.last_period
    sel = df[df["period"] == period]
    cats = [d for d in profile.dims if d.name != sex.name and d.n_values - len(d.total_values) >= 2
            and d.role != "code" and not d.role.endswith("_code")]
    cat = cats[0] if cats else None
    sel = _hold_others(sel, profile, {sex.name} | ({cat.name} if cat else set()))
    if cat is None:
        m, f = sel[sel[sex.name] == male]["value"].dropna(), sel[sel[sex.name] == female]["value"].dropna()
        if len(m) == 1 and len(f) == 1 and m.iloc[0] > 0:
            gap = (m.iloc[0] - f.iloc[0]) / m.iloc[0] * 100
            values = {"period": human_period(period), "amount": fmt_pct(abs(gap)), "gap": fmt_pct(gap, signed=True)}
            text = (tr("In {period} women's average pay is {amount} below men's (gender pay gap: {gap}).", **values) if gap > 0 else
                    tr("In {period} women's average pay is {amount} above men's (gender pay gap: {gap}).", **values))
            _replace_gap(facts, Fact("pay_gap", "headline", tr("Gender pay gap"), text, 0.92, {"gap_pct": float(gap)}, None, period))
        return
    sel = sel[~sel[cat.name].isin(list(cat.total_values) + [""])]
    piv = sel.pivot_table(index=cat.name, columns=sex.name, values="value", aggfunc="first")
    if male not in piv or female not in piv:
        return
    piv = piv.dropna(subset=[male, female])
    piv = piv[piv[male] > 0]
    if len(piv) < 3:
        return
    gap = (piv[male] - piv[female]) / piv[male] * 100
    worse = int((gap > 0).sum())
    big, small = gap.idxmax(), gap.idxmin()
    analysis.extras["pay_gap"] = gap.sort_values(ascending=False)
    text = tr("In {period} women earn less than men in {worse} of {n} categories {by}. The median gender pay gap is {median}, widest in "
              "{widest} ({widest_gap}).", period=human_period(period), worse=num(worse), n=num(len(gap)), by=by_role(cat.role),
              median=fmt_pct(gap.median()), widest=display(str(big)), widest_gap=fmt_pct(gap[big]))
    if gap[small] < 0:
        text += " " + tr("In {place} women earn {amount} more than men.", place=display(str(small)), amount=fmt_pct(abs(gap[small])))
    _replace_gap(facts, Fact("pay_gap", "headline", tr("Gender pay gap"), text, 0.92,
                             {"median_gap": float(gap.median()), "worse": worse, "n": len(gap), "widest": str(big)}, None, period))


def _replace_gap(facts: list[Fact], fact: Fact) -> None:
    """The pay-gap statement replaces the general comparison of women and men."""
    facts[:] = [f for f in facts if f.kind != "gap"]
    facts.append(fact)


RECIPES: list[Callable] = [cpi_contributions, gdp_identities, trade_balance, age_structure, youth_unemployment, gender_pay_gap]
