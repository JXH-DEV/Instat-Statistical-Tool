"""The local web server, tested over real HTTP on an ephemeral port: who may use it, what it refuses, and that every
endpoint the page calls answers with valid, complete data."""

from __future__ import annotations

import http.client
import io
import json
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

import pytest

from instatkit.web import server as web


def _strict(token):
    raise AssertionError(f"not valid JSON: {token}")


class Client:
    def __init__(self, server, app):
        self.server, self.app = server, app
        self.port = server.server_address[1]
        self.cookie = f"{app.cookie}={app.token}"

    def request(self, method, path, body=None, *, auth=True, json_body=None, headers=None, cookie=None, host=None):
        h = dict(headers or {})
        if auth:
            h["Cookie"] = cookie or self.cookie
        if json_body is not None:
            body = json.dumps(json_body).encode()
            h["Content-Type"] = "application/json"
        if method == "POST":
            h.setdefault("X-Requested-With", "instat")
        if host:
            h["Host"] = host
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        try:
            conn.request(method, path, body=body, headers=h)
            r = conn.getresponse()
            data = r.read()
            return r.status, {k.lower(): v for k, v in r.getheaders()}, data
        finally:
            conn.close()

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, payload=None, **kw):
        return self.request("POST", path, json_body={} if payload is None else payload, **kw)

    def json(self, status, headers, data, expect=200):
        assert status == expect, (status, data[:300])
        assert "application/json" in headers["content-type"]
        return json.loads(data, parse_constant=_strict)


def _serve(**kw):
    server, app = web.start(0, **kw)
    client = Client(server, app)
    client.thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    client.thread.start()
    return client


@pytest.fixture(scope="module")
def srv():
    c = _serve()
    yield c
    c.server.shutdown()
    c.server.server_close()


@pytest.fixture(scope="module")
def cpi(srv):
    return srv.json(*srv.post("/api/demo", {"name": "cpi"}))["key"]


@pytest.fixture(scope="module")
def gdp(srv):
    return srv.json(*srv.post("/api/demo", {"name": "gdp"}))["key"]


# --- who may use it ------------------------------------------------------------------------------------------------

def test_health_needs_no_token(srv):
    assert srv.get("/health", auth=False)[0] == 200


def test_without_the_cookie_every_page_and_api_is_locked(srv):
    for path in ("/", "/app.js", "/api/state", "/api/about", "/export?key=a&i=0&kind=tidy"):
        status, headers, body = srv.get(path, auth=False)
        assert status == 403, path
        assert b"INSTAT Explorer" in body and b"{" not in body.split(b"<style>")[0]
    status, headers, _ = srv.get("/", auth=False)
    csp = headers["content-security-policy"]
    assert "script-src 'self'" in csp and "style-src 'sha256-" in csp, "the locked page has a styled, hash-allowed rule"
    assert srv.post("/api/state", auth=False)[0] == 403


def test_the_access_link_sets_a_port_specific_cookie(srv):
    assert srv.get("/?t=wrong", auth=False)[0] == 403
    status, headers, _ = srv.get(f"/?t={srv.app.token}", auth=False)
    assert status == 303 and headers["location"] == "/"
    cookie = headers["set-cookie"]
    assert cookie.startswith(f"instat-{srv.port}=") and "HttpOnly" in cookie and "SameSite=Strict" in cookie


def test_a_second_copy_of_the_program_does_not_log_out_the_first(srv):
    other = _serve()
    try:
        assert other.port != srv.port and other.app.cookie != srv.app.cookie
        both = f"{other.cookie}; {srv.cookie}"          # a browser sends the cookies of both, whatever port it talks to
        assert srv.get("/api/state", cookie=both)[0] == 200 and other.get("/api/state", cookie=both)[0] == 200
        assert srv.get("/api/state", cookie=other.cookie)[0] == 403
    finally:
        other.server.shutdown()
        other.server.server_close()


