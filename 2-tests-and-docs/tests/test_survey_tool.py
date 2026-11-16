"""The real-file survey and its regression check (tools/survey.py), with a fetcher that serves demo workbooks instead of INSTAT's server: what a
baseline keeps, what counts as a changed reading, and that a file INSTAT replaced is listed but never judged."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from instatkit import demo
from instatkit.sources.fetch import Downloaded, FetchError

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def survey():
    spec = importlib.util.spec_from_file_location("instat_survey", ROOT / "tools" / "survey.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    del sys.modules[spec.name]


class FakeFetcher:
    """Serves ``files`` (url -> bytes); a url that maps to ``None`` is a dead link."""

    def __init__(self, files: dict[str, bytes | None], offline: bool = False) -> None:
        self.files = files

    def download(self, url: str) -> Downloaded:
        data = self.files.get(url)
        if data is None:
            raise FetchError("The page answered with HTTP 404.", status=404, url=url)
        return Downloaded(url, "file.xlsx", data, hashlib.sha256(data).hexdigest(), len(data), "xlsx")


CPI, TRADE = demo.make_cpi_consistent()[0], demo.make_trade_monthly()[0]
URLS = {"a": "https://instat.gov.al/a.xlsx", "b": "https://instat.gov.al/b.xlsx"}


def run(survey, files):
    fetcher = FakeFetcher(files)
    return [survey.process_file(fetcher, {"topic": "T", "label": f"file {k}", "url": u}) for k, u in URLS.items()]


def test_a_record_carries_the_hash_of_the_bytes_and_how_the_file_was_read(survey):
    rec = run(survey, {URLS["a"]: CPI, URLS["b"]: TRADE})[0]
    assert rec["file_sha"] == hashlib.sha256(CPI).hexdigest()[:16] and rec["ok"] and not rec.get("crash")
    kept = survey.reading(rec)
    assert kept["file_sha"] == rec["file_sha"] and kept["ok"] and kept["label"] == "file a" and kept["url"] == URLS["a"]
    assert kept["tables"][0]["orientation"] == "periods_in_columns" and kept["tables"][0]["freq"] == "M"
    assert len(kept["tables"][0]["tidy_hash"]) == 12 and kept["tables"][0]["failed_checks"] == []


def test_a_baseline_keeps_no_values(survey):
    kept = survey.reading(run(survey, {URLS["a"]: CPI, URLS["b"]: TRADE})[0])
    assert set(kept) == {"topic", "label", "url", "file_sha", "ok", "tables"}
    assert set(kept["tables"][0]) == {"sheet", "orientation", "freq", "n_obs", "n_series", "tidy_hash", "failed_checks"}


def test_the_same_files_read_the_same_way(survey):
    files = {URLS["a"]: CPI, URLS["b"]: TRADE}
    baseline = [survey.reading(r) for r in run(survey, files)]
    report = survey.compare(baseline, run(survey, files))
    assert report == {"changed": [], "source_changed": [], "unreachable": [], "unchanged": ["file a", "file b"]}


def test_a_file_that_was_replaced_is_listed_and_not_judged(survey):
    baseline = [survey.reading(r) for r in run(survey, {URLS["a"]: CPI, URLS["b"]: TRADE})]
    report = survey.compare(baseline, run(survey, {URLS["a"]: demo.make_cpi_consistent(n_months=36)[0], URLS["b"]: TRADE}))
    assert report["source_changed"] == ["file a"] and report["changed"] == [] and report["unchanged"] == ["file b"]


def test_a_dead_link_is_not_the_programs_fault(survey):
    baseline = [survey.reading(r) for r in run(survey, {URLS["a"]: CPI, URLS["b"]: TRADE})]
    report = survey.compare(baseline, run(survey, {URLS["a"]: CPI, URLS["b"]: None}))
    assert report["unreachable"] == ["file b"] and report["changed"] == [] and report["unchanged"] == ["file a"]
    assert survey.compare(baseline, [])["unreachable"] == ["file a", "file b"]


@pytest.mark.parametrize("key, was", [("orientation", "cross_section"), ("freq", "Q"), ("n_obs", 211), ("n_series", 8),
                                      ("tidy_hash", "000000000000"), ("failed_checks", ["sum:x"])])
def test_a_different_reading_of_the_same_bytes_is_a_change(survey, key, was):
    files = {URLS["a"]: CPI, URLS["b"]: TRADE}
    baseline = [survey.reading(r) for r in run(survey, files)]
    now = baseline[0]["tables"][0][key]
    baseline[0]["tables"][0][key] = was
    report = survey.compare(baseline, run(survey, files))
    assert report["changed"] == [f"file a: table 1 [Sheet] {key} {was} -> {now}"]
    assert report["unchanged"] == ["file b"]


def test_tables_that_appear_or_disappear_and_files_that_stop_reading_are_changes(survey):
    files = {URLS["a"]: CPI, URLS["b"]: TRADE}
    baseline = [survey.reading(r) for r in run(survey, files)]
    baseline[0]["tables"] = baseline[0]["tables"] * 2
    baseline[1]["ok"] = False
    report = survey.compare(baseline, run(survey, files))
    assert report["changed"] == ["file a: 2 tables -> 1", "file b: readable False -> True"]


def test_a_crash_is_a_change(survey, monkeypatch):
    files = {URLS["a"]: CPI, URLS["b"]: TRADE}
    baseline = [survey.reading(r) for r in run(survey, files)]

    def explode(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(survey, "process_bytes", explode)
    report = survey.compare(baseline, run(survey, files))
    assert len(report["changed"]) == 2 and "now crashes (RuntimeError: boom)" in report["changed"][0]


def test_the_command_line_saves_and_checks_a_baseline(survey, monkeypatch, tmp_path, capsys):
    files = {URLS["a"]: CPI, URLS["b"]: TRADE}
    monkeypatch.setattr(survey, "Fetcher", lambda offline=False: FakeFetcher(files))
    monkeypatch.setattr(survey, "choose_files", lambda pages, n: [{"topic": "T", "label": f"file {k}", "url": u, "ext": ".xlsx"}
                                                                  for k, u in URLS.items()])
    monkeypatch.setattr(survey, "list_pages", lambda fetcher, topics: {})
    base, out = tmp_path / "base.json", tmp_path / "out.json"
    assert survey.main(["--out", str(out), "--save-baseline", str(base)]) == 0
    text = base.read_text(encoding="utf-8")
    assert text.startswith("[\n") and text.endswith("\n]\n") and "\r" not in text and text.count("\n") == 4          # a file per line
    assert [b["label"] for b in json.loads(text)] == ["file a", "file b"]

    assert survey.main(["--out", str(out), "--check", str(base)]) == 0
    assert "2 read as before | 0 read differently" in capsys.readouterr().out

    changed = json.loads(text)
    changed[0]["tables"][0]["tidy_hash"] = "0" * 12
    base.write_text(json.dumps(changed), encoding="utf-8")
    assert survey.main(["--out", str(out), "--check", str(base)]) == 1
    printed = capsys.readouterr().out
    assert "1 read as before | 1 read differently" in printed and "CHANGED: file a: table 1" in printed


def test_a_replaced_file_does_not_fail_the_check(survey, monkeypatch, tmp_path, capsys):
    files = {URLS["a"]: CPI, URLS["b"]: TRADE}
    base, out = tmp_path / "base.json", tmp_path / "out.json"
    monkeypatch.setattr(survey, "Fetcher", lambda offline=False: FakeFetcher(files))
    monkeypatch.setattr(survey, "choose_files", lambda pages, n: [{"topic": "T", "label": f"file {k}", "url": u, "ext": ".xlsx"}
                                                                  for k, u in URLS.items()])
    monkeypatch.setattr(survey, "list_pages", lambda fetcher, topics: {})
    survey.main(["--out", str(out), "--save-baseline", str(base)])
    files[URLS["a"]] = demo.make_cpi_consistent(n_months=36)[0]
    assert survey.main(["--out", str(out), "--check", str(base)]) == 0
    assert "1 replaced by INSTAT since" in capsys.readouterr().out
