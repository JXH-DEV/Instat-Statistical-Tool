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

1,941 tests, about 40 seconds, no network and no browser needed. They run 96 % of the program's statements and branches together
(`pytest --cov`; the floor in `pyproject.toml` is 88 %). `mypy` (types), `bandit` (security lint) and `ruff` find nothing; the CI workflow
runs all of them on Windows, macOS and Linux (that workflow has not run yet: nothing has been pushed):

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
  and left apart when their titles, layouts or block names differ;
* the words of the findings (the highest, the lowest, a change of pattern, a ranking, a gap, the movers) are pinned for made-up series whose right
  sentence is known, with the thresholds at which a sentence appears or disappears.

### Do the tests notice a mistake?

A test run that passes says nothing unless the tests would fail when the program is wrong, and "96 % covered" only says that a line ran. So the
tests were also measured the other way round. `tools/mutation_test.py` takes a copy of the program and changes one comparison, arithmetic or
boolean operator, one `not` or one number in a module (`>` becomes `>=`, `+` becomes `-`, `30` becomes `31`), then runs all the tests. A change that
makes a test fail is *noticed*; one that leaves every test green is a *survivor*: a place where a wrong program would have passed. The places are a
random sample (22 per module, the same seed gives the same places) from the eight modules that decide what the program says about a table:

| module | what it does | places in it | the first 469 tests notice | the tests of 0.10.1 notice |
| --- | --- | --- | --- | --- |
| `semantics/numbers.py` | reads a cell as a number or a marker | 37 | 18 of 22 | 19 of 22 |
| `semantics/units.py` | unit, scale and base of an index | 53 | 13 of 22 | 21 of 22 |
| `semantics/periods.py` | months, quarters, years in headers | 360 | 13 of 22 | 16 of 22 |
| `analysis/checks.py` | the consistency checks | 133 | **1 of 22** | 18 of 22 |
| `analysis/series.py` | trend, seasons, jumps, outliers | 370 | 5 of 22 | 18 of 22 |
| `analysis/insights.py` | the sentences of the findings | 185 | 5 of 22 | 15 of 22 (22 of 22 after tests were added for the seven that got through) |
| `excel/tidy.py` | from a located table to tidy rows | 188 | 13 of 22 | 16 of 22 |
| `excel/layout.py` | finds headers, labels and data in a sheet | 1,121 | 7 of 22 | **11 of 22** |
| **all** | | | **75 of 176 (43 %)** | **134 of 176 (76 %)**; 141 (80 %) counting those seven |

The results were measured with 991 of the 1,008 tests that existed then; 933 tests have been added since.

**A fresh sample (seed 31), drawn on the tests as they were before the last round was written**, over eleven modules (the eight above, plus
`analysis/recipes.py`, `analysis/fmt.py` and `semantics/interpret.py`). Nothing was fixed after seeing it, so it is the honest figure:

| module | noticed | | module | noticed |
| --- | --- | --- | --- | --- |
| `analysis/recipes.py` | **5 of 22** | | `analysis/insights.py` | 20 of 22 |
| `semantics/interpret.py` | **10 of 22** | | `semantics/periods.py` | 20 of 22 |
| `excel/layout.py` | **9 of 22** | | `analysis/checks.py` | 20 of 22 |
| `analysis/series.py` | 17 of 22 | | `semantics/numbers.py`, `semantics/units.py` | 21 of 22 each |
| `analysis/fmt.py` | 18 of 22 | | `excel/tidy.py` | 19 of 22 |
| **all** | | | **180 of 242 (74 %)** |

