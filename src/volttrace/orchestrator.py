"""SiL-first orchestration: which test runs where, and when, for each incoming software change.

Every change is a CI event. It is either one of the seeded bugs (mutants) or a *clean* change
(a refactor or an in-spec calibration tweak), and it declares the features it touches, the way a
commit touches known modules. Four policies decide what to run:

  A  full      every test on SiL and on HiL-mock
  B  static    every test on SiL; on HiL every test that traces to a requirement declared `hil`
  C  adaptive  impact-selected tests on SiL; a test escalates to HiL only if
               (1) it traces to a requirement declared `hil` whose features the change touches, or
               (2) a requirement passed in SiL with a thin margin (INCONCLUSIVE), or
               (3) a criticality-A requirement's SiL margin dropped by more than `margin_drop`
                   against the reference run of the unchanged software (margin regression)
               and only if it did not already fail in SiL.
  D  adaptive + noise-aware: C, plus a change to measurement-consuming code escalates its
               impacted tests to HiL, and every HiL run of such a change is repeated on
               independent noise seeds (stopping at the first failure)

All policies use the same ordering heuristic, the same environments and the same seeds, so the
comparison isolates the policy. Durations come from the environment cost model, not the host clock.
Detection means a requirement FAILs on the change but not on the reference software in the same
environment with the same noise seed.
"""

from __future__ import annotations

import heapq
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from volttrace.catalog import TestCase
from volttrace.env import ENVS, HIL_MOCK, SIL, Env
from volttrace.evaluate import ReqResult, RequirementSet, evaluate
from volttrace.sim import simulate
from volttrace.sut.changes import CLEAN
from volttrace.sut.ems import Calibration, EnergyManager
from volttrace.sut.impact import features_of, noise_sensitive
from volttrace.sut.mutants import MUTANTS


@dataclass(frozen=True)
class Change:
    name: str
    factory: Callable[[Calibration], EnergyManager]
    features: tuple[str, ...]
    buggy: bool
    fidelity: str  # where the bug is observable by design: sil | hil | vehicle | none (clean)
    description: str
    noise_sensitive: bool = False  # touches code that consumes raw measurements (derived, see ownership.yaml)


def all_changes() -> list[Change]:
    """Every seeded bug plus every clean change; features come from impact analysis, not labels."""
    bugs = [
        Change(m.name, m.factory, m.features, True, m.fidelity, m.description, noise_sensitive(m.factory))
        for m in MUTANTS.values()
    ]
    clean = [
        Change(c.__name__, c, features_of(c), False, "none", (c.__doc__ or "").strip(), noise_sensitive(c))
        for c in CLEAN
    ]
    return bugs + clean


# ----------------------------------------------------------------- execution cache
@dataclass
class Execution:
    results: list[ReqResult]
    sim_seconds: float


class Runner:
    """Runs (software, test, env) once and caches it; noise seeds are paired across software versions."""

    def __init__(self, reqset: RequirementSet, cases: list[TestCase], seed_offset: int = 0):
        self.reqset = reqset
        self.seed_offset = seed_offset
        self.cases = {c.id: c for c in cases}
        self.cache: dict[tuple[str, str, str, int], Execution] = {}
        self.factories: dict[str, Callable[[Calibration], EnergyManager]] = {"reference": EnergyManager}

    def run(self, software: str, test_id: str, env: Env, rep: int = 0) -> Execution:
        """`rep` selects an independent noise seed for repeated HiL runs (paired with the reference)."""
        key = (software, test_id, env.name, rep)
        if key not in self.cache:
            case = self.cases[test_id]
            seed = zlib.crc32(test_id.encode()) + self.seed_offset + 7919 * rep
            tr = simulate(case.scenario, self.factories[software], sut_name=software, env=env, seed=seed)
            self.cache[key] = Execution(evaluate(tr, self.reqset, list(case.requirements)), float(tr.t[-1]))
        return self.cache[key]

    def new_failures(self, software: str, test_id: str, env: Env, rep: int = 0) -> list[str]:
        ref = {r.req_id for r in self.run("reference", test_id, env, rep).results if r.verdict == "FAIL"}
        res = self.run(software, test_id, env, rep).results
        return [r.req_id for r in res if r.verdict == "FAIL" and r.req_id not in ref]


# --------------------------------------------------------------------- policies
def _order(cases: list[TestCase]) -> list[TestCase]:
    return sorted(cases, key=lambda c: (c.criticality, c.id))


def _needs_hil(case: TestCase, reqset: RequirementSet) -> bool:
    return case.required_fidelity == "hil" or any(reqset.reqs[r].fidelity == "hil" for r in case.requirements)


