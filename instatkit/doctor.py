"""``instat doctor``: a quick check that a teacher or an IT administrator can run to see that an installation works."""

from __future__ import annotations

import http.client
import sys
import threading
from collections.abc import Callable

from . import __version__, config
from .i18n import tn, tr


def _libraries() -> str:
    import numpy
    import pandas
    import xlrd

    return f"pandas {pandas.__version__}, numpy {numpy.__version__}, xlrd {xlrd.__version__}"


def _engine() -> str:
    from .demo import DEMOS
    from .export.excel_export import excel_bytes
    from .export.html_report import build_report
    from .pipeline import SourceInfo, process_bytes

    label, fname, build = DEMOS["cpi"]
    data = build()
    pf = process_bytes(data, fname, source=SourceInfo(fname, "", len(data), "demo"), label=label)
    if not pf.ok:
        raise RuntimeError("; ".join(pf.errors) or tr("the demo file could not be read"))
    return tr("a demo file was read; the report is {report} KB and the workbook {workbook} KB", report=len(build_report(pf)) // 1024,
              workbook=len(excel_bytes(pf)) // 1024)


def _server() -> str:
    from .web.server import start

    server, app = start(8590)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]

        def get(path: str, cookie: str | None = None) -> tuple[int, bytes]:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            conn.request("GET", path, headers={"Cookie": cookie} if cookie else {})
            r = conn.getresponse()
            body = r.read()
            conn.close()
            return r.status, body

        if get("/health")[0] != 200:
            raise RuntimeError(tr("the health check failed"))
        if get("/api/state")[0] != 403:
            raise RuntimeError(tr("the access token is not enforced"))
        status, body = get("/", f"instat={app.token}")
        if status != 200 or b"INSTAT Explorer" not in body:
            raise RuntimeError(tr("the start page is not served"))
        return tr("listening on port {port}, access token enforced", port=port)
    finally:
        server.shutdown()
        server.server_close()


def _online() -> str:
    from .sources.fetch import Fetcher

    info = Fetcher().head(config.BASE_URL + "/")
    if not info.ok:
        raise RuntimeError(tr("instat.gov.al answered with HTTP {status}", status=info.status))
    return tr("instat.gov.al can be reached")


def run_checks(*, online: bool = False) -> int:
    ok_dir = config.ensure_data_dir()
    is64 = sys.maxsize > 2**32
    checks: list[tuple[str, Callable[[], str]]] = [
        (tr("64-bit Python 3.11 or newer"), lambda: _require(sys.version_info >= (3, 11) and is64, tr(
            "Python {version}, {bits}-bit", version=sys.version.split()[0], bits=64 if is64 else 32))),
        (tr("Libraries"), _libraries),
        (tr("The data folder can be written to"), lambda: _require(True, str(config.DATA_DIR) + (
            "" if ok_dir else tr(" (temporary: the usual folder cannot be written to)")))),
        (tr("Reading, analysing and exporting a file"), _engine),
        (tr("The web server of the app"), _server),
    ]
    if online:
        checks.append((tr("Internet access to INSTAT"), _online))
    print(f"INSTAT Explorer {__version__}")
    failed = 0
    for name, check in checks:
        try:
            print(f"  [ok] {name}: {check()}")
        except Exception as exc:  # report every problem, not just the first
            failed += 1
            print(f"  [!!] {name}: {type(exc).__name__}: {exc}")
    print("\n" + (tr("Everything works.") if not failed else tn(
        failed, "{n} check failed. Please send this output to whoever looks after the installation.",
        "{n} checks failed. Please send this output to whoever looks after the installation.")))
    return 1 if failed else 0


def _require(condition: bool, detail: str) -> str:
    if not condition:
        raise RuntimeError(detail)
    return detail
