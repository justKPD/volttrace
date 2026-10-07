"""End-to-end checks on the real catalogue: these are the project's own regression gates."""

from pathlib import Path

import pytest

from volttrace.catalog import lint, load_catalog
from volttrace.cli import _gate, _run_case, main, mutation_matrix
from volttrace.evaluate import RequirementSet
from volttrace.falsify import Template, falsify

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def reqset():
    return RequirementSet.load(ROOT / "requirements.yaml")


@pytest.fixture(scope="module")
def cases():
    return load_catalog(ROOT / "catalog")


def test_catalog_is_consistent(reqset, cases):
    assert lint(cases, reqset) == []


def test_clean_sut_has_no_blocking_failure_and_no_thin_margins(reqset, cases):
    records = [_run_case(c, reqset, "baseline", None, False) for c in cases]
    blocking, xfail, _ = _gate(records)
    assert blocking == []
    assert xfail == ["FZ-003-CX (F-002)"]  # open finding, tracked until the SOP fix lands
    for rec in records:
        if "known_issue" not in rec.extra:
            assert {r.verdict for r in rec.results} <= {"PASS"}, rec.case.id


def test_every_sil_observable_mutant_is_killed(reqset, cases):
    m = mutation_matrix(reqset, cases)
    assert m["sil_killable_killed"] == m["sil_killable_total"]


def test_falsifier_rediscovers_f002(reqset):
    tpl = Template.load(ROOT / "falsify" / "FZ-003_regen.yaml")
    res = falsify(tpl, reqset, strategy="random", budget=30, seed=1)
    assert res.found and res.best.per_target["REQ-HV-002"] < 0


def test_cli_run_writes_junit_json_and_readable_mdf(tmp_path):
    asammdf = pytest.importorskip("asammdf")
    rc = main(
        [
            "run",
            "--requirements",
            str(ROOT / "requirements.yaml"),
            "--catalog",
            str(ROOT / "catalog"),
            "--out",
            str(tmp_path),
        ]
    )
    assert rc == 0
    assert (tmp_path / "junit_baseline.xml").exists()
    assert (tmp_path / "results_baseline.json").exists()
    mdf = asammdf.MDF(tmp_path / "mdf" / "TC-001_baseline.mf4")
    v = mdf.get("v_kph")
    assert v.samples.max() == pytest.approx(200, abs=2)
