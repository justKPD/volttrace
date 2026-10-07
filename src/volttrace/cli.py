"""Command line: lint | run | mutants | falsify | pipeline."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import yaml

from volttrace import __version__
from volttrace.catalog import TestCase, lint, load_catalog
from volttrace.evaluate import RequirementSet, evaluate
from volttrace.falsify import Template, counterexample_case, falsify
from volttrace.report import RunRecord, run_summary_md, write_json, write_junit, write_mdf
from volttrace.sim import simulate
from volttrace.sut.mutants import MUTANTS, sut_factory


def _run_case(case: TestCase, reqset: RequirementSet, sut: str, out: Path | None, mdf: bool) -> RunRecord:
    t0 = time.perf_counter()
    trace = simulate(case.scenario, sut_factory(sut), sut_name=sut)
    results = evaluate(trace, reqset, list(case.requirements))
    wall = time.perf_counter() - t0
    mdf_path = None
    if out is not None and mdf:
        p = write_mdf(trace, out / "mdf" / f"{case.id}_{sut}.mf4", comment=f"{case.id}: {case.title}")
        mdf_path = str(p.relative_to(out)) if p else None
    rec = RunRecord(case, sut, "sil", results, float(trace.t[-1]), wall, mdf_path)
    if case.raw.get("known_issue"):
        rec.extra["known_issue"] = case.raw["known_issue"]
    return rec


def _gate(records: list[RunRecord]) -> tuple[list[str], list[str], list[str]]:
    """Return (blocking failures, expected failures, unexpected passes of known issues)."""
    blocking, xfail, xpass = [], [], []
    for rec in records:
        issue = rec.extra.get("known_issue")
        if rec.verdict == "FAIL":
            (xfail if issue else blocking).append(f"{rec.case.id} ({issue})" if issue else rec.case.id)
        elif issue:
            xpass.append(f"{rec.case.id} ({issue})")
    return blocking, xfail, xpass


def cmd_lint(args: argparse.Namespace) -> int:
    reqset = RequirementSet.load(args.requirements)
    problems = lint(load_catalog(args.catalog), reqset)
    for p in problems:
        print(f"LINT {p}")
    print(f"lint: {len(problems)} problem(s), {len(reqset.reqs)} requirements")
    return 1 if problems else 0


def cmd_run(args: argparse.Namespace) -> int:
    reqset = RequirementSet.load(args.requirements)
    cases = load_catalog(args.catalog)
    out = Path(args.out)
    records = []
    for case in cases:
        rec = _run_case(case, reqset, args.sut, out, not args.no_mdf)
        records.append(rec)
        tag = f" [known issue {rec.extra['known_issue']}]" if "known_issue" in rec.extra else ""
        print(f"{rec.case.id:<12} {rec.verdict:<13} sim {rec.sim_seconds:6.1f}s  wall {rec.wall_seconds:5.2f}s{tag}")
    write_json(records, out / f"results_{args.sut}.json", {"sut": args.sut, "version": __version__})
    write_junit(records, out / f"junit_{args.sut}.xml", f"volttrace.{args.sut}")
    (out / f"summary_{args.sut}.md").write_text(run_summary_md(records, reqset, f"SiL run - SUT {args.sut}"))
    blocking, xfail, xpass = _gate(records)
    print(
        f"blocking failures: {blocking or 'none'}; known issues failing: {xfail or 'none'}; "
        f"known issues now passing: {xpass or 'none'}"
    )
    return 1 if blocking else 0


def mutation_matrix(reqset: RequirementSet, cases: list[TestCase]) -> dict:
    """Kill matrix: which test kills which mutant (FAIL on mutant where the clean SUT does not fail)."""
    base = {c.id: _run_case(c, reqset, "baseline", None, False) for c in cases}
    base_fail = {cid: {r.req_id for r in rec.results if r.verdict == "FAIL"} for cid, rec in base.items()}
    rows = []
    for name, info in MUTANTS.items():
        killers = []
        for c in cases:
            rec = _run_case(c, reqset, name, None, False)
            newly = [r.req_id for r in rec.results if r.verdict == "FAIL" and r.req_id not in base_fail[c.id]]
            if newly:
                killers.append({"test": c.id, "requirements": newly})
        rows.append(
            {
                "mutant": name,
                "description": info.description,
                "fidelity": info.fidelity,
                "killed": bool(killers),
                "killed_by": killers,
            }
        )
    killed = sum(r["killed"] for r in rows)
    sil_rows = [r for r in rows if r["fidelity"] == "sil"]
    return {
        "mutants": rows,
        "killed": killed,
        "total": len(rows),
        "sil_killable_killed": sum(r["killed"] for r in sil_rows),
        "sil_killable_total": len(sil_rows),
    }


def cmd_mutants(args: argparse.Namespace) -> int:
    reqset = RequirementSet.load(args.requirements)
    cases = load_catalog(args.catalog)
    m = mutation_matrix(reqset, cases)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "mutation_matrix.json").write_text(json.dumps(m, indent=2))
    lines = [
        "# Mutation kill matrix",
        "",
        f"Killed {m['killed']}/{m['total']} mutants "
        f"({m['sil_killable_killed']}/{m['sil_killable_total']} of those observable in SiL).",
        "",
        "| Mutant | Seeded bug | Observable in | Killed by |",
        "|---|---|---|---|",
    ]
    for r in m["mutants"]:
        by = "; ".join(f"{k['test']} ({', '.join(k['requirements'])})" for k in r["killed_by"]) or "**survived**"
        lines.append(f"| {r['mutant']} | {r['description']} | {r['fidelity']} | {by} |")
    (out / "mutation_matrix.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


def cmd_falsify(args: argparse.Namespace) -> int:
    reqset = RequirementSet.load(args.requirements)
    tpl = Template.load(args.template)
    res = falsify(tpl, reqset, sut_factory(args.sut), args.sut, args.strategy, args.budget, seed=args.seed)
    best = res.best
    print(f"{tpl.id} [{args.strategy}, seed {args.seed}] sims={len(res.samples)}", end=" ")
    print(f"best robustness={best.robustness:+.4f}")
    print(f"  per target: { {k: round(v, 4) for k, v in best.per_target.items()} }")
    print(f"  scenario: {json.dumps(best.scenario)}")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"falsify_{tpl.id}_{args.sut}_{args.strategy}_s{args.seed}.json").write_text(
        json.dumps(
            {
                "template": tpl.id,
                "strategy": args.strategy,
                "sut": args.sut,
                "seed": args.seed,
                "found": res.found,
                "sims_to_first_counterexample": res.sims_to_first_counterexample,
                "best": {"robustness": best.robustness, "per_target": best.per_target, "scenario": best.scenario},
                "trajectory": res.trajectory(),
            },
            indent=2,
        )
    )
    if res.found and args.emit:
        case = counterexample_case(tpl, best, args.sut)
        path = Path(args.emit) / f"{case['id']}.yaml"
        path.write_text(yaml.safe_dump(case, sort_keys=False))
        print(f"  counterexample written as regression test {path}")
    return 2 if res.found else 0


def cmd_pipeline(args: argparse.Namespace) -> int:
    """CI entry point: static checks -> requirement/catalog lint -> SiL execution -> gate + report."""
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stages: list[tuple[str, str]] = []
    ruff = shutil.which("ruff")
    if ruff:
        rc = subprocess.call([ruff, "check", str(Path(__file__).parent / "sut")])
        stages.append(("static checks (ruff on SUT)", "pass" if rc == 0 else "FAIL"))
        if rc:
            return _finish(out, stages, 1)
    else:
        stages.append(("static checks (ruff on SUT)", "skipped: ruff not installed"))
    if cmd_lint(args):
        stages.append(("requirement & catalog lint", "FAIL"))
        return _finish(out, stages, 1)
    stages.append(("requirement & catalog lint", "pass"))
    rc = cmd_run(args)
    stages.append((f"SiL execution + STL evaluation (SUT {args.sut})", "pass" if rc == 0 else "FAIL"))
    return _finish(out, stages, rc)


def _finish(out: Path, stages: list[tuple[str, str]], rc: int) -> int:
    md = ["# Pipeline", "", "| Stage | Result |", "|---|---|", *[f"| {s} | {r} |" for s, r in stages]]
    (out / "pipeline.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))
    return rc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="volttrace", description=__doc__)
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--requirements", default="requirements.yaml")
        p.add_argument("--catalog", default="catalog")
        p.add_argument("--out", default="out")
        p.add_argument("--sut", default="baseline", help="baseline or a mutant name")

    p = sub.add_parser("lint", help="check requirements and catalogue consistency")
    common(p)
    p.set_defaults(fn=cmd_lint)
    p = sub.add_parser("run", help="run the catalogue in SiL and write JSON / JUnit / MDF4 / Markdown")
    common(p)
    p.add_argument("--no-mdf", action="store_true")
    p.set_defaults(fn=cmd_run)
    p = sub.add_parser("mutants", help="mutation kill matrix of the catalogue")
    common(p)
    p.set_defaults(fn=cmd_mutants)
    p = sub.add_parser("falsify", help="search a scenario template for a counterexample")
    common(p)
    p.add_argument("template")
    p.add_argument("--strategy", choices=["cem", "random"], default="cem")
    p.add_argument("--budget", type=int, default=48)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--emit", help="directory to write a found counterexample as a regression test")
    p.set_defaults(fn=cmd_falsify)
    p = sub.add_parser("pipeline", help="static checks -> lint -> SiL run -> gate (CI entry point)")
    common(p)
    p.add_argument("--no-mdf", action="store_true")
    p.set_defaults(fn=cmd_pipeline)

    args = ap.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    sys.exit(main())
