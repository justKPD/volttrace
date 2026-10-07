"""DBC-driven virtual CAN layer between plant and EMS.

Each message is sent on its DBC cycle time. Each signal is quantised and
saturated exactly as its DBC scale, offset and bit length dictate. Faults
(timeout, stuck, offset, latency) are injected here, which is how a
residual-bus simulation in CANoe would do it.

For speed, frames are not bit-packed every step. The quantisation is derived
from the DBC once and stored in `data/dbc_signals.json` (`volttrace dbc-export`),
so the runtime needs no DBC parser (it also runs in the browser).
`tests/test_canbus.py` checks that table, and the quantisation, against cantools'
real DBC parsing and encode/decode.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from functools import cache
from importlib import resources
from typing import Any

import numpy as np

from volttrace.env import BusEffects


@dataclass(frozen=True)
class _SigQ:
    scale: float
    offset: float
    lo: float
    hi: float

    def __call__(self, x: float) -> float:
        raw = round((x - self.offset) / self.scale)
        return min(self.hi, max(self.lo, raw * self.scale + self.offset))


def load_dbc() -> Any:
    """Parse the DBC with cantools (development and tests only; the runtime uses `signal_table`)."""
    import cantools

    path = resources.files("volttrace.data").joinpath("volttrace.dbc")
    return cantools.database.load_string(path.read_text(), database_format="dbc")


def export_signal_table() -> dict[str, Any]:
    """Message cycle times and per-signal quantisation, extracted from the DBC."""
    db = load_dbc()
    return {
        m.name: {
            "cycle_ms": m.cycle_time or 100,
            "signals": {s.name: [s.scale, s.offset, float(s.minimum), float(s.maximum)] for s in m.signals},
        }
        for m in db.messages
    }


@cache
def signal_table() -> dict[str, Any]:
    return json.loads(resources.files("volttrace.data").joinpath("dbc_signals.json").read_text())


@dataclass
class Fault:
    t: float
    kind: str  # timeout | stuck | offset | delay
    message: str | None = None
    signal: str | None = None
    value: float = 0.0
    until: float | None = None

    def active(self, t: float) -> bool:
        return t >= self.t and (self.until is None or t < self.until)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Fault:
        return cls(**d)


@dataclass
class _Msg:
    name: str
    cycle_s: float
    signals: dict[str, _SigQ]
    next_tx: float = 0.0
    in_flight: deque[tuple[float, dict[str, float]]] = field(default_factory=deque)
    last_rx_t: float = 0.0
    last_values: dict[str, float] = field(default_factory=dict)


class CanBus:
    """Receiver-side view: the EMS reads `rx` values and per-message `age`."""

    RX_MESSAGES = ("VCU_1", "BMS_1", "INV_1")

    def __init__(self, faults: list[Fault] | None = None, effects: BusEffects | None = None, seed: int = 0) -> None:
        table = signal_table()
        self.faults = faults or []
        self.effects = effects or BusEffects()
        self.rng = np.random.default_rng(seed)
        self.msgs: dict[str, _Msg] = {}
        for name in self.RX_MESSAGES:
            m = table[name]
            sigs = {sig: _SigQ(*q) for sig, q in m["signals"].items()}
            self.msgs[name] = _Msg(name, m["cycle_ms"] / 1000.0, sigs)
        self._signal_owner = {s: m.name for m in self.msgs.values() for s in m.signals}

    def _apply_signal_faults(self, t: float, values: dict[str, float]) -> dict[str, float]:
        for f in self.faults:
            if f.signal in values and f.active(t):
                if f.kind == "stuck":
                    values[f.signal] = f.value
                elif f.kind == "offset":
                    values[f.signal] += f.value
        return values

    def _msg_fault(self, t: float, name: str, kind: str) -> Fault | None:
        for f in self.faults:
            if f.kind == kind and f.message == name and f.active(t):
                return f
        return None

    def tick(self, t: float, physical: dict[str, float]) -> None:
        """Transmit every message whose cycle is due, then deliver what has arrived."""
        eps = 1e-9
        for m in self.msgs.values():
            if t + eps >= m.next_tx:
                m.next_tx += m.cycle_s
                if self._msg_fault(t, m.name, "timeout"):
                    continue
                fx = self.effects
                if fx.drop_prob and self.rng.random() < fx.drop_prob:
                    continue
                vals = {s: physical[s] for s in m.signals}
                for sig in vals:
                    sigma = fx.noise_sigma.get(sig)
                    if sigma:
                        vals[sig] += float(self.rng.normal(0.0, sigma))
                vals = self._apply_signal_faults(t, vals)
                vals = {s: q(vals[s]) for s, q in m.signals.items()}
                delay = self._msg_fault(t, m.name, "delay")
                arrival = t + (delay.value if delay else 0.0)
                if fx.latency_max_s:
                    arrival += float(self.rng.uniform(0.0, fx.latency_max_s))
                if m.in_flight:  # frames of one CAN ID arrive in order
                    arrival = max(arrival, m.in_flight[-1][0])
                m.in_flight.append((arrival, vals))
            while m.in_flight and m.in_flight[0][0] <= t + eps:
                _, vals = m.in_flight.popleft()
                m.last_values = vals
                m.last_rx_t = t

    def rx(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for m in self.msgs.values():
            out.update(m.last_values)
        return out

    def age(self, t: float) -> dict[str, float]:
        return {name: t - m.last_rx_t for name, m in self.msgs.items()}
