"""Build the release files from this checkout.

    python packaging/build_release.py --out dist

Output, in ``dist``:

    INSTAT-Explorer-<v>-windows.exe            stand-alone launcher with the program inside (unpacks itself on first start)
    INSTAT-Explorer-<v>-windows-portable.zip   the same as a folder: Start-INSTAT-Explorer.bat, python\\, INSTAT-Explorer.exe
    INSTAT-Explorer-<v>.zip                    for macOS and Linux, or Windows with Python: the wheel and the launcher scripts
    SHA256SUMS.txt, BUILD-INFO.txt

The Windows files contain the wheel built here, the dependency wheels (win_amd64, same Python minor version as the embedded one; the versions
are pinned in ``constraints.txt``, ``--latest`` takes the newest) and the embeddable Python from python.org. They need Windows: the launcher is
compiled with the csc.exe of .NET Framework 4. The zip for macOS and Linux can be made anywhere. Nothing is signed.

With the same inputs the wheel, the payload (what the .exe unpacks) and the zip for macOS and Linux are byte-identical whichever folder or day the
build runs in, on the same operating system (the wheel's metadata file takes the line endings of the system that builds it); ``BUILD-INFO.txt`` records their hashes. The two .exe files differ between builds: the compiler stamps a time and a GUID into every executable.

Needs ``pip install build``. Downloads (cached in ``dist/cache``): the embeddable Python and the wheels of pandas, numpy and their dependencies.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from instatkit import __version__  # noqa: E402

STAMP = (2026, 1, 1, 0, 0, 0)  # every file in a zip gets this time: the build does not depend on when it is made
EPOCH = 1767225600  # the same moment, 2026-01-01 00:00 UTC, as seconds


def run(cmd: list[str | Path], **kw) -> None:
    print("  $", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    """Write a text file with ``\\n`` line endings on every platform. (``Path.write_text`` on Windows writes ``\\r\\n``, which breaks
    ``sha256sum -c`` and the ``VERSION`` file that the launcher script of macOS and Linux reads.)"""
    path.write_bytes(text.encode(encoding))


def write_zip(target: Path, entries: list[tuple[str, Path]]) -> None:
    """A zip of ``(name in the zip, file)`` with sorted entries and fixed timestamps. Shell scripts are stored with ``\\n`` line endings
    even if a checkout on Windows turned them into ``\\r\\n``: a script with ``\\r`` in it does not run."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for name, path in sorted(entries):
            info = zipfile.ZipInfo(name, STAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if path.suffix in (".sh", ".command", ".exe") else 0o644) << 16
            data = path.read_bytes()
            z.writestr(info, data.replace(b"\r\n", b"\n") if path.suffix in (".sh", ".command") else data)


def tree(folder: Path, prefix: str = "") -> list[tuple[str, Path]]:
    return [(prefix + p.relative_to(folder).as_posix(), p) for p in sorted(folder.rglob("*")) if p.is_file()]


def build_wheel(out: Path) -> Path:
    """The wheel, built from a copy so that the checkout gets no ``build`` or ``egg-info`` folders."""
    src, wheels = out / "buildsrc", out / "wheel"
    shutil.rmtree(src, ignore_errors=True)
    shutil.rmtree(wheels, ignore_errors=True)
    shutil.copytree(ROOT / "instatkit", src / "instatkit", ignore=shutil.ignore_patterns("__pycache__"))
    for name in ("pyproject.toml", "README.md", "LICENSE"):
        shutil.copy2(ROOT / name, src / name)
    env = {**os.environ, "SOURCE_DATE_EPOCH": str(EPOCH)}  # setuptools stamps the files of the wheel with this instead of the time of the build
    run([sys.executable, "-m", "build", "--wheel", "--outdir", wheels, src], env=env)
    shutil.rmtree(src, ignore_errors=True)
    return next(wheels.glob("*.whl"))


