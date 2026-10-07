import { createEngine } from "./engine.js";
import { fmt, gantt, hideTip, lineChart, progressChart } from "./charts.js";

const $ = (sel, root = document) => root.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const view = $("#view");

let engine = null;
let info = null;
const state = {
  bench: { case: "TC-001", sut: "baseline", env: "sil", seed: 0, overlay: false, overrides: {}, focus: null, window: null,
           autorun: false, scenario: null, last: null, ref: null },
  hunt: { active: false, runs: [], candidates: [], reveal: null },
  falsify: { template: "FZ-003", sut: "M09SopAssumesNewPack", strategy: "random", budget: 30, seed: 1, result: null },
  ci: { change: "M14MissingVoltageAsZero", policy: "C", seed: 0, result: null },
};

// ------------------------------------------------------------------ engine boot
const pill = $("#engine");
function setStatus(s) {
  pill.className = "engine " + (s.error ? "error" : s.ready ? "ready" : "loading");
  pill.textContent = s.error ? "Engine failed: " + s.error : s.ready ? "Engine ready · runs " + s.mode : s.text || "Engine: starting…";
}
const booting = createEngine(setStatus)
  .then((e) => {
    engine = e;
    info = e.info;
    setStatus({ ready: true, mode: e.mode === "server" ? "in a local Python process" : "in your browser (Pyodide)" });
    render();
  })
  .catch((err) => setStatus({ error: err.message }));

async function call(method, params, onProgress) {
  await booting;
  if (!engine) throw new Error("engine not available");
  return engine.call(method, params, onProgress);
}

// ------------------------------------------------------------------ helpers
const caseById = (id) => info.cases.find((c) => c.id === id);
const reqById = (id) => info.requirements.find((r) => r.id === id);
const versionById = (id) => info.versions.find((v) => v.id === id);

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
  btn.disabled = on;
  if (on) {
    btn.dataset.label = btn.innerHTML;
    btn.innerHTML = `<span class="spinner"></span> ${label || "Running…"}`;
  } else if (btn.dataset.label) btn.innerHTML = btn.dataset.label;
}
function errorNote(host, err) {
  host.insertAdjacentHTML("afterbegin", `<div class="note bad">${esc(err.message || err)}</div>`);
}

// ------------------------------------------------------------------ router
const routes = { "": renderStart, bench: renderBench, hunt: renderHunt, falsify: renderFalsify, ci: renderCI,
                 requirements: renderRequirements, findings: renderFindings };
function render() {
  hideTip();
  const route = location.hash.replace(/^#\/?/, "").split("?")[0];
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
window.addEventListener("hashchange", render);
render();

// ------------------------------------------------------------------ start
function renderStart() {
  const b = info.results.benchmark;
  view.innerHTML = `
  <h1>Validate an 800 V energy-management ECU, right here.</h1>
  <p class="lede">VoltTrace Studio runs a complete SiL test bench in your browser: a battery-electric vehicle model, a CAN bus
  defined by a DBC file, the energy-management software under test, and requirements written in Signal Temporal Logic. Every
  test tells you not only <b>pass or fail</b> but <b>how much margin</b> the software had. Pick a path:</p>
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
  <a href="report.html">evidence report</a>.</p>` : ""}`;
}

// ------------------------------------------------------------------ test bench
const PARAMS = [
  ["soc", "State of charge", "", 0.01, (v) => v],
  ["t_bat_c", "Cell temperature", "°C", 0.5, (v) => v],
  ["t_coolant_bat_c", "Coolant temperature", "°C", 0.5, (v) => v],
  ["v_kph", "Start speed", "km/h", 5, (v) => v],
  ["r_aging_factor", "Pack ageing (× resistance)", "", 0.1, (v) => v],
];
const DEFAULT_INITIAL = { soc: 0.8, t_bat_c: 30, t_coolant_bat_c: 25, v_kph: 0, r_aging_factor: 1.0 };

function renderBench() {
  const s = state.bench;
  const c = s.scenario ? null : caseById(s.case);
  const initial = s.scenario ? s.scenario.initial || {} : { ...DEFAULT_INITIAL, ...c.initial, ...(s.overrides.initial || {}) };
  const ver = versionById(s.sut);
  view.innerHTML = `
  <h1>Test Bench</h1>
  <p class="lede">Choose a test, a software version and a test tier, then run it. The ECU code, the plant and the requirement
  checks all execute ${engine.mode === "server" ? "in the local Python process" : "in your browser"}.</p>
  <div class="layout">
    <form class="side" id="benchForm">
      ${s.scenario ? `<div class="note">Running a custom scenario (from the falsifier or a finding).
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
      ${s.scenario ? "" : `<details ${Object.keys(s.overrides.initial || {}).length ? "open" : ""}><summary class="small">Scenario parameters</summary>
        <div class="grid2" style="margin-top:8px">${PARAMS.map(([k, label, unit, step]) =>
          `<label class="f small">${label}${unit ? ` (${unit})` : ""}<input type="number" step="${step}" name="p_${k}" value="${initial[k]}"></label>`).join("")}</div>
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
    if (n === "seed") s.seed = +e.target.value;
    if (n && n.startsWith("p_")) {
      const k = n.slice(2);
      s.overrides.initial = { ...(s.overrides.initial || {}), [k]: +e.target.value };
    }
  });
  $("#resetParams")?.addEventListener("click", () => { s.overrides = {}; renderBench(); });
  $("#clearScenario")?.addEventListener("click", () => { s.scenario = null; s.last = null; s.ref = null; renderBench(); });
  form.addEventListener("submit", (e) => { e.preventDefault(); runBench(); });
  if (s.last) showBenchResult();
  if (s.autorun) { s.autorun = false; runBench(); }
}