def _hil_reqs_touched(case: TestCase, reqset: RequirementSet, change: Change) -> list[str]:
    """`hil`-declared requirements of this test whose features the change touches."""
    touched = set(change.features)
    return [r for r in case.requirements if reqset.reqs[r].fidelity == "hil" and touched & set(reqset.reqs[r].features)]


def _impact(change: Change, cases: list[TestCase], reqset: RequirementSet) -> list[TestCase]:
    touched = set(change.features)
    out = []
    for c in cases:
        feats = set(c.features)
        for rid in c.requirements:
            feats |= set(reqset.reqs[rid].features)
        if feats & touched:
            out.append(c)
    return out


@dataclass
class Job:
    test_id: str
    env: Env
    ready_after: str | None = None  # SiL job of the same test that must finish first
    reason: str = ""
    reps: int = 1  # independent noise seeds on HiL; repetition stops at the first failure


@dataclass
class Outcome:
    strategy: str
    change: str
    buggy: bool
    fidelity: str
    detected: bool
    detected_in: list[str]
    time_to_first_failure_s: float | None
    makespan_s: float
    sil_minutes: float
    hil_minutes: float
    sil_jobs: int
    hil_jobs: int
    escalations: dict[str, str] = field(default_factory=dict)
    timeline: list[dict[str, Any]] = field(default_factory=list)


def _schedule(
    jobs_sil: list[Job], decide_hil: Callable[[str], Job | None], runner: Runner, software: str, static_hil: list[Job]
) -> tuple[list[dict[str, Any]], dict[str, Job]]:
    """Discrete-event list scheduling: SIL.slots parallel SiL executors, HIL_MOCK.slots HiL rigs.

    HiL jobs from `static_hil` are ready at t=0. Jobs produced by `decide_hil` become ready when the
    SiL job of the same test finishes.
    """
    timeline: list[dict[str, Any]] = []
    sil_free = [0.0] * SIL.slots
    hil_ready: list[tuple[float, int, Job]] = []
    seq = 0
    for j in static_hil:
        hil_ready.append((0.0, seq, j))
        seq += 1
    escalated: dict[str, Job] = {}
    for job in jobs_sil:
        heapq.heapify(sil_free)
        start = heapq.heappop(sil_free)
        ex = runner.run(software, job.test_id, SIL)
        end = start + SIL.duration(ex.sim_seconds)
        heapq.heappush(sil_free, end)
        timeline.append(
            {
                "test": job.test_id,
                "env": "sil",
                "start": start,
                "end": end,
                "new_failures": runner.new_failures(software, job.test_id, SIL),
            }
        )
        h = decide_hil(job.test_id)
        if h is not None:
            escalated[job.test_id] = h
            hil_ready.append((end, seq, h))
            seq += 1
    hil_ready.sort(key=lambda x: (x[0], x[1]))
    hil_free = [0.0] * HIL_MOCK.slots
    for ready, _, job in hil_ready:
        for rep in range(job.reps):
            heapq.heapify(hil_free)
            start = max(heapq.heappop(hil_free), ready)
            ex = runner.run(software, job.test_id, HIL_MOCK, rep)
            end = start + HIL_MOCK.duration(ex.sim_seconds)
            heapq.heappush(hil_free, end)
            failures = runner.new_failures(software, job.test_id, HIL_MOCK, rep)
            timeline.append(
                {
                    "test": job.test_id,
                    "env": "hil_mock",
                    "start": start,
                    "end": end,
                    "reason": job.reason + (f" (run {rep + 1}/{job.reps})" if job.reps > 1 else ""),
                    "new_failures": failures,
                }
            )
            if failures:
                break
    return timeline, escalated


