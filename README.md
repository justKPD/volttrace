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
3. **It decides where each test should run** (SiL or HiL) for each code change. This addresses the published
   SiL-first e-drive question of test time vs. rig time. The adaptive policy cuts rig time per change by ~75 %
   with no false alarms. A noise-aware variant finds at least as many bugs as running everything on the rig, at
   ~30 % less rig time.

## Try it: VoltTrace Studio

**https://justkpd.github.io/volttrace/** is a live app. The real validation engine (plant, CAN bus, ECU software, STL
checks, falsifier, orchestrator) runs **in your browser** through Pyodide, so every click is a fresh simulation, with
no server and nothing precomputed except the 15-minute multi-seed benchmark.

| Page | What you can do |
|---|---|
| **Test Bench** | Pick a test, a software version (released, one of 14 seeded bugs, a clean change, or a historical build) and a tier (SiL or HiL mock). Edit SOC, temperatures, speed and pack ageing. Run it, read each requirement's verdict and margin, inspect signals against the requirement limits with the released software overlaid, and export CSV, JSON or JUnit. |
| **Bug Hunt** | A hidden change is loaded. Run tests to find which feature it breaks, spending as little HiL rig time as you can, then reveal it. |
| **Falsifier** | Search the scenario space live (random or cross-entropy) and watch the margin fall. Open the counterexample on the bench or download it as a regression test. |
| **CI Orchestrator** | Pick a change and a policy (A full, B static, C adaptive, D noise-aware) and run the whole CI cycle live: every SiL job, every HiL escalation and why, as a Gantt chart. |
| **Requirements** | Read the 15 requirements, and write your own STL formula against the last run. |
| **Findings** | Replay each of the six defects in one click, on the build that still has it. |
| **Report** | Your **live session report**: every test, search, CI cycle, hunt and formula you ran, with tiles, plain-language insights (bugs caught and missed, thinnest margins, rig time), requirement coverage and an activity log with "run again". Download it as a self-contained HTML report, JSON or JUnit XML. It survives a reload. |

**Ask VoltTrace** (bottom right) drives all of it in plain words: *"replay F-002"*, *"run TC-003 with M07 on HiL seed 2"*,
*"zoom to violation"*, *"falsify M09 with cem"*, *"ci M05 policy D"*, *"start a hunt"*, *"always(v_bus <= 812)"*,
*"summary"*. The built-in mode works offline. An optional Claude mode (your own API key, kept only in your browser)
plans multi-step requests, using the same actions as tools.

Run it locally with the engine in your own Python process: `pip install -e . && volttrace serve` → http://127.0.0.1:8000.
Every push rebuilds the Studio and boots the **static** site in Chromium, where 67 end-to-end checks covering every page,
export, finding replay, the session report and the assistant must pass (`scripts/studio_e2e.py`) before it deploys.
The pre-built project [evidence report](https://justkpd.github.io/volttrace/report.html) sits next to it.

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

## Where should each test run? (A/B/C/D benchmark)

Every software change is a CI event: 14 seeded bugs (9 SiL-observable, 4 HiL-only, 1 vehicle-only) and 5 clean
changes (refactors, in-spec calibration updates). A change's features, and whether it touches code that consumes raw
measurements, are **derived from its diff** through an ownership file, not hand-labelled. All policies use the same
tests, tiers, ordering and paired noise seeds.

| Policy | Bugs found (noise seed sets 0 / 1 / 2) | HiL-only bugs found | False alarms | HiL rig-min per change | Verdict on a clean change |
|---|---|---|---|---|---|
| **A** full: every test on SiL and HiL | 13 / 12 / 11 of 14 | 4 / 3 / 2 of 4 | 0 / 5 | 13.0 | 12.8 min |
| **B** static: HiL for tests with declared-HiL requirements | 13 / 12 / 11 | 4 / 3 / 2 | 0 / 5 | 12.4 | 12.2 min |
| **C** adaptive: impact selection, SiL first, escalate on touched HiL requirements, thin margins or margin regression | 12 / 12 / 11 | 3 / 3 / 2 | 0 / 5 | **3.1** | **0.7 min** |
| **D** adaptive + noise-aware: C, plus changes to measurement-consuming code escalate and repeat each HiL run on 3 noise seeds | **13 / 12 / 12** | **4 / 3 / 3** | 0 / 5 | 9.1–9.8 | **0.7 min** |

- **C** is the cheap everyday policy. It finds every SiL-observable bug (9/9 on every seed), each first on SiL, at a
  quarter of A's rig time, and it gives a clean change its verdict in under a minute.
- **D** finds at least as many bugs as running everything once (A) on every seed set, and more on one, at ~30 % less
  rig time than A.
  The reason is that intermittent, noise-triggered faults need more than one HiL draw: one HiL run is weak evidence.
- **Honest limits.** No policy reliably catches M13: D catches it on 1 of 3 seed sets, as A does. D also spends rig
  time on changes SiL has already failed (M04, M09), because no policy here uses fail-fast. When a change is broad
  (M14 modifies the top-level `step()`), impact analysis rightly escalates widely, and C reaches its first failure
  later than A (5.8 vs 4.2 min). Full table: [`docs/results/benchmark.md`](docs/results/benchmark.md). CI
  regenerates seed set 0 and fails if a single number changes.

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
volttrace bench --seeds 0 1 2      # A/B/C/D orchestration benchmark (~15 min)
volttrace serve                    # VoltTrace Studio on http://127.0.0.1:8000 (engine in this process)
volttrace build-site               # static Studio + evidence report -> out/site
volttrace falsify falsify/FZ-003_regen.yaml --sut M09SopAssumesNewPack --seed 1   # rediscover F-002
pytest -q                          # 49 tests: STL semantics vs brute force, CAN vs cantools, physics, gates, policies
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