def embeddable_python(out: Path, version: str, expected: str | None) -> tuple[Path, str]:
    cache = out / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    name = f"python-{version}-embed-amd64.zip"
    archive = cache / name
    if not archive.exists():
        url = f"https://www.python.org/ftp/python/{version}/{name}"
        print(f"  downloading {url}", flush=True)
        req = urllib.request.Request(url, headers={"User-Agent": "instat-explorer-build"})
        with urllib.request.urlopen(req, timeout=120) as r, archive.open("wb") as f:
            shutil.copyfileobj(r, f)
    digest = sha256(archive)
    if expected and digest != expected.lower():
        archive.unlink()
        sys.exit(f"The embeddable Python has the SHA-256 {digest}, not {expected}. Refusing to use it.")
    return archive, digest


def _tidy_install(site: Path) -> None:
    """Remove what pip leaves that the program does not use and that would change from build to build, and the ``RECORD`` lines for it:
    the console scripts in ``bin`` (the launcher starts the program itself) and ``direct_url.json`` (the folder the wheel was in)."""
    for note in site.glob("*.dist-info/direct_url.json"):
        note.unlink()
    shutil.rmtree(site / "bin", ignore_errors=True)
    for record in site.glob("*.dist-info/RECORD"):
        gone = (f"{record.parent.name}/direct_url.json,", "../../bin/")
        kept = [line for line in record.read_text(encoding="utf-8").splitlines(keepends=True) if not line.startswith(gone)]
        record.write_text("".join(kept), encoding="utf-8", newline="")


def stage_windows(out: Path, wheel: Path, python_zip: Path, py_version: str, *, pinned: bool = True) -> Path:
    """The folder that is the portable program: python\\ with every package installed, and the program's own files."""
    stage = out / "stage" / f"INSTAT-Explorer-{__version__}"
    shutil.rmtree(out / "stage", ignore_errors=True)
    py = stage / "python"
    with zipfile.ZipFile(python_zip) as z:
        z.extractall(py)
    minor = "".join(py_version.split(".")[:2])
    pth = py / f"python{minor}._pth"
    write_text(pth, f"python{minor}.zip\n.\nLib\\site-packages\nimport site\n")  # the embeddable Python ignores site-packages otherwise
    site = py / "Lib" / "site-packages"
    site.mkdir(parents=True)
    major_minor = ".".join(py_version.split(".")[:2])
    pins = ["-c", ROOT / "packaging" / "constraints.txt"] if pinned else []
    run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-compile", "--only-binary=:all:", "--target", site,
         "--platform", "win_amd64", "--python-version", major_minor, "--implementation", "cp", "--abi", f"cp{minor}", *pins, wheel])
    for folder in sorted(site.rglob("tests"), reverse=True):  # pandas and numpy ship their own test suites: 55 MB nobody needs to run
        if folder.is_dir():
            shutil.rmtree(folder)
    _tidy_install(site)
    # compile once now: the first start is then not slow. "unchecked-hash" keeps file times out of the result and -d keeps the folder
    # the build ran in out of it (Python puts the real path back when it imports the file)
    run([py / "python.exe", "-m", "compileall", "-q", "-d", "site-packages", "--invalidation-mode", "unchecked-hash", site])
    for name in ("LICENSE", "README.md"):
        shutil.copy2(ROOT / name, stage / name)
    write_text(stage / "VERSION", __version__ + "\n", "ascii")
    return stage


