/* VoltTrace engine in a Web Worker: CPython (Pyodide) running the real volttrace package. */
const PYODIDE = "https://cdn.jsdelivr.net/pyodide/v0.27.8/full/";
importScripts(PYODIDE + "pyodide.js");

let py = null;
const ready = (async () => {
  const status = (text) => postMessage({ status: text });
  status("Loading the Python runtime (first visit ~10 MB, cached afterwards)…");
  py = await loadPyodide({ indexURL: PYODIDE });
  status("Loading numpy and PyYAML…");
  await py.loadPackage(["numpy", "pyyaml", "micropip"]);
  const base = new URL("../", self.location.href);
  const bundle = await (await fetch(new URL("data/bundle.json", base))).json();
  if (!bundle.wheel) throw new Error("this build has no engine wheel; run it with `volttrace serve` instead");
  status("Installing the VoltTrace engine…");
  py.globals.set("wheel_url", new URL(bundle.wheel, base).href);
  await py.runPythonAsync("import micropip\nawait micropip.install(wheel_url, deps=False)");
  py.globals.set("bundle_json", JSON.stringify(bundle));
  py.runPython(
    "import json\nfrom volttrace.webapi import Engine\nengine = Engine(json.loads(bundle_json))\ndel bundle_json"
  );
  status("ready");
})();

self.onmessage = async (e) => {
  const { id, method, params } = e.data;
  try {
    await ready;
    py.globals.set("call_params", JSON.stringify(params || {}));
    py.globals.set("js_progress", (s) => postMessage({ id, progress: JSON.parse(s) }));
    const withProgress = method === "falsify" || method === "orchestrate";
    const code =
      "json.dumps(engine." + method + "(json.loads(call_params)" +
      (withProgress ? ", lambda d: js_progress(json.dumps(d))" : "") + "))";
    const out = py.runPython(code);
    postMessage({ id, result: JSON.parse(out) });
  } catch (err) {
    const msg = String(err && err.message ? err.message : err);
    const last = msg.trim().split("\n").filter(Boolean).pop();
    postMessage({ id, error: last || msg });
  }
};

ready.catch((err) => postMessage({ status: "error", error: String(err && err.message ? err.message : err) }));
