"""Shared fixtures. The demo workbooks (``instatkit.demo``) are the test data: they imitate INSTAT's layouts and every
builder returns the values the reader is expected to recover, so no real INSTAT file and no network are needed."""

from __future__ import annotations

import pytest

from instatkit import config, demo, i18n
from instatkit.pipeline import ProcessedFile, SourceInfo, process_bytes


@pytest.fixture(autouse=True)
def english():
    """Every test starts (and ends) in English; the language is per-thread state that would otherwise leak."""
    i18n.set_language("en")
    yield
    i18n.set_language("en")


@pytest.fixture(autouse=True, scope="session")
def private_data_dir(tmp_path_factory):
    """Nothing a test writes (downloads cache, exports, SQLite manifest) may land in the user's data folder."""
    root = tmp_path_factory.mktemp("instat-data")
    saved = config.DATA_DIR, config.RAW_DIR, config.EXPORT_DIR, config.DB_PATH
    config.DATA_DIR, config.RAW_DIR, config.EXPORT_DIR, config.DB_PATH = root, root / "raw", root / "exports", root / "instat.sqlite"
    yield root
    config.DATA_DIR, config.RAW_DIR, config.EXPORT_DIR, config.DB_PATH = saved


def process_demo(name: str, lang: str = "en") -> ProcessedFile:
    label, fname, build = demo.DEMOS[name]
    data = build()
    with i18n.using(lang):
        return process_bytes(data, fname, source=SourceInfo(fname, "", len(data), "demo"), label=label)


@pytest.fixture(scope="session")
def demo_file():
    """``demo_file("cpi")`` or ``demo_file("cpi", "sq")``: the processed demo, built once per session. Treat as read-only."""
    cache: dict[tuple[str, str], ProcessedFile] = {}

    def get(name: str, lang: str = "en") -> ProcessedFile:
        if (name, lang) not in cache:
            cache[(name, lang)] = process_demo(name, lang)
        return cache[(name, lang)]

    return get


def process_workbook_bytes(data: bytes, filename: str = "test.xlsx", lang: str = "en") -> ProcessedFile:
    with i18n.using(lang):
        return process_bytes(data, filename, source=SourceInfo(filename, "", len(data), "upload"))
