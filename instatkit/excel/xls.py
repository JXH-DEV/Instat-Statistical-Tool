"""Legacy ``.xls`` (BIFF) reader on xlrd, which is only imported when such a file arrives."""

from __future__ import annotations

from .. import config
from ..i18n import tr
from .raw import ParsedBook, SheetBuilder, UnreadableWorkbook


def parse(data: bytes) -> ParsedBook:
    import xlrd

    notes: list[str] = []
    try:
        try:
            book = xlrd.open_workbook(file_contents=data, formatting_info=True)
            formatted = True
        except NotImplementedError:  # formatting info is not available for the oldest BIFF versions
            book = xlrd.open_workbook(file_contents=data)
            formatted = False
            notes.append(tr("Merged cells and formats cannot be read from this old .xls file."))
    except xlrd.XLRDError as exc:
        msg = str(exc)
        if "encrypt" in msg.lower() or "password" in msg.lower():
            raise UnreadableWorkbook(tr("The workbook is password-protected.")) from exc
        raise UnreadableWorkbook(tr("The old .xls file could not be read: {error}", error=msg)) from exc
    except Exception as exc:
        raise UnreadableWorkbook(tr("The old .xls file could not be read ({error}).", error=type(exc).__name__)) from exc

    empty = (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK)
    pct_formats = set()
    if formatted:  # the cell formats whose pattern shows a percent sign
        pct_formats = {i for i, xf in enumerate(book.xf_list) if "%" in book.format_map[xf.format_key].format_str}
    sheets = []
    for sh in book.sheets():
        sb = SheetBuilder(sh.name, sh.visibility == 0)
        sb.truncated = sh.nrows > config.MAX_ROWS or sh.ncols > config.MAX_COLS
        for r in range(min(sh.nrows, config.MAX_ROWS)):
            types, values = sh.row_types(r, 0, config.MAX_COLS), sh.row_values(r, 0, config.MAX_COLS)
            for c, (ty, v) in enumerate(zip(types, values)):
                if ty in empty:
                    continue
                pct = False
                if ty == xlrd.XL_CELL_DATE:
                    try:
                        v = xlrd.xldate_as_datetime(v, book.datemode)
                    except Exception:
                        continue
                elif ty == xlrd.XL_CELL_BOOLEAN:
                    v = bool(v)
                elif ty == xlrd.XL_CELL_ERROR:
                    v = xlrd.error_text_from_code.get(v, "#ERR")
                elif ty == xlrd.XL_CELL_NUMBER and pct_formats:
                    pct = sh.cell_xf_index(r, c) in pct_formats
                sb.put(r, c, v, pct)
        if formatted:
            for rlo, rhi, clo, chi in sh.merged_cells:  # xlrd's upper bounds are exclusive
                sb.merge(rlo, clo, rhi - 1, chi - 1)
            sb.hidden_rows.update(r for r, info in sh.rowinfo_map.items() if info.hidden and r < config.MAX_ROWS)
            sb.hidden_cols.update(c for c, info in sh.colinfo_map.items() if info.hidden and c < config.MAX_COLS)
        sheets.append(sb.finish())
    book.release_resources()
    return ParsedBook(sheets, notes=notes)
