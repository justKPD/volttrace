/* Small SVG chart kit: line charts with requirement limits and hover, a progress scatter, a Gantt. */

const NS = "http://www.w3.org/2000/svg";
const COLORS = ["var(--s1)", "var(--s2)", "var(--s3)"];

function el(tag, attrs = {}, parent) {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (parent) parent.appendChild(n);
  return n;
}

export function niceTicks(lo, hi, n = 4) {
  if (!(hi > lo)) hi = lo + 1;
  const raw = (hi - lo) / n;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) || raw;
  const out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) out.push(+v.toFixed(10));
  return out;
}

export function fmt(v) {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  const a = Math.abs(v);
  if (a >= 100 || Number.isInteger(v)) return String(Math.round(v));
  if (a >= 10) return v.toFixed(1);
  if (a >= 1) return v.toFixed(2);
  return v.toPrecision(2);
}

const tip = () => document.getElementById("tip");
export function showTip(e, html) {
  const t = tip();
  t.innerHTML = html;
  t.style.display = "block";
  const x = Math.min(e.clientX + 14, innerWidth - t.offsetWidth - 8);
  const y = Math.min(e.clientY + 14, innerHeight - t.offsetHeight - 8);
  t.style.left = x + "px";
  t.style.top = y + "px";
}
export function hideTip() {
  tip().style.display = "none";
}

/**
 * series: [{name, t:[], y:[]}]; limits: [{value, label}]; window: [t0, t1] | null; marker: t | null
 */
export function lineChart(host, { title, unit, series, limits = [], window = null, marker = null, height = 170 }) {
  const W = 560, H = height, L = 48, R = 12, T = 10, B = 24;
  const fig = document.createElement("figure");
  fig.className = "panel chart";
  const cap = document.createElement("figcaption");
  cap.innerHTML = `<b>${title}</b> <span class="unit">${unit || ""}</span>`;
  if (series.length > 1) {
    const lg = document.createElement("span");
    lg.className = "legend";
    lg.innerHTML = series
      .map((s, i) => `<span class="key"><i style="background:${COLORS[i]}"></i>${s.name}</span>`)
      .join("");
    cap.appendChild(lg);
  }
  fig.appendChild(cap);

  let t0 = window ? window[0] : Math.min(...series.map((s) => s.t[0]));
  let t1 = window ? window[1] : Math.max(...series.map((s) => s.t[s.t.length - 1]));
  if (!(t1 > t0)) t1 = t0 + 1;
  const clipped = series.map((s) => {
    const t = [], y = [];
    for (let i = 0; i < s.t.length; i++) {
      if (s.t[i] >= t0 && s.t[i] <= t1 && s.y[i] !== null) {
        t.push(s.t[i]);
        y.push(s.y[i]);
      }
    }
    return { ...s, t, y };
  });
  const vals = clipped.flatMap((s) => s.y).concat(limits.map((l) => l.value));
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (!isFinite(lo)) { lo = 0; hi = 1; }
  const span = hi - lo || Math.abs(hi) || 1;
  lo -= 0.08 * span;
  hi += 0.08 * span;
  const px = (t) => L + ((t - t0) / (t1 - t0)) * (W - L - R);
  const py = (v) => T + ((hi - v) / (hi - lo)) * (H - T - B);

  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, class: "svgchart", role: "img", "aria-label": title });
  for (const v of niceTicks(lo, hi)) {
    el("line", { class: "grid", x1: L, x2: W - R, y1: py(v), y2: py(v) }, svg);
    el("text", { class: "tick", x: L - 6, y: py(v) + 4, "text-anchor": "end" }, svg).textContent = fmt(v);
  }
  for (const v of niceTicks(t0, t1, 5)) {
    el("text", { class: "tick", x: px(v), y: H - 7, "text-anchor": "middle" }, svg).textContent = fmt(v) + " s";
  }
  el("line", { class: "axis", x1: L, x2: W - R, y1: H - B, y2: H - B }, svg);
  for (const l of limits) {
    el("line", { class: "limit", x1: L, x2: W - R, y1: py(l.value), y2: py(l.value) }, svg);
    el("text", { class: "limit-label", x: W - R - 4, y: py(l.value) - 4, "text-anchor": "end" }, svg).textContent = l.label;
  }
  if (marker !== null && marker >= t0 && marker <= t1) {
    el("line", { class: "violation", x1: px(marker), x2: px(marker), y1: T, y2: H - B }, svg);
    el("text", { class: "violation-label", x: px(marker) + 4, y: T + 10 }, svg).textContent = "first violation";
  }
  clipped.forEach((s, i) => {
    if (!s.t.length) return;
    el("polyline", {
      class: "series",
      style: `stroke:${COLORS[i]}`,
      points: s.t.map((t, k) => `${px(t).toFixed(1)},${py(s.y[k]).toFixed(1)}`).join(" "),
    }, svg);
  });
  const cross = el("line", { class: "cross", x1: 0, x2: 0, y1: T, y2: H - B, visibility: "hidden" }, svg);
  const hit = el("rect", { class: "hit", x: L, y: T, width: W - L - R, height: H - T - B }, svg);
  hit.addEventListener("mousemove", (e) => {
    const p = svg.createSVGPoint();
    p.x = e.clientX;
    p.y = e.clientY;
    const q = p.matrixTransform(svg.getScreenCTM().inverse());
    const tq = t0 + ((q.x - L) / (W - L - R)) * (t1 - t0);
    let rows = "", tt = null;
    clipped.forEach((s, i) => {
      if (!s.t.length) return;
      let b = 0, d = Infinity;
      for (let k = 0; k < s.t.length; k++) {
        const dd = Math.abs(s.t[k] - tq);
        if (dd < d) { d = dd; b = k; }
      }
      if (tt === null) tt = s.t[b];
      rows += `<div><i style="background:${COLORS[i]}"></i>${s.name}: <b>${fmt(s.y[b])}</b> ${unit || ""}</div>`;
    });
    cross.setAttribute("x1", px(tt));
    cross.setAttribute("x2", px(tt));
    cross.setAttribute("visibility", "visible");
    showTip(e, `<div>t = ${fmt(tt)} s</div>${rows}`);
  });
  hit.addEventListener("mouseleave", () => {
    cross.setAttribute("visibility", "hidden");
    hideTip();
  });
  fig.appendChild(svg);
  host.appendChild(fig);
  return fig;
}

