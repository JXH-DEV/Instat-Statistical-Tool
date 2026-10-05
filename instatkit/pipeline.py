"""From the bytes of a file to the results in one call: read, find the layout, tidy, interpret, analyse and write it up."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .analysis.engine import Analysis, analyze
from .analysis.narrate import Briefing, narrate
from .excel.grid import UnreadableWorkbook, Workbook, read_workbook
from .excel.layout import Overrides
from .excel.tidy import TidyTable, WorkbookResult, extract_tables
from .i18n import language, tr
from .semantics.interpret import DatasetProfile, interpret
from .store import now_iso


@dataclass
class SourceInfo:
    filename: str
    sha256: str
    size: int
    kind: str = "upload"  # url | upload | local | demo
    url: str | None = None
    retrieved_at: str = field(default_factory=now_iso)
    last_modified: str | None = None
    label: str | None = None  # English label from the INSTAT page, when known


@dataclass
class ProcessedTable:
    dataset_id: str
    table: TidyTable
    profile: DatasetProfile
    analysis: Analysis
    briefing: Briefing


@dataclass
class ProcessedFile:
    source: SourceInfo
    result: WorkbookResult | None
    tables: list[ProcessedTable] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    workbook: Workbook | None = None
    overrides: dict[str, Overrides] = field(default_factory=dict)  # sheet name -> manual corrections
    lang: str = field(default_factory=language)  # the language its texts were written in

    @property
    def ok(self) -> bool:
        return bool(self.tables)

    @property
    def meta(self) -> dict:
        return self.result.meta if self.result else {}


def process_bytes(data: bytes, filename: str, *, source: SourceInfo | None = None, label: str | None = None,
                  overrides: dict[str, Overrides] | None = None) -> ProcessedFile:
    """Process spreadsheet bytes. Problems are reported in ``errors`` rather than raised, so the UI can show them."""
    try:
        wb = read_workbook(data, filename)
    except UnreadableWorkbook as exc:
        return ProcessedFile(source or SourceInfo(filename, "", len(data)), None, errors=[str(exc)])
    src = source or SourceInfo(filename, wb.sha256, wb.size)
    src.sha256 = src.sha256 or wb.sha256
    return process_workbook(wb, src, label=label, overrides=overrides)


def process_workbook(wb: Workbook, src: SourceInfo, *, label: str | None = None,
                     overrides: dict[str, Overrides] | None = None) -> ProcessedFile:
    """Run the pipeline on an already-read workbook (used to re-read a file with manual corrections)."""
    if label:
        src.label = label
    overrides = {k: v for k, v in (overrides or {}).items() if not v.is_empty()}
    result = extract_tables(wb, overrides=overrides)
    pf = ProcessedFile(src, result, errors=list(result.warnings), workbook=wb, overrides=overrides)
    multi = len(result.tables) > 1
    for t in result.tables:
        if src.label and not t.title_en:
            t.title_en = f"{src.label}: {t.title_sq or t.sheet}" if multi else src.label
        try:
            profile = interpret(t, source=_source_dict(src))
            with t.wording():
                analysis = analyze(t, profile)
                briefing = narrate(analysis)
            pf.tables.append(ProcessedTable(f"{src.sha256[:10]}-{t.table_id}", t, profile, analysis, briefing))
        except Exception as exc:  # never lose the whole file because one table misbehaves
            pf.errors.append(tr("Sheet '{sheet}' could not be analysed ({error}).", sheet=t.sheet, error=f"{type(exc).__name__}: {exc}"))
    if not pf.tables and not pf.errors:
        pf.errors.append(tr("No data table was found in this file."))
    return pf


def _source_dict(src: SourceInfo) -> dict:
    return {"url": src.url, "filename": src.filename, "sha256": src.sha256, "retrieved_at": src.retrieved_at,
            "last_modified": src.last_modified, "label": src.label}


def source_from_download(d, *, label: str | None = None) -> SourceInfo:
    return SourceInfo(d.filename, d.sha256, d.size, "url", d.url, last_modified=d.last_modified, label=label)


def slug(text: str, limit: int = 60) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")[:limit] or "dataset"
