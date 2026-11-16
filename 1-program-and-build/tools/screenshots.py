"""Click through the program in a real browser, save the pictures used in the documentation, and fail if the browser reports a problem.

    python tools/screenshots.py                          # this checkout; pictures go to docs/screenshots
    python tools/screenshots.py --exe INSTAT-Explorer-0.10.1-windows.exe --out shots
    python tools/screenshots.py --xlsx some-real-file.xlsx --xls some-real-file.xls
    python tools/screenshots.py --web site               # the web version built by tools/build_web.py, served as a static host would

It starts the program on a free port and drives Edge, Chrome or Chromium (headless) over the DevTools protocol: the demo, every tab, Albanian
in dark mode, a phone-sized screen, the exported report, a file that is not a spreadsheet, and the Stop button. It collects console errors,
uncaught exceptions, failed requests and Content-Security-Policy violations; exit code 0 means every step worked and the browser reported nothing.
Pictures of real INSTAT files need ``--xlsx`` / ``--xls`` (see tools/survey.py for downloading files). The web version has no Stop button, and its
files do not survive a change of language (each language is a page of its own), so the journey opens the demo again where needed.

Needs ``pip install websockets`` and one of those browsers.
"""

from __future__ import annotations

import argparse
import base64
import functools
import http.server
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from collections.abc import Callable
from contextlib import ExitStack
from pathlib import Path

try:
    from websockets.sync.client import connect
except ImportError:  # pragma: no cover - the message is the point
    sys.exit("This tool needs the websockets library: python -m pip install websockets")

ROOT = Path(__file__).resolve().parent.parent
TABS = ["Insights", "Explore", "Clean data", "How it was read", "Quality", "Export"]
BROWSERS = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge",
)


def find_browser(given: str | None) -> str:
    for candidate in (given, os.environ.get("BROWSER_EXE"), *BROWSERS):
        if candidate and (Path(candidate).is_file() or shutil.which(candidate)):
            return candidate
    sys.exit("No Edge, Chrome or Chromium was found. Give one with --browser PATH.")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class App:
    """The program under test, started on a free port; ``url`` is its address with the access token."""

    def __init__(self, command: list[str], env: dict[str, str], cwd: Path | None) -> None:
        self.proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env={**os.environ, **env}, cwd=cwd, text=True,
                                     encoding="utf-8", errors="replace")
        assert self.proc.stdout is not None
        self.url = ""
        for line in self.proc.stdout:
            found = re.search(r"http://127\.0\.0\.1:\d+/\S*", line)
            if found:
                self.url = found.group(0)
                break
        if not self.url:
            sys.exit("The program did not print its address.")

    def finish(self, browser: Browser, stopped: bool) -> tuple[str, bool]:
        """Wait for the program to end. If a step has not already stopped it with its Stop button, ask it to quit; the exit code is the proof
        that it shut down by itself and was not killed."""
        try:
            if not stopped:
                browser.js("fetch('/api/quit', {method: 'POST', headers: {'X-Requested-With': 'instat', 'Content-Type': 'application/json'}, body: '{}'})")
            code = self.proc.wait(timeout=20)
            return f"the program exited by itself with code {code}" + (" after its Stop button was pressed" if stopped else ""), code == 0
        except Exception as exc:
            self.proc.kill()
            return f"the program had to be killed ({type(exc).__name__})", False


class Site:
    """The web version: a built site (tools/build_web.py) served by a plain static server, as a web host would serve it."""

    def __init__(self, folder: Path) -> None:
        class Quiet(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *args) -> None:
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(folder)))
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def finish(self, browser: Browser, stopped: bool) -> tuple[str, bool]:
        self.server.shutdown()
        self.server.server_close()
        return "the static server was stopped", True


