"""The two things the web layer needs before pandas is loaded: the error type and the JSON encoder.

Keeping them out of ``api`` lets the server start listening, and the browser show the page, while the heavy analysis
libraries are still being imported in the background (noticeable on an old computer).
"""

from __future__ import annotations

import json


class ApiError(Exception):
    """Something the user should be told about; the server turns it into a JSON error reply."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def _default(o: object) -> object:
    item = getattr(o, "item", None)
    if callable(item):  # numpy scalars
        return item()
    if hasattr(o, "isoformat"):  # dates, datetimes, pandas Timestamps
        return o.isoformat()
    if isinstance(o, (set, frozenset, tuple)):
        return list(o)
    return str(o)


def dumps(obj: object) -> bytes:
    return json.dumps(obj, ensure_ascii=False, default=_default, separators=(",", ":")).encode("utf-8")
