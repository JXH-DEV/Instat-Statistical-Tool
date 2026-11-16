"""Where the program keeps its files on each operating system, what happens when no folder can be written, and which language a console
or a browser asks for."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

import pytest

from instatkit import __version__, config, i18n


@pytest.fixture
def restore_paths():
    saved = config.DATA_DIR, config.RAW_DIR, config.EXPORT_DIR, config.DB_PATH
    yield
    config.DATA_DIR, config.RAW_DIR, config.EXPORT_DIR, config.DB_PATH = saved


# --- the data folder ---
def test_windows_keeps_its_files_under_local_app_data(monkeypatch, tmp_path):
    monkeypatch.setattr(config.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    assert config._user_data_dir() == tmp_path / "Local" / "INSTAT-Explorer"
    monkeypatch.delenv("LOCALAPPDATA")
    monkeypatch.setattr(config.Path, "home", lambda: tmp_path / "home")
    assert config._user_data_dir() == tmp_path / "home" / "AppData" / "Local" / "INSTAT-Explorer"


def test_macos_keeps_its_files_in_application_support(monkeypatch, tmp_path):
    monkeypatch.setattr(config.sys, "platform", "darwin")
    monkeypatch.setattr(config.Path, "home", lambda: tmp_path / "home")
    assert config._user_data_dir() == tmp_path / "home" / "Library" / "Application Support" / "INSTAT-Explorer"


def test_linux_follows_the_xdg_folder_and_otherwise_uses_local_share(monkeypatch, tmp_path):
    monkeypatch.setattr(config.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert config._user_data_dir() == tmp_path / "xdg" / "instat-explorer"
    monkeypatch.delenv("XDG_DATA_HOME")
    monkeypatch.setattr(config.Path, "home", lambda: tmp_path / "home")
    assert config._user_data_dir() == tmp_path / "home" / ".local" / "share" / "instat-explorer"


def test_the_environment_variable_decides_first(monkeypatch, tmp_path):
    monkeypatch.setenv("INSTAT_DATA_DIR", str(tmp_path / "portable"))
    assert config._data_dir() == tmp_path / "portable"
    monkeypatch.setenv("INSTAT_DATA_DIR", "~/instat-data")
    assert config._data_dir() == Path("~/instat-data").expanduser()


def test_a_source_checkout_keeps_its_data_beside_the_code_and_an_install_does_not(monkeypatch, tmp_path):
    monkeypatch.delenv("INSTAT_DATA_DIR", raising=False)
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "pyproject.toml").write_text("[project]\n")
    monkeypatch.setattr(config, "ROOT", checkout)
    assert config._data_dir() == checkout / "data"
    installed = tmp_path / "site-packages"
    installed.mkdir()
    monkeypatch.setattr(config, "ROOT", installed)
    monkeypatch.setattr(config, "_user_data_dir", lambda: tmp_path / "user")
    assert config._data_dir() == tmp_path / "user"


def test_when_no_folder_can_be_written_nothing_is_switched(monkeypatch, tmp_path, restore_paths):
    def refuse(self, *args, **kwargs):
        raise PermissionError("read-only")

    before = config.DATA_DIR, config.RAW_DIR, config.EXPORT_DIR, config.DB_PATH
    monkeypatch.setattr(Path, "mkdir", refuse)
    assert config.ensure_data_dir() is False
    assert (config.DATA_DIR, config.RAW_DIR, config.EXPORT_DIR, config.DB_PATH) == before


def test_the_usual_folder_is_reported_as_usual_and_all_paths_follow_it(monkeypatch, tmp_path, restore_paths):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    assert config.ensure_data_dir() is True
    assert config.DATA_DIR == tmp_path / "data" and config.RAW_DIR == tmp_path / "data" / "raw"
    assert config.EXPORT_DIR == tmp_path / "data" / "exports" and config.DB_PATH == tmp_path / "data" / "instat.sqlite"
    assert config.DATA_DIR.is_dir() and list(config.DATA_DIR.iterdir()) == []                      # the probe left nothing behind


# --- language ---
@pytest.mark.parametrize("header, expected", [
    ("sq", "sq"), ("sq-AL", "sq"), ("SQ,en;q=0.8", "sq"), ("  sq-AL , en", "sq"), ("en-US,sq;q=0.5", "en"), ("de", "en"), ("", "en"), (None, "en"),
    ("sqx", "sq"),
])
def test_the_language_a_browser_or_locale_asks_for(header, expected):
    assert i18n.guess(header) == expected


@pytest.mark.parametrize("env, expected", [
    ({"LC_ALL": "sq_AL.UTF-8", "LC_MESSAGES": "en_US", "LANG": "en_US"}, "sq"),
    ({"LC_MESSAGES": "sq_AL", "LANG": "en_US"}, "sq"),
    ({"LANG": "sq_AL.UTF-8"}, "sq"),
    ({"LANG": "en_US.UTF-8"}, "en"),
    ({}, "en"),
])
def test_a_console_on_unix_uses_the_first_locale_variable_that_is_set(monkeypatch, env, expected):
    for name in ("LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(i18n.sys, "platform", "linux")
    assert i18n.system_language() == expected


def test_a_windows_console_uses_the_language_of_the_computer(monkeypatch):
    import types

    class Kernel:
        def __init__(self, ui):
            self.ui = ui

        def GetUserDefaultUILanguage(self):
            return self.ui

    for ui, expected in ((0x041C, "sq"), (0x0409, "en"), (0x0C1C, "sq")):                         # Albanian, English (US), Albanian with another sublanguage
        fake = types.SimpleNamespace(windll=types.SimpleNamespace(kernel32=Kernel(ui)))
        monkeypatch.setitem(sys.modules, "ctypes", fake)
        monkeypatch.setattr(i18n.sys, "platform", "win32")
        assert i18n.system_language() == expected


def test_a_windows_console_that_cannot_tell_is_english(monkeypatch):
    import types

    class Broken:
        def GetUserDefaultUILanguage(self):
            raise OSError("no such call")

    monkeypatch.setitem(sys.modules, "ctypes", types.SimpleNamespace(windll=types.SimpleNamespace(kernel32=Broken())))
    monkeypatch.setattr(i18n.sys, "platform", "win32")
    assert i18n.system_language() == "en"


# --- python -m instatkit ---
def test_running_the_package_as_a_program_exits_with_the_code_of_main(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["instatkit", "--version"])
    with pytest.raises(SystemExit) as stopped:
        runpy.run_module("instatkit", run_name="__main__")
    assert stopped.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_importing_the_package_main_module_runs_nothing(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["instatkit", "--version"])
    runpy.run_module("instatkit", run_name="not_main")
    assert capsys.readouterr().out == ""
