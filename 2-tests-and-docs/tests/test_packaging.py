"""The release build: the parts of it that do not need Windows, the network or a compiler."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "packaging" / "build_release.py"


@pytest.fixture(scope="module")
def build():
    # loaded by path: a folder called "packaging" would shadow the PyPI library of that name if it were put on the import path
    spec = importlib.util.spec_from_file_location("instat_build_release", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_zips_do_not_depend_on_when_or_in_what_order_they_are_made(build, tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "one.txt").write_text("1")
    (tmp_path / "two.sh").write_text("#!/bin/sh\n")
    entries = [("z/two.sh", tmp_path / "two.sh"), ("z/a/one.txt", tmp_path / "a" / "one.txt")]
    first, second = tmp_path / "1.zip", tmp_path / "2.zip"
    build.write_zip(first, entries)
    (tmp_path / "a" / "one.txt").touch()  # a different modification time
    build.write_zip(second, list(reversed(entries)))  # a different order
    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first) as z:
        assert z.namelist() == ["z/a/one.txt", "z/two.sh"]
        assert {i.date_time for i in z.infolist()} == {build.STAMP}
        assert (z.getinfo("z/two.sh").external_attr >> 16) & 0o111, "launcher scripts must stay executable"


def test_text_files_of_the_build_have_unix_line_endings(build, tmp_path):
    # Path.write_text writes \r\n on Windows: that breaks `sha256sum -c` and the VERSION file the macOS/Linux launcher reads
    build.write_text(tmp_path / "VERSION", "0.10.1\n", "ascii")
    build.write_text(tmp_path / "BUILD-INFO.txt", "one\ntwo\n")
    assert (tmp_path / "VERSION").read_bytes() == b"0.10.1\n"
    assert (tmp_path / "BUILD-INFO.txt").read_bytes() == b"one\ntwo\n"


def test_shell_scripts_are_zipped_with_lf_endings(build, tmp_path):
    script, bat = tmp_path / "start.sh", tmp_path / "start.bat"
    script.write_bytes(b"#!/bin/sh\r\necho hi\r\n")
    bat.write_bytes(b"@echo off\r\necho hi\r\n")
    target = tmp_path / "z.zip"
    build.write_zip(target, [("start.sh", script), ("start.bat", bat)])
    with zipfile.ZipFile(target) as z:
        assert z.read("start.sh") == b"#!/bin/sh\necho hi\n"
        assert z.read("start.bat") == b"@echo off\r\necho hi\r\n", "Windows scripts keep their line endings"


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_the_shell_scripts_parse_and_have_no_carriage_returns():
    for name in ("start-instat-explorer.sh", "Start-INSTAT-Explorer.command"):
        path = ROOT / "packaging" / "unix" / name
        assert b"\r" not in path.read_bytes(), name
        assert subprocess.run(["bash", "-n", path.as_posix()], capture_output=True, check=False).returncode == 0, name


def test_tree_lists_files_with_forward_slashes(build, tmp_path):
    (tmp_path / "python" / "Lib").mkdir(parents=True)
    (tmp_path / "python" / "Lib" / "x.py").write_text("")
    (tmp_path / "VERSION").write_text("1")
    assert sorted(n for n, _p in build.tree(tmp_path, "root/")) == ["root/VERSION", "root/python/Lib/x.py"]  # (the order is the zip writer's job)


def test_tidy_install_removes_unstable_files(build, tmp_path):
    site = tmp_path / "site-packages"
    dist = site / "pkg-1.0.dist-info"
    dist.mkdir(parents=True)
    (site / "bin").mkdir()
    (site / "bin" / "pkg.exe").write_bytes(b"MZ")
    (dist / "direct_url.json").write_text("{}")
    (dist / "METADATA").write_text("Name: pkg\n")
    (dist / "RECORD").write_text(
        "pkg/__init__.py,sha256=aaa,10\r\n../../bin/pkg.exe,sha256=bbb,2\r\npkg-1.0.dist-info/METADATA,sha256=ccc,9\r\n"
        "pkg-1.0.dist-info/direct_url.json,sha256=ddd,2\r\npkg-1.0.dist-info/RECORD,,\r\n", encoding="utf-8", newline="")
    build._tidy_install(site)
    assert not (site / "bin").exists() and not (dist / "direct_url.json").exists() and (dist / "METADATA").exists()
    assert (dist / "RECORD").read_text(encoding="utf-8").splitlines() == [
        "pkg/__init__.py,sha256=aaa,10", "pkg-1.0.dist-info/METADATA,sha256=ccc,9", "pkg-1.0.dist-info/RECORD,,"]


def test_dependencies_are_pinned_within_the_allowed_range():
    import tomllib

    from packaging.requirements import Requirement  # (the PyPI library: the folder of the same name in this repository is never on the path)

    wanted = [Requirement(d) for d in tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["dependencies"]]
    pins = {}
    for line in (ROOT / "packaging" / "constraints.txt").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            name, _eq, version = line.partition("==")
            assert _eq, f"{line!r} is not pinned with =="
            pins[name.strip().lower()] = version.strip()
    for req in wanted:
        assert req.name.lower() in pins, f"{req.name} is not pinned in packaging/constraints.txt"
        assert req.specifier.contains(pins[req.name.lower()]), f"the pin {req.name}=={pins[req.name.lower()]} is outside {req.specifier}"


def test_the_launcher_scripts_and_source_are_in_the_repository():
    for rel in ("windows/Launcher.cs", "windows/Start-INSTAT-Explorer.bat", "windows/Check-installation.bat", "windows/README-FIRST.txt",
                "unix/start-instat-explorer.sh", "unix/Start-INSTAT-Explorer.command"):
        assert (ROOT / "packaging" / rel).is_file(), rel
    cs = (ROOT / "packaging" / "windows" / "Launcher.cs").read_text(encoding="utf-8")
    assert "INSTAT_APP_DIR" in cs and "payload.zip" in cs and "Unexpected path in the payload" in cs


def test_the_unix_launcher_installs_the_wheel_of_the_same_version():
    sh = (ROOT / "packaging" / "unix" / "start-instat-explorer.sh").read_text(encoding="utf-8")
    assert 'instat-explorer==$WANT' in sh and "VERSION" in sh
