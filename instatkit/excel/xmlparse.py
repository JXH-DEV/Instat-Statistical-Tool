"""What the two XML readers (``.xlsx`` and Excel 2003 XML) share: the target base and namespace-free names."""

from __future__ import annotations

from ..i18n import tr
from .raw import UnreadableWorkbook


class Names(dict):
    """Element names without their ``{namespace}``, so the strict and transitional flavours read the same: ``names[tag]``.
    Memoised for the length of one parse (a hit is a plain dict lookup), and never beyond a thousand entries, so a file
    with endless distinct tags cannot make it grow."""

    def __missing__(self, tag: str) -> str:
        name = tag.rpartition("}")[2]
        if len(self) < 1024:
            self[tag] = name
        return name


class Target:
    """Base of the expat targets. Entity declarations live inside a DOCTYPE, so refusing the DOCTYPE in the parser,
    wherever it appears in the part, rules out entity-expansion files without scanning the bytes for it."""

    def __init__(self) -> None:
        self._names = Names()

    def doctype(self, name: str, pubid: str | None, system: str | None) -> None:
        raise UnreadableWorkbook(tr("This file uses XML features (a DOCTYPE or entity declarations) that are not read for safety."))
