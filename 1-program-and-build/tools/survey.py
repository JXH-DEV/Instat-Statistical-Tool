"""Run the program over real INSTAT files and report how each was read; the figures in docs/EVIDENCE.md come from this.

    python tools/survey.py                      # the default topics; census tables are sampled; about 150 files
    python tools/survey.py --census 0           # without the census tables
    python tools/survey.py --topics "tourism,wages" --out tourism.json
    python tools/survey.py --offline            # only what is already in the download cache
    python tools/survey.py --save-baseline tools/survey_baseline.json     # remember how every file was read
    python tools/survey.py --check tools/survey_baseline.json             # read the same files again; exit 1 if a reading changed

Files are downloaded through the program's own fetcher (one request at a time, with a pause, cached in the data folder). Set INSTAT_DATA_DIR
to keep the downloads out of the source folder. Nothing is corrected: the output says which files were read, how, and which checks failed.

``--check`` is the regression test on real files. INSTAT replaces files at the same address, so a file is compared only when its bytes are the
ones the baseline was made from (the SHA-256 is recorded); a file that changed is listed, not judged. A changed reading of unchanged bytes means
the program changed: either a mistake, or an improvement, in which case the baseline is saved again and the difference is explained in the change log.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import statistics
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from instatkit.export.excel_export import excel_bytes
from instatkit.export.html_report import build_report
from instatkit.export.tables import sqlite_bytes, tidy_csv
from instatkit.pipeline import process_bytes, source_from_download
from instatkit.sources.fetch import Fetcher, FetchError
from instatkit.sources.page_links import parse_page
from instatkit.sources.search import search_topics

DEFAULT_TOPICS = ["consumer price index", "employment and unemployment from LFS", "gross domestic product", "international trade", "population",
                  "tourism", "average wage", "industrial production", "construction", "agriculture", "census of population", "harmonized index",
                  "producer prices", "transport", "energy", "education", "health", "births", "migration"]


def choose_files(topic_pages: dict[str, dict], census_sample: int) -> list[dict]:
    chosen = []
    for url, page in topic_pages.items():
        files = page["files"]
        if "census-of-population" in url:
            if not census_sample:
                continue
            xls = [f for f in files if f["ext"] == ".xls"]
            xlsx = [f for f in files if f["ext"] == ".xlsx"]
            files = xls[:: max(1, len(xls) // census_sample)][:census_sample] + xlsx[:: max(1, len(xlsx) // census_sample)][:census_sample]
        chosen += [{**f, "topic": page["title"]} for f in files]
    return chosen


def list_pages(fetcher: Fetcher, topics: list[str]) -> dict[str, dict]:
    pages: dict[str, dict] = {}
    for query in topics:
        hits = search_topics(query, limit=1)
        if not hits or hits[0].topic.url in pages:
            continue
        url = hits[0].topic.url
        try:
            page = parse_page(fetcher.get_html(url), url)
        except FetchError as exc:
            print(f"  ! {query}: {exc}", flush=True)
            continue
        pages[url] = {"title": page.title, "files": [{"url": f.url, "label": f.label, "ext": f.ext} for f in page.files]}
        print(f"  {page.title[:50]:50s} {len(page.files):4d} files", flush=True)
    return pages


def process_file(fetcher: Fetcher, entry: dict) -> dict:
    rec = {"topic": entry["topic"], "label": entry["label"], "url": entry["url"]}
    t0 = time.time()
    try:
        d = fetcher.download(entry["url"])
    except FetchError as exc:
        rec["download_error"] = str(exc)
        return rec
    rec.update(size=d.size, fmt=d.fmt, filename=d.filename, file_sha=d.sha256[:16])
    try:
        pf = process_bytes(d.data, d.filename, source=source_from_download(d, label=entry["label"]), label=entry["label"])
        rec.update(ok=pf.ok, errors=pf.errors, tables=[])
        for pt in pf.tables:
            t, p = pt.table, pt.profile
            rec["tables"].append({
                "sheet": t.sheet, "title": t.title, "orientation": t.spec.orientation, "freq": p.freq, "n_obs": p.n_obs, "n_series": p.n_series,
                "confidence": round(p.confidence, 3), "dims": [[d_.name, d_.role] for d_ in p.dims],
                "bad_checks": [(c.key, c.status, c.detail[:160]) for c in pt.analysis.checks if c.status in ("warn", "fail")],
                "tidy_hash": hashlib.sha256(t.df.to_csv(index=False).encode("utf-8")).hexdigest()[:12]})
        if pf.ok:  # every export has to work on real data too
            rec["exports"] = {}
            for name, fn in (("report", lambda: build_report(pf)), ("xlsx", lambda: excel_bytes(pf)), ("sqlite", lambda: sqlite_bytes(pf)),
                             ("csv", lambda: tidy_csv(pf.tables[0]))):
                try:
                    fn()
                    rec["exports"][name] = "ok"
                except Exception as exc:
                    rec["exports"][name] = f"{type(exc).__name__}: {exc}"
    except Exception as exc:  # a crash is a finding, not something to stop on
        rec["crash"] = f"{type(exc).__name__}: {exc}"
        rec["trace"] = traceback.format_exc()[-900:]
    rec["seconds"] = round(time.time() - t0, 2)
    return rec


def reading(rec: dict) -> dict:
    """What a baseline keeps of one file: how it was read, not the data (the hash of the tidy table stands for the values)."""
    out = {"topic": rec.get("topic", ""), "label": rec["label"], "url": rec["url"], "file_sha": rec.get("file_sha"), "ok": bool(rec.get("ok"))}
    if "crash" in rec:
        out["crash"] = rec["crash"]
    out["tables"] = [{"sheet": t["sheet"], "orientation": t["orientation"], "freq": t["freq"], "n_obs": t["n_obs"], "n_series": t["n_series"],
                      "tidy_hash": t["tidy_hash"], "failed_checks": sorted(c[0] for c in t["bad_checks"] if c[1] == "fail")}
                     for t in rec.get("tables", [])]
    return out


def compare(baseline: list[dict], results: list[dict]) -> dict[str, list[str]]:
    """Set today's readings against the baseline. ``changed`` are readings that differ although the file's bytes are the same (the program
    changed); ``source_changed`` are files INSTAT replaced (not compared); ``unreachable`` could not be downloaded (not the program's fault)."""
    today = {r["url"]: r for r in results}
    report: dict[str, list[str]] = {"changed": [], "source_changed": [], "unreachable": [], "unchanged": []}
    for before in baseline:
        label, now = before["label"][:70], today.get(before["url"])
        if now is None or "download_error" in now:
            report["unreachable"].append(label)
        elif now.get("file_sha") != before.get("file_sha"):
            report["source_changed"].append(label)
        elif (diff := _differences(before, reading(now))):
            report["changed"].append(f"{label}: {'; '.join(diff)}")
        else:
            report["unchanged"].append(label)
    return report


def _differences(before: dict, now: dict) -> list[str]:
    if "crash" in now:
        return [f"now crashes ({now['crash'][:80]})"]
    if before["ok"] != now["ok"]:
        return [f"readable {before['ok']} -> {now['ok']}"]
    if len(before["tables"]) != len(now["tables"]):
        return [f"{len(before['tables'])} tables -> {len(now['tables'])}"]
    out = []
    for i, (a, b) in enumerate(zip(before["tables"], now["tables"], strict=True), 1):
        moved = [f"{k} {a[k]} -> {b[k]}" for k in a if a[k] != b[k]]
        if moved:
            out.append(f"table {i} [{a['sheet'][:20]}] " + ", ".join(moved))
    return out


def summarise(results: list[dict]) -> None:
    ok = [r for r in results if r.get("ok")]
    tables = [t for r in ok for t in r["tables"]]
    failed = lambda t: any(c[1] == "fail" for c in t["bad_checks"])  # noqa: E731
    dead = [r for r in results if "download_error" in r]
    crashes = [r for r in results if "crash" in r]
    print(f"\nfiles listed {len(results)} | could not be downloaded {len(dead)} | crashed {len(crashes)} | read {len(ok)}")
    if not tables:
        return
    clean = sum(not failed(t) for t in tables)
    clean_files = sum(not any(failed(t) for t in r["tables"]) for r in ok)
    print(f"tables {len(tables)} | none of the program's checks failed on {clean} ({clean / len(tables):.1%}) | files with every table clean {clean_files}/{len(ok)}")
    print(f"observations {sum(t['n_obs'] for t in tables):,} | formats {dict(collections.Counter(r['fmt'] for r in ok))}")
    secs = [r["seconds"] for r in results if "seconds" in r]
    print(f"time per file: median {statistics.median(secs):.2f}s, max {max(secs):.1f}s | exports all ok: {all(v == 'ok' for r in ok for v in r.get('exports', {}).values())}")
    print("tables with a failed check, by check:", dict(collections.Counter(c[0].split(':')[0] for t in tables for c in t["bad_checks"] if c[1] == "fail")))
    for r in dead:
        print(f"  dead link: {r['label'][:70]}  ({r['download_error'][:60]})")
    for r in crashes:
        print(f"  CRASH: {r['label'][:70]}  {r['crash'][:80]}")
    for r in ok:
        for t in r["tables"]:
            for key, status, detail in t["bad_checks"]:
                if status == "fail":
                    print(f"  flagged: {r['label'][:60]} [{t['sheet'][:20]}] {key.split(':')[0]}: {detail[:70]}")


def write_baseline(path: Path, results: list[dict]) -> int:
    """One file per line, so that a changed reading shows as a changed line in a diff."""
    kept = [reading(r) for r in results if "download_error" not in r]
    path.write_text("[\n" + ",\n".join(json.dumps(k, ensure_ascii=False) for k in kept) + "\n]\n", encoding="utf-8", newline="\n")
    return len(kept)


def print_comparison(report: dict[str, list[str]]) -> None:
    print(f"\nagainst the baseline: {len(report['unchanged'])} read as before | {len(report['changed'])} read differently | "
          f"{len(report['source_changed'])} replaced by INSTAT since (not compared) | {len(report['unreachable'])} not downloadable")
    for line in report["changed"]:
        print(f"  CHANGED: {line}")
    for label in report["source_changed"]:
        print(f"  new file at the same address: {label}")
    for label in report["unreachable"]:
        print(f"  not downloadable: {label}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default="survey.json", help="where to write the per-file results (JSON)")
    ap.add_argument("--topics", help="comma-separated topic words to search for (default: the list in this script)")
    ap.add_argument("--census", type=int, default=15, help="census tables to sample per format (.xls and .xlsx); 0 skips them")
    ap.add_argument("--offline", action="store_true", help="use only files already in the download cache")
    ap.add_argument("--save-baseline", metavar="FILE", help="write how each file was read to FILE (hashes of the tables, no data)")
    ap.add_argument("--check", metavar="FILE", help="read the files listed in a baseline again; exit 1 if a file with the same bytes reads differently")
    args = ap.parse_args(argv)
    fetcher = Fetcher(offline=args.offline)
    baseline: list[dict] | None = None
    if args.check:
        baseline = json.loads(Path(args.check).read_text(encoding="utf-8"))
        chosen = [{"topic": b.get("topic", ""), "label": b["label"], "url": b["url"], "ext": ""} for b in baseline]
    else:
        topics = [t.strip() for t in args.topics.split(",")] if args.topics else DEFAULT_TOPICS
        print("topic pages:", flush=True)
        chosen = choose_files(list_pages(fetcher, topics), args.census)
    print(f"{len(chosen)} files selected\n", flush=True)
    results = []
    for n, entry in enumerate(chosen, 1):
        rec = process_file(fetcher, entry)
        results.append(rec)
        state = "DEAD LINK" if "download_error" in rec else "CRASH" if "crash" in rec else "ok" if rec.get("ok") else "NO TABLE"
        print(f"[{n}/{len(chosen)}] {state:9s} {len(rec.get('tables', []))} tbl  {rec.get('seconds', 0):5.1f}s  {entry['label'][:70]}", flush=True)
        Path(args.out).write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    summarise(results)
    crashed = any("crash" in r for r in results)
    if args.save_baseline:
        print(f"baseline of {write_baseline(Path(args.save_baseline), results)} files written to {args.save_baseline}")
    if baseline is not None:
        report = compare(baseline, results)
        print_comparison(report)
        return 1 if crashed or report["changed"] else 0
    return 1 if crashed else 0


if __name__ == "__main__":
    sys.exit(main())
