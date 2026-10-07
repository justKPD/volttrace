/* "Ask VoltTrace": one chat panel that drives every feature of the Studio from plain commands
   ("replay F-002", "run TC-003 with M07 on HiL seed 2 then zoom to violation", "falsify M09 with cem").
   It runs entirely in the browser: no account, no key, no server. */

import { fmt } from "./charts.js";

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const sgn = (v) => (v === null || v === undefined ? "n/a" : (v >= 0 ? "+" : "") + fmt(v));
const tierName = (env) => (env === "sil" ? "SiL" : "HiL mock");

// ------------------------------------------------------------------ vocabulary
const PAGES = [
  [/\b(test )?bench\b/, "bench"], [/\b(bug )?hunt\b/, "hunt"], [/\bfalsifier\b/, "falsify"], [/\b(ci|orchestrator)\b/, "ci"],
  [/\brequirements?\b|\bspec(ification)?\b/, "requirements"], [/\bfindings?\b/, "findings"], [/\breport\b/, "report"],
  [/\b(start|home)( page)?\b/, ""],
];
const SIGNAL_ALIASES = [
  [/\bbus voltage\b|\bpack voltage\b|\bvoltage\b/, "v_bus"], [/\bbattery current\b|\bcurrent\b/, "i_bat"], [/\bspeed\b/, "v_kph"],
  [/\bcell temp(erature)?\b|\bbattery temp(erature)?\b/, "t_bat"], [/\binverter temp(erature)?\b/, "t_inv"],
  [/\btorque\b/, "torque_cmd"], [/\bbattery power\b/, "p_bat_kw"], [/\bregen power\b/, "p_regen_kw"],
  [/\bdischarge limit\b/, "p_dis_lim_kw"], [/\bcharge limit\b/, "p_chg_lim_kw"], [/\bdecel(eration)? error\b/, "decel_error"],
];
const CASE_KEYWORDS = [
  [/\bcold\b.*\b(aged|old)\b|\b(aged|old)\b.*\bcold\b/, "TC-003"], [/\bcold\b/, "TC-007"], [/\blaunch(es)?\b/, "TC-001"],
  [/\bbrak(e|ing)\b/, "TC-002"], [/\b(track|sprint|laps?|hot pack)\b/, "TC-004"],
  [/\b(frame (lost|loss)|lost frame|timeout|limp)\b/, "TC-005"], [/\b(sensor|open circuit|plausib\w*)\b/, "TC-006"],
];
const EXPLAIN = [
  [/\bmargin|robustness\b/, "<b>Margin</b> (STL robustness) is the signed distance to breaking a requirement, divided by a per-signal scale. +1 means one scale unit of headroom; below 0 means it broke. Two greens with +0.02 and +2.0 are very different evidence."],
  [/\binconclusive\b/, "<b>INCONCLUSIVE</b> means every check held, but at least one margin is below 0.1. A pass that thin on SiL is not trustworthy, because the HiL effects (bus jitter, noise) are bigger than that. The adaptive CI policy escalates such tests to HiL."],
  [/\b(vacuous|not exercised)\b/, "<b>NOT EXERCISED</b> (vacuous) means the requirement's trigger never fired: <code>implies(a, b)</code> where <code>a</code> was never true. The test proved nothing about it."],
  [/\bstl\b|\btemporal logic\b/, "<b>Signal Temporal Logic</b> writes requirements as formulas over signals: <code>always(v_bus &lt;= 815)</code>, <code>eventually(p_dis_lim_kw &lt;= 52, 0, 0.2)</code>, <code>implies(a, b)</code>. Each formula yields a verdict and a quantitative margin. Type one here and I will evaluate it on the last run."],
  [/\bhil\b|\bsil\b|\btier\b/, "<b>SiL</b> runs the ECU code against a model: seconds, four parallel slots. <b>HiL</b> runs it on a rig with real bus timing and sensors: 30 s bring-up, real time, one rig. Here HiL is a <b>mock</b> that adds CAN jitter (0–15 ms), 0.2 % frame loss and ADC noise; it is not a real rig."],
  [/\bpolic(y|ies)\b|\b(a|b|c|d) policy\b/, "CI policies: <b>A</b> runs every test on SiL and HiL. <b>B</b> sends tests with HiL-relevant requirements to HiL. <b>C</b> selects tests from the code diff and escalates on touched HiL requirements, thin margins or margin regressions. <b>D</b> is C plus noise-aware escalation with 3 HiL noise seeds. Try <i>ci M12 policy D</i>."],
  [/\bfalsif\w*\b/, "The <b>falsifier</b> searches the scenario space (SOC, ageing, temperatures, brake levels) for the input with the least margin. Below zero is a counterexample, which you can keep as a regression test. Try <i>falsify M09</i>."],
  [/\bseeded bugs?|mutants?\b/, "<b>Seeded bugs</b> M01–M14 are realistic mistakes (unit slips, wrong maps, missing debounce) built in as alternative software versions. They measure the test suite: a good suite fails on them. M11–M13 only show on HiL; M08 only in the vehicle."],
  [/\bfindings?\b|\bf-00\d\b/, "Six <b>findings</b> (F-001 to F-006) are defects the pipeline found in its own released code. Say <i>replay F-002</i> to watch one fail on the build that still has it."],
];

