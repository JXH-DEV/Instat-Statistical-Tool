"""A polite, cautious downloader on the standard library (urllib), no requests.

Nothing here runs unless the caller asks for a specific URL. Requests are rate limited per host, retried with
back-off, size-capped, checked for what they really are (HTML error pages served with status 200 are rejected),
cached by content hash, and revalidated with conditional requests (ETag / Last-Modified). Every redirect hop is
validated *before* it is followed, so a link can never lead the program to a local or private address.
"""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import re
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

from .. import config, store
from ..i18n import tr
from ..excel.grid import format_problem, sniff_format
from .page_links import filename_of, normalize_url

_GOOD_FORMATS = {"xlsx", "xls", "spreadsheetml", "csv"}  # INSTAT saves some census tables as Excel 2003 XML named .xls
_RETRY_STATUS = frozenset((429, 500, 502, 503, 504))
_MAX_RETRIES = 3
_MAX_HTML_BYTES = 5 * 1024 * 1024
_CHUNK = 65536
_EXT = re.compile(r"\.[a-z0-9]{1,5}")


class FetchError(Exception):
    def __init__(self, message: str, *, status: int | None = None, url: str | None = None, retryable: bool = False):
        super().__init__(message)
        self.status = status
        self.url = url
        self.retryable = retryable  # a network hiccup worth another try, as opposed to a refusal or a dead link


@dataclass
class RemoteInfo:
    url: str
    status: int
    size: int | None = None
    last_modified: str | None = None

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


@dataclass
class Downloaded:
    url: str
    filename: str
    data: bytes
    sha256: str
    size: int
    fmt: str
    last_modified: str | None = None
    from_cache: bool = False
    path: Path | None = None


class Response:
    """What a transport returns: status, lower-cased headers, the final URL and a body to read in chunks."""

    def __init__(self, status: int, headers: dict[str, str], url: str, fp) -> None:
        self.status, self.headers, self.url, self._fp = status, headers, url, fp

    def chunks(self, size: int = _CHUNK) -> Iterator[bytes]:
        try:
            while chunk := self._fp.read(size):
                yield chunk
        except (OSError, http.client.HTTPException) as exc:  # the connection dropped half way
            raise FetchError(tr("The connection was lost during the download ({error}).", error=type(exc).__name__), url=self.url, retryable=True) from exc

    def close(self) -> None:
        self._fp.close()


Transport = Callable[[str, str, dict[str, str]], Response]


def host_of(url: str) -> str | None:
    """The host name of ``url``, or ``None`` when it is not a well-formed address."""
    try:
        return urlparse(url).hostname
    except ValueError:  # e.g. an unterminated IPv6 literal
        return None


def is_instat_host(host: str | None) -> bool:
    host = (host or "").lower().rstrip(".")
    return any(host == h or host.endswith("." + h) for h in config.INSTAT_HOSTS)


def validate_url(url: str) -> str:
    """Normalise ``url`` and refuse anything that could reach a private network or a non-web scheme."""
    try:
        parts = urlparse(url.strip())
    except ValueError as exc:  # e.g. an unterminated IPv6 literal
        raise FetchError(tr("This is not a valid web address."), url=url) from exc
    if parts.scheme not in ("http", "https"):
        raise FetchError(tr("Only http and https links are supported."), url=url)
    if not parts.hostname:
        raise FetchError(tr("The link has no host name."), url=url)
    if not is_instat_host(parts.hostname):
        try:
            infos = socket.getaddrinfo(parts.hostname, None)
        except socket.gaierror as exc:
            raise FetchError(tr("The host '{host}' could not be found.", host=parts.hostname), url=url) from exc
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
                raise FetchError(tr("Links to local or private network addresses are not allowed."), url=url)
    return normalize_url(url.strip(), url.strip())


class _Redirects(urllib.request.HTTPRedirectHandler):
    max_redirections = 5

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return super().redirect_request(req, fp, code, msg, headers, validate_url(urljoin(req.full_url, newurl)))


_OPENER = urllib.request.build_opener(_Redirects())


