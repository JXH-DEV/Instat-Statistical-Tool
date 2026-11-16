"""How the server starts and stops, and what it does when something inside it breaks: the start-up messages, a port that cannot be had,
an error inside a handler, a client that disappears in the middle of an upload."""

from __future__ import annotations

import socket
import threading
from types import SimpleNamespace

import pytest

from instatkit import config
from instatkit.web import server as web

from .test_server import _serve


class FakeServer:
    """What ``start`` returns, with a ``serve_forever`` that ends at once (or as a Ctrl+C)."""

    def __init__(self, port=8123, interrupt=False):
        self.server_address = ("127.0.0.1", port)
        self.interrupt, self.closed, self.served = interrupt, False, False

    def serve_forever(self, poll_interval=0.5):
        self.served = True
        if self.interrupt:
            raise KeyboardInterrupt

    def server_close(self):
        self.closed = True


class FakeTimer:
    started: list = []

    def __init__(self, delay, fn, args):
        self.delay, self.fn, self.args = delay, fn, args

    def start(self):
        FakeTimer.started.append((self.delay, self.fn, self.args))


@pytest.fixture
def starts(monkeypatch):
    """``run()`` against a fake server; returns the fake server and the recorded timers."""
    FakeTimer.started = []
    fake = FakeServer(interrupt=True)
    app = SimpleNamespace(token="TOKEN123", warmed=False, warm_up=lambda: setattr(app, "warmed", True))
    monkeypatch.setattr(web, "start", lambda port, share=False: (fake, app))
    monkeypatch.setattr(web.threading, "Timer", FakeTimer)
    monkeypatch.setattr(config, "ensure_data_dir", lambda: True)
    fake.app = app
    return fake


def test_run_prints_the_address_with_the_token_and_ends_quietly_on_ctrl_c(capsys, starts):
    assert web.run(8123) == 0
    out = capsys.readouterr().out
    assert f"INSTAT Explorer {web.__version__}" in out
    assert "http://127.0.0.1:8123/?t=TOKEN123" in out
    assert "Keep this window open while you work." in out
    assert "Sharing is ON" not in out
    assert starts.served and starts.closed and starts.app.warmed


def test_run_opens_the_browser_a_moment_after_starting_unless_told_not_to(starts):
    web.run(8123)
    [(delay, fn, args)] = FakeTimer.started
    assert 0 < delay < 1 and fn is web.webbrowser.open and args == ("http://127.0.0.1:8123/?t=TOKEN123",)
    FakeTimer.started.clear()
    web.run(8123, open_browser=False)
    assert FakeTimer.started == []


def test_run_in_shared_mode_gives_the_network_address_and_a_warning(capsys, monkeypatch, starts):
    monkeypatch.setattr(web, "lan_address", lambda: "192.168.1.20")
    web.run(8123, share=True, open_browser=False)
    out = capsys.readouterr().out
    assert "http://192.168.1.20:8123/?t=TOKEN123" in out
    assert "Sharing is ON: anyone on this network who has the address above can use the program." in out


def test_run_says_so_when_it_has_to_use_a_temporary_data_folder(capsys, monkeypatch, starts):
    monkeypatch.setattr(config, "ensure_data_dir", lambda: False)
    web.run(8123, open_browser=False)
    assert "Note: the usual data folder cannot be written to, so " in capsys.readouterr().out


def test_run_gives_up_with_code_1_when_no_port_is_free(capsys, monkeypatch):
    def refuse(port, share=False):
        raise OSError("No free port near 8501.")

    monkeypatch.setattr(web, "start", refuse)
    monkeypatch.setattr(config, "ensure_data_dir", lambda: True)
    assert web.run(8501) == 1
    assert "No free port was found near 8501. Close other copies of the program and try again." in capsys.readouterr().out


def test_the_server_is_closed_even_when_it_stops_on_an_error(monkeypatch, starts):
    def explode(poll_interval=0.5):
        raise RuntimeError("boom")

    starts.serve_forever = explode
    with pytest.raises(RuntimeError):
        web.run(8123, open_browser=False)
    assert starts.closed


# --- when something breaks inside ---
def test_an_error_inside_a_handler_is_a_500_without_a_traceback_for_the_browser(capsys, monkeypatch):
    c = _serve()
    try:
        def explode(self, app, method):
            raise RuntimeError("secret internal detail")

        monkeypatch.setattr(web._Handler, "_dispatch", explode)
        status, headers, body = c.get("/api/state")
        assert status == 500
        assert b"Something went wrong inside the program. The details are in its window." in body
        assert b"secret internal detail" not in body and b"Traceback" not in body
        assert "RuntimeError: secret internal detail" in capsys.readouterr().err         # the console has the details
        monkeypatch.undo()
        assert c.get("/health")[0] == 200                                                # and the server goes on
    finally:
        c.server.shutdown()
        c.server.server_close()


def test_a_client_that_vanishes_in_the_middle_of_an_upload_gets_an_explanation_not_a_hang():
    c = _serve()
    try:
        with socket.create_connection(("127.0.0.1", c.port), timeout=10) as s:
            head = (f"POST /api/upload HTTP/1.1\r\nHost: 127.0.0.1:{c.port}\r\nCookie: {c.cookie}\r\nX-Requested-With: instat\r\n"
                    f"Content-Type: application/octet-stream\r\nContent-Length: 5000\r\n\r\n")
            s.sendall(head.encode() + b"only a few bytes")
            s.shutdown(socket.SHUT_WR)
            reply = b""
            while chunk := s.recv(4096):
                reply += chunk
        assert reply.startswith(b"HTTP/1.") and b" 400 " in reply.split(b"\r\n")[0]
        assert b"The upload was interrupted." in reply
    finally:
        c.server.shutdown()
        c.server.server_close()


def test_a_dropped_connection_is_not_an_error_to_print(capsys):
    server = web._Server.__new__(web._Server)
    for error in (ConnectionResetError(), BrokenPipeError(), TimeoutError()):
        try:
            raise error
        except OSError:
            server.handle_error(None, ("127.0.0.1", 1))
    assert capsys.readouterr().err == ""


def test_any_other_error_in_a_request_is_still_printed(capsys):
    server = web._Server.__new__(web._Server)
    try:
        raise ValueError("a real bug")
    except ValueError:
        server.handle_error(None, ("127.0.0.1", 1))
    assert "ValueError: a real bug" in capsys.readouterr().err


def test_the_lan_address_is_the_computers_own_and_falls_back_to_its_name(monkeypatch):
    address = web.lan_address()
    assert address == socket.gethostname() or socket.inet_aton(address)           # four numbers, or the name when there is no network

    class NoNetwork:
        def __enter__(self):
            raise OSError("unreachable")

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(web.socket, "socket", lambda *a, **k: NoNetwork())
    assert web.lan_address() == socket.gethostname()


def test_the_warm_up_loads_the_analysis_code_in_the_background():
    app = web._App(False, 0, None)
    assert app._ws is None
    app.warm_up()
    for t in threading.enumerate():
        if t.name == "warm-up":
            t.join(60)
    assert app._ws is not None