/** Falsifier progress: one dot per simulation (its robustness), a best-so-far line, the zero line. */
export function progressChart(host, { samples, budget, title = "Search progress" }) {
  const W = 560, H = 190, L = 48, R = 12, T = 10, B = 26;
  host.innerHTML = "";
  const fig = document.createElement("figure");
  fig.className = "panel chart";
  fig.innerHTML = `<figcaption><b>${title}</b> <span class="unit">robustness per simulation (below 0 = requirement broken)</span>
    <span class="legend"><span class="key"><i style="background:var(--s1)"></i>each simulation</span>
    <span class="key"><i style="background:var(--s2)"></i>best so far</span></span></figcaption>`;
  const ys = samples.filter((v) => v !== null);
  let lo = Math.min(0, ...ys), hi = Math.max(0.5, ...ys);
  const span = hi - lo || 1;
  lo -= 0.08 * span;
  hi += 0.08 * span;
  const n = Math.max(budget, samples.length, 2);
  const px = (i) => L + ((i - 1) / (n - 1)) * (W - L - R);
  const py = (v) => T + ((hi - v) / (hi - lo)) * (H - T - B);
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, class: "svgchart" });
  for (const v of niceTicks(lo, hi)) {
    el("line", { class: "grid", x1: L, x2: W - R, y1: py(v), y2: py(v) }, svg);
    el("text", { class: "tick", x: L - 6, y: py(v) + 4, "text-anchor": "end" }, svg).textContent = fmt(v);
  }
  for (const v of niceTicks(1, n, 5)) {
    el("text", { class: "tick", x: px(v), y: H - 8, "text-anchor": "middle" }, svg).textContent = `#${Math.round(v)}`;
  }
  el("line", { class: "limit", x1: L, x2: W - R, y1: py(0), y2: py(0) }, svg);
  el("text", { class: "limit-label", x: W - R - 4, y: py(0) - 4, "text-anchor": "end" }, svg).textContent = "0 = violation";
  let best = Infinity;
  const bestPts = [];
  samples.forEach((v, k) => {
    if (v === null) return;
    best = Math.min(best, v);
    bestPts.push(`${px(k + 1).toFixed(1)},${py(best).toFixed(1)}`);
    const c = el("circle", { cx: px(k + 1), cy: py(v), r: 4, class: v < 0 ? "dot fail" : "dot" }, svg);
    c.addEventListener("mousemove", (e) => showTip(e, `simulation #${k + 1}: robustness <b>${fmt(v)}</b>`));
    c.addEventListener("mouseleave", hideTip);
  });
  el("polyline", { class: "series", style: "stroke:var(--s2)", points: bestPts.join(" ") }, svg);
  fig.appendChild(svg);
  host.appendChild(fig);
}

