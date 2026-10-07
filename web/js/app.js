import { createEngine } from "./engine.js";
import { fmt, gantt, hideTip, lineChart, progressChart } from "./charts.js";
import * as session from "./session.js";
import { mountAssistant } from "./assistant.js";

const $ = (sel, root = document) => root.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const view = $("#view");

let engine = null;
let info = null;
const state = {
  bench: { case: "TC-001", sut: "baseline", env: "sil", seed: 0, overlay: false, overrides: {}, focus: null, window: null,
           scenario: null, last: null, ref: null, source: "Test Bench" },
  hunt: { active: false, runs: [], candidates: [], reveal: null, rig: 0, case: "TC-001", env: "sil", seed: 0, shown: null },
  falsify: { template: "FZ-003", sut: "M09SopAssumesNewPack", strategy: "random", budget: 30, seed: 1, result: null },
  ci: { change: "M14MissingVoltageAsZero", policy: "C", seed: 0, result: null },
  stl: { formula: "always(v_bus <= 812)", result: null },
};

// ------------------------------------------------------------------ engine boot
const pill = $("#engine");
function setStatus(s) {
  pill.className = "engine " + (s.error ? "error" : s.ready ? "ready" : "loading");
  pill.textContent = s.error ? "Engine failed to start" : s.ready ? "Engine ready · runs " + s.mode : s.text || "Engine: starting…";
  pill.title = s.error || "Where the simulation runs";
}
let bootError = null;
const booting = createEngine(setStatus)
  .then((e) => {
    engine = e;
    info = e.info;
    setStatus({ ready: true, mode: e.mode === "server" ? "in a local Python process" : "in your browser (Pyodide)" });
    render();
  })
  .catch((err) => {
    setStatus({ error: err.message });
    bootError = err;
    view.innerHTML = `<div class="note bad"><h3>The validation engine could not start</h3><p>${esc(err.message)}</p>
      <p>Everything on this site is computed by a Python engine that runs inside your browser. The
      <a href="report.html">project evidence report</a> works without it.</p></div>`;
  });

async function call(method, params, onProgress) {
  await booting;
  if (!engine) throw new Error("the validation engine is not available");
  return engine.call(method, params, onProgress);
}

// ------------------------------------------------------------------ helpers
const caseById = (id) => info.cases.find((c) => c.id === id);
const reqById = (id) => info.requirements.find((r) => r.id === id);
const versionById = (id) => info.versions.find((v) => v.id === id);
const verLabel = (id) => (id === "hidden" ? "the hidden change" : versionById(id)?.label || id);

function versionOptions(selected, groups = ["released", "seeded bug", "clean change", "historical build"]) {
  return groups
    .map((g) => {
      const opts = info.versions.filter((v) => v.group === g)
        .map((v) => `<option value="${v.id}" ${v.id === selected ? "selected" : ""}>${esc(v.label)}</option>`).join("");
      return opts ? `<optgroup label="${esc(g)}">${opts}</optgroup>` : "";
    })
    .join("");
}
function caseOptions(selected) {
  return info.cases.map((c) => `<option value="${c.id}" ${c.id === selected ? "selected" : ""}>${c.id} · ${esc(c.title)}</option>`).join("");
}
function chip(verdict, extra = "") {
  return `<span class="chip ${verdict}">${verdict === "VACUOUS" ? "NOT EXERCISED" : verdict}</span>${extra}`;
}
function marginBar(m) {
  if (m === null || m === undefined) return '<span class="muted">n/a</span>';
  const v = Math.max(-2, Math.min(2, m));
  const left = v >= 0 ? 50 : 50 + (v / 2) * 50;
  const width = (Math.abs(v) / 2) * 50;
  const color = m < 0 ? "var(--crit)" : m < 0.1 ? "#b37400" : "var(--good)";
  return `<span class="mbar"><b></b><i style="left:${left}%;width:${width}%;background:${color}"></i></span>${fmt(m)}`;
}
function download(name, text, type = "text/plain") {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type }));
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
function busy(btn, on, label) {
  if (!btn) return;
  btn.disabled = on;
  if (on) {
    btn.dataset.label = btn.innerHTML;
    btn.innerHTML = `<span class="spinner"></span> ${label || "Running…"}`;
  } else if (btn.dataset.label) btn.innerHTML = btn.dataset.label;
}
function errorNote(host, err) {
  host?.insertAdjacentHTML("afterbegin", `<div class="note bad">${esc(err.message || err)}</div>`);
}
const toastBox = $("#toast");
function toast(html) {
  if (!toastBox) return;
  toastBox.innerHTML = html;
  toastBox.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => toastBox.classList.remove("show"), 4500);
}

// ------------------------------------------------------------------ router
const routes = { "": renderStart, bench: renderBench, hunt: renderHunt, falsify: renderFalsify, ci: renderCI,
                 requirements: renderRequirements, findings: renderFindings, report: renderReport };
const ROUTE_NAMES = { "": "Start", bench: "Test Bench", hunt: "Bug Hunt", falsify: "Falsifier", ci: "CI Orchestrator",
                      requirements: "Requirements", findings: "Findings", report: "Session Report" };
