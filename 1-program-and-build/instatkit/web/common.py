"""The two things the web layer needs before pandas is loaded: the error type and the JSON encoder.

Keeping them out of ``api`` lets the server start listening, and the browser show the page, while the heavy analysis
libraries are still being imported in the background (noticeable on an old computer).
"""

from __future__ import annotations

import json
import math
from typing import Any

from ..i18n import tr


class ApiError(Exception):
    """Something the user should be told about; the server turns it into a JSON error reply."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def whole_number(value: object, label: str, *, minimum: int | None = None) -> int:
    """``value`` as an integer; otherwise an :class:`ApiError` that names the field, in words the page can show."""
    try:
        if isinstance(value, bool) or (isinstance(value, float) and not value.is_integer()):
            raise ValueError(value)
        number = value if isinstance(value, int) else int(value) if isinstance(value, float) else int(str(value).strip())
    except (ValueError, TypeError):
        raise ApiError(tr("{field} must be a whole number.", field=label)) from None
    if minimum is not None and number < minimum:
        raise ApiError(tr("{field} must be {minimum} or more.", field=label, minimum=minimum))
    return number


def _default(o: object) -> object:
    item = getattr(o, "item", None)
    if callable(item):  # numpy scalars
        return item()
    if hasattr(o, "isoformat"):  # dates, datetimes, pandas Timestamps
        return o.isoformat()
    if isinstance(o, (set, frozenset, tuple)):
        return list(o)
    return str(o)


def _finite(o: object) -> object:
    """``o`` with every NaN or infinity replaced by ``None``: JSON has no such numbers, and ``JSON.parse`` rejects the
    bare ``NaN`` that Python would write."""
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: _finite(v) for k, v in o.items()}
    if isinstance(o, list | tuple | set | frozenset):
        return [_finite(v) for v in o]
    item = getattr(o, "item", None)
    if callable(item):  # numpy scalars
        try:
            return _finite(item())
        except (TypeError, ValueError):
            return o
    return o


def dumps(obj: object) -> bytes:
    """The JSON bytes of a reply. Always valid JSON: a NaN or infinity anywhere in it is written as ``null``."""
    kw: dict[str, Any] = {"ensure_ascii": False, "default": _default, "separators": (",", ":"), "allow_nan": False}
    try:
        return json.dumps(obj, **kw).encode("utf-8")
    except ValueError:  # a non-finite number somewhere
        return json.dumps(_finite(obj), **kw).encode("utf-8")
