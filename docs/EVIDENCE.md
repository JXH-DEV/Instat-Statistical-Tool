# What has been tested, and what that does and does not show

This is the evidence behind the claim that INSTAT Explorer reads INSTAT's Excel files correctly. It says how the program was tested,
what the results were, and what the tests cannot show. Version 0.10.1, tested on Windows with Python 3.14, pandas 3.1.

## 1. Real INSTAT files

The program was run over a spread of real files from instat.gov.al. They were downloaded through the program's own fetcher (one request
at a time, with a pause between requests), so the test was as gentle on the server as normal use.

| | |
|---|---|
| Topic pages visited | 19 (prices, labour market, national accounts, foreign trade, census, tourism, wages, production, construction, agriculture, transport, energy, education, health, population movements, migration ...) |
| Files those pages offer | 384 (266 of them census tables) |
| Files tested | 148: **every** file on the 18 non-census pages (118) and a spread of 30 census tables (15 `.xls`, 15 `.xlsx`) |
| Links that no longer work | 4, all on the wages page (HTTP 404 on INSTAT's own site). The program says so in plain words. The first run found 8; INSTAT replaced four of them with working files the same day, which is why the figures differ slightly from earlier runs. The figures here are from the last run |
| Files read | 144: 124 `.xlsx`, 11 old `.xls`, 9 Excel 2003 XML saved as `.xls` |
| Crashes | 0 |
| Tables found | 276, holding 118,483 observations |
| Tables in which none of the program's own checks failed | **252 (91.3 %)** |
| Files in which every table passed | **128 of 144 (88.9 %)** |
| Exports (HTML report, Excel, SQLite, CSV) | worked on every file |
| Time per file | median 0.4 s, 95th percentile 3.5 s, slowest 15 s (it varied between 7 and 22 s from run to run on a busy computer) |

| Topic | Files | Tables | Flagged | Observations |
|---|---:|---:|---:|---:|
| Census of Population and Housing (sample) | 30 | 52 | 7 | 17,723 |
| Transport, accidents | 16 | 18 | 2 | 5,416 |
| National accounts | 13 | 42 | 0 | 3,104 |
| Foreign trade | 9 | 9 | 0 | 1,304 |
| Consumer price index | 8 | 9 | 0 | 33,091 |
| Labour force survey | 8 | 8 | 0 | 1,160 |
| Migration | 8 | 8 | 0 | 358 |
| Education | 7 | 8 | 3 | 521 |
| Agriculture | 6 | 78 | 6 | 12,878 |
| Harmonised consumer prices | 6 | 7 | 0 | 32,898 |
| Energy | 6 | 6 | 2 | 1,216 |
| Tourism | 5 | 5 | 0 | 1,039 |
| Construction | 5 | 7 | 2 | 1,236 |
| Producer prices | 5 | 5 | 0 | 5,206 |
| Births, deaths, marriages | 5 | 5 | 0 | 772 |
| Health | 5 | 7 | 2 | 418 |
| Industrial production | 1 | 1 | 0 | 78 |
| Wages (5 files listed; the 4 dead links are here) | 1 | 1 | 0 | 65 |

"Flagged" means one of the program's checks failed (see section 4). Flagged tables are marked as *probably read wrongly* in the app
and in the report, with a lowered confidence and a warning at the top; they are not hidden.

## 2. Against INSTAT's own published figures

The checks of section 4 show only that a table agrees with itself. This compares the program with something independent: the figures that
INSTAT's staff wrote into the press release of the same data. `tools/check_published.py` takes ten releases (consumer prices and the
harmonised index of September 2026; GDP of the second quarter of 2026 and of 2025; the labour force survey, wages, building permits and births of
the second quarter of 2026; foreign trade of September 2026; accommodation of August 2026), finds each figure the release states in the program's
reading of the Excel tables on the same page (or works it out the way INSTAT does: an annual change from the index, a change in percentage points
from two rates), and compares them at the precision INSTAT published. The full table, with the quoted text of every figure, is in
`docs/PUBLISHED_COMPARISON.md`.

