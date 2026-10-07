"""Requirement evaluation: trace -> per-requirement verdict, margin and evidence.

Verdicts
  PASS          robustness >= band
  INCONCLUSIVE  0 <= robustness < band. It holds, but too thinly to trust a SiL
                abstraction; the orchestrator escalates these.
  FAIL          robustness < 0
  VACUOUS       an `always(implies(trigger, ...))` whose trigger never fired, so the
                test did not exercise the requirement. That is not evidence either way.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from volttrace import stl
from volttrace.sim import Trace

DEFAULT_BAND = 0.1  # one tenth of a scale unit


@dataclass(frozen=True)
class Requirement:
    id: str
    title: str
    criticality: str
    features: tuple[str, ...]
    fidelity: str
    kind: str = "stl"
    stl_text: str = ""
    formula: stl.Formula | None = None
    metric: str = ""
    max: float = 0.0


@dataclass
class RequirementSet:
    reqs: dict[str, Requirement]
    scales: dict[str, float]

    @classmethod
    def load(cls, path: str | Path) -> RequirementSet:
        d = yaml.safe_load(Path(path).read_text())
        reqs: dict[str, Requirement] = {}
        for r in d["requirements"]:
            kind = r.get("kind", "stl")
            reqs[r["id"]] = Requirement(
                id=r["id"],
                title=r["title"],
                criticality=r["criticality"],
                features=tuple(r.get("features", [])),
                fidelity=r.get("fidelity", "sil"),
                kind=kind,
                stl_text=r.get("stl", ""),
                formula=stl.parse(r["stl"]) if kind == "stl" else None,
                metric=r.get("metric", ""),
                max=float(r.get("max", 0.0)),
            )
        return cls(reqs, {k: float(v) for k, v in d.get("scales", {}).items()})


@dataclass
class ReqResult:
    req_id: str
    verdict: str
    robustness: float
    first_violation_t: float | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _launch_spread(trace: Trace) -> tuple[float | None, list[float]]:
    times = [e.t_end - e.t_start for e in trace.events if e.kind == "launch" and e.t_end is not None]
    if len(times) < 2:
        return None, times
    return (max(times) - min(times)) / min(times), times


KPIS = {"launch_time_spread": _launch_spread}


def _conditional(phi: stl.Formula, trace: Trace, scales: dict[str, float]) -> tuple[bool, float] | None:
    """For always(implies(a, b)): did `a` ever fire, and the worst margin of `b` where it did.

    Standard robustness of an implication is also small when the *trigger* merely hovers near its
    threshold. That says nothing about how well the response met its bound. The verdict margin uses
    the response's margin at the instants the trigger was actually active.
    """
    if not (isinstance(phi, stl.Always) and isinstance(phi.a, stl.Implies)):
        return None
    a = phi.a.a.rho(trace.signals, trace.dt, scales)
    fired = a >= 0
    if not fired.any():
        return False, float("inf")
    b = phi.a.b.rho(trace.signals, trace.dt, scales)
    return True, float(b[fired].min())


def evaluate_requirement(
    req: Requirement, trace: Trace, scales: dict[str, float], band: float = DEFAULT_BAND
) -> ReqResult:
    if req.kind == "kpi":
        value, samples = KPIS[req.metric](trace)
        if value is None:
            return ReqResult(req.id, "VACUOUS", float("inf"), detail={"samples": samples})
        rob = (req.max - value) / req.max
        verdict = "FAIL" if rob < 0 else ("INCONCLUSIVE" if rob < band else "PASS")
        return ReqResult(req.id, verdict, rob, detail={"value": value, "max": req.max, "samples": samples})

    assert req.formula is not None
    rho = stl.robustness(req.formula, trace.signals, trace.dt, scales)
    cond = _conditional(req.formula, trace, scales)
    detail: dict[str, Any] = {"stl": req.stl_text, "standard_robustness": rho}
    if rho < 0:
        idx = stl.first_violation(req.formula, trace.signals, trace.dt, scales)
        t_v = float(trace.t[idx]) if idx is not None else None
        return ReqResult(req.id, "FAIL", rho, t_v, detail)
    if cond is not None:
        fired, margin = cond
        detail["trigger_fired"] = fired
        if not fired:
            return ReqResult(req.id, "VACUOUS", rho, None, detail)
        rho = margin
    return ReqResult(req.id, "INCONCLUSIVE" if rho < band else "PASS", rho, None, detail)


def evaluate(
    trace: Trace, reqset: RequirementSet, req_ids: list[str] | None = None, band: float = DEFAULT_BAND
) -> list[ReqResult]:
    ids = req_ids or list(reqset.reqs)
    return [evaluate_requirement(reqset.reqs[i], trace, reqset.scales, band) for i in ids]


def overall(results: list[ReqResult]) -> str:
    verdicts = {r.verdict for r in results}
    for v in ("FAIL", "INCONCLUSIVE", "PASS"):
        if v in verdicts:
            return v
    return "VACUOUS"