class Browser:
    """A headless browser driven over the DevTools protocol. Everything it reports as wrong is collected in ``problems``."""

    def __init__(self, exe: str) -> None:
        port = free_port()
        self.profile = tempfile.mkdtemp(prefix="instat-shots-profile-")
        flags = ["--no-sandbox"] if getattr(os, "geteuid", lambda: 1)() == 0 else []  # Chrome refuses to start as root (a container) with its sandbox on
        self.proc = subprocess.Popen([exe, "--headless=new", f"--remote-debugging-port={port}", f"--user-data-dir={self.profile}", "--no-first-run",
                                      "--disable-gpu", "--hide-scrollbars", "--force-color-profile=srgb", *flags, "about:blank"],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        target = None
        for _ in range(150):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2))
                target = next((t for t in tabs if t["type"] == "page"), None)
                if target:
                    break
            except OSError:
                pass
            time.sleep(0.2)
        if target is None:
            sys.exit("The browser did not start.")
        self._connection = ExitStack()
        self.ws = self._connection.enter_context(connect(target["webSocketDebuggerUrl"], max_size=None, open_timeout=10))
        self.next_id = 0
        self.problems: list[str] = []
        for domain in ("Page", "Runtime", "Log", "Network", "DOM"):
            self.send(f"{domain}.enable")

    # the protocol
    def send(self, method: str, **params):
        self.next_id += 1
        mine = self.next_id
        self.ws.send(json.dumps({"id": mine, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv(timeout=60))
            if msg.get("id") == mine:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})
            self._note(msg)

    def pump(self, seconds: float = 0.4) -> None:
        end = time.time() + seconds
        while time.time() < end:
            try:
                self._note(json.loads(self.ws.recv(timeout=max(0.05, end - time.time()))))
            except TimeoutError:
                break

    def _note(self, msg: dict) -> None:
        method, p = msg.get("method"), msg.get("params", {})
        if method == "Runtime.exceptionThrown":
            d = p["exceptionDetails"]
            self.problems.append("uncaught exception: " + (d.get("exception", {}).get("description") or d.get("text", ""))[:200])
        elif method == "Runtime.consoleAPICalled" and p.get("type") in ("error", "warning"):
            self.problems.append(f"console.{p['type']}: " + " ".join(str(a.get("value", a.get("description", ""))) for a in p.get("args", []))[:200])
        elif method == "Log.entryAdded" and p["entry"].get("level") in ("error", "warning"):
            e = p["entry"]
            self.problems.append(f"browser log {e['level']} [{e.get('source')}]: {e.get('text', '')[:160]} {e.get('url', '')[-60:]}")
        elif method == "Network.responseReceived" and p["response"]["status"] >= 400:
            self.problems.append(f"HTTP {p['response']['status']}: {p['response']['url'][-80:]}")
        elif method == "Network.loadingFailed" and not p.get("canceled"):
            self.problems.append(f"request failed: {p.get('errorText')} {p.get('blockedReason', '')}")

    # the page
    def go(self, url: str) -> None:
        self.send("Page.navigate", url=url)
        self.wait("document.readyState === 'complete'")

    def js(self, expression: str):
        out = self.send("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True)
        if "exceptionDetails" in out:
            raise RuntimeError(out["exceptionDetails"].get("exception", {}).get("description", "script error")[:300])
        return out["result"].get("value")

    def wait(self, condition: str, timeout: float = 20.0) -> None:
        end = time.time() + timeout
        while time.time() < end:
            if self.js(f"Boolean({condition})"):
                self.pump(0.15)
                return
            self.pump(0.15)
        raise TimeoutError(f"timed out waiting for: {condition} | page says: {self.js('document.body.innerText.slice(0, 300)')!r}")

    def click(self, selector: str) -> None:
        """A real pointer click at the centre of the first element that matches."""
        box = self.js(f"""(() => {{ const e = document.querySelector({json.dumps(selector)}); if (!e) return null; e.scrollIntoView({{block: 'center'}});
            const r = e.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; }})()""")
        if box is None:
            raise LookupError(f"nothing matches {selector}")
        for kind in ("mouseMoved", "mousePressed", "mouseReleased"):
            self.send("Input.dispatchMouseEvent", type=kind, x=box[0], y=box[1], button="left", clickCount=1)
        self.pump(0.3)

    def click_text(self, text: str, within: str = "body", tags: str = "button, [role=tab], a, summary") -> None:
        """Click the first visible button, tab or link in ``within`` whose text starts with ``text``."""
        found = self.js(f"""(() => {{ const root = document.querySelector({json.dumps(within)}); if (!root) return false;
            const e = [...root.querySelectorAll({json.dumps(tags)})].find(b => b.offsetParent !== null && b.textContent.trim().startsWith({json.dumps(text)}));
            if (!e) return false; e.setAttribute('data-shot-target', '1'); return true; }})()""")
        if not found:
            raise LookupError(f"no button starting with {text!r} in {within}")
        try:
            self.click("[data-shot-target]")
        finally:
            self.js("document.querySelectorAll('[data-shot-target]').forEach(e => e.removeAttribute('data-shot-target'))")

    def upload(self, selector: str, path: Path) -> None:
        root = self.send("DOM.getDocument", depth=0)["root"]["nodeId"]
        node = self.send("DOM.querySelector", nodeId=root, selector=selector)["nodeId"]
        if not node:
            raise LookupError(f"nothing matches {selector}")
        self.send("DOM.setFileInputFiles", nodeId=node, files=[str(path)])
        self.pump(0.3)

    # the look
    def viewport(self, width: int, height: int, *, mobile: bool = False, scale: float = 1.0) -> None:
        self.send("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=scale, mobile=mobile)

    def scheme(self, name: str) -> None:
        self.send("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": name}])

    def shot(self, path: Path, *, full: bool = False, max_height: int = 2600) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        params: dict = {"format": "png"}
        if full:
            height = min(self.js("Math.ceil(document.documentElement.scrollHeight)"), max_height)
            width = self.js("Math.ceil(document.documentElement.clientWidth)")
            params |= {"captureBeyondViewport": True, "clip": {"x": 0, "y": 0, "width": width, "height": height, "scale": 1}}
        path.write_bytes(base64.b64decode(self.send("Page.captureScreenshot", **params)["data"]))
        return path

    def close(self) -> None:
        try:
            self.send("Browser.close")
        except Exception:
            pass
        self._connection.close()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        shutil.rmtree(self.profile, ignore_errors=True)