| | |
|---|---|
| Figures compared | **149** (the tool says so when it cannot find one; none was skipped) |
| Equal after rounding as INSTAT rounds | 140 |
| Equal when INSTAT's own rounded levels are used | 1: the fall of the unemployment rate is published as -0.2, which is 8.3 - 8.5; the unrounded levels give -0.26 |
| Close, by design | 7: the contributions of product groups to inflation, which the program works out from the published weights without chain-linking. The largest deviation from INSTAT's figure is 0.015 percentage points (Transport); up to 0.02 is accepted |
| Different | **1** |

The one difference is in INSTAT's own press release. Its Table 1 gives the Transport index for September 2026 as 112.8; the Excel table, which the
program reads, says 112.92. The Excel table is the one that agrees with INSTAT's published annual rate for Transport (12.4 %: 112.92 against 100.42 a year
before gives 12.45 %, while 112.8 would give 12.3 %). The other twelve divisions agree with Table 1 to rounding.

**What the comparison found in the program.** Two defects that none of the program's own checks could see, because both left every number intact:

* **Quarters written as Roman numerals** (`II/23`, `I - 22`) were not recognised as periods. Seven real files, among them the wage table, three
  tables of building permits, births and deaths by prefecture, and the quarterly electricity balance, were read as one-year snapshots made of hundreds
  of one-point series. All seven had passed every check.
* **A thousand marker written against the currency** (`000Lekë / 000ALL`) was not recognised, and the unit was then taken from the title: the value
  of building permits was read as 15,959,638 *buildings* instead of ALL 16.0 billion.

Both are fixed, with tests. After the fixes the wage figures (92,150 ALL, +9.8 % on a year) and the building-permit figures (460 permits, +30.7 %;
ALL 16.0 billion, -13.2 %) agree with INSTAT's releases, and the other 141 of the 148 real files read exactly as before.

**What it does not show.** That every cell of every table is right: these are the headline figures of ten recent releases, and INSTAT publishes about 640
files. The tables on the site can be revised after a release, and a release can contain a slip, so a difference can be on either side. And it shows
that **passing every check is not the same as being right**: seven files were wrong and clean. The percentage of clean tables in section 1 measures
consistency, not correctness.

## 3. What the first run found, and what changed

The first run over these files found, besides small things, that **the program was merging rows silently** in some layouts and
that its own duplicate check could not see it for tables without a time axis. After fixing the layout detection and extending the check,
the number of tables with colliding values fell from 40 to 13. The layouts that were fixed, all from real files:

* a breakdown under its parent row whose rows repeat the names above it (census: "Other citizenship" followed by its countries); the
  program finds where the breakdown ends because its rows add up to the parent;
* group heading rows (Total / Males / Females) with the same age groups under each (the labour force survey indicators and others);
* the same rows twice on one sheet (counts, then shares; production, then consumption);
* an annual block above a quarterly block, with the year written only on the first quarter's row (quarterly GDP, 2 workbooks);
* periods written once at the top of a group (`T1.2023` above Total / Male / Female);
* quarters written `2017-4` (read as April 2017), codes kept as text beside the names (`B`, `06`, `21`), a column-number row (`1 2 2a 3 ...`), and a stray
  number in a title row that became a one-value "table" (consumer price index).

Each of these has a test built from the same pattern (`tests/test_readers.py`); each fails on 0.10.0 and passes on 0.10.1.

## 4. What the checks are, and what they cannot prove

The program checks every table it reads: all cells have a value; no gaps between periods; at most one value per series and period;
percentages lie between 0 and 100; the parts add up to the stated total (regions to the national figure, age groups to the total);
the consumer price index contributions add up to the headline; national-accounts and trade identities hold.

These are **consistency checks**. They catch most misreadings, because a misread table usually breaks one of them, but:

* a table can pass every check and still be read wrongly (for example two columns swapped in a way that keeps the sums);
* the values were compared with INSTAT's published figures only for the headline figures of ten releases (section 2), not cell by cell;
* a failed "parts add up" check can also mean INSTAT's own table does not add up (rounding, or a missing category).

**24 tables still carry a failed check** (29 failed checks in all: 15 "duplicate observations" and 14 "parts add up"): in the census
sample, 7 tables (women by number of children, by urban/rural area, with disabilities, ever-married women, occupied dwellings); building
permits (2); the agriculture yearbook (6 sheets); railway accidents and road vehicles by age (2);
the two electric power balances; school and university enrolment (3); the activity of health services (2, new files that INSTAT published
while this was being tested). `docs/LIMITATIONS.md` says what is wrong with each kind.

