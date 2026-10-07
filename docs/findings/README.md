# Findings log

Defects in the system under test (SUT) that the pipeline found on its own.
Each finding has raw evidence next to it, produced by a run, not edited by hand.

| ID | Found by | Status | Summary |
|---|---|---|---|
| F-001 | STL margin (INCONCLUSIVE verdict) on TC-003 | **fixed** in v0.1 | Undervoltage guard limit-cycles at ~1 Hz on a cold, aged pack |
| F-002 | Falsifier FZ-003 (not by any hand-written test) | **open**: tracked as known issue on regression test `FZ-003-CX` | Regen transient overshoots the 815 V pack limit on an aged pack at ~90 % SOC |

---

## F-001: undervoltage guard limit cycle (fixed)

**Symptom.** TC-003 (−10 °C, internal resistance ×1.8) passed REQ-HV-001 with a margin of only +0.01 (0.5 V of 560 V).
The verdict was INCONCLUSIVE, not FAIL. A plain PASS/FAIL harness would have reported a green test.

**Evidence.** [`F-001_voltage_guard_limit_cycle_before.txt`](F-001_voltage_guard_limit_cycle_before.txt): the discharge
limit swings between ~45 kW and ~210 kW about once a second, and the terminal voltage dips to 561 V on every cycle.

**Root cause.** The guard was memoryless and proportional (`limit *= 1 − k·(V_guard − V)`). It ran against
a 20 ms BMS frame and a torque-rate limiter, so it released the limit as soon as the voltage recovered, the
power came back, and the voltage sagged again.

**Fix.** A stateful, asymmetric guard factor: fast pull-down while the voltage is outside the window, slow recovery once
inside (`v_guard_down_per_v_s`, `v_guard_recover_per_s` in the calibration). TC-003 margin after the fix: **+0.54**.

**Regression protection.** Mutant M07 (guard sign error) must be killed by TC-003, and it is.

## F-002: regen overvoltage on an aged pack (open)

**Found by.** The falsifier (`volttrace falsify falsify/FZ-003_regen.yaml`). Both strategies reach a counterexample:
random search after 9 simulations, the cross-entropy method after 2 (seed 1). The hand-written test TC-002 uses a new pack and passes.

**Evidence.** [`F-002_regen_overvoltage_aged_pack.txt`](F-002_regen_overvoltage_aged_pack.txt): braking from 200 km/h at
SOC 0.895 with R ×1.72. The charge limit is still 300 kW below 90 % SOC, so the regen torque ramp drives the pack to
**817.4 V within 30 ms**. That is before the next BMS frame lets the 805 V guard react. The guard then holds 805 V.

**Root cause.** The overvoltage protection is *reactive*. The SOC map assumes a healthy pack, and nothing limits charge
power *before* the voltage moves.

**Planned fix.** A predictive state-of-power (SOP) charge limit,
`P_chg,max = V_max · (V_max − OCV) / R̂`, with `R̂` estimated online from ΔV/ΔI on consecutive BMS frames. The
regression test `FZ-003-CX` carries `known_issue: F-002`. The gate expects it to fail until the fix lands and
reports it as soon as it passes.
