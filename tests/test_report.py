from pathlib import Path

from volttrace.htmlreport import build

ROOT = Path(__file__).resolve().parents[1]


def test_report_builds_self_contained_without_benchmark(tmp_path):
    page = build(tmp_path, ROOT / "requirements.yaml", ROOT / "catalog").read_text()
    assert page.startswith("<!doctype html>")
    assert "F-002" in page and "F-006" in page and "REQ-HV-002" in page
    assert "<script src" not in page and "<link" not in page  # no external assets
    assert "prefers-color-scheme:dark" in page