export function helpHtml() {
  return `I drive the Studio for you. Try:
  <ul>
    <li><code>replay F-002</code> · replays a finding on the build that has it</li>
    <li><code>run TC-003 with M07 on HiL seed 2</code> · any test, version, tier and seed</li>
    <li><code>run TC-002 with M09 soc 95% ageing 1.8 compare</code> · edit parameters, overlay the released build</li>
    <li><code>zoom to violation</code> · <code>zoom 4 to 6</code> · <code>show v_bus and i_bat</code></li>
    <li><code>falsify M09 with cem budget 20</code> · search for a counterexample</li>
    <li><code>ci M05 policy D</code> · run a full CI cycle</li>
    <li><code>start a hunt</code> · <code>try TC-005 on hil</code> · <code>guess voltage_guard</code></li>
    <li><code>always(v_bus &lt;= 812)</code> · evaluate any STL formula on the last run</li>
    <li><code>summary</code> · what your session shows · <code>download report</code></li>
    <li><code>run TC-003 with M07 then zoom to violation</code> · chain steps with <code>then</code></li>
    <li><code>explain inconclusive</code> · margin, STL, SiL vs HiL, policies</li>
  </ul>`;
}

// ------------------------------------------------------------------ the rule-based interpreter
function findVersion(l, info) {
  const m = l.match(/\b([mch])\s?0?(\d{1,2})\b/);
  if (m) {
    const pre = m[1].toUpperCase() + m[2].padStart(2, "0");
    const v = info.versions.find((x) => x.id.startsWith(pre));
    if (v) return v.id;
  }
  const full = info.versions.find((x) => x.id !== "baseline" && l.includes(x.id.toLowerCase()));
  if (full) return full.id;
  if (/\b(released|baseline|production|clean build)\b/.test(l)) return "baseline";
  return null;
}
function findCase(l, info, useKeywords) {
  const cx = l.match(/\bfz-?003-?cx(2)?\b/);
  if (cx) return cx[1] ? "FZ-003-CX2" : "FZ-003-CX";
  const m = l.match(/\btc\s?-?\s?0*(\d{1,2})\b/);
  if (m) {
    const id = "TC-" + m[1].padStart(3, "0");
    return info.cases.some((c) => c.id === id) ? id : id; // validated by the action
  }
  if (useKeywords) for (const [re, id] of CASE_KEYWORDS) if (re.test(l)) return id;
  return null;
}
const num = (l, re) => {
  const m = l.match(re);
  return m ? parseFloat(m[1]) : null;
};
function findParams(l0) {
  let l = l0;
  const p = {};
  const coolant = l.match(/coolant\s*(?:temp(?:erature)?)?\s*(?:=|of|at|to|:)?\s*(-?\d+(?:\.\d+)?)/);
  if (coolant) { p.t_coolant_bat_c = parseFloat(coolant[1]); l = l.replace(coolant[0], " "); }
  const soc = l.match(/\bsoc\s*(?:=|of|at|to|:)?\s*(\d+(?:\.\d+)?)\s*(%)?/);
  if (soc) { p.soc = parseFloat(soc[1]) / (soc[2] || parseFloat(soc[1]) > 1 ? 100 : 1); l = l.replace(soc[0], " "); }
  const temp = l.match(/(?:cell temp(?:erature)?|temp(?:erature)?|t_bat(?:_c)?)\s*(?:=|of|at|to|:)?\s*(-?\d+(?:\.\d+)?)/) ||
               l.match(/(-?\d+(?:\.\d+)?)\s*(?:°\s?c|degc|deg c|degrees?)\b/);
  if (temp) { p.t_bat_c = parseFloat(temp[1]); l = l.replace(temp[0], " "); }
  const speed = l.match(/(\d+(?:\.\d+)?)\s*km\/?h/) || l.match(/\b(?:speed|v_kph)\s*(?:=|of|at|to|:)?\s*(\d+(?:\.\d+)?)/);
  if (speed) { p.v_kph = parseFloat(speed[1]); l = l.replace(speed[0], " "); }
  const age = l.match(/\b(?:ageing|aging|aged|age|resistance|r_aging_factor)\s*(?:=|of|at|to|:)?\s*[x×]?\s*(\d+(?:\.\d+)?)/);
  if (age) p.r_aging_factor = parseFloat(age[1]);
  return p;
}
function findSignals(l, info) {
  const out = [];
  for (const ch of Object.keys(info.channels)) if (new RegExp(`\\b${ch}\\b`).test(l)) out.push(ch);
  if (!out.length) for (const [re, ch] of SIGNAL_ALIASES) if (re.test(l) && !out.includes(ch)) out.push(ch);
  return out;
}
function findGuess(l, candidates) {
  if (/\b(no bug|clean|nothing|not buggy|refactor)\b/.test(l)) return candidates.find((c) => c.startsWith("no bug"));
  const norm = l.replace(/[_-]/g, " ");
  return candidates.filter((c) => !c.startsWith("no bug")).sort((a, b) => b.length - a.length)
    .find((c) => norm.includes(c.replace(/_/g, " ")) || norm.includes(c.replace(/_/g, "")));
}

