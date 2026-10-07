"""Falsification: search a scenario space for the input that minimises STL robustness.

Hand-written test cases check the corners an engineer thought of. The falsifier
treats the closed loop as a black box and searches initial conditions, driver
parameters, pack ageing and faults for the scenario with the *least* margin. If
it reaches negative robustness, it has found a counterexample. That
counterexample is written out as a regular catalogue test, so the finding
becomes a permanent regression test.

Two strategies run on the same simulation budget, so the comparison is fair:
  random  uniform sampling (the baseline any claim must beat)
  cem     cross-entropy method: sample from a Gaussian in the normalised box, refit to the elite
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from volttrace import stl
from volttrace.evaluate import RequirementSet
from volttrace.scenario import Scenario
from volttrace.sim import simulate
from volttrace.sut.ems import Calibration, EnergyManager


@dataclass(frozen=True)
class Param:
    path: str
    lo: float
    hi: float
    integer: bool = False

    def value(self, u: float) -> float | int:
        x = self.lo + float(np.clip(u, 0.0, 1.0)) * (self.hi - self.lo)
        return int(round(x)) if self.integer else round(x, 4)


@dataclass
class Template:
    id: str
    title: str
    targets: tuple[str, ...]
    base: dict[str, Any]
    params: tuple[Param, ...]
    features: tuple[str, ...] = ()

    @classmethod
    def load(cls, path: str | Path) -> Template:
        d = yaml.safe_load(Path(path).read_text())
        params = tuple(
            Param(p["path"], float(p["lo"]), float(p["hi"]), bool(p.get("integer", False))) for p in d["params"]
        )
        return cls(d["id"], d["title"], tuple(d["targets"]), d["scenario"], params, tuple(d.get("features", [])))

    def instantiate(self, u: np.ndarray) -> dict[str, Any]:
        scn = copy.deepcopy(self.base)
        for p, ui in zip(self.params, u, strict=True):
            node: Any = scn
            *head, leaf = p.path.split(".")
            for key in head:  # dotted path; integer parts index into lists ("args.rows.0.brake")
                node = node[int(key)] if isinstance(node, list) else node.setdefault(key, {})
            if isinstance(node, list):
                node[int(leaf)] = p.value(ui)
            else:
                node[leaf] = p.value(ui)
        return scn


@dataclass
class Sample:
    scenario: dict[str, Any]
    robustness: float
    per_target: dict[str, float]


@dataclass
class FalsificationResult:
    template: str
    strategy: str
    sut: str
    budget: int
    samples: list[Sample] = field(default_factory=list)

    @property
    def best(self) -> Sample:
        return min(self.samples, key=lambda s: s.robustness)

    @property
    def found(self) -> bool:
        return self.best.robustness < 0

    @property
    def sims_to_first_counterexample(self) -> int | None:
        for i, s in enumerate(self.samples, 1):
            if s.robustness < 0:
                return i
        return None

    def trajectory(self) -> list[float]:
        return list(np.minimum.accumulate([s.robustness for s in self.samples]))


def _objective(
    tpl: Template, reqset: RequirementSet, sut: Callable[[Calibration], EnergyManager], sut_name: str
) -> Callable[[np.ndarray], Sample]:
    def f(u: np.ndarray) -> Sample:
        scn_dict = tpl.instantiate(u)
        trace = simulate(Scenario.from_dict(scn_dict), sut, sut_name=sut_name)
        per = {}
        for rid in tpl.targets:
            formula = reqset.reqs[rid].formula
            assert formula is not None, f"{rid} is not an STL requirement"
            per[rid] = stl.robustness(formula, trace.signals, trace.dt, reqset.scales)
        return Sample(scn_dict, min(per.values()), per)

    return f


def falsify(
    tpl: Template,
    reqset: RequirementSet,
    sut: Callable[[Calibration], EnergyManager] = EnergyManager,
    sut_name: str = "baseline",
    strategy: str = "cem",
    budget: int = 60,
    population: int = 12,
    elite_frac: float = 0.25,
    seed: int = 0,
    stop_on_counterexample: bool = True,
) -> FalsificationResult:
    rng = np.random.default_rng(seed)
    f = _objective(tpl, reqset, sut, sut_name)
    res = FalsificationResult(tpl.id, strategy, sut_name, budget)
    dim = len(tpl.params)
    mu, sigma = np.full(dim, 0.5), np.full(dim, 0.35)
    while len(res.samples) < budget:
        n = min(population, budget - len(res.samples))
        if strategy == "random":
            batch_u = rng.uniform(0.0, 1.0, size=(n, dim))
        elif strategy == "cem":
            batch_u = np.clip(rng.normal(mu, sigma, size=(n, dim)), 0.0, 1.0)
        else:
            raise ValueError(f"unknown strategy {strategy!r}")
        batch = []
        for u in batch_u:
            s = f(u)
            res.samples.append(s)
            batch.append((s.robustness, u))
            if stop_on_counterexample and s.robustness < 0:
                return res
        if strategy == "cem":
            batch.sort(key=lambda x: x[0])
            k = max(2, int(round(elite_frac * len(batch))))
            elite = np.array([u for _, u in batch[:k]])
            mu = 0.7 * elite.mean(axis=0) + 0.3 * mu
            sigma = np.maximum(0.7 * elite.std(axis=0) + 0.3 * sigma, 0.05)
    return res


def counterexample_case(tpl: Template, sample: Sample, sut_name: str) -> dict[str, Any]:
    """Turn a falsifier counterexample into a catalogue test case (regression test)."""
    return {
        "id": f"{tpl.id}-CX",
        "title": f"Counterexample from falsifier {tpl.id} against {sut_name}: {tpl.title}",
        "requirements": list(tpl.targets),
        "features": list(tpl.features),
        "criticality": "A",
        "required_fidelity": "sil",
        "origin": {"falsifier": tpl.id, "sut": sut_name, "robustness": round(sample.robustness, 4)},
        "scenario": sample.scenario,
    }
