"""The Studio's engine API: the same calls the browser and `volttrace serve` make."""

import json
from pathlib import Path

import pytest

from volttrace.webapi import FINDINGS, Engine, build_bundle

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def engine():
    return Engine(json.loads(json.dumps(build_bundle(ROOT))))  # the bundle must survive JSON, as in the browser


def test_info_is_json_and_complete(engine):
    info = json.loads(json.dumps(engine.info()))
    assert {c["id"] for c in info["cases"]} >= {"TC-001", "FZ-003-CX"}
    assert any(v["group"] == "seeded bug" for v in info["versions"])
    assert all(r["limits"] or r["stl"].startswith("KPI") for r in info["requirements"])


@pytest.mark.parametrize("finding", FINDINGS, ids=[f["id"] for f in FINDINGS])
def test_every_finding_replays_and_the_release_is_clean(engine, finding):
    spec = finding["reproduce"]
    bug = engine.run(spec)
    rel = engine.run({**spec, "sut": "baseline"})
    assert bug["overall"] in ("FAIL", "INCONCLUSIVE")
    assert rel["overall"] == "PASS"
    assert len(bug["t"]) <= 2000 and set(bug["signals"]) >= set(spec["focus"])


def test_downsampling_keeps_the_f002_overshoot(engine):
    out = engine.run(FINDINGS[1]["reproduce"])
    assert max(v for v in out["signals"]["v_bus"] if v is not None) > 815


def test_stl_playground_needs_a_run_and_rejects_unknown_signals():
    e = Engine(build_bundle(ROOT))
    with pytest.raises(ValueError):
        e.stl_eval({"formula": "always(v_bus <= 812)"})
    e.run({"case": "TC-002"})
    assert e.stl_eval({"formula": "always(v_bus <= 900)"})["verdict"] == "PASS"
    with pytest.raises(ValueError):
        e.stl_eval({"formula": "always(not_a_signal <= 1)"})


def test_falsifier_reports_progress_and_emits_a_regression_test(engine):
    seen = []
    r = engine.falsify({"template": "FZ-003", "sut": "M09SopAssumesNewPack", "budget": 20, "seed": 1}, seen.append)
    assert r["found"] and r["regression_test_yaml"].startswith("id: FZ-003-CX")
    assert [p["i"] for p in seen] == list(range(1, r["sims"] + 1))


def test_bug_hunt_hides_then_reveals(engine):
    engine.hunt_start({"seed": 3})
    out = engine.hunt_run({"case": "TC-005", "env": "sil"})
    assert out["sut"] == "hidden" and out["hunt"]["runs"] == 1
    reveal = engine.hunt_reveal({"guess": "diagnostics"})
    assert reveal["change"] and reveal["runs"] == 1
    with pytest.raises(ValueError):
        engine.hunt_run({"case": "TC-005"})