`analysis/recipes.py` (the inflation contributions, the national-accounts identities, the trade balance, the age structure, youth unemployment and
the pay gap) had almost no value-based tests; `tests/test_recipes.py` now checks every figure against the demo builders' own truth. All 17 survivors
of that sample are noticed (one change, `nunique() <= 1` to `< 1` in `_one_measure`, makes no difference and cannot be), and so are the neighbouring
changes tried by hand except one that only changes the wording for exactly equal pay. Writing the tests found one defect (a measure blank in every
period stopped the GDP and trade checks). **`excel/layout.py` and `semantics/interpret.py` have not had a second round of tests.** Other places
known to make no difference: the `rfind` comparison in `semantics/numbers.py`, the start of `_PROV_LETTER` in `periods.py`, `maxsplit` in
`units.py`, `b > 0` after `|t| >= 2` in `series.py`, and the swap when `lo == hi` in `web/api.py`.

What this showed:

* The first set of tests was mostly imitation. It ran the code, and it checked that the program did not crash and that the demo tables came out
  right, but it asserted almost nothing about the consistency checks (1 of 22 changes noticed), the trend and outlier statistics (5 of 22) or the
  wording of the findings (5 of 22). A program whose checks were wrong would have passed.
* Tests were then written for the survivors, with the right answer worked out by hand each time. They found eight real defects, which are fixed
  (`CHANGELOG.md`, 0.10.1): the Albanian word `përqindje` was not a percentage; an index "December of the previous year = 100" or "same month of
  the previous year = 100" was read as "previous year = 100"; month and quarter names written in both languages in one cell (`Janar / January`)
  were not read as months; a series that rises by the same step every month was reported to have "unusual" months (rounding noise of 1e-16) and,
  because a steady rise splits into a low half and a high half, "a change of pattern"; the swing of the seasons was reported as a change of
  pattern too; a ranking of three categories named the middle one as both the highest and the lowest; a value of exactly zero was written
  `ALL 0.0000`. None of them changes the clean data of the 148 real files (their tidy output is identical, file by file).
* The first tests were written looking at the survivors of one sample (seed 7), so the improvement on that sample is flattering (44 % to 89 %,
  six modules). A sample drawn afterwards with another seed (11) gave 64 % over seven modules. The table is a third sample (seed 23), drawn
  after the main rounds of test-writing; some tests were added later for what it showed, so it is not a clean hold-out either. Read 76 % as
  "about three changes in four", not as a measurement to the percent.
* What is still weak. **`excel/layout.py`, the part that finds the table in a sheet, is noticed in only 11 of 22 places**; it has 1,121 places and
  most survivors there are thresholds and conditions for particular sheet shapes. Its real protection is `tools/survey.py` over the 148 real
  files (section 1), which needs the internet and is not part of `pytest` or of the CI. The readers for `.xls`, `.xlsx` and SpreadsheetML are
  covered 72 %, 75 % and 65 %. Most survivors in the other modules are boundary values (`>` where `>=` was meant, the year 1900 against 1901) and
  conditions that need a particular sheet shape; they are the next tests to write.
* A sample is not the whole module: 176 of about 2,450 places were tried. The scores are estimates (22 places per module give a margin of
  roughly ±20 points, the 176 together roughly ±7); they show the order of magnitude and where to look, not a precise figure.

To repeat it on a module you changed (it works on a copy and never touches the repository):

```
python tools/mutation_test.py ../copy-of-the-repository instatkit/analysis/checks.py --count 22 --seed 7 --out checks.json
```

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
python tools/mutation_test.py COPY instatkit/analysis/checks.py   # section 5: do the tests notice a mistake? (COPY = a copy of this folder)
mypy && bandit -q -c pyproject.toml -r instatkit   # section 5: types and security lint
python tools/survey.py                    # sections 1, 3 and 4: downloads ~150 files from instat.gov.al and prints what it made of them
python tools/survey.py --census 0         # without the census tables
python tools/check_published.py --out docs/PUBLISHED_COMPARISON.md   # section 2 (needs pypdf): compares with INSTAT's press releases
python tools/screenshots.py               # section 6: the program in a real browser; --xlsx / --xls FILE adds a real INSTAT file
```

INSTAT publishes about 640 Excel files; 148 were tested here. The results will change as INSTAT changes its files. The way to find
out whether it works on a file you care about is to open it, and to look at the *How it was read* tab.
