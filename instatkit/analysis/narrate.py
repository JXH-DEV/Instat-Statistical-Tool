"""Puts the facts of one analysed table together into a short written briefing (fixed rules, no internet, no AI)."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..i18n import N_, num, tn, tr
from ..semantics.interpret import DatasetProfile
from ..semantics.labels import by_role, topic_name
from ..semantics.units import unit_text
from .engine import Analysis
from .fmt import human_period, join_list
from .insights import short_measure

SECTION_TITLES = {
    "headline": N_("Main findings"),
    "change": N_("Recent changes"),
    "pattern": N_("Patterns over time"),
    "comparison": N_("Comparisons"),
    "composition": N_("Breakdown"),
    "caveat": N_("Worth knowing"),
}
SECTION_CAPS = {"headline": 5, "change": 4, "pattern": 5, "comparison": 4, "composition": 3, "caveat": 4}

_PRICE_BASIS = {"current": N_("current prices"), "previous_year": N_("previous-year prices"), "constant": N_("constant prices")}
_BASES = {"previous_year": N_("the previous year"), "previous_december": N_("the previous December"),
          "same_period": N_("the same period of the previous year")}


@dataclass
class Briefing:
    title: str
    subtitle: str
    what_is_this: str
    sections: list[tuple[str, list[str]]] = field(default_factory=list)

    def markdown(self) -> str:
        lines = [f"# {self.title}", f"*{self.subtitle}*", "", self.what_is_this, ""]
        for name, bullets in self.sections:
            lines.append(f"## {name}")
            lines += [f"- {b}" for b in bullets]
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"


def _what_it_measures(p: DatasetProfile) -> str:
    if len(p.measures) > 1:
        names = join_list([short_measure(m.display) for m in p.measures[:4]]) + ("…" if len(p.measures) > 4 else "")
        return tr("{n} measures ({names})", n=num(len(p.measures)), names=names)
    return short_measure(p.measures[0].display) if p.measures else p.shown_title


def _how_it_is_broken_down(p: DatasetProfile) -> str:
    parts = []
    for d in p.dims:
        if d.alias_of:
            continue
        details = [tn(d.n_values - len(d.total_values), "{n} category", "{n} categories")]
        if d.total_values:
            details.append(tr("plus a total"))
        if any(o.alias_of == d.name for o in p.dims):
            details.append(tr("with classification codes"))
        parts.append(f"{by_role(d.role)} ({', '.join(details)})")
    return join_list(parts)


def describe_profile(p: DatasetProfile) -> str:
    """One paragraph on what the file is, in words a non-specialist can follow."""
    measure = _what_it_measures(p)
    first, last = human_period(p.first_period), human_period(p.last_period)
    if p.kind == "time_series":
        values = {"frequency": tr(p.freq_name), "measure": measure, "first": first, "last": last,
                  "periods": tn(p.n_periods, "{n} period", "{n} periods")}
        if p.freq_name[:1] in "aeiou":
            head = tr("This is an {frequency} series of {measure}, from {first} to {last} ({periods}).", **values)
        else:
            head = tr("This is a {frequency} series of {measure}, from {first} to {last} ({periods}).", **values)
    elif p.kind == "short_panel":
        head = tr("This table compares {measure} across two periods: {first} and {last}.", measure=measure, first=first, last=last)
    elif p.first_period:
        head = tr("This is a snapshot for {period}: {measure} compared across categories.", period=first, measure=measure)
    else:
        head = tr("This is a snapshot with no time axis: {measure} compared across categories.", measure=measure)
    bits = []
    dated_base = bool(p.base_period and p.base_period[:1].isdigit())
    if dated_base and (p.unit or "").startswith("index"):  # the unit label already carries the base: say it once
        bits.append(tr("the values are an index with {period} = 100", period=human_period(p.base_period)))
    else:
        if p.unit:
            bits.append(tr("values are in {unit}", unit=unit_text(p.unit)))
        if dated_base:
            bits.append(tr("the index base is {period} = 100", period=human_period(p.base_period)))
    if p.base_period and not dated_base:
        bits.append(tr("changes are measured against {what}", what=tr(_BASES[p.base_period]) if p.base_period in _BASES else p.base_period.replace("_", " ")))
    if p.price_basis:
        bits.append(tr("figures are at {basis}", basis=tr(_PRICE_BASIS[p.price_basis])))
    tail = []
    if bits:
        tail.append(tr("In the file, {bits}.", bits=join_list(bits)))
    series = tn(p.n_series, "{n} series", "{n} series")
    observations = tn(p.n_obs, "{n} observation", "{n} observations")
    dims = _how_it_is_broken_down(p)
    if dims:
        tail.append(tr("It is broken down {dims}, giving {series} and {observations}.", dims=dims, series=series, observations=observations))
    else:
        tail.append(tr("It contains {series} and {observations}.", series=series, observations=observations))
    if p.code_system:
        tail.append(tr("Rows follow the {code_system} classification.", code_system=p.code_system))
    if p.topics:
        tail.append(tr("Topic: {topics}.", topics=", ".join(topic_name(t) for t in p.topics[:3])))
    return " ".join([head] + tail)


def narrate(analysis: Analysis, *, caps: dict[str, int] | None = None) -> Briefing:
    p = analysis.profile
    caps = {**SECTION_CAPS, **(caps or {})}
    sub = [tr(p.freq_name).capitalize() if p.freq else tr("Snapshot")]
    if p.first_period:
        sub.append(human_period(p.first_period) if p.first_period == p.last_period else
                   f"{human_period(p.first_period)} – {human_period(p.last_period)}")
    if p.unit:
        sub.append(unit_text(p.unit))
    sections: list[tuple[str, list[str]]] = []
    by = analysis.facts_by_section()
    for key in ("headline", "change", "pattern", "comparison", "composition", "caveat"):
        facts = sorted(by.get(key, []), key=lambda f: -f.importance)[: caps[key]]
        if facts:
            sections.append((tr(SECTION_TITLES[key]), [f.text for f in facts]))
    return Briefing(p.shown_title, " · ".join(sub), describe_profile(p), sections)
