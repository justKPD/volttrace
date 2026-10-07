/* The session log: every test, search, CI cycle, hunt and formula the user runs, kept in this browser.
   It drives the live Session Report and its HTML / JSON / JUnit exports. */

const KEY = "volttrace.session.v1";
const MAX_ENTRIES = 400;
const listeners = new Set();

function fresh() {
  return { started: new Date().toISOString(), entries: [] };
}
function load() {
  try {
    const j = JSON.parse(localStorage.getItem(KEY) || "null");
    if (j && Array.isArray(j.entries)) return j;
  } catch { /* storage blocked or corrupt: start a new session */ }
  return fresh();
}
export const log = load();

function save() {
  try {
    localStorage.setItem(KEY, JSON.stringify(log));
  } catch { /* private mode or quota: the session still works, it just will not survive a reload */ }
}

export function onChange(fn) {
  listeners.add(fn);
}

export function record(kind, data) {
  const last = log.entries[log.entries.length - 1];
  const entry = { n: (last ? last.n : 0) + 1, at: new Date().toISOString(), kind, ...data };
  log.entries.push(entry);
  if (log.entries.length > MAX_ENTRIES) log.entries.shift();
  save();
  listeners.forEach((fn) => fn(entry));
  return entry;
}

export function clear() {
  Object.assign(log, fresh());
  save();
  listeners.forEach((fn) => fn(null));
}

// ------------------------------------------------------------------ analysis
const byKind = (entries, k) => entries.filter((e) => e.kind === k);
const tierName = (env) => (env === "sil" ? "SiL" : "HiL mock");

export function stats(entries = log.entries) {
  const runs = byKind(entries, "run");
  const huntRuns = byKind(entries, "hunt_run");
  const all = [...runs, ...huntRuns];
  const reveals = byKind(entries, "hunt_reveal");
  const fz = byKind(entries, "falsify");
  const ci = byKind(entries, "ci");
  return {
    tests: all.length,
    sil: all.filter((r) => r.env === "sil").length,
    hil: all.filter((r) => r.env !== "sil").length,
    failedRuns: all.filter((r) => r.overall === "FAIL").length,
    failedChecks: all.reduce((n, r) => n + r.verdicts.filter((v) => v.verdict === "FAIL").length, 0),
    checks: all.reduce((n, r) => n + r.verdicts.length, 0),
    rigSeconds: all.filter((r) => r.env !== "sil").reduce((n, r) => n + (r.rig_s || 0), 0),
    simSeconds: all.reduce((n, r) => n + (r.sim_s || 0), 0),
    searches: fz.length,
    counterexamples: fz.filter((f) => f.found).length,
    ciCycles: ci.length,
    ciRigMinutes: ci.reduce((n, c) => n + (c.hil_minutes || 0), 0),
    hunts: reveals.length,
    huntsCorrect: reveals.filter((h) => h.correct).length,
    formulas: byKind(entries, "stl").length,
  };
}

/** Per requirement: how often it was checked, how often it failed, the thinnest margin and where. */
export function coverage(entries = log.entries) {
  const out = {};
  for (const r of entries.filter((e) => e.kind === "run" || e.kind === "hunt_run")) {
    for (const v of r.verdicts) {
      const c = (out[v.id] ||= { id: v.id, checks: 0, fails: 0, inconclusive: 0, worst: null, worstOn: "", caught: new Set() });
      c.checks += 1;
      if (v.verdict === "FAIL") {
        c.fails += 1;
        c.caught.add(r.sutLabel);
      }
      if (v.verdict === "INCONCLUSIVE") c.inconclusive += 1;
      if (v.margin !== null && v.margin !== undefined && (c.worst === null || v.margin < c.worst)) {
        c.worst = v.margin;
        c.worstOn = `${r.sutLabel} · ${r.test} · ${tierName(r.env)}`;
      }
    }
  }
  return Object.values(out)
    .map((c) => ({ ...c, caught: [...c.caught] }))
    .sort((a, b) => a.id.localeCompare(b.id));
}

const f2 = (v) => (v === null || v === undefined ? "n/a" : (v >= 0 ? "+" : "") + Number(v).toFixed(2));

