"use strict";
/* SteveCAM panel for STEVE (SYIL X7).
   Bridge rules (steve_panel_bridge.md): all data comes from STEVE through postMessage to the
   parent frame. No network, no storage, no cookies, no popups, no navigation. */
(function () {
  const FX = window.SteveCAMFields;
  const RP = window.SteveCAMReport;
  const FINAL = new Set(["succeeded", "failed", "rejected", "cancelled", "expired"]);
  const ACTION = { rough: "adaptive_rough", finish: "slope_split_finish", check: "check_program", measure: "model.measure" };
  const NAME = { rough: "roughing", finish: "the slope-split finish", measure: "measuring" };
  const ENGINE_ACTION = {
    adaptive_rough: "Rough", slope_split_finish: "Finish", check_program: "Check", "model.measure": "Measure",
    "tools.list": "Tools", "tools.update": "Tools", "job.get": "Job", "job.renumber": "Job", "job.setup": "Job",
  };
  const STATE_TEXT = {
    awaiting_confirmation: "Waiting for you to confirm in STEVE",
    pending: "Waiting to start", queued: "Waiting to start", created: "Waiting to start", waiting: "Waiting to start",
    received: "SteveCAM got it", running: "Working", succeeded: "Done", failed: "Failed",
    rejected: "Not accepted", cancelled: "Cancelled", expired: "Expired: nobody answered in time",
  };
  const PLAIN = {
    caller_not_allowed: "This panel isn't allowed to run that. Allow it for panels in STEVE's connector settings.",
    rate_limited: "Too many runs in the last minute. Wait a moment, then try again.",
    action_not_found: "SteveCAM doesn't offer this right now. Check that SteveCAM is running and up to date.",
    input_out_of_range: "A value is outside what SteveCAM accepts.",
    input_missing: "A needed value is missing.",
    input_unknown: "SteveCAM didn't recognise one of the values sent.",
  };

  const $ = (id) => document.getElementById(id);
  function el(tag, attrs, ...kids) {
    const e = document.createElement(tag);
    for (const k in attrs || {}) {
      const v = attrs[k];
      if (v === undefined || v === null || v === false) continue;
      if (k === "class") e.className = v;
      else if (k === "text") e.textContent = v;
      else e.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids) if (kid !== null && kid !== undefined) e.append(kid);
    return e;
  }
  const isObj = (o) => o !== null && typeof o === "object" && !Array.isArray(o);

  // ------------------------------------------------------------- bridge --
  let seq = 0;
  const waiting = new Map();
  function call(method, params) {
    const id = ++seq;
    window.parent.postMessage({ steve: 1, id, method, params: params || {} }, "*");
    return new Promise((resolve, reject) => waiting.set(id, { resolve, reject }));
  }
  window.addEventListener("message", (event) => {
    const m = event.data;
    if (event.source !== window.parent || !m || m.steve !== 1) return;
    if (m.id !== undefined && waiting.has(m.id)) {
      const w = waiting.get(m.id);
      waiting.delete(m.id);
      if (m.error) w.reject(m.error); else w.resolve(m.result);
    } else if (m.event === "event") {
      onEvent(m.name, m.data);
    } else if (m.event === "run") {
      noteRun(m.run);
    } else if (m.event === "context" && m.context) {
      applyContext(m.context);
    }
  });

  // --------------------------------------------------------------- runs --
  const runs = new Map();       // run id -> latest run seen
  const watchers = new Map();   // run id -> callback
  function noteRun(run) {
    if (!run || run.id === undefined) return;
    const prev = runs.get(run.id);
    if (prev && FINAL.has(prev.state) && !FINAL.has(run.state)) return;  // never go back from a final state
    const merged = Object.assign({}, prev, run);
    runs.set(run.id, merged);
    const w = watchers.get(run.id);
    if (w) {
      if (FINAL.has(merged.state)) watchers.delete(run.id);
      w(merged);
    } else if (merged.action === ACTION.check || (S.act[ACTION.check] && merged.action === S.act[ACTION.check].id)) {
      showCheckRun(merged);
    }
  }
  function watchRun(run, fn) {
    watchers.set(run.id, fn);
    if (runs.has(run.id)) {          // a push got here before the answer: it is newer
      const latest = runs.get(run.id);
      if (FINAL.has(latest.state)) watchers.delete(run.id);
      fn(latest);
    } else {
      noteRun(run);
    }
  }
  // Posts the run at once (synchronously), so a click handler can call it.
  function startRun(action, inputs, note, onUpdate) {
    let p;
    try {
      p = call("run", { action, inputs, note });
    } catch (e) {
      onUpdate({ state: "error", callError: { code: "post_failed", message: String(e && e.message || e) } });
      return;
    }
    p.then((run) => {
      if (!run || run.id === undefined) onUpdate({ state: "error", callError: { code: "no_run", message: "STEVE did not start the run." } });
      else watchRun(run, onUpdate);
    }, (err) => onUpdate({ state: "error", callError: err || {} }));
  }
  function runToEnd(action, inputs) {
    return new Promise((resolve, reject) => {
      startRun(action, inputs, "SteveCAM panel", (run) => {
        if (run.state === "error") reject(run.callError);
        else if (FINAL.has(run.state)) resolve(run);
      });
    });
  }
  function errText(err) {
    if (!err) return "Something went wrong.";
    if (PLAIN[err.code] && ["caller_not_allowed", "rate_limited", "action_not_found"].includes(err.code)) return PLAIN[err.code];
    return err.message || PLAIN[err.code] || (err.code ? "Error: " + err.code : "Something went wrong.");
  }

  // -------------------------------------------------------------- state --
  const S = {
    units: "inch", doc: null, act: {}, actionsLoaded: false, loaded: false,
    vals: {}, tools: null, toolsMode: false, toolsLoading: false, pockets: null, job: null,
    pick: { rough: "", finish: "", rest: "", chain: "" },
    busy: { rough: false, finish: false, measure: false },
    measured: null, setupTouched: false, savedSetup: null, saving: false,
    results: { rough: null, finish: null }, checkRuns: [],
  };
  const F = {};       // "form.name" -> {spec, form, wrap, lbl, ctl, err}
  const cards = {};   // form -> run card elements

  function present(name) { const a = S.act[name]; return !!a; }
  function allowed(name) { const a = S.act[name]; return !!a && a.allowed !== false; }
  function schemaProps(name) {
    const a = S.act[name];
    if (!a) return null;
    const inp = a.inputs;
    if (Array.isArray(inp)) {
      const o = {};
      for (const x of inp) if (x && x.name) o[x.name] = x;
      return Object.keys(o).length ? o : null;
    }
    if (!isObj(inp)) return null;
    if (isObj(inp.properties)) return Object.keys(inp.properties).length ? inp.properties : null;
    const keys = Object.keys(inp);
    if (keys.length && keys.every((k) => isObj(inp[k]))) return inp;
    return null;
  }
  function enumOf(name, field) {
    const p = schemaProps(name);
    const f = p && p[field];
    return f && Array.isArray(f.enum) ? f.enum : null;
  }
  function hasInput(name, field) { const p = schemaProps(name); return !!(p && p[field]); }
  function limits(form, spec) {
    const p = ACTION[form] ? schemaProps(ACTION[form]) : null;
    const f = p && p[spec.name];
    return {
      // STEVE gets length/feed minimums as INCH numbers (catalog.published_catalog:
      // it checks raw values before units are known); the field's own mm minimum
      // stays exact, so take the stricter of the two
      min: f && typeof f.minimum === "number"
        ? (FX.isLen(spec) && typeof spec.min === "number" ? Math.max(f.minimum, spec.min) : f.minimum)
        : spec.min,
      max: f && typeof f.maximum === "number" ? f.maximum : spec.max,
    };
  }
  function originFor(form) { return hasInput(ACTION[form], "origin"); }
  function originShown() { return originFor("rough") || originFor("finish"); }
  function hasJobSetup() { return allowed("job.get") && allowed("job.setup"); }

  // ------------------------------------------------------------- fields --
  function viewOf(key, lim) {
    const f = F[key];
    return FX.view(S.vals[key], f.spec, S.units, lim || f.spec);
  }
  function labelText(spec) {
    const u = FX.unitText(spec, S.units);
    return spec.label + (u ? " (" + u + ")" : "");
  }
  function makeField(form, spec, extra) {
    const key = form + "." + spec.name;
    S.vals[key] = FX.initial(spec);
    const id = "f-" + form + "-" + spec.name;
    let ctl;
    if (spec.kind === "enum") {
      ctl = el("select", { id, name: spec.name });
      for (const [v, t] of spec.options) ctl.append(el("option", { value: v, text: t }));
      ctl.addEventListener("change", () => { S.vals[key] = { v: ctl.value }; changed(key); });
    } else {
      ctl = el("input", {
        id, name: spec.name, type: "text", autocomplete: "off", spellcheck: "false",
        inputmode: spec.kind === "int" ? "numeric" : "decimal", placeholder: spec.placeholder,
      });
      ctl.addEventListener("input", () => { S.vals[key] = FX.parse(spec, ctl.value, S.units); changed(key); });
      ctl.addEventListener("blur", () => paint(key));
    }
    const lbl = el("span", { class: "lbl" });
    const err = el("span", { class: "err", id: "err-" + form + "-" + spec.name, "aria-live": "polite" });
    const note = el("span", { class: "note" });
    const wrap = el("label", { class: "fld", id: "w-" + form + "-" + spec.name, for: id }, lbl, ctl, note, err);
    F[key] = { spec, form, wrap, lbl, ctl, err, note, extra: extra || {} };
    return wrap;
  }
  function crField(key) { return /(^|\.)(rough_)?corner_radius$/.test(key) ? key.replace(/corner_radius$/, "tool_type") : null; }
  const BLANK_AXIS = { stock_x: "x", stock_y: "y", stock_top: "z" };

  function paint(key) {
    const f = F[key];
    if (!f) return;
    f.lbl.textContent = labelText(f.spec);
    const st = S.vals[key];
    if (f.spec.kind === "enum") { f.ctl.value = st.v; return; }
    let text = viewOf(key).text, disabled = false, note = "", title = "";
    const tt = crField(key);
    if (tt && F[tt] && S.vals[tt].v === "flat") { text = "0"; disabled = true; title = "A flat tool has no corner radius."; }
    if (f.form === "setup" && BLANK_AXIS[f.spec.name]) {
      const sv = stockView(f.spec.name, f.spec);
      if (sv.computed) {
        disabled = true;
        text = sv.error ? "" : sv.text;
        note = sv.error && !freshMeasure() ? "needs a measure" : "from blank";
        title = "Worked out from the blank size.";
      }
    }
    if (f.spec.name === "tool_number" || f.spec.name === "rest_tool_number") f.wrap.hidden = S.toolsMode || S.toolsLoading;
    if (document.activeElement !== f.ctl || disabled !== f.ctl.disabled) f.ctl.value = text;
    f.ctl.disabled = disabled;
    f.ctl.title = title;
    f.note.textContent = note;
  }
  function paintAll() {
    $("units").value = S.units;
    for (const key in F) paint(key);
    paintSetupInfo();
    for (const form of ["rough", "finish"]) paintResults(form);
    for (const c of S.checkRuns) paintCheckRun(c);
  }
  function changed(key) {
    const f = F[key];
    if (f.form === "setup" || f.form === "blank") S.setupTouched = true;
    clearFieldError(key);
    for (const k in F) {
      if (k === key) continue;
      const g = F[k];
      if (crField(k) || (g.form === "setup" && BLANK_AXIS[g.spec.name])) paint(k);
    }
    paintSetupInfo();
  }
  function clearFieldError(key) {
    const f = F[key];
    if (!f) return;
    f.err.textContent = "";
    f.wrap.classList.remove("bad");
  }

  // -------------------------------------------------------- measure/blank --
  function freshMeasure() {
    const m = S.measured;
    if (!m || !S.doc) return null;
    if (m.docId !== S.doc.id || m.revision !== S.doc.revision) return null;
    if (m.orientation !== S.vals["setup.orientation"].v) return null;
    return m;
  }
  // The blank is used only when all three sizes are filled (job.setup takes {x,y,z} or null).
  function blankFilled() { return ["x", "y", "z"].filter((a) => S.vals["blank.blank_" + a] && !S.vals["blank.blank_" + a].empty).length; }
  function hasBlank(axis) {
    if (!present(ACTION.measure)) return false;
    const st = S.vals["blank.blank_" + axis];
    return !!st && !st.empty && blankFilled() === 3;
  }
  // The stock extra the run will use, for stock_x / stock_y / stock_top (from the blank when typed).
  function stockView(name, spec, lim) {
    const axis = BLANK_AXIS[name];
    if (axis && hasBlank(axis)) {
      const b = viewOf("blank.blank_" + axis);
      if (b.send === null || Number.isNaN(b.send)) return { computed: true, error: "Blank " + axis.toUpperCase() + " is not a number." };
      const m = freshMeasure();
      if (!m) return { computed: true, error: "The blank size needs the model size: press Measure model." };
      const bmm = FX.serverMm(F["blank.blank_" + axis].spec, b.send, S.units);
      const model = m.size_mm[axis];
      let mm;
      if (axis === "z") {
        // the stock block equals the blank: top = blank Z - model Z - extra on bottom
        const bot = viewOf("setup.stock_bottom");
        if (bot.send === null || Number.isNaN(bot.send)) return { computed: true, error: "Blank Z needs the extra on bottom filled in." };
        const botMm = FX.serverMm(F["setup.stock_bottom"].spec, bot.send, S.units);
        mm = bmm - model - botMm;
        if (mm < 0) {
          return Object.assign(FX.view({ mm, src: null }, spec, S.units, lim || spec), { computed: true,
            error: "Blank Z: the blank is shorter than the model plus the bottom allowance (" + fmtLen(model + botMm) + ")." });
        }
      } else {
        mm = (bmm - model) / 2;
      }
      const v = FX.view({ mm, src: null }, spec, S.units, lim || spec);
      if (mm < 0) {
        return Object.assign(v, { computed: true, error: "Blank " + axis.toUpperCase() + " is smaller than the model (" +
          fmtLen(model) + ")." });
      }
      return Object.assign(v, { computed: true });
    }
    return viewOf("setup." + name, lim);
  }
  function fmtLen(mm, fixed) {
    const u = S.units;
    const v = u === "inch" ? mm / FX.MM_PER_IN : mm;
    const d = fixed ? (u === "inch" ? 3 : 2) : FX.DECIMALS[u];
    const s = fixed ? v.toFixed(d) : FX.numText(FX.round(v, d));
    return s.replace(/^-/, "−") + " " + (u === "inch" ? "in" : "mm");
  }
  function numOnly(mm) {
    const u = S.units;
    return (u === "inch" ? mm / FX.MM_PER_IN : mm).toFixed(u === "inch" ? 3 : 2);
  }
  function mmOfSetup(name) {
    const spec = F["setup." + name].spec;
    const v = stockView(name, spec);
    if (v.error || v.send === null || v.send === undefined || Number.isNaN(v.send)) return v.send === null ? null : NaN;
    return FX.serverMm(spec, v.send, S.units);
  }
  function stockBox() {
    const m = freshMeasure();
    if (!m) return null;
    const xy = mmOfSetup("stock_xy");
    let sx = mmOfSetup("stock_x"), sy = mmOfSetup("stock_y");
    if (sx === null) sx = xy;
    if (sy === null) sy = xy;
    const top = mmOfSetup("stock_top"), bottom = mmOfSetup("stock_bottom");
    const vals = [sx, sy, top, bottom];
    if (vals.some((v) => v === null || Number.isNaN(v))) return null;
    return { x: m.size_mm.x + 2 * sx, y: m.size_mm.y + 2 * sy, z: m.size_mm.z + top + bottom };
  }
  function orientLabel() {
    const sel = F["setup.orientation"].ctl;
    const o = sel.options[sel.selectedIndex];
    return o ? o.textContent.replace(/^./, (c) => c.toLowerCase()) : "as modeled";
  }
  function setupSentence(form) {
    const origin = originFor(form) ? S.vals["setup.origin"].v : "model_origin";
    const box = stockBox();
    const unit = S.units === "inch" ? "in" : "mm";
    const orient = " Orientation: " + orientLabel() + ".";
    if (box) {
      const size = "Blank " + numOnly(box.x) + " × " + numOnly(box.y) + " × " + numOnly(box.z) + " " + unit;
      const xy = "X ±" + numOnly(box.x / 2) + ", Y ±" + numOnly(box.y / 2);
      if (origin === "stock_bottom_centre") {
        return size + ", origin at the stock bottom centre (Z0 = stock bottom): " + xy + ", Z 0 to " + numOnly(box.z) + "." + orient;
      }
      if (origin === "stock_top_centre") {
        return size + ", origin at the stock top centre (Z0 = stock top): " + xy + ", Z −" + numOnly(box.z) + " to 0." + orient;
      }
      return size + ", placed as drawn in the model (the model's own origin)." + orient;
    }
    if (["x", "y", "z"].some(hasBlank)) {
      return "Blank size typed: press Measure model so SteveCAM can fit the model in it." + orient;
    }
    const t = (name) => {
      const v = viewOf("setup." + name);
      return v.send === null ? null : Number.isNaN(v.send) ? "?" : v.text + " " + unit;
    };
    const sx = t("stock_x"), sy = t("stock_y");
    const side = sx || sy ? "X " + (sx || t("stock_xy")) + " and Y " + (sy || t("stock_xy")) : t("stock_xy");
    let s = "Blank: the model plus " + side + " per side, " + t("stock_top") + " on top and " + t("stock_bottom") + " on bottom";
    if (origin === "stock_bottom_centre") s += ", origin at the stock bottom centre (Z0 = stock bottom).";
    else if (origin === "stock_top_centre") s += ", origin at the stock top centre (Z0 = stock top).";
    else s += ", placed as drawn in the model (the model's own origin).";
    return s + orient;
  }
  function paintSetupInfo() {
    const n = blankFilled();
    $("blank-partial").hidden = !present(ACTION.measure) || n === 0 || n === 3;
    const m = S.measured;
    const ms = $("model-size");
    if (m) {
      const fresh = freshMeasure();
      let why = "";
      if (!fresh) {
        why = !S.doc || m.docId !== S.doc.id || m.revision !== S.doc.revision ? " (old: the model changed, measure again)"
          : " (old: orientation changed, measure again)";
      }
      ms.textContent = "Model: " + numOnly(m.size_mm.x) + " × " + numOnly(m.size_mm.y) + " × " +
        numOnly(m.size_mm.z) + " " + (S.units === "inch" ? "in" : "mm") + why;
      ms.hidden = false;
    } else {
      ms.hidden = true;
    }
    const box = stockBox();
    const bs = $("block-size");
    if (box) {
      bs.textContent = "Blank (model + extras): " + numOnly(box.x) + " × " + numOnly(box.y) + " × " +
        numOnly(box.z) + " " + (S.units === "inch" ? "in" : "mm");
      bs.hidden = false;
    } else {
      bs.hidden = true;
    }
    for (const form of ["rough", "finish"]) if (cards[form]) cards[form].sentence.textContent = setupSentence(form);
  }

  // -------------------------------------------------------------- tools --
  function toolById(id) { return (S.tools || []).find((t) => String(t.tool_id) === String(id)) || null; }
  function jobT(tool) {
    const r = S.job && isObj(S.job.renumber) ? S.job.renumber[tool.tool_id] : undefined;
    return r !== undefined && r !== null ? Number(r) : tool.t;
  }
  function toolName(tool) {
    if (tool.name) return String(tool.name);
    const d = typeof tool.dia_mm === "number" ? fmtLen(tool.dia_mm) : "";
    return (d + " " + (tool.type || "tool")).trim();
  }
  const PICKERS = {
    rough: { label: "Tool", types: ["flat", "bull"], none: "Auto (from tool table)", form: "rough", p: "", cut: true },
    finish: { label: "Ball", types: ["ball"], none: "Auto (from tool table)", form: "finish", p: "", cut: true },
    rest: { label: "Rest ball", types: ["ball"], none: "No rest pass", form: "finish", p: "", rest: true },
    chain: { label: "Fill sizes from", types: ["flat", "bull"], none: "Type the sizes", form: "finish", p: "rough_" },
  };
  const pickEls = {};
  function makePicker(kind) {
    const cfg = PICKERS[kind];
    const sel = el("select", { id: "pick-" + kind });
    sel.addEventListener("change", () => {
      S.pick[kind] = sel.value;
      const tool = toolById(sel.value);
      if (tool && !cfg.rest) fillFromTool(kind, tool);
      paintSetupInfo();
    });
    const wrap = el("label", { class: "fld wide", id: "w-pick-" + kind, for: "pick-" + kind, hidden: true },
      el("span", { class: "lbl", text: cfg.label }), sel);
    pickEls[kind] = { sel, wrap };
    return wrap;
  }
  function refreshPickers() {
    for (const kind in PICKERS) {
      const { sel, wrap } = pickEls[kind];
      wrap.hidden = !(S.toolsMode || S.toolsLoading);
      sel.replaceChildren();
      if (S.toolsLoading) {
        sel.append(el("option", { value: "", text: "Loading tools…" }));
        sel.disabled = true;
        continue;
      }
      sel.disabled = false;
      sel.append(el("option", { value: "", text: PICKERS[kind].none }));
      for (const t of (S.tools || []).filter((x) => PICKERS[kind].types.includes(x.type))) {
        sel.append(el("option", { value: String(t.tool_id), text: "T" + jobT(t) + " · " + toolName(t) }));
      }
      if (!toolById(S.pick[kind])) S.pick[kind] = "";
      sel.value = S.pick[kind];
    }
    for (const key in F) if (/\.(rest_)?tool_number$/.test(key)) paint(key);
  }
  function fillFromTool(kind, tool) {
    const cfg = PICKERS[kind];
    const set = (name, st) => {
      const key = cfg.form + "." + cfg.p + name;
      if (!F[key]) return;
      S.vals[key] = st;
      clearFieldError(key);
    };
    const mm = (name, v) => { if (typeof v === "number" && Number.isFinite(v)) set(name, FX.fromMm(v)); };
    if (tool.type === "flat" || tool.type === "bull") set("tool_type", { v: tool.type });
    mm("tool_diameter", tool.dia_mm);
    if (tool.type === "bull") mm("corner_radius", tool.corner_r_mm);
    mm("flute_length", tool.flute_len_mm);
    if (cfg.cut && cfg.p === "") {
      if (typeof tool.rpm === "number") set("rpm", { v: Math.round(tool.rpm) });
      mm("feed", tool.feed_mm_min);
    }
    for (const key in F) if (F[key].form === cfg.form) paint(key);
  }
  async function loadTools() {
    S.toolsLoading = true;
    refreshPickers();
    try {
      const run = await runToEnd("tools.list", {});
      if (run.state !== "succeeded" || !isObj(run.result) || !Array.isArray(run.result.tools)) {
        throw run.error || { message: "The tool table didn't load (" + (STATE_TEXT[run.state] || run.state) + ")." };
      }
      S.tools = run.result.tools.filter(isObj);
      S.pockets = typeof run.result.pockets === "number" ? run.result.pockets : null;
      S.toolsMode = true;
    } catch (e) {
      S.tools = null;
      S.toolsMode = false;
      setNotice("Couldn't load the tool table, so type tool numbers by hand. " + errText(e));
    }
    S.toolsLoading = false;
    refreshPickers();
    renderJob();
  }

  // ---------------------------------------------------------------- job --
  let jobLoading = false;
  async function loadJob() {
    if (!allowed("job.get") || !S.doc) { renderJob(); return; }
    if (jobLoading) return;
    jobLoading = true;
    const docId = S.doc.id;
    try {
      const run = await runToEnd("job.get", { document_id: docId });
      if (!S.doc || S.doc.id !== docId) return;
      if (run.state === "succeeded" && isObj(run.result)) {
        S.job = run.result;
        if (hasJobSetup()) {
          if (isObj(S.job.setup) && !S.setupTouched) {
            prefill(S.job.setup);
            S.savedSetup = JSON.stringify(setupObject());
          }
        }
      }
    } catch (e) {
      /* the job section stays hidden; runs still work */
    } finally {
      jobLoading = false;
    }
    refreshPickers();
    renderJob();
  }
  function renderJob() {
    const box = $("job-tools");
    const show = S.toolsMode && !!S.job && allowed("job.renumber") && !!S.doc;
    box.hidden = !show;
    if (!show) return;
    const list = $("job-list");
    list.replaceChildren();
    const used = Array.isArray(S.job.tools_used) ? S.job.tools_used : [];
    if (!used.length) {
      list.append(el("p", { class: "muted small", text: "No tools in this job yet. They show here after a Rough or Finish run." }));
      return;
    }
    for (const id of used) {
      const tool = toolById(id) || { tool_id: id, t: null, name: String(id) };
      const safe = String(id).replace(/[^\w-]/g, "_");
      const input = el("input", {
        id: "jobt-" + safe, type: "text", inputmode: "numeric", autocomplete: "off",
        "aria-label": "T number for " + toolName(tool), value: jobT(tool) == null ? "" : String(jobT(tool)),
      });
      const err = el("span", { class: "err", id: "jobt-err-" + safe, "aria-live": "polite" });
      const ok = el("span", { class: "ok", id: "jobt-ok-" + safe });
      input.addEventListener("change", () => renumber(tool, input, err, ok));
      input.addEventListener("keydown", (e) => { if (e.key === "Enter") input.blur(); });
      list.append(el("div", { class: "job-row" },
        el("label", { for: "jobt-" + safe, text: toolName(tool) }), el("span", { class: "tcell" }, input), err, ok));
    }
  }
  function renumber(tool, input, err, ok) {
    err.textContent = "";
    ok.textContent = "";
    const max = S.pockets || 999;
    const raw = input.value.trim().replace(/^T/i, "");
    const t = Number(raw);
    if (raw === "" || !Number.isInteger(t) || t < 1 || t > max) {
      err.textContent = "Use a whole number from 1 to " + max + (S.pockets ? " (the machine has " + max + " pockets)." : ".");
      return;
    }
    if (t === jobT(tool)) return;
    if (!S.doc) return;
    input.disabled = true;
    ok.textContent = "Saving…";
    runToEnd("job.renumber", { document_id: S.doc.id, tool_id: tool.tool_id, t }).then((run) => {
      input.disabled = false;
      ok.textContent = "";
      const e = run.error || (isObj(run.result) && isObj(run.result.error) ? run.result.error : null);
      if (run.state === "succeeded" && !e) {
        if (isObj(run.result) && (run.result.renumber || run.result.tools_used)) S.job = Object.assign({}, S.job, run.result);
        else S.job = Object.assign({}, S.job, { renumber: Object.assign({}, S.job.renumber, { [tool.tool_id]: t }) });
        refreshPickers();
        renderJob();
        const okEl = document.getElementById("jobt-ok-" + String(tool.tool_id).replace(/[^\w-]/g, "_"));
        if (okEl) okEl.textContent = "Now T" + t + " in every program for this job.";
      } else {
        err.textContent = renumberError(e, t, tool) || ("Couldn't change it: " + (STATE_TEXT[run.state] || run.state) + ".");
        input.value = jobT(tool) == null ? "" : String(jobT(tool));
      }
    }, (callErr) => {
      input.disabled = false;
      ok.textContent = "";
      err.textContent = renumberError(callErr, t, tool) || errText(callErr);
      input.value = jobT(tool) == null ? "" : String(jobT(tool));
    });
  }
  function renumberError(e, t, tool) {
    if (!e) return null;
    if (e.code === "duplicate_t") {
      const other = (S.tools || []).find((x) => x.tool_id !== tool.tool_id && jobT(x) === t);
      return "T" + t + " is already used by " + (other ? toolName(other) : "another tool") + ". Pick a free number.";
    }
    if (e.code === "out_of_range") {
      return "T" + t + " isn't a pocket on this machine. Use 1 to " + (S.pockets || "the pocket count") + ".";
    }
    return e.message ? String(e.message) : null;
  }

  // -------------------------------------------------------------- setup --
  const SETUP_LEN = ["stock_xy", "stock_x", "stock_y", "stock_top", "stock_bottom", "floor_z"];
  function setupObject() {
    const mmOf = (key) => {
      const f = F[key];
      const v = FX.view(S.vals[key], f.spec, S.units);
      if (v.send === null || typeof v.send !== "number" || Number.isNaN(v.send)) return null;
      return FX.round(FX.serverMm(f.spec, v.send, S.units), 6);
    };
    const o = { orientation: S.vals["setup.orientation"].v, units: S.units };
    if (originShown()) o.origin = S.vals["setup.origin"].v;
    for (const n of SETUP_LEN) o[n] = mmOf("setup." + n);
    const blank = { x: mmOf("blank.blank_x"), y: mmOf("blank.blank_y"), z: mmOf("blank.blank_z") };
    o.blank = ["x", "y", "z"].every((a) => typeof blank[a] === "number" && blank[a] > 0) ? blank : null;
    return o;
  }
  function savedState(mm) {
    if (S.units === "inch") return FX.fromUnit(Number((mm / FX.MM_PER_IN).toFixed(6)), "inch");
    return FX.fromMm(mm);
  }
  function prefill(s) {
    if (s.units === "inch" || s.units === "mm") S.units = s.units;
    const hasOpt = (key, v) => [...F[key].ctl.options].some((o) => o.value === v);
    if (s.orientation && hasOpt("setup.orientation", s.orientation)) S.vals["setup.orientation"] = { v: s.orientation };
    if (s.origin && hasOpt("setup.origin", s.origin)) S.vals["setup.origin"] = { v: s.origin };
    for (const n of SETUP_LEN) {
      if (!(n in s)) continue;
      const key = "setup." + n;
      if (typeof s[n] === "number" && Number.isFinite(s[n])) S.vals[key] = savedState(s[n]);
      else if (s[n] === null && F[key].spec.optional) S.vals[key] = { empty: true };
    }
    for (const a of ["x", "y", "z"]) {
      const v = isObj(s.blank) ? s.blank[a] : null;
      S.vals["blank.blank_" + a] = typeof v === "number" && Number.isFinite(v) ? savedState(v) : { empty: true };
    }
    paintAll();
  }
  function saveSetup(force) {
    if (!hasJobSetup() || !S.doc) return;
    const obj = setupObject();
    const json = JSON.stringify(obj);
    if (!force && json === S.savedSetup) return;
    const prev = S.savedSetup;
    S.savedSetup = json;
    S.saving = true;
    $("save-state").textContent = "Saving…";
    $("save-setup").disabled = true;
    const docId = S.doc.id;
    runToEnd("job.setup", { document_id: docId, setup: obj }).then((run) => {
      S.saving = false;
      $("save-setup").disabled = !S.doc;
      if (run.state === "succeeded") {
        if (isObj(run.result) && S.doc && S.doc.id === docId) S.job = Object.assign({}, S.job, run.result);
        $("save-state").textContent = "Setup saved for this part.";
      } else {
        S.savedSetup = prev === json ? null : prev;
        $("save-state").textContent = "Couldn't save the setup: " + errText(run.error);
        if (run.error && run.error.field) markServerField(null, run.error);
      }
    }, (e) => {
      S.saving = false;
      $("save-setup").disabled = !S.doc;
      S.savedSetup = null;
      $("save-state").textContent = "Couldn't save the setup: " + errText(e);
      if (e && e.field) markServerField(null, e);
    });
  }

  // ------------------------------------------------------- collect/send --
  // Builds the exact inputs for a run, in the selected unit. Pure apart from reading state.
  function collect(form) {
    const action = ACTION[form];
    const props = schemaProps(action);
    const u = S.units;
    const inputs = {};
    const errors = [];
    inputs.model = { document_id: S.doc.id, revision: S.doc.revision };
    if (props && props.document_id) inputs.document_id = S.doc.id;
    const orient = S.vals["setup.orientation"].v;
    const oe = enumOf(action, "orientation");
    if (oe && !oe.includes(orient)) errors.push({ key: "setup.orientation", msg: "This orientation isn't offered for " + NAME[form] + "." });
    inputs.orientation = orient;
    if (originFor(form)) inputs.origin = S.vals["setup.origin"].v;
    inputs.units = u;
    for (const n of SETUP_LEN) {
      const key = "setup." + n, spec = F[key].spec, lim = limits(form, spec);
      const v = stockView(n, spec, lim);
      const errKey = v.computed ? "blank.blank_" + BLANK_AXIS[n] : key;  // blank errors go on the blank field
      if (v.error) { errors.push({ key: errKey, msg: v.error }); continue; }
      const label = v.computed ? Object.assign({}, spec, { label: spec.label + " (from blank " + BLANK_AXIS[n].toUpperCase() + ")" }) : spec;
      const e = FX.check(label, v, u, lim);
      if (e) errors.push({ key: errKey, msg: e });
      else if (v.send !== null) inputs[n] = v.send;
    }
    for (const spec of FX.FORMS[form]) {
      const key = form + "." + spec.name;
      if ((spec.name === "tool_number" || spec.name === "rest_tool_number") && S.toolsMode) {
        const tool = toolById(S.pick[spec.name === "tool_number" ? form : "rest"]);
        if (tool && jobT(tool) != null) inputs[spec.name] = jobT(tool);
        continue;
      }
      const tt = crField(key);
      if (tt && S.vals[tt].v === "flat") { inputs[spec.name] = 0; continue; }
      const lim = limits(form, spec);
      const v = viewOf(key, lim);
      const e = FX.check(spec, v, u, lim);
      if (e) errors.push({ key, msg: e });
      else if (v.send !== null) inputs[spec.name] = v.send;
    }
    for (const p of form === "finish" ? ["rough_"] : [""]) {
      if (inputs[p + "tool_type"] !== "bull") continue;
      const cr = inputs[p + "corner_radius"], dia = inputs[p + "tool_diameter"];
      if (typeof cr !== "number" || typeof dia !== "number") continue;
      const crMm = FX.serverMm({ kind: "len" }, cr, u), diaMm = FX.serverMm({ kind: "len" }, dia, u);
      if (!(crMm > 0 && crMm < diaMm / 2)) {
        errors.push({ key: form + "." + p + "corner_radius",
          msg: "Corner radius must be more than 0 and less than half the tool dia (" + fmtLen(diaMm / 2) + "). For no radius pick Flat." });
      }
    }
    if (props) for (const k of Object.keys(inputs)) if (!(k in props)) delete inputs[k];
    return { inputs, errors };
  }
  function clearErrors(form) {
    for (const key in F) if (F[key].form === form || F[key].form === "setup" || F[key].form === "blank") clearFieldError(key);
    cards[form].errors.replaceChildren();
  }
  function showErrors(form, errors) {
    const ul = cards[form].errors;
    ul.replaceChildren();
    const listed = new Set();
    for (const e of errors) {
      const f = F[e.key];
      if (f) { f.err.textContent = e.msg; f.wrap.classList.add("bad"); }
      if (!listed.has(e.msg)) ul.append(el("li", { text: e.msg }));
      listed.add(e.msg);
    }
    if (errors.length && F[errors[0].key] && !F[errors[0].key].ctl.disabled) F[errors[0].key].ctl.focus();
  }

  function canRun(form) {
    return S.actionsLoaded && allowed(ACTION[form]) && !!S.doc && !S.busy[form];
  }
  function updateButtons() {
    for (const form of ["rough", "finish"]) {
      const c = cards[form];
      if (!c) continue;
      c.btn.disabled = !canRun(form);
      let reason = "";
      if (!S.actionsLoaded) reason = "Loading…";
      else if (!present(ACTION[form])) reason = "SteveCAM doesn't offer this.";
      else if (!allowed(ACTION[form])) reason = "Not allowed from this panel. Allow it for panels in STEVE's connector settings.";
      else if (!S.doc) reason = "Open the part in STEVE first.";
      c.reason.textContent = reason;
    }
    const mb = $("measure-btn");
    mb.disabled = !S.actionsLoaded || !allowed(ACTION.measure) || !S.doc || S.busy.measure;
    if (S.actionsLoaded && present(ACTION.measure) && !allowed(ACTION.measure)) $("measure-state").textContent = "Not allowed from this panel.";
    $("save-setup").disabled = S.saving || !S.doc;
  }
  function setBusy(form, on) {
    S.busy[form] = on;
    updateButtons();
  }

  function onRunClick(form) {
    if (!canRun(form)) return;
    clearErrors(form);
    const { inputs, errors } = collect(form);
    if (errors.length) { showErrors(form, errors); return; }
    setBusy(form, true);
    resetCard(form);
    // Start the run right here in the click handler, with context().document: no await or timer before it.
    startRun(ACTION[form], inputs, "SteveCAM panel: " + NAME[form], (run) => showRunState(form, run));
    S.setupTouched = true;
    saveSetup(false);  // after the run is on its way
  }

  // ---------------------------------------------------------- run cards --
  function makeCard(form) {
    const state = el("span", { class: "run-state", id: form + "-state" });
    const cancel = el("button", { type: "button", class: "cancel", id: form + "-cancel", text: "Cancel", hidden: true });
    const prog = el("progress", { id: form + "-progress", max: "1" });
    const msg = el("div", { class: "run-msg", id: form + "-msg" });
    const err = el("div", { class: "run-err", id: form + "-err", hidden: true });
    const results = el("div", { id: form + "-results" });
    const preview = el("img", { class: "run-preview", id: form + "-preview", alt: "Toolpath preview", hidden: true });
    const root = el("div", { class: "run", id: form + "-run", hidden: true },
      el("div", { class: "run-head" }, state, cancel), prog, msg, err, results, preview);
    const sentence = el("p", { class: "setup-line", id: form + "-setup-line" });
    const errors = el("ul", { class: "errors", id: form + "-errors", role: "alert" });
    const reason = el("p", { class: "reason", id: form + "-reason" });
    const btn = el("button", { type: "button", class: "primary", id: form + "-btn", disabled: true,
      text: form === "rough" ? "Make rough program" : "Make finish programs" });
    btn.addEventListener("click", () => onRunClick(form));
    cancel.addEventListener("click", () => {
      const id = cards[form].runId;
      if (id === undefined) return;
      cancel.disabled = true;
      cancel.textContent = "Cancelling…";
      call("cancel", { id }).catch((e) => {
        cancel.disabled = false;
        cancel.textContent = "Cancel";
        msg.textContent = "Couldn't cancel: " + errText(e);
      });
    });
    cards[form] = { root, state, cancel, prog, msg, err, results, preview, sentence, errors, reason, btn, runId: undefined, shown: undefined, url: null };
    return [sentence, errors, reason, btn, root];
  }
  function resetCard(form) {
    const c = cards[form];
    c.root.hidden = false;
    c.runId = undefined;
    c.shown = undefined;
    c.state.textContent = "Starting…";
    c.state.dataset.state = "starting";
    c.msg.textContent = "";
    c.err.hidden = true;
    c.err.replaceChildren();
    c.results.replaceChildren();
    c.preview.hidden = true;
    if (c.url) { URL.revokeObjectURL(c.url); c.url = null; }
    c.prog.hidden = false;
    c.prog.removeAttribute("value");
    c.cancel.hidden = true;
    S.results[form] = null;
  }
  function showError(c, form, e, isCall) {
    c.err.hidden = false;
    c.err.replaceChildren();
    const text = isCall ? errText(e) : (e.message || PLAIN[e.code] || "The run failed.");
    c.err.append(el("div", { text }));
    if (e.next_step) c.err.append(el("div", { class: "next", text: "Next: " + e.next_step }));
    if (e.code) c.err.append(el("div", { class: "muted small", text: "Code: " + e.code }));
    if (e.field && form) markServerField(form, e);
  }
  // Server error fields look like "tool_diameter", "inputs.tool_diameter" or "setup.stock_xy" / "setup.blank.x".
  function markServerField(form, e) {
    const name = String(e.field).replace(/^(setup|inputs)\./, "");
    const b = /^blank(?:\.([xyz]))?$/.exec(name);
    if (b) {
      for (const a of b[1] ? [b[1]] : ["x", "y", "z"]) {
        const f = F["blank.blank_" + a];
        f.err.textContent = e.message || "Check the blank size.";
        f.wrap.classList.add("bad");
      }
      return;
    }
    const key = [form ? form + "." + name : null, "setup." + name].find((k) => k && F[k]);
    if (!key) return;
    const f = F[key];
    const range = FX.rangeText(f.spec, limits(form || "setup", f.spec), S.units);
    let text = range ? "Allowed: " + range + "." : "";
    if (!text && e.allowed != null) text = "Allowed: " + (Array.isArray(e.allowed) ? e.allowed.join(", ") : isObj(e.allowed) ? JSON.stringify(e.allowed) : e.allowed);
    f.err.textContent = text || (e.message || "Check this value.");
    f.wrap.classList.add("bad");
  }
  function showRunState(form, run) {
    const c = cards[form];
    c.root.hidden = false;
    if (run.state === "error") {
      c.state.textContent = "Not started";
      c.state.dataset.state = "error";
      c.prog.hidden = true;
      c.cancel.hidden = true;
      showError(c, form, run.callError || {}, true);
      setBusy(form, false);
      return;
    }
    c.runId = run.id;
    const active = !FINAL.has(run.state);
    c.state.textContent = STATE_TEXT[run.state] || String(run.state || "").replace(/_/g, " ");
    c.state.dataset.state = run.state;
    c.prog.hidden = !active;
    if (typeof run.progress === "number") c.prog.value = Math.max(0, Math.min(1, run.progress));
    else c.prog.removeAttribute("value");
    c.msg.textContent = active || run.state !== "succeeded" ? run.message || "" : "";
    c.cancel.hidden = !active;
    if (active) { c.cancel.disabled = false; c.cancel.textContent = "Cancel"; }
    if (!active) setBusy(form, false);
    if (run.error) showError(c, form, run.error, false);
    if (FINAL.has(run.state) && c.shown !== run.id && (run.state === "succeeded" || run.result)) {
      c.shown = run.id;
      showResults(form, run);
      if (run.state === "succeeded" && S.toolsMode) loadJob();
    }
  }
  function fileNames(files) {
    if (!Array.isArray(files)) return [];
    return files.map((f) => (typeof f === "string" ? f : f && f.name)).filter(Boolean).map(String);
  }
  function blobText(b) {
    if (b && typeof b.text === "function") return b.text();
    return new Promise((resolve, reject) => {
      const r = new FileReader();
      r.onload = () => resolve(String(r.result));
      r.onerror = () => reject(r.error);
      r.readAsText(b);
    });
  }
  async function fetchCheck(run, files) {
    if (!files.includes("check.json")) return { check: null };
    try {
      const f = await call("run.file", { id: run.id, name: "check.json" });
      return { check: JSON.parse(await blobText(f.blob)) };
    } catch (e) {
      return { check: null, checkErr: "Couldn't read check.json: " + (e && (e.message || e.code) || "unknown error") };
    }
  }
  async function showPreview(run, files, img, holder) {
    if (!files.includes("preview.png")) return;
    try {
      const f = await call("run.file", { id: run.id, name: "preview.png" });
      if (!f || !f.blob) return;
      const url = URL.createObjectURL(f.blob);
      if (holder.url) URL.revokeObjectURL(holder.url);
      holder.url = url;
      img.src = url;
      img.hidden = false;
    } catch (e) { /* no preview */ }
  }
  async function showResults(form, run) {
    const files = fileNames(run.files);
    const c = cards[form];
    const { check, checkErr } = await fetchCheck(run, files);
    if (c.runId !== run.id) return;
    S.results[form] = { run, check, checkErr, files };
    paintResults(form);
    showPreview(run, files, c.preview, c);
    if (window.SteveCAMViewer) window.SteveCAMViewer.attach(c, run, files, call);
  }
  function outputDir(result) {
    if (!isObj(result)) return null;
    for (const k of ["output_dir", "program_dir", "saved_to", "folder"]) if (typeof result[k] === "string") return result[k];
    return null;
  }
  function paintResults(form) {
    const r = S.results[form];
    const c = cards[form];
    if (!r || !c) return;
    c.results.replaceChildren();
    c.results.append(RP.render(RP.build(r.run.result, r.check), S.units, { files: r.files, outputDir: outputDir(r.run.result) }));
    if (r.checkErr) c.results.append(el("p", { class: "muted small", text: r.checkErr }));
  }

  // ------------------------------------------------------------- check --
  function showCheckRun(run) {
    let c = S.checkRuns.find((x) => x.run.id === run.id);
    if (!c) {
      $("check-empty").hidden = true;
      c = { run, box: el("div", { class: "check-run" }), check: null, files: [], fetched: false, url: null };
      c.preview = el("img", { class: "run-preview", alt: "Check preview", hidden: true });
      c.body = el("div");
      c.box.append(c.body, c.preview);
      $("check-runs").prepend(c.box);
      S.checkRuns.unshift(c);
    }
    c.run = run;
    c.files = fileNames(run.files);
    paintCheckRun(c);
    if (run.state === "succeeded" && !c.fetched) {
      c.fetched = true;
      fetchCheck(run, c.files).then((r) => { c.check = r.check; paintCheckRun(c); });
      showPreview(run, c.files, c.preview, c);
    }
  }
  function paintCheckRun(c) {
    const run = c.run;
    c.body.replaceChildren(el("div", { class: "run-head" },
      el("span", { class: "run-state", text: "Check program: " + (STATE_TEXT[run.state] || run.state) })));
    if (run.message && !FINAL.has(run.state)) c.body.append(el("div", { class: "run-msg", text: run.message }));
    if (run.error) {
      const e = el("div", { class: "run-err" }, el("div", { text: run.error.message || PLAIN[run.error.code] || "The check failed." }));
      if (run.error.next_step) e.append(el("div", { class: "next", text: "Next: " + run.error.next_step }));
      c.body.append(e);
    }
    if (FINAL.has(run.state) && (run.result || c.check)) {
      c.body.append(RP.render(RP.build(run.result, c.check), S.units, { files: c.files, outputDir: outputDir(run.result) }));
    }
    if (window.SteveCAMViewer && c.files.indexOf("view.bin") >= 0) window.SteveCAMViewer.noteInto(c.body);
  }

  // --------------------------------------------------------- recent runs --
  function recentTime(at) { return String(at || "").slice(0, 16).replace("T", " "); }
  function renderRecent() {
    const box = $("recent"), list = $("recent-list");
    const runs = (S.lastRuns || []).slice(0, 10);
    box.hidden = !runs.length;
    list.replaceChildren();
    for (const r of runs) {
      const row = el("div", { class: "recent-run" });
      row.append(el("div", { class: "recent-info" },
        el("strong", { text: ENGINE_ACTION[r.action] || String(r.action || "run") }),
        el("span", { class: "muted small", text: " " + recentTime(r.at) }),
        el("span", { class: "muted small", text: r.has_view ? " · has 3D" : " · no 3D view" })));
      const holder = el("div", { class: "recent-view" });
      if (present("view.load")) {
        const btn = el("button", { type: "button", class: "secondary show3d-btn",
          "data-run-id": String(r.run_id), text: "Show 3D",
          disabled: !r.has_view || !allowed("view.load") });
        btn.addEventListener("click", () => {
          if (btn.disabled) return;
          btn.disabled = true;   // from click until this run ends
          holder.replaceChildren(el("p", { class: "muted small", text: "Loading this run's 3D view…" }));
          startRun("view.load", { run_id: r.run_id }, "SteveCAM panel: show 3D", (run) => {
            if (run.state === "error") {
              holder.replaceChildren(el("p", { class: "run-err", text: errText(run.callError) }));
              btn.disabled = false;
              return;
            }
            if (!FINAL.has(run.state)) return;
            if (run.state !== "succeeded") {
              holder.replaceChildren(el("p", { class: "run-err", text:
                "Couldn't load the 3D view: " + (run.error ? errText(run.error) : (STATE_TEXT[run.state] || run.state)) + "." }));
              btn.disabled = false;
              return;
            }
            btn.disabled = false;
            holder.replaceChildren();
            if (window.SteveCAMViewer) window.SteveCAMViewer.attach({ results: holder }, run, fileNames(run.files), call);
            else holder.append(el("p", { class: "muted small", text: "The 3D viewer is not available." }));
          });
        });
        row.append(btn);
      }
      row.append(holder);
      list.append(row);
    }
  }

  // ------------------------------------------------------------ measure --
  function onMeasureClick() {
    if (S.busy.measure || !S.doc || !allowed(ACTION.measure)) return;
    const doc = S.doc;
    const orientation = S.vals["setup.orientation"].v;
    const oe = enumOf(ACTION.measure, "orientation");
    if (oe && !oe.includes(orientation)) { $("measure-state").textContent = "Measuring doesn't offer this orientation."; return; }
    setBusy("measure", true);
    $("measure-state").textContent = "Starting…";
    startRun(ACTION.measure, { model: { document_id: doc.id, revision: doc.revision }, orientation },
      "SteveCAM panel: measure model", (run) => onMeasureRun(run, doc, orientation));
  }
  function onMeasureRun(run, doc, orientation) {
    const ms = $("measure-state");
    if (run.state === "error") { ms.textContent = "Couldn't measure: " + errText(run.callError); setBusy("measure", false); return; }
    const final = FINAL.has(run.state);
    ms.textContent = (STATE_TEXT[run.state] || run.state) + (run.message && !final ? ": " + run.message : "");
    if (!final) return;
    setBusy("measure", false);
    const size = isObj(run.result) && isObj(run.result.size_mm) ? run.result.size_mm : null;
    if (run.state === "succeeded" && size && ["x", "y", "z"].every((k) => typeof size[k] === "number")) {
      S.measured = { size_mm: size, bbox_mm: run.result.bbox_mm || null, orientation, docId: doc.id, revision: doc.revision };
      ms.textContent = "Measured.";
      for (const key in F) if (F[key].form === "setup") paint(key);
      paintSetupInfo();
    } else if (run.state === "succeeded") {
      ms.textContent = "Couldn't read the model size from SteveCAM.";
    } else {
      ms.textContent = "Couldn't measure: " + (run.error ? errText(run.error) : (STATE_TEXT[run.state] || run.state));
    }
  }

  // ------------------------------------------------------ context/events --
  function setNotice(text) {
    const n = $("notice");
    n.textContent = text;
    n.hidden = !text;
  }
  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme === "dark" ? "dark" : "light");
    if (window.SteveCAMViewer) window.SteveCAMViewer.theme();
  }
  function applyContext(ctx) {
    if (ctx.theme) applyTheme(ctx.theme);
    if ("document" in ctx) setDoc(ctx.document || null);
  }
  function setDoc(doc) {
    const prevId = S.doc ? S.doc.id : null;
    S.doc = doc && doc.id !== undefined ? doc : null;
    $("doc-line").textContent = S.doc
      ? "Open in STEVE: " + (S.doc.kind || "document") + " " + S.doc.id + (S.doc.revision !== undefined ? " (revision " + S.doc.revision + ")" : "")
      : "No part open. Open the part in STEVE to make programs.";
    if (S.loaded && S.doc && S.doc.id !== prevId) {
      S.job = null;
      S.savedSetup = null;
      S.setupTouched = false;
      loadJob();
    }
    if (!S.doc) { S.job = null; renderJob(); }
    for (const key in F) if (F[key].form === "setup") paint(key);
    paintSetupInfo();
    updateButtons();
  }
  function onEvent(name, data) {
    if (name === "last_runs") {
      S.lastRuns = isObj(data) && Array.isArray(data.runs) ? data.runs.filter(isObj) : [];
      renderRecent();
      return;
    }
    if (name !== "engine_state" || !isObj(data)) return;
    const pill = $("engine");
    const state = String(data.state || "unknown");
    let text = state === "idle" ? "Idle" : state === "busy" ? "Busy" : state.replace(/_/g, " ");
    if (data.action) text += " · " + (ENGINE_ACTION[data.action] || data.action);
    if (typeof data.progress === "number" && state === "busy") text += " " + Math.round(Math.max(0, Math.min(1, data.progress)) * 100) + "%";
    pill.textContent = text;
    pill.className = "pill " + state.replace(/[^\w-]/g, "");
  }

  // ------------------------------------------------------------ actions --
  function setActions(list) {
    S.act = {};
    for (const a of Array.isArray(list) ? list : []) {
      if (!isObj(a)) continue;
      if (a.name) S.act[a.name] = a;
      if (a.id && !S.act[a.id]) S.act[a.id] = a;
    }
    S.actionsLoaded = true;
    // orientation: four 90° tips only when a run action's schema lists them
    const enums = [ACTION.rough, ACTION.finish].map((n) => enumOf(n, "orientation") || []);
    const sel = F["setup.orientation"].ctl;
    const cur = S.vals["setup.orientation"].v;
    sel.replaceChildren();
    for (const [v, t] of FX.ORIENT_BASE) sel.append(el("option", { value: v, text: t }));
    for (const [v, t] of FX.ORIENT_TIPS) if (enums.some((e) => e.includes(v))) sel.append(el("option", { value: v, text: t }));
    S.vals["setup.orientation"] = { v: [...sel.options].some((o) => o.value === cur) ? cur : "as_modeled" };
    // origin
    const showOrigin = originShown();
    F["setup.origin"].wrap.hidden = !showOrigin;
    $("origin-fixed").hidden = showOrigin;
    if (showOrigin) {
      const oe = [ACTION.rough, ACTION.finish].map((n) => enumOf(n, "origin")).filter(Boolean);
      const osel = F["setup.origin"].ctl;
      const ocur = S.vals["setup.origin"].v;
      osel.replaceChildren();
      for (const [v, t] of FX.ORIGINS) if (!oe.length || oe.some((e) => e.includes(v))) osel.append(el("option", { value: v, text: t }));
      const opts = [...osel.options].map((o) => o.value);
      S.vals["setup.origin"] = { v: opts.includes(ocur) ? ocur : opts[0] };
    }
    // tabs
    const tabs = { rough: present(ACTION.rough), finish: present(ACTION.finish), check: present(ACTION.check) };
    for (const t in tabs) $("tab-" + t).hidden = !tabs[t];
    const first = ["rough", "finish", "check"].find((t) => tabs[t]);
    $("no-tabs").hidden = !!first;
    if (!first) for (const t in tabs) $("pane-" + t).hidden = true;
    else if (!tabs[currentTab]) selectTab(first);
    else selectTab(currentTab);
    // measure + blank
    $("measure-box").hidden = !present(ACTION.measure);
    $("save-row").hidden = !hasJobSetup();
    paintAll();
    updateButtons();
    renderRecent();
  }
  let currentTab = "rough";
  function selectTab(t) {
    currentTab = t;
    for (const x of ["rough", "finish", "check"]) {
      const on = x === t;
      $("tab-" + x).setAttribute("aria-selected", on ? "true" : "false");
      $("tab-" + x).tabIndex = on ? 0 : -1;
      $("pane-" + x).hidden = !on;
    }
  }

  // ---------------------------------------------------------------- UI --
  function grid(id, ...kids) { const g = id ? $(id) : el("div", { class: "grid" }); g.append(...kids); return g; }
  function buildUI() {
    // setup
    const units = el("select", { id: "units" }, el("option", { value: "inch", text: "inch" }), el("option", { value: "mm", text: "mm" }));
    units.addEventListener("change", () => {
      S.units = units.value === "mm" ? "mm" : "inch";
      S.setupTouched = true;
      for (const form of ["rough", "finish"]) if (cards[form]) cards[form].errors.replaceChildren();
      for (const key in F) clearFieldError(key);
      paintAll();
    });
    const sp = (n) => makeField("setup", FX.specOf("setup", n));
    grid("setup-top", el("label", { class: "fld", for: "units" }, el("span", { class: "lbl", text: "Units" }), units),
      sp("orientation"), sp("origin"));
    F["setup.orientation"].wrap.classList.add("wide");
    F["setup.origin"].wrap.classList.add("wide");
    F["setup.origin"].wrap.hidden = true;
    grid("setup-stock", sp("stock_xy"), sp("stock_top"), sp("stock_bottom"), sp("floor_z"), sp("stock_x"), sp("stock_y"));
    F["setup.floor_z"].ctl.title = "Height of the roughing floor above the stock bottom.";
    grid("blank-fields", ...FX.FORMS.blank.map((s) => makeField("blank", s)));
    $("measure-btn").addEventListener("click", onMeasureClick);
    $("save-setup").addEventListener("click", () => saveSetup(true));

    // rough
    const rf = (n) => makeField("rough", FX.specOf("rough", n));
    $("rough-form").append(
      el("h3", { text: "Tool" }),
      grid(null, makePicker("rough"), rf("tool_number"), rf("tool_type"), rf("tool_diameter"), rf("corner_radius"), rf("flute_length")),
      el("h3", { text: "Cut" }),
      grid(null, rf("stepdown"), rf("optimal_load"), rf("stock_to_leave"), rf("rest_stepup"),
        rf("rpm"), rf("feed"), rf("ramp_feed"), rf("program_number")),
      ...makeCard("rough"));

    // finish
    const ff = (n) => makeField("finish", FX.specOf("finish", n));
    const chain = el("details", { class: "group", id: "finish-chain" },
      el("summary", { text: "Roughing tool for this chain" }),
      grid(null, makePicker("chain"), ff("rough_tool_type"), ff("rough_tool_diameter"), ff("rough_corner_radius"),
        ff("rough_flute_length"), ff("rough_stepdown"), ff("rough_optimal_load"), ff("rough_stock_to_leave"), ff("rough_rest_stepup")));
    $("finish-form").append(
      el("h3", { text: "Finish ball" }),
      grid(null, makePicker("finish"), ff("tool_number"), ff("tool_diameter"), ff("stepover"), ff("stepdown"), ff("slope_threshold"),
        ff("rpm"), ff("feed"), ff("ramp_feed"), ff("program_number")),
      el("h3", { text: "Rest pass" }),
      grid(null, makePicker("rest"), ff("rest_tool_number"), ff("min_rest")),
      chain,
      ...makeCard("finish"));

    // tabs
    for (const t of ["rough", "finish", "check"]) $("tab-" + t).addEventListener("click", () => selectTab(t));
    $("tabs").addEventListener("keydown", (e) => {
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      const vis = ["rough", "finish", "check"].filter((t) => !$("tab-" + t).hidden);
      const i = vis.indexOf(currentTab);
      const n = vis[(i + (e.key === "ArrowRight" ? 1 : vis.length - 1)) % vis.length];
      if (n) { selectTab(n); $("tab-" + n).focus(); }
    });
    selectTab("rough");
  }

  // -------------------------------------------------------------- load --
  async function load() {
    buildUI();
    paintAll();
    updateButtons();
    let ctx;
    try {
      ctx = await call("context");
    } catch (e) {
      $("doc-line").textContent = "Not connected to STEVE: " + errText(e);
      return;
    }
    applyContext(isObj(ctx) ? ctx : {});
    try {
      const ev = await call("events");
      const list = Array.isArray(ev) ? ev : isObj(ev) ? Object.keys(ev).map((k) => Object.assign({ name: k }, ev[k])) : [];
      for (const x of list) if (x) onEvent(x.name, x.data);
    } catch (e) { /* no events yet */ }
    try {
      setActions(await call("actions"));
    } catch (e) {
      setActions([]);
      setNotice("Couldn't read what SteveCAM offers: " + errText(e));
    }
    S.loaded = true;
    if (allowed("tools.list")) await loadTools();
    loadJob();
  }
  load();
})();
