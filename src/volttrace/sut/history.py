"""Historical builds of the EMS that contained a finding which no seeded mutant re-creates.

They let the Studio replay a finding exactly as it was found. They are not part of the mutation
matrix or the orchestration benchmark, so the published numbers do not change.
"""

from __future__ import annotations

from volttrace.sut.ems import EnergyManager


class H01MemorylessVoltageGuard(EnergyManager):
    """v0.1 undervoltage guard: memoryless and proportional, limit-cycles against the 20 ms BMS frame (F-001)."""

    def voltage_guard(self, v_bus: float, p_dis: float, p_chg: float, dt: float) -> tuple[float, float]:
        c = self.cal
        if v_bus < c.v_min_guard_v:
            p_dis *= max(0.0, 1.0 - 0.02 * (c.v_min_guard_v - v_bus))
        if v_bus > c.v_max_guard_v:
            p_chg *= max(0.0, 1.0 - 0.02 * (v_bus - c.v_max_guard_v))
        return p_dis, p_chg


class H04DiagnosticsArmedAtPowerUp(EnergyManager):
    """v0.2 diagnostics: no start-up enable condition, so a late first BMS frame is a lost BMS (F-004)."""

    CAL_OVERRIDE = {"diag_startup_grace_s": 0.0}


HISTORY = {cls.__name__: cls for cls in (H01MemorylessVoltageGuard, H04DiagnosticsArmedAtPowerUp)}
