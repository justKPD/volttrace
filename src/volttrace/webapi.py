"""Engine API behind VoltTrace Studio: plain dicts in, plain dicts out.

The same `Engine` runs in two places:
  * in the visitor's browser, inside a Web Worker on Pyodide (the GitHub Pages deployment), and
  * behind `volttrace serve`, a small HTTP server for local use or a hosted backend.

Every call runs the real plant, CAN layer, EMS and STL evaluator. Nothing is precomputed except the
multi-seed benchmark summary, which takes ~15 minutes and is shown as published results.
"""

from __future__ import annotations

import copy
import random
from collections.abc import Callable
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from volttrace import __version__, stl
from volttrace.catalog import case_from_dict
from volttrace.env import ENVS
from volttrace.evaluate import RequirementSet, evaluate, overall
from volttrace.falsify import Template, counterexample_case, falsify
from volttrace.orchestrator import Runner, all_changes, run_strategy
from volttrace.scenario import Scenario
from volttrace.sim import CHANNELS, Trace, simulate
from volttrace.sut.changes import CLEAN
from volttrace.sut.ems import Calibration, EnergyManager
from volttrace.sut.history import HISTORY
from volttrace.sut.mutants import MUTANTS

Progress = Callable[[dict[str, Any]], None]

MAX_POINTS = 500

FINDINGS: list[dict[str, Any]] = [
    {
        "id": "F-001",
        "title": "Undervoltage guard limit-cycles on a cold, aged pack",
        "found_by": "thin STL margin",
        "story": "TC-003 passed with a margin of +0.01: green in a PASS/FAIL report, flagged INCONCLUSIVE here. "
        "The v0.1 guard released the power limit as soon as the voltage recovered, so power and voltage "
        "oscillated at about 1 Hz.",
        "fix": "A stateful guard: fast pull-down, slow recovery.",
        "reproduce": {
            "case": "TC-003",
            "sut": "H01MemorylessVoltageGuard",
            "env": "sil",
            "overrides": {"initial": {"r_aging_factor": 1.8}},  # TC-003 as it stood when F-001 was found
            "focus": ["v_bus", "p_dis_lim_kw"],
            "window": [0, 8],
        },
    },
    {
        "id": "F-002",
        "title": "Regen overvoltage on an aged pack",
        "found_by": "falsifier",
        "story": "Hard braking at ~90 % SOC with internal resistance x1.7 drove the pack past 815 V within 30 ms, before "
        "the reactive guard saw the next BMS frame. No hand-written test caught it.",
        "fix": "Predictive charge state-of-power limit with an online pack-resistance estimate.",
        "reproduce": {
            "case": "FZ-003-CX",
            "sut": "M09SopAssumesNewPack",
            "env": "sil",
            "focus": ["v_bus", "p_regen_kw"],
            "window": [0, 1],
        },
    },
    {
        "id": "F-003",
        "title": "Brake release over-brakes the car (requirements conflict)",
        "found_by": "falsifier, re-run",
        "story": "Easing off the brake during heavy regen: the torque slew limit holds regen while friction cannot go "
        "negative, so the car brakes harder than the driver asks. Two requirements could not both hold.",
        "fix": "Fast regen ramp-out during driver brake release; requirements refined.",
        "reproduce": {
            "case": "FZ-003-CX2",
            "sut": "M10NoBrakeReleaseRampOut",
            "env": "sil",
            "focus": ["decel_error", "torque_cmd"],
            "window": [4.9, 5.3],
        },
    },
    {
        "id": "F-004",
        "title": "Spurious limp-home at power-up",
        "found_by": "first run on the HiL tier",
        "story": "On the rig the first BMS frame arrives a few ms late. The diagnostics treated 'no frame yet' as a lost "
        "BMS, so every test started in limp-home. SiL can never show this.",
        "fix": "A diagnostic enable condition: a 0.5 s start-up grace period.",
        "reproduce": {
            "case": "TC-001",
            "sut": "H04DiagnosticsArmedAtPowerUp",
            "env": "hil_mock",
            "seed": 1,
            "focus": ["fault_code", "p_dis_lim_kw"],
            "window": [0, 3],
        },
    },
    {
        "id": "F-005",
        "title": "Plausibility check trips on one noisy frame",
        "found_by": "first run on the HiL tier",
        "story": "With 0.2 K sensor noise, a single noisy cell-temperature frame set a latched fault.",
        "fix": "Debounce: the jump must persist for 3 consecutive frames.",
        "reproduce": {
            "case": "TC-004",
            "sut": "M12PlausibilityNoDebounce",
            "env": "hil_mock",
            "seed": 1,
            "focus": ["fault_code", "t_bat_sensed"],
            "window": None,
        },
    },
    {
        "id": "F-006",
        "title": "Missing voltage read as 0 V at power-up",
        "found_by": "a 'false alarm' on a clean change",
        "story": "Before the first BMS frame the EMS used 0 V as the pack voltage. The undervoltage guard latched the "
        "discharge limit for ~3 s and the first launch was slow. Found because a harmless change crossed a KPI.",
        "fix": "Stay in INIT until the first valid BMS frame.",
        "reproduce": {
            "case": "TC-001",
            "sut": "M14MissingVoltageAsZero",
            "env": "hil_mock",
            "seed": 1,
            "focus": ["p_dis_lim_kw", "v_kph"],
            "window": [0, 6],
        },
    },
]


