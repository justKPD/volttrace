# Findings log

Defects in the system under test (SUT) that the pipeline found on its own.
Each finding has raw evidence next to it, produced by a run, not edited by hand.

| ID | Found by | Status | Summary |
|---|---|---|---|
| F-001 | STL margin (INCONCLUSIVE verdict) on TC-003 | **fixed** in v0.1 | Undervoltage guard limit-cycles at ~1 Hz on a cold, aged pack |
| F-002 | Falsifier FZ-003 (not by any hand-written test) | **fixed** in v0.2 (predictive charge SOP + online resistance estimate) | Regen transient overshoots the 815 V pack limit on an aged pack at ~90 % SOC |
| F-003 | Falsifier FZ-003, re-run on the F-002 fix | **fixed** in v0.2; two requirements refined | Requirements conflict: torque slew limit vs. deceleration accuracy when the driver releases the brake; plus a 3 % gear-efficiency modelling error in brake blending |
| F-004 | First run on the mock-HiL tier | **fixed** in v0.3 | Diagnostics armed before the first CAN frame: spurious limp-home at power-up whenever the first BMS frame is late |
| F-005 | First run on the mock-HiL tier | **fixed** in v0.3 | Temperature plausibility check without debounce: one noisy frame sets a latched fault |
| F-006 | A *clean* calibration change raised a HiL-only "false alarm"; the alarm was real | **fixed** in v0.3 | Missing pack voltage read as 0 V before the first frame; the undervoltage guard latched the discharge limit and the first launch was slow |

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

## F-002: regen overvoltage on an aged pack (fixed)

**Found by.** The falsifier (`volttrace falsify falsify/FZ-003_regen.yaml`). Both strategies reach a counterexample:
random search after 9 simulations, the cross-entropy method after 2 (seed 1). The hand-written test TC-002 uses a new pack and passes.

**Evidence.** [`F-002_regen_overvoltage_aged_pack.txt`](F-002_regen_overvoltage_aged_pack.txt): braking from 200 km/h at
SOC 0.895 with R ×1.72. The charge limit is still 300 kW below 90 % SOC, so the regen torque ramp drives the pack to
**817.4 V within 30 ms**. That is before the next BMS frame lets the 805 V guard react. The guard then holds 805 V.

**Root cause.** The overvoltage protection is *reactive*. The SOC map assumes a healthy pack, and nothing limits charge
power *before* the voltage moves.

**Fix (v0.2).** A predictive charge state-of-power limit, `P_chg,max = V_max · (V_max − OCV) / R̂` with
`V_max = 810 V`, applied *before* the voltage moves:
- `R̂` is estimated online from −ΔV/ΔI on consecutive BMS frames with current steps ≥ 50 A, filtered and stored as
  a ratio to the nominal R(T) map, i.e. an ageing estimate.
- Until 5 samples have arrived, the SOP assumes an **end-of-life** pack (R ×2.0). A cold-booted car on an aged pack
  is therefore safe from the first brake application. A new pack gives up a little regen in the first seconds,
  which is a deliberate safety-over-performance trade-off.
- `OCV` is reconstructed from the measured `V + I·R̂`.

**After the fix.** `FZ-003-CX` passes with margin +0.12 (≈6 V). Re-running the falsifier (4 seeds × 60 simulations)
finds no overvoltage counterexample. The worst margin is +0.08, thin by design: the SOP plans to 810 V against an
815 V limit, so this requirement is a standing HiL escalation candidate.

**Regression protection.** Mutant M09 (SOP assumes a new pack) is killed by `FZ-003-CX`.

## F-003: brake-release over-braking, a requirements conflict (fixed)

**Found by.** The falsifier again, re-run on the F-002 fix. The first campaign had stopped at the first
counterexample (the overvoltage), so this one was hidden behind it. It existed in v0.1 as well.

**Symptom.** The driver releases the brake from 0.85 to 0.42 during heavy regen. The torque-rate limiter
(6000 Nm/s) ramps regen out over ~40 ms, and the friction brake cannot apply negative force. The car over-brakes by
**20 % of full braking force** against the driver's request (REQ-EM-006 robustness −3.0).

