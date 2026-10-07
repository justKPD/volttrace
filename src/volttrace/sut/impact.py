"""Change-impact analysis: derive the features a software change touches from what it modifies."""

from __future__ import annotations

from functools import cache
from importlib import resources
from typing import Any

import yaml

from volttrace.sut.ems import EnergyManager


@cache
def ownership() -> dict[str, Any]:
    return yaml.safe_load(resources.files("volttrace.data").joinpath("ownership.yaml").read_text())


def modified_symbols(cls: type[EnergyManager]) -> tuple[list[str], list[str]]:
    """(overridden EMS methods, overridden calibration keys) of a change class."""
    base = set(dir(EnergyManager))
    methods = sorted(n for n in vars(cls) if n in base and not n.startswith("__") and n != "CAL_OVERRIDE")
    return methods, sorted(getattr(cls, "CAL_OVERRIDE", {}))


def features_of(cls: type[EnergyManager]) -> tuple[str, ...]:
    own = ownership()
    methods, keys = modified_symbols(cls)
    feats: set[str] = set()
    for m in methods:
        if m not in own["methods"]:
            raise KeyError(f"{cls.__name__} modifies {m}, which has no entry in ownership.yaml")
        feats |= set(own["methods"][m])
    for k in keys:
        hits = [v for prefix, v in own["calibration"].items() if k.startswith(prefix)]
        if not hits:
            raise KeyError(f"{cls.__name__} changes calibration {k}, which has no entry in ownership.yaml")
        for v in hits:
            feats |= set(v)
    return tuple(sorted(feats))