/** Plain-language observations about the session, most important first. Each is {tone, text}. */
export function insights(entries = log.entries, info = null) {
  const out = [];
  const s = stats(entries);
  const runs = entries.filter((e) => e.kind === "run");
  if (!entries.length) return out;

  // Seeded bugs: which were exercised, which were caught, and by which requirement
  const bugRuns = runs.filter((r) => r.group === "seeded bug" || r.group === "historical build");
  const bugs = [...new Set(bugRuns.map((r) => r.sut))];
  const caught = bugs.filter((b) => bugRuns.some((r) => r.sut === b && r.overall === "FAIL"));
  const flagged = bugs.filter((b) => !caught.includes(b) && bugRuns.some((r) => r.sut === b && r.overall === "INCONCLUSIVE"));
  const missed = bugs.filter((b) => !caught.includes(b) && !flagged.includes(b));
  if (flagged.length) {
    out.push({ tone: "info", text: `Flagged but not failed: ${flagged.join(", ")}. Every check held, but with a margin too thin to trust (INCONCLUSIVE). That is how F-001 was found: escalate it to HiL or search around it.` });
  }
  if (caught.length) {
    const detail = caught.map((b) => {
      const reqs = [...new Set(bugRuns.filter((r) => r.sut === b).flatMap((r) => r.verdicts.filter((v) => v.verdict === "FAIL").map((v) => v.id)))];
      return `${b} (by ${reqs.join(", ")})`;
    });
    out.push({ tone: "good", text: `Your tests caught ${caught.length} of ${bugs.length} faulty version${bugs.length > 1 ? "s" : ""} you ran: ${detail.join("; ")}.` });
  }
  if (missed.length) {
    const hilOnly = missed.filter((b) => !bugRuns.some((r) => r.sut === b && r.env !== "sil"));
    out.push({
      tone: "bad",
      text: `Not caught yet: ${missed.join(", ")}. ` +
        (hilOnly.length ? `${hilOnly.join(", ")} never ran on the HiL tier; some faults only show with bus timing and sensor noise.` :
          "Try another test case or another HiL noise seed: intermittent faults show on some seeds only."),
    });
  }
  // Clean versions that failed: false alarms or real findings (F-006 started this way)
  const cleanFails = runs.filter((r) => (r.group === "released" || r.group === "clean change") && r.overall === "FAIL");
  if (cleanFails.length) {
    out.push({ tone: "bad", text: `${cleanFails.length} run${cleanFails.length > 1 ? "s" : ""} of released or clean software failed (${[...new Set(cleanFails.map((r) => `${r.sutLabel} on ${r.test}`))].join(", ")}). Either the scenario is outside the spec, or you found something: F-006 began as exactly such a "false alarm".` });
  }
  // Thinnest passing margin across the session
  const passing = [];
  for (const r of entries.filter((e) => e.kind === "run" || e.kind === "hunt_run")) {
    for (const v of r.verdicts) if (v.verdict !== "FAIL" && v.margin !== null && v.margin !== undefined) passing.push({ r, v });
  }
  if (passing.length) {
    const t = passing.reduce((a, b) => (b.v.margin < a.v.margin ? b : a));
    if (t.v.margin < 0.3) {
      out.push({ tone: t.v.margin < 0.1 ? "bad" : "info", text: `Thinnest pass: ${t.v.id} at ${f2(t.v.margin)} on ${t.r.sutLabel}, ${t.r.test}, ${tierName(t.r.env)}. ${t.v.margin < 0.1 ? "That is inside the inconclusive band: a SiL pass this thin is not evidence, so escalate it to HiL." : "Green, but close: a falsifier search around this scenario is a good next step."}` });
    }
  }
  // Tier usage
  if (s.tests) {
    out.push({ tone: "info", text: `${s.tests} test run${s.tests > 1 ? "s" : ""}: ${s.sil} on SiL and ${s.hil} on the HiL mock, ${Math.round(s.rigSeconds)} s of rig time.` +
      (s.hil === 0 && s.tests >= 3 ? " You have not used the HiL tier yet: TC-005 and the noise-sensitive bugs (M11, M12, M13) need it." : "") });
  }
  // Falsifier
  for (const f of byKind(entries, "falsify").slice(-3)) {
    out.push({ tone: f.found ? "bad" : "good", text: f.found ? `The falsifier broke ${f.sutLabel} with ${f.template} after ${f.sims} simulations (worst margin ${f2(f.best)}). Keep that scenario as a regression test.` :
      `The falsifier found no counterexample for ${f.sutLabel} with ${f.template} in ${f.sims} simulations; it got within ${f2(f.best)}.` });
  }
  // CI policies compared on the same change
  const ci = byKind(entries, "ci");
  const changes = [...new Set(ci.map((c) => c.change))];
  for (const ch of changes) {
    const cs = ci.filter((c) => c.change === ch);
    const pols = [...new Set(cs.map((c) => c.policy))];
    if (pols.length > 1) {
      const last = Object.fromEntries(cs.map((c) => [c.policy, c]));
      out.push({ tone: "info", text: `${ch}: ` + pols.sort().map((p) => `policy ${p} ${last[p].detected ? "caught it" : last[p].buggy ? "missed it" : "stayed green"} with ${f2(last[p].hil_minutes).replace("+", "")} rig-min`).join(", ") + "." });
    } else {
      const c = cs[cs.length - 1];
      out.push({ tone: c.detected || !c.buggy ? "good" : "bad", text: `CI on ${ch}, policy ${c.policy}: ${c.detected ? `red build, found in ${c.detected_in.join(", ")}` : c.buggy ? "green build, but the change is buggy: a miss" : "green build, correctly: the change is clean"} (${f2(c.hil_minutes).replace("+", "")} rig-min). Run another policy on it to compare.` });
    }
  }
  // Hunts
  if (s.hunts) out.push({ tone: s.huntsCorrect === s.hunts ? "good" : "info", text: `Bug hunts: ${s.huntsCorrect} of ${s.hunts} solved.` });
  if (info && runs.length && !runs.some((r) => r.group === "seeded bug")) {
    out.push({ tone: "info", text: `Every run so far used released or clean software. Pick a seeded bug (for example M09) on the Test Bench to see a requirement catch it.` });
  }
  return out;
}