def test_port_zero_and_a_busy_port(srv):
    assert srv.app.hosts == {f"127.0.0.1:{srv.port}", f"localhost:{srv.port}", f"[::1]:{srv.port}"}
    server, app = web.start(srv.port)                  # the port is taken: the next free one is used
    try:
        assert server.server_address[1] != srv.port
    finally:
        server.server_close()
    server, _app = web.start(65535)                      # the last port: no OverflowError from the search
    server.server_close()


def test_dns_rebinding_is_refused(srv):
    for host in ("evil.example.com", f"evil.example.com:{srv.port}", "127.0.0.1:1"):
        assert srv.get("/health", host=host)[0] == 421, host
        assert srv.get("/", host=host)[0] == 421


def test_writes_need_the_custom_header_and_the_same_origin(srv):
    no_header = srv.request("POST", "/api/resolve", json_body={"q": "x"}, headers={"X-Requested-With": ""})
    assert no_header[0] == 403
    foreign = srv.post("/api/resolve", {"q": "x"}, headers={"Origin": "http://evil.example.com"})
    assert foreign[0] == 403
    same = srv.post("/api/resolve", {"q": "inflation"}, headers={"Origin": f"http://127.0.0.1:{srv.port}"})
    assert same[0] == 200


def test_other_methods_and_unknown_paths(srv):
    for method in ("PUT", "DELETE", "PATCH", "OPTIONS"):
        assert srv.request(method, "/api/state")[0] == 405, method
    for path in ("/nope", "/api/nope", "/../pyproject.toml", "/%2e%2e/pyproject.toml", "/app.js/../../config.py", "/static/app.js", "//etc/passwd"):
        assert srv.get(path)[0] in (404, 403), path
    assert srv.get("/favicon.ico")[0] == 204


# --- limits --------------------------------------------------------------------------------------------------------

def test_body_limits_and_bad_json(srv):
    status, headers, data = srv.request("POST", "/api/resolve", body=b"x" * (web.MAX_JSON + 1), headers={"Content-Type": "application/json"})
    assert status == 413 and "limit" in json.loads(data)["error"]
    assert srv.request("POST", "/api/resolve", body=b"{not json")[0] == 400
    assert srv.request("POST", "/api/resolve", body=b"[1, 2]")[0] == 400
    bad_length = srv.request("POST", "/api/resolve", body=b"{}", headers={"Content-Length": "abc"})
    assert bad_length[0] in (400, 413)


def test_chunked_bodies_are_refused(srv):
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=10)
    conn.putrequest("POST", "/api/resolve")
    for k, v in {"Cookie": srv.cookie, "X-Requested-With": "instat", "Transfer-Encoding": "chunked"}.items():
        conn.putheader(k, v)
    conn.endheaders()
    conn.send(b"2\r\n{}\r\n0\r\n\r\n")
    r = conn.getresponse()
    assert r.status == 411
    conn.close()


def test_unauthenticated_uploads_are_not_waited_for(srv):
    """A refused request gets its answer at once; the server does not sit on a connection for the rest of the body."""
    import time

    t0 = time.perf_counter()
    status, _h, _d = srv.request("POST", "/api/upload", body=b"x" * 200_000, auth=False, headers={"X-Filename": "a.xlsx"})
    assert status == 403 and time.perf_counter() - t0 < 3


# --- the page --------------------------------------------------------------------------------------------------------

def test_start_page_and_assets(srv):
    status, headers, body = srv.get("/")
    assert status == 200 and headers["content-type"].startswith("text/html")
    assert headers["x-content-type-options"] == "nosniff" and headers["cache-control"] == "no-cache"
    assert b"{{" not in body, "every placeholder in the page must have been filled in"
    assert "default-src 'none'" in headers["content-security-policy"] and "script-src 'self'" in headers["content-security-policy"]
    assert b'lang="en"' in body
    types = {"/app.js": "javascript", "/chart.js": "javascript", "/app.css": "css", "/chart.css": "css"}
    for path, kind in types.items():
        status, h, data = srv.get(path)
        assert status == 200 and kind in h["content-type"] and len(data) > 500, path
    assert b"{{v}}" not in srv.get("/app.js")[2]


