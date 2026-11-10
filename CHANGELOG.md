# Changelog

## 0.10.1 (2026-11-01)

Fixes and hardening, no new features. The Windows `.exe` and portable zip of 0.10.0 do not contain these fixes.

### Fixed: results

- Quarters written as Roman numerals (`II/23`, `I - 22`, `IV 2023`, `2023/II`, `Quarter II 2026`, `Tremujori II 2024`) are periods. Seven real
  INSTAT files (wages, building permits, births, deaths, electricity balance) were read as one-year snapshots.
- A thousand marker written against the currency (`000Lekë / 000ALL`) is recognised. Building-permit values were labelled "buildings".
- A canonical label such as `2005-06` is June 2005, not the years 2005 and 2006.
- `10,000 inhabitants` is not "in thousands", the English word "all" is not the currency ALL, and `0,500` is 0.5.
- Years down the rows with quarters or half-years across the columns are no longer labelled monthly.
- Found by the tests written to check the tests (see `docs/EVIDENCE.md`, section 5). None of the 148 real files changes (their clean data is
  identical), but these were wrong:
  * the Albanian word `përqindje` was not a percentage; an index "December of the previous year = 100" or "same month of the previous year = 100"
    was read as "previous year = 100";
  * month and quarter names written in both languages in one cell (`Janar / January`, `Tr.1 / Q1`) were not months and quarters, so a table with
    years down the rows and such headers across was read as an annual one;
  * a series that rises by the same step every month was reported to have "unusual" months (rounding noise of 1e-16 was taken for variation) and
    "a change of pattern" (a steady rise also splits into a low half and a high half); the swing of the seasons was reported as a change of
    pattern too. A jump is now reported only when two levels describe the data at least twice as well as a straight line, and not in a series
    with strong seasons;
  * a ranking of three categories named the middle one as both the highest and the lowest;
  * a value of exactly zero was written `ALL 0.0000`.
- Found by the second round of such tests, and by a check of the findings on the real files (`narration_digest` over 150 files, old code against
  new; nothing crashes, 16 files tell a different story, all of them for the reasons below):
  * numbers are rounded the way people and Excel round: a half goes up (`6.25` is `6.3`, `2.675` is `2.68`). Python's `format` rounds half to
    even and a float cannot hold 2.675, so figures in sentences, charts, tooltips and exports could be one unit of the last digit lower than the
    cell they came from;
  * `(5%)` and `(-5%)` are percentages written in the accounting style, not text;
  * a seasonal pattern is reported only if it also holds in the years it was not fitted on (each year is left out in turn and predicted from the
    others). The old test judged the fit on the same data, so 75 % of pure-noise monthly series and 58 % of quarterly ones were called seasonal;
    ten weak "seasonal" claims about quarterly files disappeared, the monthly ones of tourism stay;
  * a change of level is looked for before unusual months, and unusual months are judged within each level, so that a series that steps up once
    is described by the step and not by "unusual" months after it (a real GDP table now reports its level shift);
  * the search for the date of a change of level is not led astray by one extreme value (the search is made on the data with their 5 % tails
    clipped; the size of the change is measured on the real data);
  * an annual rate of change or growth is stated only for a series that covers more than a year; a shorter one says "Over the whole series the
    trend is ...";
  * a correction made by hand that sets only one end of the data rows ("Data: first row" without a last row) keeps the program's own other end
    (it used to take the end of the sheet and read the footnotes as data).
- A one-cell footnote between rows is not the "section" of the rows below it.
- Percentages stored as fractions have no float noise (`7.000000000000001`).
- Findings: no `nan%` or `inf`; a series that reaches zero or goes negative is described in lek, not percent; a constant series is not "the highest of
  all N observations"; the trend of a series with missing months counts the gaps as time; a missing last figure is not counted as "the identity
  holds"; charts use the unit of the measure they describe; movers are ranked on one basis.
- `Explore` and `Clean data` no longer show scientific notation, four-decimal rounding, or a thousands separator in id columns. Replies that
  contained a NaN were not valid JSON.
- The Quality tab, the report and the workbook no longer repeat a check's sentence as its own example.

### Fixed: table layouts

- Rows are no longer merged silently when the same labels recur (a breakdown under its parent row, or the same rows twice on a sheet). They are kept
  apart in a `block` dimension, a breakdown is recognised because it adds up to its parent, and the duplicate check covers tables without a time axis.
- Group heading rows (Total, Males, Females, each with the same age groups below) become sections; two or more sections become a dimension
  (`sex`, `region`).
- An annual block above a quarterly block (quarterly GDP) is read as two tables, the quarterly one with proper periods (`2019-Q1`).
- A period written once at the top of a group (`T1.2023` above Total / Male / Female) applies to the rows below it.
- Quarters written `2017-4` are not April; codes kept as text beside names (`B`, `06`, `21`) do not stop the label columns; a row of column numbers
  is not data; a stray number in a title row is not a table; "About the guide" sheets are not tables.
- A table whose values collide shows a low confidence and a warning at the top, in the app and in the report. No population pyramid is drawn for
  unemployment rates.
- A column that repeats a period (`2022 | 2023 | 2023`) is named by its Excel letter in the warning ("Column D ..."); it used to be its position
  in the trimmed table counted from zero, which is not a column anyone can find in the sheet.
- A layout asked for by hand that does not fit the table is refused with a reason and the automatic reading is kept (this path was never exercised
  by a test; it is now, for every layout on every demo).

### Fixed: found by the second round of tests

