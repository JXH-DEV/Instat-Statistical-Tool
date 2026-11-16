"""Findings are facts first and sentences second.

Every sentence the program shows comes with a :class:`Fact` whose ``data`` holds the exact numbers it was built from,
so nothing is made up and the evidence behind each claim can be shown.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..i18n import N_, language, tr

SECTIONS = ["headline", "change", "pattern", "comparison", "composition", "caveat"]


@dataclass
class Fact:
    kind: str  # latest | change | extreme | trend | seasonality | anomaly | shift | ranking | movers | ...
    section: str  # one of SECTIONS
    subject: str  # the series / category the fact is about
    text: str  # rendered sentence
    importance: float = 0.5  # 0..1, used to pick what to show first
    data: dict = field(default_factory=dict)  # the numbers behind the sentence
    series_id: int | None = None
    period: str | None = None

    def __post_init__(self) -> None:
        if language() == "sq":  # a month is written in lower case in Albanian, but a sentence still starts with a capital
            self.text = self.text[:1].upper() + self.text[1:]


@dataclass
class Check:
    key: str  # a fixed English id, for the code to recognise the check
    status: str  # pass | warn | fail | info
    detail: str
    examples: list[str] = field(default_factory=list)
    name: str = ""  # what the user sees; the key, translated, unless given

    def __post_init__(self) -> None:
        self.name = self.name or tr(self.key)


_KINDS = {
    "latest": N_("Latest value"), "change": N_("Change"), "extreme": N_("Record"), "trend": N_("Trend"),
    "seasonality": N_("Seasonal pattern"), "anomaly": N_("Unusual period"), "shift": N_("Change in pattern"),
    "ranking": N_("Ranking"), "movers": N_("Biggest changes"), "composition": N_("Breakdown"), "gap": N_("Women and men"),
    "growth": N_("Growth"), "contribution": N_("Contributions"), "share": N_("Share"), "trade": N_("Foreign trade"),
    "age_structure": N_("Age structure"), "youth": N_("Young people"), "pay_gap": N_("Gender pay gap"), "range": N_("Range"),
    "caveat": N_("Worth knowing"),
}
_STATUS = {"pass": N_("Passed"), "warn": N_("Check"), "fail": N_("Problem"), "info": N_("Note")}


def kind_text(kind: str) -> str:
    """A readable name for the kind of a finding."""
    return tr(_KINDS[kind]) if kind in _KINDS else kind


def status_text(status: str) -> str:
    """The word shown for a check's status."""
    return tr(_STATUS[status]) if status in _STATUS else status


def sort_facts(facts: list[Fact]) -> list[Fact]:
    order = {s: i for i, s in enumerate(SECTIONS)}
    return sorted(facts, key=lambda f: (order.get(f.section, 99), -f.importance))
