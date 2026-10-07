"""Falsifier efficiency: simulations to the first counterexample, random search vs cross-entropy, many seeds.

Each (template, mutant) pair is a fault hypothesis the falsifier has to confirm. A run that exhausts its
budget without a counterexample counts as a miss. Writes docs/results/falsifier_benchmark.{md,json}.

    python scripts/falsifier_benchmark.py --seeds 8 --budget 40
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

from volttrace.evaluate import RequirementSet
from volttrace.falsify import Template, falsify
from volttrace.sut.mutants import sut_factory

PAIRS = [
    ("falsify/FZ-001_undervoltage.yaml", "M07VoltageGuardSign"),
    ("falsify/FZ-001_undervoltage.yaml", "M01NoColdDerating"),
    ("falsify/FZ-003_regen.yaml", "M09SopAssumesNewPack"),
    ("falsify/FZ-003_regen.yaml", "M10NoBrakeReleaseRampOut"),
    ("falsify/FZ-003_regen.yaml", "M02RegenUsesDischargeMap"),
    ("falsify/FZ-002_thermal.yaml", "M05DerateRampInverted"),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=8)
    ap.add_argument("--budget", type=int, default=40)
    args = ap.parse_args()
    reqset = RequirementSet.load("requirements.yaml")
    rows, raw = [], []
    for tpl_path, mutant in PAIRS:
        tpl = Template.load(tpl_path)
        row = {"template": tpl.id, "mutant": mutant}
        for strategy in ("random", "cem"):
            sims = []
            for seed in range(args.seeds):
                res = falsify(tpl, reqset, sut_factory(mutant), mutant, strategy, args.budget, seed=seed)
                sims.append(res.sims_to_first_counterexample)
                raw.append(
                    {
                        "template": tpl.id,
                        "mutant": mutant,
                        "strategy": strategy,
                        "seed": seed,
                        "sims_to_first_counterexample": sims[-1],
                        "best": res.best.robustness,
                    }
                )
            found = [s for s in sims if s is not None]
            row[strategy] = {
                "found": f"{len(found)}/{len(sims)}",
                "median_sims": statistics.median(found) if found else None,
            }
            print(tpl.id, mutant, strategy, row[strategy], flush=True)
        rows.append(row)
    out = Path("docs/results")
    out.mkdir(parents=True, exist_ok=True)
    (out / "falsifier_benchmark.json").write_text(
        json.dumps({"seeds": args.seeds, "budget": args.budget, "summary": rows, "runs": raw}, indent=2)
    )
    md = [
        "# Falsifier efficiency: random search vs cross-entropy method",
        "",
        f"{args.seeds} seeds per cell, budget {args.budget} simulations, stop at the first counterexample. "
        "Median is over the seeds that found one.",
        "",
        "| Template | Mutant (fault hypothesis) | random: found | random: median sims | CEM: found | CEM: median sims |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        md.append(
            f"| {r['template']} | {r['mutant']} | {r['random']['found']} | {r['random']['median_sims']} | "
            f"{r['cem']['found']} | {r['cem']['median_sims']} |"
        )
    (out / "falsifier_benchmark.md").write_text("\n".join(md) + "\n")


if __name__ == "__main__":
    main()