- The topic search treated most plurals and singulars as different words (`prices`/`price`, `offices`/`office`, `cars`/`car`), so "prices" put the
  producer price index of agricultural products above the consumer price index; plurals are now stemmed first and Albanian endings second, and of two
  equally good hits the one with the shorter name comes first ("population" now gives *Population* before the *Census of Population and Housing*).
- The GDP and the foreign-trade checks stopped with a `KeyError` ("analysis was skipped") when one of their measures was blank in every period; the
  other checks now still run.
- A number written in brackets with a minus sign, `(-5)`, is read as -5 (it was text); `(--5)` stays text.
- The web layer refused a whole number sent as `4.0` or `1e3` (JSON may write it so); a malformed web address such as `http://[::1/` ended in a raw
  error instead of "This is not a valid web address."

### Fixed: crashes, limits and hangs

- Header cells such as `5 tremujor 2023` or `01-0000` aborted the whole file (`ValueError`).
- A header cell of many asterisks made the period parser take exponential time.
- An `.xlsx` package without a workbook part said "the part There is no item named 'xl/workbook.xml' in the archive is missing" (Python's own
  message inside ours); it now names the part. A cell holding `nan` or `inf`, which Python reads as numbers although Excel never writes them,
  is tested through the whole program and the pages.
- Checking whether the data folder can be written (`instat doctor`, the first start) no longer leaves a file behind if the program is stopped at
  that moment.
- A sheet with a very large number of merged ranges could keep the reader busy for minutes.
- `inplace=True` calls that pandas 3.1 deprecates and pandas 4 removes.
- A missing `xlrd` or pandas is reported as such. `--port 0` and ports near 65535 start. A browser tab closed mid-request no longer prints a traceback.
- Downloads: `Content-Disposition` is parsed properly (`filename=a.xlsx; size=5`, `filename*=UTF-8''...`) and is never a path. A link that is not
  closed before the next one stays in the listing of a page.

### Fixed: the app

- A second copy of the program no longer logs out the first: the access cookie is per port.
- A bad number in "Correct how this table is read" gives a message naming the field and keeps the previous reading.
- Requests in different languages no longer overwrite each other's re-reading of a file.
- The page shown without the access link is styled.
- Page listings are limited to instat.gov.al like downloads, and "I trust the source" must be a real `true`. A refused request is answered at once.
- Up to 20 files can be open (it was 12), and the page names the file that was closed to make room.
- Exports of different tables of one file get different names; names keep the base letters of Albanian words.
- On a phone, opening a file scrolls to the results, and the header fits on one row.
- Errors appear in the panel as readable messages; sortable headings work from the keyboard; focus stays where it was after a tab, sort or page
  change; out-of-date answers are ignored; downloads cannot replace the page with raw JSON; "Select all shown" for file lists; value cells are
  coloured in "How it was read"; the page has an icon.
- Colours of links, buttons and faint text meet WCAG 2.1 AA contrast in both themes; tabs name the panel they control.
- Command line: problems go to stderr, `instat --port 9000 serve` and `instat-explorer serve --share` work as documented, Ctrl+C ends quietly, the
  data folder falls back to a temporary one when it cannot be written (two copies started at the same moment no longer make each other think it
  cannot), and `instat doctor` really tries to write to it.

### Added

- **A web version**: the same program running inside the visitor's browser (Pyodide), with nothing to install and no server that sees the files.
  `python tools/build_web.py` builds it as a static site; `.github/workflows/pages.yml` publishes it on GitHub Pages. It opens uploaded files and the demos
  (a browser cannot fetch from instat.gov.al). See `docs/WEB.md`. `tools/screenshots.py --web` tests it in a real browser; on 12 real INSTAT files its
  clean data equals the local program's.
- Tests (`pytest`, 1,941 tests covering 96 % of the statements and branches together), settings for `ruff`, `mypy` and `bandit`, and a CI
  workflow: three operating systems, Python 3.11 to 3.14, a browser job and a build job. `tools/mutation_test.py` breaks a module one operator or
  number at a time and counts the breaks the tests notice: the first 469 tests noticed 43 % of 176 such breaks in the eight core modules; a sample
  drawn afterwards over eleven modules (before the last tests were written) 74 % of 242 (`docs/EVIDENCE.md`, section 5).
- `tools/survey.py --save-baseline` / `--check` records how every real file was read and fails when a change makes one read differently; the optional
  workflow `.github/workflows/real-files.yml` runs the check.
- `tools/survey.py` reads real INSTAT files and reports how each was read. `tools/screenshots.py` drives the program in a real browser and makes the
  pictures in `docs/screenshots/`. `tools/check_published.py` compares the program's numbers with the figures in INSTAT's press releases
  (`docs/PUBLISHED_COMPARISON.md`).
- `packaging/`: the build of the stand-alone `.exe`, the portable zip and the zip for macOS and Linux (`python packaging/build_release.py`), with the
  source of the Windows launcher. Dependency versions are pinned in `packaging/constraints.txt`; the wheel, the payload of the `.exe` and the zip
  for macOS and Linux are reproducible.
- Documents: `docs/EVIDENCE.md`, `LIMITATIONS.md`, `SECURITY_AND_PRIVACY.md`, `DEPLOYMENT.md` and `PROPOSAL.md`.

### Changed

- `series_facts`, `compute_series_stats`, `_parse_text` and `interpret` are split into smaller functions. Their output is unchanged (compared on the
  demos and on 160 synthetic series).

## 0.10.0

First release.
