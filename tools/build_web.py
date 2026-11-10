"""Build the web version: a static site that runs the program in the visitor's browser.

    python tools/build_web.py --out site
    python -m http.server -d site            # to try it: open http://localhost:8000

The site holds the page (the same app.js as the local program), webapp/bridge.js and webapp/pyworker.js, a zip of the instatkit package, and
Pyodide (Python for the browser) with numpy, pandas and xlrd. Everything is served from the site itself, so a visitor's browser contacts no other
server. Pyodide is downloaded once (cached; see --cache) and checked against the hashes pinned below. Standard library only.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import shutil
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from instatkit import __version__, i18n  # noqa: E402
from instatkit.web import server  # noqa: E402

PYODIDE = "314.0.7"
PYODIDE_TARBALL = f"https://registry.npmjs.org/pyodide/-/pyodide-{PYODIDE}.tgz"
PYODIDE_INTEGRITY = "sha512-0YvXxEhfEdpLfb/XkM2BFAeMROq0iMUX2bzzH9pOttyMcWkwq+HbE5uyuGD82LN7y2q+SNvi/6V5JEsOlD2R1A=="  # of that tarball, as the registry states it
PYODIDE_PACKAGES = f"https://cdn.jsdelivr.net/pyodide/v{PYODIDE}/full/"  # the wheels; each is checked against the sha256 in the lock file of the tarball
CORE = ("pyodide.mjs", "pyodide.asm.mjs", "pyodide.asm.wasm", "python_stdlib.zip")
PACKAGES = ("numpy", "pandas", "xlrd", "tzdata")  # and what they depend on
MARKER = ".instat-web-build"
STAMP = (2026, 1, 1, 0, 0, 0)

# the page loads only files of the site; the Python and WebAssembly run in the worker, which has its own (unrestricted) context
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; connect-src 'self' blob:; worker-src 'self'; "
       "base-uri 'none'; form-action 'none'")

THIRD_PARTY = """Software that the web version of INSTAT Explorer contains, served from this site

Pyodide {pyodide} (MPL-2.0)            https://pyodide.org  - Python for the browser (CPython 3.14, PSF licence)
numpy, pandas, xlrd (BSD-3-Clause)     https://numpy.org  https://pandas.pydata.org  https://github.com/python-excel/xlrd
python-dateutil (Apache-2.0 / BSD-3), pytz (MIT), six (MIT), tzdata (Apache-2.0)

