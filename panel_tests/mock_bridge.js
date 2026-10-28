"use strict";
// Mock STEVE parent for the panel tests. Records every postMessage the panel sends (window.__mock.log)
// and answers the bridge methods. Configured by window.__CFG (set by the test before load).
(function () {
  const FINAL = ["succeeded", "failed", "rejected", "cancelled", "expired"];
  const TOOLS = [
    { tool_id: "tl-flat-12", t: 13, h: 13, d: 13, name: "1/2\" flat endmill", type: "flat", dia_mm: 12.7, corner_r_mm: 0, flute_len_mm: 31.75, reach_mm: 50, holder: "BT30-ER32-70", rpm: 8000, feed_mm_min: 3429, plunge_mm_min: 1270 },
    { tool_id: "tl-bull-12", t: 5, h: 5, d: 5, name: "1/2\" bull, 0.03\" radius", type: "bull", dia_mm: 12.7, corner_r_mm: 0.762, flute_len_mm: 31.75, reach_mm: 45, holder: "BT30-ER32-70", rpm: 7500, feed_mm_min: 3429, plunge_mm_min: 1270 },
    { tool_id: "tl-ball-6", t: 20, h: 20, d: 20, name: "6 mm ball", type: "ball", dia_mm: 6, corner_r_mm: 3, flute_len_mm: 12, reach_mm: 30, holder: "BT30-ER16-60", rpm: 12000, feed_mm_min: 1800, plunge_mm_min: 600 },
    { tool_id: "tl-ball-3", t: 33, h: 33, d: 33, name: "3 mm ball", type: "ball", dia_mm: 3, corner_r_mm: 1.5, flute_len_mm: 6, reach_mm: 20, holder: "BT30-ER16-60", rpm: 15000, feed_mm_min: 1000, plunge_mm_min: 300 },
  ];
  const ALL = ["adaptive_rough", "slope_split_finish", "check_program", "model.measure", "tools.list", "tools.update", "job.get", "job.renumber", "job.setup"];
  const CFG = Object.assign({
    actions: ALL, allowed: {}, schema: "extended", manual: [], callErrors: {}, results: {}, checkJson: null,
    jobSetup: null, tools: TOOLS, pockets: 12, toolsUsed: ["tl-flat-12", "tl-ball-6"], theme: "light",
    doc: { id: "doc-42", kind: "part", revision: 7 }, width: 450, height: 2600, delay: 15,
    measure: { x: 254, y: 165, z: 55 }, failRun: {},
  }, window.__CFG || {});
  const M = window.__mock = { cfg: CFG, log: [], runs: {}, job: { renumber: {}, tools_used: CFG.toolsUsed.slice(), setup: CFG.jobSetup } };

  const frame = document.createElement("iframe");
  frame.id = "panel";
  frame.width = CFG.width;
  frame.height = CFG.height;
  frame.src = "../connector/panel/index.html";
  document.body.append(frame);
  M.frame = frame;

  function send(data) { M.log.push({ dir: "out", data: strip(data) }); frame.contentWindow.postMessage(data, "*"); }
  function strip(d) { try { return JSON.parse(JSON.stringify(d, (k, v) => (v instanceof Blob ? "[Blob]" : v))); } catch (e) { return String(d); } }
  function plainRun(r) { const c = Object.assign({}, r); return JSON.parse(JSON.stringify(c)); }
  M.push = function (id, patch) {
    const r = Object.assign(M.runs[id], patch);
    send({ steve: 1, event: "run", run: plainRun(r) });
  };
  M.pushRun = function (run) { M.runs[run.id] = run; send({ steve: 1, event: "run", run: plainRun(run) }); };
  M.pushContext = function (patch) {
    Object.assign(CFG, patch);
    send({ steve: 1, event: "context", context: { panel: "stevecam", connector: "stevecam", document: CFG.doc, theme: CFG.theme } });
  };
  M.pushEvent = function (name, data) { send({ steve: 1, event: "event", name, data }); };
  M.sent = function (method, action) {
    return M.log.filter((e) => e.dir === "in" && e.data && e.data.method === method && (!action || (e.data.params && e.data.params.action === action))).map((e) => e.data);
  };
  M.lastRun = function (action) { const s = M.sent("run", action); return s.length ? s[s.length - 1] : null; };
  M.pending = 0;
  const later = (fn, ms) => { M.pending++; setTimeout(() => { M.pending--; fn(); }, ms == null ? CFG.delay : ms); };

  function actions() {
    const cat = window.CATALOG.catalog(CFG.schema === "extended");
    const util = { "tools.list": {}, "tools.update": { tool: { type: "object" } }, "job.get": { document_id: { type: "string" } },
      "job.renumber": { document_id: {}, tool_id: {}, t: { type: "integer" } }, "job.setup": { document_id: {}, setup: { type: "object" } } };
    return CFG.actions.map((name, i) => ({
      id: "act-" + (i + 1), name, title: name, allowed: CFG.allowed[name] !== false, needs_confirmation: false,
      sends_open_document_on_click: true,
      inputs: CFG.schema === "empty" ? {} : { type: "object", properties: cat[name] || util[name] || {} },
    }));
  }
  const DEFAULT_RESULT = {
    adaptive_rough: { estimated_time_min: 0.82, cut_length_mm: 1253.9, zmap_gouges: { count: 0 }, rapid_collisions: { count: 0 },
      over_flute: { count: 0 }, leftover: { mean_mm: 0.42, p95_mm: 0.5, within_0p5mm_fraction: 0.98 } },
    slope_split_finish: { chain_time_min: 3.4, chain_cut_length_mm: 8120.5, probe_clcheck: { count: 0 },
      chain: { zmap_gouges: { count: 0 }, rapid_collisions: { count: 0 }, leftover: { mean_mm: 0.05, p95_mm: 0.11, within_0p5mm_fraction: 0.999 } } },
  };
  let nextRun = 0;
  function newRun(action, state) {
    const r = { id: "mock-run-" + (++nextRun), action, state, progress: null, message: "", result: null, error: null, files: [] };
    M.runs[r.id] = r;
    return r;
  }
  function finishLater(r, patch, ms) { later(() => M.push(r.id, Object.assign({ progress: 1 }, patch)), ms); }

  function onRun(id, p) {
    const action = p.action, inputs = p.inputs || {};
    if (CFG.callErrors[action]) return send({ steve: 1, id, error: CFG.callErrors[action] });
    if (!CFG.actions.includes(action)) return send({ steve: 1, id, error: { code: "action_not_found", message: "no " + action } });
    if (CFG.manual.includes(action)) {
      const r = newRun(action, CFG.firstState || "awaiting_confirmation");
      return send({ steve: 1, id, result: plainRun(r) });
    }
    if (action === "tools.list") { const r = newRun(action, "running"); send({ steve: 1, id, result: plainRun(r) }); return finishLater(r, { state: "succeeded", result: { tools: CFG.tools, pockets: CFG.pockets } }); }
    if (action === "job.get") {
      const r = newRun(action, "running"); send({ steve: 1, id, result: plainRun(r) });
      return finishLater(r, { state: "succeeded", result: Object.assign({ document_id: inputs.document_id }, JSON.parse(JSON.stringify(M.job))) });
    }
    if (action === "job.setup") {
      const r = newRun(action, "running"); send({ steve: 1, id, result: plainRun(r) });
      if (CFG.setupError) return finishLater(r, { state: "failed", error: CFG.setupError });
      M.job.setup = inputs.setup;
      return finishLater(r, { state: "succeeded", result: Object.assign({ document_id: inputs.document_id }, JSON.parse(JSON.stringify(M.job))) });
    }
    if (action === "job.renumber") {
      const r = newRun(action, "running"); send({ steve: 1, id, result: plainRun(r) });
      const jt = (t) => (M.job.renumber[t.tool_id] != null ? M.job.renumber[t.tool_id] : t.t);
      if (!Number.isInteger(inputs.t) || inputs.t < 1 || inputs.t > CFG.pockets) return finishLater(r, { state: "failed", error: { code: "out_of_range", message: "t out of range" } });
      const other = CFG.tools.find((t) => t.tool_id !== inputs.tool_id && jt(t) === inputs.t);
      if (other) return finishLater(r, { state: "failed", error: { code: "duplicate_t", message: "T" + inputs.t + " already used by " + other.tool_id } });
      M.job.renumber[inputs.tool_id] = inputs.t;
      return finishLater(r, { state: "succeeded", result: Object.assign({ document_id: inputs.document_id }, JSON.parse(JSON.stringify(M.job))) });
    }
    if (action === "model.measure") {
      const r = newRun(action, "received"); send({ steve: 1, id, result: plainRun(r) });
      const s = CFG.measure;
      return finishLater(r, { state: "succeeded", result: { size_mm: s, bbox_mm: { min: [-s.x / 2, -s.y / 2, 0], max: [s.x / 2, s.y / 2, s.z] } } });
    }
    // CAM runs, automatic
    const r = newRun(action, "awaiting_confirmation");
    send({ steve: 1, id, result: plainRun(r) });
    const fin = CFG.results[action] || { state: "succeeded", result: DEFAULT_RESULT[action] || {}, files: ["rough.nc", "check.json", "preview.png"] };
    later(() => {
      M.push(r.id, { state: "running", progress: 0.4, message: "Level 2/5" });
      finishLater(r, JSON.parse(JSON.stringify(fin)));
    });
  }
  function pngBlob() {
    return new Promise((resolve) => {
      const c = document.createElement("canvas");
      c.width = 160; c.height = 100;
      const g = c.getContext("2d");
      g.fillStyle = "#3a6ea5"; g.fillRect(0, 0, 160, 100);
      g.strokeStyle = "#ffd166"; g.strokeRect(20, 15, 120, 70);
      c.toBlob(resolve, "image/png");
    });
  }
  async function onFile(id, p) {
    const r = M.runs[p.id];
    if (!r) return send({ steve: 1, id, error: { code: "action_not_found", message: "no run" } });
    let blob;
    if (p.name === "preview.png") blob = await pngBlob();
    else if (p.name === "check.json") blob = new Blob([JSON.stringify(CFG.checkJson || {})], { type: "application/json" });
    else if (p.name === "view.bin" && CFG.viewBinBase64) blob = new Blob([Uint8Array.from(atob(CFG.viewBinBase64), (ch) => ch.charCodeAt(0))], { type: "application/octet-stream" });
    else if (p.name === "view.json" && CFG.viewJson) blob = new Blob([JSON.stringify(CFG.viewJson)], { type: "application/json" });
    else blob = new Blob(["%\nO1001\nM30\n%\n"], { type: "text/plain" });
    send({ steve: 1, id, result: { name: p.name, media_type: blob.type, bytes: blob.size, blob } });
  }

  window.addEventListener("message", (event) => {
    if (event.source !== frame.contentWindow) return;
    const m = event.data;
    M.log.push({ dir: "in", data: strip(m) });
    if (!m || m.steve !== 1) return;  // markers from tests
    const { id, method, params } = m;
    if (method === "context") send({ steve: 1, id, result: { panel: "stevecam", connector: "stevecam", document: CFG.doc, theme: CFG.theme } });
    else if (method === "events") send({ steve: 1, id, result: [{ name: "engine_state", data: { state: "idle", action: null, progress: null }, at: 1 }] });
    else if (method === "actions") send({ steve: 1, id, result: actions() });
    else if (method === "run") onRun(id, params || {});
    else if (method === "run.get") send(M.runs[params.id] ? { steve: 1, id, result: plainRun(M.runs[params.id]) } : { steve: 1, id, error: { code: "action_not_found", message: "no run" } });
    else if (method === "run.file") onFile(id, params || {});
    else if (method === "cancel") {
      send({ steve: 1, id, result: { ok: true } });
      const r = M.runs[params.id];
      if (r && !FINAL.includes(r.state)) later(() => M.push(r.id, { state: "cancelled", message: "Cancelled" }));
    } else send({ steve: 1, id, error: { code: "action_not_found", message: "unknown method " + method } });
  });
})();