def run_strategy(
    strategy: str, change: Change, runner: Runner, margin_drop: float = 0.25, noise_reps: int = 3
) -> Outcome:
    reqset = runner.reqset
    cases = _order(list(runner.cases.values()))
    runner.factories[change.name] = change.factory
    sw = change.name

    if strategy == "A":
        sil = [Job(c.id, SIL) for c in cases]
        timeline, esc = _schedule(sil, lambda _t: None, runner, sw, [Job(c.id, HIL_MOCK, reason="full") for c in cases])
    elif strategy == "B":
        sil = [Job(c.id, SIL) for c in cases]
        static = [Job(c.id, HIL_MOCK, reason="declared hil") for c in cases if _needs_hil(c, reqset)]
        timeline, esc = _schedule(sil, lambda _t: None, runner, sw, static)
    elif strategy in ("C", "D"):
        selected = _impact(change, cases, reqset)
        # D = C + noise awareness: a change to measurement-consuming code escalates its impacted tests and
        # repeats each HiL run on independent noise seeds, because intermittent faults need more than one draw
        noisy = strategy == "D" and change.noise_sensitive
        reps = noise_reps if noisy else 1

        def decide(test_id: str) -> Job | None:
            case = runner.cases[test_id]
            if runner.new_failures(sw, test_id, SIL):
                return None  # already caught at the cheapest level
            hil_reqs = _hil_reqs_touched(case, reqset, change)
            if hil_reqs:
                return Job(test_id, HIL_MOCK, reason=f"touches hil requirement {', '.join(hil_reqs)}", reps=reps)
            res = {r.req_id: r for r in runner.run(sw, test_id, SIL).results}
            ref = {r.req_id: r for r in runner.run("reference", test_id, SIL).results}
            for rid, r in res.items():
                if r.verdict == "INCONCLUSIVE":
                    return Job(test_id, HIL_MOCK, reason=f"thin margin {rid} {r.robustness:+.2f}", reps=reps)
                if reqset.reqs[rid].criticality == "A" and r.robustness < ref[rid].robustness - margin_drop:
                    drop = ref[rid].robustness - r.robustness
                    return Job(test_id, HIL_MOCK, reason=f"margin regression {rid} -{drop:.2f}", reps=reps)
            if noisy:
                return Job(test_id, HIL_MOCK, reason="noise-sensitive change", reps=reps)
            return None

        timeline, esc = _schedule([Job(c.id, SIL) for c in selected], decide, runner, sw, [])
    else:
        raise ValueError(strategy)

    fails = [e for e in timeline if e["new_failures"]]
    ttff = min((e["end"] for e in fails), default=None)
    sil_e = [e for e in timeline if e["env"] == "sil"]
    hil_e = [e for e in timeline if e["env"] == "hil_mock"]
    return Outcome(
        strategy=strategy,
        change=change.name,
        buggy=change.buggy,
        fidelity=change.fidelity,
        detected=bool(fails),
        detected_in=sorted({f"{e['test']}@{e['env']}" for e in fails}),
        time_to_first_failure_s=ttff,
        makespan_s=max((e["end"] for e in timeline), default=0.0),
        sil_minutes=sum(e["end"] - e["start"] for e in sil_e) / 60.0,
        hil_minutes=sum(e["end"] - e["start"] for e in hil_e) / 60.0,
        sil_jobs=len(sil_e),
        hil_jobs=len(hil_e),
        escalations={k: v.reason for k, v in esc.items()},
        timeline=timeline,
    )


def benchmark(runner: Runner, changes: list[Change] | None = None, strategies: str = "ABCD") -> list[Outcome]:
    return [run_strategy(s, ch, runner) for ch in (changes or all_changes()) for s in strategies]


def summarise(outcomes: list[Outcome]) -> list[dict[str, Any]]:
    rows = []
    for s in sorted({o.strategy for o in outcomes}):
        os_ = [o for o in outcomes if o.strategy == s]
        bugs = [o for o in os_ if o.buggy]
        clean = [o for o in os_ if not o.buggy]

        def rate(group: list[Outcome]) -> str:
            return f"{sum(o.detected for o in group)}/{len(group)}"

        detected = [o for o in bugs if o.detected and o.time_to_first_failure_s is not None]
        rows.append(
            {
                "strategy": s,
                "bugs_detected": rate(bugs),
                "sil_observable_detected": rate([o for o in bugs if o.fidelity == "sil"]),
                "hil_only_detected": rate([o for o in bugs if o.fidelity == "hil"]),
                "vehicle_only_detected": rate([o for o in bugs if o.fidelity == "vehicle"]),
                "false_alarms_on_clean": rate(clean),
                "mean_hil_minutes": round(sum(o.hil_minutes for o in os_) / len(os_), 1),
                "mean_makespan_min": round(sum(o.makespan_s for o in os_) / len(os_) / 60.0, 1),
                "median_ttff_s": _median([o.time_to_first_failure_s for o in detected]),
                "clean_change_makespan_min": round(sum(o.makespan_s for o in clean) / max(len(clean), 1) / 60.0, 1),
            }
        )
    return rows


def _median(xs: list[float | None]) -> float | None:
    v = sorted(x for x in xs if x is not None)
    if not v:
        return None
    m = len(v) // 2
    return round(v[m] if len(v) % 2 else (v[m - 1] + v[m]) / 2, 1)


__all__ = ["ENVS", "Change", "Runner", "all_changes", "benchmark", "run_strategy", "summarise"]