// ------------------------------------------------------------------ exports
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

export function toJSON(entries = log.entries) {
  return JSON.stringify({ tool: "VoltTrace Studio", started: log.started, exported: new Date().toISOString(), stats: stats(entries), coverage: coverage(entries), entries }, null, 2);
}

export function toJUnit(entries = log.entries) {
  const runs = entries.filter((e) => e.kind === "run" || e.kind === "hunt_run");
  const suites = runs.map((r) => {
    const name = `#${r.n} ${r.sutLabel} ${r.test} ${tierName(r.env)}${r.env !== "sil" ? ` seed ${r.seed}` : ""}`;
    const cases = r.verdicts.map((v) => `    <testcase classname="volttrace.${esc(r.sut)}.${esc(r.test)}.${esc(r.env)}" name="${esc(v.id)}">` +
      (v.verdict === "FAIL" ? `<failure message="margin=${v.margin} first_violation_t=${v.t}"/>` :
        v.verdict !== "PASS" ? `<skipped message="${esc(v.verdict)} margin=${v.margin}"/>` : "") + "</testcase>").join("\n");
    const nf = r.verdicts.filter((v) => v.verdict === "FAIL").length;
    return `  <testsuite name="${esc(name)}" tests="${r.verdicts.length}" failures="${nf}" timestamp="${esc(r.at)}">\n${cases}\n  </testsuite>`;
  });
  return `<?xml version="1.0" encoding="utf-8"?>\n<testsuites name="VoltTrace Studio session">\n${suites.join("\n")}\n</testsuites>\n`;
}

export function describe(e) {
  switch (e.kind) {
    case "run": return `Ran ${e.test} on ${e.sutLabel}, ${tierName(e.env)}${e.env !== "sil" ? ` seed ${e.seed}` : ""}: ${e.overall}` + (e.source && e.source !== "Test Bench" ? ` (via ${e.source})` : "");
    case "hunt_start": return "Started a bug hunt on a hidden change";
    case "hunt_run": return `Bug hunt: ${e.test} on ${tierName(e.env)}${e.env !== "sil" ? ` seed ${e.seed}` : ""}: ${e.overall}${e.newFails.length ? ` (new failures: ${e.newFails.join(", ")})` : ""}`;
    case "hunt_reveal": return `Bug hunt revealed ${e.change}: guessed "${e.guess}", ${e.correct ? "correct" : "wrong"} after ${e.runs} runs and ${Math.round(e.rig_s)} s rig time`;
    case "falsify": return `Falsifier ${e.template} (${e.strategy}) on ${e.sutLabel}: ${e.found ? `counterexample after ${e.sims} sims` : `nothing in ${e.sims} sims`}, worst margin ${f2(e.best)}`;
    case "ci": return `CI cycle on ${e.change}, policy ${e.policy}: ${e.detected ? `red (${e.detected_in.join(", ")})` : e.buggy ? "green, bug missed" : "green, clean"}, ${f2(e.hil_minutes).replace("+", "")} rig-min`;
    case "stl": return `STL ${e.formula} on ${e.trace}: ${e.verdict}, robustness ${f2(e.robustness)}`;
    default: return e.kind;
  }
}

