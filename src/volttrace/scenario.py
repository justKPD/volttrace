"""Scenarios: initial conditions, a closed-loop driver model and injected faults.

Drivers react to the *true* vehicle speed. "Launch to 200 km/h, brake, repeat"
is defined by events, not by a fixed time table. That keeps a scenario meaningful
when a bug or a derate changes how fast the car accelerates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from volttrace.canbus import Fault
from volttrace.plant import InitialState


@dataclass
class Event:
    kind: str
    t_start: float
    t_end: float | None = None


class Driver:
    """Returns (pedal 0..1, brake 0..1) for the current true speed in m/s."""

    def __init__(self) -> None:
        self.events: list[Event] = []
        self.done = False

    def __call__(self, t: float, v: float) -> tuple[float, float]:  # pragma: no cover
        raise NotImplementedError


class LaunchRepeat(Driver):
    """n x (full-pedal launch to v_target, brake to standstill, cool-down pause)."""

    def __init__(self, n: int = 5, v_target_kph: float = 200.0, brake: float = 0.6, pause_s: float = 10.0):
        super().__init__()
        self.n, self.v_t, self.brake, self.pause = n, v_target_kph / 3.6, brake, pause_s
        self.k, self.phase, self.t_phase = 0, "launch", 0.0
        self.events.append(Event("launch", 0.0))

    def __call__(self, t: float, v: float) -> tuple[float, float]:
        if self.phase == "launch":
            if v >= self.v_t:
                self.events[-1].t_end = t
                self.phase, self.t_phase = "brake", t
            else:
                return 1.0, 0.0
        if self.phase == "brake":
            if v <= 0.05:
                self.phase, self.t_phase = "pause", t
            else:
                return 0.0, self.brake
        if self.phase == "pause" and t - self.t_phase >= self.pause:
            self.k += 1
            if self.k >= self.n:
                self.done = True
            else:
                self.phase = "launch"
                self.events.append(Event("launch", t))
                return 1.0, 0.0
        return 0.0, 0.0


class TrackSprint(Driver):
    """Synthetic lap: segments of (accelerate to v_hi, brake to v_lo, hold v_lo for hold_s)."""

    def __init__(self, laps: int = 3, segments: list[dict[str, float]] | None = None, brake: float = 0.8):
        super().__init__()
        self.segments = segments or [
            {"v_hi": 250, "v_lo": 90, "hold_s": 4},
            {"v_hi": 200, "v_lo": 120, "hold_s": 3},
            {"v_hi": 230, "v_lo": 70, "hold_s": 5},
        ]
        self.laps, self.brake = laps, brake
        self.lap, self.seg, self.phase, self.t_phase = 0, 0, "accel", 0.0
        self.events.append(Event("lap", 0.0))

    def __call__(self, t: float, v: float) -> tuple[float, float]:
        s = self.segments[self.seg]
        v_hi, v_lo = s["v_hi"] / 3.6, s["v_lo"] / 3.6
        if self.phase == "accel":
            if v >= v_hi:
                self.phase = "brake"
            else:
                return 1.0, 0.0
        if self.phase == "brake":
            if v <= v_lo:
                self.phase, self.t_phase = "hold", t
            else:
                return 0.0, self.brake
        # hold: proportional speed controller, a "corner"
        if t - self.t_phase >= s["hold_s"]:
            self.seg += 1
            self.phase = "accel"
            if self.seg == len(self.segments):
                self.seg = 0
                self.events[-1].t_end = t
                self.lap += 1
                if self.lap >= self.laps:
                    self.done = True
                else:
                    self.events.append(Event("lap", t))
        return min(1.0, max(0.0, 0.15 + 0.3 * (v_lo - v))), 0.0


class Profile(Driver):
    """Piecewise-constant table: [{t, pedal, brake}, ...] (last row holds)."""

    def __init__(self, rows: list[dict[str, float]]):
        super().__init__()
        self.rows = sorted(rows, key=lambda r: r["t"])

    def __call__(self, t: float, v: float) -> tuple[float, float]:
        cur = self.rows[0]
        for r in self.rows:
            if r["t"] <= t:
                cur = r
        return cur.get("pedal", 0.0), cur.get("brake", 0.0)


DRIVERS: dict[str, type[Driver]] = {"launch_repeat": LaunchRepeat, "track_sprint": TrackSprint, "profile": Profile}


@dataclass
class Scenario:
    driver: str
    driver_args: dict[str, Any] = field(default_factory=dict)
    initial: InitialState = field(default_factory=InitialState)
    faults: list[Fault] = field(default_factory=list)
    max_duration_s: float = 120.0

    def make_driver(self) -> Driver:
        return DRIVERS[self.driver](**self.driver_args)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Scenario:
        return cls(
            driver=d["driver"],
            driver_args=dict(d.get("args", {})),
            initial=InitialState(**d.get("initial", {})),
            faults=[Fault.from_dict(f) for f in d.get("faults", [])],
            max_duration_s=float(d.get("max_duration_s", 120.0)),
        )
