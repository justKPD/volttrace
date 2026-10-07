# Design record

## 1. Why this project exists

The target role is high-voltage system development and testing for future performance BEV powertrains. The work:

- prepares, runs and evaluates **measurements** on SiL, HiL and the vehicle
- owns small work packages in **HV energy management**
- uses Vector CANoe/CANape, ETAS INCA and tracetronic ecu.test

Mercedes-AMG and tracetronic have published how their e-drive test ecosystem works: SiL-first, CI-triggered,
ecu.test/test.guide based. The article is Schaak, Sauren, Georges, Fochtmann, *"SiL-First Approach in a Test Ecosystem as Success
Factor for Automotive Software"*, ATZelektronik 5/2025. Its stated open point is the balance between test
execution time, parallelisation and resource use.

VoltTrace is a small, honest exploration of the engineering questions underneath that loop:

1. **Is a SiL PASS trustworthy?** A green SiL result with 0.5 V of margin is not the same evidence as one with
   50 V. Margins come from STL robustness, and a thin margin means *escalate to HiL*.
2. **Did we test the right scenarios?** Hand-written tests cover the corners an engineer imagined. A falsifier
   searches the scenario space for the worst case and turns what it finds into regression tests.
3. **Is the test suite any good?** Seeded bugs (mutants) give ground truth: a suite that cannot kill them is not
   protecting anything.

## 2. Topics considered

| Option | Role fit | Novelty | Depth of evidence it produces | Picked |
|---|---|---|---|---|
| EV CAN dashboard | low | low | none (visualisation only) | no |
| HV battery anomaly detector (ML) | medium | medium | weak (the role is not an ML role) | no |
| Test-plan scheduler only (resource-aware) | high | medium | medium: schedules synthetic tests whose verdicts are made up | later layer |
| **Falsification + STL margins + mutation-scored SiL loop for HV energy management** | **high** | **high** | **strong: real simulations, real verdicts, findings with evidence** | **yes** |

The scheduler idea is not dropped. It becomes Phase 3, where it schedules tests whose verdicts and margins are real.

## 3. How it differs from the earlier E/E validation project