export function toHTML(entries = log.entries, info = null) {
  const s = stats(entries);
  const cov = coverage(entries);
  const ins = insights(entries, info);
  const reqTitle = (id) => (info ? (info.requirements.find((r) => r.id === id) || {}).title || "" : "");
  const tiles = [
    ["Test runs", s.tests, `${s.sil} SiL · ${s.hil} HiL mock`],
    ["Failed runs", s.failedRuns, `${s.failedChecks} of ${s.checks} requirement checks`],
    ["HiL rig time", `${Math.round(s.rigSeconds)} s`, `plus ${s.ciRigMinutes.toFixed(1)} rig-min in CI cycles`],
    ["Counterexamples", s.counterexamples, `${s.searches} falsifier searches`],
    ["CI cycles", s.ciCycles, ""],
    ["Bug hunts", `${s.huntsCorrect}/${s.hunts}`, "solved"],
  ];
  const runs = entries.filter((e) => e.kind === "run" || e.kind === "hunt_run");
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>VoltTrace session report</title><style>
:root{--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--ring:rgba(11,11,11,.12);--page:#f9f9f7;--surface:#fff;--good:#006300;--bad:#d03b3b;--warn:#b37400}
@media (prefers-color-scheme:dark){:root{--ink:#fff;--ink2:#c3c2b7;--muted:#898781;--ring:rgba(255,255,255,.12);--page:#0d0d0d;--surface:#1a1a19;--good:#0ca30c}}
body{margin:0;background:var(--page);color:var(--ink);font:14px/1.5 system-ui,sans-serif}main{max-width:1100px;margin:0 auto;padding:24px 16px}
h1{margin:0 0 4px}h2{margin:26px 0 8px;font-size:18px}.muted{color:var(--muted)}table{border-collapse:collapse;width:100%;background:var(--surface);font-size:13px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--ring);vertical-align:top}th{color:var(--ink2)}.tw{overflow-x:auto}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}.tile{background:var(--surface);border:1px solid var(--ring);border-radius:12px;padding:10px 12px}
.tile b{display:block;font-size:24px}.ins{background:var(--surface);border:1px solid var(--ring);border-left:3px solid var(--ink2);border-radius:8px;padding:8px 12px;margin:6px 0}
.ins.good{border-left-color:var(--good)}.ins.bad{border-left-color:var(--bad)}.FAIL{color:var(--bad);font-weight:600}.PASS{color:var(--good);font-weight:600}.INCONCLUSIVE{color:var(--warn);font-weight:600}
</style></head><body><main>
<h1>VoltTrace session report</h1>
<p class="muted">Session started ${esc(new Date(log.started).toLocaleString())}; exported ${esc(new Date().toLocaleString())}. Every result was computed by the
VoltTrace engine during this session. The system is synthetic and the HiL tier is a mock of HiL effects, not a rig.</p>
<div class="tiles">${tiles.map(([k, v, d]) => `<div class="tile"><span class="muted">${k}</span><b>${esc(v)}</b><span class="muted">${esc(d)}</span></div>`).join("")}</div>
<h2>What this session shows</h2>${ins.map((i) => `<div class="ins ${i.tone}">${esc(i.text)}</div>`).join("") || '<p class="muted">Nothing yet.</p>'}
<h2>Requirement coverage</h2><div class="tw"><table><thead><tr><th>Requirement</th><th>Checks</th><th>Failed</th><th>Inconclusive</th><th>Thinnest margin</th><th>Caught</th></tr></thead><tbody>
${cov.map((c) => `<tr><td><b>${c.id}</b> <span class="muted">${esc(reqTitle(c.id))}</span></td><td>${c.checks}</td><td class="${c.fails ? "FAIL" : ""}">${c.fails}</td><td>${c.inconclusive}</td><td>${f2(c.worst)} <span class="muted">${esc(c.worstOn)}</span></td><td>${esc(c.caught.join(", "))}</td></tr>`).join("")}
</tbody></table></div>
<h2>Test runs</h2><div class="tw"><table><thead><tr><th>#</th><th>Time</th><th>Software</th><th>Test</th><th>Tier</th><th>Verdict</th><th>Failed requirements</th><th>Rig s</th></tr></thead><tbody>
${runs.map((r) => `<tr><td>${r.n}</td><td>${esc(new Date(r.at).toLocaleTimeString())}</td><td>${esc(r.sutLabel)}</td><td>${esc(r.test)}</td><td>${tierName(r.env)}${r.env !== "sil" ? ` (seed ${r.seed})` : ""}</td><td class="${r.overall}">${r.overall}</td><td>${esc(r.verdicts.filter((v) => v.verdict === "FAIL").map((v) => `${v.id} ${f2(v.margin)}`).join(", "))}</td><td>${Math.round(r.rig_s || 0)}</td></tr>`).join("")}
</tbody></table></div>
<h2>Activity</h2><ol>${entries.map((e) => `<li>${esc(new Date(e.at).toLocaleTimeString())} · ${esc(describe(e))}</li>`).join("")}</ol>
<p class="muted">Generated by VoltTrace Studio · https://justkpd.github.io/volttrace/</p></main></body></html>`;
}
