"""Put repeated tables back together.

INSTAT repeats one table many times: a sheet per prefecture in the same workbook, or a block per sex and area one
under the other on the same sheet. Read separately they are a dozen tables that cannot be compared. When the pieces
share their layout and title, and something tells them apart (the scope line under the title, the sheet name, the
top-left header cell or the label of each block's first row), they are combined into one table with that
distinguishing information as an extra dimension. The pieces stay available as ``TidyTable.parts``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd

from ..i18n import num, tr
from ..semantics import glossary
from ..semantics.textnorm import clean_text, fold, split_bilingual
from .grid import Grid
from .tidy import TidyTable

_TAG_HEADER = {"sex": "Sex", "urban_rural": "Area", "county": "Prefecture", "municipality": "Municipality",
               "education": "Education", "status": "Status", "ownership": "Ownership", "country": "Country"}


def _signature(t: TidyTable) -> tuple:
    s = t.spec
    return (s.orientation, s.header_is_dimension, tuple(c.name for c in s.value_cols),
            tuple(c.measure or "" for c in s.value_cols), len(s.label_cols), tuple(k for k, _ in s.scope),
            tuple(s.header_level_names), tuple(t.dim_columns))


def _title_key(t: TidyTable) -> str:
    return re.sub(r"\s+", " ", (t.title_en or t.title_sq or "").strip().lower())


def _display(text: str) -> str:
    """English side of a bilingual block label (``'Meshkuj Male'`` -> ``'Male'``), else the glossary's, else as written."""
    pair = split_bilingual(text)
    if pair:
        return pair[1]
    return glossary.translate(text) or clean_text(text)


@dataclass
class _Key:
    orig: str
    display: str
    tag: str | None


def _make_key(text: str) -> _Key | None:
    text = clean_text(text)
    if not text or len(text) > 60:
        return None
    disp = _display(text)
    tag = "total" if glossary.is_total_label(text) or glossary.is_total_label(disp) else (glossary.tag_of(disp) or glossary.tag_of(text))
    return _Key(text, disp, tag)


def _cell(grid: Grid | None, r: int, c: int) -> str:
    if grid is None or not (0 <= r < grid.n_rows and 0 <= c < grid.n_cols):
        return ""
    v = grid.cells[r][c]
    return clean_text(v) if v is not None else ""


def _block_keys(members: list[TidyTable], grids: dict[str, Grid], rows_of) -> list[_Key] | None:
    """The key each block carries in its first label column, on the row ``rows_of(spec)[0]``; ``None`` unless all have one."""
    out = []
    for m in members:
        s = m.spec
        rows = rows_of(s)
        if not rows or not s.label_cols:
            return None
        k = _make_key(_cell(grids.get(m.sheet), rows[0], s.label_cols[0]))
        if k is None:
            return None
        out.append(k)
    return out


def _decode(keys: list[_Key]) -> list[dict[str, _Key]] | None:
    """Turn the sequence of block keys into one value per dimension and block.

    A key tagged ``sex`` sets the sex; a key tagged ``urban_rural`` sets the area and puts every dimension that was
    already being split back to *Total* (INSTAT lists Total, Male, Female for the country, then again for Rural, then
    for Urban); ``total`` resets everything. Untagged keys are one plain block dimension and must all differ."""
    tags = [k.tag for k in keys]
    if all(t is None for t in tags) or any(t is None for t in tags):
        if len({fold(k.display) for k in keys}) == len(keys):
            return [{"Block": k} for k in keys]
        return None
    dims = list(dict.fromkeys(t for t in tags if t != "total"))
    if not dims:
        return None
    first_seen = {t: tags.index(t) for t in dims}
    total = {t: _Key("", "Total", "total") for t in dims}
    cur = dict(total)
    out = []
    for k in keys:
        if k.tag == "total":
            cur = dict(total)
        else:
            for t in dims:  # a key resets the splits that began before its own dimension did
                if t != k.tag and first_seen[t] < first_seen[k.tag]:
                    cur[t] = total[t]
            cur[k.tag] = k
        out.append({_TAG_HEADER.get(t, t.replace("_", " ").title()): v for t, v in cur.items()})
    combos = [tuple(fold(v.display) for v in o.values()) for o in out]
    return out if len(set(combos)) == len(combos) else None


def _try_stack(members: list[TidyTable], grids: dict[str, Grid]) -> TidyTable | None:
    titles = {_title_key(m) for m in members if _title_key(m)}
    if len(titles) > 1:
        return None
    sheets = [m.sheet for m in members]
    scopes = [tuple(v for _k, v in m.spec.scope) for m in members]
    labels: list[dict[str, _Key]] | None = None
    first_row_blocks = False
    if all(scopes) and len(set(scopes)) == len(scopes):
        mode = "scope"
    elif len(set(sheets)) == len(sheets) and len(titles) == 1 and all(m.title_en or m.title_sq for m in members):
        mode = "sheet"
        labels = [{"Sheet": _Key(m.sheet, m.sheet, None)} for m in members]
    elif len(set(sheets)) == 1:
        mode = "blocks"
        labels = _decode(keys) if (keys := _block_keys(members, grids, lambda s: s.header_rows)) else None  # the top-left header cell
        if labels is None and (keys := _block_keys(members, grids, lambda s: s.data_rows)):  # else the block's first row
            labels = _decode(keys)
            first_row_blocks = labels is not None
        if labels is None:
            return None
    else:
        return None
    return _concat(members, labels, mode, first_row_blocks)


