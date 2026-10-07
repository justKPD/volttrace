"""Command line: lint | run | mutants | falsify | pipeline."""

from __future__ import annotations

import argparse
import contextlib
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


def cmd_bench(args: argparse.Namespace) -> int:
    from dataclasses import asdict

    from volttrace.orchestrator import Runner, all_changes, benchmark, summarise

    reqset = RequirementSet.load(args.requirements)
    cases = load_catalog(args.catalog)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    per_seed = {}
    all_outcomes = []
    for seed in args.seeds:
        runner = Runner(reqset, cases, seed_offset=seed)
        outcomes = benchmark(runner, all_changes())
        all_outcomes.extend(outcomes)
        per_seed[seed] = summarise(outcomes)
        print(f"noise seed set {seed}: {len(runner.cache)} simulations")
    first = args.seeds[0]
    (out / "benchmark.json").write_text(
        json.dumps(
            {
                "seeds": args.seeds,
                "summary_per_seed": per_seed,
                "outcomes": [
                    asdict(o) | {"seed": args.seeds[i // (len(all_outcomes) // len(args.seeds))]}
                    for i, o in enumerate(all_outcomes)
                ],
            },
            indent=2,
            default=float,
        )
    )
    cols = [
        "strategy",
        "bugs_detected",
        "sil_observable_detected",
        "hil_only_detected",
        "vehicle_only_detected",
        "false_alarms_on_clean",
        "mean_hil_minutes",
        "mean_makespan_min",
        "median_ttff_s",
        "clean_change_makespan_min",
    ]
    md = ["# Orchestration benchmark", ""]
    for seed, rows in per_seed.items():
        md += [f"## Noise seed set {seed}", "", "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
        md += ["| " + " | ".join(str(r[c]) for c in cols) + " |" for r in rows]
        md.append("")
    md += [f"## Per change (seed set {first})", ""]
    md += ["| Change | Strategy | Detected in | HiL min | Makespan min | TTFF s |", "|---|---|---|---|---|---|"]
    for o in all_outcomes[: len(all_outcomes) // len(args.seeds)]:
        ttff = "" if o.time_to_first_failure_s is None else round(o.time_to_first_failure_s, 1)
        found = ", ".join(o.detected_in) or "-"
        md.append(f"| {o.change} | {o.strategy} | {found} | {o.hil_minutes:.1f} | {o.makespan_s / 60:.1f} | {ttff} |")
    (out / "benchmark.md").write_text("\n".join(md) + "\n")
    print("\n".join(md[: 6 + 3 * len(per_seed)]))
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    from volttrace.htmlreport import build

    path = build(Path(args.out), Path(args.requirements), Path(args.catalog))
    print(f"evidence report written to {path}")
    return 0


def cmd_build_site(args: argparse.Namespace) -> int:
    """Assemble the deployable Studio: static app, data bundle, evidence report, optional engine wheel."""
    from volttrace.htmlreport import build
    from volttrace.webapi import build_bundle

    root = Path(args.root)
    site = Path(args.out) / "site"
    site.mkdir(parents=True, exist_ok=True)
    shutil.copytree(root / "web", site, dirs_exist_ok=True)
    (site / "data").mkdir(exist_ok=True)
    bundle = build_bundle(root)
    wheels = sorted((site / "py").glob("volttrace-*.whl")) if (site / "py").exists() else []
    bundle["wheel"] = f"py/{wheels[-1].name}" if wheels else None
    (site / "data" / "bundle.json").write_text(json.dumps(bundle))
    (site / "data" / "runtime.json").write_text(json.dumps({"engine": "browser"}))
    build(Path(args.out), root / "requirements.yaml", root / "catalog")
    print(f"site assembled in {site} (engine wheel: {bundle['wheel'] or 'none - local server mode only'})")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    """Serve the Studio with the engine running in this Python process (local use or a hosted backend)."""
    import threading
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    from volttrace.webapi import Engine, build_bundle

    site = Path(args.out) / "site"
    if not (site / "index.html").exists():
        cmd_build_site(args)
    engine = Engine(build_bundle(args.root))
    lock = threading.Lock()
    methods = {"info", "run", "stl_eval", "falsify", "orchestrate", "hunt_start", "hunt_run", "hunt_reveal"}

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a: object, **kw: object) -> None:
            super().__init__(*a, directory=str(site), **kw)  # type: ignore[arg-type]

        def log_message(self, fmt: str, *a: object) -> None:
            if args.verbose:
                super().log_message(fmt, *a)

        def do_GET(self) -> None:  # noqa: N802 (http.server API)
            if self.path.split("?")[0] == "/data/runtime.json":  # tell the app the engine is this process
                data = b'{"engine": "server"}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            super().do_GET()

        def do_POST(self) -> None:  # noqa: N802 (http.server API)
            name = self.path.removeprefix("/api/")
            if name not in methods:
                self.send_error(404)
                return
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            try:
                with lock:
                    result, status = getattr(engine, name)(body), 200
            except Exception as exc:  # report engine errors to the UI instead of dropping the connection
                result, status = {"error": f"{type(exc).__name__}: {exc}"}, 400
            data = json.dumps(result).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"VoltTrace Studio on http://{args.host}:{args.port}/  (engine: local Python, Ctrl+C to stop)")
    with contextlib.suppress(KeyboardInterrupt):
        server.serve_forever()
    return 0


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
    p = sub.add_parser("bench", help="A/B/C orchestration benchmark over all changes (bugs + clean)")
    common(p)
    p.add_argument("--seeds", type=int, nargs="+", default=[0], help="noise seed sets for the HiL-mock runs")
    p.set_defaults(fn=cmd_bench)
    p = sub.add_parser("report", help="self-contained HTML evidence report from out/ (+ fresh evidence simulations)")
    common(p)
    p.set_defaults(fn=cmd_report)
    p = sub.add_parser("build-site", help="assemble the Studio web app, data bundle and report into out/site")
    common(p)
    p.add_argument("--root", default=".")
    p.set_defaults(fn=cmd_build_site)
    p = sub.add_parser("serve", help="run VoltTrace Studio locally with the engine in this Python process")
    common(p)
    p.add_argument("--root", default=".")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--verbose", action="store_true")
    p.set_defaults(fn=cmd_serve)
    p = sub.add_parser("pipeline", help="static checks -> lint -> SiL run -> gate (CI entry point)")
    common(p)
    p.add_argument("--no-mdf", action="store_true")
    p.set_defaults(fn=cmd_pipeline)

    args = ap.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    sys.exit(main())
