"""Break one thing at a time in a module and see whether the test suite notices.

    python tools/mutation_test.py COPY instatkit/analysis/checks.py --count 22 --seed 7 --out checks.json

COPY is a copy of the repository (never the repository itself: the tool rewrites the module in it and puts it back). Each mutant changes one
comparison, arithmetic or boolean operator, one ``not`` or one number; pytest then runs with ``-x``. A mutant is *killed* when a test fails (or
the run hangs, or the module no longer imports) and *survived* when the whole suite still passes. Survivors are the places where a wrong
program would go unnoticed: each is either a test that is missing or a change that makes no difference (a counter only tested for being
non-zero, a branch that cannot be reached).

The mutants are a random sample of all the places in the module, drawn with ``--seed``; the same seed on the same module picks the same places.
Before anything is changed the tool checks that the unmodified suite passes and that a module which cannot be imported makes it fail, so that a
copy that tests the wrong files cannot report a good score.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SWAP_COMPARE = {ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE, ast.GtE: ast.Gt, ast.Eq: ast.NotEq, ast.NotEq: ast.Eq,
                ast.Is: ast.IsNot, ast.IsNot: ast.Is, ast.In: ast.NotIn, ast.NotIn: ast.In}
SWAP_ARITHMETIC = {ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.Div, ast.Div: ast.Mult, ast.FloorDiv: ast.Mult}
TRANSLATORS = {"tr", "tn", "N_"}  # the text of a sentence is not logic: changing a number inside one proves nothing


class Mutator(ast.NodeTransformer):
    """Walks the tree in a fixed order. Without ``apply`` it only lists the places; with ``apply=k`` it changes place number k."""

    def __init__(self, apply: int | None = None) -> None:
        self.apply = apply
        self.sites: list[tuple[int, str]] = []
        self.in_translator = 0

    def _site(self, node: ast.AST, what: str) -> bool:
        k = len(self.sites)
        self.sites.append((getattr(node, "lineno", 0), what))
        return k == self.apply

    def visit_Call(self, node: ast.Call) -> ast.AST:
        name = node.func.id if isinstance(node.func, ast.Name) else ""
        self.in_translator += name in TRANSLATORS
        self.generic_visit(node)
        self.in_translator -= name in TRANSLATORS
        return node

    def visit_Compare(self, node: ast.Compare) -> ast.AST:
        self.generic_visit(node)
        for i, op in enumerate(node.ops):
            if type(op) in SWAP_COMPARE and self._site(node, f"{type(op).__name__} -> {SWAP_COMPARE[type(op)].__name__}"):
                node.ops[i] = SWAP_COMPARE[type(op)]()
        return node

    def visit_BinOp(self, node: ast.BinOp) -> ast.AST:
        self.generic_visit(node)
        if type(node.op) in SWAP_ARITHMETIC and self._site(node, f"{type(node.op).__name__} -> {SWAP_ARITHMETIC[type(node.op)].__name__}"):
            node.op = SWAP_ARITHMETIC[type(node.op)]()
        return node

    def visit_BoolOp(self, node: ast.BoolOp) -> ast.AST:
        self.generic_visit(node)
        if self._site(node, "and <-> or"):
            node.op = ast.Or() if isinstance(node.op, ast.And) else ast.And()
        return node

    def visit_UnaryOp(self, node: ast.UnaryOp) -> ast.AST:
        self.generic_visit(node)
        if isinstance(node.op, ast.Not) and self._site(node, "remove not"):
            return node.operand
        return node

    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        if self.in_translator or isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            return node
        if self._site(node, f"number {node.value!r} -> {node.value + 1!r}"):
            return ast.copy_location(ast.Constant(node.value + 1), node)
        return node


def sites_of(source: str) -> list[tuple[int, str]]:
    mutator = Mutator()
    mutator.visit(ast.parse(source))
    return mutator.sites


def mutate(source: str, k: int) -> str:
    tree = ast.parse(source)
    Mutator(apply=k).visit(tree)
    return ast.unparse(ast.fix_missing_locations(tree))


def run_tests(copy: Path, timeout: int) -> tuple[bool, str]:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    command = [sys.executable, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider", "--no-header", "-W", "ignore::DeprecationWarning"]
    try:
        done = subprocess.run(command, cwd=copy, env=env, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "timeout"
    return done.returncode == 0, done.stdout[-1500:]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("copy", type=Path, help="a copy of the repository")
    ap.add_argument("module", help="the module to break, relative to the copy, e.g. instatkit/analysis/checks.py")
    ap.add_argument("--count", type=int, default=22, help="how many mutants (default 22)")
    ap.add_argument("--seed", type=int, default=7, help="which random sample of places (default 7)")
    ap.add_argument("--out", type=Path, default=Path("mutation.json"), help="where to write the results (JSON), updated after every mutant")
    ap.add_argument("--timeout", type=int, default=150, help="seconds a test run may take before the mutant counts as killed")
    args = ap.parse_args()

    copy = args.copy.resolve()
    if copy == ROOT:
        ap.error("COPY must be a copy of the repository, not the repository itself")
    target = copy / args.module
    original = target.read_bytes().decode("utf-8")

    def put(text: str) -> None:
        target.write_bytes(text.encode("utf-8"))  # byte for byte: write_text would turn \n into \r\n on Windows

    ok, tail = run_tests(copy, args.timeout)
    if not ok:
        print("the suite does not pass before any change:\n" + tail, file=sys.stderr)
        return 2
    put(original + "\nraise RuntimeError('canary')\n")
    try:
        canary_ok, _ = run_tests(copy, args.timeout)
    finally:
        put(original)
    if canary_ok:
        print("the tests do not notice a module that cannot be imported: the copy is not what pytest imports", file=sys.stderr)
        return 2

    sites = sites_of(original)
    chosen = sorted(random.Random(args.seed).sample(range(len(sites)), min(args.count, len(sites))))
    results = []
    for n, k in enumerate(chosen, 1):
        line, what = sites[k]
        started = time.time()
        try:
            put(mutate(original, k))
            survived, tail = run_tests(copy, args.timeout)
        finally:
            put(original)
        killed_by = "" if survived else " | ".join(row[:140] for row in tail.splitlines() if row.startswith(("FAILED", "ERROR")))[:300]
        results.append({"module": args.module, "line": line, "change": what, "survived": survived,
                        "seconds": round(time.time() - started, 1), "killed_by": killed_by})
        args.out.write_text(json.dumps({"module": args.module, "sites": len(sites), "done": n, "of": len(chosen), "results": results}, indent=1),
                            encoding="utf-8")
        print(f"{args.module} {n}/{len(chosen)} line {line}: {what}: {'SURVIVED' if survived else 'killed'}", flush=True)
    killed = sum(not r["survived"] for r in results)
    print(f"{args.module}: {killed} of {len(results)} mutants killed ({len(sites)} places in the module)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
