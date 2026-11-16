# Installing and running it

For a teacher, a lab administrator or an IT department. No server, no database, no account and no administrator rights are needed.

## Choose how to run it

| You have | Use | Needs |
|---|---|---|
| Windows 10 or 11, 64-bit, and want it to just work | `INSTAT-Explorer-<version>-windows.exe` from the Releases page | nothing; Python is inside. The first start unpacks about 100 MB into your user folder and takes about a minute |
| Windows, and the `.exe` is blocked or you want it on a USB stick | `...-windows-portable.zip`: unzip the whole folder, open `Start-INSTAT-Explorer.bat` | nothing |
| macOS, Linux, or Windows with Python | `python -m pip install .` then `instat-explorer` | Python 3.11 or newer, 64-bit. Installs pandas, numpy and xlrd |
| A source checkout, to work on it | `python -m pip install -e ".[dev]"` | the same |

Check an installation: `instat doctor` (or `Check-installation.bat` in the portable zip). Add `--online` to test that instat.gov.al can be
reached. It checks Python, the libraries, that the data folder can be written to, that a demo file can be read, analysed and exported,
and that the web server starts and enforces its access link.

**Verify what you downloaded.** Each release has a `SHA256SUMS.txt`. On Windows: `Get-FileHash <file> -Algorithm SHA256`, and compare.

## Where things go

| | Default | To change it |
|---|---|---|
| Downloaded files, the download manifest, `instat process` exports | `%LOCALAPPDATA%\INSTAT-Explorer` (portable zip: the `data` folder next to the program; a source checkout: `data` inside it) | set `INSTAT_DATA_DIR` |
| Where the `.exe` unpacks itself | `%LOCALAPPDATA%\Programs\INSTAT-Explorer\<version>` | set `INSTAT_APP_DIR` (keep the path short: Windows refuses paths over 260 characters) |
| Exports you save from the app | the browser's download folder | the browser's setting |

If the data folder cannot be written to (a locked-down PC), a temporary folder is used for that session and the program says so.
There is nothing to install: to remove the program, delete those folders.

## In a computer lab

* Copy the program to the **local disk** first, not a network drive.
* The `.exe` and the zip need no administrator rights and no internet. The program goes online only when someone asks it to fetch
  something from instat.gov.al.
* One computer can serve a whole class: `instat-explorer --share` (or `INSTAT-Explorer.exe serve --share`). The others open the address it
  prints. **It is plain HTTP and anyone with the address can use it**: use a trusted network, and see `SECURITY_AND_PRIVACY.md`.
  Windows may ask to allow the program through its firewall on the first run. If it does not appear, allow the port (8501, or the next free one).
* The Windows files are not code-signed. A policy that only allows signed programs (Smart App Control, AppLocker) will refuse the `.exe`, and
  may refuse the compiled parts of numpy and pandas as well. Ask IT to allow the program folder, or run it from Python.
* Offline: everything except fetching from instat.gov.al works without internet. A file you downloaded earlier can be uploaded from disk.

## Running it

```
instat-explorer                  # the app; opens your browser on an address like http://127.0.0.1:8501/?t=...
instat-explorer --no-browser     # print the address only
instat-explorer --port 9000      # the first port to try
instat-explorer --share          # let others on the network use it (see above)
instat search inflation          # find a topic (works offline)
instat files inflation           # list the Excel files on a topic page
instat process table.xlsx --export html,csv,xlsx,sqlite,md,zip --out results
instat inspect table.xlsx        # show how a file is read, without exporting
instat doctor --online
```

Add `--lang sq` (or set `INSTAT_LANG=sq`) for Albanian. Exit codes: 0 success, 1 nothing found or nothing readable, 2 a bad argument or a
failed download, 130 stopped with Ctrl+C. Messages about problems go to the error stream, so redirecting the output keeps only results.

## Upgrading

Install or unpack the new version; the data folder is kept. The `.exe` removes older unpacked versions of itself.

## The web version

A copy of the program that needs nothing installed: a static site, `python tools/build_web.py --out site`, that any web server can host (about 22 MB). On
GitHub, switch on Pages (Source: GitHub Actions) and `.github/workflows/pages.yml` publishes it. For a lab or an intranet, copy the folder to any web
server; it makes no request to the internet. `WEB.md` describes what it can and cannot do.

## Making the release files

They are built from this repository:

```
python -m pip install build
python packaging/build_release.py --out dist
```

That makes the stand-alone `.exe`, the portable zip, the zip for macOS and Linux, `SHA256SUMS.txt` and `BUILD-INFO.txt`. Windows is needed for
the first two. The `.exe` is a small launcher (`packaging/windows/Launcher.cs`, compiled with the compiler that ships with Windows, no SDK) that
unpacks an embedded Python 3.14 with pandas, numpy, xlrd and the program the first time it runs. The portable zip is the same folder without
the unpacking. The embeddable Python is downloaded from python.org (pass `--python-sha256` to insist on a known file).

What comes out the same: with the same inputs, the wheel, the payload (everything the stand-alone `.exe` unpacks) and the zip for macOS and Linux
are identical byte for byte, whichever folder or day the build runs in. This was checked by building twice in two different folders on Windows and
comparing every file; the wheel's metadata file takes the line endings of the system that builds it, so a build on another system is compared by content, not by hash. `BUILD-INFO.txt` records their hashes and the version of every package, so anyone can build again and compare. The inputs
are this checkout, the embeddable Python and the versions of pandas, numpy and the rest, which are pinned in `packaging/constraints.txt` so that
building again next month gives the same files (`--latest` takes the newest instead; `BUILD-INFO.txt` lists the versions that went in, so a
different hash can always be traced to a different version). What does not come out the same: the two `.exe` files. The
compiler stamps a time and a GUID into every executable, so the stand-alone `.exe` and the portable zip (which holds a copy of the launcher)
differ from build to build in those few bytes, and nowhere else. A reviewer who wants to check the portable zip compares it with their own
build except for `INSTAT-Explorer.exe`.
**Nothing is signed.** Signing needs a certificate and is the last step of a release (`signtool sign ...`), after which the checksums are made again.

To test the file you made as a person would receive it, run the browser check on the `.exe` itself (use a short folder for `INSTAT_APP_DIR`: Windows
stops at 260 characters and pandas has deep paths):

```
set INSTAT_APP_DIR=C:\instat-app
python tools/screenshots.py --exe dist\INSTAT-Explorer-0.10.1-windows.exe --out shots --xlsx some-real-file.xlsx
```

It unpacks the program, clicks through every screen in Edge, Chrome or Chromium, ends it with its own Stop button and exits with
code 0 only if the browser reported nothing and the program ended by itself. The pictures it saves show the real file.