def test_the_page_is_served_in_the_language_of_the_cookie(srv):
    en = srv.get("/")[2].decode()
    sq = srv.get("/", cookie=f"{srv.cookie}; lang=sq")[2].decode()
    assert 'lang="sq"' in sq and en != sq and ">English<" in sq, "the language button offers the other language"
    lang = srv.json(*srv.get("/api/lang", cookie=f"{srv.cookie}; lang=sq"))
    assert lang["language"] == "sq" and len(lang["catalog"]) > 500
    assert srv.json(*srv.get("/api/lang"))["catalog"] == {}


def test_accept_language_picks_albanian(srv):
    lang = srv.json(*srv.get("/api/lang", headers={"Accept-Language": "sq-AL,sq;q=0.9,en;q=0.5"}))
    assert lang["language"] == "sq"


# --- the app -------------------------------------------------------------------------------------------------------

def test_search_and_resolve(srv):
    r = srv.json(*srv.post("/api/resolve", {"q": "inflation"}))
    assert r["kind"] == "topics" and r["hits"] and all(h["url"].startswith("https://www.instat.gov.al") for h in r["hits"])
    r = srv.json(*srv.post("/api/resolve", {"q": "papunësia"}))
    assert r["hits"]
    r = srv.json(*srv.post("/api/resolve", {"q": ""}))
    assert r["hits"] == [] or r["kind"] != "file"
    r = srv.json(*srv.post("/api/resolve", {"q": "https://www.instat.gov.al/media/1234/table.xlsx"}))
    assert r["kind"] == "file" and not r["external"]
    r = srv.json(*srv.post("/api/resolve", {"q": "https://example.com/table.xlsx"}))
    assert r["kind"] == "file" and r["external"]


def test_pages_outside_instat_cannot_be_listed_or_loaded(srv):
    for url in ("https://example.com/", "http://127.0.0.1:8080/", "file:///etc/passwd", "ftp://instat.gov.al/x", "not a url", ""):
        status, _h, data = srv.post("/api/listing", {"url": url})
        assert status == 400, (url, status, data[:100])
    status, _h, data = srv.post("/api/load", {"url": "https://example.com/t.xlsx"})
    assert status == 400 and b"instat.gov.al" in data
    status, _h, data = srv.post("/api/load", {"url": "https://example.com/t.xlsx", "external": "false"})
    assert status == 400, "only a real true counts as the user's confirmation"


def test_state_and_table(srv, cpi):
    state = srv.json(*srv.get("/api/state"))
    f = next(f for f in state["files"] if f["key"] == cpi)
    assert f["ok"] and f["kind"] == "demo" and f["tables"][0]["confidence"] > 0.8 and state["demos"]
    t = srv.json(*srv.get(f"/api/table?key={cpi}&i=0"))
    assert t["title"] and t["tiles"] and t["sections"] and t["charts"] and t["source"]["demo"] is True
    assert all(c["svg"].startswith("<svg") for c in t["charts"])
    assert t["warnings"] == []


def test_explore_every_view_and_a_csv(srv, cpi):
    q = f"?key={cpi}&i=0"
    first = srv.json(*srv.post("/api/explore" + q, {}))
    assert first["measures"] and first["dims"] and first["periods"] and first["kinds"][0] == "lines" and first["svg"]
    for kind in first["kinds"]:
        out = srv.json(*srv.post("/api/explore" + q, {"kind": kind, "measure": first["measure"]}))
        assert out["kind"] == kind and out["rows"] and out["total"] >= len(out["rows"]) and out["shown"] == len(out["rows"])
    narrow = srv.json(*srv.post("/api/explore" + q, {"lo": first["periods"][3][0], "hi": first["periods"][5][0], "kind": "table"}))
    assert {r[narrow["columns"].index("period")] for r in narrow["rows"]} == {p[0] for p in first["periods"][3:6]}
    nothing = srv.json(*srv.post("/api/explore" + q, {"filters": {first["dims"][0]["name"]: ["no such value"]}}))
    assert nothing["rows"] == [] and nothing["caption"]
    status, headers, data = srv.post("/api/explore" + q, {"csv": True})
    assert status == 200 and data.startswith(b"\xef\xbb\xbf") and "attachment" in headers["content-disposition"]
    assert srv.post("/api/explore" + q, {"filters": "garbage", "lo": 5, "hi": ["x"]})[0] == 200, "odd types are ignored, not a crash"


