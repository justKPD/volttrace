"""Synthetic physical plant: longitudinal vehicle, motor envelope, Rint battery, lumped thermal.

The plant is the "truth" side of the loop. Requirements are checked against these
values, never against what the EMS believes, so a sensor or bus fault that
fools the EMS still shows up as a physical violation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from importlib import resources
from typing import Any

import numpy as np
import yaml

G = 9.81


def _load_yaml(name: str) -> dict[str, Any]:
    return yaml.safe_load(resources.files("volttrace.data").joinpath(name).read_text())


@dataclass(frozen=True)
class PlantParams:
    raw: dict[str, Any]

    @classmethod
    def default(cls) -> PlantParams:
        return cls(_load_yaml("plant_synthetic.yaml"))

    def __getitem__(self, section: str) -> dict[str, Any]:
        return self.raw[section]


@dataclass
class InitialState:
    soc: float = 0.80
    t_bat_c: float = 30.0
    t_inv_c: float = 50.0
    v_kph: float = 0.0
    t_coolant_bat_c: float = 25.0
    t_coolant_inv_c: float = 50.0
    r_aging_factor: float = 1.0  # end-of-life packs: internal resistance grows (1.5-2x)


class Plant:
    def __init__(self, params: PlantParams, init: InitialState) -> None:
        self.p = params
        veh, mot, bat, inv = params["vehicle"], params["motor"], params["battery"], params["inverter"]
        self.m = veh["mass_kg"]
        self.r = veh["wheel_radius_m"]
        self.i = veh["gear_ratio"]
        self.eta_g = veh["gear_efficiency"]
        self.f_aero_k = 0.5 * veh["air_density"] * veh["cd"] * veh["frontal_area_m2"]
        self.f_roll = veh["crr"] * self.m * G
        self.f_tire = veh["tire_mu"] * self.m * G
        self.t_peak = mot["torque_peak_nm"]
        self.p_peak = mot["power_peak_w"]
        self.eta_m = mot["efficiency"]
        self.p_aux = mot["aux_load_w"]
        self.ns = bat["n_series"]
        self.q_as = bat["capacity_ah"] * 3600.0
        self.soc_bp = np.asarray(bat["soc_bp"])
        self.ocv_cell = np.asarray(bat["ocv_cell_v"])
        self.r25 = bat["r_pack_25c_ohm"] * init.r_aging_factor
        self.r_t_bp = np.asarray(bat["r_temp_bp_c"])
        self.r_t_f = np.asarray(bat["r_temp_factor"])
        self.c_bat = bat["thermal_capacity_j_per_k"]
        self.rth_bat = bat["thermal_resistance_k_per_w"]
        self.inv_loss = inv["loss_fraction"]
        self.c_inv = inv["thermal_capacity_j_per_k"]
        self.rth_inv = inv["thermal_resistance_k_per_w"]

        self.v = init.v_kph / 3.6
        self.soc = init.soc
        self.t_bat = init.t_bat_c
        self.t_inv = init.t_inv_c
        self.t_cool_bat = init.t_coolant_bat_c
        self.t_cool_inv = init.t_coolant_inv_c
        # outputs of the last step
        self.torque = 0.0
        self.i_bat = 0.0
        self.p_bat = 0.0
        self.v_bus = self.ocv()
        self.f_regen_wheel = 0.0
        self.f_friction = 0.0

    # --- algebraic helpers -------------------------------------------------
    def omega(self) -> float:
        return self.v * self.i / self.r

    def ocv(self) -> float:
        return self.ns * float(np.interp(self.soc, self.soc_bp, self.ocv_cell))

    def r_int(self) -> float:
        return self.r25 * float(np.interp(self.t_bat, self.r_t_bp, self.r_t_f))

    def torque_envelope(self) -> float:
        return min(self.t_peak, self.p_peak / max(self.omega(), 1e-3))

    # --- integration -------------------------------------------------------
    def step(self, torque_cmd: float, friction_force_cmd: float, dt: float) -> None:
        w = self.omega()
        t_lim = self.torque_envelope()
        torque = max(-t_lim, min(t_lim, torque_cmd))

        # wheel force from motor torque, limited by tyre adhesion
        if torque >= 0.0:
            f_motor = torque * self.i * self.eta_g / self.r
        else:
            f_motor = torque * self.i / (self.eta_g * self.r)
        if abs(f_motor) > self.f_tire:
            scale = self.f_tire / abs(f_motor)
            f_motor *= scale
            torque *= scale
        self.torque = torque

        p_mech = torque * w
        p_elec = p_mech / self.eta_m if p_mech >= 0.0 else p_mech * self.eta_m
        p_elec += self.p_aux

        # Rint battery: P = OCV*I - R*I^2
        ocv, r = self.ocv(), self.r_int()
        p_max = 0.999 * ocv * ocv / (4.0 * r)  # beyond this the pack collapses
        p_elec = min(p_elec, p_max)
        i_bat = (ocv - math.sqrt(ocv * ocv - 4.0 * r * p_elec)) / (2.0 * r)
        self.i_bat = i_bat
        self.p_bat = p_elec
        self.v_bus = ocv - i_bat * r

        self.soc -= i_bat * dt / self.q_as
        self.t_bat += dt * (i_bat * i_bat * r - (self.t_bat - self.t_cool_bat) / self.rth_bat) / self.c_bat
        self.t_inv += (
            dt * (self.inv_loss * abs(p_elec - self.p_aux) - (self.t_inv - self.t_cool_inv) / self.rth_inv) / self.c_inv
        )

        # longitudinal dynamics; friction brakes and resistances never push the car backwards
        f_friction = max(0.0, friction_force_cmd)
        self.f_friction = f_friction
        self.f_regen_wheel = -f_motor if f_motor < 0.0 else 0.0
        f_resist = self.f_aero_k * self.v * self.v + (self.f_roll if self.v > 0.0 else 0.0)
        dv = (f_motor - f_resist - f_friction) / self.m * dt
        self.v = max(0.0, self.v + dv)
