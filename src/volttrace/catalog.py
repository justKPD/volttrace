"""Test catalogue: YAML test cases that trace to requirement IDs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from volttrace.evaluate import RequirementSet
from volttrace.scenario import Scenario
from volttrace.sim import CHANNELS


@dataclass(frozen=True)
class TestCase:
    id: str
    title: str
    requirements: tuple[str, ...]
    features: tuple[str, ...]
    criticality: str
    required_fidelity: str
    scenario: Scenario
    raw: dict[str, Any]


def load_case(path: Path) -> TestCase:
    d = yaml.safe_load(path.read_text())
    return TestCase(
        id=d["id"],
        title=d["title"],
        requirements=tuple(d["requirements"]),
        features=tuple(d.get("features", [])),
        criticality=d.get("criticality", "B"),
        required_fidelity=d.get("required_fidelity", "sil"),
        scenario=Scenario.from_dict(d["scenario"]),
        raw=d,
    )


def load_catalog(directory: str | Path) -> list[TestCase]:
    return [load_case(p) for p in sorted(Path(directory).glob("*.yaml"))]


def lint(cases: list[TestCase], reqset: RequirementSet) -> list[str]:
    """Static checks: unknown requirement IDs, unknown signals, untested requirements, duplicate IDs."""
    problems: list[str] = []
    known = set(CHANNELS)
    for r in reqset.reqs.values():
        if r.formula is not None:
            for sig in sorted(r.formula.signals() - known):
                problems.append(f"{r.id}: STL references unknown channel {sig!r}")
    seen: set[str] = set()
    covered: set[str] = set()
    for c in cases:
        if c.id in seen:
            problems.append(f"duplicate test id {c.id}")
        seen.add(c.id)
        for rid in c.requirements:
            if rid not in reqset.reqs:
                problems.append(f"{c.id}: unknown requirement {rid}")
            covered.add(rid)
    for rid in sorted(set(reqset.reqs) - covered):
        problems.append(f"{rid}: no test case traces to this requirement")
    return problems