def test_data_tab_paging_sorting_and_search(srv, cpi):
    q = f"/api/data?key={cpi}&i=0"
    page0 = srv.json(*srv.get(q))
    assert page0["total"] == 336 and len(page0["rows"]) == page0["size"] == 100 and "period_end" not in page0["columns"]
    page3 = srv.json(*srv.get(q + "&page=3"))
    assert len(page3["rows"]) == 36
    assert srv.json(*srv.get(q + "&page=99"))["rows"] == []
    desc = srv.json(*srv.get(q + "&sort=value&desc=1"))
    asc = srv.json(*srv.get(q + "&sort=value&desc="))
    col = desc["columns"].index("value")
    assert desc["rows"][0][col] >= desc["rows"][-1][col] and asc["rows"][0][col] <= asc["rows"][-1][col]
    assert desc["rows"][0][col] == max(r[col] for r in desc["rows"])
    found = srv.json(*srv.get(q + "&q=transport"))
    assert 0 < found["total"] < 336
    wide = srv.json(*srv.get(q + "&layout=wide"))
    assert wide["total"] == 7 and len(wide["columns"]) > 40
    assert srv.json(*srv.get(q + "&sort=nonexistent&q=%25"))["total"] >= 0


def test_read_quality_and_the_original_sheet(srv, cpi):
    q = f"key={cpi}&i=0"
    read = srv.json(*srv.get(f"/api/read?{q}"))
    assert read["rows"] and read["grid"]["rows"] and read["override"]["data_first"] >= 1 and "auto" in read["override"]["layouts"]
    roles = {cell[1] for row in read["grid"]["rows"] for cell in row["cells"]}
    assert {"title", "header", "label", "value"} <= roles, roles
    cells = [c[0] for row in read["grid"]["rows"] for c in row["cells"]]
    assert not any("e+" in c for c in cells), "numbers must be shown as in the file, not in scientific notation"
    quality = srv.json(*srv.get(f"/api/quality?{q}"))
    assert quality["checks"] and all(c["status"] in ("pass", "warn", "fail", "info") for c in quality["checks"])


@pytest.mark.parametrize("kind, mime, signature", [
    ("report", "text/html", b"<!doctype html>"), ("tidy", "text/csv", b"\xef\xbb\xbf"), ("wide", "text/csv", b"\xef\xbb\xbf"),
    ("xlsx", "spreadsheetml.sheet", b"PK"), ("sqlite", "sqlite3", b"SQLite format 3\x00"), ("zip", "application/zip", b"PK"),
    ("diagnostic", "application/json", b"{")])
def test_every_export(srv, cpi, kind, mime, signature):
    status, headers, data = srv.get(f"/export?key={cpi}&i=0&kind={kind}")
    assert status == 200 and mime in headers["content-type"] and data.startswith(signature) and len(data) > 100
    disposition = headers["content-disposition"]
    assert disposition.startswith("attachment; filename=\"") and all(ch.isalnum() or ch in "-._\"=; " for ch in disposition)
    if kind == "diagnostic":
        assert json.loads(data, parse_constant=_strict)["spec"]["orientation"]
    if kind == "zip":
        assert zipfile.ZipFile(io.BytesIO(data)).testzip() is None


def test_exports_of_different_tables_have_different_names(srv, gdp):
    names = {srv.get(f"/export?key={gdp}&i={i}&kind=tidy")[1]["content-disposition"] for i in (0, 1)}
    assert len(names) == 2
    assert srv.get(f"/export?key={gdp}&i=0&kind=zip")[1]["content-disposition"] == srv.get(f"/export?key={gdp}&i=1&kind=zip")[1]["content-disposition"]