function benchSpec(sut) {
  const s = state.bench;
  const base = s.scenario ? { scenario: s.scenario } : { case: s.case, overrides: s.overrides };
  return { ...base, sut, env: s.env, seed: s.seed };
}

async function runBench() {
  const s = state.bench;
  const btn = $("#runBtn");
  busy(btn, true, "Simulating…");
  const out = $("#benchOut");
  try {
    s.ref = s.overlay && s.sut !== "baseline" ? await call("run", benchSpec("baseline")) : null;
    s.last = await call("run", benchSpec(s.sut));
    showBenchResult();
  } catch (err) {
    errorNote(out, err);
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
  const verName = res.sut === "hidden" ? "the hidden change" : versionById(res.sut)?.label || res.sut;
  const explain = {
    PASS: "Every requirement held with a comfortable margin.",
    FAIL: "At least one requirement broke. The red line in the plots marks the first violation.",
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
  const ordered = [...new Set([...focus, ...reqSignals, ...Object.keys(info.channels)])];
  chips.innerHTML = ordered.map((ch) => `<label><input type="checkbox" value="${ch}" ${focus.includes(ch) ? "checked" : ""}>${ch}</label>`).join("");
  const draw = () => {
    const box = $("#charts", host);
    box.innerHTML = "";
    if (win) { $("#w0", host).value = win[0]; $("#w1", host).value = win[1]; }
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
    if (!opts.noExport) s.focus = focus;
    draw();
  });
  $("#wApply", host).onclick = () => {
    const a = parseFloat($("#w0", host).value), b = parseFloat($("#w1", host).value);
    win = isFinite(a) && isFinite(b) && b > a ? [a, b] : null;
    if (!opts.noExport) s.window = win;
    draw();
  };
  if ($("#wViol", host)) $("#wViol", host).onclick = () => { win = [Math.max(0, firstV - 0.5), firstV + 1.5]; draw(); };
  $("#wAll", host).onclick = () => { win = null; if (!opts.noExport) s.window = null; $("#w0", host).value = ""; $("#w1", host).value = ""; draw(); };
  host.querySelectorAll("tr[data-req]").forEach((tr) =>
    tr.addEventListener("click", () => {
      const r = reqById(tr.dataset.req);
      const sig = r.limits.map((l) => l.signal).filter((x) => x in res.signals);
      focus = [...new Set([...sig, ...focus])];
      chips.querySelectorAll("input").forEach((i) => (i.checked = focus.includes(i.value)));
      const v = res.verdicts.find((x) => x.id === r.id);
      if (v.first_violation_t !== null) win = [Math.max(0, v.first_violation_t - 0.5), v.first_violation_t + 1.5];
      draw();
      $("#charts", host).scrollIntoView({ behavior: "smooth", block: "start" });
    }));
  if (!opts.noExport) {
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
      <label class="f">Test case<select name="case">${caseOptions(h.case || "TC-001")}</select></label>
      <div class="f"><span class="f">Tier</span><div class="seg">
        <label><input type="radio" name="env" value="sil" checked>SiL</label>
        <label><input type="radio" name="env" value="hil_mock">HiL (mock)</label></div></div>
      <label class="f">Noise seed (HiL)<input type="number" name="seed" value="0" min="0"></label>
      <button class="btn primary" id="huntRun" type="submit">Run on the hidden change</button>
      <div class="note small">Rig time spent: <b id="rigSpent">${fmt(h.rig || 0)} s</b> over ${h.runs.length} runs</div>
      <label class="f">Your verdict: which feature does it break?<select id="guess">
        <option value="">choose…</option>${h.candidates.map((c) => `<option>${esc(c)}</option>`).join("")}</select></label>
      <button class="btn" type="button" id="reveal">Reveal the change</button>
      <div class="history" id="hist">${h.runs.map((r, i) => `<button type="button" class="btn sm" data-i="${i}">#${i + 1} ${r.case} · ${r.env === "sil" ? "SiL" : "HiL"} · ${r.res.overall}${r.res.verdicts.some((v) => v.new_vs_released) ? " · new failure" : ""}</button>`).join("")}</div>
    </form><div id="huntOut" class="stack"><div class="empty">Tip: start with cheap SiL runs across different tests. Escalate to HiL
    only when SiL is clean but you suspect timing or noise.</div></div></div>` : ""}`;
  $("#huntStart")?.addEventListener("click", async (e) => {
    busy(e.target, true, "Hiding a change…");
    const r = await call("hunt_start", { seed: Math.floor(Math.random() * 1e9) });
    Object.assign(h, { active: true, runs: [], candidates: r.candidates, reveal: null, rig: 0 });
    renderHunt();
  });
  if (!h.active) return;
  const form = $("#huntForm");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    const spec = { case: fd.get("case"), env: fd.get("env"), seed: +fd.get("seed") };
    h.case = spec.case;
    const btn = $("#huntRun");
    busy(btn, true, "Running…");
    try {
      const res = await call("hunt_run", spec);
      h.rig = res.hunt.rig_seconds;
      h.runs.push({ ...spec, res });
      renderHunt();
      showBenchResult($("#huntOut"), res, null, { noExport: true });
    } catch (err) { errorNote($("#huntOut"), err); busy(btn, false); }
  });
  form.querySelectorAll("#hist button").forEach((b) => b.addEventListener("click", () =>
    showBenchResult($("#huntOut"), h.runs[+b.dataset.i].res, null, { noExport: true })));
  $("#reveal").addEventListener("click", async () => {
    const guess = $("#guess").value;
    if (!guess) { alert("Pick your verdict first."); return; }
    h.reveal = await call("hunt_reveal", { guess });
    h.active = false;
    renderHunt();
  });
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
  if (a) state.ci.change = a.dataset.change;
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
  </form><div class="stack"><div id="fzChart"></div><div id="fzOut"></div></div></div>`;
  const form = $("#fzForm");
  form.addEventListener("change", (e) => {
    const fd = new FormData(form);
    Object.assign(f, { template: fd.get("template"), sut: fd.get("sut"), strategy: fd.get("strategy"), budget: +fd.get("budget"), seed: +fd.get("seed") });
    if (e.target.name === "template") renderFalsify();
  });
  if (f.result) showFalsify(f.result);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = $("#fzRun");
    busy(btn, true, "Searching…");
    const samples = [];
    $("#fzOut").innerHTML = "";
    progressChart($("#fzChart"), { samples, budget: f.budget });
    try {
      f.result = await call("falsify", { template: f.template, sut: f.sut, strategy: f.strategy, budget: f.budget, seed: f.seed }, (p) => {
        samples.push(p.robustness);
        progressChart($("#fzChart"), { samples, budget: f.budget, title: `Search progress · simulation ${p.i} of ${p.budget}` });
      });
      showFalsify(f.result);
    } catch (err) { errorNote($("#fzOut"), err); } finally { busy(btn, false); }
  });
}
function showFalsify(r) {
  const f = state.falsify;
  progressChart($("#fzChart"), { samples: r.samples, budget: f.budget, title: `Search finished · ${r.sims} simulations` });
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
    Object.assign(state.bench, { scenario: r.best.scenario, sut: f.sut, env: "sil", seed: 0, overlay: true, focus: null, window: null, autorun: true, last: null });
    location.hash = "#/bench";
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
  </form><div id="ciOut" class="stack">${c.result ? "" : '<div class="empty">Run a CI cycle to see the schedule.</div>'}</div></div>
  ${b ? `<h2>Published benchmark: all 19 changes × 4 policies × 3 noise seed sets</h2>
  <div class="tw"><table><thead><tr><th>Seed set</th><th>Policy</th><th>Bugs found</th><th>SiL-observable</th><th>HiL-only</th><th>False alarms</th><th>HiL min / change</th><th>Clean-change verdict (min)</th></tr></thead><tbody>
  ${Object.entries(b.summary_per_seed).flatMap(([seed, rows]) => rows.map((r) => `<tr><td>${seed}</td><td><b>${r.strategy}</b> ${POLICIES[r.strategy][0]}</td><td>${r.bugs_detected}</td><td>${r.sil_observable_detected}</td><td>${r.hil_only_detected}</td><td>${r.false_alarms_on_clean}</td><td class="num">${r.mean_hil_minutes}</td><td class="num">${r.clean_change_makespan_min}</td></tr>`)).join("")}
  </tbody></table></div><p class="muted small">Computed by <code>volttrace bench --seeds 0 1 2</code> (about 15 minutes); CI reproduces seed set 0 exactly on every push.</p>` : ""}`;
  const form = $("#ciForm");
  form.addEventListener("change", (e) => {
    const fd = new FormData(form);
    Object.assign(c, { change: fd.get("change"), policy: fd.get("policy"), seed: +fd.get("seed") });
    if (e.target.name === "change") renderCI();
  });
  if (c.result) showCI(c.result);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = $("#ciRun");
    busy(btn, true, "Running CI…");
    try {
      c.result = await call("orchestrate", { change: c.change, policy: c.policy, seed: c.seed }, (p) => {
        btn.innerHTML = `<span class="spinner"></span> ${p.simulations} simulations…`;
      });
      showCI(c.result);
    } catch (err) { errorNote($("#ciOut"), err); } finally { busy(btn, false); }
  });
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
function renderRequirements() {
  view.innerHTML = `
  <h1>Requirements</h1>
  <p class="lede">Each requirement is a Signal Temporal Logic formula over the logged signals. <code>always(φ)</code> must hold at
  every instant, <code>eventually(φ, 0, 0.2)</code> within 0.2 s, and <code>implies(a, b)</code> only when <code>a</code>
  holds. Robustness is divided by a per-signal scale, so margins of volts and degrees are comparable.</p>
  <h2>Write your own</h2>
  <div class="layout"><div class="side">
    <label class="f">STL formula<textarea id="stlText">always(v_bus <= 812)</textarea></label>
    <div class="row">${["always(v_bus <= 812)", "always(implies(brake >= 0.5, eventually(decel_error <= 0.02, 0, 0.05)))", "eventually(v_kph >= 100, 0, 5)", "always(t_inv <= 90)"]
      .map((ex) => `<button class="btn sm ex" type="button">${esc(ex)}</button>`).join("")}</div>
    <button class="btn primary" id="stlRun">Evaluate on the last Test Bench run</button>
    <p class="help">Signals: ${Object.keys(info.channels).map((c) => `<code>${c}</code>`).join(" ")}</p>
  </div><div id="stlOut" class="stack"><div class="empty">Run a test on the Test Bench, then evaluate a formula against its trace.</div></div></div>
  <h2>The specification</h2>
  <div class="tw"><table><thead><tr><th>ID</th><th>Requirement</th><th>Formal (STL)</th><th>Crit.</th><th>Needs</th><th>Features</th></tr></thead><tbody>
  ${info.requirements.map((r) => `<tr><td><b>${r.id}</b></td><td>${esc(r.title)}</td><td><code>${esc(r.stl)}</code></td><td>${r.criticality}</td>
    <td>${r.fidelity === "hil" ? "HiL" : "SiL"}</td><td>${r.features.map((f) => `<span class="tag">${f}</span>`).join("")}</td></tr>`).join("")}
  </tbody></table></div>`;
  view.querySelectorAll(".ex").forEach((b) => b.addEventListener("click", () => ($("#stlText").value = b.textContent)));
  $("#stlRun").addEventListener("click", async (e) => {
    const out = $("#stlOut");
    busy(e.target, true, "Evaluating…");
    try {
      const r = await call("stl_eval", { formula: $("#stlText").value });
      out.innerHTML = `<div class="banner"><span class="big">${chip(r.verdict)}</span><span>robustness <b>${fmt(r.robustness)}</b>
        ${r.first_violation_t !== null ? ` · first violation at ${fmt(r.first_violation_t)} s` : ""}</span>
        <span class="muted small">on the last run (${esc(state.bench.last ? state.bench.last.sut : "")}); signals used: ${r.signals.join(", ")}</span></div>`;
      lineChart(out, { title: "Robustness over time", unit: "scaled margin (below 0 = violated)", series: [{ name: "ρ(t)", t: r.t, y: r.rho }],
                       limits: [{ value: 0, label: "0 = violation" }], marker: r.first_violation_t });
    } catch (err) { out.innerHTML = ""; errorNote(out, err); } finally { busy(e.target, false); }
  });
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
  view.querySelectorAll(".replay").forEach((b) => b.addEventListener("click", () => {
    const f = info.findings.find((x) => x.id === b.dataset.id).reproduce;
    Object.assign(state.bench, { scenario: null, case: f.case, sut: f.sut, env: f.env, seed: f.seed || 0, overrides: f.overrides || {},
      overlay: true, focus: f.focus, window: f.window, autorun: true, last: null, ref: null });
    location.hash = "#/bench";
  }));
}
