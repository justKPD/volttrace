"""High-voltage energy-management function: the system under test (SUT).

It runs once per 10 ms task, using only CAN-received values. It computes:
  * discharge / charge power limits (SOC map, cold map, thermal derating, voltage guard)
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

    def __init__(self, cal: Calibration) -> None:
        self.cal = cal
        self.state = State.INIT
        self.fault_code = self.FAULT_NONE
        self.torque_prev = 0.0
        self.bat_derating = False
        self.inv_derating = False
        self.t_bat_prev: float | None = None
        self.t_bat_prev_t = 0.0
        self.clock = 0.0
        self.g_dis = 1.0
        self.g_chg = 1.0

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

    # ----------------------------------------------------------- diagnostics
    def diagnose(self, rx: dict[str, float], age: dict[str, float], dt: float) -> int:
        c = self.cal
        if age.get("BMS_1", 1e9) > c.can_timeout_s or "BMS_T_bat" not in rx:
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
                    return self.FAULT_TBAT_PLAUS
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
        step = self.cal.torque_rate_max_nm_s * dt
        return self.torque_prev + float(np.clip(target - self.torque_prev, -step, step))

    def blend_friction(self, decel_force_req: float, torque_cmd: float) -> float:
        """The friction brake supplies whatever the motor does not regenerate."""
        c = self.cal
        regen_force = max(0.0, -torque_cmd) * c.gear_ratio / c.wheel_radius_m
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
        if fault and not self.fault_code:
            self.fault_code = fault  # latched until the next key cycle
        cold_dis, cold_chg = self.cold_factors(t_bat)
        derate = self.derate_factor(t_bat, t_inv)
        p_dis = self.soc_discharge_kw(soc) * 1e3 * cold_dis * derate
        p_chg = self.soc_charge_kw(soc) * 1e3 * cold_chg * derate
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
            regen_req = decel_force_req * c.wheel_radius_m / c.gear_ratio
            target = -min(regen_req, t_regen_max * self.regen_fade(v))
        else:
            target = pedal * t_drive_max

        torque = self.rate_limit(target, dt)
        self.torque_prev = torque
        friction = self.blend_friction(decel_force_req, torque)
        return EmsOutput(torque, friction, p_dis, p_chg, self.state, derate, self.fault_code)
