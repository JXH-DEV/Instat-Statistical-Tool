"""Getting files from instat.gov.al, without a network: the fetcher takes a transport, a clock and a sleep, so every answer a server
can give (and every way it can misbehave) is played back from memory. What matters most: the program never connects to a private or
local address, never believes a page that is not a spreadsheet, never keeps more than its limits, and never writes outside its folder."""

from __future__ import annotations

import ipaddress
import socket
import urllib.request
from collections.abc import Callable
from pathlib import Path

import pytest

from instatkit import config, store
from instatkit.export.xlsx_writer import Workbook as Writer
from instatkit.sources import fetch
from instatkit.sources.fetch import Fetcher, FetchError, Response, is_instat_host, validate_url
from instatkit.sources.page_links import filename_of, normalize_url, parse_page
from instatkit.sources.resolve import looks_like_url, resolve
from instatkit.sources.search import search_topics
from instatkit.sources.topic_index import THEMES

PAGE = "https://www.instat.gov.al/en/themes/prices/"
FILE = "https://www.instat.gov.al/media/101/cpi-2025.xlsx"


# test doubles
class Body:
    """What a connection returns: read in chunks, optionally dropping half way."""

    def __init__(self, data: bytes, drop_after: int | None = None) -> None:
        self.data, self.drop_after, self.pos, self.closed, self.reads = data, drop_after, 0, False, 0

    def read(self, size: int = -1) -> bytes:
        self.reads += 1
        if self.drop_after is not None and self.pos >= self.drop_after:
            raise ConnectionResetError("reset by peer")
        end = len(self.data) if size < 0 else self.pos + size
        if self.drop_after is not None:
            end = min(end, self.drop_after)
        chunk, self.pos = self.data[self.pos:end], min(end, len(self.data))
        return chunk

    def close(self) -> None:
        self.closed = True


def reply(status: int = 200, body: bytes = b"", url: str = FILE, *, drop_after: int | None = None, **headers: str) -> Response:
    lowered = {k.replace("_", "-").lower(): v for k, v in headers.items()}
    return Response(status, lowered, url, Body(body, drop_after))


class Script:
    """A transport that plays back a list of answers (or errors to raise), one per request, and remembers the requests."""

    def __init__(self, *answers: Response | Exception | Callable[[], Response]) -> None:
        self.answers, self.calls = list(answers), []

    def __call__(self, method: str, url: str, headers: dict[str, str]) -> Response:
        self.calls.append((method, url, dict(headers)))
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return answer() if callable(answer) else answer


def xlsx(value: float = 1.5) -> bytes:
    book = Writer()
    sheet = book.active
    for r, row in enumerate([["A table"], [], ["Region", " 01-23", " 02-23"], ["Tirana", value, 2.5], ["Durrës", 4, 5]], 1):
        for c, v in enumerate(row, 1):
            sheet.cell(r, c, v)
    return book.save()


@pytest.fixture
def sleeps() -> list[float]:
    return []


@pytest.fixture
def make(tmp_path, sleeps):
    """``make(*answers)`` -> ``(fetcher, script)`` with its own cache folder and database and no waiting between requests."""

    def build(*answers, **kwargs) -> tuple[Fetcher, Script]:
        script = Script(*answers)
        fetcher = Fetcher(script, db_path=tmp_path / "d.sqlite", raw_dir=tmp_path / "raw", min_interval=kwargs.pop("min_interval", 0.0),
                          sleep=sleeps.append, clock=kwargs.pop("clock", lambda: 0.0), **kwargs)
        return fetcher, script

    return build


@pytest.fixture
def dns(monkeypatch):
    """A name server that knows a few hosts. Addresses written as numbers answer themselves, as the real one does."""
    table = {"internal.example": "10.1.2.3", "public.example": "93.184.216.34", "instat.gov.al.evil.example": "10.9.9.9",
             "notinstat.gov.al": "192.168.0.7", "mixed.example": "93.184.216.34,127.0.0.1", "v6.example": "fe80::1"}

    def getaddrinfo(host, port, *args, **kwargs):
        try:
            ipaddress.ip_address(host)
            addresses = [host]
        except ValueError:
            if host not in table:
                raise socket.gaierror(f"unknown host {host}") from None
            addresses = table[host].split(",")
        return [(socket.AF_INET6 if ":" in a else socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, 0)) for a in addresses]

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)