INSTAT Explorer itself is under the MIT licence (LICENSE). The data it reads belong to INSTAT.
"""


def get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "instat-explorer-build"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def cached(cache: Path, name: str, url: str, check) -> bytes:
    """The file from the cache if it is there and passes ``check``, else downloaded (and checked, then cached)."""
    path = cache / name
    if path.is_file() and check(path.read_bytes()):
        return path.read_bytes()
    data = get(url)
    if not check(data):
        sys.exit(f"{url} is not the file this build expects (its hash differs from the pinned one). Refusing to use it.")
    cache.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def pyodide_files(cache: Path) -> tuple[dict[str, bytes], dict]:
    """The core files of Pyodide and its lock file, from the verified npm package."""
    def integrity_ok(data: bytes) -> bool:
        return "sha512-" + base64.b64encode(hashlib.sha512(data).digest()).decode() == PYODIDE_INTEGRITY

    tarball = cached(cache, f"pyodide-{PYODIDE}.tgz", PYODIDE_TARBALL, integrity_ok)
    with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as archive:
        files = {name: archive.extractfile(f"package/{name}").read() for name in (*CORE, "pyodide-lock.json")}  # type: ignore[union-attr]
    return files, json.loads(files.pop("pyodide-lock.json"))


def closure(lock: dict, names: tuple[str, ...]) -> list[str]:
    """The packages to ship: the ones asked for and everything they depend on, in a stable order."""
    seen: dict[str, None] = {}

    def add(name: str) -> None:
        if name in seen:
            return
        if name not in lock["packages"]:
            sys.exit(f"Pyodide {PYODIDE} has no package {name!r}.")
        seen[name] = None
        for dependency in lock["packages"][name].get("depends", []):
            add(dependency)

    for name in names:
        add(name)
    return sorted(seen)


def zip_of_package() -> bytes:
    """The instatkit package, with its data files, as a zip with fixed times and sorted entries (the same bytes from the same source)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted((ROOT / "instatkit").rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                info = zipfile.ZipInfo(path.relative_to(ROOT).as_posix(), STAMP)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                archive.writestr(info, path.read_bytes())
    return buffer.getvalue()


def page(language: str) -> str:
    """The start page in one language, for a static host: the sentences are put in now, the addresses are relative, the bridge is added."""
    i18n.set_language(language)
    html = server._page(server._asset("index.html")[0]).decode()
    for attribute, name in (("href", "chart.css"), ("href", "app.css"), ("src", "chart.js"), ("src", "app.js")):
        old = f'{attribute}="/{name}?'
        assert html.count(old) == 1, old
        html = html.replace(old, f'{attribute}="{name}?')
    html = html.replace('<meta charset="utf-8">', f'<meta charset="utf-8">\n<meta http-equiv="Content-Security-Policy" content="{CSP}">', 1)
    return html.replace('<script src="chart.js', f'<script src="bridge.js?v={__version__}" defer></script>\n<script src="chart.js', 1)


def build(out: Path, cache: Path) -> None:
    if out.exists():
        if not (out / MARKER).is_file() and any(out.iterdir()):
            sys.exit(f"{out} exists and was not made by this tool. Give a new or empty folder.")
        shutil.rmtree(out)
    (out / "pyodide").mkdir(parents=True)
    (out / MARKER).write_text("made by tools/build_web.py\n", encoding="utf-8")

    core, lock = pyodide_files(cache)
    names = closure(lock, PACKAGES)
    for name, data in core.items():
        (out / "pyodide" / name).write_bytes(data)
    trimmed = {"info": lock["info"], "packages": {name: lock["packages"][name] for name in names}}
    (out / "pyodide" / "pyodide-lock.json").write_text(json.dumps(trimmed, indent=1), encoding="utf-8", newline="\n")
    for name in names:
        entry = lock["packages"][name]
        wheel = cached(cache, entry["file_name"], PYODIDE_PACKAGES + entry["file_name"], lambda data, want=entry["sha256"]: hashlib.sha256(data).hexdigest() == want)
        (out / "pyodide" / entry["file_name"]).write_bytes(wheel)

    (out / "index.html").write_text(page("en"), encoding="utf-8", newline="\n")
    (out / "sq.html").write_text(page("sq"), encoding="utf-8", newline="\n")
    i18n.set_language("en")
    for name in ("app.js", "app.css", "chart.css", "chart.js"):
        (out / name).write_bytes(server._asset(name)[0])
    for name in ("bridge.js", "pyworker.js"):
        (out / name).write_bytes((ROOT / "webapp" / name).read_bytes())
    (out / "instatkit.zip").write_bytes(zip_of_package())
    (out / "LICENSE").write_bytes((ROOT / "LICENSE").read_bytes())
    (out / "THIRD-PARTY.txt").write_text(THIRD_PARTY.format(pyodide=PYODIDE), encoding="utf-8", newline="\n")
    (out / ".nojekyll").write_text("", encoding="utf-8")  # GitHub Pages: serve every file as it is


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, default=ROOT / "site", help="the folder to build into (replaced if an earlier build is there)")
    ap.add_argument("--cache", type=Path, default=ROOT / ".web-cache", help="where Pyodide is kept after it has been downloaded")
    args = ap.parse_args()
    build(args.out.resolve(), args.cache.resolve())
    files = [p for p in args.out.rglob("*") if p.is_file()]
    print(f"INSTAT Explorer {__version__} web version: {len(files)} files, {sum(p.stat().st_size for p in files) / 1e6:.1f} MB in {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
