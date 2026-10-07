/* Optional Claude mode for the assistant. Loaded only when the user switches to it and supplies their own API key.
   Claude gets the Studio's actions as tools and runs them in a manual tool loop; the UI updates as each runs. */

const SDK_URL = "https://cdn.jsdelivr.net/npm/@anthropic-ai/sdk@0.131.0/+esm";
const MODEL = "claude-opus-5-5";
const MAX_STEPS = 10;

let messages = [];
export function reset() {
  messages = [];
}

function tools(info) {
  const caseIds = info.cases.map((c) => c.id);
  const versionIds = info.versions.map((v) => v.id);
  const changeIds = info.versions.filter((v) => v.group === "seeded bug" || v.group === "clean change").map((v) => v.id);
  const obj = (properties, required = []) => ({ type: "object", properties, required, additionalProperties: false });
  const tier = { type: "string", enum: ["sil", "hil_mock"], description: "sil = software-in-the-loop (fast); hil_mock = the mock HiL tier (bus jitter, frame loss, sensor noise; slow)" };
  const seed = { type: "integer", minimum: 0, description: "noise seed (matters on hil_mock only)" };
  return [
    { name: "run_test", description: "Run one test case on the Test Bench and return verdicts and margins per requirement. Omitted fields keep the bench's current choice. The page shows the result live.",
      input_schema: obj({
        case: { type: "string", enum: caseIds }, software: { type: "string", enum: versionIds, description: "baseline = released software" },
        tier, seed, overlay_released: { type: "boolean", description: "also run the released software and overlay it in the plots" },
        params: obj({ soc: { type: "number", description: "state of charge 0.05-1.0" }, t_bat_c: { type: "number", description: "cell temperature degC" },
                      t_coolant_bat_c: { type: "number" }, v_kph: { type: "number", description: "start speed km/h" },
                      r_aging_factor: { type: "number", description: "pack resistance multiplier 1.0-3.0" } }),
      }) },
    { name: "replay_finding", description: "Replay one of the six findings on the build that still has the defect, with the released software overlaid.",
      input_schema: obj({ finding: { type: "string", enum: info.findings.map((f) => f.id) } }, ["finding"]) },
    { name: "falsify", description: "Search the scenario space for a counterexample (a scenario with negative margin) against a software version.",
      input_schema: obj({ template: { type: "string", enum: info.templates.map((t) => t.id) }, software: { type: "string", enum: versionIds },
        strategy: { type: "string", enum: ["random", "cem"] }, budget: { type: "integer", minimum: 5, maximum: 80 }, seed: { type: "integer", minimum: 0 } }) },
    { name: "open_counterexample", description: "Open the last falsifier result's worst scenario on the Test Bench and run it.", input_schema: obj({}) },
    { name: "run_ci", description: "Run one full CI cycle for a code change under a policy (A full, B static, C adaptive, D noise-aware). Slow in the browser: up to ~60 simulations.",
      input_schema: obj({ change: { type: "string", enum: changeIds }, policy: { type: "string", enum: ["A", "B", "C", "D"] }, seed: { type: "integer", minimum: 0 } }, ["change", "policy"]) },
    { name: "hunt_start", description: "Start a bug hunt: a random hidden change (buggy or clean) is loaded.", input_schema: obj({}) },
    { name: "hunt_run", description: "Run a test on the hidden change of the active bug hunt; failures new versus the released software are flagged.",
      input_schema: obj({ case: { type: "string", enum: caseIds }, tier, seed }) },
    { name: "hunt_reveal", description: "End the active bug hunt with a guess of which feature the change breaks (one of the candidates hunt_start returned).",
      input_schema: obj({ guess: { type: "string" } }, ["guess"]) },
    { name: "evaluate_stl", description: "Evaluate a Signal Temporal Logic formula on the most recent run, e.g. always(v_bus <= 812) or always(implies(t_bat >= 59, eventually(p_dis_lim_kw <= 240, 0, 1))).",
      input_schema: obj({ formula: { type: "string" } }, ["formula"]) },
    { name: "show_signals", description: "Choose which signals the Test Bench plots for the last run.",
      input_schema: obj({ signals: { type: "array", items: { type: "string", enum: Object.keys(info.channels) }, minItems: 1 } }, ["signals"]) },
    { name: "zoom", description: "Zoom the Test Bench plots: to the first violation, to a time window, or back to the whole run (no arguments).",
      input_schema: obj({ to_violation: { type: "boolean" }, from_s: { type: "number" }, to_s: { type: "number" } }) },
    { name: "open_page", description: "Navigate the Studio.", input_schema: obj({ page: { type: "string", enum: ["start", "bench", "hunt", "falsify", "ci", "requirements", "findings", "report"] } }, ["page"]) },
    { name: "session_summary", description: "Statistics and insights about everything the user has run in this session, and open the Session Report.", input_schema: obj({}) },
  ];
}

