"""The web version's build and its scripts. The build needs no network here: the Pyodide download is replaced by a few bytes."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "tools" / "build_web.py"


@pytest.fixture(scope="module")
def web():
    spec = importlib.util.spec_from_file_location("instat_build_web", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    del sys.modules[spec.name]


def fake_lock():
    def entry(name, depends=()):
        wheel = f"{name}-1.0-py3-none-any.whl"
        return {"name": name, "version": "1.0", "file_name": wheel, "sha256": hashlib.sha256(wheel.encode()).hexdigest(), "depends": list(depends)}

    packages = {"numpy": entry("numpy"), "pandas": entry("pandas", ["numpy", "python-dateutil", "pytz"]), "python-dateutil": entry("python-dateutil", ["six"]),
                "pytz": entry("pytz"), "six": entry("six"), "xlrd": entry("xlrd"), "tzdata": entry("tzdata"), "scipy": entry("scipy", ["numpy"])}
    return {"info": {"python": "3.14.2"}, "packages": packages}


def test_the_page_is_ready_for_a_static_host(web):
    html = web.page("en")
    assert 'lang="en"' in html and "{{" not in html
    for name in ("chart.css", "app.css"):
        assert f'href="{name}?v=' in html
    assert 'src="chart.js?v=' in html and 'src="app.js?v=' in html
    assert 'href="/' not in html.replace("href=\"/\"", "") and 'src="/' not in html, "addresses must be relative: the site may live in a sub-folder"
    assert html.index("bridge.js") < html.index('src="chart.js') < html.index('src="app.js'), "the bridge must run before the page script"
    assert 'http-equiv="Content-Security-Policy"' in html and "script-src 'self'" in html and "unsafe" not in html


def test_each_language_has_its_own_page(web):
    english, albanian = web.page("en"), web.page("sq")
    assert 'lang="sq"' in albanian and 'lang="en"' in english and english != albanian
    assert ">Shqip<" in english and ">English<" in albanian, "the language button offers the other language"
    assert "Skip to the results" in english and "Skip to the results" not in albanian, "the sentences of the page are put in at build time"


def test_dependencies_of_the_packages_are_shipped_and_nothing_else(web):
    assert web.closure(fake_lock(), ("numpy", "pandas", "xlrd", "tzdata")) == ["numpy", "pandas", "python-dateutil", "pytz", "six", "tzdata", "xlrd"]
    with pytest.raises(SystemExit):
        web.closure(fake_lock(), ("not-a-package",))


def test_the_package_zip_has_the_data_files_and_is_the_same_every_time(web):
    first, second = web.zip_of_package(), web.zip_of_package()
    assert first == second
    names = set(zipfile.ZipFile(io.BytesIO(first)).namelist())
    assert {"instatkit/__init__.py", "instatkit/web/embedded.py", "instatkit/data/sq.json", "instatkit/viz/chart.js", "instatkit/export/report.css"} <= names
    assert not [n for n in names if "__pycache__" in n or n.endswith(".pyc")]


def test_a_download_with_the_wrong_hash_is_refused_and_not_kept(web, tmp_path, monkeypatch):
    monkeypatch.setattr(web, "get", lambda url: b"something else")
    with pytest.raises(SystemExit):
        web.cached(tmp_path, "pyodide.tgz", "https://example.invalid/pyodide.tgz", lambda data: data == b"the real file")
    assert not list(tmp_path.iterdir())
    monkeypatch.setattr(web, "get", lambda url: b"the real file")
    assert web.cached(tmp_path, "pyodide.tgz", "https://example.invalid/pyodide.tgz", lambda data: data == b"the real file") == b"the real file"
    monkeypatch.setattr(web, "get", lambda url: pytest.fail("a cached file that passes the check is not downloaded again"))
    assert web.cached(tmp_path, "pyodide.tgz", "https://example.invalid/pyodide.tgz", lambda data: data == b"the real file") == b"the real file"


def test_the_site_is_built_from_the_verified_pieces(web, tmp_path, monkeypatch):
    core = {name: name.encode() for name in web.CORE}
    monkeypatch.setattr(web, "pyodide_files", lambda cache: (dict(core), fake_lock()))
    monkeypatch.setattr(web, "cached", lambda cache, name, url, check: name.encode())
    site = tmp_path / "site"
    web.build(site, tmp_path / "cache")
    names = {p.relative_to(site).as_posix() for p in site.rglob("*") if p.is_file()}
    assert {"index.html", "sq.html", "app.js", "app.css", "chart.js", "chart.css", "bridge.js", "pyworker.js", "instatkit.zip", "LICENSE", "THIRD-PARTY.txt", ".nojekyll",
            "pyodide/pyodide.mjs", "pyodide/pyodide.asm.wasm", "pyodide/python_stdlib.zip", "pyodide/pyodide-lock.json"} <= names
    lock = json.loads((site / "pyodide" / "pyodide-lock.json").read_text(encoding="utf-8"))
    assert sorted(lock["packages"]) == ["numpy", "pandas", "python-dateutil", "pytz", "six", "tzdata", "xlrd"], "only what the program needs is served"
    assert all((site / "pyodide" / p["file_name"]).is_file() for p in lock["packages"].values())
    assert "\r" not in (site / "index.html").read_text(encoding="utf-8")
    (site / "stale.txt").write_text("from an earlier build")
    web.build(site, tmp_path / "cache")
    assert not (site / "stale.txt").exists(), "an earlier build is replaced, not added to"


def test_a_folder_that_is_not_a_build_is_never_emptied(web, tmp_path):
    precious = tmp_path / "my-documents"
    precious.mkdir()
    (precious / "thesis.docx").write_text("do not delete")
    with pytest.raises(SystemExit):
        web.build(precious, tmp_path / "cache")
    assert (precious / "thesis.docx").read_text() == "do not delete"


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
@pytest.mark.parametrize("relative", ["instatkit/web/static/app.js", "instatkit/viz/chart.js", "webapp/bridge.js", "webapp/pyworker.js"])
def test_the_scripts_parse(relative, tmp_path):
    source = ROOT / relative
    target = tmp_path / (source.stem + (".mjs" if relative.endswith("pyworker.js") else ".js"))  # the worker is an ES module
    target.write_bytes(source.read_bytes())
    done = subprocess.run(["node", "--check", str(target)], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