def _concat(members: list[TidyTable], labels: list[dict[str, _Key]] | None, mode: str, first_row_blocks: bool) -> TidyTable:
    first = members[0]
    n = len(first.dim_columns)
    new_headers = list(labels[0]) if labels else []
    new_cols = [f"dim_{n + 1 + i}" for i in range(len(new_headers))]
    multi_sheet = len({m.sheet for m in members}) > 1
    frames = []
    unit0 = first.df["unit"].iloc[0] if len(first.df) else ""
    for i, m in enumerate(members):
        df = m.df.copy()
        if mode == "blocks":  # later blocks carry no title of their own: they take the first block's measure and unit
            df["measure"] = df["measure"].where(df["measure"] != m.measure, first.measure)
            df["unit"] = unit0
        if first_row_blocks:  # the block's first row is its total, labelled with the block key
            s = m.spec
            row_no = s.data_rows[0] + s.origin[0] + 1
            mask = df["src_ref"].str.extract(r"(\d+)$")[0].astype(float) == row_no
            d0 = m.dim_columns[0]
            if f"{d0}_orig" not in df.columns:
                df[f"{d0}_orig"] = df[d0]
            df.loc[mask, d0] = "Total"
            df.loc[mask, "is_total"] = True
        if labels:
            for col, header in zip(new_cols, new_headers):
                key = labels[i][header]
                df[col] = key.display
                if key.orig and key.orig != key.display:
                    df[f"{col}_orig"] = key.orig
        if multi_sheet:
            df["src_ref"] = m.sheet + "!" + df["src_ref"].astype(str)
        frames.append(df)
    big = pd.concat(frames, ignore_index=True)
    for col in [c for c in big.columns if c.endswith("_orig")]:
        base = col[: -len("_orig")]
        if base in big.columns:
            big[col] = big[col].fillna(big[base])
    dim_columns = first.dim_columns + new_cols
    keys = ["measure"] + dim_columns + [c for c in ("code", "section") if c in big.columns]
    big["series_id"] = big.groupby(keys, sort=False, dropna=False).ngroup()
    dim_info = {k: dict(v) for k, v in first.dim_info.items()}
    for col, header in zip(new_cols, new_headers):
        dim_info[col] = {"source": "block", "header": header}
    if mode == "blocks" and not first_row_blocks:  # the top-left header cell was the block key, not the labels' header
        dim_info[first.dim_columns[0]] = {**dim_info.get(first.dim_columns[0], {}), "header": ""}
    warnings = list(dict.fromkeys(w for m in members for w in m.warnings))
    n = num(len(members))
    if mode == "scope":
        text = tr("{n} sheets, one per place, have the same layout and were combined into one table. The original pieces are kept "
                  "under “How it was read”.", n=n)
    elif mode == "sheet":
        text = tr("{n} sheets have the same layout and were combined into one table. The original pieces are kept under “How it was "
                  "read”.", n=n)
    else:
        text = tr("{n} blocks on the sheet have the same layout and were combined into one table. The original pieces are kept under "
                  "“How it was read”.", n=n)
    warnings.append(text)
    title_en = next((m.title_en for m in members if m.title_en), None)
    title_sq = next((m.title_sq for m in members if m.title_sq), None)
    measure_names = {k: v for m in members for k, v in m.measure_names.items()}
    label_words = {k: v for m in members for k, v in m.label_words.items()}
    return TidyTable(table_id=f"{first.table_id}_stacked", sheet=first.sheet, spec=first.spec, df=big, dim_columns=dim_columns,
                     dim_info=dim_info, title_en=title_en, title_sq=title_sq, measure=first.measure, measure_names=measure_names,
                     label_words=label_words, warnings=warnings, parts=list(members))


def stack_tables(tables: list[TidyTable], grids: dict[str, Grid]) -> list[TidyTable]:
    """Replace each family of repeated tables by one combined table (placed where the first piece was)."""
    groups: dict[tuple, list[int]] = {}
    for i, t in enumerate(tables):
        groups.setdefault(_signature(t), []).append(i)
    stacked: dict[int, TidyTable] = {}
    used: set[int] = set()
    for idx in groups.values():
        if len(idx) < 2:
            continue
        st = _try_stack([tables[i] for i in idx], grids)
        if st is not None:
            stacked[idx[0]] = st
            used.update(idx)
    return [stacked.get(i, t) for i, t in enumerate(tables) if i not in used or i in stacked]
