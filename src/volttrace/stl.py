"""Signal Temporal Logic (STL) with quantitative robustness, in discrete time.

A requirement such as

    always(implies(soc >= 0.97, p_regen_kw <= 40))

evaluates to a *robustness* value instead of a boolean. The value is positive
when the requirement holds and negative when it is violated. Its magnitude is the
margin, in the signal's units divided by a per-signal `scale`. That margin is what
the falsifier minimises and what the orchestrator uses to decide whether a SiL
PASS is trustworthy or should be escalated.

Semantics (standard space robustness, Donze & Maler 2010) on a uniformly
sampled finite trace:
  pred  x <= c        ->  (c - x) / scale
  not phi             ->  -rho(phi)
  and / or            ->  min / max
  implies(a, b)       ->  max(-rho(a), rho(b))
  always(phi, lo, hi) ->  min over [t+lo, t+hi]   (window clipped at trace end;
  eventually(...)     ->  max over [t+lo, t+hi]    no hi = until the end)

The parser accepts a small, safe subset of Python syntax via `ast`. Nothing is evaluated.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

Signals = Mapping[str, np.ndarray]


class Formula:
    def rho(self, s: Signals, dt: float, scales: Mapping[str, float]) -> np.ndarray:
        raise NotImplementedError

    def signals(self) -> set[str]:
        raise NotImplementedError


@dataclass(frozen=True)
class Pred(Formula):
    signal: str
    op: str  # '<=', '<', '>=', '>'
    c: float

    def rho(self, s: Signals, dt: float, scales: Mapping[str, float]) -> np.ndarray:
        x = np.asarray(s[self.signal], dtype=float)
        r = (self.c - x) if self.op in ("<=", "<") else (x - self.c)
        return r / scales.get(self.signal, 1.0)

    def signals(self) -> set[str]:
        return {self.signal}

    def __str__(self) -> str:
        return f"{self.signal} {self.op} {self.c:g}"


@dataclass(frozen=True)
class Not(Formula):
    a: Formula

    def rho(self, s: Signals, dt: float, scales: Mapping[str, float]) -> np.ndarray:
        return -self.a.rho(s, dt, scales)

    def signals(self) -> set[str]:
        return self.a.signals()


@dataclass(frozen=True)
class And(Formula):
    parts: tuple[Formula, ...]

    def rho(self, s: Signals, dt: float, scales: Mapping[str, float]) -> np.ndarray:
        return np.minimum.reduce([p.rho(s, dt, scales) for p in self.parts])

    def signals(self) -> set[str]:
        return set().union(*(p.signals() for p in self.parts))


@dataclass(frozen=True)
class Or(Formula):
    parts: tuple[Formula, ...]

    def rho(self, s: Signals, dt: float, scales: Mapping[str, float]) -> np.ndarray:
        return np.maximum.reduce([p.rho(s, dt, scales) for p in self.parts])

    def signals(self) -> set[str]:
        return set().union(*(p.signals() for p in self.parts))


@dataclass(frozen=True)
class Implies(Formula):
    a: Formula
    b: Formula

    def rho(self, s: Signals, dt: float, scales: Mapping[str, float]) -> np.ndarray:
        return np.maximum(-self.a.rho(s, dt, scales), self.b.rho(s, dt, scales))

    def signals(self) -> set[str]:
        return self.a.signals() | self.b.signals()


def _window(r: np.ndarray, lo: int, hi: int | None, reduce_min: bool) -> np.ndarray:
    n = len(r)
    if hi is None:  # unbounded: reverse cumulative min/max, then shift by lo
        acc = (np.minimum if reduce_min else np.maximum).accumulate(r[::-1])[::-1]
        out = np.empty(n)
        out[: max(n - lo, 0)] = acc[lo:]
        out[max(n - lo, 0) :] = acc[-1]
        return out
    width = hi - lo + 1
    # clip at trace end by padding with the last sample (no vacuous truth at the end of a record)
    padded = np.concatenate([r, np.full(hi, r[-1])])
    win = sliding_window_view(padded[lo:], width)[:n]
    return win.min(axis=1) if reduce_min else win.max(axis=1)


@dataclass(frozen=True)
class Always(Formula):
    a: Formula
    lo: float = 0.0
    hi: float | None = None

    def rho(self, s: Signals, dt: float, scales: Mapping[str, float]) -> np.ndarray:
        hi = None if self.hi is None else int(round(self.hi / dt))
        return _window(self.a.rho(s, dt, scales), int(round(self.lo / dt)), hi, True)

    def signals(self) -> set[str]:
        return self.a.signals()


@dataclass(frozen=True)
class Eventually(Formula):
    a: Formula
    lo: float = 0.0
    hi: float | None = None

    def rho(self, s: Signals, dt: float, scales: Mapping[str, float]) -> np.ndarray:
        hi = None if self.hi is None else int(round(self.hi / dt))
        return _window(self.a.rho(s, dt, scales), int(round(self.lo / dt)), hi, False)

    def signals(self) -> set[str]:
        return self.a.signals()


# ------------------------------------------------------------------ parser
_OPS = {ast.LtE: "<=", ast.Lt: "<", ast.GtE: ">=", ast.Gt: ">"}
_FLIP = {"<=": ">=", "<": ">", ">=": "<=", ">": "<"}


class STLSyntaxError(ValueError):
    pass


def _num(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_num(node.operand)
    raise STLSyntaxError(f"expected a number, got {ast.dump(node)}")


def _conv(node: ast.AST) -> Formula:
    if isinstance(node, ast.Compare):
        if len(node.ops) != 1 or type(node.ops[0]) not in _OPS:
            raise STLSyntaxError("only single <, <=, >, >= comparisons are allowed")
        op = _OPS[type(node.ops[0])]
        left, right = node.left, node.comparators[0]
        if isinstance(left, ast.Name):
            return Pred(left.id, op, _num(right))
        if isinstance(right, ast.Name):
            return Pred(right.id, _FLIP[op], _num(left))
        raise STLSyntaxError("a comparison needs a signal name on one side")
    if isinstance(node, ast.BoolOp):
        parts = tuple(_conv(v) for v in node.values)
        return And(parts) if isinstance(node.op, ast.And) else Or(parts)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return Not(_conv(node.operand))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        name = node.func.id
        kw = {k.arg: _num(k.value) for k in node.keywords}
        args = node.args
        if name == "implies" and len(args) == 2:
            return Implies(_conv(args[0]), _conv(args[1]))
        if name in ("always", "eventually") and 1 <= len(args) <= 3:
            lo = _num(args[1]) if len(args) > 1 else kw.get("lo", 0.0)
            hi = _num(args[2]) if len(args) > 2 else kw.get("hi")
            cls = Always if name == "always" else Eventually
            return cls(_conv(args[0]), lo, hi)
        if name == "not_" and len(args) == 1:
            return Not(_conv(args[0]))
    raise STLSyntaxError(f"unsupported STL construct: {ast.unparse(node)}")


def parse(text: str) -> Formula:
    try:
        tree = ast.parse(text.strip(), mode="eval")
    except SyntaxError as exc:
        raise STLSyntaxError(str(exc)) from exc
    return _conv(tree.body)


def robustness(phi: Formula, s: Signals, dt: float, scales: Mapping[str, float] | None = None) -> float:
    """Robustness at t = 0, the verdict-defining number."""
    return float(phi.rho(s, dt, scales or {})[0])


def first_violation(phi: Formula, s: Signals, dt: float, scales: Mapping[str, float] | None = None) -> int | None:
    """Index of the first sample where an `always(...)` body is violated, if any."""
    body = phi.a if isinstance(phi, Always) else phi
    r = body.rho(s, dt, scales or {})
    lo = int(round(phi.lo / dt)) if isinstance(phi, Always) else 0
    idx = np.flatnonzero(r[lo:] < 0)
    return int(idx[0]) + lo if idx.size else None
