# VoltTrace

**Falsification-driven, margin-aware, SiL-first validation of high-voltage energy management**

[![ci](https://github.com/justKPD/volttrace/actions/workflows/ci.yml/badge.svg)](https://github.com/justKPD/volttrace/actions/workflows/ci.yml)

> An independent portfolio project. Every parameter, requirement and line of ECU code here is **synthetic**.
> It does not represent or reproduce any Mercedes-AMG or Mercedes-Benz system, and it has no affiliation with
> either company. The HiL tier is a **mock**: a model of HiL effects, not a rig.

A test that passes by 0.5 V and a test that passes by 50 V are both green in a PASS/FAIL report. They are not the
same evidence. VoltTrace runs an 800 V performance-BEV energy-management function in a closed loop and judges every
measurement against requirements written in **Signal Temporal Logic**, so each verdict carries a *margin*. It then
does three things a regression suite alone does not:

1. **It searches for failures nobody wrote a test for**, using a falsifier that minimises the margin over the scenario space.
2. **It measures its own test suite** with 14 seeded bugs, including 4 that only a HiL rig can expose.
3. **It decides where each test should run** (SiL or HiL) for each code change. On the published SiL-first
   e-drive testing question of test time vs. rig time, it cuts rig time per change by ~75 % with no false alarms.

**Evidence report:** every finding with its measurements, the benchmark and the kill matrix are in one generated page.
Download it from the `validation-evidence` CI artefact, or from GitHub Pages once Pages is enabled.

## What the pipeline found in its own "clean" code

None of these were planted. Each has a write-up, raw evidence, a fix and a regression test that kills the mutant
re-introducing it: [`docs/findings/`](docs/findings/README.md).

| ID | Found by | Defect |
|---|---|---|
| F-001 | **thin STL margin** (+0.01, verdict INCONCLUSIVE) | undervoltage guard limit-cycles at ~1 Hz on a cold, aged pack |
| F-002 | **falsifier**: no hand-written test caught it | regen on an aged pack overshoots 815 V within 30 ms, before the reactive guard sees the next BMS frame. Fixed with a predictive state-of-power limit and online pack-resistance estimation |
| F-003 | **falsifier**, re-run on the F-002 fix | a **requirements conflict**: torque slew limit vs. deceleration accuracy when the driver releases the brake, plus a 3 % gearbox-efficiency error in brake blending |
| F-004 | **first run on the HiL tier** | diagnostics armed before the first CAN frame: spurious limp-home at power-up |
| F-005 | **first run on the HiL tier** | temperature plausibility check without debounce: one noisy frame latches a fault |
| F-006 | a **"false alarm" on a clean change** that turned out to be real | missing pack voltage read as 0 V at power-up latched the discharge limit for ~3 s |

## Where should each test run? (A/B/C benchmark)

Every software change is a CI event: 14 seeded bugs (9 SiL-observable, 4 HiL-only, 1 vehicle-only) and 5 clean
changes (refactors, in-spec calibration updates). A change's features are **derived from its diff** (the EMS methods
and calibration keys it modifies, mapped through an ownership file), not hand-labelled. All policies use the same
tests, tiers, ordering and paired noise seeds.

| Policy | Bugs found (noise seed sets 0 / 1 / 2) | False alarms | HiL rig-min per change | Verdict on a clean change |
|---|---|---|---|---|
| **A** full: every test on SiL and HiL | 13 / 12 / 11 of 14 | 0 / 5 | 13.0 | 12.8 min |
| **B** static: HiL for tests with declared-HiL requirements | 13 / 12 / 11 of 14 | 0 / 5 | 12.4 | 12.2 min |
| **C** adaptive: impact selection, SiL first, escalate on touched HiL requirements, thin margins or margin regression | 12 / 12 / 11 of 14 | 0 / 5 | **3.1** | **0.7 min** |

- C finds **every SiL-observable bug** (9/9 on every seed), each first on SiL. Some still get a short HiL check when a margin regressed (M02, M03: ~0.7 rig-min).
- C matches A on 2 of 3 seed sets. Its one miss is M13, an **intermittent** noise-triggered bug that even A only
  catches on 1 of 3 seeds. The real lesson: one HiL run is weak evidence against intermittent faults.
- When a change is broad (M14 modifies the top-level `step()`), impact analysis escalates widely and C costs about as
  much as A. It is **slower** to its first failure there (5.8 vs 4.2 min). Full table:
  [`docs/results/benchmark.md`](docs/results/benchmark.md). CI regenerates seed set 0 and fails if a single number changes.

## Is the falsifier any good?

Measured, not assumed: six fault hypotheses (template × seeded bug), 8 seeds each, a budget of 40 simulations,
stopping at the first counterexample ([`docs/results/falsifier_benchmark.md`](docs/results/falsifier_benchmark.md)).

| Template → seeded bug | Random search: found / median sims | Cross-entropy: found / median sims |
|---|---|---|
| FZ-001 undervoltage → M07 guard sign error | 8/8 · 2 | 8/8 · 2.5 |
| FZ-003 regen → M09 SOP assumes a new pack (F-002) | 7/8 · 9 | **8/8** · 19 |
| FZ-003 regen → M10 no brake-release ramp-out (F-003) | **7/8** · 8 | 6/8 · 14 |
| FZ-003 regen → M02 charge map from discharge table | **8/8** · 4.5 | 7/8 · 11 |
| FZ-001 undervoltage → M01 no cold derating | 0/8 | 0/8 |
| FZ-002 thermal → M05 derating ramp inverted | 0/8 | 0/8 |

Two honest conclusions:
- **The cross-entropy method does not beat random search here.** These failure regions are large enough that
  random sampling hits them quickly. CEM is the more reliable of the two on only one hypothesis, and it is slower
  everywhere. Random search stays the baseline any smarter optimiser has to beat.
- **A falsifier only finds what its objective measures.** M01 breaks the cold-power cap, and M05 breaks the
  derating *reaction-time* requirement. Neither is a target of the template that searched for them, and in both
  cases the physical limit the template watches still holds. The hand-written tests kill both. Search complements a
  requirement-traced test suite; it does not replace one.

## The pieces

| | |
|---|---|
| **Plant** | longitudinal dynamics, torque/power envelope, tyre limit, Rint pack (192s, OCV(SOC), R(T), ageing), lumped cell and inverter thermal |
| **CAN** | [`volttrace.dbc`](src/volttrace/data/volttrace.dbc): cycle times and DBC quantisation, checked against `cantools`. Faults: timeout, delay, stuck, offset |
| **SUT** | SOC/cold power maps, thermal derating with hysteresis, stateful voltage guards, **predictive charge SOP with online resistance estimation**, torque arbitration, regen/friction blending, slew limiter with brake-release exception, debounced diagnostics with enable conditions, state machine. Calibration lives in a separate dataset |
| **Requirements** | 14 STL requirements + 1 performance KPI, each with criticality, features and required fidelity: [`requirements.yaml`](requirements.yaml) |
| **Verdicts** | PASS / FAIL / INCONCLUSIVE (margin too thin to trust SiL) / VACUOUS (trigger never fired, so the test proved nothing) |
| **Tiers** | SiL, and a HiL **mock** (per-frame CAN jitter, frame loss, ADC noise, 30 s bring-up, real time, one rig) |
| **Artefacts** | ASAM **MDF4** per run (the measurement format CANape and INCA record), **JUnit XML**, JSON, Markdown, the HTML evidence report |

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

volttrace pipeline                 # static checks -> lint -> SiL run -> gate (CI entry point)
volttrace mutants                  # SiL kill matrix
volttrace bench --seeds 0 1 2      # A/B/C orchestration benchmark (~9 min)
volttrace report                   # HTML evidence report -> out/site/index.html
volttrace falsify falsify/FZ-003_regen.yaml --sut M09SopAssumesNewPack --seed 1   # rediscover F-002
pytest -q                          # 34 tests: STL semantics vs brute force, CAN vs cantools, physics, gates, policies
```

## What this is and is not

- It **is** a working validation loop: formal requirements, quantitative margins, falsification, mutation scoring,
  change-impact analysis, tier escalation, and industry file formats.
- It is **not** HiL experience. The HiL tier is a labelled mock of the class of effects SiL abstracts away.
- It does **not** use CANoe, CANape, INCA or ecu.test. It produces their open formats (DBC, MDF4) and CI-native
  results (JUnit).
- Motivation: the SiL-first e-drive test ecosystem described by Schaak, Sauren et al. (ATZelektronik 5/2025), and its
  stated open question of balancing test time, parallelisation and resource use. VoltTrace explores that question on
  a synthetic system, from first principles.

Design record, alternatives considered and roadmap: [`docs/DESIGN.md`](docs/DESIGN.md).