/** Gantt of a CI run: lanes = SiL workers + the HiL rig. */
export function gantt(host, { timeline, title, slots = 4, tMax = null }) {
  const W = 900, lane = 26, T = 8, L = 110, R = 12;
  const lanesSil = Array.from({ length: slots }, () => []);
  const free = Array(slots).fill(0);
  const hil = [];
  for (const e of [...timeline].sort((a, b) => a.start - b.start)) {
    if (e.env === "sil") {
      let i = free.findIndex((f) => f <= e.start + 1e-6);
      if (i < 0) i = free.indexOf(Math.min(...free));
      free[i] = e.end;
      lanesSil[i].push(e);
    } else hil.push(e);
  }
  const lanes = lanesSil.map((j, i) => [`SiL worker ${i + 1}`, j]).concat([["HiL rig (mock)", hil]]);
  const H = T + lane * lanes.length + 26;
  const end = tMax || Math.max(60, ...timeline.map((e) => e.end));
  const sx = (s) => L + (s / end) * (W - L - R);
  const fig = document.createElement("figure");
  fig.className = "panel chart";
  fig.innerHTML = `<figcaption><b>${title}</b><span class="legend">
    <span class="key"><i style="background:var(--s1)"></i>SiL job</span>
    <span class="key"><i style="background:var(--s2)"></i>HiL job</span>
    <span class="key"><i class="failkey"></i>found a failure</span></span></figcaption>`;
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, class: "svgchart" });
  for (const v of niceTicks(0, end / 60, 6)) {
    el("line", { class: "grid", x1: sx(v * 60), x2: sx(v * 60), y1: T, y2: H - 24 }, svg);
    el("text", { class: "tick", x: sx(v * 60), y: H - 8, "text-anchor": "middle" }, svg).textContent = fmt(v) + " min";
  }
  lanes.forEach(([name, jobs], li) => {
    const y = T + li * lane;
    el("text", { class: "cat", x: L - 8, y: y + 17, "text-anchor": "end" }, svg).textContent = name;
    for (const e of jobs) {
      const fail = e.new_failures && e.new_failures.length;
      const w = Math.max(sx(e.end) - sx(e.start) - 1.5, 2);
      const r = el("rect", {
        x: sx(e.start) + 0.5, y: y + 4, width: w, height: lane - 8, rx: 3,
        class: fail ? "job fail" : "job", style: `fill:${e.env === "sil" ? "var(--s1)" : "var(--s2)"}`,
      }, svg);
      const why = e.reason ? `<div>escalated: ${e.reason}</div>` : "";
      const res = fail ? `<div><b>FAILED</b> ${e.new_failures.join(", ")}</div>` : "<div>passed</div>";
      r.addEventListener("mousemove", (ev) =>
        showTip(ev, `<div><b>${e.test}</b> on ${e.env === "sil" ? "SiL" : "HiL"}</div><div>${(e.start / 60).toFixed(1)}–${(e.end / 60).toFixed(1)} min</div>${why}${res}`)
      );
      r.addEventListener("mouseleave", hideTip);
    }
  });
  fig.appendChild(svg);
  host.appendChild(fig);
}