**Why it is a requirements problem, not only a code problem.** REQ-DR-009 (torque slew ≤ 6500 Nm/s) and REQ-EM-006
(deceleration within 5 % of demand) cannot both hold during a fast brake release. Something has to give, and the
specification must say what.

**Resolution.**
1. Code: regen may ramp *out* at 40 000 Nm/s for 0.3 s after the driver reduces the brake request
   (`torque_rate_release_nm_s`).
2. REQ-DR-009 refined: it applies outside a driver brake release. Rationale: the slew limit protects the
   drivetrain from *system-induced* torque steps, not from the driver.
3. New REQ-DR-013: a hard drivetrain cap of ±40 500 Nm/s that always applies.
4. REQ-EM-006 refined: a deviation must recover within 20 ms. A pedal *step* needs one 10 ms control cycle, so
   only a persistent deviation is a defect.
5. A second defect surfaced in the same traces: brake blending ignored gearbox efficiency in regen, a steady 3 %
   over-braking. Fixed. Together with the refined window, REQ-EM-006 margins on braking tests rose from ~0.6 to ~1.0.

**Reproduce the defect.** `volttrace run --sut M10NoBrakeReleaseRampOut` fails `FZ-003-CX2` with REQ-EM-006 at −3.5.

**Regression protection.** `FZ-003-CX2`. The original F-003 scenario stopped discriminating the fix once the
efficiency error was corrected: mutant M10, which removes the ramp-out exception, survived it. The scenario was
re-derived by **falsifying against M10** (seed 2, found in 11 simulations, robustness −3.5). M10 is now killed.
That is the falsifier used as a test generator for a specific fault hypothesis.

## F-004 / F-005: two defects SiL could never show (fixed)

Both appeared the first time the clean software ran on the mock-HiL tier (`env.py`: per-frame CAN latency jitter
0–15 ms, 0.2 % frame loss, ADC noise σ = 0.4 V / 2 A / 0.2 K).

- **F-004.** In SiL every frame arrives at exactly t = 0. On the rig the first BMS frame arrives a few ms late, and the
  EMS read "no frame yet" as a lost BMS. Every HiL test began in limp-home (REQ-FS-014, no spurious fault).
  **Fix:** a diagnostic enable condition. Before the first frame, only a BMS still missing after a 0.5 s start-up grace
  period is a fault.
- **F-005.** The cell-temperature rate check tripped on a single noisy frame at t = 6.3 s. **Fix:** a debounce. The jump
  must persist against the last *accepted* value for 3 consecutive fresh frames. A genuine step still trips within 60 ms.

**Regression protection.** Mutants M11 (CAN timeout 25 ms, tuned on clean SiL timing) and M12 (no debounce) are
invisible in SiL and killed on the mock-HiL tier.

## F-006: the "false alarm" that was not (fixed)

**Found by.** The orchestration benchmark. The clean change C02, an in-spec slower undervoltage-guard recovery, failed
the repeatability KPI on HiL: the first of five launches was 6 % slower. A clean change cannot add a defect.
Looking at the reference run showed the first launch was *already* slow on HiL (9.07 s vs 8.86 s). C02 only made a
latent defect cross the 5 % line.

**Root cause.** Before the first BMS frame, the EMS used 0 V as the default pack voltage. The undervoltage guard
saw a 600 V deficit, pulled the discharge limit to zero, and then needed ~3 s to recover. SiL could never show it,
because there the first frame is never late.

**Fix.** The EMS stays in INIT, with no HV power and guards frozen, until the first valid BMS frame. A missing
signal is invalid, not zero. After the fix, all five launches take 8.86–8.87 s on HiL and C02 raises nothing.

**Regression protection.** Mutant M14 re-introduces the 0 V default. New requirement REQ-FS-015 (full discharge
power within 1 s of power-up, declared `hil`) and the KPI kill it on HiL.

**Lesson.** A "false alarm" on a clean change is a lead, not noise to tune away.
