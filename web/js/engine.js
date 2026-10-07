/* One engine interface, two transports:
   - local Python behind `volttrace serve` (POST api/<method>), detected automatically;
   - otherwise Pyodide in a Web Worker (the static GitHub Pages deployment). */

export async function createEngine(onStatus) {
  try {
    const r = await fetch("api/info", { method: "POST", body: "{}" });
    if (r.ok) {
      const info = await r.json();
      onStatus({ ready: true, mode: "local Python server" });
      return {
        mode: "server",
        info,
        call: async (method, params) => {
          const res = await fetch("api/" + method, { method: "POST", body: JSON.stringify(params || {}) });
          const body = await res.json();
          if (!res.ok) throw new Error(body.error || res.statusText);
          return body;
        },
      };
    }
  } catch (_) {
    /* no server: fall through to the in-browser engine */
  }

  const worker = new Worker("js/worker.js");
  let seq = 0;
  const pending = new Map();
  let readyResolve, readyReject;
  const ready = new Promise((res, rej) => ((readyResolve = res), (readyReject = rej)));
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
