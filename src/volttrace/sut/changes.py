"""Clean software changes: refactors and in-spec calibration updates with no intended defect.

They are the negative controls of the orchestration benchmark. A policy that "detects" one of
these has raised a false alarm. A policy's cost on these is its everyday CI cost.
"""

from __future__ import annotations

import numpy as np

from volttrace.sut.ems import EnergyManager


class C01RefactorBlendFriction(EnergyManager):
    """Refactor of brake blending (explicit regen-force helper), no behaviour change."""

    def blend_friction(self, decel_force_req: float, torque_cmd: float) -> float:
        c = self.cal
        regen_torque = -torque_cmd if torque_cmd < 0.0 else 0.0
        regen_force = regen_torque * c.gear_ratio / (c.gear_efficiency * c.wheel_radius_m)
        return float(np.maximum(decel_force_req - regen_force, 0.0))


class C02GuardRecoveryTweak(EnergyManager):
    """In-spec calibration: undervoltage-guard recovery 0.30 -> 0.25 /s."""

    CAL_OVERRIDE = {"v_guard_recover_per_s": 0.25}


class C03DerateExitTweak(EnergyManager):
    """In-spec calibration: battery derating exit 47 -> 46 degC (wider hysteresis)."""

    CAL_OVERRIDE = {"bat_derate_exit_c": 46.0}


class C04RefactorRegenFade(EnergyManager):
    """Refactor of the regen fade ramp (piecewise form instead of clip), no behaviour change."""

    def regen_fade(self, v: float) -> float:
        lo, hi = self.cal.regen_fade_speed_mps
        if v <= lo:
            return 0.0
        if v >= hi:
            return 1.0
        return (v - lo) / (hi - lo)


class C05ReleaseRateTweak(EnergyManager):
    """In-spec calibration: brake-release regen ramp-out 40 000 -> 35 000 Nm/s."""

    CAL_OVERRIDE = {"torque_rate_release_nm_s": 35000.0}


CLEAN = (C01RefactorBlendFriction, C02GuardRecoveryTweak, C03DerateExitTweak, C04RefactorRegenFade, C05ReleaseRateTweak)
