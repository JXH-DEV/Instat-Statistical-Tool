"""The local web server: static assets and a JSON API on the standard library, hardened for a program on someone's PC.

* It listens on 127.0.0.1 only (``--share`` opens it to the local network, still behind the access token).
* Every request needs the random per-run access token, handed to the browser once in the start-up link and kept in a
  ``SameSite=Strict`` cookie, so other local users and web pages cannot use the program.
* ``Host`` is checked (DNS rebinding), writes need a custom header plus a matching ``Origin`` (cross-site requests),
  bodies are size-capped, and responses carry a strict Content-Security-Policy.
* The heavy analysis code (:mod:`.api`, pandas) is imported in the background after the port is open, so the page
  appears at once even on a slow computer; the first request that needs it simply waits for the import to finish.
"""

from __future__ import annotations

import codecs
import contextlib
import hmac
import json
import re
import secrets
import socket
import sys
import threading
import time
import traceback
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cache
from html import escape
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, unquote, urlsplit

from .. import __version__, config, i18n
from ..i18n import tr
from ..viz.theme import chart_css
from .common import ApiError, dumps

if TYPE_CHECKING:
    from . import api as api_module

MAX_JSON = 1 << 20
LINGER_BYTES, LINGER_SECONDS = 256 << 20, 5  # how much of a refused request body is read and thrown away, and for how long
COOKIE = "instat"
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
       "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
_LOCKED = ("<!doctype html><meta charset=utf-8><title>INSTAT Explorer</title>"
           "<body style=\"font:16px system-ui;max-width:34rem;margin:15vh auto\">"
           "<h1>Open INSTAT Explorer from its own window</h1><p>This address needs the access link that the program prints (it "
           "changes every time the program starts). Close this tab, start INSTAT Explorer again and use the link it opens.</p>"
           "<h1>Hapeni INSTAT Explorer nga dritarja e vet</h1><p>Kjo adresë ka nevojë për lidhjen e hyrjes që shfaq programi "
           "(ndryshon sa herë që niset). Mbyllni këtë skedë, nisni sërish INSTAT Explorer dhe përdorni lidhjen që hap ai.</p>"
           ).encode()
_PAGES = {"/": "index.html", "/index.html": "index.html", "/app.css": "app.css", "/app.js": "app.js",
          "/chart.css": "chart.css", "/chart.js": "chart.js"}
_MARK = re.compile(r"\{\{(.+?)\}\}")


def _api() -> api_module:
    """The analysis layer, imported on first use (and by the start-up warm-up thread)."""
    from . import api

    return api


@dataclass
class Request:
    query: dict[str, str]
    body: bytes
    headers: object
    _json: dict | None = field(default=None, repr=False)

    def json(self) -> dict:
        if self._json is None:
            try:
                data = json.loads(self.body or b"{}")
            except ValueError as exc:
                raise ApiError(tr("The request was not valid JSON.")) from exc
            if not isinstance(data, dict):
                raise ApiError(tr("The request must be a JSON object."))
            self._json = data
        return self._json

    def arg(self, name: str, default: str = "") -> str:
        if name in self.query:
            return self.query[name]
        return str(self.json().get(name, default)) if self.body else default


@dataclass
class Reply:
    status: int = 200
    body: bytes = b""
    ctype: str = "application/json; charset=utf-8"
    headers: dict[str, str] = field(default_factory=dict)


def _json(obj: object, status: int = 200) -> Reply:
    return Reply(status, dumps(obj))


def _error(status: int, message: str) -> Reply:
    return _json({"error": message}, status)


def _attachment(name: str, mime: str, data: bytes) -> Reply:
    return Reply(200, data, mime, {"Content-Disposition": f'attachment; filename="{name}"'})


@cache
def _asset(name: str) -> tuple[bytes, str]:
    if name == "chart.css":
        return chart_css().encode(), "text/css; charset=utf-8"
    if name == "chart.js":
        return files("instatkit.viz").joinpath("chart.js").read_bytes(), "text/javascript; charset=utf-8"
    ctype = {"html": "text/html; charset=utf-8", "css": "text/css; charset=utf-8", "js": "text/javascript; charset=utf-8"}[name.rsplit(".", 1)[1]]
    return files("instatkit.web").joinpath("static", name).read_bytes().replace(b"{{v}}", __version__.encode()), ctype


