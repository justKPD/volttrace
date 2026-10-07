/* One engine interface, two transports:
   - local Python behind `volttrace serve` (POST api/<method>);
   - Pyodide in a Web Worker (the static GitHub Pages deployment). */

export async function createEngine(onStatus) {
  // data/runtime.json says where the engine lives: written as "browser" by `volttrace build-site`,
  // answered as "server" by `volttrace serve`. No probing request that a static host would reject.
  let runtime = { engine: "browser" };
  try {
    const r = await fetch("data/runtime.json", { cache: "no-store" });
    if (r.ok) runtime = await r.json();
  } catch (_) {
    /* missing file: assume the static deployment */
  }
  if (runtime.engine === "server") {
    const res = await fetch("api/info", { method: "POST", body: "{}" });
    const info = await res.json();
    onStatus({ ready: true, mode: "local Python server" });
    return {
      mode: "server",
      info,
      call: async (method, params) => {
        const r = await fetch("api/" + method, { method: "POST", body: JSON.stringify(params || {}) });
        const body = await r.json();
        if (!r.ok) throw new Error(body.error || r.statusText);
        return body;
      },
    };
  }

  const worker = new Worker("js/worker.js");
  let seq = 0;
  const pending = new Map();
  let readyResolve, readyReject;
  const ready = new Promise((res, rej) => ((readyResolve = res), (readyReject = rej)));
  const fail = (why) => {
    const msg = `${why} Your network may block cdn.jsdelivr.net. You can run it locally instead: pip install -e . && volttrace serve`;
    onStatus({ ready: false, error: msg });
    readyReject(new Error(msg));
  };
  worker.onerror = (e) => {
    e.preventDefault();
    fail("Could not load the Python runtime.");
  };
  const watchdog = setTimeout(() => fail("The Python runtime did not load within 3 minutes."), 180000);
  ready.then(() => clearTimeout(watchdog), () => clearTimeout(watchdog));
  worker.onmessage = (e) => {
    const m = e.data;
    if (m.status !== undefined) {
      if (m.status === "ready") readyResolve();
      else if (m.status === "error") readyReject(new Error(m.error));
      onStatus({ ready: m.status === "ready", mode: "in your browser (Pyodide)", text: m.status, error: m.error });
      return;
    }
    const p = pending.get(m.id);
    if (!p) return;
    if (m.progress) return p.onProgress && p.onProgress(m.progress);
    pending.delete(m.id);
    m.error ? p.reject(new Error(m.error)) : p.resolve(m.result);
  };
  const call = (method, params, onProgress) =>
    new Promise((resolve, reject) => {
      const id = ++seq;
      pending.set(id, { resolve, reject, onProgress });
      worker.postMessage({ id, method, params });
    });
  await ready;
  const info = await call("info", {});
  return { mode: "browser", info, call };
}
