"""Test environments: what each execution tier adds, and what it costs.

SiL       ideal bus timing and ideal sensors (only DBC quantisation). Fast and cheap.
HiL-mock  a *mock* of what a real ECU on a HiL rig adds: per-frame CAN latency jitter, rare
          frame loss, and ADC noise on the measured voltage, current and temperatures. It runs in
          real time and costs bring-up time. It is NOT a HiL rig. It models the class of effects
          SiL abstracts away, so the escalation policy can be studied.

Costs are modelled, not measured, so benchmark numbers do not depend on the machine they run on.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BusEffects:
    latency_max_s: float = 0.0  # per-frame latency, uniform in [0, latency_max_s]
    drop_prob: float = 0.0  # per-frame loss probability
    noise_sigma: dict[str, float] = field(default_factory=dict)  # signal -> Gaussian sigma (physical units)


@dataclass(frozen=True)
class Env:
    name: str
    effects: BusEffects
    setup_s: float  # bring-up per test (flash, rig init)
    wall_per_sim_s: float  # wall-clock seconds per simulated second
    slots: int  # parallel executors available

    def duration(self, sim_seconds: float) -> float:
        return self.setup_s + self.wall_per_sim_s * sim_seconds


SIL = Env("sil", BusEffects(), setup_s=2.0, wall_per_sim_s=0.02, slots=4)

HIL_MOCK = Env(
    "hil_mock",
    BusEffects(
        latency_max_s=0.015,
        drop_prob=0.002,
        noise_sigma={"BMS_V_bus": 0.4, "BMS_I_bat": 2.0, "BMS_T_bat": 0.2, "INV_T_inv": 0.3},
    ),
    setup_s=30.0,
    wall_per_sim_s=1.0,
    slots=1,
)

ENVS = {e.name: e for e in (SIL, HIL_MOCK)}