# ------------------------------------------------------------------ helpers
def software_versions() -> list[dict[str, Any]]:
    out = [
        {
            "id": "baseline",
            "group": "released",
            "label": f"Released v{__version__}",
            "description": "The current energy-management software with all findings fixed.",
        }
    ]
    for m in MUTANTS.values():
        out.append(
            {
                "id": m.name,
                "group": "seeded bug",
                "label": m.name,
                "description": m.description,
                "fidelity": m.fidelity,
                "features": list(m.features),
            }
        )
    for c in CLEAN:
        out.append(
            {"id": c.__name__, "group": "clean change", "label": c.__name__, "description": (c.__doc__ or "").strip()}
        )
    for name, cls in HISTORY.items():
        out.append({"id": name, "group": "historical build", "label": name, "description": (cls.__doc__ or "").strip()})
    return out


def factory_for(name: str) -> Callable[[Calibration], EnergyManager]:
    if name in ("baseline", "reference"):
        return EnergyManager
    if name in MUTANTS:
        return MUTANTS[name].factory
    if name in HISTORY:
        return HISTORY[name]
    for c in CLEAN:
        if c.__name__ == name:
            return c
    raise KeyError(f"unknown software version {name!r}")


def _predicates(phi: Any) -> list[stl.Pred]:
    if isinstance(phi, stl.Pred):
        return [phi]
    out: list[stl.Pred] = []
    if is_dataclass(phi):
        for f in fields(phi):
            v = getattr(phi, f.name)
            if isinstance(v, stl.Formula):
                out += _predicates(v)
            elif isinstance(v, tuple):
                for x in v:
                    if isinstance(x, stl.Formula):
                        out += _predicates(x)
    return out


PEAK_CHANNELS = ("v_bus", "decel_error", "torque_rate", "p_regen_kw", "fault_code", "t_bat", "t_inv", "p_bat_kw")