def test_albanian_exports_and_pages(srv, cpi):
    sq = {"cookie": f"{srv.cookie}; lang=sq"}
    table = srv.json(*srv.get(f"/api/table?key={cpi}&i=0", **sq))
    en = srv.json(*srv.get(f"/api/table?key={cpi}&i=0"))
    assert table["what"] != en["what"] and table["sections"] != en["sections"]
    html = srv.get(f"/export?key={cpi}&i=0&kind=report", **sq)[2].decode()
    assert 'lang="sq"' in html
    assert srv.json(*srv.get(f"/api/table?key={cpi}&i=0"))["what"] == en["what"], "switching back must give the English text again"


def test_upload_and_a_hostile_filename(srv):
    from instatkit import demo

    data = demo.make_month_by_year()[0]
    name = "../../..\\Windows/<script>evil</script>.xlsx"
    r = srv.json(*srv.request("POST", "/api/upload", body=data, headers={"X-Filename": quote(name), "Content-Type": "application/octet-stream"}))
    state = srv.json(*srv.get("/api/state"))
    f = next(f for f in state["files"] if f["key"] == r["key"])
    assert f["ok"] and "/" not in f["filename"] and "\\" not in f["filename"] and "<" not in f["filename"] and f["filename"].endswith(".xlsx")
    for payload in (b"", b"garbage", b"PK\x03\x04" + b"0" * 64):
        status, _h, data = srv.request("POST", "/api/upload", body=payload, headers={"X-Filename": "bad.xlsx"})
        body = json.loads(data)
        assert status == 200 or "error" in body
        if status == 200:
            f = next(f for f in srv.json(*srv.get("/api/state"))["files"] if f["key"] == body["key"])
            assert not f["ok"] and f["errors"]


def test_uploading_the_same_file_twice_keeps_one_copy(srv):
    from instatkit import demo

    data = demo.make_cross_section()[0]
    keys = {srv.json(*srv.request("POST", "/api/upload", body=data, headers={"X-Filename": "w.xlsx"}))["key"] for _ in range(2)}
    assert len(keys) == 1


def test_closing_files(srv):
    key = srv.json(*srv.post("/api/demo", {"name": "wages"}))["key"]
    after = srv.json(*srv.post("/api/close", {"key": key}))
    assert key not in {f["key"] for f in after["files"]}
    assert srv.get(f"/api/table?key={key}&i=0")[0] == 404


# --- bad input is a message, not a crash -------------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "/api/table?key=nope&i=0", "/api/table?i=0", "/api/data?key=nope&i=0", "/api/read?key=nope&i=0", "/api/quality?key=nope&i=0",
    "/export?key=nope&i=0&kind=tidy"])
def test_unknown_file_is_404(srv, path):
    status, _h, data = srv.get(path)
    assert status in (400, 404) and json.loads(data)["error"]


def test_bad_numbers_give_400_not_500(srv, cpi):
    for path in (f"/api/table?key={cpi}&i=abc", f"/api/table?key={cpi}&i=%C2%B2", f"/api/table?key={cpi}&i=-1", f"/api/table?key={cpi}&i=99",
                 f"/api/data?key={cpi}&i=0&page=abc", f"/api/data?key={cpi}&i=0&page=-4", f"/api/read?key={cpi}&i=0&part=x",
                 f"/export?key={cpi}&i=0&kind=exe"):
        status, _h, data = srv.get(path)
        assert status in (400, 404), (path, status, data[:100])
        assert json.loads(data)["error"]


