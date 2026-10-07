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

## 6. Roadmap

| Phase | Content | Status |
|---|---|---|
| 1 | Plant, DBC/CAN, EMS + calibration, STL engine, 7+1 catalogue tests, 8 mutants, falsifier, JUnit/MDF4/JSON, CI | **done** |
| 2 | Fix F-002 with predictive SOP charge limit + online R estimation; time-robustness for reaction-time requirements; falsifier vs. random benchmark over many seeds | next |
| 3 | Mock-HiL environment (real-time pacing, bus jitter, ADC noise, limited slots, cost model), margin-based escalation and resource-aware scheduling, baselines A/B/C | planned |
| 4 | Measurement viewer UI (signals + STL envelopes + first violation), deployment | planned |
