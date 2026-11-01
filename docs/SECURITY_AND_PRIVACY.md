# Security and privacy

What the program does with your computer, your files and the network; how it is protected; and what is left. Everything here is
checked by tests in `tests/test_server.py` and `tests/test_readers.py`, or can be seen in `instatkit/web/server.py` and
`instatkit/sources/fetch.py`.

## What leaves the computer

Nothing, unless you ask for a download. There are no accounts, no analytics, no update checks and no crash reports.

When you search, paste a link or choose files, the program makes ordinary `GET` requests to **instat.gov.al** for the page or the
file you chose, one at a time with a pause between them, and identifies itself as
`instatkit/<version> (free educational tool; one request at a time)`. It sends nothing else: no file names from your computer,
no content of anything you opened, no identifiers.

Files you upload are read in memory and never written to disk. Downloaded files and what you export are kept in the data folder
(`%LOCALAPPDATA%\INSTAT-Explorer`, or the folder in `INSTAT_DATA_DIR`).

## Who can use the running program

The app is a small web server. By default it listens on **127.0.0.1 only**: other computers cannot reach it.

* **Access link.** Every start makes a new random token. The link the program opens carries it once; the browser then keeps it in a cookie
  (`HttpOnly`, `SameSite=Strict`, one cookie per port so that a second copy does not log out the first). Without it every address answers
  "403". The token is compared in constant time.
* **Other web pages on the same computer** cannot use it: a page on another site cannot read the cookie, and writes also need a
  custom header and a matching `Origin`.
* **DNS rebinding**: the `Host` header must be one of the program's own addresses.
* **Browser protections**: a strict Content-Security-Policy (no inline script, no inline style, nothing loaded from elsewhere),
  `X-Content-Type-Options`, `Referrer-Policy: no-referrer`, no caching of replies.
* **Limits**: request bodies are capped (1 MB for requests, 50 MB for an uploaded file) and chunked uploads are refused. A refused
  request is answered at once.
* Only `GET` and `POST` exist; there is no path that reads a file from disk by name, so nothing like `../../` can reach the file system.

## Files from outside are treated as hostile

Spreadsheets come from the internet or from users. The readers (`instatkit/excel/`) are bounded: rows, columns, cells, sheets,
merged ranges, uncompressed size and zip entries all have limits (`instatkit/config.py`), documents with a `DOCTYPE` or XML entities are
refused, nothing is extracted to disk, and a file that cannot be read ends in a message. The period parser cannot be made to take
exponential time (a header of 50 asterisks used to freeze it). The tests include each of these cases.

Output is escaped: text from a file is escaped in the HTML report, in the charts (SVG) and in the web page (which builds its DOM with
`textContent`); Excel labels that start with `=` are stored as text, so they cannot run as formulas.

## What the program downloads

By default only from `instat.gov.al`. A link elsewhere needs an explicit "I trust the source" confirmation. Every redirect is checked
before it is followed: http or https only, and a host that does not resolve to a local or private network address. Downloads are capped
at 50 MB, must really be a spreadsheet (an HTML error page served with status 200 is refused) and are saved under the hash of their
content. The listing of a topic page is limited to instat.gov.al.

## The web version

The web version (`docs/WEB.md`) is a static site: there is no server-side program and no access token, because nothing is stored or processed on a
server. A visitor's files are read by Python running inside their own browser tab and are gone when the tab closes. The browser contacts only the
site it was loaded from: Pyodide, numpy, pandas and xlrd are served from that site, checked against hashes pinned in `tools/build_web.py`, and
there is no CDN, analytics or font service. The page carries a Content-Security-Policy of its own (`script-src 'self'`, no inline script or style,
`connect-src 'self'`). Whoever hosts the site can see that it was visited, as for any web page, but not the files. Files are limited by the memory a
browser gives one tab.

## Dependencies

Three libraries: pandas, numpy and xlrd (the reader for the old `.xls` format; Excel 2007+ files and Excel 2003 XML are read by
the program's own code on the standard library). No other package is needed to run it.

## What remains

These are known and chosen; know them before deploying.

* **`--share` is plain HTTP.** In a lab, the access link and the data travel unencrypted on the local network, the `Host` check is off,
  and anyone who gets the link can use the program (but not stop it). Use it only on a trusted network, and keep the link inside the room.
* **The check against private addresses** resolves a host name once to check it and once to connect, so it is a safeguard for a program
  on someone's PC, not a firewall. Addresses of instat.gov.al itself are trusted.
* **The Windows `.exe` and the portable zip are not code-signed.** Windows warns on the first start, and a policy that allows only signed
  programs (Smart App Control, AppLocker) will refuse them. Verify downloads against `SHA256SUMS.txt`; a signing certificate is the fix.
* **A CSV opened in Excel** can treat a text cell that starts with `=`, `+`, `-` or `@` as a formula. The labels in INSTAT's files are
  data and are exported unchanged; the Excel export stores them as text.
* **No third-party security review** has been done. The tests above are the author's. They include, run on every change, `bandit` over the
  program (no findings; each of the few places it first flagged was looked at and is explained in a comment next to the code), tests of the
  download layer against played-back answers (private and local addresses, look-alike host names, redirects, size limits, a database entry that
  points outside the cache), and a run in a real browser that fails on any Content-Security-Policy violation (`tools/screenshots.py`).

Report a vulnerability by opening an issue at https://github.com/JXH-DEV/Instat-Statistical-Tool/issues, or by writing to the repository owner.
