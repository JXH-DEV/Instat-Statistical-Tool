"""The web version's entry point: the page's requests answered in-process, as they are in the browser (Pyodide), without a server."""

from __future__ import annotations

import io
import json
import zipfile
from urllib.parse import quote

import pytest

from instatkit import demo
from instatkit.web import embedded


@pytest.fixture(autouse=True)
def fresh_program(monkeypatch):
    monkeypatch.setattr(embedded, "_app", None)  # every test starts with no open files


def call(method: str, target: str, body: bytes | dict | None = None, **headers: str):
    if isinstance(body, dict):
        body = json.dumps(body).encode()
    status, ctype, reply_headers, data = embedded.handle(method, target, headers, body or b"")
    return status, ctype, reply_headers, data


def api(method: str, target: str, body=None, **headers):
    status, ctype, _h, data = call(method, target, body, **headers)
    assert "json" in ctype, ctype
    return status, json.loads(data)


def test_a_demo_is_opened_and_read_like_on_a_server():
    status, opened = api("POST", "/api/demo", {"name": "cpi"})
    assert status == 200 and opened["key"]
    status, state = api("GET", "/api/state")
    assert [f["key"] for f in state["files"]] == [opened["key"]] and state["files"][0]["ok"]
    status, summary = api("GET", f"/api/table?key={opened['key']}&i=0")
    assert status == 200 and summary["title"] and summary["tiles"]


def test_an_uploaded_file_is_read_and_its_name_comes_from_the_header_whatever_its_case():
    data = demo.DEMOS["wages"][2]()
    status, opened = api("POST", "/api/upload", data, **{"X-Filename": quote("paga e vitit.xlsx"), "Content-Type": "application/octet-stream"})
    assert status == 200
    _s, state = api("GET", "/api/state")
    assert state["files"][0]["label"].startswith("paga e vitit") or "paga e vitit" in json.dumps(state["files"][0], ensure_ascii=False)
    status, opened_again = api("POST", "/api/upload", data, **{"x-filename": "other.xlsx"})
    assert status == 200 and opened_again["key"]


@pytest.mark.parametrize(("kind", "signature"), [("report", b"<!doctype"), ("xlsx", b"PK"), ("tidy", b"\xef\xbb\xbf"), ("zip", b"PK"), ("sqlite", b"SQLite format 3\x00")])
def test_exports_are_files_with_a_name_and_the_right_content(kind, signature):
    _s, opened = api("POST", "/api/demo", {"name": "gdp"})
    status, ctype, headers, data = call("GET", f"/export?key={opened['key']}&i=0&kind={kind}")
    assert status == 200 and data.lower().startswith(signature.lower())
    assert 'attachment; filename="' in headers["Content-Disposition"] and "json" not in ctype


def test_the_bundle_zip_holds_the_sqlite_file_too():
    _s, opened = api("POST", "/api/demo", {"name": "cpi"})
    _status, _c, _h, data = call("GET", f"/export?key={opened['key']}&i=0&kind=zip")
    assert {"report.html", "workbook.xlsx", "data.sqlite"} <= set(zipfile.ZipFile(io.BytesIO(data)).namelist())


def test_the_page_language_is_the_one_sent_with_the_request():
    _s, english = api("GET", "/api/lang", **{"x-language": "en"})
    _s, albanian = api("GET", "/api/lang", **{"x-language": "sq"})
    assert english["language"] == "en" and albanian["language"] == "sq" and albanian["catalog"]["Upload"] == "Ngarko"
    _s, shown = api("POST", "/api/demo", {"name": "nope"}, **{"x-language": "sq"})
    assert shown["error"] and shown["error"] != api("POST", "/api/demo", {"name": "nope"}, **{"x-language": "en"})[1]["error"]


@pytest.mark.parametrize(("path", "body"), [("/api/listing", {"url": "https://www.instat.gov.al/en/themes/prices/"}), ("/api/load", {"url": "https://www.instat.gov.al/media/1/a.xlsx"})])
def test_nothing_is_downloaded_from_instat_in_the_browser_and_the_page_is_told_why(path, body):
    status, reply = api("POST", path, body)
    assert status == 501 and "upload it here" in reply["error"]
    _s, albanian = api("POST", path, body, **{"x-language": "sq"})
    assert "ngarkoje këtu" in albanian["error"]


def test_the_about_box_has_no_data_folder_and_nothing_to_stop():
    status, about = api("GET", "/api/about")
    assert status == 200 and about["web"] is True and about["shared"] is True and about["data_dir"] is None


def test_the_program_cannot_be_stopped_from_the_page():
    status, reply = api("POST", "/api/quit", {})
    assert status == 403 and reply["error"]


def test_unknown_addresses_and_oversize_requests_are_refused_with_a_message():
    assert api("GET", "/api/nothing")[0] == 404
    status, reply = api("POST", "/api/demo", b"x" * ((1 << 20) + 1))
    assert status == 413 and "limit" in reply["error"]


def test_a_broken_request_is_a_message_not_an_exception():
    status, reply = api("POST", "/api/demo", b"{not json")
    assert status == 400 and reply["error"]
    status, reply = api("GET", "/api/table?key=missing&i=0")
    assert status == 404 and "no longer open" in reply["error"]


def test_a_failure_inside_the_program_is_reported_in_one_sentence(monkeypatch, capsys):
    def boom(*_args):
        raise RuntimeError("internal detail")

    monkeypatch.setitem(embedded.app().routes, ("GET", "/api/state"), (1024, boom))
    status, reply = api("GET", "/api/state")
    assert status == 500 and "internal detail" not in reply["error"]
    assert "internal detail" in capsys.readouterr().err, "the detail goes to the console"
