"""The commands that talk to INSTAT (``files``, ``fetch``, ``process <address>``), with the network replaced by stand-ins: what they print,
what goes to stderr and which exit code each failure gives."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from instatkit import cli, demo
from instatkit.sources import fetch, page_links, resolve
from instatkit.sources.fetch import Downloaded, FetchError
from instatkit.sources.page_links import FileLink, PageListing
from instatkit.sources.resolve import Resolution

PAGE = "https://www.instat.gov.al/al/temat/tregu-i-punës/punësimi/"
FILE_URL = "https://www.instat.gov.al/media/1/punesimi.xlsx"


def run(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


class FakeFetcher:
    """Stands in for ``Fetcher``. ``html`` is what a page request answers, an exception to raise, and ``answer`` is what a download
    answers; every request is recorded in ``calls``."""

    html: object = "<html></html>"
    answer: object = None
    calls: list = []

    def get_html(self, url):
        FakeFetcher.calls.append(("html", url))
        if isinstance(FakeFetcher.html, Exception):
            raise FakeFetcher.html
        return FakeFetcher.html

    def download(self, url, force=False):
        FakeFetcher.calls.append(("download", url, force))
        if isinstance(FakeFetcher.answer, Exception):
            raise FakeFetcher.answer
        return FakeFetcher.answer


@pytest.fixture
def network(monkeypatch):
    FakeFetcher.calls, FakeFetcher.html, FakeFetcher.answer = [], "<html></html>", None
    monkeypatch.setattr(fetch, "Fetcher", FakeFetcher)
    monkeypatch.setattr(cli.config, "ensure_data_dir", lambda: True)
    return FakeFetcher


def downloaded(data: bytes, name: str, tmp_path: Path, from_cache: bool = False) -> Downloaded:
    path = tmp_path / name
    path.write_bytes(data)
    return Downloaded(FILE_URL, name, data, hashlib.sha256(data).hexdigest(), len(data), "xlsx", from_cache=from_cache, path=path)


# --- files ---
def test_files_lists_what_a_page_offers(capsys, monkeypatch, network):
    listing = PageListing(PAGE, "Employment", [FileLink(FILE_URL, "Employed persons", ".xlsx", "punesimi.xlsx", "Figures"),
                                              FileLink(FILE_URL + "2", "Other table", ".xls", "tjeter.xls")], n_pdfs=1)
    monkeypatch.setattr(resolve, "resolve", lambda text: Resolution("page", url=PAGE))
    monkeypatch.setattr(page_links, "parse_page", lambda html, url: listing)
    code, out, err = run(capsys, "files", PAGE)
    assert code == 0 and err == ""
    assert out.splitlines()[0] == "Employment: 2 Excel or CSV files, 1 PDF link ignored"
    assert PAGE in out and "  1. [Figures] Employed persons" in out and "  2. [Other] Other table" in out
    assert FILE_URL in out and network.calls == [("html", PAGE)]


def test_files_says_one_file_in_the_singular(capsys, monkeypatch, network):
    monkeypatch.setattr(resolve, "resolve", lambda text: Resolution("topic", url=PAGE))
    monkeypatch.setattr(page_links, "parse_page", lambda html, url: PageListing(PAGE, "Employment", [FileLink(FILE_URL, "A", ".xlsx", "a.xlsx")]))
    assert run(capsys, "files", "employment")[1].splitlines()[0] == "Employment: 1 Excel or CSV file, 0 PDF links ignored"


def test_files_given_a_word_opens_the_best_matching_topic(capsys, monkeypatch, network):
    from instatkit.sources.search import search_topics

    hits = search_topics("employment")
    assert hits
    monkeypatch.setattr(resolve, "resolve", lambda text: Resolution("topics", "employment", hits=hits))
    monkeypatch.setattr(page_links, "parse_page", lambda html, url: PageListing(url, "T", []))
    code, out, _ = run(capsys, "files", "employment")
    assert code == 0 and out.splitlines()[0] == f"Best match: {hits[0].topic.title}"
    assert network.calls == [("html", hits[0].topic.url)]


def test_files_with_no_matching_topic_explains_and_fails(capsys, monkeypatch, network):
    monkeypatch.setattr(resolve, "resolve", lambda text: Resolution("topics", "zzz", message="No INSTAT topic matched."))
    code, out, err = run(capsys, "files", "zzz")
    assert (code, out, err) == (1, "", "No INSTAT topic matched.\n") and network.calls == []


@pytest.mark.parametrize("resolution,expected", [(Resolution("unsupported", message="That is not an INSTAT page."), "That is not an INSTAT page."),
                                                 (Resolution("empty"), "Give a topic word or the address of a topic page of INSTAT."),
                                                 (Resolution("page", url=None), "Give a topic word or the address of a topic page of INSTAT.")])
def test_files_refuses_what_is_not_a_topic_page(capsys, monkeypatch, network, resolution, expected):
    monkeypatch.setattr(resolve, "resolve", lambda text: resolution)
    code, out, err = run(capsys, "files", "x")
    assert (code, out, err.strip()) == (1, "", expected) and network.calls == []


def test_files_reports_a_page_that_cannot_be_opened(capsys, monkeypatch, network):
    monkeypatch.setattr(resolve, "resolve", lambda text: Resolution("page", url=PAGE))
    network.html = FetchError("timed out")
    code, out, err = run(capsys, "files", PAGE)
    assert (code, out, err.strip()) == (2, "", "The page could not be opened: timed out")


# --- fetch ---
def test_fetch_prints_the_name_size_hash_and_place(capsys, network, tmp_path):
    data = b"x" * 1500
    network.answer = downloaded(data, "punesimi.xlsx", tmp_path)
    code, out, err = run(capsys, "fetch", FILE_URL)
    assert code == 0 and err == ""
    assert out.splitlines()[0] == f"punesimi.xlsx  1,500 bytes  sha256 {hashlib.sha256(data).hexdigest()[:12]}…  (downloaded)"
    assert out.splitlines()[1] == f"saved at {tmp_path / 'punesimi.xlsx'}"
    assert network.calls == [("download", FILE_URL, False)]


def test_fetch_says_when_the_file_came_from_the_cache_and_passes_force_on(capsys, network, tmp_path):
    network.answer = downloaded(b"abc", "a.xlsx", tmp_path, from_cache=True)
    code, out, _ = run(capsys, "fetch", FILE_URL, "--force")
    assert code == 0 and "(from the cache)" in out
    assert network.calls == [("download", FILE_URL, True)]


def test_a_failed_download_is_an_error_on_stderr(capsys, network):
    network.answer = FetchError("HTTP 404")
    code, out, err = run(capsys, "fetch", FILE_URL)
    assert (code, out, err.strip()) == (2, "", "The download failed: HTTP 404")


def test_the_messages_are_translated(capsys, network):
    network.answer = FetchError("HTTP 404")
    code, out, err = run(capsys, "--lang", "sq", "fetch", FILE_URL)
    assert code == 2 and out == "" and "The download failed" not in err and "HTTP 404" in err


# --- process an address or a path ---
def test_process_an_address_downloads_and_reads_the_file(capsys, network, tmp_path):
    label, fname, build = demo.DEMOS["cpi"]
    network.answer = downloaded(build(), "cpi.xlsx", tmp_path)
    code, out, err = run(capsys, "process", FILE_URL, "--export", "", "--quiet", "--label", "Prices")
    assert code == 0 and err == "" and "layout confidence" in out
    assert network.calls == [("download", FILE_URL, False)]


def test_process_an_address_that_cannot_be_downloaded_fails_with_code_2(capsys, network):
    network.answer = FetchError("connection reset")
    code, out, err = run(capsys, "process", FILE_URL, "--export", "")
    assert (code, out, err.strip()) == (2, "", "The download failed: connection reset")


def test_process_a_missing_file_names_the_path(capsys, tmp_path):
    missing = tmp_path / "nothing.xlsx"
    code, out, err = run(capsys, "process", str(missing), "--export", "")
    assert code == 2 and out == "" and err.strip() == f"File not found: {missing}"


def test_process_a_file_that_cannot_be_read_says_it_may_be_damaged(capsys, monkeypatch, tmp_path):
    path = tmp_path / "locked.xlsx"
    path.write_bytes(b"x")

    def refuse(self):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "read_bytes", refuse)
    code, out, err = run(capsys, "process", str(path), "--export", "")
    assert code == 2 and out == ""
    assert err.strip() == "The file could not be read (PermissionError: Permission denied); it may be damaged."


def test_process_does_not_export_a_file_that_could_not_be_read(capsys, tmp_path):
    broken = tmp_path / "broken.xlsx"
    broken.write_bytes(b"this is not a workbook")
    out_dir = tmp_path / "out"
    code, out, err = run(capsys, "process", str(broken), "--export", "csv", "--out", str(out_dir))
    assert code == 1 and not out_dir.exists()
    assert err.startswith("! ")