def compile_launcher(out: Path, exe: Path, payload: Path | None) -> None:
    windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
    csc = next((p for p in (windir / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe",
                            windir / "Microsoft.NET" / "Framework" / "v4.0.30319" / "csc.exe") if p.exists()), None)
    if csc is None:
        sys.exit("csc.exe (the compiler of .NET Framework 4) was not found; it comes with Windows.")
    info = out / "AssemblyInfo.cs"
    v = f"{__version__}.0"
    info.write_text(
        "using System.Reflection;\n"
        '[assembly: AssemblyTitle("INSTAT Explorer")]\n'
        '[assembly: AssemblyDescription("Reads, cleans and explains the Excel tables published by INSTAT, the Institute of Statistics of Albania")]\n'
        '[assembly: AssemblyProduct("INSTAT Explorer")]\n'
        '[assembly: AssemblyCopyright("MIT licence. An independent project, not affiliated with INSTAT.")]\n'
        f'[assembly: AssemblyVersion("{v}")]\n[assembly: AssemblyFileVersion("{v}")]\n', encoding="utf-8")
    cmd: list[str | Path] = [csc, "/nologo", "/target:exe", "/optimize+", f"/out:{exe}", "/reference:System.IO.Compression.dll",
                             "/reference:System.IO.Compression.FileSystem.dll"]
    if payload is not None:
        cmd.append(f"/resource:{payload},payload.zip")
    run([*cmd, ROOT / "packaging" / "windows" / "Launcher.cs", info])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default="dist", type=Path)
    ap.add_argument("--python", default="3.14.7", help="version of the embeddable Python from python.org")
    ap.add_argument("--python-sha256", help="refuse the embeddable Python unless it has this SHA-256")
    ap.add_argument("--no-windows", action="store_true", help="only the zip for macOS and Linux")
    ap.add_argument("--latest", action="store_true", help="take the newest pandas, numpy and the rest instead of the versions in packaging/constraints.txt")
    args = ap.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    v = __version__
    print(f"INSTAT Explorer {v}\n1/4 wheel", flush=True)
    wheel = build_wheel(out)
    results: list[Path] = []
    info = [f"INSTAT Explorer {v}", f"wheel {wheel.name} sha256 {sha256(wheel)}"]

    print("2/4 zip for macOS, Linux and Windows with Python", flush=True)
    unix = [(f"INSTAT-Explorer-{v}/wheel/{wheel.name}", wheel), (f"INSTAT-Explorer-{v}/LICENSE", ROOT / "LICENSE"),
            (f"INSTAT-Explorer-{v}/README.md", ROOT / "README.md")]
    unix += [(f"INSTAT-Explorer-{v}/{p.name}", p) for folder in ("unix", "windows") for p in sorted((ROOT / "packaging" / folder).iterdir())
             if p.suffix in (".sh", ".command", ".bat", ".txt")]
    version_file = out / "VERSION"
    write_text(version_file, v + "\n", "ascii")
    unix.append((f"INSTAT-Explorer-{v}/VERSION", version_file))
    zip_unix = out / f"INSTAT-Explorer-{v}.zip"
    write_zip(zip_unix, unix)
    results.append(zip_unix)

    if not args.no_windows:
        if sys.platform != "win32":
            sys.exit("The Windows files can only be built on Windows (use --no-windows for the other zip).")
        print("3/4 the program folder (python, packages, launcher)", flush=True)
        python_zip, python_hash = embeddable_python(out, args.python, args.python_sha256)
        info.append(f"embedded Python {args.python} ({python_zip.name}) sha256 {python_hash}")
        stage = stage_windows(out, wheel, python_zip, args.python, pinned=not args.latest)
        info.append("package versions: " + ("the newest (--latest)" if args.latest else "pinned in packaging/constraints.txt"))
        payload = out / "payload.zip"
        write_zip(payload, tree(stage))  # exactly what the stand-alone exe unpacks
        info.append(f"payload (everything the .exe unpacks) sha256 {sha256(payload)}")
        info.append("packages " + ", ".join(sorted(p.name.removesuffix(".dist-info") for p in (stage / "python" / "Lib" / "site-packages").glob("*.dist-info"))))
        for name in ("Start-INSTAT-Explorer.bat", "Check-installation.bat", "README-FIRST.txt"):
            shutil.copy2(ROOT / "packaging" / "windows" / name, stage / name)

        print("4/4 launchers and zips", flush=True)
        exe_standalone = out / f"INSTAT-Explorer-{v}-windows.exe"
        compile_launcher(out, exe_standalone, payload)
        compile_launcher(out, stage / "INSTAT-Explorer.exe", None)
        portable = out / f"INSTAT-Explorer-{v}-windows-portable.zip"
        write_zip(portable, tree(stage, f"INSTAT-Explorer-{v}/"))
        payload.unlink()
        results = [exe_standalone, portable, *results]

    sums = "".join(f"{sha256(p)} *{p.name}\n" for p in sorted(results, key=lambda p: p.name))
    write_text(out / "SHA256SUMS.txt", sums, "ascii")
    write_text(out / "BUILD-INFO.txt", "\n".join(info) + "\n")
    print("\n" + sums)
    return 0


if __name__ == "__main__":
    sys.exit(main())
