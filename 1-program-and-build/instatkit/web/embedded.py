"""The program as a function from a request to a reply, for the web version, where it runs inside the visitor's browser (Pyodide).

The page asks for ``/api/...`` exactly as it asks a local server, and ``handle`` answers with the same handlers (``server._App.routes``),
without sockets, cookies or threads. The language is the page's: it arrives in the ``x-language`` header.
"""

from __future__ import annotations

import sys
import traceback
from urllib.parse import parse_qs, urlsplit

from .. import i18n
from ..i18n import tr
from .common import ApiError
from .server import Reply, Request, _App, _error, _json


class _Headers(dict):
    """Request headers with lower-case names, looked up without regard to case (as the headers of a real request are)."""

    def __init__(self, items: dict[str, str]) -> None:
        super().__init__({str(k).lower(): str(v) for k, v in items.items()})

    def get(self, key, default=None):
        return super().get(key.lower(), default)


_app: _App | None = None


def app() -> _App:
    """The one program of this browser tab: its open files live as long as the tab does."""
    global _app
    if _app is None:
        _app = _App(share=True, port=0, web=True)
    return _app


def handle(method: str, target: str, headers: dict[str, str], body: bytes) -> tuple[int, str, dict[str, str], bytes]:
    """Answer one request of the page: ``(status, content type, headers, body)``."""
    headers = _Headers(headers)
    i18n.set_language(headers.get("x-language"))
    reply = _answer(method, target, headers, body)
    return reply.status, reply.ctype, dict(reply.headers), reply.body


def _answer(method: str, target: str, headers: _Headers, body: bytes) -> Reply:
    split = urlsplit(target)
    query = {k: v[-1] for k, v in parse_qs(split.query, keep_blank_values=True).items()}
    route = app().routes.get((method, split.path))
    if route is None:
        return _error(404, tr("Not found."))
    cap, handler = route
    if len(body) > cap:
        return _error(413, tr("The request is larger than the limit of {limit} MB.", limit=max(cap // 1_000_000, 1)))
    try:
        return handler(app().ws, Request(query, body, headers))
    except ApiError as exc:
        return _json({"error": str(exc)}, exc.status)
    except Exception:  # the page shows a sentence; the details go to the browser console
        traceback.print_exc(file=sys.stderr)
        return _error(500, tr("Something went wrong inside the program. The details are in its window."))