def urllib_transport(method: str, url: str, headers: dict[str, str]) -> Response:
    """The real network transport. HTTP error statuses come back as responses; network failures raise FetchError."""
    req = urllib.request.Request(url, method=method, headers={"User-Agent": config.USER_AGENT, **headers})
    try:
        fp = _OPENER.open(req, timeout=config.REQUEST_TIMEOUT)
    except urllib.error.HTTPError as exc:  # 304, 404, 500 ...: an answer, not a failure
        fp = exc
    except urllib.error.URLError as exc:
        raise FetchError(tr("The server could not be reached ({error}).", error=type(exc.reason).__name__), url=url, retryable=True) from exc
    except (OSError, http.client.HTTPException) as exc:  # a reset connection, a garbled reply
        raise FetchError(tr("The server could not be reached ({error}).", error=type(exc).__name__), url=url, retryable=True) from exc
    except ValueError as exc:  # an address urllib cannot use
        raise FetchError(tr("This is not a valid web address."), url=url) from exc
    return Response(fp.status, {k.lower(): v for k, v in fp.headers.items()}, fp.geturl(), fp)


class Fetcher:
    def __init__(self, transport: Transport | None = None, *, db_path: Path | str | None = None, raw_dir: Path | None = None,
                 min_interval: float | None = None, offline: bool = False, sleep=time.sleep, clock=time.monotonic):
        self.transport = transport or urllib_transport
        self.db_path = db_path or config.DB_PATH
        self.raw_dir = Path(raw_dir or config.RAW_DIR)
        self.min_interval = config.MIN_REQUEST_INTERVAL if min_interval is None else min_interval
        self.offline = offline
        self._sleep, self._clock = sleep, clock
        self._last: dict[str, float] = {}

    # politeness
    def _throttle(self, url: str) -> None:
        host = urlparse(url).hostname or ""
        wait = self.min_interval - (self._clock() - self._last.get(host, -1e9))
        if wait > 0:
            self._sleep(wait)
        self._last[host] = self._clock()

    def _request(self, method: str, url: str, headers: dict[str, str] | None = None) -> Response:
        """One request, retried with back-off on throttling and server errors; never reaches a private address."""
        if self.offline:
            raise FetchError(tr("Offline mode: this is not in the local cache."), url=url)
        url = validate_url(url)
        for attempt in range(_MAX_RETRIES + 1):
            self._throttle(url)
            try:
                resp = self.transport(method, url, headers or {})
            except FetchError as exc:
                if not exc.retryable or attempt == _MAX_RETRIES:
                    raise
                self._sleep(0.6 * 2 ** attempt)
                continue
            if resp.status in _RETRY_STATUS and attempt < _MAX_RETRIES:
                retry_after = resp.headers.get("retry-after", "")
                resp.close()
                self._sleep(min(30.0, float(retry_after)) if retry_after.isdigit() else 0.6 * 2 ** attempt)
                continue
            break
        final_host = urlparse(resp.url or url).hostname
        if final_host and not is_instat_host(final_host):
            validate_url(resp.url)  # defence in depth: the redirect handler already checked every hop
        return resp

    # pages
    def get_html(self, url: str) -> str:
        resp = self._request("GET", url)
        try:
            if resp.status != 200:
                raise FetchError(tr("The page answered with HTTP {status}.", status=resp.status), status=resp.status, url=url)
            body = b""
            for chunk in resp.chunks():
                body += chunk
                if len(body) > _MAX_HTML_BYTES:
                    raise FetchError(tr("The page is unexpectedly large."), url=url)
            m = re.search(r"charset=([\w-]+)", resp.headers.get("content-type", ""), re.I)
            try:
                return body.decode(m.group(1) if m else "utf-8", "replace")
            except LookupError:
                return body.decode("utf-8", "replace")
        finally:
            resp.close()

    # file metadata without downloading the file
    def head(self, url: str) -> RemoteInfo:
        resp = self._request("HEAD", url)
        if resp.status in (403, 405, 501):  # some servers refuse HEAD; ask for one byte instead
            resp.close()
            resp = self._request("GET", url, {"Range": "bytes=0-0"})
            size = None
            cr = resp.headers.get("content-range", "")
            if "/" in cr and cr.rsplit("/", 1)[-1].isdigit():
                size = int(cr.rsplit("/", 1)[-1])
        else:
            size = int(resp.headers["content-length"]) if resp.headers.get("content-length", "").isdigit() else None
        h = resp.headers
        resp.close()
        return RemoteInfo(url, resp.status, size, h.get("last-modified"))

    # files
    def download(self, url: str, *, force: bool = False) -> Downloaded:
        url = validate_url(url)
        with store.connect(self.db_path) as conn:
            row = store.get_download(conn, url)
            cached = self._read_cached(row) if row is not None else None
            headers = {}
            if cached is not None and not force:
                if row["etag"]:
                    headers["If-None-Match"] = row["etag"]
                if row["last_modified"]:
                    headers["If-Modified-Since"] = row["last_modified"]
            if self.offline:
                if cached is None:
                    raise FetchError(tr("Offline mode: this file has not been downloaded before."), url=url)
                return cached
            resp = self._request("GET", url, headers)
            try:
                if resp.status == 304 and cached is not None:
                    cached.from_cache = True
                    return cached
                if resp.status == 404:
                    raise FetchError(tr("This link is broken on INSTAT's side (HTTP 404, file not found)."), status=404, url=url)
                if resp.status != 200:
                    raise FetchError(tr("The server answered with HTTP {status}.", status=resp.status), status=resp.status, url=url)
                length = resp.headers.get("content-length", "")
                if length.isdigit() and int(length) > config.MAX_DOWNLOAD_BYTES:
                    raise FetchError(tr("The file is {size} MB, over the limit of {limit} MB.", size=f"{int(length) / 1e6:.0f}", limit=config.MAX_DOWNLOAD_BYTES // 1_000_000), url=url)
                buf = bytearray()
                for chunk in resp.chunks():
                    buf.extend(chunk)
                    if len(buf) > config.MAX_DOWNLOAD_BYTES:
                        raise FetchError(tr("The file is over the limit of {limit} MB.", limit=config.MAX_DOWNLOAD_BYTES // 1_000_000), url=url)
                data = bytes(buf)
                fname = _filename(resp, url)
                fmt = sniff_format(data, fname)
                if fmt not in _GOOD_FORMATS:
                    raise FetchError(format_problem(fmt), url=url)
                sha = hashlib.sha256(data).hexdigest()
                path = self._store(sha, fname, data)
                h = resp.headers
                store.record_download(conn, url=url, sha256=sha, path=str(path), size=len(data), etag=h.get("etag"),
                                      last_modified=h.get("last-modified"), content_type=h.get("content-type"),
                                      fetched_at=store.now_iso(), status=200, filename=fname)
                return Downloaded(url, fname, data, sha, len(data), fmt, h.get("last-modified"),
                                  from_cache=(cached is not None and cached.sha256 == sha), path=path)
            finally:
                resp.close()

    # cache plumbing (cached files are always revalidated with a conditional request, which is cheap)
    def _read_cached(self, row) -> Downloaded | None:
        path = Path(row["path"]) if row["path"] else None
        try:  # only files inside our own cache are ever read back, whatever the database says
            if not path or not path.is_file() or not path.resolve().is_relative_to(self.raw_dir.resolve()):
                return None
        except OSError:
            return None
        data = path.read_bytes()
        fmt = sniff_format(data, row["filename"])
        return Downloaded(row["url"], row["filename"] or path.name, data, row["sha256"], len(data), fmt,
                          row["last_modified"], from_cache=True, path=path)

    def _store(self, sha: str, filename: str, data: bytes) -> Path:
        ext = Path(filename).suffix.lower()
        path = self.raw_dir / sha[:2] / (sha + (ext if _EXT.fullmatch(ext) else ".bin"))
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(data)
        return path


def _filename(resp: Response, url: str) -> str:
    cd = resp.headers.get("content-disposition", "")
    if "filename=" in cd:
        name = cd.split("filename=", 1)[1].strip().strip('"; ')
        if name:
            return Path(name).name  # never a path, whatever the server sent
    return filename_of(url) or "download.xlsx"
