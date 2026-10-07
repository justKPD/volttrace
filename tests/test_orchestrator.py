"""Policy-level checks of the SiL-first orchestrator on a small, fast slice of the catalogue."""

from pathlib import Path

import pytest

from volttrace.catalog import load_catalog
from volttrace.evaluate import RequirementSet
from volttrace.orchestrator import Runner, all_changes, run_strategy
from volttrace.sut.changes import CLEAN
from volttrace.sut.impact import features_of, modified_symbols
from volttrace.sut.mutants import M11CanTimeoutTooTight, M13ResistanceEstimatorNoGate

ROOT = Path(__file__).resolve().parents[1]
FAST = {"TC-004", "TC-005", "TC-006", "TC-007"}


@pytest.fixture(scope="module")
def runner():
    reqset = RequirementSet.load(ROOT / "requirements.yaml")
    cases = [c for c in load_catalog(ROOT / "catalog") if c.id in FAST]
    return Runner(reqset, cases)


def change(name):
    return next(c for c in all_changes() if c.name == name)


def test_features_are_derived_from_the_diff_not_labelled():
    assert modified_symbols(M13ResistanceEstimatorNoGate) == ([], ["r_est_min_di_a"])
    assert set(features_of(M11CanTimeoutTooTight)) == {"diagnostics", "can"}
    assert all(features_of(c) for c in CLEAN)


def test_adaptive_catches_sil_bug_without_touching_hil(runner):
    o = run_strategy("C", change("M05DerateRampInverted"), runner)
    assert o.detected and o.detected_in == ["TC-004@sil"]
    assert o.hil_jobs == 0


def test_adaptive_escalates_hil_only_bug_and_catches_it(runner):
    o = run_strategy("C", change("M11CanTimeoutTooTight"), runner)
    assert o.detected and all(d.endswith("@hil_mock") for d in o.detected_in)
    assert any("REQ-FS-014" in reason for reason in o.escalations.values())


def test_clean_change_is_cheap_and_raises_no_alarm(runner):
    c = run_strategy("C", change("C03DerateExitTweak"), runner)
    a = run_strategy("A", change("C03DerateExitTweak"), runner)
    assert not c.detected and not a.detected
    assert c.makespan_s < a.makespan_s / 5


def test_full_strategy_runs_every_test_on_both_tiers(runner):
    o = run_strategy("A", change("C01RefactorBlendFriction"), runner)
    assert o.sil_jobs == o.hil_jobs == len(FAST)