async function runTool(name, x, A) {
  switch (name) {
    case "run_test": return A.runTest({ case: x.case, sut: x.software, env: x.tier, seed: x.seed, overlay: x.overlay_released, params: x.params }, "Assistant (Claude)");
    case "replay_finding": return A.replayFinding(x.finding);
    case "falsify": return A.falsify({ template: x.template, sut: x.software, strategy: x.strategy, budget: x.budget, seed: x.seed });
    case "open_counterexample": {
      const r = A.state.falsify.result;
      if (!r) throw new Error("run the falsifier first");
      return A.runTest({ scenario: r.best.scenario, sut: r.spec.sut, env: "sil", seed: 0, overlay: true, window: null }, `Falsifier ${r.spec.template}`);
    }
    case "run_ci": return A.ci({ change: x.change, policy: x.policy, seed: x.seed });
    case "hunt_start": return A.huntStart();
    case "hunt_run": return A.huntRun({ case: x.case, env: x.tier, seed: x.seed });
    case "hunt_reveal": return A.huntReveal(x.guess);
    case "evaluate_stl": return A.stl(x.formula);
    case "show_signals": return A.showSignals(x.signals);
    case "zoom": return A.zoom(x.to_violation ? "violation" : x.from_s !== undefined && x.to_s !== undefined ? [x.from_s, x.to_s] : null);
    case "open_page": return A.go(x.page === "start" ? "" : x.page);
    case "session_summary": { const s = A.summary(); await A.go("report"); return s; }
    default: throw new Error(`unknown tool ${name}`);
  }
}

function system(A) {
  const info = A.info;
  return `You are the assistant inside VoltTrace Studio, a web app that validates a synthetic 800 V battery-electric energy-management ECU. A real validation engine (vehicle/battery/thermal plant, DBC-defined CAN bus, the ECU software, STL requirement checks, a falsifier and a CI orchestrator) runs in the user's browser. Your tools operate the app; the page updates live as each tool runs, so the user watches you work.

How to help:
- Act with the tools rather than describing what the user could click. Chain tools for multi-step requests.
- After acting, answer briefly (1-4 sentences): the verdict, which requirement broke and its margin, and what that means. Margins are scaled STL robustness: below 0 = violated, 0 to 0.1 = INCONCLUSIVE (too thin to trust SiL).
- Facts you can rely on: the system is synthetic and unaffiliated with any manufacturer; the HiL tier is a mock of HiL effects, not a rig. Do not invent results: report only what tools return.
- CI cycles and HiL runs are slow in the browser; mention that before starting several.

Test cases: ${info.cases.map((c) => `${c.id} (${c.title})`).join("; ")}.
Software versions: ${info.versions.map((v) => `${v.id} [${v.group}]: ${v.description}`).join(" | ")}.
Findings: ${info.findings.map((f) => `${f.id} ${f.title}`).join("; ")}.
Requirements: ${info.requirements.map((r) => `${r.id} ${r.title} [${r.stl}]`).join("; ")}.
Falsifier templates: ${info.templates.map((t) => `${t.id} ${t.title} (targets ${t.targets.join(", ")})`).join("; ")}.
Signals: ${Object.keys(info.channels).join(", ")}.
Current page: ${A.currentRoute() || "start"}. Bug hunt active: ${A.state.hunt.active ? `yes (candidates: ${A.state.hunt.candidates.join(", ")})` : "no"}.`;
}

/** One user turn: call Claude, run the tools it asks for, repeat until it ends its turn. */
export async function turn(text, A, ui) {
  const { default: Anthropic } = await import(SDK_URL);
  const client = new Anthropic({ apiKey: ui.key, dangerouslyAllowBrowser: true });
  messages.push({ role: "user", content: text });
  for (let step = 0; step < MAX_STEPS; step++) {
    let resp;
    try {
      resp = await client.beta.messages.create({
        model: MODEL,
        max_tokens: 16000,
        betas: ["server-side-fallback-2026-07-01"],
        fallbacks: "default",
        thinking: { type: "adaptive" },
        system: system(A),
        tools: tools(A.info),
        messages,
      });
    } catch (err) {
      messages.pop(); // let the user retry this turn cleanly
      const status = err && err.status ? ` (HTTP ${err.status})` : "";
      throw new Error(`Claude request failed${status}: ${err && err.message ? err.message : err}`);
    }
    messages.push({ role: "assistant", content: resp.content }); // keep every block, thinking included, unchanged
    for (const b of resp.content) {
      if (b.type === "text" && b.text.trim()) ui.text(b.text.trim());
      if (b.type === "fallback") ui.note(`<span class="muted small">${b.from?.model || "the primary model"} declined; ${b.to?.model || "a fallback model"} continued.</span>`);
    }
    if (resp.stop_reason === "refusal") {
      const why = resp.stop_details && resp.stop_details.explanation ? `: ${resp.stop_details.explanation}` : ".";
      ui.note(`Claude declined this request${why}`);
      return;
    }
    if (resp.stop_reason === "max_tokens") { ui.note("The response hit its length limit."); return; }
    if (resp.stop_reason !== "tool_use") return;
    const results = [];
    for (const b of resp.content.filter((x) => x.type === "tool_use")) {
      const input = b.input && typeof b.input === "object" ? b.input : {};
      ui.tool(b.name, input);
      try {
        const out = await runTool(b.name, input, A);
        results.push({ type: "tool_result", tool_use_id: b.id, content: JSON.stringify(out ?? {}) });
      } catch (err) {
        results.push({ type: "tool_result", tool_use_id: b.id, content: String(err && err.message ? err.message : err), is_error: true });
      }
    }
    messages.push({ role: "user", content: results });
  }
  ui.note("Stopped after 10 steps. Ask me to continue if needed.");
}
