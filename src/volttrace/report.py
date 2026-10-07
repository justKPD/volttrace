"""Result artefacts: JSON per run, JUnit XML for CI, MDF4 measurements, Markdown summary."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from volttrace.catalog import TestCase
from volttrace.evaluate import ReqResult, RequirementSet, overall
from volttrace.sim import CHANNELS, Trace


@dataclass
class RunRecord:
    case: TestCase
    sut: str
    env: str
    results: list[ReqResult]
    sim_seconds: float
    wall_seconds: float
    mdf_path: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def verdict(self) -> str:
        return overall(self.results)

    def to_dict(self) -> dict[str, Any]:
        return {
            "test_id": self.case.id,
            "title": self.case.title,
            "sut": self.sut,
            "env": self.env,
            "verdict": self.verdict,
            "sim_seconds": round(self.sim_seconds, 3),
            "wall_seconds": round(self.wall_seconds, 3),
            "mdf": self.mdf_path,
            "requirements": [_clean(r.to_dict()) for r in self.results],
            **self.extra,
        }


def _clean(obj: Any) -> Any:
    if isinstance(obj, float):
        return None if not np.isfinite(obj) else round(obj, 4)
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_clean(v) for v in obj]
    return obj


def write_mdf(trace: Trace, path: Path, comment: str = "") -> Path | None:
    """Write an ASAM MDF4 file (the format CANape / INCA record). Returns None if asammdf is absent."""
    try:
        from asammdf import MDF, Signal
    except ImportError:
        return None
    mdf = MDF(version="4.10")
    sigs = [
        Signal(samples=trace.signals[name].astype(np.float64), timestamps=trace.t, name=name, unit=unit)
        for name, unit in CHANNELS.items()
    ]
    mdf.append(sigs, comment=comment or f"VoltTrace SiL run, SUT={trace.sut}")
    path.parent.mkdir(parents=True, exist_ok=True)
    mdf.save(path, overwrite=True)
    return path


def write_junit(records: list[RunRecord], path: Path, suite_name: str) -> None:
    suite = ET.Element("testsuite", name=suite_name)
    failures = errors = 0
    for rec in records:
        for r in rec.results:
            tc = ET.SubElement(
                suite,
                "testcase",
                classname=f"{suite_name}.{rec.case.id}",
                name=r.req_id,
                time=f"{rec.wall_seconds / max(len(rec.results), 1):.3f}",
            )
            msg = f"robustness={r.robustness:+.3f}"
            if r.first_violation_t is not None:
                msg += f" first_violation_t={r.first_violation_t:.2f}s"
            if r.verdict == "FAIL":
                failures += 1
                ET.SubElement(tc, "failure", message=msg).text = json.dumps(_clean(r.detail))
            elif r.verdict in ("INCONCLUSIVE", "VACUOUS"):
                ET.SubElement(tc, "skipped", message=f"{r.verdict}: {msg}")
            ET.SubElement(tc, "system-out").text = msg
    suite.set("tests", str(len(suite)))
    suite.set("failures", str(failures))
    suite.set("errors", str(errors))
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)


def write_json(records: list[RunRecord], path: Path, meta: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"meta": meta, "runs": [r.to_dict() for r in records]}, indent=2))


_ICON = {"PASS": "PASS", "FAIL": "**FAIL**", "INCONCLUSIVE": "INCONCLUSIVE", "VACUOUS": "vacuous"}


def run_summary_md(records: list[RunRecord], reqset: RequirementSet, title: str) -> str:
    lines = [f"# {title}", "", "| Test | Requirement | Verdict | Margin | First violation |", "|---|---|---|---|---|"]
    for rec in records:
        for r in rec.results:
            fv = f"{r.first_violation_t:.2f} s" if r.first_violation_t is not None else ""
            margin = f"{r.robustness:+.2f}" if np.isfinite(r.robustness) else "n/a"
            lines.append(f"| {rec.case.id} | {r.req_id} | {_ICON[r.verdict]} | {margin} | {fv} |")
    escalate = [
        (rec.case.id, r.req_id)
        for rec in records
        for r in rec.results
        if r.verdict == "INCONCLUSIVE" or (r.verdict == "PASS" and reqset.reqs[r.req_id].fidelity != "sil")
    ]
    lines += ["", "## Escalation candidates (SiL margin thin, or the requirement needs higher fidelity)", ""]
    lines += [f"- {tid} / {rid} (fidelity: {reqset.reqs[rid].fidelity})" for tid, rid in escalate] or ["- none"]
    return "\n".join(lines) + "\n"