## 5. Automated tests

469 tests, about 20 seconds, no network and no browser needed. They cover 90.4 % of the program's code. `mypy` (types) and `bandit` (security
lint) find nothing; `ruff` finds nothing; the CI workflow runs all of them on Windows, macOS and Linux (that workflow has not run yet: nothing has
been pushed):

* the reader recovers **exactly** the numbers written into seven synthetic workbooks that imitate INSTAT layouts (consumer prices,
  labour force survey, national accounts with cover and contents sheets, foreign trade, population with a two-level header, tourism,
  wages with `..` and `-` markers), cell by cell, in English and in Albanian;
* hostile and broken files (empty, truncated, wrong format, XML entity bombs, oversize parts, too many merged ranges, a header made
  of 50 asterisks) end in a message, never a crash or a hang;
* the web server over real HTTP: who may use it, request limits, every endpoint, every export, bad input, concurrency, shutdown;
* every export opens in an independent reader (openpyxl for Excel, `sqlite3`, the `csv` module, an HTML parser);
* every sentence of the interface and of the findings has an Albanian version, with matching placeholders;
* the part that talks to the internet (93 % covered; it was 30 % before this release) is tested against played-back answers: it never connects to a
  local or private address, not through a redirect or a look-alike host name either; it refuses error pages sent as files, over-large files
  and over-large pages, retries throttling with a growing pause, remembers files by their content, and never reads outside its folder;
* repeated sheets and blocks (a sheet per prefecture, a block per sex) are combined into one table with every number checked cell by cell,
  and left apart when their titles, layouts or block names differ.

## 6. The interface

Checked on the running app in a browser, in both languages and both light and dark themes: all six tabs for all seven demos and for
real files; the full journey of searching a topic, choosing files on INSTAT's page, confirming, downloading and analysing; phone width
(no horizontal scrolling); keyboard use (sortable headers are buttons, focus stays where it was after a change); a stopped program
gives a readable message. **Contrast: 4,250 pieces of text per theme checked against WCAG 2.1 AA (4.5:1), no failures.** Controls have
accessible names, charts have text alternatives, there are no duplicate ids or skipped headings.
**Not done:** a test with a screen reader, and a full WCAG audit by a specialist.

`tools/screenshots.py` makes the same journey repeatable: it starts the program (or the stand-alone `.exe`), drives Edge, Chrome or Chromium
like a person, saves the pictures in `docs/screenshots/` and fails on anything the browser reports (console errors, uncaught exceptions,
failed requests, Content-Security-Policy violations). The last run, on the stand-alone `.exe` of this release with two real INSTAT files
(a 13-table `.xlsx` of national accounts, an old `.xls` census table), reported **0 problems**; the exported report loads nothing from the
internet; on a 390 px wide screen nothing scrolls sideways; the program ended by itself (exit code 0) when its Stop button was pressed. Looking at the pictures found
two things that no test had: after opening a file on a phone the results were below the "Get data" cards instead of in view, and the Quality
tab said some sentences twice. Both are fixed. The pictures are in `docs/screenshots/`.

The web version was compared with the local program on 12 real INSTAT files (including the 73-table agriculture yearbook, a legacy `.xls` table and the
wage workbook with Roman-numeral quarters): the clean data it exports, in long and wide form, is identical table by table (`docs/WEB.md`). It passed the
same browser journey as the local program (`python tools/screenshots.py --web site`) with no browser error.

## 7. Reproduce it

```
python -m pip install -e ".[dev]"
python -m pytest --cov                    # section 5
mypy && bandit -q -c pyproject.toml -r instatkit   # section 5: types and security lint
python tools/survey.py                    # sections 1, 3 and 4: downloads ~150 files from instat.gov.al and prints what it made of them
python tools/survey.py --census 0         # without the census tables
python tools/check_published.py --out docs/PUBLISHED_COMPARISON.md   # section 2 (needs pypdf): compares with INSTAT's press releases
python tools/screenshots.py               # section 6: the program in a real browser; --xlsx / --xls FILE adds a real INSTAT file
```

INSTAT publishes about 640 Excel files; 148 were tested here. The results will change as INSTAT changes its files. The way to find
out whether it works on a file you care about is to open it, and to look at the *How it was read* tab.
