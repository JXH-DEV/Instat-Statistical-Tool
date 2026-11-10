"""``instat doctor`` when things are wrong: each check has to fail on its own, say which one it was, and set the exit code. The healthy
case and the unwritable data folder are in test_cli.py."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from instatkit import config, doctor
from instatkit.sources import fetch


def run(capsys, *, online=False):
    code = doctor.run_checks(online=online)
    return code, capsys.readouterr().out


@pytest.fixture(autouse=True)
def folder_is_fine(monkeypatch):
    monkeypatch.setattr(config, "ensure_data_dir", lambda: True)


def test_a_32_bit_or_old_python_is_reported_with_its_version(capsys, monkeypatch):
    old = SimpleNamespace(version_info=(3, 10, 4), maxsize=2**63 - 1, version="3.10.4 (main)")
    monkeypatch.setattr(doctor, "sys", old)
    code, out = run(capsys)
    assert code == 1
    assert "[!!] 64-bit Python 3.11 or newer: RuntimeError: Python 3.10.4, 64-bit" in out
    small = SimpleNamespace(version_info=sys.version_info, maxsize=2**31 - 1, version="3.14.0 (main)")
    monkeypatch.setattr(doctor, "sys", small)
    code, out = run(capsys)
    assert code == 1 and "Python 3.14.0, 32-bit" in out


def test_a_missing_library_fails_that_check_and_nothing_else(capsys, monkeypatch):
    monkeypatch.setitem(sys.modules, "xlrd", None)                 # makes "import xlrd" fail
    code, out = run(capsys)
    assert code == 1
    assert "[!!] Libraries: ModuleNotFoundError" in out
    assert out.count("[ok]") == 4 and out.count("[!!]") == 1
    assert "1 check failed. Please send this output to whoever looks after the installation." in out


def test_a_demo_that_cannot_be_read_names_the_errors(capsys, monkeypatch):
    import instatkit.pipeline as pipeline

    monkeypatch.setattr(pipeline, "process_bytes", lambda *a, **k: SimpleNamespace(ok=False, errors=["no sheet", "no data"]))
    code, out = run(capsys)
    assert code == 1 and "[!!] Reading, analysing and exporting a file: RuntimeError: no sheet; no data" in out
    monkeypatch.setattr(pipeline, "process_bytes", lambda *a, **k: SimpleNamespace(ok=False, errors=[]))
    assert "RuntimeError: the demo file could not be read" in run(capsys)[1]


class ScriptedConnection:
    """Answers the three requests of the server check with the statuses in ``script`` (path -> (status, body))."""

    script: dict = {}

    def __init__(self, host, port, timeout):
        self.path = ""

    def request(self, method, path, headers=None):
        self.path = path

    def getresponse(self):
        status, body = ScriptedConnection.script[self.path]
        return SimpleNamespace(status=status, read=lambda: body)

    def close(self):
        pass


@pytest.mark.parametrize("script,reason", [
    ({"/health": (500, b""), "/api/state": (403, b""), "/": (200, b"INSTAT Explorer")}, "the health check failed"),
    ({"/health": (200, b"ok"), "/api/state": (200, b"{}"), "/": (200, b"INSTAT Explorer")}, "the access token is not enforced"),
    ({"/health": (200, b"ok"), "/api/state": (403, b""), "/": (404, b"")}, "the start page is not served"),
    ({"/health": (200, b"ok"), "/api/state": (403, b""), "/": (200, b"some other site")}, "the start page is not served"),
])
def test_each_failure_of_the_server_check_has_its_own_reason(capsys, monkeypatch, script, reason):
    monkeypatch.setattr(doctor.http.client, "HTTPConnection", ScriptedConnection)
    ScriptedConnection.script = script
    code, out = run(capsys)
    assert code == 1 and f"[!!] The web server of the app: RuntimeError: {reason}" in out


def test_the_server_check_stops_the_server_it_started(monkeypatch):
    import threading

    before = {t.ident for t in threading.enumerate()}
    assert "access token enforced" in doctor._server()
    leftover = [t for t in threading.enumerate() if t.ident not in before and t.is_alive() and not t.daemon]
    assert leftover == []


def test_the_online_check_is_only_made_when_asked_for(capsys, monkeypatch):
    class Fetcher:
        def head(self, url):
            return SimpleNamespace(ok=True, status=200)

    monkeypatch.setattr(fetch, "Fetcher", Fetcher)
    assert "Internet access to INSTAT" not in run(capsys)[1]
    code, out = run(capsys, online=True)
    assert code == 0 and "[ok] Internet access to INSTAT: instat.gov.al can be reached" in out and out.count("[ok]") == 6


def test_the_online_check_reports_the_status_the_site_answered_with(capsys, monkeypatch):
    class Fetcher:
        def head(self, url):
            return SimpleNamespace(ok=False, status=503)

    monkeypatch.setattr(fetch, "Fetcher", Fetcher)
    code, out = run(capsys, online=True)
    assert code == 1 and "[!!] Internet access to INSTAT: RuntimeError: instat.gov.al answered with HTTP 503" in out


def test_several_failures_are_counted_in_the_plural(capsys, monkeypatch):
    monkeypatch.setitem(sys.modules, "xlrd", None)
    monkeypatch.setattr(doctor.http.client, "HTTPConnection", ScriptedConnection)
    ScriptedConnection.script = {"/health": (500, b""), "/api/state": (403, b""), "/": (200, b"")}
    code, out = run(capsys)
    assert code == 1 and "2 checks failed. Please send this output to whoever looks after the installation." in out


def test_a_temporary_folder_is_mentioned_beside_the_data_folder_check(capsys, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ensure_data_dir", lambda: False)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    code, out = run(capsys)
    assert code == 0 and f"{tmp_path} (temporary: the usual folder cannot be written to)" in out
