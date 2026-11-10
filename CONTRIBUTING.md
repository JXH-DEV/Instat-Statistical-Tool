# Contributing

Bug reports and pull requests are welcome. For a table that is read wrongly, attach the diagnostic file (Export tab, "Report a problem with how a
file was read") or the INSTAT file itself, and say what you expected.

## Setup

```
python -m pip install -e ".[dev]"
python -m pytest --cov
ruff check .
mypy
bandit -q -c pyproject.toml -r instatkit
```

A test run that passes says little unless the tests would fail when the code is wrong. `python tools/mutation_test.py COPY instatkit/analysis/checks.py`
(on a copy of the repository) breaks the module one operator or number at a time and lists the breaks that no test noticed; each is a missing test
or a change that makes no difference. Do it for a module you changed.

The tests need no network. `instatkit/demo.py` builds sample workbooks and returns the numbers it wrote, so a reader change can be checked cell by
cell. Add a test for every fix; a layout change should also be run over real files with `python tools/survey.py` (before and after) so that no
file reads worse: `python tools/survey.py --offline --check tools/survey_baseline.json` compares every real file with how it was read before and lists any
that reads differently (refresh the baseline with `--save-baseline` only when the difference is the intended improvement).

The web version is the same Python run in the browser (Pyodide): `instatkit/web/embedded.py` answers the page's requests in-process, `webapp/` holds
the bridge and the worker, and `tools/build_web.py` builds the site (`python tools/build_web.py --out site`, then `python tools/screenshots.py --web site`).

## Conventions

- Python 3.11 or newer, standard library first: the runtime depends on pandas, numpy and xlrd only.
- Every sentence the program can show goes through `tr()` / `tn()` and needs an Albanian entry in `instatkit/data/sq.json`; a test fails when one is
  missing.
- Shell scripts keep Unix line endings (see `.gitattributes`).
- `CHANGELOG.md` lists what changed for users.