def _page(html: bytes) -> bytes:
    """The start page in the language of this request. ``{{some text}}`` is translated; ``{{lang}}``, ``{{other}}`` and
    ``{{other_name}}`` stand for the language in use and the one that the language button switches to."""
    code = i18n.language()
    other = next(c for c in i18n.LANGUAGES if c != code)
    fixed = {"lang": code, "other": other, "other_name": i18n.LANGUAGES[other]}
    return _MARK.sub(lambda m: escape(fixed.get(m[1]) or tr(m[1])), html.decode()).encode()


Handler = Callable[["api_module.Workspace", Request], Reply]


def _table(ws, r: Request):
    """(key, table number, ProcessedFile, ProcessedTable) named by the request."""
    key, i = r.arg("key"), r.arg("i", "0")
    if not i.isdigit():
        raise ApiError(tr("Bad table number."))
    pf, pt = ws.get(key, int(i))
    return key, int(i), pf, pt


def _summary(ws, r):
    _k, _i, pf, pt = _table(ws, r)
    return _json(_api().summary(pf, pt))


def _explore(ws, r):
    out = _api().explore(_table(ws, r)[3], r.json())
    if "csv" in out:
        return _attachment("view.csv", "text/csv; charset=utf-8", codecs.BOM_UTF8 + out["csv"].encode("utf-8"))
    return _json(out)


def _data(ws, r):
    key, i, _pf, pt = _table(ws, r)
    return _json(_api().data_page(ws, key, i, pt, r.query))


def _read(ws, r):
    _k, _i, pf, pt = _table(ws, r)
    return _json(_api().read_info(pf, pt, int(r.query.get("part", "0") or 0)))


def _reread(ws, r):
    key, i, _pf, _pt = _table(ws, r)
    return _json(_api().reread(ws, key, i, r.json()))


def _quality(ws, r):
    return _json(_api().quality(_table(ws, r)[3]))


def _export(ws, r):
    key, i, _pf, _pt = _table(ws, r)
    return _attachment(*_api().export(ws, key, i, r.arg("kind")))


def _upload(ws, r):
    return _json(_api().load_upload(ws, r.body, unquote(r.headers.get("X-Filename", "upload.xlsx"))))


def _load(ws, r):
    j = r.json()
    return _json(_api().load_url(ws, str(j.get("url", "")), j.get("label"), bool(j.get("external"))))


class _App:
    def __init__(self, share: bool, port: int, ws=None) -> None:
        self.token = secrets.token_urlsafe(24)
        self.share = share
        self.hosts = None if share else {f"{h}:{port}" for h in ("127.0.0.1", "localhost", "[::1]")}
        self.server: ThreadingHTTPServer | None = None
        self._ws, self._ws_lock = ws, threading.Lock()
        self.routes: dict[tuple[str, str], tuple[int, Handler]] = {
            ("GET", "/api/state"): (MAX_JSON, lambda w, r: _json(_api().state(w))),
            ("GET", "/api/about"): (MAX_JSON, lambda w, r: _json(_api().about())),
            ("GET", "/api/lang"): (MAX_JSON, lambda w, r: _json(_api().translations(r.arg("code", i18n.language())))),
            ("POST", "/api/resolve"): (MAX_JSON, lambda w, r: _json(_api().resolve_query(str(r.json().get("q", ""))[:500]))),
            ("POST", "/api/listing"): (MAX_JSON, lambda w, r: _json(_api().listing(w, str(r.json().get("url", ""))))),
            ("POST", "/api/load"): (MAX_JSON, _load),
            ("POST", "/api/upload"): (config.MAX_DOWNLOAD_BYTES, _upload),
            ("POST", "/api/demo"): (MAX_JSON, lambda w, r: _json(_api().load_demo(w, str(r.json().get("name", ""))))),
            ("POST", "/api/close"): (MAX_JSON, lambda w, r: _json(_api().close_file(w, r.json().get("key")))),
            ("GET", "/api/table"): (MAX_JSON, _summary),
            ("POST", "/api/explore"): (MAX_JSON, _explore),
            ("GET", "/api/data"): (MAX_JSON, _data),
            ("GET", "/api/read"): (MAX_JSON, _read),
            ("POST", "/api/reread"): (MAX_JSON, _reread),
            ("GET", "/api/quality"): (MAX_JSON, _quality),
            ("GET", "/export"): (MAX_JSON, _export),
            ("POST", "/api/quit"): (MAX_JSON, self._quit),
        }

    @property
    def ws(self):
        """The workspace; created (which imports the analysis layer) on first use."""
        with self._ws_lock:
            if self._ws is None:
                self._ws = _api().Workspace()
            return self._ws

    def warm_up(self) -> None:
        threading.Thread(target=lambda: self.ws, daemon=True, name="warm-up").start()

    def _quit(self, _ws, _r) -> Reply:
        if self.share:
            raise ApiError(tr("Stopping the program remotely is not allowed."), 403)
        threading.Thread(target=self.stop, daemon=True).start()
        return _json({"ok": True})

    def stop(self) -> None:
        if self.server:
            self.server.shutdown()

    def authorised(self, cookie_header: str | None) -> bool:
        jar = SimpleCookie()
        try:
            jar.load(cookie_header or "")
        except Exception:
            return False
        morsel = jar.get(COOKIE)
        return bool(morsel) and hmac.compare_digest(morsel.value.encode(), self.token.encode())

    def knows(self, token: str) -> bool:
        return hmac.compare_digest(token.encode(), self.token.encode())


