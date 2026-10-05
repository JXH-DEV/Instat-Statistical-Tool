"""The command line: ``instat <command>`` (or ``python -m instatkit <command>``).

With no command the app starts. Nothing is downloaded unless you name a file or a page, and there is no "download
everything" command on purpose. The messages follow the language of the computer; ``--lang sq`` or ``--lang en`` (or the
environment variable ``INSTAT_LANG``) overrides that.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
from pathlib import Path

from . import __version__, config, i18n
from .i18n import tn, tr

EXPORTS = ("html", "csv", "xlsx", "sqlite", "md", "zip")


def _choose_language(argv: list[str] | None) -> None:
    """Pick the language before the parser is built, so that its help text is in that language too: ``--lang``, else the
    environment variable, else the language of the computer."""
    args = sys.argv[1:] if argv is None else argv
    code = os.environ.get("INSTAT_LANG") or i18n.system_language()
    for i, arg in enumerate(args):
        if arg == "--lang" and i + 1 < len(args):
            code = args[i + 1]
        elif arg.startswith("--lang="):
            code = arg.split("=", 1)[1]
    i18n.set_language(code)


def _console() -> None:
    """UTF-8 output (Albanian letters on a Windows console) and one flushed line at a time, so the start-up address
    is visible at once even when the output is redirected to a file or another program."""
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(Exception):  # a redirected stream may not support it
            stream.reconfigure(encoding="utf-8", line_buffering=True)


def cmd_search(args) -> int:
    from .sources.search import search_topics

    hits = search_topics(args.query, limit=args.limit)
    if not hits:
        print(tr("No INSTAT topic matched. Try a broader word (prices, labour, population, tourism, trade ...)."))
        return 1
    for h in hits:
        print(f"{h.score:5.1f}  {h.topic.title}  [{h.topic.theme_name}]\n       {h.topic.url}")
    return 0


def cmd_files(args) -> int:
    from .sources.fetch import FetchError, Fetcher
    from .sources.page_links import parse_page
    from .sources.resolve import resolve

    res = resolve(args.target)
    url = res.url
    if res.kind == "topics":
        if not res.hits:
            print(res.message)
            return 1
        url = res.hits[0].topic.url
        print(tr("Best match: {name}", name=res.hits[0].topic.title))
    elif res.kind not in ("topic", "page"):
        print(res.message or tr("Give a topic word or the address of a topic page of INSTAT."))
        return 1
    try:
        listing = parse_page(Fetcher().get_html(url), url)
    except FetchError as exc:
        print(tr("The page could not be opened: {error}", error=exc))
        return 2
    files = tn(len(listing.files), "{n} Excel or CSV file", "{n} Excel or CSV files")
    pdfs = tn(listing.n_pdfs, "{n} PDF link ignored", "{n} PDF links ignored")
    print(f"{listing.title}: {files}, {pdfs}\n{url}\n")
    for i, f in enumerate(listing.files, 1):
        print(f"{i:3d}. [{f.section or tr('Other')}] {f.label}\n       {f.url}")
    return 0


def cmd_fetch(args) -> int:
    from .sources.fetch import FetchError, Fetcher

    try:
        d = Fetcher().download(args.url, force=args.force)
    except FetchError as exc:
        print(tr("The download failed: {error}", error=exc))
        return 2
    where = tr("from the cache") if d.from_cache else tr("downloaded")
    print(tr("{name}  {size} bytes  sha256 {sha}…  ({where})\nsaved at {path}", name=d.filename, size=f"{d.size:,}", sha=d.sha256[:12],
             where=where, path=d.path))
    return 0


def _write_exports(pf, kinds: list[str], out: Path) -> list[Path]:
    from .export.bundle import bundle_bytes
    from .export.excel_export import excel_bytes
    from .export.html_report import build_report
    from .export.tables import sqlite_bytes, tidy_csv, wide_csv
    from .pipeline import slug

    out.mkdir(parents=True, exist_ok=True)
    base = slug(pf.source.label or pf.source.filename.rsplit(".", 1)[0])
    written: list[Path] = []

    def put(name: str, data: bytes | str) -> None:
        p = out / name
        p.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
        written.append(p)

    if "html" in kinds:
        put(f"{base}-report.html", build_report(pf))
    if "xlsx" in kinds:
        put(f"{base}.xlsx", excel_bytes(pf))
    if "sqlite" in kinds:
        put(f"{base}.sqlite", sqlite_bytes(pf))
    if "zip" in kinds:
        put(f"{base}-bundle.zip", bundle_bytes(pf))
    for i, pt in enumerate(pf.tables, 1):
        suffix = f"-t{i}" if len(pf.tables) > 1 else ""
        if "csv" in kinds:
            put(f"{base}{suffix}-tidy.csv", tidy_csv(pt))
            put(f"{base}{suffix}-wide.csv", wide_csv(pt))
        if "md" in kinds:
            put(f"{base}{suffix}-briefing.md", pt.briefing.markdown())
    return written


def _export_kinds(spec: str) -> list[str] | None:
    """The export types named in a comma list, or ``None`` (after saying so) when one of them is not known."""
    kinds = [k.strip() for k in spec.split(",") if k.strip()]
    unknown = [k for k in kinds if k not in EXPORTS]
    if unknown:
        print(tr("Unknown export type(s): {unknown}. Choose from {known}.", unknown=", ".join(unknown), known=", ".join(EXPORTS)))
        return None
    return kinds


def _export(pf, kinds: list[str], out: str | None) -> None:
    if kinds:
        for path in _write_exports(pf, kinds, Path(out or config.EXPORT_DIR)):
            print(tr("wrote {path}", path=path))


def _summarise(pf, *, quiet: bool = False) -> None:
    for e in pf.errors:
        print(f"! {e}")
    for pt in pf.tables:
        p = pt.profile
        print("\n" + tr("=== {title}  (sheet {sheet}; layout confidence {confidence}) ===", title=pt.table.title, sheet=pt.table.sheet,
                       confidence=f"{p.confidence:.0%}"))
        if not quiet:
            print(pt.briefing.markdown().split("\n", 3)[-1].strip())
        bad = [c for c in pt.analysis.checks if c.status in ("warn", "fail")]
        print("\n" + tr("{n} checks, {bad} need attention", n=len(pt.analysis.checks), bad=len(bad)) + ("" if not bad else ":"))
        for c in bad:
            print(f"  - {c.name}: {c.detail}")


def _load(target: str, label: str | None = None):
    from .pipeline import SourceInfo, process_bytes, source_from_download
    from .sources.fetch import FetchError, Fetcher

    if target.lower().startswith(("http://", "https://")):
        try:
            d = Fetcher().download(target)
        except FetchError as exc:
            print(tr("The download failed: {error}", error=exc))
            return None
        return process_bytes(d.data, d.filename, source=source_from_download(d, label=label), label=label)
    path = Path(target)
    if not path.is_file():
        print(tr("File not found: {path}", path=path))
        return None
    data = path.read_bytes()
    return process_bytes(data, path.name, source=SourceInfo(path.name, "", len(data), "local"), label=label)


def cmd_process(args) -> int:
    kinds = _export_kinds(args.export)  # checked first, so a typo does not cost a download
    if kinds is None:
        return 2
    pf = _load(args.target, args.label)
    if pf is None:
        return 2
    _summarise(pf, quiet=args.quiet)
    if not pf.ok:
        return 1
    _export(pf, kinds, args.out)
    return 0


def cmd_inspect(args) -> int:
    from .export.reading import reading_summary

    pf = _load(args.target)
    if pf is None:
        return 2
    for e in pf.errors:
        print(f"! {e}")
    for pt in pf.tables:
        print(f"\n=== {pt.table.title}  [{pt.table.sheet}] ===")
        for k, v in reading_summary(pt):
            print(f"{k:>22}: {v}")
        print()
        print(pt.table.df.head(args.rows).to_string(max_colwidth=36))
    if pf.result:
        for name, why in pf.result.skipped:
            print("\n" + tr("skipped sheet {name}: {why}", name=repr(name), why=why))
    return 0 if pf.ok else 1


def cmd_demo(args) -> int:
    from .demo import DEMOS
    from .pipeline import SourceInfo, process_bytes

    if args.name not in DEMOS:
        print(tr("Available demos: {names}", names=", ".join(DEMOS)))
        return 1
    kinds = _export_kinds(args.export)
    if kinds is None:
        return 2
    label, fname, build = DEMOS[args.name]
    data = build()
    pf = process_bytes(data, fname, source=SourceInfo(fname, "", len(data), "demo"), label=label)
    print(tr("(demo data: the numbers are invented, not INSTAT figures)"))
    _summarise(pf, quiet=args.quiet)
    _export(pf, kinds, args.out)
    return 0


def cmd_serve(args) -> int:
    from .web.server import run

    return run(args.port, open_browser=not args.no_browser, share=args.share)


def cmd_doctor(args) -> int:
    from .doctor import run_checks

    return run_checks(online=args.online)


def _serve_options(p: argparse.ArgumentParser) -> None:
    p.add_argument("--port", type=int, default=8501, help=tr("the first port to try (default 8501)"))
    p.add_argument("--no-browser", action="store_true", help=tr("do not open a browser window"))
    p.add_argument("--share", action="store_true",
                   help=tr("let other computers on this network use the program (they need the access link)"))
    _language_option(p)


def _language_option(p: argparse.ArgumentParser) -> None:
    p.add_argument("--lang", choices=sorted(i18n.LANGUAGES), default=argparse.SUPPRESS,
                   help=tr("language of the messages: en (English) or sq (Albanian)"))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="instat", description=tr("Clean, understand and export the Excel tables of INSTAT (Albania). "
                                                              "With no command the app starts."))
    p.add_argument("--version", action="version", version=f"INSTAT Explorer {__version__}")
    _serve_options(p)
    p.set_defaults(func=cmd_serve)
    sub = p.add_subparsers(dest="command")

    s = sub.add_parser("search", help=tr("find INSTAT topics (works offline)"))
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=8)
    _language_option(s)
    s.set_defaults(func=cmd_search)

    s = sub.add_parser("files", help=tr("list the Excel files on one INSTAT page (downloads that one page)"))
    s.add_argument("target", help=tr("a topic word, or the link of a topic page of INSTAT"))
    _language_option(s)
    s.set_defaults(func=cmd_files)

    s = sub.add_parser("fetch", help=tr("download ONE file into the local cache"))
    s.add_argument("url")
    s.add_argument("--force", action="store_true", help=tr("ignore the cache"))
    _language_option(s)
    s.set_defaults(func=cmd_fetch)

    s = sub.add_parser("process", help=tr("analyse a local file, or one file from a link, and write the exports"))
    s.add_argument("target", help=tr("the path or the link of an .xlsx, .xls or .csv file"))
    s.add_argument("--export", default="html,csv,xlsx",
                   help=tr("comma-separated list from: {kinds} (default html,csv,xlsx)", kinds=", ".join(EXPORTS)))
    s.add_argument("--out", help=tr("output folder (default: the exports folder of the data directory)"))
    s.add_argument("--label", help=tr("English title to use when the sheet has none"))
    s.add_argument("--quiet", action="store_true", help=tr("do not print the findings"))
    _language_option(s)
    s.set_defaults(func=cmd_process)

    s = sub.add_parser("inspect", help=tr("show how a file is read: titles, header, labels, periods (no exports)"))
    s.add_argument("target")
    s.add_argument("--rows", type=int, default=6)
    _language_option(s)
    s.set_defaults(func=cmd_inspect)

    s = sub.add_parser("demo", help=tr("run a built-in sample with invented numbers (no network)"))
    s.add_argument("name", nargs="?", default="cpi")
    s.add_argument("--export", default="", help=tr("comma-separated list from: {kinds}", kinds=", ".join(EXPORTS)))
    s.add_argument("--out")
    s.add_argument("--quiet", action="store_true")
    _language_option(s)
    s.set_defaults(func=cmd_demo)

    s = sub.add_parser("serve", help=tr("start the app (this is the default)"))
    _serve_options(s)
    s.set_defaults(func=cmd_serve)

    s = sub.add_parser("doctor", help=tr("check that this installation works"))
    s.add_argument("--online", action="store_true", help=tr("also check that instat.gov.al can be reached"))
    _language_option(s)
    s.set_defaults(func=cmd_doctor)
    return p


def main(argv: list[str] | None = None) -> int:
    _console()
    _choose_language(argv)
    args = build_parser().parse_args(argv)
    return int(args.func(args) or 0)


def app_main() -> int:
    """The entry point of the ``instat-explorer`` launcher: the app, with the same options as ``instat serve``."""
    _console()
    _choose_language(None)
    p = argparse.ArgumentParser(prog="instat-explorer", description=tr("Start INSTAT Explorer in your browser."))
    p.add_argument("--version", action="version", version=f"INSTAT Explorer {__version__}")
    _serve_options(p)
    return cmd_serve(p.parse_args())
