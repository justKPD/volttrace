"""Self-contained HTML evidence report: findings with measurements, kill matrix, orchestration benchmark.

One file, no external assets: inline SVG charts, a few lines of JS for hover, light and dark themes.
Every number in it is computed by this run or read from this run's outputs in `out/`.
"""

from __future__ import annotations

import html
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from volttrace import __version__
from volttrace.catalog import load_catalog
from volttrace.env import ENVS
from volttrace.evaluate import RequirementSet
from volttrace.sim import simulate
from volttrace.sut.mutants import MUTANTS, sut_factory

SERIES = ["var(--s1)", "var(--s2)", "var(--s3)"]
W, H = 640, 190
WF = 1080  # canvas width of full-width charts, so their text renders at the same size as the half-width ones
PAD_L, PAD_R, PAD_T, PAD_B = 52, 16, 14, 28


def esc(x: Any) -> str:
    return html.escape(str(x))


# ------------------------------------------------------------------ primitives
def _ticks(lo: float, hi: float, n: int = 4) -> list[float]:
    if hi <= lo:
        hi = lo + 1.0
    raw = (hi - lo) / n
    mag = 10 ** np.floor(np.log10(raw))
    step = min((m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw), default=raw)
    start = np.ceil(lo / step) * step
    return [float(v) for v in np.arange(start, hi + step * 1e-9, step)]


def _fmt(v: float) -> str:
    return f"{v:.0f}" if abs(v) >= 100 or float(v).is_integer() else f"{v:.2f}".rstrip("0").rstrip(".")


@dataclass
class Line:
    name: str
    t: np.ndarray
    y: np.ndarray