class _Handler(BaseHTTPRequestHandler):
    server: _Server
    server_version = "INSTATExplorer"
    sys_version = ""
    protocol_version = "HTTP/1.1"
    timeout = 120  # a stalled client cannot hold a thread forever
    _body_read = True

    def log_message(self, fmt, *args):  # quiet: the console is for the user, not an access log
        pass

    def do_GET(self) -> None:
        self._handle("GET")

    def do_POST(self) -> None:
        self._handle("POST")

    def _refuse(self) -> None:
        self._body_read = False  # these methods may carry a body we will not read: close the connection afterwards
        self._send(_error(405, tr("This method is not allowed.")))

    do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _refuse

    # request handling
    def _pick_language(self) -> None:
        """The language of this request: the ``lang`` cookie the page sets, else what the browser prefers."""
        jar = SimpleCookie()
        with contextlib.suppress(Exception):
            jar.load(self.headers.get("Cookie") or "")
        morsel = jar.get("lang")
        i18n.set_language(morsel.value if morsel else i18n.guess(self.headers.get("Accept-Language")))

    def _handle(self, method: str) -> None:
        self._body_read = method != "POST"
        self._pick_language()
        try:
            reply = self._dispatch(self.server.app, method)
        except Exception:  # never show a traceback to the browser; keep it for the console
            traceback.print_exc(file=sys.stderr)
            reply = _error(500, tr("Something went wrong inside the program. The details are in its window."))
        self._send(reply)

    def _dispatch(self, app: _App, method: str) -> Reply:
        if app.hosts is not None and self.headers.get("Host", "") not in app.hosts:
            return _error(421, tr("Unexpected host name."))
        split = urlsplit(self.path)
        path = split.path
        if path == "/health":
            return Reply(200, b"ok", "text/plain")
        query = {k: v[-1] for k, v in parse_qs(split.query, keep_blank_values=True).items()}
        if path == "/" and method == "GET" and app.knows(query.get("t", "")):
            return Reply(303, b"", "text/plain", {"Location": "/", "Set-Cookie": f"{COOKIE}={app.token}; Path=/; HttpOnly; SameSite=Strict"})
        if not app.authorised(self.headers.get("Cookie")):
            return Reply(403, _LOCKED, "text/html; charset=utf-8")
        if method == "POST" and not self._same_origin():
            return _error(403, tr("A request from another site was refused."))
        if method == "GET" and path in _PAGES:
            body, ctype = _asset(_PAGES[path])
            if _PAGES[path] == "index.html":
                body = _page(body)
            return Reply(200, body, ctype, {"Cache-Control": "no-cache"})
        route = app.routes.get((method, path))
        if route is None:
            return _error(404, tr("Not found."))
        cap, handler = route
        try:
            body = self._read_body(cap) if method == "POST" else b""
            return handler(app.ws, Request(query, body, self.headers))
        except ApiError as exc:
            return _json({"error": str(exc)}, exc.status)

    def _same_origin(self) -> bool:
        if self.headers.get("X-Requested-With") != "instat":  # a custom header cannot be sent cross-site without a CORS pre-flight
            return False
        origin = self.headers.get("Origin")
        return origin is None or origin.split("://", 1)[-1] == self.headers.get("Host")

    def _read_body(self, cap: int) -> bytes:
        if "chunked" in self.headers.get("Transfer-Encoding", "").lower():
            raise ApiError(tr("Chunked uploads are not supported."), 411)
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ApiError(tr("The Content-Length is not valid.")) from None
        if not 0 <= length <= cap:
            raise ApiError(tr("The request is larger than the limit of {limit} MB.", limit=max(cap // 1_000_000, 1)), 413)
        buf = bytearray()
        while len(buf) < length:
            chunk = self.rfile.read(min(1 << 16, length - len(buf)))
            if not chunk:
                raise ApiError(tr("The upload was interrupted."))
            buf.extend(chunk)
        self._body_read = True
        return bytes(buf)

    def _send(self, reply: Reply) -> None:
        if not self._body_read:  # an unread request body would corrupt the next request on this connection
            self.close_connection = True
        self.send_response(reply.status)
        self.send_header("Content-Type", reply.ctype)
        self.send_header("Content-Length", str(len(reply.body)))
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", reply.headers.get("Cache-Control", "no-store"))
        if self.close_connection:
            self.send_header("Connection", "close")
        for k, v in reply.headers.items():
            if k != "Cache-Control":
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(reply.body)
        if not self._body_read:
            self._linger()

    def _linger(self) -> None:
        """Let the client finish sending a body that was refused, within limits. Closing a socket that still holds unread
        data makes the operating system reset the connection, and the client then never sees the explanation."""
        try:
            self.connection.shutdown(socket.SHUT_WR)
            deadline, left = time.monotonic() + LINGER_SECONDS, LINGER_BYTES
            while left > 0 and (remaining := deadline - time.monotonic()) > 0:
                self.connection.settimeout(remaining)
                chunk = self.connection.recv(1 << 16)
                if not chunk:
                    break
                left -= len(chunk)
        except OSError:
            pass  # the client went away: nothing left to protect


class _Server(ThreadingHTTPServer):
    allow_reuse_address = False  # on Windows this flag would let another program share the port
    daemon_threads = True
    app: _App


def lan_address() -> str:
    """This computer's address on the local network (for --share); falls back to the host name."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # no packet is sent: this only selects the outgoing interface
            return s.getsockname()[0]
    except OSError:
        return socket.gethostname()


def start(port: int = 8501, *, share: bool = False, workspace=None) -> tuple[_Server, _App]:
    """Bind the first free port from ``port`` on and return the server with its app state (not yet serving)."""
    host = "0.0.0.0" if share else "127.0.0.1"
    for p in range(port, port + 20):
        try:
            server = _Server((host, p), _Handler)
        except OSError:
            continue
        app = _App(share, p, workspace)
        app.server, server.app = server, app
        return server, app
    raise OSError(f"No free port near {port}.")


def run(port: int = 8501, *, open_browser: bool = True, share: bool = False) -> int:
    """Start the app and block until it is stopped. Returns a process exit code."""
    if not config.ensure_data_dir():
        print(tr("Note: the usual data folder cannot be written to, so {folder} is used for this session.", folder=config.DATA_DIR))
    try:
        server, app = start(port, share=share)
    except OSError:
        print(tr("No free port was found near {port}. Close other copies of the program and try again.", port=port))
        return 1
    app.warm_up()
    url = f"http://{lan_address() if share else '127.0.0.1'}:{server.server_address[1]}/?t={app.token}"
    print(f"INSTAT Explorer {__version__}\n\n  " + tr("Open this address in your browser if it does not open by itself:") + f"\n  {url}\n")
    print("  " + tr("Keep this window open while you work. Close it (or press Ctrl+C) to stop the program."))
    if share:
        print("\n  " + tr("Sharing is ON: anyone on this network who has the address above can use the program."))
    if open_browser:
        threading.Timer(0.3, webbrowser.open, (url,)).start()
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