/** Turn a sentence into {act, args} (an action to run) or {reply} (an answer). */
export function interpret(text, A) {
  const info = A.info;
  const raw = text.trim();
  const l = raw.toLowerCase().replace(/\s+/g, " ");
  if (!l) return null;
  if (/^(help|\?|what can you do|commands|how do i use (this|you))/.test(l)) return { reply: helpHtml() };
  const stlAt = raw.search(/\b(always|eventually)\s*\(/i);
  if (stlAt >= 0) return { act: "stl", args: [raw.slice(stlAt).replace(/[.;]+$/, "")] };
  if (/\b(clear|reset|wipe)\b.*\b(session|report|log|history)\b/.test(l)) return { act: "clearSession", args: [] };
  if (/\bdownload\b.*\breport\b|\bexport\b.*\b(report|session)\b/.test(l)) return { act: "downloadReport", args: [] };
  if (/\b(summary|summari[sz]e|what did i do|my session|how am i doing|insights?|session report)\b|^report$|\bshow (me )?(the |my )?report\b|\bopen (the |my )?report\b/.test(l))
    return { act: "summary", args: [] };
  if (/^(what|explain|why|how|define|tell me about|what's|whats|meaning)\b/.test(l) || /\?$/.test(l)) {
    for (const [re, html] of EXPLAIN) if (re.test(l)) return { reply: html };
  }
  if (/\bcounterexample\b/.test(l) && /\b(open|bench|replay|run|show|load)\b/.test(l)) return { act: "openCounterexample", args: [] };

  const version = findVersion(l.replace(/\b(compare[sd]?( it)?( with| to)?|overlay( with)?|vs\.?|versus|against) (the )?released\b/g, " "), info);
  const explicitCase = findCase(l, info, false);
  const finding = l.match(/\bf\s?-?\s?0*([1-6])\b/);
  if (/^(go( to)?|open|take me( to)?|navigate( to)?|switch to|show me the)\b/.test(l) && !version && !explicitCase && !finding) {
    for (const [re, route] of PAGES) if (re.test(l)) return { act: "go", args: [route] };
  }
  if ((/^(what|explain|tell me about|describe|who|which)\b/.test(l) || /\?$/.test(l)) && !/\b(run|replay|try|simulate|falsify|start|reproduce|show)\b/.test(l)) {
    if (finding) {
      const f = info.findings.find((x) => x.id === `F-00${finding[1]}`);
      return { reply: `<b>${f.id} · ${esc(f.title)}</b> (found by ${esc(f.found_by)})<br>${esc(f.story)}<br><b>Fix:</b> ${esc(f.fix)}<br>Say <code>replay ${f.id}</code> to watch it fail.` };
    }
    if (version) {
      const v = info.versions.find((x) => x.id === version);
      return { reply: `<b>${esc(v.label)}</b> (${esc(v.group)}): ${esc(v.description)}<br>Say <code>run ${v.id.slice(0, 3)}</code> or <code>ci ${v.id.slice(0, 3)} policy C</code>.` };
    }
    if (explicitCase) {
      const c = info.cases.find((x) => x.id === explicitCase);
      if (c) return { reply: `<b>${c.id}</b>: ${esc(c.title)}. Checks ${c.requirements.join(", ")}. Say <code>run ${c.id}</code>.` };
    }
  }
  if (finding) return { act: "replayFinding", args: [`F-00${finding[1]}`] };

  const hunt = A.state.hunt;
  if (/\b(hunt|hidden change|mystery)\b/.test(l) && /\b(start|new|begin|another|play|again)\b/.test(l)) return { act: "huntStart", args: [] };
  if (/\b(reveal|guess|my verdict|answer|i think it|it breaks|it'?s)\b/.test(l) && (hunt.active || /\b(guess|reveal)\b/.test(l))) {
    if (!hunt.active) return { reply: "No hunt is running. Say <code>start a hunt</code> first." };
    const g = findGuess(l, hunt.candidates);
    if (!g) return { reply: `Which feature do you think it breaks? Say <code>guess …</code> with one of: ${hunt.candidates.map((c) => `<code>${esc(c)}</code>`).join(" ")}` };
    return { act: "huntReveal", args: [g] };
  }
  const env = /\b(hil|rig|hardware)\b/.test(l) ? "hil_mock" : /\bsil\b/.test(l) ? "sil" : null;
  const seed = num(l, /\bseeds?\s*(?:=|:|set)?\s*(\d+)/);
  if (hunt.active && !version && (/\b(hunt|hidden)\b/.test(l) || (A.currentRoute() === "hunt" && /\b(run|try|test|check)\b|\btc\b/.test(l)))) {
    return { act: "huntRun", args: [{ case: findCase(l, info, true), env, seed }] };
  }
  if (/\b(falsif\w*|counterexample|search)\b|\bfz-00\d\b/.test(l)) {
    const t = l.match(/\bfz-?0*(\d)\b/);
    let template = t ? `FZ-00${t[1]}` : null;
    if (!template) {
      if (/\b(regen|overvoltage|over-voltage|brak\w*|charg\w*|blend\w*)\b/.test(l)) template = "FZ-003";
      else if (/\b(undervoltage|under-voltage|voltage sag|cold|sag)\b/.test(l)) template = "FZ-001";
      else if (/\b(thermal|hot|temperature|overheat\w*|derat\w*)\b/.test(l)) template = "FZ-002";
    }
    return { act: "falsify", args: [{ template, sut: version, strategy: /\b(cem|cross[- ]?entropy|smart)\b/.test(l) ? "cem" : /\brandom\b/.test(l) ? "random" : null,
      budget: num(l, /\b(?:budget|sims?|simulations?)\s*(?:=|of|:)?\s*(\d+)/) ?? num(l, /\b(\d+)\s*(?:sims?|simulations?)\b/), seed }] };
  }
  if (/\b(ci|policy|policies|orchestrat\w*|pipeline)\b/.test(l)) {
    const pm = l.match(/\bpolicy\s*([abcd])\b/) || l.match(/\b([abcd])\s+policy\b/);
    let policy = pm ? pm[1].toUpperCase() : null;
    if (!policy) {
      if (/\bfull\b/.test(l)) policy = "A";
      else if (/\bstatic\b/.test(l)) policy = "B";
      else if (/\badaptive\b/.test(l)) policy = "C";
      else if (/\bnoise[- ]?aware\b/.test(l)) policy = "D";
    }
    return { act: "ci", args: [{ change: version, policy, seed }] };
  }
  if (/\b(zoom|window)\b/.test(l)) {
    if (/\bviolation|failure|fail\b/.test(l)) return { act: "zoom", args: ["violation"] };
    const r = l.match(/(-?\d+(?:\.\d+)?)\s*(?:s|sec|seconds)?\s*(?:to|-|–|and|\.\.)\s*(-?\d+(?:\.\d+)?)/);
    if (r) return { act: "zoom", args: [[parseFloat(r[1]), parseFloat(r[2])]] };
    return { act: "zoom", args: [null] };
  }
  if (/\b(whole run|reset zoom|unzoom)\b/.test(l)) return { act: "zoom", args: [null] };
  const signals = findSignals(l, info);
  if (/^(show|plot|display|add|graph|chart|draw)\b/.test(l) && signals.length && !explicitCase) return { act: "showSignals", args: [signals] };

  const params = findParams(l);
  const overlay = /\b(compare|overlay|vs\.? released|versus|against (the )?released)\b/.test(l) ? true : null;
  const runish = /\b(run|test|try|simulate|check|launch|execute|again|rerun|re-run)\b/.test(l);
  const kase = explicitCase || (runish ? findCase(l, info, true) : null);
  if (runish || kase || version || env || Object.keys(params).length) {
    return { act: "runTest", args: [{ case: kase, sut: version, env, seed, overlay, params }] };
  }
  for (const [route_re, route] of PAGES) if (route_re.test(l) && l.split(" ").length <= 3) return { act: "go", args: [route] };
  for (const [re, html] of EXPLAIN) if (re.test(l)) return { reply: html };
  return { reply: `I did not catch that. ${helpHtml()}` };
}

// ------------------------------------------------------------------ result formatting
function runHtml(r, extra = "") {
  const head = `<span class="chip ${r.overall}">${r.overall === "VACUOUS" ? "NOT EXERCISED" : r.overall}</span> <b>${esc(r.software)}</b>, ${tierName(r.tier)}${r.tier !== "sil" ? ` seed ${r.seed}` : ""}${extra}.`;
  const lines = [];
  if (r.failed.length) lines.push("Broke: " + r.failed.map((f) => `<b>${f.requirement}</b> (margin ${sgn(f.margin)}${f.first_violation_s !== null ? `, first at ${fmt(f.first_violation_s)} s` : ""}${f.new_vs_released ? ", new vs released" : ""})`).join("; ") + ".");
  if (r.inconclusive.length) lines.push("Too thin to trust: " + r.inconclusive.map((x) => `${x.requirement} ${sgn(x.margin)}`).join(", ") + ".");
  if (!r.failed.length && r.thinnest_pass) lines.push(`Thinnest pass: ${r.thinnest_pass.requirement} at ${sgn(r.thinnest_pass.margin)}.`);
  if (r.not_exercised.length) lines.push(`Not exercised: ${r.not_exercised.join(", ")}.`);
  lines.push(`<span class="muted">${fmt(r.simulated_s)} s simulated, rig cost ${fmt(r.rig_cost_s)} s.</span>`);
  return `${head}<br>${lines.join("<br>")}`;
}
function followUps(act, res, A) {
  if (act === "runTest" || act === "replayFinding") {
    const s = [];
    if (res.failed && res.failed.length) s.push("zoom to violation");
    if (res.tier === "sil") s.push("run it on HiL seed 1");
    s.push("summary");
    return s;
  }
  if (act === "falsify") return res.found ? ["open the counterexample on the bench", "summary"] : ["falsify with cem budget 40", "summary"];
  if (act === "ci") return ["ci policy D", "ci policy A", "summary"];
  if (act === "huntStart" || act === "huntRun") return A.state.hunt.active ? ["try TC-002 on SiL", "try TC-005 on HiL", "guess …"] : [];
  if (act === "huntReveal") return ["start another hunt", "summary"];
  return ["help"];
}
function resultHtml(act, res, A) {
  switch (act) {
    case "runTest": return runHtml(res);
    case "replayFinding": return `<b>${res.finding}</b> · ${esc(res.title)}<br>` + runHtml(res, ", released software overlaid in the plots");
    case "falsify": return res.found ?
      `<span class="chip FAIL">COUNTEREXAMPLE</span> ${res.template} broke <b>${esc(res.software)}</b> after ${res.simulations} simulations (${res.strategy}); worst margin ${sgn(res.worst_margin)}.` :
      `<span class="chip PASS">NONE FOUND</span> ${res.template} on <b>${esc(res.software)}</b>: no counterexample in ${res.simulations} simulations (${res.strategy}); closest ${sgn(res.worst_margin)}.`;
    case "ci": return `${res.detected ? '<span class="chip FAIL">RED BUILD</span>' : '<span class="chip PASS">GREEN BUILD</span>'} <b>${esc(res.change)}</b>, policy ${res.policy}: ` +
      (res.detected ? `caught in ${res.detected_in.join(", ")}` : res.buggy ? "<b>missed</b>: the change is buggy" : "correct, the change is clean") +
      `. ${res.sil_jobs} SiL jobs, ${res.hil_jobs} HiL jobs, ${fmt(res.hil_rig_minutes)} rig-min, verdict after ${fmt(res.verdict_after_min)} min.` +
      (Object.keys(res.escalations).length ? `<br>Escalated: ${Object.entries(res.escalations).map(([t, w]) => `${esc(t)} (${esc(w)})`).join("; ")}.` : "");
    case "huntStart": return `A hidden change is loaded. Run tests on it (<code>try TC-002</code>, <code>try TC-005 on hil</code>), then <code>guess</code> one of: ${res.candidates.map((c) => `<code>${esc(c)}</code>`).join(" ")}`;
    case "huntRun": return runHtml(res) +
      `<br>Rig time spent so far: ${fmt(res.rig_spent_total_s)} s over ${res.runs} runs.`;
    case "huntReveal": return `${res.correct ? '<span class="chip PASS">CORRECT</span>' : '<span class="chip FAIL">NOT QUITE</span>'} It was <code>${esc(res.change)}</code>: ${esc(res.description)} ` +
      (res.buggy ? `It touches ${res.features.join(", ")}.` : "A clean change.") + ` ${res.runs} runs, ${fmt(res.rig_seconds)} s rig time.`;
    case "stl": return `<span class="chip ${res.verdict}">${res.verdict}</span> <code>${esc(res.formula)}</code> on ${esc(res.trace)}: robustness ${sgn(res.robustness)}` +
      (res.first_violation_s !== null ? `, first violation at ${fmt(res.first_violation_s)} s` : "") + ".";
    case "showSignals": return `Showing ${res.showing.map((s) => `<code>${s}</code>`).join(", ")} on the Test Bench.`;
    case "zoom": return Array.isArray(res.window_s) ? `Zoomed to ${fmt(res.window_s[0])}–${fmt(res.window_s[1])} s.` : "Showing the whole run.";
    case "go": return `Opened ${esc(res.opened)}.`;
    case "clearSession": return "Session cleared. The report starts fresh.";
    case "downloadReport": return "Downloaded your session report as a self-contained HTML file.";
    case "summary": {
      const s = res;
      return `<b>Your session:</b> ${s.tests} test runs (${s.sil} SiL, ${s.hil} HiL), ${s.failedRuns} failed, ${Math.round(s.rigSeconds)} s rig time, ` +
        `${s.counterexamples}/${s.searches} searches found a counterexample, ${s.ciCycles} CI cycles, ${s.huntsCorrect}/${s.hunts} hunts solved.` +
        (s.insights.length ? `<ul>${s.insights.slice(0, 5).map((i) => `<li>${esc(i)}</li>`).join("")}</ul>` : "<br>Nothing recorded yet: run something!") +
        ` Full details on the <a href="#/report">Session Report</a>.`;
    }
    default: return esc(JSON.stringify(res));
  }
}

// ------------------------------------------------------------------ executing an interpreted command
export async function execute(cmd, A) {
  const [arg] = cmd.args;
  const clean = (o) => Object.fromEntries(Object.entries(o).filter(([, v]) => v !== null && v !== undefined && !(typeof v === "object" && !Array.isArray(v) && !Object.keys(v).length)));
  switch (cmd.act) {
    case "runTest": return A.runTest(clean(arg), "Assistant");
    case "falsify": return A.falsify(clean(arg));
    case "ci": return A.ci(clean(arg));
    case "huntRun": return A.huntRun(clean(arg));
    case "openCounterexample": {
      const r = A.state.falsify.result;
      if (!r) throw new Error("run the falsifier first");
      return A.runTest({ scenario: r.best.scenario, sut: r.spec.sut, env: "sil", seed: 0, overlay: true, window: null }, `Falsifier ${r.spec.template}`);
    }
    case "summary": {
      const s = A.summary();
      A.go("report");
      return s;
    }
    case "downloadReport": {
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([A.session.toHTML(A.session.log.entries, A.info)], { type: "text/html" }));
      a.download = "volttrace_session.html";
      a.click();
      return {};
    }
    default: return A[cmd.act](...cmd.args);
  }
}

// ------------------------------------------------------------------ the panel
const MENU = [
  ["Run a test", ["run TC-001", "run TC-003 with M07", "run TC-005 on HiL seed 2", "run TC-002 with M09 soc 95% ageing 1.8 compare"]],
  ["Findings", ["replay F-001", "replay F-002", "replay F-003", "replay F-004", "replay F-005", "replay F-006"]],
  ["Plots", ["zoom to violation", "zoom 4 to 6", "whole run", "show v_bus and i_bat"]],
  ["Falsifier", ["falsify M09", "falsify M09 with cem budget 40", "falsify released", "open the counterexample on the bench"]],
  ["CI", ["ci M05 policy C", "ci M12 policy D", "ci C01 policy A"]],
  ["Bug Hunt", ["start a hunt", "try TC-002 on SiL", "try TC-005 on HiL", "guess …"]],
  ["Requirements", ["always(v_bus <= 812)", "eventually(v_kph >= 100, 0, 5)", "open requirements"]],
  ["Report", ["summary", "download report", "open report"]],
  ["Explain", ["explain margin", "explain inconclusive", "explain SiL vs HiL", "explain policies"]],
];

export function mountAssistant(A) {
  try { localStorage.removeItem("volttrace.anthropicKey"); localStorage.removeItem("volttrace.assistant.mode"); } catch { /* storage blocked */ }
  const fab = document.createElement("button");
  fab.className = "ask-fab";
  fab.id = "askFab";
  fab.type = "button";
  fab.innerHTML = '<span aria-hidden="true">✦</span> Ask VoltTrace';
  const panel = document.createElement("section");
  panel.className = "ask";
  panel.id = "askPanel";
  panel.hidden = true;
  panel.setAttribute("aria-label", "VoltTrace assistant");
  panel.innerHTML = `
    <header><b>Ask VoltTrace</b>
      <button type="button" class="btn sm" id="askMenuBtn" aria-expanded="false">All features</button>
      <button type="button" class="btn sm" id="askClose" aria-label="Close">✕</button></header>
    <div class="ask-menu" id="askMenu" hidden>${MENU.map(([group, items]) => `<div class="grp"><b>${esc(group)}</b>
      <div class="row">${items.map((t) => `<button type="button" class="btn sm">${esc(t)}</button>`).join("")}</div></div>`).join("")}</div>
    <div class="ask-log" id="askLog" aria-live="polite"></div>
    <div class="ask-sugg" id="askSugg"></div>
    <form id="askForm" class="ask-form"><input id="askInput" type="text" autocomplete="off" placeholder="e.g. replay F-002, then zoom to violation">
      <button class="btn primary" type="submit" id="askSend">Send</button></form>
    <div class="ask-foot small muted">Chain steps with <code>then</code>. Everything runs in your browser.</div>`;
  document.body.append(fab, panel);
  const $ = (s) => panel.querySelector(s);
  const logBox = $("#askLog");
  let busyNow = false;

  const scroll = () => (logBox.scrollTop = logBox.scrollHeight);
  function bubble(who, html) {
    const d = document.createElement("div");
    d.className = "msg " + who;
    d.innerHTML = html;
    logBox.append(d);
    scroll();
    return d;
  }
  const pick = (t) => {
    if (t.endsWith("…")) { $("#askInput").value = t.replace("…", ""); $("#askInput").focus(); } else send(t);
  };
  function suggest(list) {
    $("#askSugg").innerHTML = list.map((s) => `<button type="button" class="btn sm">${esc(s)}</button>`).join("");
    $("#askSugg").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => pick(b.textContent)));
  }
  const menu = (on) => {
    $("#askMenu").hidden = !on;
    $("#askMenuBtn").setAttribute("aria-expanded", String(on));
    $("#askMenuBtn").classList.toggle("on", on);
  };
  $("#askMenuBtn").addEventListener("click", () => menu($("#askMenu").hidden));
  $("#askMenu").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => { menu(false); pick(b.textContent); }));
  const open = (on) => {
    panel.hidden = !on;
    fab.hidden = on;
    if (on) {
      if (!logBox.children.length) {
        bubble("bot", "Hi! I run everything in the Studio for you: tests, findings, plots, the falsifier, CI cycles, bug hunts, STL checks and your report. Type in plain words, tap <b>All features</b>, or chain steps: <i>run TC-003 with M07 then zoom to violation</i>.");
        suggest(["replay F-002", "run TC-003 with M07", "falsify M09", "ci M05 policy C", "start a hunt", "summary"]);
      }
      $("#askInput").focus();
    }
  };
  fab.addEventListener("click", () => open(true));
  $("#askClose").addEventListener("click", () => open(false));
  $("#askForm").addEventListener("submit", (e) => { e.preventDefault(); send($("#askInput").value); });

  async function step(text) {
    const pending = bubble("bot", '<span class="spinner"></span> Working…');
    try {
      const cmd = interpret(text, A);
      if (!cmd) { pending.remove(); return true; }
      if (cmd.reply) { pending.innerHTML = cmd.reply; suggest(["help", "replay F-002", "summary"]); return true; }
      const res = await execute(cmd, A);
      pending.innerHTML = resultHtml(cmd.act, res, A);
      suggest(followUps(cmd.act, res, A));
      return true;
    } catch (err) {
      pending.classList.add("err");
      pending.innerHTML = esc(err.message || String(err));
      return false;
    }
  }
  async function send(text) {
    text = String(text || "").trim();
    if (!text || busyNow) return;
    $("#askInput").value = "";
    bubble("me", esc(text));
    busyNow = true;
    $("#askSend").disabled = true;
    try {
      // "run TC-003 with M07 then zoom to violation": one step at a time, stop at the first error
      const steps = /\b(always|eventually)\s*\(/i.test(text) ? [text] : text.split(/\s*(?:,\s*|\b)(?:and )?then\b\s*/i).filter(Boolean);
      for (const s of steps) if (!(await step(s))) break;
    } finally {
      busyNow = false;
      $("#askSend").disabled = false;
      scroll();
    }
  }
  A.ask = (text) => { open(true); return send(text); };
}