def _downsample(t: np.ndarray, ys: dict[str, np.ndarray]) -> tuple[list[float], dict[str, list[float]]]:
    """A uniform grid plus each bucket's min and max of the safety-relevant channels, so a 30 ms overshoot survives."""
    n = len(t)
    if n <= MAX_POINTS:
        idx = np.arange(n)
    else:
        keep = set(np.linspace(0, n - 1, MAX_POINTS).astype(int).tolist())
        edges = np.linspace(0, n, 121).astype(int)
        for name in (c for c in PEAK_CHANNELS if c in ys):
            y = ys[name]
            for a, b in zip(edges[:-1], edges[1:], strict=True):
                seg = y[a:b]
                if b > a and not np.all(np.isnan(seg)):
                    keep.add(a + int(np.nanargmin(seg)))
                    keep.add(a + int(np.nanargmax(seg)))
        idx = np.array(sorted(keep))

    def clean(a: np.ndarray) -> list[float | None]:
        return [None if not np.isfinite(v) else round(float(v), 3) for v in a]

    return clean(t[idx]), {k: clean(v[idx]) for k, v in ys.items()}


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in over.items():
        out[k] = _merge(out.get(k, {}), v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def _clean_num(x: float) -> float | None:
    return None if not np.isfinite(x) else round(float(x), 4)


# ------------------------------------------------------------------ engine
class Engine:
    def __init__(self, bundle: dict[str, Any]):
        self.bundle = bundle
        self.reqset = RequirementSet.from_dict(bundle["requirements"])
        self.cases = {d["id"]: d for d in bundle["catalog"]}
        self.templates = {d["id"]: d for d in bundle["templates"]}
        self.last_trace: Trace | None = None
        self.last_label = ""
        self._hunt: dict[str, Any] | None = None

    # -- metadata ------------------------------------------------------------
    def info(self, _: dict[str, Any] | None = None) -> dict[str, Any]:
        reqs = []
        for r in self.reqset.reqs.values():
            preds = _predicates(r.formula) if r.formula is not None else []
            reqs.append(
                {
                    "id": r.id,
                    "title": r.title,
                    "stl": r.stl_text or f"KPI {r.metric} <= {r.max}",
                    "criticality": r.criticality,
                    "fidelity": r.fidelity,
                    "features": list(r.features),
                    "limits": [{"signal": p.signal, "op": p.op, "value": p.c} for p in preds],
                }
            )
        cases = [
            {
                "id": c["id"],
                "title": c["title"],
                "requirements": c["requirements"],
                "criticality": c.get("criticality", "B"),
                "fidelity": c.get("required_fidelity", "sil"),
                "driver": c["scenario"]["driver"],
                "initial": c["scenario"].get("initial", {}),
                "faults": c["scenario"].get("faults", []),
                "max_duration_s": c["scenario"].get("max_duration_s"),
            }
            for c in self.cases.values()
        ]
        envs = {
            k: {"setup_s": e.setup_s, "wall_per_sim_s": e.wall_per_sim_s, "slots": e.slots} for k, e in ENVS.items()
        }
        return {
            "version": __version__,
            "channels": CHANNELS,
            "requirements": reqs,
            "cases": cases,
            "versions": software_versions(),
            "templates": [
                {"id": t["id"], "title": t["title"], "targets": t["targets"], "params": t["params"]}
                for t in self.templates.values()
            ],
            "envs": envs,
            "findings": FINDINGS,
            "results": self.bundle.get("results", {}),
        }

    # -- test bench ----------------------------------------------------------
    def _scenario(self, spec: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        if "scenario" in spec:
            scn = copy.deepcopy(spec["scenario"])
            reqs = spec.get("requirements") or list(self.reqset.reqs)
        else:
            case = self.cases[spec["case"]]
            scn = _merge(case["scenario"], spec.get("overrides", {}))
            reqs = spec.get("requirements") or list(case["requirements"])
        return scn, reqs

    def run(self, spec: dict[str, Any]) -> dict[str, Any]:
        """Run one test: spec = {case | scenario, overrides?, sut, env, seed, compare_reference?}."""
        scn, req_ids = self._scenario(spec)
        sut = spec.get("sut", "baseline")
        env = ENVS[spec.get("env", "sil")]
        seed = int(spec.get("seed", 0))
        trace = simulate(Scenario.from_dict(scn), factory_for(sut), sut_name=sut, env=env, seed=seed)
        self.last_trace = trace
        self.last_label = f"{sut} on {env.name}" + (f" (seed {seed})" if env.name != "sil" else "")
        results = evaluate(trace, self.reqset, req_ids)
        ref_fail: set[str] = set()
        if spec.get("compare_reference") and sut != "baseline":
            ref = simulate(Scenario.from_dict(scn), EnergyManager, env=env, seed=seed)
            ref_fail = {r.req_id for r in evaluate(ref, self.reqset, req_ids) if r.verdict == "FAIL"}
        verdicts = []
        for r in results:
            req = self.reqset.reqs[r.req_id]
            verdicts.append(
                {
                    "id": r.req_id,
                    "title": req.title,
                    "stl": req.stl_text or f"KPI {req.metric} <= {req.max}",
                    "criticality": req.criticality,
                    "fidelity": req.fidelity,
                    "verdict": r.verdict,
                    "margin": _clean_num(r.robustness),
                    "first_violation_t": r.first_violation_t,
                    "new_vs_released": r.verdict == "FAIL" and r.req_id not in ref_fail,
                    "detail": {k: v for k, v in r.detail.items() if k in ("value", "max", "trigger_fired")},
                }
            )
        t, signals = _downsample(trace.t, trace.signals)
        return {
            "sut": sut,
            "env": env.name,
            "seed": seed,
            "scenario": scn,
            "overall": overall(results),
            "verdicts": verdicts,
            "t": t,
            "signals": signals,
            "events": [{"kind": e.kind, "t_start": e.t_start, "t_end": e.t_end} for e in trace.events],
            "sim_seconds": round(float(trace.t[-1]), 2),
            "rig_seconds": round(env.duration(float(trace.t[-1])), 1),
        }

    def stl_eval(self, spec: dict[str, Any]) -> dict[str, Any]:
        """Evaluate a user-written STL formula on the last test-bench run."""
        if self.last_trace is None:
            raise ValueError("run a test on the Test Bench first")
        phi = stl.parse(spec["formula"])
        unknown = sorted(phi.signals() - set(CHANNELS))
        if unknown:
            raise ValueError(f"unknown signal(s): {', '.join(unknown)}")
        tr = self.last_trace
        scales = {**self.reqset.scales, **spec.get("scales", {})}
        rho = phi.rho(tr.signals, tr.dt, scales)
        idx = stl.first_violation(phi, tr.signals, tr.dt, scales) if rho[0] < 0 else None
        t, ys = _downsample(tr.t, {"rho": rho})
        return {
            "robustness": _clean_num(rho[0]),
            "verdict": "FAIL" if rho[0] < 0 else "PASS",
            "first_violation_t": None if idx is None else float(tr.t[idx]),
            "t": t,
            "rho": ys["rho"],
            "signals": sorted(phi.signals()),
            "trace": self.last_label,
        }

    # -- falsifier -----------------------------------------------------------
    def falsify(self, spec: dict[str, Any], progress: Progress | None = None) -> dict[str, Any]:
        tpl = Template.from_dict(self.templates[spec["template"]])
        sut = spec.get("sut", "baseline")
        best = [float("inf")]

        def on_sample(i: int, s: Any) -> None:
            best[0] = min(best[0], s.robustness)
            if progress is not None:
                progress(
                    {
                        "i": i,
                        "robustness": _clean_num(s.robustness),
                        "best": _clean_num(best[0]),
                        "budget": int(spec.get("budget", 40)),
                    }
                )

        res = falsify(
            tpl,
            self.reqset,
            factory_for(sut),
            sut,
            spec.get("strategy", "random"),
            int(spec.get("budget", 40)),
            seed=int(spec.get("seed", 0)),
            on_sample=on_sample,
        )
        b = res.best
        case = counterexample_case(tpl, b, sut) if res.found else None
        return {
            "found": res.found,
            "sims": len(res.samples),
            "trajectory": [_clean_num(x) for x in res.trajectory()],
            "samples": [_clean_num(s.robustness) for s in res.samples],
            "best": {
                "robustness": _clean_num(b.robustness),
                "per_target": {k: _clean_num(v) for k, v in b.per_target.items()},
                "scenario": b.scenario,
            },
            "regression_test_yaml": yaml.safe_dump(case, sort_keys=False) if case else None,
            "targets": list(tpl.targets),
        }

    # -- CI orchestration ----------------------------------------------------
    def orchestrate(self, spec: dict[str, Any], progress: Progress | None = None) -> dict[str, Any]:
        cases = [case_from_dict(d) for d in self.cases.values()]
        runner = Runner(self.reqset, cases, seed_offset=int(spec.get("seed", 0)))
        if progress is not None:
            runner.on_simulation = lambda n: progress({"simulations": n})
        change = next(c for c in all_changes() if c.name == spec["change"])
        o = run_strategy(spec.get("policy", "C"), change, runner)
        return {
            "change": o.change,
            "policy": o.strategy,
            "buggy": o.buggy,
            "fidelity": o.fidelity,
            "detected": o.detected,
            "detected_in": o.detected_in,
            "time_to_first_failure_s": o.time_to_first_failure_s,
            "makespan_s": o.makespan_s,
            "sil_minutes": o.sil_minutes,
            "hil_minutes": o.hil_minutes,
            "sil_jobs": o.sil_jobs,
            "hil_jobs": o.hil_jobs,
            "escalations": o.escalations,
            "timeline": o.timeline,
            "simulations": len(runner.cache),
            "features": list(change.features),
            "noise_sensitive": change.noise_sensitive,
            "description": change.description,
        }

    # -- bug hunt ------------------------------------------------------------
    def hunt_start(self, spec: dict[str, Any]) -> dict[str, Any]:
        rng = random.Random(spec.get("seed"))
        pool = [c for c in all_changes() if c.fidelity != "vehicle"]
        change = rng.choice(pool)
        self._hunt = {"change": change, "rig_seconds": 0.0, "runs": 0}
        return {
            "started": True,
            "candidates": sorted({f for c in pool for f in c.features}) + ["no bug (clean change)"],
        }

    def hunt_run(self, spec: dict[str, Any]) -> dict[str, Any]:
        if self._hunt is None:
            raise ValueError("start a hunt first")
        spec = {**spec, "sut": self._hunt["change"].name, "compare_reference": True}
        out = self.run(spec)
        self._hunt["rig_seconds"] += out["rig_seconds"]
        self._hunt["runs"] += 1
        out["sut"] = "hidden"
        self.last_label = f"the hidden change on {out['env']}" + (
            f" (seed {out['seed']})" if out["env"] != "sil" else ""
        )
        out["hunt"] = {"rig_seconds": round(self._hunt["rig_seconds"], 1), "runs": self._hunt["runs"]}
        return out

    def hunt_reveal(self, spec: dict[str, Any]) -> dict[str, Any]:
        if self._hunt is None:
            raise ValueError("start a hunt first")
        ch = self._hunt["change"]
        guess = spec.get("guess", "")
        correct = (guess == "no bug (clean change)") if not ch.buggy else guess in ch.features
        out = {
            "change": ch.name,
            "buggy": ch.buggy,
            "description": ch.description,
            "features": list(ch.features),
            "fidelity": ch.fidelity,
            "guess": guess,
            "correct": correct,
            "rig_seconds": round(self._hunt["rig_seconds"], 1),
            "runs": self._hunt["runs"],
        }
        self._hunt = None
        return out


# ------------------------------------------------------------------ bundle
def build_bundle(root: str | Path) -> dict[str, Any]:
    """Everything the Studio needs that is not Python code: requirements, catalogue, templates, published results."""
    import json

    root = Path(root)
    results: dict[str, Any] = {}
    for name, path in (
        ("benchmark", "docs/results/benchmark_summary.json"),
        ("falsifier", "docs/results/falsifier_benchmark.json"),
        ("mutation_matrix", "out/mutation_matrix.json"),
    ):
        p = root / path
        if p.exists():
            d = json.loads(p.read_text())
            if name == "falsifier":
                d = {k: v for k, v in d.items() if k != "runs"}
            results[name] = d
    return {
        "requirements": yaml.safe_load((root / "requirements.yaml").read_text()),
        "catalog": [yaml.safe_load(p.read_text()) for p in sorted((root / "catalog").glob("*.yaml"))],
        "templates": [yaml.safe_load(p.read_text()) for p in sorted((root / "falsify").glob("*.yaml"))],
        "results": results,
    }