# addresses
@pytest.mark.parametrize("url", ["ftp://www.instat.gov.al/x.xlsx", "file:///etc/passwd", "javascript:alert(1)", "//www.instat.gov.al/x", "data:text/plain,hi"])
def test_only_web_addresses_are_followed(url, dns):
    with pytest.raises(FetchError, match="http and https"):
        validate_url(url)


def test_an_address_without_a_host_is_refused(dns):
    with pytest.raises(FetchError, match="no host name"):
        validate_url("http:///x.xlsx")


def test_a_malformed_address_is_refused_not_crashed_on(dns):
    with pytest.raises(FetchError, match="not a valid web address"):
        validate_url("http://[::1/x.xlsx")


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/x.xlsx", "http://127.1.2.3:8080/x", "http://[::1]/x", "http://10.0.0.5/x", "http://192.168.1.1/x", "http://172.16.0.9/x",
    "http://169.254.169.254/latest/meta-data/", "http://0.0.0.0/x", "http://224.0.0.1/x", "http://[fe80::1]/x",
    "http://internal.example/x.xlsx",            # a name that points at a private address
    "http://mixed.example/x.xlsx",               # one good address is not enough when another is local
    "http://v6.example/x.xlsx",                  # link-local IPv6
    "https://instat.gov.al.evil.example/x.xlsx",  # starts like INSTAT's address but is not
    "https://notinstat.gov.al/x.xlsx",           # ends like INSTAT's address but is not
    "https://www.instat.gov.al@internal.example/x.xlsx",  # the part before @ is a user name, not the host
])
def test_local_and_private_addresses_are_refused(url, dns):
    with pytest.raises(FetchError, match="local or private"):
        validate_url(url)


def test_an_unknown_host_says_so(dns):
    with pytest.raises(FetchError, match="could not be found"):
        validate_url("https://no-such-host.example/x.xlsx")