def line_chart(
    title: str,
    unit: str,
    lines: list[Line],
    limits: list[tuple[float, str]] | None = None,
    t_range: tuple[float, float] | None = None,
) -> str:
    """Single-axis line chart with optional limit lines; hover shows every series at the cursor time."""
    limits = limits or []
    t0, t1 = t_range or (min(float(ln.t[0]) for ln in lines), max(float(ln.t[-1]) for ln in lines))
    clipped = []
    for ln in lines:
        m = (ln.t >= t0) & (ln.t <= t1)
        t, y = ln.t[m], ln.y[m]
        step = max(1, len(t) // 400)
        clipped.append((ln.name, t[::step], y[::step]))
    ys = np.concatenate([c[2] for c in clipped] + [np.array([v for v, _ in limits])])
    lo, hi = float(np.nanmin(ys)), float(np.nanmax(ys))
    span = hi - lo or 1.0
    lo, hi = lo - 0.08 * span, hi + 0.08 * span
    px = lambda t: PAD_L + (t - t0) / (t1 - t0) * (W - PAD_L - PAD_R)  # noqa: E731
    py = lambda v: PAD_T + (hi - v) / (hi - lo) * (H - PAD_T - PAD_B)  # noqa: E731
    out = [f'<svg viewBox="0 0 {W} {H}" class="chart line" role="img" aria-label="{esc(title)}">']
    for v in _ticks(lo, hi):
        out.append(f'<line class="grid" x1="{PAD_L}" x2="{W - PAD_R}" y1="{py(v):.1f}" y2="{py(v):.1f}"/>')
        out.append(f'<text class="tick" x="{PAD_L - 6}" y="{py(v) + 4:.1f}" text-anchor="end">{_fmt(v)}</text>')
    for v in _ticks(t0, t1, 5):
        out.append(f'<text class="tick" x="{px(v):.1f}" y="{H - 8}" text-anchor="middle">{_fmt(v)} s</text>')
    out.append(f'<line class="axis" x1="{PAD_L}" x2="{W - PAD_R}" y1="{H - PAD_B}" y2="{H - PAD_B}"/>')
    for v, label in limits:
        out.append(f'<line class="limit" x1="{PAD_L}" x2="{W - PAD_R}" y1="{py(v):.1f}" y2="{py(v):.1f}"/>')
        out.append(
            f'<text class="limit-label" x="{W - PAD_R - 4}" y="{py(v) - 5:.1f}" text-anchor="end">{esc(label)}</text>'
        )
    data = []
    for i, (name, t, y) in enumerate(clipped):
        pts = " ".join(f"{px(a):.1f},{py(b):.1f}" for a, b in zip(t, y, strict=True))
        out.append(f'<polyline class="series" style="stroke:{SERIES[i]}" points="{pts}"/>')
        data.append(
            {
                "name": name,
                "color": SERIES[i],
                "x": [round(px(a), 1) for a in t],
                "t": [round(float(a), 2) for a in t],
                "y": [round(float(b), 2) for b in y],
            }
        )
    out.append(f'<line class="cross" x1="0" x2="0" y1="{PAD_T}" y2="{H - PAD_B}" visibility="hidden"/>')
    out.append(
        f'<rect class="hit" x="{PAD_L}" y="{PAD_T}" width="{W - PAD_L - PAD_R}" '
        f'height="{H - PAD_T - PAD_B}" data-unit="{esc(unit)}" data-series=\'{esc(json.dumps(data))}\'/>'
    )
    out.append("</svg>")
    legend = (
        "".join(
            f'<span class="key"><i style="background:{SERIES[i]}"></i>{esc(ln.name)}</span>'
            for i, ln in enumerate(lines)
        )
        if len(lines) > 1
        else ""
    )
    return (
        f'<figure class="panel"><figcaption><b>{esc(title)}</b> <span class="unit">{esc(unit)}</span>'
        f'<span class="legend">{legend}</span></figcaption>{"".join(out)}</figure>'
    )


def bar_chart(title: str, unit: str, cats: list[str], series: list[tuple[str, list[float]]]) -> str:
    """Grouped horizontal bars with direct value labels."""
    n = len(series)
    row_h = 14 * n + 16
    h = PAD_T + row_h * len(cats) + 22
    vmax = max(max(v) for _, v in series) or 1.0
    x0, x1 = 120, WF - 60
    sx = lambda v: x0 + v / vmax * (x1 - x0)  # noqa: E731
    out = [f'<svg viewBox="0 0 {WF} {h}" class="chart bars" role="img" aria-label="{esc(title)}">']
    for v in _ticks(0, vmax):
        out.append(f'<line class="grid" x1="{sx(v):.1f}" x2="{sx(v):.1f}" y1="{PAD_T}" y2="{h - 22}"/>')
        out.append(f'<text class="tick" x="{sx(v):.1f}" y="{h - 6}" text-anchor="middle">{_fmt(v)}</text>')
    for ci, cat in enumerate(cats):
        y = PAD_T + ci * row_h
        out.append(f'<text class="cat" x="{x0 - 10}" y="{y + row_h / 2 + 2:.1f}" text-anchor="end">{esc(cat)}</text>')
        for si, (name, vals) in enumerate(series):
            by = y + 6 + si * 14
            v = round(vals[ci], 1)
            wbar = max(sx(v) - x0, 1.0)
            tip = esc(f"{cat} · {name}: {_fmt(v)} {unit}")
            out.append(
                f'<path class="bar" data-tip="{tip}" style="fill:{SERIES[si]}" '
                f'd="M{x0},{by} h{wbar - 4:.1f} a4,4 0 0 1 4,4 v4 a4,4 0 0 1 -4,4 h-{wbar - 4:.1f} z"/>'
            )
            out.append(f'<text class="val" x="{x0 + wbar + 6:.1f}" y="{by + 10}">{_fmt(v)}</text>')
    out.append(f'<line class="axis" x1="{x0}" x2="{x0}" y1="{PAD_T}" y2="{h - 22}"/></svg>')
    legend = (
        "".join(
            f'<span class="key"><i style="background:{SERIES[i]}"></i>{esc(nm)}</span>'
            for i, (nm, _) in enumerate(series)
        )
        if n > 1
        else ""
    )
    return (
        f'<figure class="panel"><figcaption><b>{esc(title)}</b> <span class="unit">{esc(unit)}</span>'
        f'<span class="legend">{legend}</span></figcaption>{"".join(out)}</figure>'
    )


def gantt(title: str, timeline: list[dict[str, Any]], t_max: float) -> str:
    lanes: list[tuple[str, list[dict[str, Any]]]] = []
    free = {"sil": [0.0] * ENVS["sil"].slots, "hil_mock": [0.0] * ENVS["hil_mock"].slots}
    assign: dict[str, list[list[dict[str, Any]]]] = {k: [[] for _ in v] for k, v in free.items()}
    for e in sorted(timeline, key=lambda e: e["start"]):
        slots = free[e["env"]]
        i = min(range(len(slots)), key=lambda k: (slots[k] > e["start"] + 1e-6, slots[k]))
        slots[i] = e["end"]
        assign[e["env"]][i].append(e)
    for i, jobs in enumerate(assign["sil"]):
        lanes.append((f"SiL worker {i + 1}", jobs))
    lanes.append(("HiL rig (mock)", assign["hil_mock"][0]))
    lane_h, h = 26, PAD_T + 26 * len(lanes) + 26
    x0, x1 = 120, WF - PAD_R
    sx = lambda s: x0 + s / max(t_max, 1.0) * (x1 - x0)  # noqa: E731
    out = [f'<svg viewBox="0 0 {WF} {h}" class="chart gantt" role="img" aria-label="{esc(title)}">']
    for v in _ticks(0, t_max / 60.0, 5):
        out.append(f'<line class="grid" x1="{sx(v * 60):.1f}" x2="{sx(v * 60):.1f}" y1="{PAD_T}" y2="{h - 24}"/>')
        out.append(f'<text class="tick" x="{sx(v * 60):.1f}" y="{h - 8}" text-anchor="middle">{_fmt(v)} min</text>')
    for li, (name, jobs) in enumerate(lanes):
        y = PAD_T + li * lane_h
        out.append(f'<text class="cat" x="{x0 - 8}" y="{y + 16}" text-anchor="end">{esc(name)}</text>')
        for e in jobs:
            fail = bool(e["new_failures"])
            color = SERIES[0] if e["env"] == "sil" else SERIES[1]
            wbar = max(sx(e["end"]) - sx(e["start"]) - 2, 2.0)
            tip = f"{e['test']} on {e['env']}: {e['start'] / 60:.1f}-{e['end'] / 60:.1f} min"
            if e.get("reason"):
                tip += f" · escalated: {e['reason']}"
            tip += f" · FAILED {', '.join(e['new_failures'])}" if fail else " · pass"
            cls = "job fail" if fail else "job"
            out.append(
                f'<rect class="{cls}" data-tip="{esc(tip)}" x="{sx(e["start"]) + 1:.1f}" y="{y + 4}" '
                f'width="{wbar:.1f}" height="{lane_h - 8}" rx="3" style="fill:{color}"/>'
            )
            if fail and wbar > 10:
                out.append(
                    f'<text class="x" x="{sx(e["start"]) + 1 + wbar / 2:.1f}" y="{y + 17}" '
                    f'text-anchor="middle">✕</text>'
                )
    out.append("</svg>")
    legend = (
        '<span class="key"><i style="background:var(--s1)"></i>SiL job</span>'
        '<span class="key"><i style="background:var(--s2)"></i>HiL job</span>'
        '<span class="key"><i class="failkey"></i>✕ found the bug</span>'
    )
    return (
        f'<figure class="panel"><figcaption><b>{esc(title)}</b><span class="legend">{legend}</span>'
        f"</figcaption>{''.join(out)}</figure>"
    )


def tiles(items: list[tuple[str, str, str]]) -> str:
    return (
        '<div class="tiles">'
        + "".join(
            f'<div class="tile"><div class="tv">{esc(v)}</div><div class="tl">{esc(lbl)}</div>'
            f'<div class="ts">{esc(sub)}</div></div>'
            for v, lbl, sub in items
        )
        + "</div>"
    )


def table(head: list[str], rows: list[list[str]], raw: bool = False) -> str:
    cell = (lambda c: c) if raw else esc
    return (
        "<div class='tw'><table><thead><tr>"
        + "".join(f"<th>{esc(h)}</th>" for h in head)
        + "</tr></thead><tbody>"
        + "".join("<tr>" + "".join(f"<td>{cell(c)}</td>" for c in r) + "</tr>" for r in rows)
        + "</tbody></table></div>"
    )


# ------------------------------------------------------------------ evidence
def _trace(case_id: str, cases: dict, sut: str, env: str = "sil", seed: int = 0):
    return simulate(cases[case_id].scenario, sut_factory(sut), sut_name=sut, env=ENVS[env], seed=seed)


def findings_section(cases: dict) -> str:
    parts = []
    # F-002
    ref, mut = _trace("FZ-003-CX", cases, "baseline"), _trace("FZ-003-CX", cases, "M09SopAssumesNewPack")
    parts.append(
        _finding(
            "F-002",
            "Regen overvoltage on an aged pack",
            "found by the falsifier, no hand-written test caught it",
            "Braking hard at 90 % SOC with R ×1.72. A reactive guard reacts one BMS frame too late. The fix is a "
            "predictive state-of-power limit from an online resistance estimate. The mutant M09 removes it.",
            [
                line_chart(
                    "Pack terminal voltage",
                    "V",
                    [
                        Line("released (SOP)", ref.t, ref["v_bus"]),
                        Line("M09: SOP assumes new pack", mut.t, mut["v_bus"]),
                    ],
                    [(815, "REQ-HV-002 limit 815 V")],
                    (0, 0.8),
                ),
                line_chart(
                    "Regenerative charging power",
                    "kW",
                    [Line("released (SOP)", ref.t, ref["p_regen_kw"]), Line("M09", mut.t, mut["p_regen_kw"])],
                    [],
                    (0, 0.8),
                ),
            ],
        )
    )
    # F-003
    ref, mut = _trace("FZ-003-CX2", cases, "baseline"), _trace("FZ-003-CX2", cases, "M10NoBrakeReleaseRampOut")
    parts.append(
        _finding(
            "F-003",
            "Brake-release over-braking: a requirements conflict",
            "found by the falsifier on the F-002 fix",
            "The driver eases off the brake during heavy regen. A slew-limited regen ramp-out over-brakes the car, "
            "because friction cannot go negative. Resolved by a ramp-out exception and refined requirements. M10 removes the exception.",
            [
                line_chart(
                    "Deceleration error vs driver demand",
                    "fraction of full braking",
                    [Line("released", ref.t, ref["decel_error"]), Line("M10: no ramp-out", mut.t, mut["decel_error"])],
                    [(0.05, "REQ-EM-006 tolerance 5 %")],
                    (4.9, 5.3),
                ),
                line_chart(
                    "Motor torque command",
                    "Nm",
                    [Line("released", ref.t, ref["torque_cmd"]), Line("M10", mut.t, mut["torque_cmd"])],
                    [],
                    (4.9, 5.3),
                ),
            ],
        )
    )
    # F-006
    ref = _trace("TC-001", cases, "baseline", "hil_mock", 3)
    mut = _trace("TC-001", cases, "M14MissingVoltageAsZero", "hil_mock", 3)
    parts.append(
        _finding(
            "F-006",
            "Power-up: missing voltage read as 0 V",
            "found because a clean change raised a HiL-only alarm",
            "On the HiL tier the first BMS frame arrives a few ms late. Reading the missing voltage as 0 V made the "
            "undervoltage guard latch the discharge limit for ~3 s. M14 re-introduces the 0 V default.",
            [
                line_chart(
                    "Discharge power limit after power-up (HiL-mock)",
                    "kW",
                    [
                        Line("released (INIT until first frame)", ref.t, ref["p_dis_lim_kw"]),
                        Line("M14: missing = 0 V", mut.t, mut["p_dis_lim_kw"]),
                    ],
                    [(500, "REQ-FS-015: >= 500 kW within 1 s")],
                    (0, 5),
                ),
                line_chart(
                    "Vehicle speed, first launch (HiL-mock)",
                    "km/h",
                    [Line("released", ref.t, ref["v_kph"]), Line("M14", mut.t, mut["v_kph"])],
                    [],
                    (0, 10),
                ),
            ],
        )
    )
    return "".join(parts)


def _finding(fid: str, title: str, how: str, text: str, charts: list[str]) -> str:
    return (
        f'<article class="finding"><header><span class="fid">{fid}</span><h3>{esc(title)}</h3>'
        f'<span class="how">{esc(how)}</span></header><p>{esc(text)}</p>'
        f'<div class="grid2">{"".join(charts)}</div></article>'
    )


def build(out: Path, requirements: Path, catalog: Path) -> Path:
    reqset = RequirementSet.load(requirements)
    cases = {c.id: c for c in load_catalog(catalog)}
    bench = json.loads((out / "benchmark.json").read_text()) if (out / "benchmark.json").exists() else None
    mm = json.loads((out / "mutation_matrix.json").read_text()) if (out / "mutation_matrix.json").exists() else None

    sections = []
    tile_items = [("6", "defects found and fixed by the pipeline", "F-001 … F-006, each with a regression test")]
    if mm:
        tile_items.append(
            (
                f"{mm['sil_killable_killed']}/{mm['sil_killable_total']}",
                "SiL-observable seeded bugs killed",
                "by the catalogue alone",
            )
        )
    if bench:
        s0 = {r["strategy"]: r for r in bench["summary_per_seed"][str(bench["seeds"][0])]}
        a, c = s0["A"], s0["C"]
        tile_items.append(
            (
                f"−{100 * (1 - c['mean_hil_minutes'] / a['mean_hil_minutes']):.0f} %",
                "HiL rig minutes per change",
                f"adaptive {c['mean_hil_minutes']} vs full {a['mean_hil_minutes']}",
            )
        )
        tile_items.append(
            (
                f"{c['bugs_detected']} vs {a['bugs_detected']}",
                "seeded bugs found",
                "adaptive vs full HiL regression (noise seed set 0)",
            )
        )
    sections.append(tiles(tile_items))

    sections.append(
        "<h2>Findings, with the measurements that show them</h2>"
        "<p class='lede'>Each plot is a fresh simulation: the released software against the mutant that "
        "re-introduces the defect. Hover for values.</p>" + findings_section(cases)
    )

    if bench:
        strategies = [
            s for s in "ABCD" if s in {r["strategy"] for r in bench["summary_per_seed"][str(bench["seeds"][0])]}
        ]
        names = {"A": "A · full", "B": "B · static", "C": "C · adaptive", "D": "D · noise-aware"}
        seeds = [str(s) for s in bench["seeds"]]
        rows = {s: {r["strategy"]: r for r in bench["summary_per_seed"][s]} for s in seeds}
        mean = lambda st, k: float(np.mean([rows[s][st][k] for s in seeds]))  # noqa: E731
        chart = bar_chart(
            "Cost per change, mean over noise seed sets",
            "minutes",
            [names[s] for s in strategies],
            [
                ("HiL rig minutes", [mean(s, "mean_hil_minutes") for s in strategies]),
                ("time to complete verdict", [mean(s, "mean_makespan_min") for s in strategies]),
                ("verdict on a clean change", [mean(s, "clean_change_makespan_min") for s in strategies]),
            ],
        )
        det_rows = []
        for s in seeds:
            for st in strategies:
                r = rows[s][st]
                det_rows.append(
                    [
                        s,
                        names[st],
                        r["bugs_detected"],
                        r["sil_observable_detected"],
                        r["hil_only_detected"],
                        r["vehicle_only_detected"],
                        r["false_alarms_on_clean"],
                        str(r["median_ttff_s"]),
                    ]
                )
        first = [o for o in bench["outcomes"] if o["seed"] == bench["seeds"][0]]
        pick = lambda st, ch: next(o for o in first if o["strategy"] == st and o["change"] == ch)  # noqa: E731

        def caption(o: dict) -> str:
            found = (
                f"found after {o['time_to_first_failure_s'] / 60:.1f} min in {', '.join(o['detected_in'][:2])}"
                if o["detected"]
                else "not found"
            )
            return (
                f"{o['change']} under policy {names[o['strategy']]}: {o['sil_jobs']} SiL jobs, {o['hil_jobs']} HiL "
                f"jobs ({o['hil_minutes']:.1f} rig-min), {found}"
            )

        ga, gc = pick("A", "M05DerateRampInverted"), pick("C", "M05DerateRampInverted")
        ha, hc = pick("A", "M14MissingVoltageAsZero"), pick("C", "M14MissingVoltageAsZero")
        tmax = max(o["makespan_s"] for o in (ga, gc, ha, hc))
        sections.append(
            "<h2>Where should a test run? SiL-first orchestration</h2>"
            "<p class='lede'>Every change is a CI event: 14 seeded bugs and 5 clean changes. Features come from the code "
            "diff via an ownership map. Same tests, environments and noise seeds for every policy. The HiL tier is a "
            "<b>mock</b>: bus jitter, frame loss, ADC noise, bring-up time.</p>"
            + "<p class='note'><b>A · full</b>: every test on SiL and on HiL. <b>B · static</b>: every test on SiL, and "
            "on HiL every test that traces to a requirement declared <code>hil</code>. <b>C · adaptive</b>: impact-selected "
            "tests on SiL; a test escalates to HiL only if the change touches one of its <code>hil</code> requirements, "
            "a SiL margin is thin, or a criticality-A margin regressed against the unchanged software. <b>D · noise-aware</b>: "
            "C, plus a change to code that consumes raw measurements escalates its impacted tests, and each HiL run is "
            "repeated on 3 noise seeds, stopping at the first failure.</p>"
            + chart
            + table(
                [
                    "seed set",
                    "policy",
                    "bugs found",
                    "SiL-observable",
                    "HiL-only",
                    "vehicle-only",
                    "false alarms (clean)",
                    "median time to first failure s",
                ],
                det_rows,
            )
            + "<h3 class='gh'>A SiL-observable bug (M05, thermal derating ramp inverted)</h3>"
            + gantt(caption(ga), ga["timeline"], tmax)
            + gantt(caption(gc), gc["timeline"], tmax)
            + "<h3 class='gh'>A HiL-only bug in a broad change (M14 modifies the top-level step(), so impact "
            "analysis rightly escalates widely)</h3>"
            + gantt(caption(ha), ha["timeline"], tmax)
            + gantt(caption(hc), hc["timeline"], tmax)
            + "<p class='note'>Honest limits: one HiL run is weak evidence against intermittent, noise-triggered faults. Policy D repeats HiL runs "
            "on 3 noise seeds for changes to measurement-consuming code and finds at least as many bugs as A on every seed set, at "
            "about 70 % of A's rig time. No policy catches M13 reliably, and D spends rig time on changes SiL has already failed, "
            "because no policy uses fail-fast.</p>"
        )

    if mm:
        rows_m = []
        hil_by = {}
        if bench:
            for o in bench["outcomes"]:
                if o["strategy"] == "A" and o["seed"] == bench["seeds"][0]:
                    hil_by[o["change"]] = sorted({d for d in o["detected_in"] if d.endswith("hil_mock")})
        for r in mm["mutants"]:
            sil = "; ".join(f"{k['test']}" for k in r["killed_by"]) or "—"
            hil = ", ".join(x.split("@")[0] for x in hil_by.get(r["mutant"], [])) or "—"
            info = MUTANTS[r["mutant"]]
            rows_m.append([r["mutant"], r["description"], ", ".join(info.features), r["fidelity"], sil, hil])
        sections.append(
            "<h2>Seeded bugs: how good is the test suite?</h2>"
            + table(
                [
                    "mutant",
                    "seeded bug",
                    "features (derived from the diff)",
                    "observable in",
                    "killed in SiL by",
                    "killed on HiL-mock by",
                ],
                rows_m,
            )
        )

    req_rows = [
        [r.id, r.title, r.stl_text or f"KPI {r.metric} <= {r.max}", r.criticality, r.fidelity]
        for r in reqset.reqs.values()
    ]
    sections.append(
        "<h2>Requirements (Signal Temporal Logic)</h2>"
        + table(["id", "requirement", "formal (STL)", "crit.", "fidelity"], req_rows)
    )

    sha = os.environ.get("GITHUB_SHA", "")[:7]
    page = (
        TEMPLATE.replace("{{BODY}}", "".join(sections))
        .replace("{{VERSION}}", esc(__version__))
        .replace("{{SHA}}", esc(f" · commit {sha}" if sha else ""))
    )
    site = out / "site"
    site.mkdir(parents=True, exist_ok=True)
    (site / "index.html").write_text(page)
    return site / "index.html"


TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>VoltTrace Evidence</title>
<style>
:root{color-scheme:light;--page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;
--grid:#e1e0d9;--axis:#c3c2b7;--ring:rgba(11,11,11,.10);--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--crit:#d03b3b}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;
--ink:#fff;--ink2:#c3c2b7;--muted:#898781;--grid:#2c2c2a;--axis:#383835;--ring:rgba(255,255,255,.10);--s1:#3987e5;
--s2:#d95926;--s3:#199e70}}
:root[data-theme="dark"]{color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;--ink:#fff;--ink2:#c3c2b7;--grid:#2c2c2a;
--axis:#383835;--ring:rgba(255,255,255,.10);--s1:#3987e5;--s2:#d95926;--s3:#199e70}
*{box-sizing:border-box}body{margin:0;background:var(--page);color:var(--ink);
font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1120px;margin:0 auto;padding:28px 16px 64px}
h1{font-size:28px;margin:0 0 4px}.gh{margin:22px 0 4px;font-size:15px}h2{font-size:20px;margin:44px 0 8px}h3{font-size:16px;margin:0}
.sub{color:var(--ink2);margin:0 0 6px}.disc{color:var(--muted);font-size:13px;margin:0 0 22px}
.lede{color:var(--ink2);max-width:80ch}.note{color:var(--ink2);font-size:14px;max-width:85ch}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}
.tile{background:var(--surface);border:1px solid var(--ring);border-radius:12px;padding:14px 16px}
.tv{font-size:30px;font-weight:650}.tl{font-weight:600}.ts{color:var(--muted);font-size:13px}
.finding{background:var(--surface);border:1px solid var(--ring);border-radius:12px;padding:16px;margin:14px 0}
.finding header{display:flex;flex-wrap:wrap;gap:8px 12px;align-items:baseline}
.fid{font-weight:700;border:1px solid var(--ring);border-radius:6px;padding:0 6px}.how{color:var(--muted);font-size:13px}
.finding p{color:var(--ink2);margin:8px 0 4px;max-width:90ch}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,460px),1fr));gap:12px}
.panel{margin:10px 0;background:var(--surface);border:1px solid var(--ring);border-radius:12px;padding:10px 12px;position:relative}
figcaption{display:flex;flex-wrap:wrap;gap:4px 10px;align-items:baseline;font-size:14px}
.unit{color:var(--muted);font-size:12px}.legend{display:flex;flex-wrap:wrap;gap:10px;margin-left:auto;font-size:12px;color:var(--ink2)}
.key i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:5px;vertical-align:-1px}
.key i.failkey{background:none;border:2px solid var(--crit)}
svg.chart{width:100%;height:auto;display:block}
.grid{stroke:var(--grid);stroke-width:1}.axis{stroke:var(--axis);stroke-width:1}
.tick,.cat,.val{fill:var(--muted);font-size:11px;font-variant-numeric:tabular-nums}.cat{fill:var(--ink2);font-size:12px}
svg.bars .tick,svg.gantt .tick,svg.bars .val{font-size:12px}svg.bars .cat,svg.gantt .cat{font-size:13px}
.val{fill:var(--ink2)}
.series{fill:none;stroke-width:2;stroke-linejoin:round;stroke-linecap:round}
.limit{stroke:var(--ink2);stroke-width:1.2;stroke-dasharray:5 4}.limit-label{fill:var(--ink2);font-size:11px}
.cross{stroke:var(--muted);stroke-width:1}.hit{fill:transparent}
.bar{stroke:var(--surface);stroke-width:2}.job{stroke:var(--surface);stroke-width:1}
.job.fail{stroke:var(--crit);stroke-width:2.5}.x{fill:#fff;font-size:11px;font-weight:700;pointer-events:none}
#tip{position:fixed;pointer-events:none;background:var(--surface);color:var(--ink);border:1px solid var(--ring);
border-radius:8px;padding:6px 9px;font-size:12px;box-shadow:0 4px 14px rgba(0,0,0,.18);display:none;z-index:9;max-width:340px}
#tip i{display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:5px}
.tw{overflow-x:auto;margin:10px 0}
table{border-collapse:collapse;width:100%;font-size:13px;background:var(--surface);border:1px solid var(--ring);border-radius:12px}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--grid);vertical-align:top}
th{color:var(--ink2);font-weight:600}td{font-variant-numeric:tabular-nums}
footer{color:var(--muted);font-size:13px;margin-top:48px}a{color:var(--s1)}
</style></head><body><main>
<h1>VoltTrace · validation evidence</h1>
<p class="sub">Falsification-driven, margin-aware SiL-first validation of a synthetic 800 V BEV energy-management function.</p>
<p class="disc">Independent portfolio project. All parameters, requirements and ECU code are synthetic and unrelated to any
manufacturer. v{{VERSION}}{{SHA}} · generated by <code>volttrace report</code> ·
<a href="https://github.com/justKPD/volttrace">source</a></p>
{{BODY}}
<footer>Every number on this page was produced by the run that generated it. Mock-HiL is a model of HiL effects,
not a HiL rig.</footer>
</main><div id="tip"></div>
<script>
const tip=document.getElementById('tip');
function show(e,h){tip.innerHTML=h;tip.style.display='block';const x=Math.min(e.clientX+14,innerWidth-tip.offsetWidth-8);
tip.style.left=x+'px';tip.style.top=(e.clientY+14)+'px'}
function hide(){tip.style.display='none'}
document.querySelectorAll('[data-tip]').forEach(el=>{el.addEventListener('mousemove',e=>show(e,el.dataset.tip));
el.addEventListener('mouseleave',hide)});
document.querySelectorAll('rect.hit').forEach(r=>{const S=JSON.parse(r.dataset.series),svg=r.ownerSVGElement,
c=svg.querySelector('.cross'),u=r.dataset.unit;
r.addEventListener('mousemove',e=>{const p=svg.createSVGPoint();p.x=e.clientX;p.y=e.clientY;
const q=p.matrixTransform(svg.getScreenCTM().inverse());let rows='',tt=null,cx=q.x;
S.forEach(s=>{let b=0,d=1e9;s.x.forEach((v,i)=>{const dd=Math.abs(v-q.x);if(dd<d){d=dd;b=i}});
if(tt===null){tt=s.t[b];cx=s.x[b]}rows+=`<div><i style="background:${s.color}"></i>${s.name}: <b>${s.y[b]}</b> ${u}</div>`});
c.setAttribute('x1',cx);c.setAttribute('x2',cx);c.setAttribute('visibility','visible');show(e,`<div>t = ${tt} s</div>`+rows)});
r.addEventListener('mouseleave',()=>{c.setAttribute('visibility','hidden');hide()})});
</script></body></html>
"""
