"""The command line: every command, its exit codes, what goes to stdout and what to stderr."""

from __future__ import annotations

import json
import os
import sqlite3
import zipfile

import pytest

from instatkit import __version__, cli, config, demo


def run(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_version(capsys):
    with pytest.raises(SystemExit) as info:
        cli.main(["--version"])
    assert info.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_help_lists_every_command(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    text = capsys.readouterr().out
    for command in ("search", "files", "fetch", "process", "inspect", "demo", "serve", "doctor"):
        assert command in text


def test_help_follows_the_language(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--lang", "sq", "--help"])
    sq = capsys.readouterr().out
    assert "gjej" in sq.lower() or "kërko" in sq.lower() or "provo" in sq.lower() or "kontrollon" in sq.lower()


def test_search_works_offline_in_both_languages(capsys):
    code, out, err = run(capsys, "search", "inflation")
    assert code == 0 and "instat.gov.al" in out and err == ""
    code, out, _ = run(capsys, "search", "papunësia", "--limit", "3")
    assert code == 0 and out.count("https://") >= 1
    code, out, err = run(capsys, "search", "zzzzqqqq")
    assert code == 1 and out == "" and err.strip(), "'nothing found' is a message on stderr and a non-zero exit"


def test_demo_prints_findings_and_labels_the_numbers_as_invented(capsys):
    code, out, err = run(capsys, "demo", "cpi")
    assert code == 0 and "invented" in out and "checks" in out and err == ""
    code, out, _ = run(capsys, "demo", "wages", "--lang", "sq")
    assert code == 0 and "shpikur" in out


def test_demo_exports_every_format(capsys, tmp_path):
    code, out, err = run(capsys, "demo", "gdp", "--export", "html,csv,xlsx,sqlite,md,zip", "--out", str(tmp_path), "--quiet")
    assert code == 0 and err == ""
    names = sorted(p.name for p in tmp_path.iterdir())
    assert any(n.endswith("-report.html") for n in names) and any(n.endswith(".xlsx") for n in names)
    assert sum(n.endswith("-tidy.csv") for n in names) == 2 and sum(n.endswith("-briefing.md") for n in names) == 2   # two tables
    assert zipfile.ZipFile(next(tmp_path.glob("*-bundle.zip"))).testzip() is None
    conn = sqlite3.connect(next(tmp_path.glob("*.sqlite")))
    assert conn.execute("select count(*) from datasets").fetchone()[0] == 2
    conn.close()
    assert out.count("wrote") == len(names)


def test_demo_unknown_name_and_unknown_export(capsys):
    code, out, err = run(capsys, "demo", "nope")
    assert code == 1 and out == "" and "cpi" in err
    code, out, err = run(capsys, "demo", "cpi", "--export", "html,pdf")
    assert code == 2 and "pdf" in err


def test_process_a_local_file(capsys, tmp_path):
    xlsx = tmp_path / "wages.xlsx"
    xlsx.write_bytes(demo.make_cross_section()[0])
    code, out, err = run(capsys, "process", str(xlsx), "--export", "csv,html", "--out", str(tmp_path / "out"))
    assert code == 0 and "wrote" in out
    assert (tmp_path / "out" / "wages-tidy.csv").read_bytes().startswith(b"\xef\xbb\xbf")
    code, _out, err = run(capsys, "process", str(tmp_path / "missing.xlsx"))
    assert code == 2 and "missing.xlsx" in err
    bad = tmp_path / "bad.xlsx"
    bad.write_bytes(b"this is not a spreadsheet")
    code, out, err = run(capsys, "process", str(bad), "--export", "csv", "--out", str(tmp_path / "out2"))
    assert code == 1 and err.strip() and not (tmp_path / "out2").exists(), "a file that cannot be read exports nothing"


def test_process_checks_the_export_names_before_doing_any_work(capsys, tmp_path):
    code, _out, err = run(capsys, "process", str(tmp_path / "does-not-matter.xlsx"), "--export", "docx")
    assert code == 2 and "docx" in err


def test_inspect_shows_how_a_file_is_read(capsys, tmp_path):
    xlsx = tmp_path / "t.xlsx"
    xlsx.write_bytes(demo.make_month_by_year()[0])
    code, out, err = run(capsys, "inspect", str(xlsx), "--rows", "3")
    assert code == 0 and "Data block" in out and err == ""
    assert "Arrivals" in out


def test_exports_go_to_the_data_folder_by_default(capsys):
    code, out, _ = run(capsys, "demo", "wages", "--export", "csv", "--quiet")
    assert code == 0
    assert any(p.parent == config.EXPORT_DIR for p in config.EXPORT_DIR.glob("*-tidy.csv")) and "wrote" in out


def test_serve_options_before_or_after_the_command(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "cmd_serve", lambda a: seen.update(port=a.port, share=a.share, no_browser=a.no_browser) or 0)
    for argv in (["--port", "9100", "--share", "serve"], ["serve", "--port", "9100", "--share"], ["--port", "9100", "--share"]):
        seen.clear()
        parsed = cli.build_parser().parse_args(argv)
        parsed.func = cli.cmd_serve
        cli.cmd_serve(parsed)
        assert seen == {"port": 9100, "share": True, "no_browser": False}, argv
    seen.clear()
    cli.cmd_serve(cli.build_parser().parse_args([]))
    assert seen == {"port": 8501, "share": False, "no_browser": False}


def test_the_launcher_accepts_the_word_serve(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "cmd_serve", lambda a: seen.update(port=a.port, share=a.share) or 0)
    for argv, expected in ((["serve", "--share"], {"port": 8501, "share": True}), (["--share"], {"port": 8501, "share": True}),
                           (["serve", "--port", "9200"], {"port": 9200, "share": False})):
        monkeypatch.setattr("sys.argv", ["instat-explorer", *argv])
        assert cli.app_main() == 0
        assert seen == expected, argv


def test_ctrl_c_is_a_quiet_exit(monkeypatch, capsys):
    monkeypatch.setattr(cli, "cmd_doctor", lambda a: (_ for _ in ()).throw(KeyboardInterrupt()))
    code = cli.main(["doctor"])
    assert code == 130 and "Traceback" not in capsys.readouterr().err


def test_doctor_passes_and_reports_each_check(capsys):
    code, out, _ = run(capsys, "doctor")
    assert code == 0 and out.count("[ok]") == 5 and "Everything works" in out and "[!!]" not in out


def test_doctor_reports_a_data_folder_that_cannot_be_written(capsys, monkeypatch, tmp_path):
    blocker = tmp_path / "file-not-folder"
    blocker.write_text("x")
    monkeypatch.setattr(config, "ensure_data_dir", lambda: True)
    monkeypatch.setattr(config, "DATA_DIR", blocker / "inside")
    code, out, _ = run(capsys, "doctor")
    assert code == 1 and "[!!] The data folder can be written to" in out and "check failed" in out


def test_ensure_data_dir_falls_back_to_a_temporary_folder(monkeypatch, tmp_path):
    blocker = tmp_path / "file-not-folder"
    blocker.write_text("x")
    saved = config.DATA_DIR, config.RAW_DIR, config.EXPORT_DIR, config.DB_PATH
    try:
        monkeypatch.setattr(config, "DATA_DIR", blocker / "inside")
        assert config.ensure_data_dir() is False
        assert config.DATA_DIR.exists() and config.EXPORT_DIR.parent == config.DATA_DIR
    finally:
        config.DATA_DIR, config.RAW_DIR, config.EXPORT_DIR, config.DB_PATH = saved


def test_unicode_output_does_not_depend_on_the_console_encoding(tmp_path):
    """Albanian letters print on a console that uses cp1252."""
    import subprocess
    import sys

    env = {**os.environ, "PYTHONIOENCODING": "cp1252", "PYTHONUTF8": "0", "INSTAT_DATA_DIR": str(tmp_path)}
    r = subprocess.run([sys.executable, "-m", "instatkit", "demo", "tourism", "--lang", "sq", "--quiet"], capture_output=True, env=env,
                       cwd=str(config.ROOT), timeout=120)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
    assert "Traceback" not in r.stderr.decode("utf-8", "replace")
    assert "ë" in r.stdout.decode("utf-8")


def test_python_dash_m_runs_and_importing_the_module_does_not(tmp_path):
    import subprocess
    import sys

    env = {**os.environ, "INSTAT_DATA_DIR": str(tmp_path)}
    r = subprocess.run([sys.executable, "-m", "instatkit", "--version"], capture_output=True, env=env, cwd=str(config.ROOT), timeout=60)
    assert r.returncode == 0 and __version__.encode() in r.stdout
    r = subprocess.run([sys.executable, "-c", "import instatkit.__main__; print('imported')"], capture_output=True, env=env,
                       cwd=str(config.ROOT), timeout=60)
    assert r.returncode == 0 and b"imported" in r.stdout


def test_json_of_the_diagnostic_is_valid(capsys, tmp_path):
    """The 'report a problem' file must be valid JSON a maintainer can load."""
    from instatkit.web import api

    from .conftest import process_demo

    pf = process_demo("gdp")
    data = json.loads(api.dumps(api.diagnostic(pf, pf.tables[1])))
    assert data["sheet"] == "_tab_6" and data["spec"]["columns"] and data["preview"]


def test_version_numbers_agree():
    """The version in the package, the changelog's newest heading and the metadata a build would use must be the same."""
    import re

    changelog = (config.ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert re.search(rf"^## {re.escape(__version__)}\b", changelog, re.M), "add a heading for this version to CHANGELOG.md"
    newest = re.search(r"^## (\d+\.\d+\.\d+)", changelog, re.M).group(1)
    assert newest == __version__
