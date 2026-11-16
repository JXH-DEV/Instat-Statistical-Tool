"""The Albanian catalogue must cover every sentence the program can show, and nothing else.

Sentences are found where they are written: ``tr("...")``, ``tn("...", "...")`` and ``N_("...")`` in the Python code, ``t('...')``
and ``N_('...')`` in the page's script, and ``{{...}}`` in its HTML. A sentence missing here would silently show in English
in the Albanian interface; one left over means a sentence was changed and its translation forgotten."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent / "instatkit"
CATALOG = json.loads((ROOT / "data" / "sq.json").read_text(encoding="utf-8"))
JS = (ROOT / "web" / "static" / "app.js").read_text(encoding="utf-8")
HTML = (ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
HTML_FIXED = {"lang", "other", "other_name", "v"}


def _literal(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def python_sentences() -> dict[str, str]:
    found: dict[str, str] = {}
    for path in sorted(ROOT.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
            where = f"{path.relative_to(ROOT.parent)}:{node.lineno}"
            if name in ("tr", "N_") and node.args and (s := _literal(node.args[0])):
                found.setdefault(s, where)
            elif name == "tn" and len(node.args) >= 3:
                for arg in node.args[1:3]:
                    if s := _literal(arg):
                        found.setdefault(s, where)
    return found


def js_sentences() -> set[str]:
    single, double = r"(?:[^'\\]|\\.)*", r'(?:[^"\\]|\\.)*'
    found = set(re.findall(rf"\bt\('({single})'", JS)) | set(re.findall(rf'\bt\("({double})"', JS)) | set(re.findall(rf"N_\('({single})'\)", JS))
    for one, other in re.findall(rf"\btn\([^,]+,\s*'({single})',\s*'({single})'", JS):
        found |= {one, other}
    return {s.replace("\\'", "'") for s in found}


def html_sentences() -> set[str]:
    return set(re.findall(r"\{\{([^}]+)\}\}", HTML)) - HTML_FIXED


def test_the_catalogue_is_well_formed():
    assert len(CATALOG) > 800
    assert all(isinstance(k, str) and isinstance(v, str) and k.strip() and v.strip() for k, v in CATALOG.items())
    raw = (ROOT / "data" / "sq.json").read_text(encoding="utf-8")
    assert not raw.startswith("﻿")
    keys = json.loads(raw, object_pairs_hook=lambda pairs: [k for k, _v in pairs])
    assert len(keys) == len(set(keys)), "duplicate keys: the later one silently wins"


def test_placeholders_match_between_english_and_albanian():
    for english, albanian in CATALOG.items():
        assert sorted(re.findall(r"\{(\w+)\}", english)) == sorted(re.findall(r"\{(\w+)\}", albanian)), english


def test_every_python_sentence_is_translated():
    missing = {s: where for s, where in python_sentences().items() if s not in CATALOG}
    assert not missing, "\n".join(f"{where}: {s!r}" for s, where in sorted(missing.items(), key=lambda kv: kv[1]))


def test_every_page_sentence_is_translated():
    missing = sorted(s for s in js_sentences() | html_sentences() if s not in CATALOG)
    assert not missing, missing


def test_nothing_in_the_catalogue_is_left_over():
    used = set(python_sentences()) | js_sentences() | html_sentences()
    stale = sorted(k for k in CATALOG if k not in used)
    assert not stale, stale


def test_most_translations_differ_from_the_english():
    same = [k for k, v in CATALOG.items() if k == v]
    assert len(same) < 15, same                      # a few are the same in both languages (ALL, EUR, USD); the rest were forgotten


@pytest.mark.parametrize("sentence", ["The request was not valid JSON.", "No data table was found in this file.", "Download and analyse this file"])
def test_sample_sentences_really_change_language(sentence):
    from instatkit import i18n

    with i18n.using("sq"):
        assert i18n.tr(sentence) != sentence
    assert i18n.tr(sentence) == sentence


def test_translated_placeholders_can_be_filled():
    from instatkit import i18n

    with i18n.using("sq"):
        for english in CATALOG:
            fields = set(re.findall(r"\{(\w+)\}", english))
            if fields:
                text = i18n.tr(english, **dict.fromkeys(fields, "X"))
                assert "{" not in text, english
