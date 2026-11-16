# The web version

INSTAT Explorer also runs as a web page with nothing to install: open it, drop in an Excel or CSV file, and read the results. It is the same program
(the same Python code and the same page), running inside the visitor's browser. **Files are read in the browser and are never sent to a server**:
the site is only a set of static files.

## How it works

```
page (app.js)  --/api/... request-->  bridge.js  -->  Web Worker (pyworker.js)  -->  Pyodide: Python 3.14 + numpy + pandas + xlrd
                                                                                      runs instatkit.web.embedded.handle()
```

The page asks for `/api/state`, `/export?...` and so on exactly as it does a local server. `bridge.js` hands each request to a Web Worker that runs the
program's own Python (through [Pyodide](https://pyodide.org)), and returns the reply. Pyodide, numpy, pandas and xlrd are served from the site
itself, checked against pinned hashes when the site is built, so a visitor's browser contacts no other server (no CDN, no analytics).

## What it does and does not do

- It opens **uploaded files** (`.xlsx`, `.xls`, Excel 2003 XML, `.csv`) and the **demos**, and gives every tab and every export of the local program:
  insights, explore, clean data, how it was read (with corrections), quality, and the HTML report, CSV, Excel, SQLite and zip.
- It cannot search or download from instat.gov.al: a browser does not let a page read another site's files (cross-origin rules). Download the file
  from INSTAT's page and upload it. The page says so.
- Nothing is kept between visits: the open files live in the page. Switching language opens the other language's page, so open files are closed.
- The first visit downloads about 22 MB (the Python interpreter and libraries); the browser keeps them. Starting takes a few seconds. A file takes
  0.1 to 7 seconds to read in the tests (the 73-table agriculture yearbook, 325 KB, took 7).
- Very large files may exhaust the memory a browser gives one tab; the local program is the better tool for those.
- It needs a current Chrome, Edge, Firefox or Safari (module Web Workers and WebAssembly). It does not work from a `file://` address: serve the
  folder over http(s).

## Is it the same program?

The same code. On 12 real INSTAT files (the wage workbook with Roman-numeral quarters, a legacy `.xls` census table, the 13-table GDP workbook,
consumer prices, labour force, births, building permits, tourism, trade, electricity, a census cross-tabulation, the 73-table agriculture yearbook)
the clean data exported by the web version is identical to the local program's, table by table. The only differences are the ones the system makes:
a CSV written on Windows ends its lines with CR LF, the web version with LF, and the byte-order mark at the start is dropped by the browser's decoder.
The web version has pandas 3.0 (what Pyodide ships), the local program the pandas it was installed with.

## Hosting it

```
python tools/build_web.py --out site        # needs only Python and an internet connection the first time
python -m http.server -d site               # to try it: http://localhost:8000
```

`site` is a folder of static files (about 22 MB) that any web host can serve. On GitHub, switch on Pages once (Settings, Pages, Source: *GitHub
Actions*): the workflow `.github/workflows/pages.yml` then builds and publishes the site on every push to `main`, at
`https://<owner>.github.io/<repository>/`. The folder works from a sub-folder as well, because every address in it is relative.

The build downloads Pyodide once into `.web-cache` and refuses anything whose hash differs from the one pinned in `tools/build_web.py`
(Pyodide 314.0.7, Python 3.14.2, pandas 3.0.2). To move to a newer Pyodide, change the version and the pinned hash together and run
`python tools/screenshots.py --web site` to check the result in a browser. `site/THIRD-PARTY.txt` lists what the site contains and under which
licence (Pyodide is MPL-2.0).

## Testing

`python tools/screenshots.py --web site` serves the built site and runs the journey of the local program in a real browser: demo, every tab, Albanian,
a phone-sized screen, the exported report, real files, a file that is not a spreadsheet. It fails on any console error, failed request or
Content-Security-Policy violation. The page carries a strict policy of its own (`script-src 'self'`, no inline script or style).