[`ee-validation-intelligence`](https://github.com/justKPD/ee-validation-intelligence) works on **test-management
data**. It decides *which* recorded tests to run first, from risk, evidence state and history, with a policy-gated agent.

VoltTrace works on **signals**. It *executes* the tests in a closed loop, judges the measurements against formal
requirements, and finds new failing scenarios. Together they cover both halves of a validation organisation: the
planning layer and the execution/evaluation layer. No code is shared.

## 4. Architecture

```
            scenario (YAML) ──► driver model ─┐
                                              ▼
 plant (vehicle, motor, Rint pack, thermal) ◄── torque / friction ── EMS (SUT) ◄── CAN rx (DBC-quantised,
          │                                                            ▲            cyclic, faults injected)
          └── physical signals ──► virtual CAN bus ────────────────────┘
          │
          └── trace (25 channels @ 100 Hz) ──► STL evaluator ──► verdict + margin + first violation
                                         │                       │
                                         ├──► MDF4 (.mf4)        └──► JUnit XML / JSON / Markdown
                                         └──► falsifier (CEM / random) ──► counterexample ──► regression test
```

| Layer | File | Real-world counterpart |
|---|---|---|
| Plant | `plant.py`, `data/plant_synthetic.yaml` | plant model in a SiL/HiL rig |
| Bus | `canbus.py`, `data/volttrace.dbc` | residual-bus simulation (CANoe) |
| SUT | `sut/ems.py`, `data/ems_calibration.yaml` | ECU software + calibration dataset (A2L/INCA) |
| Seeded bugs | `sut/mutants.py` | fault seeding / mutation testing |
| Requirements | `requirements.yaml`, `stl.py` | formalised requirements |
| Tests | `catalog/*.yaml` | ecu.test packages |
| Evaluation | `evaluate.py` | measurement evaluation / trace analysis |
| Artefacts | `report.py` | test.guide report, CANape/INCA measurement files |
| Pipeline | `cli.py pipeline`, `.github/workflows/ci.yml` | CI-triggered SiL stage |
| Tiers | `env.py` | SiL vs HiL rig (here a **mock**: bus jitter, frame loss, ADC noise, bring-up cost) |
| Impact analysis | `sut/impact.py`, `data/ownership.yaml` | change → affected functions (CODEOWNERS-style) |
| Orchestration | `orchestrator.py`, `cli.py bench` | test-plan distribution across SiL workers and HiL rigs |
| Evidence report | `htmlreport.py`, `.github/workflows/pages.yml` | test.guide-style report portal |

## 5. Decisions

- **Truth vs. belief.** Requirements are checked on plant (truth) signals. The EMS only ever sees DBC-quantised,
  possibly faulted CAN values. A sensor fault that fools the EMS still fails a physical requirement.
- **Verdict vocabulary.** PASS / FAIL / INCONCLUSIVE (margin < 0.1 scale units) / VACUOUS (an implication's trigger
  never fired, so the test proved nothing about that requirement).
- **Conditional margin.** Standard robustness of `always(implies(a, b))` is also small when *a* only hovers near its
  threshold. The verdict margin is the response's margin at the instants the trigger fired. FAIL still uses the
  standard semantics.
- **Known issues are explicit.** A failing regression test for an open finding carries `known_issue: F-xxx`. The gate
  still blocks on any *new* failure, and it reports the known issue once it starts passing.
- **Fidelity is declared.** A requirement or mutant marked `hil` or `vehicle` is not claimed as covered by SiL.
  Mutant M08 (regen fade removed) is not observable in this SiL abstraction, and the report says so.
- **Synthetic everything.** No parameter is an AMG value. The drive is one equivalent motor, not AMG.EA's three
  axial-flux motors.

## 6. Mock-HiL and orchestration (v0.3)

- **Tiers.** `env.py` defines SiL (ideal bus, DBC quantisation only) and HiL-mock (per-frame CAN latency jitter
  0–15 ms, 0.2 % frame loss, ADC noise, 30 s bring-up, real-time execution, one rig). Costs are modelled, so benchmark
  numbers do not depend on the host. Noise seeds are paired between the reference and the changed software, so a
  difference is the change and not the dice.
- **Changes are CI events.** 14 seeded bugs (9 SiL-observable, 4 HiL-only, 1 vehicle-only) and 5 clean changes
  (refactors and in-spec calibration updates). A change's features are **derived from its diff**: the EMS methods and
  calibration keys it modifies, mapped through `data/ownership.yaml`. No change is hand-labelled, so the adaptive
  policy cannot be tuned through its labels.
- **Policies.** A full (all tests, both tiers), B static (HiL for every test with a `hil` requirement), C adaptive
  (impact selection, SiL first, escalate a test only if the change touches one of its `hil` requirements, a SiL
  margin is thin, or a criticality-A margin regressed against the reference). Same ordering, tiers and seeds for
  all three, so the comparison isolates the policy.
- **Detection** means a requirement FAILs on the change but not on the reference software, in the same tier with the
  same noise seed. A FAIL on a clean change is a false alarm, or, as F-006 showed, a latent defect worth chasing.

## 7. Roadmap

| Phase | Content | Status |
|---|---|---|
| 1 | Plant, DBC/CAN, EMS + calibration, STL engine, catalogue, mutants, falsifier, JUnit/MDF4/JSON, CI | done |
| 2 | F-002 fixed with predictive SOP + online R estimation; F-003 requirements conflict resolved | done |
| 3 | Mock-HiL tier (F-004/F-005/F-006 found and fixed), impact analysis from the diff, A/B/C orchestration benchmark, HTML evidence report | done |
| 4 | Repeated, seed-varied HiL runs for intermittent faults (M12/M13 are caught on only some noise seeds); time-robustness for reaction-time requirements; vehicle-level replay tier for M08-class defects | next |
