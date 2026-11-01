# Known limitations

What the program does not do well, or at all. `EVIDENCE.md` has the measurements behind it.

## Tables the program flags or reads imperfectly

On the 148 real files tested, 24 of 276 tables fail one of the program's checks and are shown with a warning and a low confidence. The
causes seen so far:

| Kind of table | Example (INSTAT file) | What goes wrong |
|---|---|---|
| Rows whose names repeat under several parents with no total to tell them apart | electric power balance (annual and quarterly), school and university enrolment, railway accidents, activity of health services | Two or more rows get the same name, so their values collide. The *How it was read* tab shows it, and a correction there can fix it |
| A parts-add-up check that fails although the file is read as written | agriculture yearbook (6 sheets), building permits, several census tables | Either the categories overlap (broad and narrow classes in one list), a subtotal is listed as a category, or INSTAT's own figures do not add up. The program cannot tell which |
| Cross-tabulations with a header more than two levels deep | census tables of women by number of children, by disability | Breakdowns get generic names (`category`, `category_2`); the values are right, the names are not always meaningful |

The web version (`WEB.md`) cannot search or download from instat.gov.al, because browsers do not let a page read another site's files; files
must be uploaded. Open files are lost when the page is closed or the language is switched, and a very large file can exhaust a browser tab's memory.

Other limits of the reading:

* **The checks are consistency checks.** A table can pass every check and still be read wrongly: seven real files did, until the headline
  figures of INSTAT's press releases were compared with the tables (`docs/PUBLISHED_COMPARISON.md`: 149 figures from ten releases agree, with one
  difference that is in INSTAT's own table). That is a sample of the headline figures, not a check of every cell of the 640 files.
* A mid-table **footnote** is recognised when it starts like one (`(*)`, `*`, `Note`, `Burimi`); a note written as a plain sentence is
  taken for a heading.
* **Nested breakdowns** are found by their sums. A breakdown whose rows do not add up to the row above it is kept apart by name only.
* INSTAT's statistical database (PxWeb) is **not** supported, nor `.xlsb`, `.ods` or PDF.
* Inflation contributions are approximate: they use the published weights and ignore chain-linking.
* The findings come from fixed rules. They describe what the numbers did, never why; the "possible context" next to an unusual month is a short
  list of known events, not an explanation. Check anything you plan to publish against INSTAT's own publication.

## The program

* **Platforms.** Tested on Windows only, on Python 3.14. Nothing in the code is Windows-specific and the syntax is checked against Python 3.11,
  but macOS, Linux and Python 3.11–3.13 are untested until the CI in `.github/workflows/ci.yml` is run.
* **One person at a time.** It is a local application, not a multi-user service. `--share` lets a class use one computer's copy over plain
  HTTP (see `SECURITY_AND_PRIVACY.md`); there are no accounts, no saved sessions and no history. Opened files are lost when the program stops.
* **Albanian** has not been checked by a native speaker. The 850 sentences and the glossary of about 340 terms were written with care and are
  complete (a test makes sure of it), but they are unreviewed.
* **Accessibility.** Contrast (WCAG 2.1 AA), names of controls, keyboard use and structure were checked automatically on the running app.
  It has not been tested with a screen reader or audited by a specialist.
* **The Windows `.exe` and portable zip are not code-signed.** They are built from this repository (`packaging/build_release.py`), but a fix
  in the source reaches them only with the next release build.
* **Size.** Files are limited to 50 MB, 20,000 rows × 1,024 columns per sheet and 1,000,000 observations per table. INSTAT's files
  are far below this; larger ones are cut short with a warning.
* **Language of the data.** Category names follow the language switch when the file has both languages or the built-in glossary knows the
  word; anything else stays as INSTAT wrote it.

## What would make it better, in this order

1. A test corpus of INSTAT's own, with the figures checked against the published tables, to turn "no check failed" into "correct".
2. A native-speaker review of the Albanian text.
3. An accessibility audit with assistive technology.
4. A code-signing certificate for the Windows files (the build itself is in `packaging/`).
5. Handling of the remaining layouts in the table above (a correction made by hand in the app already works for most of them).
6. Optional: save the open files between sessions; reading from PxWeb.