const currentRoute = () => location.hash.replace(/^#\/?/, "").split("?")[0];
let skipHash = null;

function render() {
  hideTip();
  if (bootError) return;
  const route = currentRoute();
  document.querySelectorAll("#nav a[data-route]").forEach((a) => a.classList.toggle("active", a.dataset.route === route));
  if (!info) {
    view.innerHTML = `<div class="empty"><span class="spinner"></span> Starting the validation engine… the first visit
      downloads a Python runtime into your browser (about 10 MB, cached afterwards). Every result you will see is computed
      on your machine.</div>`;
    return;
  }
  (routes[route] || renderStart)();
  window.scrollTo(0, 0);
}
/** Show a page now (synchronously), so an action can run on it straight away. */
function navigate(route) {
  const hash = "#/" + route;
  if (location.hash !== hash && !(route === "" && location.hash === "")) {
    skipHash = hash;
    location.hash = hash;
  }
  render();
}
window.addEventListener("hashchange", () => {
  if (location.hash === skipHash) { skipHash = null; return; }
  skipHash = null;
  render();
});
render();

// ------------------------------------------------------------------ session log
function recordRun(res, source, spec) {
  const v = versionById(res.sut);
  const test = spec.scenario ? (source.startsWith("Falsifier") ? "falsifier scenario" : "custom scenario") : spec.case;
  const custom = spec.overrides && spec.overrides.initial && Object.keys(spec.overrides.initial).length ? spec.overrides.initial : null;
  const entry = session.record("run", {
    source, sut: res.sut, sutLabel: verLabel(res.sut), group: v ? v.group : "", test, env: res.env, seed: res.seed,
    overall: res.overall, rig_s: res.rig_seconds, sim_s: res.sim_seconds, params: custom,
    verdicts: res.verdicts.map((x) => ({ id: x.id, verdict: x.verdict, margin: x.margin, t: x.first_violation_t })),
    spec: { case: spec.case, scenario: spec.scenario, overrides: spec.overrides, sut: spec.sut, env: spec.env, seed: spec.seed },
  });
  toast(`Run #${entry.n} added to your <a href="#/report">Session Report</a>.`);
  return entry;
}
session.onChange(() => {
  const n = session.log.entries.length;
  const badge = $("#reportCount");
  if (badge) { badge.textContent = n ? String(n) : ""; badge.hidden = !n; }
  if (info && currentRoute() === "report") renderReport();
});
{
  const badge = $("#reportCount");
  if (badge && session.log.entries.length) { badge.textContent = String(session.log.entries.length); badge.hidden = false; }
}

/** Compact, signal-free summary of a run, for the assistant and for tool results. */
function runSummary(res) {
  const failed = res.verdicts.filter((v) => v.verdict === "FAIL");
  const passing = res.verdicts.filter((v) => v.margin !== null && v.verdict !== "FAIL");
  const thin = passing.length ? passing.reduce((a, b) => (b.margin < a.margin ? b : a)) : null;
  return {
    software: verLabel(res.sut), tier: res.env, seed: res.seed, overall: res.overall,
    failed: failed.map((v) => ({ requirement: v.id, title: v.title, margin: v.margin, first_violation_s: v.first_violation_t,
                                 new_vs_released: v.new_vs_released })),
    inconclusive: res.verdicts.filter((v) => v.verdict === "INCONCLUSIVE").map((v) => ({ requirement: v.id, margin: v.margin })),
    not_exercised: res.verdicts.filter((v) => v.verdict === "VACUOUS").map((v) => v.id),
    thinnest_pass: thin ? { requirement: thin.id, margin: thin.margin } : null,
    simulated_s: res.sim_seconds, rig_cost_s: res.rig_seconds,
  };
}

// ------------------------------------------------------------------ actions (UI buttons and the assistant share these)
const PARAM_ALIASES = { temp: "t_bat_c", temperature: "t_bat_c", t_bat: "t_bat_c", coolant: "t_coolant_bat_c", speed: "v_kph",
                        ageing: "r_aging_factor", aging: "r_aging_factor", age: "r_aging_factor" };
const actions = {
  routes: ROUTE_NAMES,
  currentRoute,
  get info() { return info; },
  state,
  session,
  ready: () => booting.then(() => { if (!info) throw new Error("the validation engine is not available"); }),

  async go(route) {
    await actions.ready();
    const r = String(route || "").replace(/^#?\/?/, "");
    if (!(r in ROUTE_NAMES)) throw new Error(`unknown page "${route}"; pages: ${Object.keys(ROUTE_NAMES).filter(Boolean).join(", ")}`);
    navigate(r);
    return { opened: ROUTE_NAMES[r] };
  },

  /** Run one test on the Test Bench. Missing fields keep the bench's current choice. */
  async runTest(o = {}, source = "Test Bench") {
    await actions.ready();
    const s = state.bench;
    if (o.case !== undefined && o.case !== null) {
      const c = info.cases.find((x) => x.id.toLowerCase() === String(o.case).toLowerCase());
      if (!c) throw new Error(`unknown test case "${o.case}"; cases: ${info.cases.map((x) => x.id).join(", ")}`);
      if (c.id !== s.case || s.scenario) { s.overrides = {}; s.focus = null; s.window = null; }
      s.case = c.id;
      s.scenario = null;
    }
    if (o.scenario) { s.scenario = o.scenario; s.overrides = {}; }
    if (o.overrides) s.overrides = o.overrides;
    if (o.sut !== undefined && o.sut !== null) {
      if (!versionById(o.sut)) throw new Error(`unknown software version "${o.sut}"; versions: ${info.versions.map((v) => v.id).join(", ")}`);
      s.sut = o.sut;
    }
    if (o.env !== undefined && o.env !== null) {
      const env = /hil/i.test(o.env) ? "hil_mock" : "sil";
      s.env = env;
    }
    if (o.seed !== undefined && o.seed !== null) s.seed = Math.max(0, Math.round(+o.seed) || 0);
    if (o.overlay !== undefined && o.overlay !== null) s.overlay = !!o.overlay;
    if (o.params && Object.keys(o.params).length) {
      if (s.scenario) throw new Error("scenario parameters apply to catalogue tests; pick a test case first");
      const initial = { ...(s.overrides.initial || {}) };
      for (const [k0, v] of Object.entries(o.params)) {
        const k = PARAM_ALIASES[k0] || k0;
        const p = PARAMS.find((x) => x[0] === k);
        if (!p) throw new Error(`unknown parameter "${k0}"; parameters: ${PARAMS.map((x) => x[0]).join(", ")}`);
        initial[k] = clampParam(k, +v);
      }
      s.overrides = { ...s.overrides, initial };
    }
    if (o.focus) s.focus = o.focus;
    if ("window" in o) s.window = o.window;
    s.last = null;
    s.ref = null;
    navigate("bench");
    const res = await runBench(source);
    return runSummary(res);
  },

  async replayFinding(id) {
    await actions.ready();
    const m = String(id).match(/(\d+)/);
    const fid = m ? `F-${m[1].padStart(3, "0")}` : String(id);
    const f = info.findings.find((x) => x.id === fid);
    if (!f) throw new Error(`unknown finding "${id}"; findings: ${info.findings.map((x) => x.id).join(", ")}`);
    const r = f.reproduce;
    Object.assign(state.bench, { scenario: null, case: r.case, sut: r.sut, env: r.env, seed: r.seed || 0, overrides: r.overrides || {},
      overlay: true, focus: r.focus, window: r.window, last: null, ref: null });
    navigate("bench");
    const res = await runBench(`Finding ${fid}`);
    return { finding: fid, title: f.title, ...runSummary(res) };
  },

  async falsify(o = {}) {
    await actions.ready();
    const f = state.falsify;
    if (o.template) {
      const t = info.templates.find((x) => x.id.toLowerCase() === String(o.template).toLowerCase());
      if (!t) throw new Error(`unknown template "${o.template}"; templates: ${info.templates.map((x) => x.id).join(", ")}`);
      f.template = t.id;
    }
    if (o.sut) {
      if (!versionById(o.sut)) throw new Error(`unknown software version "${o.sut}"`);
      f.sut = o.sut;
    }
    if (o.strategy) f.strategy = /cem|cross/i.test(o.strategy) ? "cem" : "random";
    if (o.budget) f.budget = Math.max(5, Math.min(80, Math.round(+o.budget) || 30));
    if (o.seed !== undefined && o.seed !== null) f.seed = Math.max(0, Math.round(+o.seed) || 0);
    f.result = null;
    navigate("falsify");
    const r = await doFalsify();
    return { template: f.template, software: verLabel(f.sut), strategy: f.strategy, found: r.found, simulations: r.sims,
             worst_margin: r.best.robustness, per_target: r.best.per_target, scenario: r.best.scenario };
  },

  async ci(o = {}) {
    await actions.ready();
    const c = state.ci;
    if (o.change) {
      const v = versionById(o.change);
      if (!v || !(v.group === "seeded bug" || v.group === "clean change")) throw new Error(`"${o.change}" is not a seeded bug or clean change`);
      c.change = v.id;
    }
    if (o.policy) {
      const p = String(o.policy).toUpperCase();
      if (!(p in POLICIES)) throw new Error("policy must be A, B, C or D");
      c.policy = p;
    }
    if (o.seed !== undefined && o.seed !== null) c.seed = Math.max(0, Math.round(+o.seed) || 0);
    c.result = null;
    navigate("ci");
    const r = await doCI();
    return { change: r.change, policy: r.policy, buggy: r.buggy, detected: r.detected, detected_in: r.detected_in,
             hil_rig_minutes: r.hil_minutes, sil_jobs: r.sil_jobs, hil_jobs: r.hil_jobs, verdict_after_min: +(r.makespan_s / 60).toFixed(2),
             escalations: r.escalations, features_from_diff: r.features };
  },

  async huntStart() {
    await actions.ready();
    const h = state.hunt;
    const r = await call("hunt_start", { seed: Math.floor(Math.random() * 1e9) });
    Object.assign(h, { active: true, runs: [], candidates: r.candidates, reveal: null, rig: 0, shown: null });
    session.record("hunt_start", {});
    navigate("hunt");
    return { started: true, candidates: r.candidates };
  },

  async huntRun(o = {}) {
    await actions.ready();
    const h = state.hunt;
    if (!h.active) throw new Error("no bug hunt is active; start one first");
    if (o.case) {
      const c = info.cases.find((x) => x.id.toLowerCase() === String(o.case).toLowerCase());
      if (!c) throw new Error(`unknown test case "${o.case}"`);
      h.case = c.id;
    }
    if (o.env) h.env = /hil/i.test(o.env) ? "hil_mock" : "sil";
    if (o.seed !== undefined && o.seed !== null) h.seed = Math.max(0, Math.round(+o.seed) || 0);
    if (currentRoute() !== "hunt") navigate("hunt");
    const res = await doHuntRun();
    return { ...runSummary(res), rig_spent_total_s: res.hunt.rig_seconds, runs: res.hunt.runs };
  },

  async huntReveal(guess) {
    await actions.ready();
    const h = state.hunt;
    if (!h.active) throw new Error("no bug hunt is active");
    if (!h.candidates.includes(guess)) throw new Error(`pick one of: ${h.candidates.join(", ")}`);
    h.reveal = await call("hunt_reveal", { guess });
    h.active = false;
    session.record("hunt_reveal", { change: h.reveal.change, guess, correct: h.reveal.correct, buggy: h.reveal.buggy,
      features: h.reveal.features, runs: h.reveal.runs, rig_s: h.reveal.rig_seconds });
    navigate("hunt");
    return h.reveal;
  },

  async stl(formula) {
    await actions.ready();
    state.stl.formula = String(formula);
    state.stl.result = null;
    navigate("requirements");
    const r = await doStl();
    return { formula: state.stl.formula, trace: r.trace, verdict: r.verdict, robustness: r.robustness, first_violation_s: r.first_violation_t };
  },

  async showSignals(list) {
    await actions.ready();
    const s = state.bench;
    if (!s.last) throw new Error("run a test first, then choose signals");
    const bad = list.filter((x) => !(x in info.channels));
    if (bad.length) throw new Error(`unknown signal(s): ${bad.join(", ")}; signals: ${Object.keys(info.channels).join(", ")}`);
    s.focus = [...list];
    navigate("bench");
    return { showing: s.focus };
  },

  /** win: [from, to] seconds, "violation", or null for the whole run. */
  async zoom(win) {
    await actions.ready();
    const s = state.bench;
    if (!s.last) throw new Error("run a test first, then zoom");
    if (win === "violation") {
      const fails = s.last.verdicts.filter((v) => v.first_violation_t !== null);
      if (!fails.length) throw new Error("the last run has no violation to zoom to");
      const t = Math.min(...fails.map((v) => v.first_violation_t));
      s.window = [Math.max(0, +(t - 0.5).toFixed(2)), +(t + 1.5).toFixed(2)];
    } else if (Array.isArray(win) && win.length === 2 && isFinite(win[0]) && isFinite(win[1]) && win[1] > win[0]) {
      s.window = [+win[0], +win[1]];
    } else s.window = null;
    navigate("bench");
    return { window_s: s.window || "whole run" };
  },

  summary() {
    const st = session.stats();
    return { ...st, insights: session.insights(session.log.entries, info).map((i) => i.text) };
  },

  clearSession() {
    session.clear();
    return { cleared: true };
  },
};
window.volttrace = actions; // handy in the console, and used by the end-to-end test

// ------------------------------------------------------------------ start
function renderStart() {
  const b = info.results.benchmark;
  const st = session.stats();
  view.innerHTML = `
  <h1>Validate an 800 V energy-management ECU, right here.</h1>
  <p class="lede">VoltTrace Studio runs a complete SiL test bench in your browser: a battery-electric vehicle model, a CAN bus
  defined by a DBC file, the energy-management software under test, and requirements written in Signal Temporal Logic. Every
  test tells you not only <b>pass or fail</b> but <b>how much margin</b> the software had. Pick a path, or ask the assistant
  (bottom right) in plain words: <i>"replay F-002"</i>, <i>"run TC-003 with M07 on HiL"</i>.</p>
  ${session.log.entries.length ? `<div class="banner"><span>Your session so far: <b>${st.tests}</b> test runs, <b>${st.failedRuns}</b> failed,
    <b>${st.counterexamples}</b> counterexamples, <b>${st.ciCycles}</b> CI cycles.</span>
    <a class="btn sm" href="#/report">Open your Session Report</a></div>` : ""}
  <div class="cards">
    <div class="card"><div class="step">1 · Run a test</div><h3>Test Bench</h3>
      <p>Run five 0–200 km/h launches, a cold aged pack or a hot track sprint. Break the software on purpose and watch the
      requirement that catches it.</p><a class="btn primary go" href="#/bench">Open the Test Bench</a></div>
    <div class="card"><div class="step">2 · Find a hidden bug</div><h3>Bug Hunt</h3>
      <p>A colleague pushed a change, which may be buggy or clean. Find what it broke, and spend as little expensive HiL rig
      time as you can.</p><a class="btn primary go" href="#/hunt">Start a hunt</a></div>
    <div class="card"><div class="step">3 · Let the machine search</div><h3>Falsifier</h3>
      <p>Instead of guessing scenarios, search them: pack ageing, state of charge, speed and braking until a requirement
      breaks. Download the result as a regression test.</p><a class="btn primary go" href="#/falsify">Run the falsifier</a></div>
    <div class="card"><div class="step">4 · Plan the CI</div><h3>CI Orchestrator</h3>
      <p>Each change is a CI event. Decide which tests run on cheap SiL and which go to the scarce HiL rig, and compare
      four policies.</p><a class="btn primary go" href="#/ci">Open the orchestrator</a></div>
  </div>
  <h2>How a test runs</h2>
  <div class="flow"><span>scenario + driver</span><em>→</em><span>vehicle, battery and thermal plant</span><em>→</em>
    <span>CAN bus (DBC, faults)</span><em>→</em><span>energy-management ECU software</span><em>→</em><span>torque and brake
    commands</span><em>→</em><span>STL requirements: verdict + margin</span></div>
  <div class="cards">
    <div class="card"><h3>SiL and HiL</h3><p><b>SiL</b> (software-in-the-loop) runs the ECU code against a model: fast and cheap.
      <b>HiL</b> (hardware-in-the-loop) runs it on a rig with real bus timing and sensors: slow and scarce. Here the HiL tier is a
      <b>mock</b> that adds bus jitter, frame loss and sensor noise.</p></div>
    <div class="card"><h3>Margin, not just PASS</h3><p>Each requirement is a formula. Its <b>robustness</b> is the signed distance
      to breaking it: +1.0 means one scale unit of headroom, below 0 means it broke. A tiny positive margin is reported as
      <b>INCONCLUSIVE</b>: green, but not trustworthy.</p></div>
    <div class="card"><h3>Seeded bugs</h3><p>${info.versions.filter((v) => v.group === "seeded bug").length} realistic mistakes
      (unit slips, wrong maps, missing debounce) are built in as alternative software versions. They are how the test suite
      itself is measured.</p></div>
    <div class="card"><h3>What it already found</h3><p>${info.findings.length} defects in its own released code, each
      replayable in one click.</p><a class="btn go" href="#/findings">See the findings</a></div>
  </div>
  ${b ? `<p class="muted small">Published benchmark: the adaptive policy uses about ${Math.round(100 * (1 - b.summary_per_seed["0"].find((r) => r.strategy === "C").mean_hil_minutes / b.summary_per_seed["0"].find((r) => r.strategy === "A").mean_hil_minutes))} %
  less HiL rig time per change than running every test on the rig. Details in <a href="#/ci">CI Orchestrator</a> and the
  <a href="report.html">project evidence report</a>.</p>` : ""}`;
}

// ------------------------------------------------------------------ test bench
// key, label, unit, step, min, max
const PARAMS = [
  ["soc", "State of charge", "0–1", 0.01, 0.05, 1.0],
  ["t_bat_c", "Cell temperature", "°C", 0.5, -30, 65],
  ["t_coolant_bat_c", "Coolant temperature", "°C", 0.5, -30, 60],
  ["v_kph", "Start speed", "km/h", 5, 0, 250],
  ["r_aging_factor", "Pack ageing (× resistance)", "", 0.1, 1.0, 3.0],
];
const DEFAULT_INITIAL = { soc: 0.8, t_bat_c: 30, t_coolant_bat_c: 25, v_kph: 0, r_aging_factor: 1.0 };
function clampParam(k, v) {
  const p = PARAMS.find((x) => x[0] === k);
  if (!Number.isFinite(v)) throw new Error(`${p[1]} must be a number`);
  if (k === "soc" && v > 1 && v <= 100) v = v / 100; // "soc 30" means 30 %
  return Math.min(p[5], Math.max(p[4], v));
}

function renderBench() {
  const s = state.bench;
  const c = s.scenario ? null : caseById(s.case);
  const initial = s.scenario ? s.scenario.initial || {} : { ...DEFAULT_INITIAL, ...c.initial, ...(s.overrides.initial || {}) };
  const ver = versionById(s.sut);
  const edited = Object.keys(s.overrides.initial || {});
  view.innerHTML = `
  <h1>Test Bench</h1>
  <p class="lede">Choose a test, a software version and a test tier, then run it. The ECU code, the plant and the requirement
  checks all execute ${engine.mode === "server" ? "in the local Python process" : "in your browser"}.</p>
  <div class="layout">
    <form class="side" id="benchForm" novalidate>
      ${s.scenario ? `<div class="note">Running a custom scenario (${esc(s.source)}).
        <button type="button" class="btn sm" id="clearScenario">Back to the catalogue</button></div>` :
      `<label class="f">Test case<select name="case">${caseOptions(s.case)}</select>
        <span class="help">${esc(c.title)} · ${c.requirements.length} requirements · ${c.fidelity === "hil" ? "needs HiL fidelity" : "SiL is enough"}</span></label>`}
      <label class="f">Software version<select name="sut">${versionOptions(s.sut)}</select>
        <span class="help">${esc(ver ? ver.description : "")}</span></label>
      <div class="f"><span class="f">Test tier</span>
        <div class="seg"><label><input type="radio" name="env" value="sil" ${s.env === "sil" ? "checked" : ""}>SiL · seconds</label>
        <label><input type="radio" name="env" value="hil_mock" ${s.env === "hil_mock" ? "checked" : ""}>HiL (mock) · minutes</label></div>
        <span class="help">HiL adds CAN jitter, frame loss and sensor noise, and costs ${info.envs.hil_mock.setup_s} s bring-up plus real time.</span></div>
      ${s.env === "hil_mock" ? `<label class="f">Noise seed<input type="number" name="seed" value="${s.seed}" min="0" step="1">
        <span class="help">Same seed = same noise. Intermittent faults show on some seeds only.</span></label>` : ""}
      ${s.scenario ? "" : `<details ${edited.length ? "open" : ""}><summary class="small">Scenario parameters${edited.length ? ` · ${edited.length} edited` : ""}</summary>
        <div class="grid2" style="margin-top:8px">${PARAMS.map(([k, label, unit, step, lo, hi]) =>
          `<label class="f small${edited.includes(k) ? " edited" : ""}">${label}${unit ? ` (${unit})` : ""}<input type="number" step="${step}" min="${lo}" max="${hi}" name="p_${k}" value="${initial[k]}"></label>`).join("")}</div>
        <span class="help">Out-of-range values are clamped to the model's valid range.</span>
        <button type="button" class="btn sm" id="resetParams" style="margin-top:6px">Reset to the test's values</button></details>`}
      <label class="check"><input type="checkbox" name="overlay" ${s.overlay ? "checked" : ""}>
        <span>Overlay the released software in the plots (runs it too, same scenario and seed)</span></label>
      <button class="btn primary" id="runBtn" type="submit">Run test</button>
    </form>
    <div id="benchOut" class="stack">${s.last ? "" : `<div class="empty">Run a test to see verdicts, margins and signals.</div>`}</div>
  </div>`;
  const form = $("#benchForm");
  form.addEventListener("change", (e) => {
    const n = e.target.name;
    if (n === "case") { s.case = e.target.value; s.overrides = {}; s.focus = null; s.window = null; return renderBench(); }
    if (n === "sut") { s.sut = e.target.value; return renderBench(); }
    if (n === "env") { s.env = e.target.value; return renderBench(); }
    if (n === "overlay") s.overlay = e.target.checked;
    if (n === "seed") { s.seed = Math.max(0, Math.round(+e.target.value) || 0); e.target.value = s.seed; }
    if (n && n.startsWith("p_")) {
      const k = n.slice(2);
      const init = { ...(s.overrides.initial || {}) };
      const raw = parseFloat(e.target.value);
      if (Number.isFinite(raw)) {
        init[k] = clampParam(k, raw);
        e.target.value = init[k];
      } else {
        delete init[k]; // a blank field means "use the test's own value"
        e.target.value = { ...DEFAULT_INITIAL, ...c.initial }[k];
      }
      s.overrides = { ...s.overrides, initial: init };
      e.target.closest("label").classList.toggle("edited", k in init);
    }
  });
  $("#resetParams")?.addEventListener("click", () => { s.overrides = {}; renderBench(); });
  $("#clearScenario")?.addEventListener("click", () => { s.scenario = null; s.last = null; s.ref = null; renderBench(); });
  form.addEventListener("submit", (e) => { e.preventDefault(); runBench().catch(() => {}); });
  if (s.last) showBenchResult();
}

function benchSpec(sut) {
  const s = state.bench;
  const base = s.scenario ? { scenario: s.scenario } : { case: s.case, overrides: s.overrides };
  return { ...base, sut, env: s.env, seed: s.seed };
}

async function runBench(source = "Test Bench") {
  const s = state.bench;
  const btn = $("#runBtn");
  busy(btn, true, "Simulating…");
  const spec = benchSpec(s.sut);
  try {
    s.ref = s.overlay && s.sut !== "baseline" ? await call("run", benchSpec("baseline")) : null;
    s.last = await call("run", spec);
    s.source = source;
    recordRun(s.last, source, spec);
    if (currentRoute() === "bench" && $("#benchOut")) showBenchResult();
    return s.last;
  } catch (err) {
    errorNote($("#benchOut"), err);
    throw err;
  } finally {
    busy(btn, false);
  }
}

function showBenchResult(host = $("#benchOut"), res = state.bench.last, ref = state.bench.ref, opts = {}) {
  const s = state.bench;
  const counts = {};
  res.verdicts.forEach((v) => (counts[v.verdict] = (counts[v.verdict] || 0) + 1));
  const fails = res.verdicts.filter((v) => v.verdict === "FAIL" && v.first_violation_t !== null);
  const firstV = fails.length ? Math.min(...fails.map((v) => v.first_violation_t)) : null;
  const verName = verLabel(res.sut);
  const explain = {
    PASS: "Every requirement held with a comfortable margin.",
    FAIL: "At least one requirement broke. The red line in the plots marks the first violation. Click a requirement row to jump to it.",
    INCONCLUSIVE: "Everything held, but at least one margin is too thin to trust this tier. A real team would escalate to HiL.",
    VACUOUS: "The scenario never triggered the requirement's condition, so it proves nothing about it.",
  }[res.overall];
  host.innerHTML = `
    <div class="banner"><span class="big">${chip(res.overall)}</span>
      <span>${Object.entries(counts).map(([k, n]) => `${n} ${k === "VACUOUS" ? "not exercised" : k.toLowerCase()}`).join(" · ")}</span>
      <span class="muted small">${esc(verName)} · ${res.env === "sil" ? "SiL" : `HiL mock, seed ${res.seed}`} ·
        ${res.sim_seconds} s simulated · rig cost ${fmt(res.rig_seconds)} s</span>
      ${opts.noExport ? "" : `<span class="row" style="margin-left:auto">
        <button class="btn sm" id="dlCsv">Signals CSV</button><button class="btn sm" id="dlJson">Verdicts JSON</button>
        <button class="btn sm" id="dlJunit">JUnit XML</button></span>`}</div>
    <div class="note">${explain}</div>
    <div class="tw"><table><thead><tr><th>Requirement</th><th>Verdict</th><th>Margin</th><th>First violation</th></tr></thead><tbody>
      ${res.verdicts.map((v) => `<tr class="click" data-req="${v.id}"><td><b>${v.id}</b> <span class="muted">${esc(v.title)}</span>
        <div class="small muted"><code>${esc(v.stl)}</code></div></td>
        <td>${chip(v.verdict, v.new_vs_released && res.sut === "hidden" ? ' <span class="chip new">new vs released</span>' : "")}</td>
        <td class="num">${marginBar(v.margin)}</td>
        <td class="num">${v.first_violation_t !== null ? fmt(v.first_violation_t) + " s" : ""}</td></tr>`).join("")}
    </tbody></table></div>
    <div class="row small"><span class="muted">Signals:</span><span class="chips" id="chanChips"></span></div>
    <div class="row small"><span class="muted">Time window:</span>
      <input type="number" id="w0" step="0.1" style="width:90px" placeholder="from s"> –
      <input type="number" id="w1" step="0.1" style="width:90px" placeholder="to s">
      <button class="btn sm" id="wApply">Apply</button>
      ${firstV !== null ? '<button class="btn sm" id="wViol">Zoom to first violation</button>' : ""}
      <button class="btn sm" id="wAll">Whole run</button></div>
    <div class="charts" id="charts"></div>`;
  const reqs = res.verdicts.map((v) => reqById(v.id));
  const reqSignals = [...new Set(reqs.flatMap((r) => r.limits.map((l) => l.signal)))].filter((x) => x in info.channels);
  const own = !opts.noExport; // the Test Bench remembers zoom and signals; the Bug Hunt panel does not
  let focus = (opts.focus || (own && s.focus) || [...reqSignals, "v_kph"]).filter((x, i, a) => a.indexOf(x) === i && x in res.signals);
  let win = "window" in opts ? opts.window : own ? s.window : null;
  const chips = $("#chanChips", host);
  const ordered = [...new Set([...focus, ...reqSignals, ...Object.keys(info.channels)])].filter((x) => x in res.signals);
  chips.innerHTML = ordered.map((ch) => `<label><input type="checkbox" value="${ch}" ${focus.includes(ch) ? "checked" : ""}>${ch}</label>`).join("");
  const setWin = (w) => { win = w; if (own) s.window = w; };
  const draw = () => {
    const box = $("#charts", host);
    box.innerHTML = "";
    $("#w0", host).value = win ? win[0] : "";
    $("#w1", host).value = win ? win[1] : "";
    for (const ch of focus) {
      const limits = [];
      reqs.forEach((r) => r.limits.filter((l) => l.signal === ch).forEach((l) => limits.push({ value: l.value, label: `${r.id} ${l.op} ${fmt(l.value)}` })));
      const series = [{ name: res.sut === "hidden" ? "hidden change" : verName, t: res.t, y: res.signals[ch] }];
      if (ref) series.push({ name: "released", t: ref.t, y: ref.signals[ch] });
      lineChart(box, { title: ch, unit: info.channels[ch], series, limits, window: win, marker: firstV });
    }
    if (!focus.length) box.innerHTML = '<div class="empty">Pick at least one signal above.</div>';
  };
  chips.addEventListener("change", () => {
    focus = [...chips.querySelectorAll("input:checked")].map((i) => i.value);
    if (own) s.focus = focus;
    draw();
  });
  $("#wApply", host).onclick = () => {
    const a = parseFloat($("#w0", host).value), b = parseFloat($("#w1", host).value);
    setWin(isFinite(a) && isFinite(b) && b > a ? [a, b] : null);
    draw();
  };
  if ($("#wViol", host)) $("#wViol", host).onclick = () => { setWin([Math.max(0, +(firstV - 0.5).toFixed(2)), +(firstV + 1.5).toFixed(2)]); draw(); };
  $("#wAll", host).onclick = () => { setWin(null); draw(); };
  host.querySelectorAll("tr[data-req]").forEach((tr) =>
    tr.addEventListener("click", () => {
      const r = reqById(tr.dataset.req);
      const sig = r.limits.map((l) => l.signal).filter((x) => x in res.signals);
      focus = [...new Set([...sig, ...focus])];
      if (own) s.focus = focus;
      chips.querySelectorAll("input").forEach((i) => (i.checked = focus.includes(i.value)));
      const v = res.verdicts.find((x) => x.id === r.id);
      if (v.first_violation_t !== null) setWin([Math.max(0, +(v.first_violation_t - 0.5).toFixed(2)), +(v.first_violation_t + 1.5).toFixed(2)]);
      draw();
      $("#charts", host).scrollIntoView({ behavior: "smooth", block: "start" });
    }));
  if (own) {
    $("#dlCsv", host).onclick = () => {
      const cols = Object.keys(res.signals);
      const lines = ["t," + cols.join(",")].concat(res.t.map((t, i) => [t, ...cols.map((c) => res.signals[c][i] ?? "")].join(",")));
      download(`volttrace_${res.sut}_${res.env}.csv`, lines.join("\n"), "text/csv");
    };
    $("#dlJson", host).onclick = () => download(`volttrace_${res.sut}_${res.env}.json`,
      JSON.stringify({ sut: res.sut, env: res.env, seed: res.seed, scenario: res.scenario, overall: res.overall, verdicts: res.verdicts }, null, 2), "application/json");
    $("#dlJunit", host).onclick = () => {
      const cases = res.verdicts.map((v) => `  <testcase classname="volttrace.${esc(res.sut)}" name="${v.id}">` +
        (v.verdict === "FAIL" ? `<failure message="margin=${v.margin} first_violation_t=${v.first_violation_t}"/>` :
          v.verdict !== "PASS" ? `<skipped message="${v.verdict} margin=${v.margin}"/>` : "") + "</testcase>").join("\n");
      const nf = res.verdicts.filter((v) => v.verdict === "FAIL").length;
      download(`junit_${res.sut}.xml`, `<?xml version="1.0" encoding="utf-8"?>\n<testsuite name="volttrace.${esc(res.sut)}" tests="${res.verdicts.length}" failures="${nf}">\n${cases}\n</testsuite>\n`, "application/xml");
    };
  }
  draw();
}

// ------------------------------------------------------------------ bug hunt
function renderHunt() {
  const h = state.hunt;
  view.innerHTML = `
  <h1>Bug Hunt</h1>
  <p class="lede">A colleague pushed a change to the energy-management software. It might contain a bug, or it might be a
  clean refactor. Find out which feature it breaks, if any. <b>SiL runs cost seconds; HiL rig runs cost minutes.</b>
  Good validation engineers spend the rig on purpose.</p>
  ${!h.active && !h.reveal ? `<div class="banner"><span>The change is hidden from you. Every run is compared with the released
    software on the same scenario and seed, and failures that only the change produces are marked <span class="chip new">new vs released</span>.</span>
    <button class="btn primary" id="huntStart">Start a hunt</button></div>` : ""}
  ${h.reveal ? revealHtml(h.reveal) : ""}
  ${h.active ? `<div class="layout"><form class="side" id="huntForm">
      <label class="f">Test case<select name="case">${caseOptions(h.case)}</select></label>
      <div class="f"><span class="f">Tier</span><div class="seg">
        <label><input type="radio" name="env" value="sil" ${h.env === "sil" ? "checked" : ""}>SiL</label>
        <label><input type="radio" name="env" value="hil_mock" ${h.env === "hil_mock" ? "checked" : ""}>HiL (mock)</label></div></div>
      <label class="f">Noise seed (HiL)<input type="number" name="seed" value="${h.seed}" min="0"></label>
      <button class="btn primary" id="huntRun" type="submit">Run on the hidden change</button>
      <div class="note small">Rig time spent: <b id="rigSpent">${fmt(h.rig || 0)} s</b> over ${h.runs.length} runs</div>
      <label class="f">Your verdict: which feature does it break?<select id="guess">
        <option value="">choose…</option>${h.candidates.map((c) => `<option>${esc(c)}</option>`).join("")}</select></label>
      <button class="btn" type="button" id="reveal">Reveal the change</button>
      <div class="history" id="hist">${h.runs.map((r, i) => `<button type="button" class="btn sm${h.shown === i ? " on" : ""}" data-i="${i}">#${i + 1} ${r.case} · ${r.env === "sil" ? "SiL" : `HiL s${r.seed}`} · ${r.res.overall}${r.res.verdicts.some((v) => v.new_vs_released) ? " · new failure" : ""}</button>`).join("")}</div>
    </form><div id="huntOut" class="stack"><div class="empty">Tip: start with cheap SiL runs across different tests. Escalate to HiL
    only when SiL is clean but you suspect timing or noise.</div></div></div>` : ""}`;
  $("#huntStart")?.addEventListener("click", async (e) => {
    busy(e.target, true, "Hiding a change…");
    try { await actions.huntStart(); } catch (err) { errorNote(view, err); busy(e.target, false); }
  });
  if (!h.active) return;
  const form = $("#huntForm");
  form.addEventListener("change", () => {
    const fd = new FormData(form);
    h.case = fd.get("case");
    h.env = fd.get("env");
    h.seed = Math.max(0, Math.round(+fd.get("seed")) || 0);
  });
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    doHuntRun().catch(() => {});
  });
  form.querySelectorAll("#hist button").forEach((b) => b.addEventListener("click", () => {
    h.shown = +b.dataset.i;
    form.querySelectorAll("#hist button").forEach((x) => x.classList.toggle("on", x === b));
    showBenchResult($("#huntOut"), h.runs[h.shown].res, null, { noExport: true });
  }));
  if (h.shown !== null && h.runs[h.shown]) showBenchResult($("#huntOut"), h.runs[h.shown].res, null, { noExport: true });
  $("#reveal").addEventListener("click", async (e) => {
    const guess = $("#guess").value;
    if (!guess) { errorNote($("#huntOut"), new Error("Pick your verdict first: which feature does the change break?")); return; }
    busy(e.target, true, "Revealing…");
    try { await actions.huntReveal(guess); } catch (err) { errorNote($("#huntOut"), err); busy(e.target, false); }
  });
}
async function doHuntRun() {
  const h = state.hunt;
  const spec = { case: h.case, env: h.env, seed: h.seed };
  const btn = $("#huntRun");
  busy(btn, true, "Running…");
  try {
    const res = await call("hunt_run", spec);
    h.rig = res.hunt.rig_seconds;
    h.runs.push({ ...spec, res });
    h.shown = h.runs.length - 1;
    const e = session.record("hunt_run", { sut: "hidden", sutLabel: "hidden change", group: "hunt", test: spec.case, env: res.env, seed: res.seed,
      overall: res.overall, rig_s: res.rig_seconds, sim_s: res.sim_seconds,
      newFails: res.verdicts.filter((v) => v.new_vs_released).map((v) => v.id),
      verdicts: res.verdicts.map((x) => ({ id: x.id, verdict: x.verdict, margin: x.margin, t: x.first_violation_t })) });
    toast(`Hunt run #${e.n} added to your <a href="#/report">Session Report</a>.`);
    if (currentRoute() === "hunt") renderHunt();
    return res;
  } catch (err) {
    errorNote($("#huntOut"), err);
    busy(btn, false);
    throw err;
  }
}
function revealHtml(r) {
  return `<div class="note ${r.correct ? "good" : "bad"}"><h3>${r.correct ? "Correct." : "Not quite."} The change was
    <code>${esc(r.change)}</code></h3>
    <p>${esc(r.description)}</p>
    <p>${r.buggy ? `It touches <b>${r.features.join(", ")}</b> and is observable in <b>${r.fidelity === "hil" ? "HiL only" : "SiL"}</b>.` : "It was a clean change: nothing to find."}
    You guessed <b>${esc(r.guess)}</b>, after ${r.runs} runs and <b>${fmt(r.rig_seconds)} s</b> of rig time.</p>
    <p class="small">See how the CI policies would have handled it: <a href="#/ci" data-change="${esc(r.change)}" id="toCi">open it in the CI Orchestrator</a>.</p>
    <button class="btn primary" id="huntStart">Hunt another one</button></div>`;
}
document.addEventListener("click", (e) => {
  const a = e.target.closest("#toCi");
  if (a) { state.ci.change = a.dataset.change; state.ci.result = null; }
});

// ------------------------------------------------------------------ falsifier
function renderFalsify() {
  const f = state.falsify;
  const tpl = info.templates.find((t) => t.id === f.template);
  view.innerHTML = `
  <h1>Falsifier</h1>
  <p class="lede">Hand-written tests check the corners an engineer thought of. The falsifier treats the closed loop as a black
  box and searches the scenario space for the input with the <b>least margin</b>. Below zero, it has found a counterexample,
  and you can keep that as a regression test.</p>
  <div class="layout"><form class="side" id="fzForm">
    <label class="f">Search template<select name="template">${info.templates.map((t) => `<option value="${t.id}" ${t.id === f.template ? "selected" : ""}>${t.id} · ${esc(t.title)}</option>`).join("")}</select>
      <span class="help">Targets: ${tpl.targets.join(", ")}</span></label>
    <div class="tw"><table class="small"><thead><tr><th>Searched parameter</th><th>Range</th></tr></thead><tbody>
      ${tpl.params.map((p) => `<tr><td><code>${esc(p.path)}</code></td><td class="num">${p.lo} – ${p.hi}</td></tr>`).join("")}</tbody></table></div>
    <label class="f">Software version<select name="sut">${versionOptions(f.sut)}</select>
      <span class="help">On the released software, a good search should find nothing. Try M09 to rediscover finding F-002.</span></label>
    <div class="f"><span class="f">Strategy</span><div class="seg">
      <label><input type="radio" name="strategy" value="random" ${f.strategy === "random" ? "checked" : ""}>Random</label>
      <label><input type="radio" name="strategy" value="cem" ${f.strategy === "cem" ? "checked" : ""}>Cross-entropy</label></div></div>
    <div class="grid2"><label class="f">Budget (sims)<input type="number" name="budget" value="${f.budget}" min="5" max="80"></label>
      <label class="f">Seed<input type="number" name="seed" value="${f.seed}" min="0"></label></div>
    <button class="btn primary" id="fzRun" type="submit">Search</button>
    <p class="help">Stops at the first counterexample. Each simulation takes a fraction of a second to a few seconds.</p>
  </form><div class="stack"><div id="fzChart"></div><div id="fzOut">${f.result ? "" : '<div class="empty">Start a search to watch the margin fall.</div>'}</div></div></div>`;
  const form = $("#fzForm");
  form.addEventListener("change", (e) => {
    const fd = new FormData(form);
    Object.assign(f, { template: fd.get("template"), sut: fd.get("sut"), strategy: fd.get("strategy"),
      budget: Math.max(5, Math.min(80, Math.round(+fd.get("budget")) || 30)), seed: Math.max(0, Math.round(+fd.get("seed")) || 0) });
    if (e.target.name === "template") { f.result = null; renderFalsify(); }
  });
  if (f.result) showFalsify(f.result);
  form.addEventListener("submit", (e) => { e.preventDefault(); doFalsify().catch(() => {}); });
}
async function doFalsify() {
  const f = state.falsify;
  const btn = $("#fzRun");
  busy(btn, true, "Searching…");
  const samples = [];
  if ($("#fzOut")) $("#fzOut").innerHTML = "";
  const chart = () => (currentRoute() === "falsify" ? $("#fzChart") : null);
  if (chart()) progressChart(chart(), { samples, budget: f.budget });
  const spec = { template: f.template, sut: f.sut, strategy: f.strategy, budget: f.budget, seed: f.seed };
  try {
    const r = await call("falsify", spec, (p) => {
      samples.push(p.robustness);
      if (chart()) progressChart(chart(), { samples, budget: f.budget, title: `Search progress · simulation ${p.i} of ${p.budget}` });
    });
    f.result = { ...r, budget: f.budget, spec };
    session.record("falsify", { ...spec, sutLabel: verLabel(f.sut), found: r.found, sims: r.sims, best: r.best.robustness, per_target: r.best.per_target });
    if (currentRoute() === "falsify" && $("#fzOut")) showFalsify(f.result);
    toast(`Search added to your <a href="#/report">Session Report</a>.`);
    return r;
  } catch (err) {
    errorNote($("#fzOut"), err);
    throw err;
  } finally { busy(btn, false); }
}
function showFalsify(r) {
  progressChart($("#fzChart"), { samples: r.samples, budget: r.budget, title: `Search finished · ${r.sims} simulations` });
  $("#fzOut").innerHTML = `
    <div class="note ${r.found ? "bad" : "good"}"><h3>${r.found ? `Counterexample found after ${r.sims} simulations` : `No counterexample in ${r.sims} simulations`}</h3>
    <p>${r.found ? "This scenario breaks a requirement. Replay it on the Test Bench, then keep it as a regression test." :
      "Worst margin found: " + fmt(r.best.robustness) + ". Absence of evidence is not proof, but it is evidence: the margin tells you how close the search got."}</p></div>
    <div class="tw"><table><thead><tr><th>Target requirement</th><th>Worst margin found</th></tr></thead><tbody>
      ${Object.entries(r.best.per_target).map(([k, v]) => `<tr><td><b>${k}</b> <span class="muted">${esc(reqById(k).title)}</span></td><td class="num">${marginBar(v)}</td></tr>`).join("")}
    </tbody></table></div>
    <div class="row"><button class="btn primary" id="toBench">Open this scenario on the Test Bench</button>
      ${r.regression_test_yaml ? '<button class="btn" id="dlYaml">Download as regression test (YAML)</button>' : ""}</div>
    <details><summary class="small">Scenario found</summary><pre>${esc(JSON.stringify(r.best.scenario, null, 2))}</pre></details>`;
  $("#toBench").onclick = () => {
    state.bench.focus = null;
    actions.runTest({ scenario: r.best.scenario, sut: r.spec.sut, env: "sil", seed: 0, overlay: true, window: null },
      `Falsifier ${r.spec.template}`).catch(() => {});
  };
  if ($("#dlYaml")) $("#dlYaml").onclick = () => download("regression_test.yaml", r.regression_test_yaml, "text/yaml");
}

// ------------------------------------------------------------------ CI orchestrator
const POLICIES = {
  A: ["Full", "Every test on SiL and on the HiL rig. The safe, slow baseline."],
  B: ["Static", "Every test on SiL; HiL for every test that traces to a requirement declared HiL-relevant."],
  C: ["Adaptive", "Only tests the change can affect run on SiL. A test goes to HiL if the change touches one of its HiL requirements, a SiL margin is thin, or a critical margin regressed."],
  D: ["Noise-aware", "C, plus: changes to code that reads raw sensor values or CAN timing escalate their tests, and every HiL run repeats on 3 noise seeds."],
};
function renderCI() {
  const c = state.ci;
  const changes = info.versions.filter((v) => v.group === "seeded bug" || v.group === "clean change");
  const ch = changes.find((v) => v.id === c.change) || changes[0];
  const b = info.results.benchmark;
  const tried = session.log.entries.filter((e) => e.kind === "ci" && e.change === ch.id);
  view.innerHTML = `
  <h1>CI Orchestrator</h1>
  <p class="lede">Every software change is a CI event. Running everything on the HiL rig is safe but slow; the question is
  which tests can stay on SiL. Pick a change and a policy and run the whole CI cycle live: every test, every escalation,
  every rig minute.</p>
  <div class="cards">${Object.entries(POLICIES).map(([k, [name, d]]) => `<div class="card"><div class="step">Policy ${k}</div><h3>${name}</h3><p>${d}</p></div>`).join("")}</div>
  <div class="layout"><form class="side" id="ciForm">
    <label class="f">Change under test<select name="change">${["seeded bug", "clean change"].map((g) => `<optgroup label="${g}">${changes.filter((v) => v.group === g).map((v) => `<option value="${v.id}" ${v.id === ch.id ? "selected" : ""}>${v.id}</option>`).join("")}</optgroup>`).join("")}</select>
      <span class="help">${esc(ch.description)}</span></label>
    <div class="f"><span class="f">Policy</span><div class="seg">${Object.keys(POLICIES).map((k) => `<label><input type="radio" name="policy" value="${k}" ${c.policy === k ? "checked" : ""}>${k}</label>`).join("")}</div></div>
    <label class="f">Noise seed set<input type="number" name="seed" value="${c.seed}" min="0"></label>
    <button class="btn primary" id="ciRun" type="submit">Run the CI cycle</button>
    <p class="help">Runs every test the policy selects on SiL and the HiL mock: from a few to ~60 simulations, so it can take a minute in the browser.</p>
    ${tried.length ? `<div class="small"><b>Your cycles on ${esc(ch.id)}</b><div class="tw"><table class="small"><thead><tr><th>Policy</th><th>Seed</th><th>Result</th><th>Rig-min</th></tr></thead><tbody>
      ${tried.map((t) => `<tr><td>${t.policy}</td><td>${t.seed}</td><td>${t.detected ? "red" : t.buggy ? "green (missed)" : "green"}</td><td class="num">${fmt(t.hil_minutes)}</td></tr>`).join("")}</tbody></table></div></div>` : ""}
  </form><div id="ciOut" class="stack">${c.result ? "" : '<div class="empty">Run a CI cycle to see the schedule.</div>'}</div></div>
  ${b ? `<h2>Published benchmark: all 19 changes × 4 policies × 3 noise seed sets</h2>
  <div class="tw"><table><thead><tr><th>Seed set</th><th>Policy</th><th>Bugs found</th><th>SiL-observable</th><th>HiL-only</th><th>False alarms</th><th>HiL min / change</th><th>Clean-change verdict (min)</th></tr></thead><tbody>
  ${Object.entries(b.summary_per_seed).flatMap(([seed, rows]) => rows.map((r) => `<tr><td>${seed}</td><td><b>${r.strategy}</b> ${POLICIES[r.strategy][0]}</td><td>${r.bugs_detected}</td><td>${r.sil_observable_detected}</td><td>${r.hil_only_detected}</td><td>${r.false_alarms_on_clean}</td><td class="num">${r.mean_hil_minutes}</td><td class="num">${r.clean_change_makespan_min}</td></tr>`)).join("")}
  </tbody></table></div><p class="muted small">Computed by <code>volttrace bench --seeds 0 1 2</code> (about 15 minutes); CI reproduces seed set 0 exactly on every push.</p>` : ""}`;
  const form = $("#ciForm");
  form.addEventListener("change", (e) => {
    const fd = new FormData(form);
    Object.assign(c, { change: fd.get("change"), policy: fd.get("policy"), seed: Math.max(0, Math.round(+fd.get("seed")) || 0) });
    if (e.target.name === "change") { c.result = null; renderCI(); }
  });
  if (c.result && c.result.change === ch.id) showCI(c.result);
  form.addEventListener("submit", (e) => { e.preventDefault(); doCI().catch(() => {}); });
}
async function doCI() {
  const c = state.ci;
  const btn = $("#ciRun");
  busy(btn, true, "Running CI…");
  const spec = { change: c.change, policy: c.policy, seed: c.seed };
  try {
    const r = await call("orchestrate", spec, (p) => {
      if (btn && btn.isConnected) btn.innerHTML = `<span class="spinner"></span> ${p.simulations} simulations…`;
    });
    c.result = r;
    session.record("ci", { ...spec, buggy: r.buggy, detected: r.detected, detected_in: r.detected_in, hil_minutes: r.hil_minutes,
      makespan_s: r.makespan_s, sil_jobs: r.sil_jobs, hil_jobs: r.hil_jobs, escalated: Object.keys(r.escalations).length });
    if (currentRoute() === "ci") renderCI();
    toast(`CI cycle added to your <a href="#/report">Session Report</a>.`);
    return r;
  } catch (err) {
    errorNote($("#ciOut"), err);
    throw err;
  } finally { busy(btn, false); }
}
function showCI(r) {
  const out = $("#ciOut");
  const verdict = r.detected ? `Red build: found in ${r.detected_in.join(", ")}` : r.buggy ? "Green build, but the change IS buggy: missed" : "Green build: correct, the change is clean";
  out.innerHTML = `
    <div class="note ${r.detected ? "bad" : r.buggy ? "bad" : "good"}"><h3>${esc(verdict)}</h3>
      <p>${esc(r.change)} under policy ${r.policy}: ${r.sil_jobs} SiL jobs, ${r.hil_jobs} HiL jobs, <b>${fmt(r.hil_minutes)} rig-minutes</b>,
      verdict after ${fmt(r.makespan_s / 60)} min${r.time_to_first_failure_s !== null ? `, first failure after ${fmt(r.time_to_first_failure_s / 60)} min` : ""}.
      ${r.simulations} simulations ran.</p>
      <p class="small">Impact analysis derived these features from the code diff: ${r.features.map((f) => `<span class="tag">${f}</span>`).join("")}
      ${r.noise_sensitive ? '<span class="tag">noise-sensitive</span>' : ""}</p></div>
    <div id="ciGantt"></div>
    ${Object.keys(r.escalations).length ? `<div class="tw"><table><thead><tr><th>Escalated to HiL</th><th>Why</th></tr></thead><tbody>
      ${Object.entries(r.escalations).map(([t, why]) => `<tr><td><b>${t}</b></td><td>${esc(why)}</td></tr>`).join("")}</tbody></table></div>` :
      '<p class="muted small">No test was escalated to HiL.</p>'}`;
  gantt($("#ciGantt"), { timeline: r.timeline, title: `Schedule: ${info.envs.sil.slots} SiL workers and ${info.envs.hil_mock.slots} HiL rig` });
}

// ------------------------------------------------------------------ requirements + STL playground
const STL_EXAMPLES = ["always(v_bus <= 812)", "always(implies(brake >= 0.5, eventually(decel_error <= 0.02, 0, 0.05)))",
                      "eventually(v_kph >= 100, 0, 5)", "always(t_inv <= 90)"];
function renderRequirements() {
  const last = state.bench.last;
  view.innerHTML = `
  <h1>Requirements</h1>
  <p class="lede">Each requirement is a Signal Temporal Logic formula over the logged signals. <code>always(φ)</code> must hold at
  every instant, <code>eventually(φ, 0, 0.2)</code> within 0.2 s, and <code>implies(a, b)</code> only when <code>a</code>
  holds. Robustness is divided by a per-signal scale, so margins of volts and degrees are comparable.</p>
  <h2>Write your own</h2>
  <div class="layout"><div class="side">
    <label class="f">STL formula<textarea id="stlText" spellcheck="false">${esc(state.stl.formula)}</textarea></label>
    <div class="row">${STL_EXAMPLES.map((ex) => `<button class="btn sm ex" type="button">${esc(ex)}</button>`).join("")}</div>
    <button class="btn primary" id="stlRun">Evaluate on the last run</button>
    <p class="help">${last || state.hunt.runs.length ? "Evaluates against the most recent Test Bench or Bug Hunt run." : "Run a test on the Test Bench first."}
      Signals: ${Object.keys(info.channels).map((c) => `<code>${c}</code>`).join(" ")}</p>
  </div><div id="stlOut" class="stack"><div class="empty">Run a test on the Test Bench, then evaluate a formula against its trace.</div></div></div>
  <h2>The specification</h2>
  <div class="tw"><table><thead><tr><th>ID</th><th>Requirement</th><th>Formal (STL)</th><th>Crit.</th><th>Needs</th><th>Features</th></tr></thead><tbody>
  ${info.requirements.map((r) => `<tr><td><b>${r.id}</b></td><td>${esc(r.title)}</td><td><code class="usestl" title="Click to load into the playground">${esc(r.stl)}</code></td><td>${r.criticality}</td>
    <td>${r.fidelity === "hil" ? "HiL" : "SiL"}</td><td>${r.features.map((f) => `<span class="tag">${f}</span>`).join("")}</td></tr>`).join("")}
  </tbody></table></div>`;
  const ta = $("#stlText");
  ta.addEventListener("input", () => (state.stl.formula = ta.value));
  view.querySelectorAll(".ex").forEach((b) => b.addEventListener("click", () => { ta.value = b.textContent; state.stl.formula = ta.value; }));
  view.querySelectorAll(".usestl").forEach((c) => c.addEventListener("click", () => {
    if (!/^KPI/.test(c.textContent)) { ta.value = c.textContent; state.stl.formula = ta.value; ta.scrollIntoView({ block: "center" }); }
  }));
  $("#stlRun").addEventListener("click", () => doStl().catch(() => {}));
  if (state.stl.result) showStl(state.stl.result);
}
async function doStl() {
  const btn = $("#stlRun");
  const out = $("#stlOut");
  busy(btn, true, "Evaluating…");
  try {
    const r = await call("stl_eval", { formula: state.stl.formula });
    state.stl.result = r;
    session.record("stl", { formula: state.stl.formula, trace: r.trace, verdict: r.verdict, robustness: r.robustness, t: r.first_violation_t });
    if (currentRoute() === "requirements") showStl(r);
    return r;
  } catch (err) {
    if (out) { out.innerHTML = ""; errorNote(out, err); }
    throw err;
  } finally { busy(btn, false); }
}
function showStl(r) {
  const out = $("#stlOut");
  out.innerHTML = `<div class="banner"><span class="big">${chip(r.verdict)}</span><span>robustness <b>${fmt(r.robustness)}</b>
    ${r.first_violation_t !== null ? ` · first violation at ${fmt(r.first_violation_t)} s` : ""}</span>
    <span class="muted small">on ${esc(r.trace)}; signals used: ${r.signals.join(", ")}</span></div>`;
  lineChart(out, { title: "Robustness over time", unit: "scaled margin (below 0 = violated)", series: [{ name: "ρ(t)", t: r.t, y: r.rho }],
                   limits: [{ value: 0, label: "0 = violation" }], marker: r.first_violation_t });
}

// ------------------------------------------------------------------ findings
function renderFindings() {
  view.innerHTML = `
  <h1>Findings</h1>
  <p class="lede">Six defects the pipeline found in its own released code. None were planted. Each <b>Replay</b> runs the exact
  scenario on the version that still has the defect, with the released software overlaid.</p>
  <div class="stack">${info.findings.map((f) => `<article class="finding"><header><span class="fid">${f.id}</span><h3>${esc(f.title)}</h3>
    <span class="tag">found by: ${esc(f.found_by)}</span></header>
    <p>${esc(f.story)}</p><p class="muted"><b>Fix:</b> ${esc(f.fix)}</p>
    <button class="btn primary replay" data-id="${f.id}">Replay ${f.id} on the Test Bench</button></article>`).join("")}</div>`;
  view.querySelectorAll(".replay").forEach((b) => b.addEventListener("click", () => actions.replayFinding(b.dataset.id).catch(() => {})));
}

// ------------------------------------------------------------------ session report
function renderReport() {
  const entries = session.log.entries;
  const st = session.stats();
  const ins = session.insights(entries, info);
  const cov = session.coverage();
  const tiles = [
    ["Test runs", st.tests, `${st.sil} SiL · ${st.hil} HiL mock`],
    ["Failed runs", st.failedRuns, `${st.failedChecks} of ${st.checks} requirement checks failed`],
    ["HiL rig time", `${Math.round(st.rigSeconds)} s`, st.ciRigMinutes ? `+ ${fmt(st.ciRigMinutes)} rig-min in CI cycles` : "in test runs"],
    ["Counterexamples", st.counterexamples, `from ${st.searches} falsifier search${st.searches === 1 ? "" : "es"}`],
    ["CI cycles", st.ciCycles, st.ciCycles ? `${session.log.entries.filter((e) => e.kind === "ci" && e.detected).length} red builds` : "none yet"],
    ["Bug hunts", `${st.huntsCorrect}/${st.hunts}`, "solved"],
  ];
  const runs = entries.filter((e) => e.kind === "run" || e.kind === "hunt_run");
  view.innerHTML = `
  <h1>Session Report</h1>
  <p class="lede">A live record of what <b>you</b> did in this browser: every test, search, CI cycle, bug hunt and formula, with
  the evidence it produced. It updates as you work and survives a reload. The
  <a href="report.html">project evidence report</a> is the separate, pre-built record of the published benchmark.</p>
  <div class="row"><button class="btn primary" id="dlHtml" ${entries.length ? "" : "disabled"}>Download report (HTML)</button>
    <button class="btn" id="dlJson" ${entries.length ? "" : "disabled"}>Session JSON</button>
    <button class="btn" id="dlJunit" ${runs.length ? "" : "disabled"}>JUnit XML (all runs)</button>
    <button class="btn" id="clearLog" ${entries.length ? "" : "disabled"}>Clear session</button>
    <span class="muted small">Started ${esc(new Date(session.log.started).toLocaleString())}</span></div>
  ${!entries.length ? `<div class="empty" style="margin-top:16px">Nothing recorded yet. Every action you take shows up here.<br><br>
    <span class="row" style="justify-content:center">
      <button class="btn primary" data-do="replay">Replay finding F-002</button>
      <button class="btn" data-do="bench">Run a test</button>
      <button class="btn" data-do="hunt">Start a bug hunt</button></span></div>` : `
  <div class="tiles">${tiles.map(([k, v, d]) => `<div class="tile"><span class="muted small">${k}</span><b>${esc(v)}</b><span class="muted small">${esc(d)}</span></div>`).join("")}</div>
  <h2>What your session shows</h2>
  <div class="stack" id="insights">${ins.map((i) => `<div class="note ${i.tone === "good" ? "good" : i.tone === "bad" ? "bad" : ""}">${esc(i.text)}</div>`).join("")}</div>
  ${cov.length ? `<h2>Requirement coverage</h2>
  <div class="tw"><table><thead><tr><th>Requirement</th><th>Checks</th><th>Failed</th><th>Inconclusive</th><th>Thinnest margin</th><th>Caught</th></tr></thead><tbody>
  ${cov.map((c) => `<tr><td><b>${c.id}</b> <span class="muted">${esc(reqById(c.id)?.title)}</span></td><td class="num">${c.checks}</td>
    <td class="num">${c.fails ? `<b style="color:var(--crit)">${c.fails}</b>` : 0}</td><td class="num">${c.inconclusive}</td>
    <td class="num">${marginBar(c.worst)} <div class="small muted">${esc(c.worstOn)}</div></td><td class="small">${esc(c.caught.join(", "))}</td></tr>`).join("")}
  </tbody></table></div>
  <p class="muted small">${info.requirements.length - cov.length} of ${info.requirements.length} requirements not checked yet in this session.</p>` : ""}
  <h2>Activity</h2>
  <div class="tw"><table id="activity"><thead><tr><th>#</th><th>Time</th><th>What happened</th><th></th></tr></thead><tbody>
  ${[...entries].reverse().map((e) => `<tr><td class="num">${e.n}</td><td class="num">${esc(new Date(e.at).toLocaleTimeString())}</td>
    <td>${e.overall ? chip(e.overall) + " " : ""}${esc(session.describe(e))}</td>
    <td>${e.kind === "run" && e.spec ? `<button class="btn sm rerun" data-n="${e.n}">Run again</button>` : ""}</td></tr>`).join("")}
  </tbody></table></div>`}`;
  const dl = (id, fn) => { const b = $(id); if (b) b.onclick = fn; };
  const stamp = () => new Date().toISOString().slice(0, 16).replace(/[:T]/g, "-");
  dl("#dlHtml", () => download(`volttrace_session_${stamp()}.html`, session.toHTML(session.log.entries, info), "text/html"));
  dl("#dlJson", () => download(`volttrace_session_${stamp()}.json`, session.toJSON(), "application/json"));
  dl("#dlJunit", () => download(`volttrace_session_${stamp()}.xml`, session.toJUnit(), "application/xml"));
  dl("#clearLog", () => { if (confirm("Clear the whole session log? Downloads you already made are not affected.")) session.clear(); });
  view.querySelectorAll("[data-do]").forEach((b) => b.addEventListener("click", () => {
    const d = b.dataset.do;
    if (d === "replay") actions.replayFinding("F-002").catch(() => {});
    else if (d === "bench") actions.runTest({}).catch(() => {});
    else actions.huntStart().catch(() => {});
  }));
  view.querySelectorAll(".rerun").forEach((b) => b.addEventListener("click", () => {
    const e = session.log.entries.find((x) => x.n === +b.dataset.n);
    const sp = e.spec;
    actions.runTest({ case: sp.scenario ? null : sp.case, scenario: sp.scenario || null, overrides: sp.scenario ? null : sp.overrides || {},
      sut: sp.sut, env: sp.env, seed: sp.seed },
      `Re-run of #${e.n}`).catch(() => {});
  }));
}

// ------------------------------------------------------------------ assistant
mountAssistant(actions);
