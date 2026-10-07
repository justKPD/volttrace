"""High-voltage energy-management function: the system under test (SUT).

It runs once per 10 ms task, using only CAN-received values. It computes:
  * discharge / charge power limits (SOC map, cold map, thermal derating, voltage guard)
  * predictive charge state-of-power from an online pack-resistance estimate
  * driver torque arbitration under those limits
  * regen / friction brake blending that keeps the total deceleration force
  * a torque-rate limiter
  * diagnostics (CAN timeout, battery-temperature plausibility) and the state machine

Each concern is its own method, so a mutant (a seeded bug) can replace exactly one of them.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from importlib import resources
from typing import Any

import numpy as np
import yaml


class State(IntEnum):
    INIT = 0
    READY = 1
    DRIVE = 2
    DERATE = 3
    FAULT = 4


@dataclass(frozen=True)
class Calibration:
    raw: dict[str, Any]

    @classmethod
    def default(cls) -> Calibration:
        text = resources.files("volttrace.data").joinpath("ems_calibration.yaml").read_text()
        return cls(yaml.safe_load(text))

    def __getattr__(self, key: str) -> Any:
        try:
            return self.raw[key]
        except KeyError as exc:  # pragma: no cover - programming error
            raise AttributeError(key) from exc


@dataclass
class EmsOutput:
    torque_cmd_nm: float
    friction_force_n: float
    p_dis_lim_w: float
    p_chg_lim_w: float
    state: State
    derate: float  # 1.0 = no derating
    fault_code: int


class EnergyManager:
    FAULT_NONE = 0
    FAULT_COMM_BMS = 1
    FAULT_TBAT_PLAUS = 2

    # calibration keys a variant overrides (used by changes and mutants; empty for the release)
    CAL_OVERRIDE: dict[str, Any] = {}

    def __init__(self, cal: Calibration) -> None:
        if self.CAL_OVERRIDE:
            cal = Calibration({**cal.raw, **self.CAL_OVERRIDE})
        self.cal = cal
        self.state = State.INIT
        self.fault_code = self.FAULT_NONE
        self.torque_prev = 0.0
        self.bat_derating = False
        self.inv_derating = False
        self.t_bat_prev: float | None = None
        self.t_bat_prev_t = 0.0
        self.plaus_count = 0
        self.clock = 0.0
        self.g_dis = 1.0
        self.g_chg = 1.0
        # online pack-resistance estimate, as a ratio to the nominal R(T) map
        self.r_ratio = 1.0
        self.r_samples = 0
        self._vi_prev: tuple[float, float] | None = None
        self.brake_prev = 0.0
        self.release_timer = 0.0

    # ---------------------------------------------------------------- limits
    def soc_discharge_kw(self, soc: float) -> float:
        return float(np.interp(soc, self.cal.dis_soc_bp, self.cal.dis_soc_kw))

    def soc_charge_kw(self, soc: float) -> float:
        return float(np.interp(soc, self.cal.chg_soc_bp, self.cal.chg_soc_kw))

    def cold_factors(self, t_bat: float) -> tuple[float, float]:
        c = self.cal
        return (
            float(np.interp(t_bat, c.cold_bp_c, c.cold_factor)),
            float(np.interp(t_bat, c.cold_bp_c, c.cold_chg_factor)),
        )

    @staticmethod
    def _ramp(x: float, start: float, full: float, floor: float) -> float:
        if x <= start:
            return 1.0
        if x >= full:
            return floor
        return 1.0 - (1.0 - floor) * (x - start) / (full - start)

    def derate_factor(self, t_bat: float, t_inv: float) -> float:
        c = self.cal
        # hysteresis: derating latches on at `start`, releases below `exit`
        if t_bat >= c.bat_derate_start_c:
            self.bat_derating = True
        elif t_bat < c.bat_derate_exit_c:
            self.bat_derating = False
        if t_inv >= c.inv_derate_start_c:
            self.inv_derating = True
        elif t_inv < c.inv_derate_exit_c:
            self.inv_derating = False
        f_bat = self._ramp(t_bat, c.bat_derate_start_c, c.bat_derate_full_c, c.derate_floor)
        f_inv = self._ramp(t_inv, c.inv_derate_start_c, c.inv_derate_full_c, c.derate_floor)
        f = 1.0
        if self.bat_derating:
            f = min(f, f_bat)
        if self.inv_derating:
            f = min(f, f_inv)
        return f

    def voltage_guard(self, v_bus: float, p_dis: float, p_chg: float, dt: float) -> tuple[float, float]:
        """Stateful guard: pull the limit down fast while the voltage is outside the window, recover slowly.

        A memoryless proportional guard limit-cycles against the 20 ms BMS frame and the torque
        rate limiter (finding F-001). The asymmetric integrator below does not.
        """
        c = self.cal
        under = c.v_min_guard_v - v_bus
        over = v_bus - c.v_max_guard_v
        self.g_dis = self._guard_integrate(self.g_dis, under, dt)
        self.g_chg = self._guard_integrate(self.g_chg, over, dt)
        return p_dis * self.g_dis, p_chg * self.g_chg

    def _guard_integrate(self, g: float, excess_v: float, dt: float) -> float:
        c = self.cal
        if excess_v > 0.0:
            return max(0.0, g - c.v_guard_down_per_v_s * excess_v * dt)
        return min(1.0, g + c.v_guard_recover_per_s * dt)

    # ------------------------------------------------- state of power (SOP)
    def r_nominal(self, t_bat: float) -> float:
        c = self.cal
        return c.r_nom_25c_ohm * float(np.interp(t_bat, c.r_nom_temp_bp_c, c.r_nom_temp_factor))

    def update_resistance(self, rx: dict[str, float], age: dict[str, float]) -> None:
        """Estimate pack resistance online from consecutive fresh BMS frames: R = -dV/dI.

        Only current steps of at least `r_est_min_di_a` are used, so the 0.1 V / 0.1 A CAN
        resolution stays a small error. The estimate is kept as a ratio to the nominal R(T)
        map, which makes it an ageing (state-of-health) estimate that survives temperature changes.
        """
        c = self.cal
        if age.get("BMS_1", 1.0) != 0.0 or "BMS_I_bat" not in rx:
            return
        v, i = rx["BMS_V_bus"], rx["BMS_I_bat"]
        if self._vi_prev is not None:
            v0, i0 = self._vi_prev
            di = i - i0
            if abs(di) >= c.r_est_min_di_a:
                ratio = -(v - v0) / di / self.r_nominal(rx["BMS_T_bat"])
                if 0.3 < ratio < 5.0:
                    first = self.r_samples == 0
                    self.r_ratio = ratio if first else self.r_ratio + c.r_est_gain * (ratio - self.r_ratio)
                    self.r_samples += 1
        self._vi_prev = (v, i)

    def r_for_sop(self, t_bat: float) -> float:
        """Until the estimate has converged, assume an end-of-life pack (conservative)."""
        c = self.cal
        ratio = self.r_ratio if self.r_samples >= c.r_est_min_samples else c.r_eol_ratio
        return self.r_nominal(t_bat) * max(ratio, 0.8)

    def charge_sop(self, v_bus: float, i_bat: float, t_bat: float) -> float:
        """Predictive charge-power limit that keeps the terminal voltage at or below `v_sop_max_v`.

        With V = OCV - I*R, charging at the voltage ceiling gives P = Vmax * (Vmax - OCV) / R.
        OCV is reconstructed from the measured V and I. This acts *before* the voltage moves,
        unlike the reactive guard (finding F-002).
        """
        c = self.cal
        r = self.r_for_sop(t_bat)
        ocv = v_bus + i_bat * r
        return max(0.0, c.v_sop_max_v * (c.v_sop_max_v - ocv) / r)

    # ----------------------------------------------------------- diagnostics
    def diagnose(self, rx: dict[str, float], age: dict[str, float], dt: float) -> int:
        c = self.cal
        if "BMS_T_bat" not in rx:
            # enable condition (finding F-004): before the first frame, only a missing BMS after the
            # start-up grace period is a fault; frame latency at power-up is not
            return self.FAULT_COMM_BMS if self.clock > c.diag_startup_grace_s else self.FAULT_NONE
        if age.get("BMS_1", 1e9) > c.can_timeout_s:
            return self.FAULT_COMM_BMS
        t_bat = rx["BMS_T_bat"]
        lo, hi = c.t_bat_plaus_range_c
        if not lo <= t_bat <= hi:
            return self.FAULT_TBAT_PLAUS
        if age.get("BMS_1", 1.0) == 0.0:  # judge the rate only on a fresh frame
            if self.t_bat_prev is not None:
                dt_frame = self.clock - self.t_bat_prev_t
                allowed = c.t_bat_plaus_rate_k_s * dt_frame + c.t_bat_plaus_quant_k
                if abs(t_bat - self.t_bat_prev) > allowed:
                    # debounce (finding F-005): a single noisy frame is not a defect; a jump that
                    # persists against the last *accepted* value for N frames is
                    self.plaus_count += 1
                    return self.FAULT_TBAT_PLAUS if self.plaus_count >= c.t_bat_plaus_debounce else self.FAULT_NONE
            self.plaus_count = 0
            self.t_bat_prev, self.t_bat_prev_t = t_bat, self.clock
        return self.FAULT_NONE

    # -------------------------------------------------------------- torque
    def torque_limits(self, omega: float, p_dis_w: float, p_chg_w: float) -> tuple[float, float]:
        c = self.cal
        w = max(omega, c.omega_min_rad_s)
        t_env = min(c.motor_torque_peak_nm, c.motor_power_peak_w / max(omega, 1e-3))
        t_drive = min(t_env, p_dis_w * c.motor_efficiency / w)
        t_regen = min(t_env, p_chg_w / (c.motor_efficiency * w))
        return t_drive, t_regen

    def regen_fade(self, v: float) -> float:
        lo, hi = self.cal.regen_fade_speed_mps
        return float(np.clip((v - lo) / (hi - lo), 0.0, 1.0))

    def rate_limit(self, target: float, dt: float) -> float:
        """Slew-rate limit on the torque command.

        Exception (finding F-003): while the driver is releasing the brake, regen torque may ramp
        *out* at `torque_rate_release_nm_s`. Friction cannot go negative, so a slow regen ramp-out
        would over-brake the car against the driver's request.
        """
        c = self.cal
        step = c.torque_rate_max_nm_s * dt
        up = step
        if self.release_timer > 0.0 and self.torque_prev < 0.0:
            up = c.torque_rate_release_nm_s * dt
        return self.torque_prev + float(np.clip(target - self.torque_prev, -step, up))

    def blend_friction(self, decel_force_req: float, torque_cmd: float) -> float:
        """The friction brake supplies whatever the motor does not regenerate."""
        c = self.cal
        regen_force = max(0.0, -torque_cmd) * c.gear_ratio / (c.gear_efficiency * c.wheel_radius_m)
        return max(0.0, decel_force_req - regen_force)

    # ---------------------------------------------------------------- step
    def step(self, rx: dict[str, float], age: dict[str, float], dt: float) -> EmsOutput:
        c = self.cal
        self.clock += dt
        pedal = rx.get("VCU_Pedal", 0.0) / 100.0
        brake = rx.get("VCU_Brake", 0.0) / 100.0
        omega = rx.get("INV_Speed", 0.0)
        v = omega * c.wheel_radius_m / c.gear_ratio
        soc = rx.get("BMS_SOC", 0.0) / 100.0
        t_bat = rx.get("BMS_T_bat", 25.0)
        t_inv = rx.get("INV_T_inv", 25.0)
        v_bus = rx.get("BMS_V_bus", 0.0)

        fault = self.diagnose(rx, age, dt)
        self.update_resistance(rx, age)
        if brake < self.brake_prev - 1e-6:
            self.release_timer = self.cal.brake_release_window_s
        else:
            self.release_timer = max(0.0, self.release_timer - dt)
        self.brake_prev = brake
        if fault and not self.fault_code:
            self.fault_code = fault  # latched until the next key cycle
        if "BMS_V_bus" not in rx:
            # INIT until the first valid BMS frame (finding F-006): a missing signal is invalid,
            # not 0 V; feeding a default into the guards latched the discharge limit to zero
            self.state = State.FAULT if self.fault_code else State.INIT
            self.torque_prev = 0.0
            p_lim = 0.0
            return EmsOutput(0.0, brake * c.brake_force_max_n, p_lim, p_lim, self.state, 1.0, self.fault_code)
        cold_dis, cold_chg = self.cold_factors(t_bat)
        derate = self.derate_factor(t_bat, t_inv)
        p_dis = self.soc_discharge_kw(soc) * 1e3 * cold_dis * derate
        p_chg = self.soc_charge_kw(soc) * 1e3 * cold_chg * derate
        if "BMS_I_bat" in rx:
            p_chg = min(p_chg, self.charge_sop(v_bus, rx["BMS_I_bat"], t_bat))
        p_dis, p_chg = self.voltage_guard(v_bus, p_dis, p_chg, dt)

        if self.fault_code:
            self.state = State.FAULT
            p_dis = min(p_dis, c.limp_p_dis_kw * 1e3)
            p_chg = 0.0
        elif derate < 1.0:
            self.state = State.DERATE
        elif v > 0.1 or pedal > 0.0:
            self.state = State.DRIVE
        else:
            self.state = State.READY

        t_drive_max, t_regen_max = self.torque_limits(omega, p_dis, p_chg)
        decel_force_req = brake * c.brake_force_max_n
        if brake > 0.0:
            # wheel force -> motor torque; in regen the gearbox losses add to the braking force
            regen_req = decel_force_req * c.wheel_radius_m * c.gear_efficiency / c.gear_ratio
            target = -min(regen_req, t_regen_max * self.regen_fade(v))
        else:
            target = pedal * t_drive_max

        torque = self.rate_limit(target, dt)
        self.torque_prev = torque
        friction = self.blend_friction(decel_force_req, torque)
        return EmsOutput(torque, friction, p_dis, p_chg, self.state, derate, self.fault_code)