class Session:
    """The steps, one after the other. A step that fails is reported and the rest still run."""

    def __init__(self, browser: Browser, app: App | Site, out: Path, work: Path, *, web: bool = False) -> None:
        self.b, self.app, self.out, self.work, self.web = browser, app, out, work, web
        self.lines: list[str] = []
        self.failed = 0
        self.stopped = False  # the program was ended with its own Stop button
        self.problems: list[str] = []

    def say(self, text: str) -> None:
        self.lines.append(text)
        print(text, flush=True)

    def step(self, title: str, fn: Callable[[], None]) -> None:
        before = len(self.b.problems)
        try:
            fn()
        except Exception as exc:
            self.failed += 1
            self.say(f"  FAIL {title}: {type(exc).__name__}: {str(exc)[:300]}")
            try:
                self.b.shot(self.out / f"_failed-{title.split()[0]}.png")
            except Exception:
                pass
            return
        new = self.b.problems[before:]
        self.problems += new
        self.say(f"  ok   {title}" + (f"   <-- the browser reported {len(new)} problem(s): {new[:3]}" if new else ""))

    def tab(self, name: str) -> None:
        self.b.click_text(name, "#main", "[role=tab]")
        self.b.wait(f"[...document.querySelectorAll('#main [role=tab]')].some(t => t.textContent.trim().startsWith({json.dumps(name)}) "
                    "&& t.getAttribute('aria-selected') === 'true')")
        self.b.pump(0.5)

    def overflow(self) -> int:
        return self.b.js("document.documentElement.scrollWidth - document.documentElement.clientWidth")

    def close_all(self) -> None:
        """Start from an empty list of files, like a person who has just opened the program."""
        if self.b.js("[...document.querySelectorAll('#side button, #side a')].some(e => e.textContent.trim() === 'Close all')"):
            self.b.click_text("Close all", "#side")
            self.b.wait("!document.querySelector('#main [role=tab]')")

    def open_demo(self, demo_button: str = "Demo", open_button: str = "Open this demo") -> None:
        self.b.click_text(demo_button, "#side")
        self.b.click_text(open_button, "#side")
        self.b.wait("document.querySelector('#main [role=tab]')", 60)

    def fetch(self, target: str) -> str:
        """A request of the page itself: in the web version it goes to the Python in the browser, not to a network."""
        return f"(window.instatWeb ? window.instatWeb.fetch : fetch)({target}, {{headers: {{'X-Requested-With': 'instat'}}}})"

    def run(self, xlsx: Path | None, xls: Path | None) -> None:
        b, out = self.b, self.out
        b.viewport(1280, 800)
        b.scheme("light")

        def start():
            b.go(self.app.url)
            b.wait("document.querySelector('#side button')", 180 if self.web else 20)  # the first visit to the web version starts Python
            b.shot(out / "01-start.png")

        def insights():
            b.click_text("Demo", "#side")
            b.click_text("Open this demo", "#side")
            b.wait("document.querySelector('#main [role=tab]')", 30)
            tabs = b.js("[...document.querySelectorAll('#main [role=tab]')].map(e => e.textContent.trim())")
            assert tabs == TABS, tabs
            b.shot(out / "02-insights.png", full=True)

        def explore():
            self.tab("Explore")
            b.wait("document.querySelector('#main svg')")
            b.shot(out / "03-explore.png", full=True)

        def clean_data():
            self.tab("Clean data")
            b.wait("document.querySelector('#main table')")
            self.say(f"       the table shows {b.js('document.querySelectorAll(`#main table tbody tr`).length')} rows")
            b.shot(out / "04-clean-data.png")

        def how_read():
            self.tab("How it was read")
            b.wait("document.querySelector('#main table, #main .card')")
            b.shot(out / "05-how-it-was-read.png", full=True)

        def quality():
            self.tab("Quality")
            b.shot(out / "06-quality.png", full=True)

        def export():
            self.tab("Export")
            b.shot(out / "07-export.png")

        def report():
            key = b.js(self.fetch("'/api/state'") + ".then(r => r.json()).then(s => s.files[0].key)")
            html = b.js(self.fetch(f"'/export?key={key}&i=0&kind=report'") + ".then(r => r.text())")
            path = self.work / "report.html"
            path.write_text(html, encoding="utf-8")
            external = len(re.findall(r"""(?:src|href)=["']https?://""", html))
            self.say(f"       the report is {len(html) // 1024} KB, one self-contained file; links to other sites that it loads from: {external}")
            assert external == 0, "the report fetches something from the internet"
            b.go(path.as_uri())
            b.pump(0.8)
            b.shot(out / "08-exported-report.png", full=True, max_height=2200)
            b.go(self.app.url)
            if self.web:  # a new page is a new Python: the open file is gone
                b.wait("document.querySelector('#side button')", 180)
                self.open_demo()
            b.wait("document.querySelector('#main [role=tab]')", 20)

        def albanian_dark():
            b.scheme("dark")
            b.click("#lang")
            if self.web:
                b.wait("document.documentElement.lang === 'sq' && document.querySelector('#side button')", 180)
                self.open_demo("Shembull", "Hap këtë shembull")
            b.wait("document.documentElement.lang === 'sq' && document.querySelector('#main [role=tab]')", 20)
            b.pump(0.6)
            tabs = b.js("[...document.querySelectorAll('#main [role=tab]')].map(e => e.textContent.trim())")
            self.say(f"       the tabs in Albanian: {tabs}")
            assert len(tabs) == len(TABS) and not set(tabs) & set(TABS), "the tabs were not translated"
            b.shot(out / "09-albanian-dark.png", full=True, max_height=1700)

        def phone():
            b.click("#lang")
            b.wait("document.documentElement.lang === 'en' && document.querySelector(" + ("'#side button'" if self.web else "'#main [role=tab]'") + ")", 180 if self.web else 20)
            b.scheme("light")
            b.viewport(390, 844, mobile=True, scale=2)
            b.go(self.app.url)
            b.wait("document.querySelector(" + ("'#side button'" if self.web else "'#main [role=tab]'") + ")", 180 if self.web else 20)
            self.close_all()
            b.js("window.scrollTo(0, 0)")
            self.say(f"       sideways overflow on a 390 px wide screen: {self.overflow()} px")
            assert self.overflow() <= 0, "the page scrolls sideways on a phone"
            b.shot(out / "10-phone-start.png")
            b.click_text("Demo", "#side")
            b.click_text("Open this demo", "#side")
            b.wait("document.querySelector('#main [role=tab]')", 30)
            b.pump(1.0)
            top = b.js("Math.round(document.querySelector('#main').getBoundingClientRect().top)")
            self.say(f"       right after opening a file the results start {top} px from the top of the screen")
            assert top < 120, "after opening a file the results are not brought into view on a phone"
            b.shot(out / "11-phone-results.png")
            b.js("window.scrollTo(0, document.querySelector('#main svg').getBoundingClientRect().top + window.scrollY - 80)")
            b.pump(0.4)
            b.shot(out / "12-phone-chart.png")
            self.tab("Clean data")
            b.wait("document.querySelector('#main table')")
            self.say(f"       sideways overflow in Clean data on a phone: {self.overflow()} px (a wide table scrolls inside its own box)")
            assert self.overflow() <= 0
            b.send("Emulation.clearDeviceMetricsOverride")
            b.viewport(1280, 800)

        def real(label: str, path: Path, name: str):
            def go():
                b.go(self.app.url)
                b.wait("document.querySelector('#side button')", 180 if self.web else 20)
                self.close_all()
                b.click_text("Upload", "#side")
                copy = self.work / path.name
                shutil.copyfile(path, copy)
                b.upload("input[type=file]", copy)
                b.wait("document.querySelector('#main [role=tab]')", 60)
                b.pump(0.8)
                titles = b.js("[...document.querySelectorAll('#tbl option')].map(o => o.textContent.trim().slice(0, 60))")
                self.say(f"       {label}: {len(titles) or 1} table(s) found" + (f", e.g. {titles[:2]}" if titles else ""))
                b.shot(out / f"{name}-insights.png", full=True, max_height=1900)
                self.tab("How it was read")
                b.wait("document.querySelector('#main table, #main .card')")
                b.shot(out / f"{name}-how-it-was-read.png", full=True, max_height=1900)
            return go

        def not_a_spreadsheet():
            bad = self.work / "tab-3.xls"
            bad.write_bytes(b"<!DOCTYPE html><html><body><h1>503 Service Unavailable</h1><p>Try again later.</p></body></html>")
            b.go(self.app.url)
            b.wait("document.querySelector('#side button')", 180 if self.web else 20)
            self.close_all()
            b.click_text("Upload", "#side")
            b.upload("input[type=file]", bad)
            b.wait("document.querySelector('#main .warn-box')", 20)
            self.say(f"       what the user reads: {b.js('document.querySelector(`#main .warn-box`).innerText')!r}")
            b.shot(out / "15-not-a-spreadsheet.png")

        def about():
            b.click("#about-btn")
            b.wait("document.querySelector('#about').open")
            b.js("document.querySelectorAll('#about p.muted').forEach(p => { p.textContent = p.textContent.split('Downloaded files')[0].trim(); })")  # the folder is a local path
            b.pump(0.2)
            b.shot(out / "16-about.png")

        def stop():
            b.click_text("Stop the program", "#about")
            b.wait("/stopped/i.test(document.querySelector('#about').innerText)")
            b.shot(out / "17-stopped.png")
            self.stopped = True

        steps: list[tuple[str, Callable[[], None]]] = [
            ("01 start page", start), ("02 insights: the demo consumer price index", insights), ("03 explore", explore), ("04 clean data", clean_data),
            ("05 how it was read", how_read), ("06 quality checks", quality), ("07 export", export), ("08 the exported report on its own", report),
            ("09 Albanian, dark", albanian_dark), ("10 phone-sized screen", phone)]
        if xlsx:
            steps.append((f"11 a real INSTAT file ({xlsx.name})", real("xlsx", xlsx, "13-real-xlsx")))
        if xls:
            steps.append((f"12 a real INSTAT file, old .xls format ({xls.name})", real("xls", xls, "14-real-xls")))
        steps += [("13 a download that is a web page, not a spreadsheet", not_a_spreadsheet), ("14 About", about)]
        if not self.web:
            steps.append(("15 the Stop button ends the program", stop))
        for title, fn in steps:
            self.step(title, fn)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "screenshots", help="where the pictures go")
    ap.add_argument("--exe", help="test the stand-alone .exe (or any launcher) instead of this checkout")
    ap.add_argument("--web", type=Path, help="test the web version: a folder built by tools/build_web.py")
    ap.add_argument("--browser", help="path of Edge, Chrome or Chromium")
    ap.add_argument("--xlsx", type=Path, help="a real INSTAT .xlsx file to open")
    ap.add_argument("--xls", type=Path, help="a real INSTAT .xls file to open")
    args = ap.parse_args()
    out: Path = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="instat-shots-"))
    env = {"INSTAT_DATA_DIR": str(work / "data"), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}
    if args.web:
        app: App | Site = Site(args.web.resolve())
    elif args.exe:
        app = App([args.exe, "--no-browser", "--port", "0"], env, None)
    else:
        app = App([sys.executable, "-m", "instatkit", "--no-browser", "--port", "0"], env, ROOT)
    browser = Browser(find_browser(args.browser))
    session = Session(browser, app, out, work, web=bool(args.web))
    session.say(f"testing {'the web version in ' + str(args.web) if args.web else 'the program in ' + args.exe if args.exe else 'this checkout'}, pictures into {out}")
    clean_exit = False
    try:
        session.run(args.xlsx, args.xls)
    finally:
        session.say(f"browser problems over the whole run: {len(session.problems)}")
        for p in session.problems[:10]:
            session.say("   " + p)
        message, clean_exit = app.finish(browser, session.stopped)
        session.say(message)
        browser.close()
        shutil.rmtree(work, ignore_errors=True)
    return 0 if clean_exit and not session.failed and not session.problems else 1


if __name__ == "__main__":
    sys.exit(main())
