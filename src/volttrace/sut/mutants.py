"""Seeded bugs (mutants) in the EMS: the ground truth for every benchmark.

Each mutant overrides one method or one calibration key of `EnergyManager`. Its features are derived
from what it modifies (`sut/impact.py`, `data/ownership.yaml`), never hand-labelled. Each represents a
plausible engineering mistake: a wrong breakpoint, a unit slip, a missing
compensation path. A test suite or falsifier "kills" a mutant when at least one
requirement fails against it but passes against the clean SUT.

`fidelity` is the design hypothesis of where the bug can show up. `sil`: the SiL loop
exercises it. `hil`: it needs bus timing or sensor noise that SiL abstracts away (mock-HiL).
`vehicle`: it needs effects neither tier models (drivetrain compliance).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from volttrace.sut.ems import Calibration, EnergyManager
from volttrace.sut.impact import features_of


class M01NoColdDerating(EnergyManager):
    """Cold-cell factor computed but never applied to discharge (copy/paste slip)."""

    def cold_factors(self, t_bat: float) -> tuple[float, float]:
        _, chg = super().cold_factors(t_bat)
        return 1.0, chg


class M02RegenUsesDischargeMap(EnergyManager):
    """Charge limit looked up in the discharge SOC table."""

    def soc_charge_kw(self, soc: float) -> float:
        return min(300.0, self.soc_discharge_kw(soc))


class M03NoFrictionCompensation(EnergyManager):
    """Friction brake fills only the *requested* regen, not the rate-limited actual regen."""

    def blend_friction(self, decel_force_req: float, torque_cmd: float) -> float:
        c = self.cal
        regen_req = decel_force_req * c.wheel_radius_m * c.gear_efficiency / c.gear_ratio
        t_regen_max = self.torque_limits(self._omega_last, 0.0, self._p_chg_last)[1]
        planned = min(regen_req, t_regen_max)
        return max(0.0, decel_force_req - planned * c.gear_ratio / (c.gear_efficiency * c.wheel_radius_m))

    def torque_limits(self, omega: float, p_dis_w: float, p_chg_w: float) -> tuple[float, float]:
        self._omega_last, self._p_chg_last = omega, p_chg_w
        return super().torque_limits(omega, p_dis_w, p_chg_w)


class M04CanTimeoutInMs(EnergyManager):
    """Timeout calibrated in ms but compared against seconds: 100 instead of 0.1."""

    CAL_OVERRIDE = {"can_timeout_s": 100.0}


class M05DerateRampInverted(EnergyManager):
    """Thermal ramp direction swapped: derating stays at 1.0 until `full`, then snaps to the floor."""

    @staticmethod
    def _ramp(x: float, start: float, full: float, floor: float) -> float:
        return 1.0 if x < full else floor


class M06RateLimiterPerMs(EnergyManager):
    """Torque-rate limit applied per millisecond count instead of per second."""

    CAL_OVERRIDE = {"torque_rate_max_nm_s": 60000.0}


class M07VoltageGuardSign(EnergyManager):
    """Undervoltage excess computed with the wrong sign, so the guard never engages on a sagging pack."""

    def voltage_guard(self, v_bus: float, p_dis: float, p_chg: float, dt: float) -> tuple[float, float]:
        c = self.cal
        self.g_dis = self._guard_integrate(self.g_dis, v_bus - c.v_min_guard_v - 400.0, dt)
        self.g_chg = self._guard_integrate(self.g_chg, v_bus - c.v_max_guard_v, dt)
        return p_dis * self.g_dis, p_chg * self.g_chg


class M08NoRegenFade(EnergyManager):
    """Regen fade removed: full regen torque is requested down to standstill."""

    def regen_fade(self, v: float) -> float:
        return 1.0 if v > 0.05 else 0.0


class M10NoBrakeReleaseRampOut(EnergyManager):
    """Brake-release exception dropped: regen ramps out at the normal slew rate (re-introduces F-003)."""

    def rate_limit(self, target: float, dt: float) -> float:
        self.release_timer = 0.0
        return super().rate_limit(target, dt)


class M09SopAssumesNewPack(EnergyManager):
    """Charge SOP uses the nominal (new-pack) resistance: no online estimate, no end-of-life default."""

    def r_for_sop(self, t_bat: float) -> float:
        return self.r_nominal(t_bat)


class M11CanTimeoutTooTight(EnergyManager):
    """CAN timeout tuned on clean SiL timing: 25 ms against a 20 ms cycle, no room for bus jitter."""

    CAL_OVERRIDE = {"can_timeout_s": 0.025}


class M12PlausibilityNoDebounce(EnergyManager):
    """Temperature plausibility trips on the first implausible frame (re-introduces F-005)."""

    CAL_OVERRIDE = {"t_bat_plaus_debounce": 1}


class M13ResistanceEstimatorNoGate(EnergyManager):
    """Resistance estimator accepts current steps of 5 A, so ADC noise dominates -dV/dI."""

    CAL_OVERRIDE = {"r_est_min_di_a": 5.0}


class M14MissingVoltageAsZero(EnergyManager):
    """Missing BMS voltage read as 0 V before the first frame, so the guard latches the limit (re-introduces F-006)."""

    def step(self, rx: dict[str, float], age: dict[str, float], dt: float):  # type: ignore[override]
        if "BMS_V_bus" not in rx:
            rx = {**rx, "BMS_V_bus": 0.0}  # the pre-fix default; other BMS signals stay missing
        return super().step(rx, age, dt)


@dataclass(frozen=True)
class MutantInfo:
    name: str
    factory: Callable[[Calibration], EnergyManager]
    description: str
    features: tuple[str, ...]
    fidelity: str = "sil"


def _info(cls: type[EnergyManager], fidelity: str = "sil") -> MutantInfo:
    doc = (cls.__doc__ or "").strip()
    return MutantInfo(cls.__name__, cls, doc, features_of(cls), fidelity)


MUTANTS: dict[str, MutantInfo] = {
    m.name: m
    for m in (
        _info(M01NoColdDerating),
        _info(M02RegenUsesDischargeMap),
        _info(M03NoFrictionCompensation),
        _info(M04CanTimeoutInMs),
        _info(M05DerateRampInverted),
        _info(M06RateLimiterPerMs),
        _info(M07VoltageGuardSign),
        _info(M09SopAssumesNewPack),
        _info(M10NoBrakeReleaseRampOut),
        _info(M11CanTimeoutTooTight, fidelity="hil"),
        _info(M12PlausibilityNoDebounce, fidelity="hil"),
        _info(M13ResistanceEstimatorNoGate, fidelity="hil"),
        _info(M14MissingVoltageAsZero, fidelity="hil"),
        _info(M08NoRegenFade, fidelity="vehicle"),
    )
}


def sut_factory(name: str) -> Callable[[Calibration], EnergyManager]:
    if name in ("baseline", "clean", "EnergyManager"):
        return EnergyManager
    if name not in MUTANTS:
        raise KeyError(f"unknown SUT {name!r}; known: baseline, {', '.join(MUTANTS)}")
    return MUTANTS[name].factory
