"""A short list of well-known events that can sit behind an unusual period in Albanian data.

They are only ever offered as possible context next to something unusual, never as the cause.
"""

from __future__ import annotations

from datetime import date

from ..i18n import N_, tr

EVENTS: list[tuple[date, date, str]] = [
    (date(2019, 11, 26), date(2020, 1, 31), N_("the November 2019 earthquake")),
    (date(2020, 3, 1), date(2021, 6, 30), N_("COVID-19 restrictions")),
    (date(2022, 2, 24), date(2023, 6, 30), N_("the 2022-23 energy and food price shock")),
]


def events_for(start: date, end: date) -> list[str]:
    """The events whose dates overlap ``start`` to ``end``."""
    return [tr(name) for a, b, name in EVENTS if start <= b and end >= a]
