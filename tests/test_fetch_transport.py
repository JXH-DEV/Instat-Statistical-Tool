"""The real network transport, against a small server on this computer: what comes back for each kind of answer, what is raised for each
kind of failure, and that a redirect to a private address is never followed. (The fetcher itself is tested with a scripted transport in
test_sources.py.)"""

from __future__ import annotations

import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from instatkit import config
from instatkit.sources.fetch import FetchError, urllib_transport


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path
        if path == "/ok":
            body = b"hello"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Custom", "Yes")
            self.end_headers()
            self.wfile.write(body)
        elif path == "/missing":
            self.send_error(404)
        elif path == "/error":
            self.send_error(503)
        elif path == "/redirect-private":
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{self.server.server_address[1]}/ok")
            self.end_headers()
        elif path == "/redirect-scheme":
            self.send_response(302)
            self.send_header("Location", "file:///etc/passwd")
            self.end_headers()
        elif path == "/garbled":
            self.wfile.write(b"this is not http\r\n\r\n")
        else:
            self.send_error(400)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def local():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def read_all(resp):
    try:
        return b"".join(resp.chunks())
    finally:
        resp.close()


def test_an_ok_answer_carries_status_headers_final_address_and_body(local):
    resp = urllib_transport("GET", local + "/ok", {"Accept": "text/plain"})
    assert (resp.status, resp.headers["content-type"], resp.headers["x-custom"], resp.url) == (200, "text/plain", "Yes", local + "/ok")
    assert read_all(resp) == b"hello"


@pytest.mark.parametrize("path, status", [("/missing", 404), ("/error", 503)])
def test_an_error_status_is_an_answer_not_an_exception(local, path, status):
    resp = urllib_transport("GET", local + path, {})
    assert resp.status == status
    resp.close()


def test_a_redirect_is_checked_before_it_is_followed(local):
    with pytest.raises(FetchError) as caught:
        urllib_transport("GET", local + "/redirect-private", {})
    assert str(caught.value) == "Links to local or private network addresses are not allowed."


def test_a_redirect_to_another_kind_of_address_is_not_followed(local):
    resp = urllib_transport("GET", local + "/redirect-scheme", {})
    assert resp.status == 302                                                                     # urllib hands back the redirect itself
    resp.close()


def test_a_server_that_is_not_there_is_a_retryable_failure_naming_the_reason():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]                                                                 # nothing listens here once the socket is closed
    with pytest.raises(FetchError) as caught:
        urllib_transport("GET", f"http://127.0.0.1:{port}/", {})
    assert caught.value.retryable and str(caught.value).startswith("The server could not be reached (")


def test_a_reply_that_is_not_http_is_a_retryable_failure(local):
    with pytest.raises(FetchError) as caught:
        urllib_transport("GET", local + "/garbled", {})
    assert caught.value.retryable and str(caught.value).startswith("The server could not be reached (")


def test_an_address_urllib_cannot_use_is_not_retried():
    with pytest.raises(FetchError) as caught:
        urllib_transport("GET", "http://[::1/", {})
    assert not caught.value.retryable and str(caught.value) == "This is not a valid web address."


def test_the_program_names_itself_in_every_request(local, monkeypatch):
    seen = {}

    class Echo(Handler):
        def do_GET(self):
            seen["agent"] = self.headers["User-Agent"]
            seen["accept"] = self.headers["Accept"]
            self.send_response(204)
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Echo)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
    try:
        urllib_transport("GET", f"http://127.0.0.1:{server.server_address[1]}/", {"Accept": "text/html"}).close()
    finally:
        server.shutdown()
        server.server_close()
    assert seen == {"agent": config.USER_AGENT, "accept": "text/html"}