def test_instat_itself_needs_no_name_lookup(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("the name server must not be asked about instat.gov.al")

    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    assert validate_url("https://www.instat.gov.al/media/1/a.xlsx") == "https://www.instat.gov.al/media/1/a.xlsx"
    assert validate_url("HTTPS://INSTAT.GOV.AL./media/1/a.xlsx")  # capitals and a trailing dot are the same host


def test_other_public_hosts_are_allowed(dns):
    assert validate_url("https://public.example/data.xlsx") == "https://public.example/data.xlsx"


def test_instat_host_matching_is_exact_not_a_substring():
    assert is_instat_host("instat.gov.al") and is_instat_host("www.instat.gov.al") and is_instat_host("DATABAZA.INSTAT.GOV.AL.")
    assert not any(is_instat_host(h) for h in ("notinstat.gov.al", "instat.gov.al.evil.example", "instat.gov.alx", "gov.al", "", None))


def test_addresses_are_normalised_and_lose_their_fragment(dns):
    out = validate_url("https://www.instat.gov.al/media/9/Çmimet e konsumit.xlsx#top")
    assert out == "https://www.instat.gov.al/media/9/%C3%87mimet%20e%20konsumit.xlsx"


# redirects
def test_redirect_to_a_private_address_is_stopped(dns):
    handler = fetch._Redirects()
    request = urllib.request.Request(FILE)
    with pytest.raises(FetchError, match="local or private"):
        handler.redirect_request(request, None, 302, "Found", {}, "http://10.0.0.5/secret")
    with pytest.raises(FetchError, match="http and https"):
        handler.redirect_request(request, None, 302, "Found", {}, "file:///etc/passwd")


def test_redirect_within_instat_is_followed(dns):
    follow = fetch._Redirects().redirect_request(urllib.request.Request(FILE), None, 301, "Moved", {}, "/media/102/new.xlsx")
    assert follow is not None and follow.full_url == "https://www.instat.gov.al/media/102/new.xlsx"


def test_the_final_address_of_an_answer_is_checked_again(make, dns):
    fetcher, _ = make(reply(200, b"<html>", url="http://internal.example/leak"))
    with pytest.raises(FetchError, match="local or private"):
        fetcher.get_html(PAGE)


# pages
def test_a_page_is_decoded_with_the_charset_it_declares(make):
    fetcher, script = make(reply(200, "Çmimet ë".encode("windows-1252"), url=PAGE, content_type="text/html; charset=windows-1252"))
    assert fetcher.get_html(PAGE) == "Çmimet ë"
    assert script.calls[0][0] == "GET"


def test_a_page_with_an_unknown_charset_is_still_read(make):
    fetcher, _ = make(reply(200, "Tiranë".encode(), url=PAGE, content_type="text/html; charset=no-such-charset"))
    assert fetcher.get_html(PAGE) == "Tiranë"


def test_error_status_of_a_page_is_raised(make):
    fetcher, script = make(reply(404, b"nope", url=PAGE))
    with pytest.raises(FetchError) as caught:
        fetcher.get_html(PAGE)
    assert caught.value.status == 404 and len(script.calls) == 1, "a dead link is not retried"


def test_a_page_over_the_size_limit_is_refused(make, monkeypatch):
    monkeypatch.setattr(fetch, "_MAX_HTML_BYTES", 100)
    fetcher, _ = make(reply(200, b"x" * 5000, url=PAGE))
    with pytest.raises(FetchError, match="unexpectedly large"):
        fetcher.get_html(PAGE)


def test_the_connection_is_closed_after_every_page(make):
    answer = reply(200, b"<html></html>", url=PAGE)
    fetcher, _ = make(answer)
    fetcher.get_html(PAGE)
    assert answer._fp.closed


# retries and manners
def test_throttling_and_server_errors_are_retried(make, sleeps):
    fetcher, script = make(reply(503, url=PAGE), reply(503, url=PAGE), reply(200, b"ok", url=PAGE))
    assert fetcher.get_html(PAGE) == "ok"
    assert len(script.calls) == 3 and sleeps == [0.6, 1.2]


def test_the_server_can_say_how_long_to_wait_but_not_for_ever(make, sleeps):
    fetcher, _ = make(reply(429, url=PAGE, retry_after="7"), reply(429, url=PAGE, retry_after="3600"), reply(200, b"ok", url=PAGE))
    fetcher.get_html(PAGE)
    assert sleeps == [7.0, 30.0]


def test_a_server_that_keeps_failing_gives_up_after_four_tries(make):
    fetcher, script = make(reply(500, url=PAGE))
    with pytest.raises(FetchError) as caught:
        fetcher.get_html(PAGE)
    assert caught.value.status == 500 and len(script.calls) == 4


def test_a_network_hiccup_is_retried_but_a_refusal_is_not(make, sleeps):
    fetcher, script = make(FetchError("dropped", retryable=True), reply(200, b"ok", url=PAGE))
    assert fetcher.get_html(PAGE) == "ok" and len(script.calls) == 2

    fetcher, script = make(FetchError("refused", retryable=False))
    with pytest.raises(FetchError, match="refused"):
        fetcher.get_html(PAGE)
    assert len(script.calls) == 1


def test_a_hiccup_that_never_ends_is_raised_after_the_last_try(make):
    fetcher, script = make(FetchError("dropped", retryable=True))
    with pytest.raises(FetchError, match="dropped"):
        fetcher.get_html(PAGE)
    assert len(script.calls) == 4


def test_requests_are_spaced_out_per_host(make, sleeps, dns):
    now = [0.0]
    fetcher, _ = make(lambda: reply(200, b"ok", url=PAGE), min_interval=1.0, clock=lambda: now[0])
    fetcher.get_html(PAGE)
    assert sleeps == []
    fetcher.get_html(PAGE)  # no time has passed: wait the whole interval
    assert sleeps == [1.0]
    now[0] += 0.25
    fetcher.get_html(PAGE)  # a quarter of it has passed since the last request ... which was at 0.0, so 0.75 is left
    assert sleeps[-1] == pytest.approx(0.75)
    sleeps.clear()
    fetcher.get_html(PAGE.replace("www.instat.gov.al", "databaza.instat.gov.al"))
    assert sleeps == []


def test_offline_mode_never_touches_the_network(make):
    fetcher, script = make(reply(200, b"x"), offline=True)
    with pytest.raises(FetchError, match="Offline"):
        fetcher.get_html(PAGE)
    with pytest.raises(FetchError, match="has not been downloaded"):
        fetcher.download(FILE)
    assert script.calls == []


# head
def test_head_reports_size_and_date_without_downloading(make):
    fetcher, script = make(reply(200, url=FILE, content_length="1234", last_modified="Tue, 07 Oct 2025 08:00:00 GMT"))
    info = fetcher.head(FILE)
    assert (info.ok, info.size, info.last_modified) == (True, 1234, "Tue, 07 Oct 2025 08:00:00 GMT")
    assert [c[0] for c in script.calls] == ["HEAD"]


def test_a_server_that_refuses_head_is_asked_for_one_byte_instead(make):
    fetcher, script = make(reply(405, url=FILE), reply(206, b"P", url=FILE, content_range="bytes 0-0/98765"))
    info = fetcher.head(FILE)
    assert info.size == 98765 and info.ok
    assert script.calls[1][0] == "GET" and script.calls[1][2]["Range"] == "bytes=0-0"


def test_head_of_a_dead_link_is_not_ok(make):
    fetcher, _ = make(reply(404, url=FILE))
    assert fetcher.head(FILE).ok is False


# download
def test_a_download_is_checked_stored_by_content_and_remembered(make, tmp_path):
    data = xlsx()
    fetcher, _ = make(reply(200, data, content_length=str(len(data)), etag='"v1"', last_modified="Tue, 07 Oct 2025 08:00:00 GMT"))
    got = fetcher.download(FILE)
    assert (got.fmt, got.size, got.filename, got.from_cache) == ("xlsx", len(data), "cpi-2025.xlsx", False)
    assert got.path == tmp_path / "raw" / got.sha256[:2] / f"{got.sha256}.xlsx" and got.path.read_bytes() == data
    with store.connect(tmp_path / "d.sqlite") as conn:
        row = store.get_download(conn, FILE)
    assert row["sha256"] == got.sha256 and row["etag"] == '"v1"' and row["status"] == 200


def test_the_second_download_asks_whether_the_file_changed(make):
    data = xlsx()
    fetcher, script = make(reply(200, data, etag='"v1"', last_modified="Tue, 07 Oct 2025 08:00:00 GMT"), reply(304, url=FILE))
    first = fetcher.download(FILE)
    again = fetcher.download(FILE)
    assert script.calls[1][2]["If-None-Match"] == '"v1"' and script.calls[1][2]["If-Modified-Since"] == "Tue, 07 Oct 2025 08:00:00 GMT"
    assert again.from_cache and again.data == data and again.sha256 == first.sha256


def test_changed_file_replaces_the_cached_one(make):
    old, new = xlsx(1.5), xlsx(99.0)
    fetcher, _ = make(reply(200, old), reply(200, old), reply(200, new))
    first = fetcher.download(FILE)
    same = fetcher.download(FILE)
    changed = fetcher.download(FILE)
    assert same.from_cache and same.sha256 == first.sha256
    assert not changed.from_cache and changed.sha256 != first.sha256 and changed.data == new
    assert first.path != changed.path and first.path.exists(), "the old copy is kept: it is named by its content"


def test_force_downloads_again_without_asking_whether_it_changed(make):
    fetcher, script = make(lambda: reply(200, xlsx(), etag='"v1"'))  # a fresh answer each time: a body can be read only once
    fetcher.download(FILE)
    fetcher.download(FILE, force=True)
    assert "If-None-Match" not in script.calls[1][2]


def test_a_dead_link_says_it_is_broken_on_instats_side(make):
    fetcher, _ = make(reply(404, url=FILE))
    with pytest.raises(FetchError, match="broken on INSTAT") as caught:
        fetcher.download(FILE)
    assert caught.value.status == 404


def test_an_unexpected_status_is_reported_with_its_number(make):
    fetcher, _ = make(reply(403, url=FILE))
    with pytest.raises(FetchError, match="HTTP 403"):
        fetcher.download(FILE)


def test_an_error_page_served_as_a_file_is_not_believed_or_kept(make, tmp_path):
    fetcher, _ = make(reply(200, b"<!DOCTYPE html><html><body>Service temporarily unavailable</body></html>", content_type="text/html"))
    with pytest.raises(FetchError):
        fetcher.download(FILE)
    assert not (tmp_path / "raw").exists() or not any((tmp_path / "raw").rglob("*.*"))
    with store.connect(tmp_path / "d.sqlite") as conn:
        assert store.get_download(conn, FILE) is None


def test_a_file_that_says_it_is_too_big_is_not_even_read(make, monkeypatch):
    monkeypatch.setattr(config, "MAX_DOWNLOAD_BYTES", 1000)
    answer = reply(200, b"x" * 5000, content_length="5000")
    fetcher, _ = make(answer)
    with pytest.raises(FetchError, match="over the limit"):
        fetcher.download(FILE)
    assert answer._fp.reads == 0 and answer._fp.closed


def test_a_file_that_lies_about_its_size_is_cut_off_at_the_limit(make, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "MAX_DOWNLOAD_BYTES", 1000)
    answer = reply(200, b"x" * 50_000)  # no Content-Length, or a false one
    fetcher, _ = make(answer)
    with pytest.raises(FetchError, match="over the limit"):
        fetcher.download(FILE)
    assert answer._fp.pos <= 1000 + fetch._CHUNK, "it stops reading soon after the limit instead of taking everything"
    assert not (tmp_path / "raw").exists()


def test_a_connection_that_drops_half_way_leaves_nothing_behind(make, tmp_path):
    data = xlsx()
    fetcher, _ = make(reply(200, data, drop_after=len(data) // 2))
    with pytest.raises(FetchError, match="connection was lost") as caught:
        fetcher.download(FILE)
    assert caught.value.retryable
    assert not (tmp_path / "raw").exists()
    with store.connect(tmp_path / "d.sqlite") as conn:
        assert store.get_download(conn, FILE) is None


def test_offline_download_returns_what_was_fetched_before(make):
    data = xlsx()
    online, _ = make(reply(200, data))
    online.download(FILE)
    offline = Fetcher(Script(), db_path=online.db_path, raw_dir=online.raw_dir, offline=True)
    got = offline.download(FILE)
    assert got.from_cache and got.data == data


def test_manifest_cannot_point_outside_the_cache(make, tmp_path):
    secret = tmp_path / "secret.xlsx"
    secret.write_bytes(xlsx(7.0))
    fetcher, _ = make(reply(200, xlsx()))
    with store.connect(fetcher.db_path) as conn:  # a tampered manifest points at a file elsewhere on the computer
        store.record_download(conn, url=FILE, sha256="0" * 64, path=str(secret), size=1, filename="secret.xlsx", status=200)
    offline = Fetcher(Script(), db_path=fetcher.db_path, raw_dir=fetcher.raw_dir, offline=True)
    with pytest.raises(FetchError, match="has not been downloaded"):
        offline.download(FILE)


@pytest.mark.parametrize(("header", "expected"), [
    ('attachment; filename="report.xlsx"', "report.xlsx"),
    ("attachment; filename=report.xlsx; size=5", "report.xlsx"),
    ('attachment; filename="../../evil.xlsx"', "evil.xlsx"),
    ('attachment; filename="..\\..\\evil.xlsx"', "evil.xlsx"),
    ("attachment; filename*=UTF-8''N%C3%AB%20vit.xlsx", "Në vit.xlsx"),
    ('attachment; filename=".."', "cpi-2025.xlsx"),
    ("attachment", "cpi-2025.xlsx"),
    ("", "cpi-2025.xlsx"),
])
def test_the_file_name_comes_from_the_server_but_is_never_a_path(header, expected):
    assert fetch._filename(reply(200, content_disposition=header), FILE) == expected


def test_a_file_without_a_name_in_the_address_gets_a_default():
    assert fetch._filename(reply(200), "https://www.instat.gov.al/download/") == "download.xlsx"


def test_files_are_stored_with_a_harmless_extension(make, tmp_path):
    fetcher, _ = make(reply(200, xlsx(), content_disposition='attachment; filename="x.xlsx;rm -rf"'))
    got = fetcher.download(FILE)
    assert got.path.suffix == ".bin" and got.path.is_relative_to(tmp_path / "raw")


# page links
LISTING = """<!doctype html><html><head><title>Consumer Price Index - INSTAT</title></head><body>
<nav><h1>Legal Bases</h1></nav>
<h1>Consumer Price Index</h1>
<ul><li><a href="#tab1">Latest</a></li><li><a href="#tab2">Figures</a></li></ul>
<div id="tab1">
  <a href="/media/101/cpi-2025.xlsx">CPI 2025</a><a href="/media/101/cpi-2025.xlsx"></a>
  <a href="/media/105/weights.xlsx"></a><a href="/media/105/weights.xlsx">Weights</a>
</div>
<div id="tab2">
  <a href="/media/102/Çmimet-e-konsumit.xls">Prices</a> <a href="/media/103/report.pdf">Report</a>
  <a href="mailto:info@instat.gov.al">mail</a> <a href="javascript:void(0)">js</a> <a href="#top">top</a>
  <a href="../media/104/data.csv">CSV file</a> <a href="http://[::1/broken.xlsx">broken</a> <a href="/media/106/macro.xlsm">Macro</a>
</div></body></html>"""


def test_a_topic_page_is_read_into_its_files():
    page = parse_page(LISTING, PAGE)
    names = {f.filename: f for f in page.files}
    assert page.title == "Consumer Price Index" and page.n_pdfs == 1
    assert list(names) == ["cpi-2025.xlsx", "weights.xlsx", "Çmimet-e-konsumit.xls", "data.csv", "macro.xlsm"], "in page order, each once"
    assert names["cpi-2025.xlsx"].label == "CPI 2025" and names["cpi-2025.xlsx"].section == "Latest"
    assert names["weights.xlsx"].label == "Weights", "a link with a label wins over its twin without one"
    assert names["Çmimet-e-konsumit.xls"].section == "Figures" and names["Çmimet-e-konsumit.xls"].is_legacy_xls
    assert names["Çmimet-e-konsumit.xls"].url.endswith("/media/102/%C3%87mimet-e-konsumit.xls"), "non-ASCII names are percent-encoded"
    assert names["data.csv"].url == "https://www.instat.gov.al/en/media/104/data.csv" or names["data.csv"].url.endswith("/media/104/data.csv")


def test_links_that_are_not_data_files_are_ignored():
    urls = [f.url for f in parse_page(LISTING, PAGE).files]
    assert not any(u.startswith(("mailto:", "javascript:")) or u.endswith((".pdf", "broken.xlsx")) for u in urls)


def test_a_menu_heading_does_not_become_the_page_title():
    assert parse_page(LISTING, PAGE).title == "Consumer Price Index"
    only_menu = "<html><head><title>Tourism - INSTAT</title></head><body><h1>Legal Bases</h1></body></html>"
    assert parse_page(only_menu, PAGE).title == "Tourism"


def test_a_page_with_no_title_is_named_by_its_address():
    assert parse_page("<p>nothing here</p>", PAGE).title == PAGE


def test_a_link_without_text_is_named_after_its_file():
    page = parse_page('<a href="/media/1/average_wage-2025.xlsx"></a>', PAGE)
    assert page.files[0].label == "Average wage 2025"


def test_broken_html_does_not_stop_the_listing():
    page = parse_page('<div><a href="/media/1/a.xlsx">A<b></a><p><a href="/media/2/b.xlsx">B', PAGE)  # the last link is never closed
    assert [f.filename for f in page.files] == ["a.xlsx", "b.xlsx"]
    assert [f.label for f in page.files] == ["A", "B"]


def test_unclosed_link_before_the_next_still_counts():
    page = parse_page('<a href="/media/1/a.xlsx">First<a href="/media/2/b.xlsx">Second</a>', PAGE)  # a browser closes the first at the second
    assert [(f.filename, f.label) for f in page.files] == [("a.xlsx", "First"), ("b.xlsx", "Second")]


def test_normalize_url_and_filename_of_agree_on_non_ascii_names():
    url = normalize_url("/media/9/Të dhëna.xlsx", PAGE)
    assert url == "https://www.instat.gov.al/media/9/T%C3%AB%20dh%C3%ABna.xlsx" and filename_of(url) == "Të dhëna.xlsx"
    assert normalize_url("a.xlsx#frag", "https://x.example/dir/b.html") == "https://x.example/dir/a.xlsx"


# resolve
def test_empty_input_is_empty():
    assert resolve("").kind == "empty" and resolve("   ").kind == "empty" and resolve(None).kind == "empty"  # type: ignore[arg-type]


def test_words_search_the_topics_and_unknown_words_say_so():
    found = resolve("consumer price index")
    assert found.kind == "topics" and found.hits
    nothing = resolve("zzzqqqxxx")
    assert nothing.kind == "topics" and not nothing.hits and nothing.message


def test_file_link_says_whether_it_is_external():
    own = resolve("https://www.instat.gov.al/media/1/a.xlsx")
    assert (own.kind, own.external, own.url) == ("file", False, "https://www.instat.gov.al/media/1/a.xlsx")
    other = resolve("https://example.org/data.CSV")
    assert (other.kind, other.external) == ("file", True)


def test_an_address_without_https_is_completed():
    assert resolve("instat.gov.al/media/9/a.xls").url == "https://instat.gov.al/media/9/a.xls"
    assert looks_like_url("www.instat.gov.al/x") and looks_like_url("databaza.instat.gov.al") and not looks_like_url("example.org/x")


def test_pxweb_and_documents_are_unsupported():
    assert "PxWeb" in resolve("https://databaza.instat.gov.al/pxweb/en/DST/").message
    assert resolve("https://www.instat.gov.al/media/1/report.pdf").kind == "unsupported"
    other = resolve("https://example.org/page")
    assert other.kind == "unsupported" and other.external and "Excel" in other.message


def test_topic_theme_and_other_pages_are_told_apart():
    topic_url = search_topics("consumer price index")[0].topic.url
    assert resolve(topic_url).kind == "topic" and resolve(topic_url).topic.url == topic_url
    theme = next(iter(THEMES))
    themed = resolve(f"https://www.instat.gov.al/en/themes/{theme}/")
    assert themed.kind == "theme" and themed.topics
    assert resolve("https://www.instat.gov.al/en/about-us/").kind == "page"


def test_a_malformed_address_is_unsupported_not_a_crash():
    res = resolve("http://[::1/x")
    assert res.kind == "unsupported" and "not a valid web address" in res.message


# store
def test_the_manifest_remembers_downloads_across_connections(tmp_path):
    path = tmp_path / "deep" / "er" / "m.sqlite"
    with store.connect(path) as conn:
        store.record_download(conn, url=FILE, sha256="a" * 64, path="p", size=3, etag="e1", status=200, filename="f.xlsx")
        store.record_download(conn, url=FILE, sha256="b" * 64, path="p2", size=4, etag="e2", status=200, filename="f.xlsx")  # replaces
    with store.connect(path) as conn:
        row = store.get_download(conn, FILE)
        assert (row["sha256"], row["etag"], row["size"]) == ("b" * 64, "e2", 4)
        assert store.get_download(conn, "https://www.instat.gov.al/other.xlsx") is None


def test_manifest_failure_is_rolled_back_and_closed(tmp_path):
    path = tmp_path / "m.sqlite"
    with store.connect(path) as conn:
        store.record_download(conn, url="https://a.example/1.xlsx", sha256="a", path="p", size=1, status=200)
    with pytest.raises(RuntimeError), store.connect(path) as conn:
        store.record_download(conn, url="https://a.example/2.xlsx", sha256="b", path="p", size=1, status=200)
        raise RuntimeError("something went wrong")
    with store.connect(path) as conn:
        assert store.get_download(conn, "https://a.example/1.xlsx") is not None
        assert store.get_download(conn, "https://a.example/2.xlsx") is None
    Path(path).unlink()  # on Windows this fails if a connection was left open


def test_the_manifest_can_live_in_memory():
    with store.connect(":memory:") as conn:
        store.record_download(conn, url="u", sha256="s", path="p", size=1, status=200)
        assert store.get_download(conn, "u")["sha256"] == "s"