def test_corrections_are_validated_and_never_lose_the_table(srv):
    key = srv.json(*srv.post("/api/demo", {"name": "population"}))["key"]
    q = f"?key={key}&i=0"
    read = srv.json(*srv.get(f"/api/read?key={key}&i=0"))["override"]
    good = {k: read[k] for k in ("header_first", "header_last", "data_first", "data_last", "n_labels")} | {"layout": "auto"}
    for bad in ({"data_first": "abc"}, {"data_first": 0}, {"data_first": 9, "data_last": 3}, {"header_first": 5, "header_last": 2},
                {"n_labels": -1}, {"layout": "diagonal"}, {"n_labels": 1.5}, {"data_last": None}):
        status, _h, data = srv.post("/api/reread" + q, good | bad)
        assert status == 400 and json.loads(data)["error"], bad
    for incomplete in ({}, {"layout": "auto"}):
        assert srv.post("/api/reread" + q, incomplete)[0] == 400
    # settings that leave nothing to read are refused, and the original reading is still there
    status, _h, data = srv.post("/api/reread" + q, good | {"data_first": 900, "data_last": 901})
    assert status == 400, data[:200]
    assert srv.json(*srv.get(f"/api/table?key={key}&i=0"))["title"]
    # a valid correction is applied and can be undone
    state = srv.json(*srv.post("/api/reread" + q, good | {"n_labels": 1}))
    assert next(f for f in state["files"] if f["key"] == key)["ok"]
    assert srv.json(*srv.get(f"/api/read?key={key}&i=0"))["override"]["active"] is True
    state = srv.json(*srv.post("/api/reread" + q, {"reset": True}))
    assert srv.json(*srv.get(f"/api/read?key={key}&i=0"))["override"]["active"] is False


# --- concurrency, files kept, shutdown --------------------------------------------------------------------------------

def test_many_requests_at_once(srv, cpi):
    def hit(i):
        path = [f"/api/table?key={cpi}&i=0", f"/api/data?key={cpi}&i=0&page={i % 4}", f"/api/quality?key={cpi}&i=0", "/api/state"][i % 4]
        return srv.get(path)[0]

    with ThreadPoolExecutor(12) as pool:
        assert set(pool.map(hit, range(48))) == {200}


def test_language_switches_do_not_corrupt_each_other(srv, cpi):
    sq = {"cookie": f"{srv.cookie}; lang=sq"}

    def hit(i):
        kw = sq if i % 2 else {}
        what = srv.json(*srv.get(f"/api/table?key={cpi}&i=0", **kw))["what"]
        return i % 2, what

    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(hit, range(24)))
    assert len({w for k, w in results if k == 0}) == 1 and len({w for k, w in results if k == 1}) == 1
    assert {w for k, w in results if k == 0}.isdisjoint({w for k, w in results if k == 1})


def test_oldest_file_is_closed_with_a_notice():
    from instatkit.web import api

    c = _serve()
    try:
        names = list(api.DEMOS_FOR_TEST) if hasattr(api, "DEMOS_FOR_TEST") else ["cpi", "lfs", "gdp", "trade", "population", "tourism", "wages"]
        old = api.MAX_FILES
        api.MAX_FILES = 3
        try:
            closed = []
            for name in names:
                closed += c.json(*c.post("/api/demo", {"name": name}))["closed"]
        finally:
            api.MAX_FILES = old
        assert len(closed) == len(names) - 3 and all(isinstance(x, str) and x for x in closed)
        assert len(c.json(*c.get("/api/state"))["files"]) == 3
    finally:
        c.server.shutdown()
        c.server.server_close()


def test_stop_button_ends_the_program_unless_it_is_shared():
    c = _serve()
    assert c.json(*c.post("/api/quit")) == {"ok": True}
    c.thread.join(10)
    assert not c.thread.is_alive(), "serve_forever should have returned"
    c.server.server_close()                              # what run() does next
    with pytest.raises(OSError):
        http.client.HTTPConnection("127.0.0.1", c.port, timeout=3).request("GET", "/health")
    shared = _serve(share=True)
    try:
        status, _h, data = shared.request("POST", "/api/quit", json_body={}, cookie=shared.cookie, host=f"127.0.0.1:{shared.port}")
        assert status == 403 and json.loads(data)["error"]
        assert shared.thread.is_alive()
    finally:
        shared.server.shutdown()
        shared.server.server_close()


def test_a_missing_library_is_explained(monkeypatch):
    c = _serve(workspace=None)
    try:
        def broken():
            raise ImportError("No module named 'pandas'")

        monkeypatch.setattr(web, "_api", broken)
        status, _h, data = c.get("/api/state")
        assert status == 500 and "pandas" in json.loads(data)["error"]
    finally:
        c.server.shutdown()
        c.server.server_close()
