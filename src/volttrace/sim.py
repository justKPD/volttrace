"""Closed-loop SiL execution: driver -> CAN -> EMS -> plant, with a fixed 10 ms step."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from volttrace.canbus import CanBus
from volttrace.plant import Plant, PlantParams
from volttrace.scenario import Event, Scenario
from volttrace.sut.ems import Calibration, EnergyManager

DT = 0.01

# channel name -> unit; this is also the MDF4 channel list
CHANNELS: dict[str, str] = {
    "pedal": "-",
    "brake": "-",
    "v_kph": "km/h",
    "soc": "-",
    "v_bus": "V",
    "i_bat": "A",
    "p_bat_kw": "kW",
    "p_regen_kw": "kW",
    "t_bat": "degC",
    "t_inv": "degC",
    "torque_cmd": "Nm",
    "torque_act": "Nm",
    "torque_rate": "Nm/s",
    "decel_demand_n": "N",
    "decel_error": "-",
    "friction_n": "N",
    "regen_wheel_n": "N",
    "p_dis_lim_kw": "kW",
    "p_chg_lim_kw": "kW",
    "derate": "-",
    "state": "-",
    "fault_code": "-",
    "age_bms": "s",
    "t_bat_sensed": "degC",
    "soc_sensed": "-",
}


@dataclass
class Trace:
    dt: float
    t: np.ndarray
    signals: dict[str, np.ndarray]
    events: list[Event] = field(default_factory=list)
    sut: str = "baseline"

    def __getitem__(self, name: str) -> np.ndarray:
        if name == "t":
            return self.t
        return self.signals[name]

    def __contains__(self, name: str) -> bool:
        return name == "t" or name in self.signals


def simulate(
    scenario: Scenario,
    sut: Callable[[Calibration], EnergyManager] = EnergyManager,
    params: PlantParams | None = None,
    cal: Calibration | None = None,
    dt: float = DT,
    sut_name: str = "baseline",
) -> Trace:
    params = params or PlantParams.default()
    cal = Calibration(dict((cal or Calibration.default()).raw))
    plant = Plant(params, scenario.initial)
    bus = CanBus(scenario.faults)
    ems = sut(cal)
    driver = scenario.make_driver()
    brake_max = cal.brake_force_max_n

    n_max = int(round(scenario.max_duration_s / dt))
    log = {k: np.empty(n_max) for k in CHANNELS}
    t_axis = np.empty(n_max)
    torque_prev = 0.0
    tail = None  # keep logging 1 s after the driver says it is done
    n = 0
    for k in range(n_max):
        t = k * dt
        pedal, brake = driver(t, plant.v)
        physical = {
            "VCU_Pedal": pedal * 100.0,
            "VCU_Brake": brake * 100.0,
            "BMS_SOC": plant.soc * 100.0,
            "BMS_T_bat": plant.t_bat,
            "BMS_V_bus": plant.v_bus,
            "BMS_I_bat": plant.i_bat,
            "INV_T_inv": plant.t_inv,
            "INV_Speed": plant.omega(),
            "INV_Torque_act": plant.torque,
        }
        bus.tick(t, physical)
        rx = bus.rx()
        age = bus.age(t)
        out = ems.step(rx, age, dt)
        plant.step(out.torque_cmd_nm, out.friction_force_n, dt)

        decel_demand = brake * brake_max
        delivered = plant.f_regen_wheel + plant.f_friction
        row = log
        t_axis[k] = t
        row["pedal"][k] = pedal
        row["brake"][k] = brake
        row["v_kph"][k] = plant.v * 3.6
        row["soc"][k] = plant.soc
        row["v_bus"][k] = plant.v_bus
        row["i_bat"][k] = plant.i_bat
        row["p_bat_kw"][k] = plant.p_bat / 1e3
        row["p_regen_kw"][k] = max(0.0, -plant.p_bat) / 1e3
        row["t_bat"][k] = plant.t_bat
        row["t_inv"][k] = plant.t_inv
        row["torque_cmd"][k] = out.torque_cmd_nm
        row["torque_act"][k] = plant.torque
        row["torque_rate"][k] = (out.torque_cmd_nm - torque_prev) / dt
        row["decel_demand_n"][k] = decel_demand
        # normalised to full braking force; only meaningful while the driver brakes above crawl speed
        row["decel_error"][k] = abs(decel_demand - delivered) / brake_max if brake > 0 and plant.v > 0.5 else 0.0
        row["friction_n"][k] = plant.f_friction
        row["regen_wheel_n"][k] = plant.f_regen_wheel
        row["p_dis_lim_kw"][k] = out.p_dis_lim_w / 1e3
        row["p_chg_lim_kw"][k] = out.p_chg_lim_w / 1e3
        row["derate"][k] = out.derate
        row["state"][k] = int(out.state)
        row["fault_code"][k] = out.fault_code
        row["age_bms"][k] = age["BMS_1"]
        row["t_bat_sensed"][k] = rx.get("BMS_T_bat", np.nan)
        row["soc_sensed"][k] = rx.get("BMS_SOC", np.nan) / 100.0
        torque_prev = out.torque_cmd_nm
        n = k + 1
        if driver.done:
            tail = t + 1.0 if tail is None else tail
            if t >= tail:
                break

    signals = {key: arr[:n].copy() for key, arr in log.items()}
    return Trace(dt, t_axis[:n].copy(), signals, driver.events, sut_name)
