"use strict";
// SteveCAM panel tests. Run: node run_tests.js   (Chromium + Playwright, no other deps)
// Every test runs the panel in an iframe under tests/mock_parent.html, which records every postMessage.
// Every test also enforces: no network (only the panel's own file:// files), no storage/cookie/popup access,
// no navigation of the panel, and no console errors.
const fs = require("fs");
const path = require("path");
const assert = require("assert");
const { chromium } = require("playwright");
const CATALOG = require("./catalog.js");

const OUT = path.resolve(__dirname, "..");
const PANEL_DIR = path.join(OUT, "connector", "panel");
const TESTS_DIR = __dirname;
const SCREENS = process.env.SCREENS || path.join(require("os").tmpdir(), "stevecam_panel_screens");
const TESTDATA = path.join(OUT, "connector", "testdata");
const MOCK_URL = "file://" + path.join(TESTS_DIR, "mock_parent.html");
const DEV_URL = "file://" + path.join(PANEL_DIR, "dev.html");
fs.mkdirSync(SCREENS, { recursive: true });
fs.mkdirSync(TESTDATA, { recursive: true });

const STORAGE_GUARD = `(() => {
  const hits = [];
  Object.defineProperty(window, "__storageHits", { value: hits });
  const wrap = (obj, prop, label) => {
    try {
      let owner = obj;
      while (owner && !Object.getOwnPropertyDescriptor(owner, prop)) owner = Object.getPrototypeOf(owner);
      if (!owner) { hits.push("noprop " + label); return; }
      const d = Object.getOwnPropertyDescriptor(owner, prop);
      const desc = { configurable: true, enumerable: d.enumerable,
        get() { hits.push(label); return d.get ? d.get.call(this) : d.value; } };
      desc.set = function (v) { hits.push(label + " (set)"); if (d.set) d.set.call(this, v); };
      Object.defineProperty(owner, prop, desc);
    } catch (e) { hits.push("wrapfail " + label + ": " + e.message); }
  };
  wrap(window, "localStorage", "localStorage");
  wrap(window, "sessionStorage", "sessionStorage");
  wrap(window, "indexedDB", "indexedDB");
  wrap(Document.prototype, "cookie", "document.cookie");
  wrap(window, "caches", "caches");
  const open = window.open;
  window.open = function () { hits.push("window.open"); return null; };
})();`;

// ------------------------------------------------------------------ harness --
let browser;
const tests = [];
function test(name, fn, opts) { tests.push({ name, fn, opts: opts || {} }); }

class Env {
  constructor(ctx) {
    this.ctx = ctx;
    this.network = [];        // anything that is not one of our own files
    this.requests = [];
    this.consoleErrors = [];
    this.navigations = [];
    this.popups = [];
  }
  async open(cfg, opts) {
    opts = opts || {};
    const page = this.page = await this.ctx.newPage({ viewport: { width: 1000, height: 900 } });
    page.on("console", (m) => { if (m.type() === "error") this.consoleErrors.push(m.text()); });
    page.on("pageerror", (e) => this.consoleErrors.push("pageerror: " + e.message));
    page.on("request", (r) => {
      this.requests.push({ url: r.url(), frame: r.frame() ? r.frame().url() : "" });
      if (!this.allowed(r.url())) this.network.push(r.url());
    });
    page.on("framenavigated", (f) => { if (f !== page.mainFrame()) this.navigations.push(f.url()); });
    page.on("popup", (p) => this.popups.push(p.url()));
    await page.addInitScript(STORAGE_GUARD);
    if (opts.init) await page.addInitScript(opts.init);
    await page.addInitScript((c) => { if (window.top === window) window.__CFG = c; }, cfg || {});
    await page.goto(opts.url || MOCK_URL);
    this.panel = await this.waitPanel();
    if (!opts.noReady) await this.ready();
    return this;
  }
  allowed(url) {
    if (!url.startsWith("file://")) return false;
    const p = decodeURIComponent(url.replace(/^file:\/\//, "").split(/[?#]/)[0]);
    return p.startsWith(PANEL_DIR + path.sep) || p.startsWith(TESTS_DIR + path.sep);
  }
  async waitPanel() {
    for (let i = 0; i < 100; i++) {
      const f = this.page.frames().find((x) => /connector\/panel\/index\.html/.test(x.url()));
      if (f) { await f.waitForSelector("#rough-btn", { state: "attached" }); return f; }
      await this.page.waitForTimeout(20);
    }
    throw new Error("panel frame never loaded");
  }
  async ready() {
    await this.page.waitForFunction(() => window.__mock && window.__mock.sent("actions").length > 0);
    await this.settle();
  }
  async settle() {
    let quiet = 0;
    for (let i = 0; i < 200 && quiet < 4; i++) {
      const p = await this.page.evaluate(() => (window.__mock ? window.__mock.pending : 0));
      quiet = p === 0 ? quiet + 1 : 0;
      await this.page.waitForTimeout(25);
    }
  }
  mock(fn, arg) { return this.page.evaluate(fn, arg); }
  sent(method, action) { return this.page.evaluate(([m, a]) => window.__mock.sent(m, a), [method, action]); }
  async runInputs(action) { const r = await this.mock((a) => window.__mock.lastRun(a), action); return r && r.params.inputs; }
  text(sel) { return this.panel.textContent(sel); }
  async waitText(sel, re, timeout) {
    await this.panel.waitForFunction(([s, src]) => {
      const e = document.querySelector(s);
      return e && new RegExp(src).test(e.textContent);
    }, [sel, re.source], { timeout: timeout || 4000 });
  }
  async waitEnabled(sel) { await this.panel.waitForFunction((s) => !document.querySelector(s).disabled, sel, { timeout: 4000 }); }
  async disabled(sel) { return this.panel.$eval(sel, (e) => e.disabled); }
  async clean() {
    const hits = await this.panel.evaluate(() => window.__storageHits.slice()).catch(() => ["(panel gone)"]);
    const problems = [];
    if (this.network.length) problems.push("network requests: " + this.network.join(", "));
    if (hits.length) problems.push("storage access in panel: " + hits.join(", "));
    if (this.consoleErrors.length) problems.push("console errors: " + this.consoleErrors.join(" | "));
    if (this.navigations.filter((u) => u !== "about:blank" && !/connector\/panel\/index\.html$/.test(u)).length) problems.push("panel navigated: " + this.navigations.join(", "));
    if (this.popups.length) problems.push("popups: " + this.popups.join(", "));
    return problems;
  }
}

async function newEnv() {
  const ctx = await browser.newContext();
  const env = new Env(ctx);
  await ctx.route("**/*", (route) => {
    const url = route.request().url();
    if (env.allowed(url)) return route.continue();
    env.network.push(url);
    return route.abort();
  });
  return env;
}

// ------------------------------------------------------------------ helpers --
const close = (a, b, eps) => Math.abs(a - b) <= (eps == null ? 1e-9 : eps) * Math.max(1, Math.abs(b));
async function clickRun(env, form) {
  await env.waitEnabled("#" + form + "-btn");
  const before = (await env.sent("run", form === "rough" ? "adaptive_rough" : "slope_split_finish")).length;
  await env.panel.click("#" + form + "-btn");
  await env.page.waitForFunction(([a, n]) => window.__mock.sent("run", a).length > n, [form === "rough" ? "adaptive_rough" : "slope_split_finish", before], { timeout: 3000 });
  return env.runInputs(form === "rough" ? "adaptive_rough" : "slope_split_finish");
}
async function waitFinal(env, form) {
  await env.panel.waitForFunction((f) => {
    const s = document.getElementById(f + "-state");
    return s && ["succeeded", "failed", "rejected", "cancelled", "expired", "error"].includes(s.dataset.state);
  }, form, { timeout: 5000 });
  await env.settle();
}
async function fieldValues(env) {
  return env.panel.$$eval("input[id^='f-'], select[id^='f-']", (els) => Object.fromEntries(els.map((e) => [e.id, e.value])));
}
async function setUnits(env, u) { await env.panel.selectOption("#units", u); }

const RESULTS = { passed: 0, failed: 0, failures: [] };
const DEFAULT_INPUTS = { note: "Exact inputs the panel sends with untouched defaults. Run each through validate_inputs(action, inputs). 'catalog_681f551' = schema as of 681f551 (no origin/document_id); 'extended' = with the parallel origin/document_id inputs.", catalog_681f551: {}, extended: {} };

// =================================================================== tests ==
test("files: count and size under the bridge limits; sources use no network/storage/navigation APIs", async () => {
  const files = [];
  (function walk(d) { for (const n of fs.readdirSync(d)) { const p = path.join(d, n); fs.statSync(p).isDirectory() ? walk(p) : files.push(p); } })(PANEL_DIR);
  const total = files.reduce((s, f) => s + fs.statSync(f).size, 0);
  assert(files.length <= 50, "too many files: " + files.length);
  assert(total <= 2 * 1024 * 1024, "too big: " + total);
  const banned = [/\bfetch\s*\(/, /XMLHttpRequest/, /WebSocket/, /EventSource/, /localStorage/, /sessionStorage/, /document\.cookie/,
    /indexedDB/, /window\.open/, /\blocation\s*[.=]/, /https?:\/\//, /<form\b/i, /<a\s/i, /@import/, /url\(\s*['"]?(?!data:)/, /sendBeacon/, /importScripts/];
  for (const f of files.filter((x) => /\.(js|html|css)$/.test(x))) {
    const src = fs.readFileSync(f, "utf8");
    for (const re of banned) assert(!re.test(src), path.basename(f) + " matches " + re);
  }
  return { files: files.length, bytes: total };
});

test("guards work: the test would catch a network request and storage access", async () => {
  const env = await newEnv();
  try {
    await env.open({});
    await env.panel.evaluate(() => { const i = new Image(); i.src = "https://example.invalid/x.png"; try { void window.localStorage; } catch (e) {} });
    await env.page.waitForTimeout(300);
    const problems = await env.clean();
    assert(problems.some((p) => /network/.test(p)), "network guard missed: " + problems);
    assert(problems.some((p) => /localStorage/.test(p)), "storage guard missed: " + problems);
  } finally { await env.ctx.close(); }
  return "guards catch both";
}, { noCleanCheck: true });

test("load order: context, then events, then actions; then only tools.list and job.get", async (env) => {
  await env.open({});
  const log = await env.mock(() => window.__mock.log.map((e) => ({ dir: e.dir, method: e.data && e.data.method, id: e.data && e.data.id, action: e.data && e.data.params && e.data.params.action })));
  const calls = log.filter((e) => e.dir === "in" && e.method);
  assert.deepStrictEqual(calls.slice(0, 3).map((c) => c.method), ["context", "events", "actions"]);
  // each one only after the previous was answered
  for (let i = 1; i < 3; i++) {
    const prevAns = log.findIndex((e) => e.dir === "out" && e.id === calls[i - 1].id);
    const thisCall = log.findIndex((e) => e.dir === "in" && e.id === calls[i].id);
    assert(prevAns >= 0 && prevAns < thisCall, calls[i].method + " was sent before " + calls[i - 1].method + " was answered");
  }
  const runs = calls.filter((c) => c.method === "run").map((c) => c.action);
  assert.deepStrictEqual(runs, ["tools.list", "job.get"], "runs on load: " + runs);
  const ansTools = log.findIndex((e) => e.dir === "out" && e.id === calls.find((c) => c.action === "tools.list").id);
  const actAns = log.findIndex((e) => e.dir === "out" && e.id === calls[2].id);
  assert(ansTools > actAns, "tools.list before actions answered");
  assert.strictEqual((await env.text("#engine")).trim(), "Idle");
  await env.mock(() => window.__mock.pushEvent("engine_state", { state: "busy", action: "adaptive_rough", progress: 0.45 }));
  await env.waitText("#engine", /Busy · Rough 45%/);
  return "order ok, " + runs.length + " runs on load";
});

test("theme: follows context.theme and its live updates", async (env) => {
  await env.open({ theme: "dark" });
  assert.strictEqual(await env.panel.evaluate(() => document.documentElement.dataset.theme), "dark");
  const bg = await env.panel.evaluate(() => getComputedStyle(document.body).backgroundColor);
  assert.strictEqual(bg, "rgb(22, 23, 27)");
  await env.mock(() => window.__mock.pushContext({ theme: "light" }));
  await env.panel.waitForFunction(() => document.documentElement.dataset.theme === "light");
  await env.mock(() => window.__mock.pushContext({ theme: "dark" }));
  await env.panel.waitForFunction(() => document.documentElement.dataset.theme === "dark");
});

for (const schema of ["extended", "catalog_681f551"]) {
  for (const units of ["inch", "mm"]) {
    test(`default inputs (${schema}, ${units}): every value valid after the server's unit rule`, async (env) => {
      const extended = schema === "extended";
      await env.open({ schema: extended ? "extended" : "legacy" });
      if (units !== "inch") await setUnits(env, units);
      assert.strictEqual(await env.panel.inputValue("#units"), units);
      const cat = CATALOG.catalog(extended);
      const out = {};
      for (const [form, action] of [["rough", "adaptive_rough"], ["finish", "slope_split_finish"]]) {
        if (form === "finish") await env.panel.click("#tab-finish");
        const inputs = await clickRun(env, form);
        out[action] = inputs;
        assert.strictEqual(inputs.units, units, "units not sent as " + units);
        assert.deepStrictEqual(inputs.model, { document_id: "doc-42", revision: 7 });
        const problems = CATALOG.validate(action, inputs, extended);
        assert.deepStrictEqual(problems, [], action + " " + units + ": " + problems.join("; "));
        // every schema field with a default is sent, in the shown unit, close to the mm default
        const mm = CATALOG.toServerMm(inputs);
        for (const [k, p] of Object.entries(cat[action])) {
          if (p.default === null || p.default === undefined || k === "units") continue;
          assert(k in inputs, action + ": " + k + " not sent (the server would apply its mm default)");
          if (typeof p.default === "number") {
            const tol = units === "mm" ? 1e-12 : 0.02;  // inch defaults are the round inch numbers (0.04 in = 1.016 mm)
            assert(close(mm[k], p.default, tol) || (p.default === 0 && mm[k] === 0), `${action}.${k}: server gets ${mm[k]} mm, schema default ${p.default} mm`);
          }
        }
        if (units === "inch") {
          assert.strictEqual(inputs.tool_diameter, form === "rough" ? 0.5 : inputs.tool_diameter);
          assert.strictEqual(inputs.feed, 135);
          assert(close(mm.tool_diameter, form === "rough" ? 12.7 : 6.0, 1e-9), "tool_diameter mm " + mm.tool_diameter);
        }
        if (!extended) {
          assert(!("origin" in inputs) && !("document_id" in inputs), "sent inputs the 681f551 schema doesn't have");
        } else {
          assert.strictEqual(inputs.origin, "stock_bottom_centre");
          assert.strictEqual(inputs.document_id, "doc-42");
        }
        await waitFinal(env, form);
      }
      DEFAULT_INPUTS[schema][units] = out;
      return Object.keys(out.adaptive_rough).length + " + " + Object.keys(out.slope_split_finish).length + " inputs checked";
    });
  }
}

test("the old bug can't happen: mm labels/values are never sent with units=inch", async (env) => {
  await env.open({});
  // inch labels
  assert.match(await env.text("#w-rough-tool_diameter .lbl"), /\(in\)/);
  assert.match(await env.text("#w-rough-feed .lbl"), /\(in\/min\)/);
  assert.match(await env.text("#w-rough-rpm .lbl"), /\(rpm\)/);
  await setUnits(env, "mm");
  assert.match(await env.text("#w-rough-tool_diameter .lbl"), /\(mm\)/);
  assert.match(await env.text("#w-rough-feed .lbl"), /\(mm\/min\)/);
  assert.strictEqual(await env.panel.inputValue("#f-rough-tool_diameter"), "12.7");
  await setUnits(env, "inch");
  assert.strictEqual(await env.panel.inputValue("#f-rough-tool_diameter"), "0.5");
  // a value typed as mm while in inch is caught before sending
  await env.panel.fill("#f-rough-tool_diameter", "12.7");
  await env.panel.click("#rough-btn");
  await env.page.waitForTimeout(150);
  assert.strictEqual((await env.sent("run", "adaptive_rough")).length, 0, "an out-of-range run was sent");
  assert.match(await env.text("#err-rough-tool_diameter"), /Tool dia must be from 0\.0394 to 1\.2598 in/);
  assert.match(await env.text("#rough-errors"), /Tool dia/);
});

test("client checks: range, whole numbers, bull 0 < r < dia/2, flat forces radius 0", async (env) => {
  await env.open({});
  const sent = async () => (await env.sent("run", "adaptive_rough")).length;
  await env.panel.fill("#f-rough-corner_radius", "0.3");
  await env.panel.click("#rough-btn");
  assert.match(await env.text("#err-rough-corner_radius"), /more than 0 and less than half the tool dia \(0\.25 in\)/);
  await env.panel.fill("#f-rough-corner_radius", "0");
  await env.panel.click("#rough-btn");
  assert.match(await env.text("#err-rough-corner_radius"), /more than 0/);
  await env.panel.fill("#f-rough-corner_radius", "0.005");
  await env.panel.fill("#f-rough-rpm", "7500.5");
  await env.panel.click("#rough-btn");
  assert.match(await env.text("#err-rough-rpm"), /whole number/);
  await env.panel.fill("#f-rough-rpm", "40000");
  await env.panel.click("#rough-btn");
  assert.match(await env.text("#err-rough-rpm"), /Spindle must be from 100 to 30000 rpm/);
  await env.panel.fill("#f-rough-rpm", "7500");
  await env.panel.fill("#f-setup-stock_xy", "abc");
  await env.panel.click("#rough-btn");
  assert.match(await env.text("#err-setup-stock_xy"), /not a number/);
  await env.panel.fill("#f-setup-stock_xy", "");
  await env.panel.click("#rough-btn");
  assert.match(await env.text("#err-setup-stock_xy"), /needs a number/);
  await env.panel.fill("#f-setup-stock_xy", "0.04");
  await env.panel.fill("#f-rough-feed", "0.3");
  await env.panel.click("#rough-btn");
  assert.match(await env.text("#err-rough-feed"), /Feed must be from 0\.3938 to 787\.4015 in\/min/);
  await env.panel.fill("#f-rough-feed", "135");
  assert.strictEqual(await sent(), 0, "a run was sent while fields were out of range");
  // flat: corner radius disabled, shows 0, sends 0
  await env.panel.selectOption("#f-rough-tool_type", "flat");
  assert.strictEqual(await env.disabled("#f-rough-corner_radius"), true);
  assert.strictEqual(await env.panel.inputValue("#f-rough-corner_radius"), "0");
  const inputs = await clickRun(env, "rough");
  assert.strictEqual(inputs.tool_type, "flat");
  assert.strictEqual(inputs.corner_radius, 0);
  assert.deepStrictEqual(CATALOG.validate("adaptive_rough", inputs, true), []);
  await waitFinal(env, "rough");
  await env.panel.selectOption("#f-rough-tool_type", "bull");
  assert.strictEqual(await env.panel.inputValue("#f-rough-corner_radius"), "0.005");
});

test("units: toggling 10 times returns the same mm values exactly (typed, default and tool-filled values)", async (env) => {
  await env.open({});
  // typed in inch, typed in mm, a tool fill (6 mm ball) and defaults
  await env.panel.fill("#f-rough-tool_diameter", "0.375");
  await env.panel.fill("#f-rough-corner_radius", "0.03");
  await setUnits(env, "mm");
  await env.panel.fill("#f-rough-stepdown", "5.5");
  await env.panel.fill("#f-setup-stock_xy", "1.27");
  await env.panel.click("#tab-finish");
  await env.panel.selectOption("#pick-finish", "tl-ball-6");
  await env.panel.click("#tab-rough");
  const mmShown = await fieldValues(env);
  const mmRough = await clickRun(env, "rough"); await waitFinal(env, "rough");
  await env.panel.click("#tab-finish");
  const mmFinish = await clickRun(env, "finish"); await waitFinal(env, "finish");
  await setUnits(env, "inch");
  const inShown = await fieldValues(env);
  const inFinish = await clickRun(env, "finish"); await waitFinal(env, "finish");
  assert(close(inFinish.tool_diameter * 25.4, 6, 1e-12), "6 mm ball sent as " + inFinish.tool_diameter + " in");
  assert.strictEqual(inShown["f-finish-tool_diameter"], "0.2362");
  for (let i = 0; i < 10; i++) await setUnits(env, i % 2 === 0 ? "mm" : "inch");
  assert.strictEqual(await env.panel.inputValue("#units"), "inch");
  assert.deepStrictEqual(await fieldValues(env), inShown, "inch fields changed after 10 toggles");
  assert.deepStrictEqual(await clickRun(env, "finish"), inFinish); await waitFinal(env, "finish");
  for (let i = 0; i < 10; i++) await setUnits(env, i % 2 === 0 ? "mm" : "inch");
  await setUnits(env, "mm");
  assert.deepStrictEqual(await fieldValues(env), mmShown, "mm fields changed after toggles");
  assert.deepStrictEqual(await clickRun(env, "finish"), mmFinish); await waitFinal(env, "finish");
  await env.panel.click("#tab-rough");
  assert.deepStrictEqual(await clickRun(env, "rough"), mmRough); await waitFinal(env, "rough");
  assert.strictEqual(mmRough.tool_diameter, 9.525);
  assert.strictEqual(mmRough.stepdown, 5.5);
  assert.strictEqual(mmShown["f-rough-tool_diameter"], "9.525");
  assert.strictEqual(inShown["f-rough-stepdown"], "0.2165");
  assert.strictEqual(inShown["f-rough-tool_diameter"], "0.375");
  return "20+ toggles, values identical";
});

test("runs start synchronously inside the click handler (rough, finish, measure)", async (env) => {
  await env.open({});
  for (const [btn, action, tab] of [["#rough-btn", "adaptive_rough", "#tab-rough"], ["#finish-btn", "slope_split_finish", "#tab-finish"], ["#measure-btn", "model.measure", null]]) {
    if (tab) await env.panel.click(tab);
    await env.waitEnabled(btn);
    const before = await env.mock(() => window.__mock.log.length);
    await env.panel.evaluate((b) => { document.querySelector(b).click(); window.parent.postMessage({ marker: "after-click" }, "*"); }, btn);
    await env.page.waitForTimeout(100);
    const log = await env.mock((n) => window.__mock.log.slice(n).filter((e) => e.dir === "in").map((e) => e.data), before);
    const iRun = log.findIndex((d) => d.method === "run" && d.params.action === action);
    const iMarker = log.findIndex((d) => d.marker === "after-click");
    assert(iRun >= 0 && iRun < iMarker, action + " run was not posted synchronously in the click (run " + iRun + ", marker " + iMarker + ")");
    const inp = log[iRun].params.inputs;
    assert.deepStrictEqual(inp.model, { document_id: "doc-42", revision: 7 }, "not the context document");
    if (action === "model.measure") assert.deepStrictEqual(Object.keys(inp).sort(), ["model", "orientation"]);
    await env.settle();
  }
});

test("run button: disabled from click through awaiting_confirmation and running; Cancel; re-enabled only on final states", async (env) => {
  await env.open({ manual: ["adaptive_rough"] });
  const runs = async () => (await env.sent("run", "adaptive_rough")).length;
  await env.panel.click("#rough-btn");
  assert.strictEqual(await env.disabled("#rough-btn"), true, "not disabled right after click");
  await env.waitText("#rough-state", /^Waiting for you to confirm in STEVE$/);
  assert.strictEqual(await env.disabled("#rough-btn"), true);
  assert.strictEqual(await env.panel.isVisible("#rough-cancel"), true);
  // a second click does nothing
  await env.panel.evaluate(() => { document.getElementById("rough-btn").click(); document.getElementById("rough-btn").click(); });
  await env.page.waitForTimeout(80);
  assert.strictEqual(await runs(), 1, "second run queued");
  const id = await env.mock(() => Object.values(window.__mock.runs).filter((r) => r.action === "adaptive_rough").pop().id);
  await env.mock((i) => window.__mock.push(i, { state: "running", progress: 0.3, message: "Level 1/5" }), id);
  await env.waitText("#rough-state", /^Working$/);
  assert.strictEqual(await env.disabled("#rough-btn"), true);
  assert.strictEqual(await env.panel.$eval("#rough-progress", (p) => p.value), 0.3);
  assert.strictEqual(await env.text("#rough-msg"), "Level 1/5");
  await env.panel.click("#rough-cancel");
  await env.waitText("#rough-state", /^Cancelled$/);
  assert.strictEqual((await env.sent("cancel")).length, 1);
  assert.strictEqual((await env.sent("cancel"))[0].params.id, id);
  await env.waitEnabled("#rough-btn");
  assert.strictEqual(await env.panel.isVisible("#rough-cancel"), false);
  for (const final of ["succeeded", "failed", "rejected", "cancelled", "expired"]) {
    const n = await runs();
    await env.panel.click("#rough-btn");
    await env.page.waitForFunction((k) => Object.values(window.__mock.runs).filter((r) => r.action === "adaptive_rough").length > k, n);
    const rid = await env.mock(() => Object.values(window.__mock.runs).filter((r) => r.action === "adaptive_rough").pop().id);
    assert.strictEqual(await env.disabled("#rough-btn"), true);
    for (const st of ["awaiting_confirmation", "received", "running"]) {
      await env.mock(([i, s]) => window.__mock.push(i, { state: s, progress: 0.5 }), [rid, st]);
      await env.page.waitForTimeout(30);
      assert.strictEqual(await env.disabled("#rough-btn"), true, "enabled while " + st);
    }
    await env.mock(([i, s]) => window.__mock.push(i, { state: s, error: s === "failed" ? { code: "x", message: "boom" } : null }), [rid, final]);
    await env.waitEnabled("#rough-btn");
    // a late non-final push can't re-disable or un-finish it
    await env.mock((i) => window.__mock.push(i, { state: "running" }), rid);
    await env.page.waitForTimeout(40);
    assert.strictEqual(await env.disabled("#rough-btn"), false, "late push re-disabled the button after " + final);
  }
  assert.strictEqual(await runs(), 6);
});

const REVIEW_RESULT = {
  verdict: "needs_review", summary: "No gouges, but two things need a look.",
  attention: [
    { code: "overload_feed", severity: "review", message: "Tool load over 1.2× optimal in 2 places.", where: { program: "rough.nc", line: 1234, x: 12.3, y: 4.5, z: -3.2 }, next_step: "Check those moves." },
    { code: "steep_ramp", severity: "review", message: "3 ramps are steeper than 3°.", where: { line: 9, x: -25, y: -25, z: 12.05 }, next_step: "Check the entry moves." },
    { code: "holder_estimated", severity: "info", message: "Holder size was estimated." },
  ],
  estimated_time_min: 0.82, cut_length_mm: 1253.9, zmap_gouges: { count: 2, max_depth: 0.12, first_line: 880 }, rapid_collisions: null,
  over_flute: { count: 0 }, leftover: { mean_mm: 0.42, p95_mm: 0.5, within_0p5mm_fraction: 0.98 },
  engagement: { overloads: 2, reduced_feed_windows: [{ line: 1234, feed_pct: 70 }] }, unsupported_codes: [{ code: "G41", line: 12 }],
  areas_left: ["pocket corners"], some_new_field: { anything: [1, 2, 3] },
};
const SAMPLE = JSON.parse(fs.readFileSync(path.join(TESTDATA, "check_sample.json"), "utf8"));

test("results view (contradiction case): result says needs_review but a gate FAILs -> badge Failed with a note; attention, rows, numbers, programs, preview", async (env) => {
  await env.open({ results: { adaptive_rough: { state: "succeeded", result: REVIEW_RESULT, files: ["rough.nc", "check.json", "preview.png"] } }, checkJson: SAMPLE });
  await clickRun(env, "rough");
  await waitFinal(env, "rough");
  await env.panel.waitForSelector("#rough-preview:not([hidden])");
  const R = "#rough-results";
  assert.strictEqual((await env.text(R + " .vbadge")).trim(), "Failed");
  assert.match(await env.text(R + " .verdict"), /two things need a look/);
  assert.strictEqual((await env.text(R + " .v-override")).trim(), "A safety check below failed, even though the result said \u201cNeeds review\u201d.");
  const groups = await env.panel.$$eval(R + " .attn h4", (hs) => hs.map((h) => h.textContent));
  assert.deepStrictEqual(groups, ["Please review (2)", "Good to know (1)"]);
  assert.match(await env.text(R + " .attn-review"), /line 1234 · X 0\.484 Y 0\.177 Z −0\.126/);
  assert.match(await env.text(R + " .attn-review"), /Next: Check those moves\./);
  const rows = await env.panel.$$eval(R + " .results > .gate", (g) => g.map((r) => r.querySelector(".g-name").textContent + "=" + r.dataset.state + ":" + r.querySelector(".g-detail").textContent));
  assert(rows.includes("Gouges=fail:2 found, worst 0.0047 in, first at line 880"), rows.join(" | "));
  assert(rows.includes("Rapid collisions=unknown:unknown"), rows.join(" | "));
  assert(rows.includes("Over-flute / shank=pass:none"), rows.join(" | "));
  const txt = await env.text(R);
  for (const re of [/Time49 s/, /Cut length49\.4 in/, /Leftover mean0\.0165 in/, /Leftover p950\.0197 in/, /Within 0\.5 mm \(0\.020 in\)98%/,
    /Tool load over 1\.2× optimal in 2 places/, /Feed is slowed in 1 window/, /G41 on line 12/, /Left for another operation/, /pocket corners/,
    /program · T13 0\.4994 in flat/, /Holder size was estimated \(BT30-ER32-70\)/, /Ramps steeper than 3°/, /line 9 · X −0\.984 Y −0\.984 Z 0\.474/,
    /Straight-down plunges/, /Overload feeds/, /Full-width slots/, /Cutter compnot used/, /Cycle time15 s/, /Leftover max0\.3307 in/, /36%/,
    /rough\.nc — attached to this run in STEVE/]) {
    assert.match(txt, re);
  }
  assert(!/[{}]/.test(txt), "raw JSON in the results: " + txt.slice(0, 200));
  assert.match(await env.panel.getAttribute("#rough-preview", "src"), /^blob:/);
  const files = (await env.sent("run.file")).map((m) => m.params.name);
  assert.deepStrictEqual(files.sort(), ["check.json", "preview.png"]);
  // switching units re-renders the numbers without fetching again
  await setUnits(env, "mm");
  assert.match(await env.text(R), /Leftover mean0\.420 mm/);
  assert.strictEqual((await env.sent("run.file")).length, 2);
});

test("verdict badge: matches the rows; a FAIL in a check.json program row also overrides 'ready'", async (env) => {
  const clean = Object.assign({}, REVIEW_RESULT, { zmap_gouges: { count: 0 }, rapid_collisions: { count: 0 } });
  await env.open({ results: { adaptive_rough: { state: "succeeded", result: clean, files: ["check.json"] } }, checkJson: SAMPLE });
  await clickRun(env, "rough"); await waitFinal(env, "rough");
  await env.waitText("#rough-results", /Ready|Needs review/);
  assert.strictEqual((await env.text("#rough-results .vbadge")).trim(), "Needs review");
  assert.strictEqual(await env.panel.$("#rough-results .v-override"), null);
  assert.strictEqual(await env.panel.$("#rough-results .gate[data-state='fail']"), null);
  const bad = JSON.parse(JSON.stringify(SAMPLE));
  bad.programs[0].check.holder_hits = { count: 2, max_intrusion: 0.4, first_line: 77 };
  await env.mock((c) => { window.__mock.cfg.checkJson = c; window.__mock.cfg.results.adaptive_rough = { state: "succeeded", result: { verdict: "ready", summary: "All clear." }, files: ["check.json"] }; }, bad);
  await clickRun(env, "rough"); await waitFinal(env, "rough");
  await env.waitText("#rough-results", /All clear/);
  assert.strictEqual((await env.text("#rough-results .vbadge")).trim(), "Failed");
  assert.match(await env.text("#rough-results .v-override"), /even though the result said “Ready to run”/);
  assert.match(await env.text("#rough-results .prog"), /FAILHolder2 found, worst 0\.0157 in, first at line 77/);
});

test("results view tolerates missing fields: legacy dev shape and an empty result", async (env) => {
  await env.open({ results: { adaptive_rough: { state: "succeeded", result: {}, files: [] } } });
  await clickRun(env, "rough"); await waitFinal(env, "rough");
  assert.strictEqual(await env.text("#rough-state"), "Done");
  await env.mock(() => { window.__mock.cfg.results.adaptive_rough = { state: "succeeded", result: null, files: ["check.json"] }; window.__mock.cfg.checkJson = { programs: [{ name: "x" }, { check: { gouges: { count: null } } }] }; });
  await clickRun(env, "rough"); await waitFinal(env, "rough");
  assert.match(await env.text("#rough-results"), /Gougesunknown/);
});

test("failed run: error message, next step, code, and the named field is highlighted with its range", async (env) => {
  const err = { code: "input_out_of_range", message: "Tool diameter 322.58 mm is above 32 mm.", field: "tool_diameter", got: 322.58, allowed: { min: 1, max: 32 }, next_step: "Check the units." };
  await env.open({ results: { adaptive_rough: { state: "failed", error: err, files: [] } } });
  await clickRun(env, "rough"); await waitFinal(env, "rough");
  assert.strictEqual(await env.text("#rough-state"), "Failed");
  const t = await env.text("#rough-err");
  assert.match(t, /Tool diameter 322\.58 mm is above 32 mm\./);
  assert.match(t, /Next: Check the units\./);
  assert.match(t, /Code: input_out_of_range/);
  assert.match(await env.panel.getAttribute("#w-rough-tool_diameter", "class"), /\bbad\b/);
  assert.match(await env.text("#err-rough-tool_diameter"), /Allowed: from 0\.0394 to 1\.2598 in\./);
  await env.waitEnabled("#rough-btn");
  // a failed run with a blocker result shows the verdict and the blocker
  await env.mock(() => { window.__mock.cfg.results.adaptive_rough = { state: "failed", error: { code: "gate_failed", message: "Gouges found.", next_step: "Leave more stock." },
    result: { verdict: "failed", summary: "The roughing cuts into the part.", attention: [{ code: "gouge", severity: "blocker", message: "Cuts 0.12 mm into the part.", where: { line: 880 }, next_step: "Leave more stock." }], zmap_gouges: { count: 3 } }, files: [] }; });
  await clickRun(env, "rough"); await waitFinal(env, "rough");
  assert.strictEqual((await env.text("#rough-results .vbadge")).trim(), "Failed");
  assert.match(await env.text("#rough-results .attn-blocker"), /Must fix \(1\)Cuts 0\.12 mm into the part\.line 880Next: Leave more stock\./);
  assert.match(await env.text("#rough-err"), /Gouges found\.Next: Leave more stock\./);
});

for (const [code, re] of [["rate_limited", /Too many runs in the last minute/], ["caller_not_allowed", /isn't allowed to run that/], ["action_not_found", /doesn't offer this right now/]]) {
  test(`bridge error ${code}: plain message, button re-enabled`, async (env) => {
    await env.open({ callErrors: { adaptive_rough: { code, message: "raw " + code } } });
    await env.panel.click("#rough-btn");
    await env.waitText("#rough-err", re);
    assert.strictEqual(await env.text("#rough-state"), "Not started");
    await env.waitEnabled("#rough-btn");
  });
}

test("missing tool, job and measure actions: sections hidden, plain tool-number fields, no extra runs", async (env) => {
  await env.open({ actions: ["adaptive_rough", "slope_split_finish", "check_program"], schema: "legacy" });
  for (const sel of ["#measure-box", "#job-tools", "#save-row", "#w-pick-rough", "#w-pick-finish", "#w-pick-rest", "#w-pick-chain", "#w-setup-origin"]) {
    assert.strictEqual(await env.panel.isVisible(sel), false, sel + " visible");
  }
  assert.strictEqual(await env.panel.isVisible("#origin-fixed"), true);
  assert.strictEqual(await env.text("#origin-fixed"), "Origin: the model's own origin (as drawn)");
  assert.strictEqual(await env.panel.isVisible("#w-rough-tool_number"), true);
  const opts = await env.panel.$$eval("#f-setup-orientation option", (o) => o.map((x) => x.value));
  assert.deepStrictEqual(opts, ["as_modeled", "flip_x_180", "flip_y_180", "flip_z_180"]);
  assert.strictEqual((await env.sent("run")).length, 0, "runs on load without tool actions");
  await env.panel.fill("#f-rough-tool_number", "13");
  const inputs = await clickRun(env, "rough");
  assert.strictEqual(inputs.tool_number, 13);
  assert(!("origin" in inputs));
  await waitFinal(env, "rough");
  assert.match(await env.text("#rough-setup-line"), /placed as drawn in the model/);
  assert.strictEqual((await env.sent("run", "job.setup")).length, 0);
  await env.panel.click("#tab-finish");
  await env.panel.fill("#f-finish-rest_tool_number", "33");
  const fin = await clickRun(env, "finish");
  assert.strictEqual(fin.rest_tool_number, 33);
  assert(!("tool_number" in fin), "blank tool number must be left out");
});

test("tabs: a missing action hides its tab; allowed:false disables the button with a short reason", async (env) => {
  await env.open({ actions: ["adaptive_rough", "slope_split_finish"], allowed: { slope_split_finish: false } });
  assert.strictEqual(await env.panel.isVisible("#tab-check"), false);
  await env.panel.click("#tab-finish");
  assert.strictEqual(await env.disabled("#finish-btn"), true);
  assert.match(await env.text("#finish-reason"), /Not allowed from this panel/);
  await env.mock(() => window.__mock.pushContext({ doc: null }));
  await env.panel.click("#tab-rough");
  await env.waitText("#rough-reason", /Open the part in STEVE first/);
  assert.strictEqual(await env.disabled("#rough-btn"), true);
});

test("tool picker: fills sizes, rpm and feed in the shown unit and sends the job T", async (env) => {
  await env.open({});
  const opts = await env.panel.$$eval("#pick-rough option", (o) => o.map((x) => x.textContent));
  assert.deepStrictEqual(opts, ["Auto (from tool table)", "T13 · 1/2\" flat endmill", "T5 · 1/2\" bull, 0.03\" radius"]);
  const balls = await env.panel.$$eval("#pick-finish option", (o) => o.map((x) => x.textContent));
  assert.deepStrictEqual(balls, ["Auto (from tool table)", "T20 · 6 mm ball", "T33 · 3 mm ball"]);
  assert.strictEqual(await env.panel.isVisible("#w-rough-tool_number"), false);
  let inputs = await clickRun(env, "rough");
  assert(!("tool_number" in inputs), "Auto must send no tool_number");
  await waitFinal(env, "rough");
  await env.panel.selectOption("#pick-rough", "tl-bull-12");
  assert.strictEqual(await env.panel.inputValue("#f-rough-tool_diameter"), "0.5");
  assert.strictEqual(await env.panel.inputValue("#f-rough-corner_radius"), "0.03");
  assert.strictEqual(await env.panel.inputValue("#f-rough-flute_length"), "1.25");
  assert.strictEqual(await env.panel.inputValue("#f-rough-rpm"), "7500");
  assert.strictEqual(await env.panel.inputValue("#f-rough-feed"), "135");
  await env.panel.selectOption("#pick-rough", "tl-flat-12");
  assert.strictEqual(await env.panel.inputValue("#f-rough-tool_type"), "flat");
  inputs = await clickRun(env, "rough");
  assert.strictEqual(inputs.tool_number, 13);
  assert.strictEqual(inputs.tool_type, "flat");
  assert.strictEqual(inputs.corner_radius, 0);
  assert.strictEqual(inputs.rpm, 8000);
  assert(close(inputs.flute_length * 25.4, 31.75));
  assert.deepStrictEqual(CATALOG.validate("adaptive_rough", inputs, true), []);
  await waitFinal(env, "rough");
  await env.panel.click("#tab-finish");
  await env.panel.selectOption("#pick-finish", "tl-ball-3");
  await env.panel.selectOption("#pick-rest", "tl-ball-3");
  await setUnits(env, "mm");
  assert.strictEqual(await env.panel.inputValue("#f-finish-tool_diameter"), "3");
  assert.strictEqual(await env.panel.inputValue("#f-finish-feed"), "1000");
  inputs = await clickRun(env, "finish");
  assert.strictEqual(inputs.tool_number, 33);
  assert.strictEqual(inputs.rest_tool_number, 33);
  assert.strictEqual(inputs.tool_diameter, 3);
  assert.deepStrictEqual(CATALOG.validate("slope_split_finish", inputs, true), []);
});

test("renumber: duplicate_t and out-of-range in plain words; success updates the T everywhere", async (env) => {
  await env.open({});
  assert.strictEqual(await env.panel.isVisible("#job-tools"), true);
  assert.match(await env.text("#job-tools"), /Changing a T number here changes it in every program for this job\./);
  assert.strictEqual(await env.panel.inputValue("#jobt-tl-flat-12"), "13");
  await env.panel.fill("#jobt-tl-flat-12", "5");
  await env.panel.press("#jobt-tl-flat-12", "Enter");
  await env.waitText("#jobt-err-tl-flat-12", /T5 is already used by 1\/2" bull, 0\.03" radius\. Pick a free number\./);
  assert.strictEqual(await env.panel.inputValue("#jobt-tl-flat-12"), "13");
  const r1 = await env.sent("run", "job.renumber");
  assert.deepStrictEqual(r1[0].params.inputs, { document_id: "doc-42", tool_id: "tl-flat-12", t: 5 });
  await env.panel.fill("#jobt-tl-flat-12", "15");
  await env.panel.press("#jobt-tl-flat-12", "Enter");
  await env.waitText("#jobt-err-tl-flat-12", /from 1 to 12 \(the machine has 12 pockets\)/);
  assert.strictEqual((await env.sent("run", "job.renumber")).length, 1, "out-of-range number was sent");
  // the server's out_of_range code also reads plainly
  await env.mock(() => { window.__mock.cfg.pockets = 6; });
  await env.panel.fill("#jobt-tl-flat-12", "9");
  await env.panel.press("#jobt-tl-flat-12", "Enter");
  await env.waitText("#jobt-err-tl-flat-12", /T9 isn't a pocket on this machine\. Use 1 to 12\./);
  await env.mock(() => { window.__mock.cfg.pockets = 12; });
  await env.panel.fill("#jobt-tl-flat-12", "7");
  await env.panel.press("#jobt-tl-flat-12", "Enter");
  await env.waitText("#jobt-ok-tl-flat-12", /Now T7 in every program for this job\./);
  const opts = await env.panel.$$eval("#pick-rough option", (o) => o.map((x) => x.textContent));
  assert(opts.includes("T7 · 1/2\" flat endmill"), opts.join("|"));
  await env.panel.selectOption("#pick-rough", "tl-flat-12");
  const inputs = await clickRun(env, "rough");
  assert.strictEqual(inputs.tool_number, 7);
});

test("measure + blank size: per-side extras worked out, shown, sent; errors and stale measure", async (env) => {
  await env.open({});
  assert.strictEqual(await env.panel.isVisible("#measure-box"), true);
  await env.panel.click("#measure-btn");
  await env.waitText("#model-size", /Model: 10\.000 × 6\.496 × 2\.165 in/);
  assert.match(await env.text("#block-size"), /10\.080 × 6\.576 × 2\.245 in/);
  assert.match(await env.text("#rough-setup-line"),
    /^Blank 10\.080 × 6\.576 × 2\.245 in, origin at the stock bottom centre \(Z0 = stock bottom\): X ±5\.040, Y ±3\.288, Z 0 to 2\.245\. Orientation: as modeled\.$/);
  await env.panel.fill("#f-blank-blank_x", "10.25");
  await env.panel.fill("#f-blank-blank_y", "6.75");
  await env.panel.fill("#f-blank-blank_z", "2.25");
  assert.strictEqual(await env.panel.inputValue("#f-setup-stock_x"), "0.125");
  assert.strictEqual(await env.panel.inputValue("#f-setup-stock_y"), "0.127");
  assert.strictEqual(await env.panel.inputValue("#f-setup-stock_top"), "0.0446");
  assert.match(await env.text("#block-size"), /10\.250 × 6\.750 × 2\.250 in/, "stock block must equal the blank");
  assert.strictEqual(await env.disabled("#f-setup-stock_x"), true);
  const inputs = await clickRun(env, "rough");
  const mm = CATALOG.toServerMm(inputs);
  assert(close(mm.stock_x, 3.175, 1e-9) && close(mm.stock_y, 3.225, 1e-9) && close(mm.stock_top, 57.15 - 55 - 1.016, 1e-9), JSON.stringify(mm));
  assert(close(mm.stock_bottom, 1.016), "bottom stays as typed");
  assert.deepStrictEqual(CATALOG.validate("adaptive_rough", inputs, true), []);
  await waitFinal(env, "rough");
  // origin variants in the setup sentence
  await env.panel.selectOption("#f-setup-origin", "stock_top_centre");
  assert.match(await env.text("#rough-setup-line"), /origin at the stock top centre \(Z0 = stock top\): X ±5\.125, Y ±3\.375, Z −2\.250 to 0\./);
  await env.panel.selectOption("#f-setup-origin", "model_origin");
  assert.match(await env.text("#rough-setup-line"), /^Blank 10\.250 × 6\.750 × 2\.250 in, placed as drawn in the model/);
  // blank smaller than the model
  await env.panel.fill("#f-blank-blank_x", "9");
  await env.panel.click("#rough-btn");
  assert.match(await env.text("#err-blank-blank_x"), /Blank X is smaller than the model \(10 in\)\./);
  // too much on top
  await env.panel.fill("#f-blank-blank_x", "10.25");
  await env.panel.fill("#f-blank-blank_z", "3.5");
  await env.panel.click("#rough-btn");
  assert.match(await env.text("#err-blank-blank_z"), /Extra on top \(from blank Z\) must be from 0 to 1 in\./);
  // shorter than model + bottom allowance: plain error on Blank Z, nothing sent
  const sentBefore = (await env.sent("run", "adaptive_rough")).length;
  await env.panel.fill("#f-blank-blank_z", "2.2");
  await env.panel.click("#rough-btn");
  assert.match(await env.text("#err-blank-blank_z"), /^Blank Z: the blank is shorter than the model plus the bottom allowance \(2\.2054 in\)\.$/);
  assert.match(await env.panel.getAttribute("#w-blank-blank_z", "class"), /\bbad\b/);
  assert.strictEqual((await env.sent("run", "adaptive_rough")).length, sentBefore, "a run was sent with a too-short blank");
  // with no bottom allowance the same blank works
  await env.panel.fill("#f-setup-stock_bottom", "0");
  assert.strictEqual(await env.panel.inputValue("#f-setup-stock_top"), "0.0346");
  await env.panel.fill("#f-setup-stock_bottom", "0.04");
  // orientation change makes the measure old
  await env.panel.fill("#f-blank-blank_z", "2.25");
  await env.panel.selectOption("#f-setup-orientation", "rot_x_90");
  assert.match(await env.text("#model-size"), /old: orientation changed, measure again/);
  await env.panel.click("#rough-btn");
  assert.match(await env.text("#rough-errors"), /press Measure model/);
  const tips = await env.panel.$$eval("#f-setup-orientation option", (o) => o.map((x) => x.textContent));
  assert(tips.includes("Tip onto side: +90° about X") && tips.includes("Tip onto side: −90° about Y"), tips.join("|"));
  // no measure: the sentence says model plus allowances
  await env.panel.fill("#f-blank-blank_x", ""); await env.panel.fill("#f-blank-blank_y", ""); await env.panel.fill("#f-blank-blank_z", "");
  await env.panel.selectOption("#f-setup-origin", "stock_bottom_centre");
  assert.strictEqual(await env.text("#rough-setup-line"),
    "Blank: the model plus 0.04 in per side, 0.04 in on top and 0.04 in on bottom, origin at the stock bottom centre (Z0 = stock bottom). Orientation: tip onto side: +90° about X.");
});

test("job setup: prefilled from job.get, saved with job.setup after the run starts, skipped when unchanged", async (env) => {
  const setup = { orientation: "flip_x_180", units: "mm", origin: "stock_top_centre", stock_xy: 2, stock_x: null, stock_y: 3,
    stock_top: 1.5, stock_bottom: 0.5, floor_z: 4, blank: null };
  await env.open({ jobSetup: setup });
  assert.strictEqual(await env.panel.inputValue("#units"), "mm");
  assert.strictEqual(await env.panel.inputValue("#f-setup-orientation"), "flip_x_180");
  assert.strictEqual(await env.panel.inputValue("#f-setup-origin"), "stock_top_centre");
  assert.strictEqual(await env.panel.inputValue("#f-setup-stock_xy"), "2");
  assert.strictEqual(await env.panel.inputValue("#f-setup-stock_x"), "");
  assert.strictEqual(await env.panel.inputValue("#f-setup-stock_y"), "3");
  assert.strictEqual(await env.panel.inputValue("#f-setup-floor_z"), "4");
  const in1 = await clickRun(env, "rough");
  assert.strictEqual(in1.stock_y, 3); assert.strictEqual(in1.units, "mm"); assert.strictEqual(in1.origin, "stock_top_centre");
  await waitFinal(env, "rough");
  assert.strictEqual((await env.sent("run", "job.setup")).length, 0, "unchanged setup was saved again");
  await env.panel.fill("#f-setup-stock_xy", "2.5");
  await env.panel.evaluate(() => { document.getElementById("rough-btn").click(); window.parent.postMessage({ marker: "m" }, "*"); });
  await env.settle();
  const order = await env.mock(() => window.__mock.log.filter((e) => e.dir === "in").map((e) => e.data.marker || (e.data.params && e.data.params.action)));
  const iRun = order.lastIndexOf("adaptive_rough"), iSetup = order.lastIndexOf("job.setup");
  assert(iRun >= 0 && iSetup > iRun, "job.setup must go after the run: " + order.join(","));
  const saved = (await env.sent("run", "job.setup")).pop().params.inputs;
  assert.deepStrictEqual(saved, { document_id: "doc-42", setup: Object.assign({}, setup, { stock_xy: 2.5 }) });
  await waitFinal(env, "rough");
  // inch: values are stored in mm
  await setUnits(env, "inch");
  await env.panel.click("#save-setup");
  await env.waitText("#save-state", /Setup saved for this part\./);
  const s2 = (await env.sent("run", "job.setup")).pop().params.inputs.setup;
  assert.strictEqual(s2.units, "inch"); assert.strictEqual(s2.stock_xy, 2.5); assert.strictEqual(s2.stock_y, 3);
});

test("job setup with inch values reloads as clean inch numbers; skipped quietly without job.setup", async (env) => {
  await env.open({ jobSetup: { orientation: "as_modeled", units: "inch", stock_xy: 1.016, stock_x: 3.175, stock_y: null, stock_top: 1.016, stock_bottom: 0, floor_z: 0, blank: { x: 260.35, y: null, z: null } } });
  assert.strictEqual(await env.panel.inputValue("#f-setup-stock_xy"), "0.04");
  assert.strictEqual(await env.panel.inputValue("#f-blank-blank_x"), "10.25");
  assert.strictEqual(await env.panel.isVisible("#blank-partial"), true, "partial blank hint missing");
  assert.strictEqual(await env.panel.inputValue("#f-setup-stock_bottom"), "0");
  await env.ctx.close();
  const env2 = await newEnv();
  try {
    await env2.open({ actions: ["adaptive_rough", "slope_split_finish", "check_program", "model.measure", "tools.list", "job.get", "job.renumber"], jobSetup: { units: "mm" } });
    assert.strictEqual(await env2.panel.inputValue("#units"), "inch", "prefilled without job.setup");
    assert.strictEqual(await env2.panel.isVisible("#save-row"), false);
    await clickRun(env2, "rough"); await waitFinal(env2, "rough");
    assert.strictEqual((await env2.sent("run", "job.setup")).length, 0);
    const problems = await env2.clean();
    assert.deepStrictEqual(problems, []);
  } finally { await env2.ctx.close(); }
}, { ownContext: true });

test("partial blank: not used, hint shown, job.setup gets blank null; all three filled -> {x,y,z} in mm", async (env) => {
  await env.open({});
  await env.panel.click("#measure-btn");
  await env.waitText("#model-size", /Model/);
  assert.strictEqual(await env.panel.isVisible("#blank-partial"), false);
  await env.panel.fill("#f-blank-blank_x", "10.25");
  assert.strictEqual(await env.panel.isVisible("#blank-partial"), true);
  assert.strictEqual((await env.text("#blank-partial")).trim(), "Fill all three to use the blank size.");
  assert.strictEqual(await env.disabled("#f-setup-stock_x"), false, "a partial blank must not drive the extras");
  await env.panel.fill("#f-blank-blank_y", "6.75");
  assert.strictEqual(await env.panel.isVisible("#blank-partial"), true);
  const inputs = await clickRun(env, "rough");
  assert(!("stock_x" in inputs) && !("stock_y" in inputs), "partial blank sent extras: " + JSON.stringify(inputs));
  assert.strictEqual(inputs.stock_top, 0.04);
  await waitFinal(env, "rough");
  const s1 = (await env.sent("run", "job.setup")).pop().params.inputs.setup;
  assert.strictEqual(s1.blank, null, "partial blank sent to job.setup");
  await env.panel.fill("#f-blank-blank_z", "2.25");
  assert.strictEqual(await env.panel.isVisible("#blank-partial"), false);
  assert.strictEqual(await env.disabled("#f-setup-stock_x"), true);
  await env.panel.click("#save-setup");
  await env.waitText("#save-state", /Setup saved/);
  const s2 = (await env.sent("run", "job.setup")).pop().params.inputs.setup;
  assert.deepStrictEqual(s2.blank, { x: 260.35, y: 171.45, z: 57.15 });
  // a zero axis is not a usable blank either
  await env.panel.fill("#f-blank-blank_z", "0");
  await env.panel.click("#save-setup");
  await env.settle();
  assert.strictEqual((await env.sent("run", "job.setup")).pop().params.inputs.setup.blank, null);
});

test("server error fields: 'setup.' and 'inputs.' prefixes are stripped before highlighting", async (env) => {
  await env.open({ setupError: { code: "input_out_of_range", field: "setup.stock_xy", message: "stock_xy is above 25.4 mm.", next_step: "Use less extra per side." },
    results: { adaptive_rough: { state: "failed", error: { code: "input_out_of_range", field: "inputs.stepdown", message: "stepdown too big" }, files: [] } } });
  await env.panel.click("#save-setup");
  await env.waitText("#save-state", /Couldn't save the setup: stock_xy is above 25\.4 mm\./);
  assert.match(await env.panel.getAttribute("#w-setup-stock_xy", "class"), /\bbad\b/);
  assert.strictEqual(await env.text("#err-setup-stock_xy"), "Allowed: from 0 to 1 in.");
  await env.mock(() => { window.__mock.cfg.setupError = { code: "input_out_of_range", field: "setup.blank", message: "The blank needs x, y and z above 0." }; });
  await env.panel.click("#save-setup");
  await env.waitText("#err-blank-blank_y", /The blank needs x, y and z above 0\./);
  assert.match(await env.panel.getAttribute("#w-blank-blank_z", "class"), /\bbad\b/);
  await env.mock(() => { window.__mock.cfg.setupError = { code: "input_out_of_range", field: "setup.blank.x", message: "Blank x must be above 0." }; });
  await env.panel.click("#save-setup");
  await env.waitText("#err-blank-blank_x", /Blank x must be above 0\./);
  await clickRun(env, "rough"); await waitFinal(env, "rough");
  assert.match(await env.panel.getAttribute("#w-rough-stepdown", "class"), /\bbad\b/);
  assert.strictEqual(await env.text("#err-rough-stepdown"), "Allowed: from 0.004 to 1 in.");
});

test("attention items with code area_left_for_next_op go in 'Left for another operation', not 'Good to know'", async (env) => {
  const result = { verdict: "needs_review", summary: "Check one thing.", zmap_gouges: { count: 0 },
    attention: [
      { code: "steep_ramp", severity: "review", message: "3 ramps are steeper than 3°.", where: { line: 9 }, next_step: "Check the entry moves." },
      { code: "area_left_for_next_op", severity: "info", message: "Pocket corners are narrower than the ball.", where: { program: "finish.nc", line: 50, x: 25.4, y: 0, z: -2.54 } },
      { code: "area_left_for_next_op", severity: "info", message: "Slot end left." },
    ],
    areas_left: ["old-style area"] };
  await env.open({ results: { slope_split_finish: { state: "succeeded", result, files: [] } } });
  await env.panel.click("#tab-finish");
  await clickRun(env, "finish"); await waitFinal(env, "finish");
  await env.waitText("#finish-results", /Left for another operation/);
  const groups = await env.panel.$$eval("#finish-results .attn h4", (hs) => hs.map((h) => h.textContent));
  assert.deepStrictEqual(groups, ["Please review (1)"], "left-for-next-op items shown as attention: " + groups);
  const lists = await env.panel.$$eval("#finish-results h4", (hs) => hs.filter((h) => h.textContent === "Left for another operation")
    .map((h) => [...h.nextElementSibling.querySelectorAll("li")].map((li) => li.textContent)));
  assert.deepStrictEqual(lists, [["Pocket corners are narrower than the ball. · finish.nc · line 50 · X 1.000 Y 0.000 Z −0.100", "Slot end left.", "old-style area"]]);
});

test("check tab: one plain line, and check runs pushed to the panel render per program", async (env) => {
  await env.open({ checkJson: SAMPLE });
  await env.panel.click("#tab-check");
  assert.match(await env.text("#pane-check .lead"), /run “Check program” from STEVE's connector menu and pick the program and its origin there\.$/);
  await env.mock(() => window.__mock.pushRun({ id: "chk-1", action: "check_program", state: "succeeded", progress: 1,
    result: { verdict: "ready", summary: "Clean.", attention: [] }, files: ["check.json"] }));
  await env.waitText("#check-runs", /Holder size was estimated/);
  const t = await env.text("#check-runs");
  assert.match(t, /Ready to run/);
  assert.match(t, /program · T13 0\.4994 in flat/);
  assert(!/No check results/.test(await env.panel.$eval("#check-runs", (e) => e.innerText)));
});

for (const width of [300, 450, 600]) {
  for (const theme of ["light", "dark"]) {
    test(`layout ${width}px ${theme}: no horizontal overflow on any tab, screenshots`, async (env) => {
      await env.open({ width, theme, checkJson: SAMPLE,
        results: { adaptive_rough: { state: "succeeded", result: REVIEW_RESULT, files: ["rough.nc", "check.json", "preview.png"] } } });
      await env.panel.click("#measure-btn");
      await env.waitText("#model-size", /Model/);
      await clickRun(env, "rough"); await waitFinal(env, "rough");
      await env.panel.waitForSelector("#rough-preview:not([hidden])");
      await env.panel.evaluate(() => { document.querySelectorAll("details").forEach((d) => (d.open = true)); });
      await env.mock(() => window.__mock.pushRun({ id: "chk-1", action: "check_program", state: "succeeded", progress: 1, result: { verdict: "needs_review", summary: "3 steep ramps.", attention: [] }, files: ["check.json"] }));
      const shots = [];
      for (const tab of ["rough", "finish", "check"]) {
        await env.panel.click("#tab-" + tab);
        await env.page.waitForTimeout(60);
        const m = await env.panel.evaluate(() => {
          const d = document.documentElement, b = document.body;
          const wide = [...document.querySelectorAll("body *")].filter((e) => e.getBoundingClientRect().right > d.clientWidth + 0.5 && e.offsetParent !== null).map((e) => e.id || e.className || e.tagName).slice(0, 5);
          return { sw: d.scrollWidth, cw: d.clientWidth, bsw: b.scrollWidth, bcw: b.clientWidth, h: d.scrollHeight, wide };
        });
        assert(m.sw <= m.cw && m.bsw <= m.bcw, `${tab}: scrollWidth ${m.sw} > clientWidth ${m.cw}; wide: ${m.wide}`);
        assert.deepStrictEqual(m.wide, [], tab + ": elements past the right edge");
        const cut = await env.panel.evaluate(() => {
          const ctx = document.createElement("canvas").getContext("2d");
          return [...document.querySelectorAll("select")].filter((s) => s.offsetParent !== null).map((s) => {
            const cs = getComputedStyle(s);
            ctx.font = cs.fontWeight + " " + cs.fontSize + " " + cs.fontFamily;
            const room = s.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight) - 18;
            const longest = Math.max(...[...s.options].map((o) => ctx.measureText(o.textContent).width));
            return longest > room ? s.id + " (" + Math.round(longest) + " > " + Math.round(room) + ")" : null;
          }).filter(Boolean);
        });
        assert.deepStrictEqual(cut, [], tab + ": select text cut off");
        await env.mock((h) => { window.__mock.frame.height = h; }, m.h);
        await env.page.setViewportSize({ width: Math.max(1000, width + 20), height: Math.min(m.h + 20, 6000) });
        const file = path.join(SCREENS, `panel_${width}_${theme}_${tab}.png`);
        await (await env.page.$("#panel")).screenshot({ path: file });
        shots.push(path.basename(file));
      }
      return shots.join(", ");
    });
  }
}

test("dev.html harness: loads network-free, answers every method, rough and finish runs pass its server-rule validator", async (env) => {
  await env.open({}, { url: DEV_URL, noReady: true });
  await env.panel.waitForSelector("#pick-rough option[value='tl-flat-12']", { state: "attached" });
  await env.page.waitForTimeout(300);
  await env.panel.click("#measure-btn");
  await env.waitText("#model-size", /10\.000 × 6\.496 × 2\.165 in/, 4000);
  await env.waitEnabled("#rough-btn");
  await env.panel.click("#rough-btn");
  await env.waitText("#rough-state", /^Done$/, 8000);
  assert.match(await env.text("#rough-results"), /Ready to run/);
  await env.page.selectOption("#outcome", "needs_review");
  await env.panel.click("#rough-btn");
  await env.waitText("#rough-results", /Please review \(2\)/, 8000);
  assert.strictEqual((await env.text("#rough-results .vbadge")).trim(), "Needs review");
  assert.strictEqual(await env.panel.$("#rough-results .gate[data-state='fail']"), null, "dev needs_review has a FAIL row");
  await env.panel.click("#tab-finish");
  await env.panel.selectOption("#pick-rest", "tl-ball-3");
  await env.panel.click("#finish-btn");
  await env.waitText("#finish-state", /^Done$/, 8000);
  await env.waitText("#finish-results", /Please review \(2\)/);
  assert.strictEqual((await env.text("#finish-results .vbadge")).trim(), "Needs review");
  assert.strictEqual(await env.panel.$("#finish-results .gate[data-state='fail']"), null, "dev finish needs_review has a FAIL row");
  assert.match(await env.text("#finish-results"), /finish\.nc/);
  assert.match(await env.text("#finish-results"), /rest\.nc/);
  await env.panel.fill("#jobt-tl-ball-6", "5");
  await env.panel.press("#jobt-tl-ball-6", "Enter");
  await env.waitText("#jobt-err-tl-ball-6", /T5 is already used by 1\/2" bull/);
  await env.page.click("#check-btn");
  await env.waitText("#check-runs", /Needs review/);
  await env.page.click("#theme");
  await env.panel.waitForFunction(() => document.documentElement.dataset.theme === "dark");
  await env.page.waitForTimeout(200);
});

// ------------------------------------------------------------------ viewer --
function viewFixture() {
  const bin = path.join(TESTDATA, "view_fixture.bin");
  const js = path.join(TESTDATA, "view_fixture.json");
  if (!fs.existsSync(bin) || !fs.existsSync(js)) throw new Error("fixture view.bin/view.json missing (write connector/testdata/view_fixture.* with connector/view.py)");
  return { bin: fs.readFileSync(bin).toString("base64"), json: JSON.parse(fs.readFileSync(js, "utf8")) };
}
function viewerCfg(fx) {
  return { results: { adaptive_rough: { state: "succeeded", result: {}, files: ["rough.nc", "check.json", "preview.png", "view.bin", "view.json"] } }, checkJson: SAMPLE, viewBinBase64: fx.bin, viewJson: fx.json };
}
// pixel fingerprint of the viewer canvas (WebGL via the stored gl, 2D via getImageData)
async function canvasFp(env) {
  return env.panel.$eval(".v3d-canvas", (c) => {
    let data;
    if (c.__v3dgl) {
      data = new Uint8Array(c.width * c.height * 4);
      c.__v3dgl.readPixels(0, 0, c.width, c.height, c.__v3dgl.RGBA, c.__v3dgl.UNSIGNED_BYTE, data);
    } else {
      data = new Uint8ClampedArray(c.getContext("2d").getImageData(0, 0, c.width, c.height).data);
    }
    const colors = new Set();
    let sum = 0;
    for (let i = 0; i < data.length; i += 4) {
      colors.add((data[i] >> 3) + "," + (data[i + 1] >> 3) + "," + (data[i + 2] >> 3));
      sum = (sum + data[i] * 3 + data[i + 1] * 7 + data[i + 2] * 11) % 1000000007;
    }
    return { colors: colors.size, sum, mode: c.dataset.mode };
  });
}
async function openViewer(env, opts) {
  await env.open(viewerCfg(viewFixture()), opts);
  await clickRun(env, "rough");
  await waitFinal(env, "rough");
  await env.panel.waitForSelector(".v3d-canvas", { timeout: 5000 });
  await env.panel.waitForFunction(() => {
    const c = document.querySelector(".v3d-canvas");
    return c && c.dataset.drawn === "1";
  }, null, { timeout: 5000 });
}

test("viewer: WebGL draws non-blank canvas from a fixture view.bin", async (env) => {
  await openViewer(env);
  const fp = await canvasFp(env);
  assert.strictEqual(fp.mode, "webgl", "viewer did not use WebGL: " + fp.mode);
  assert(fp.colors > 3, "WebGL canvas nearly blank (distinct colors): " + fp.colors);
  await (await env.page.$("#panel")).screenshot({ path: path.join(SCREENS, "viewer_webgl.png") });
  return "colors=" + fp.colors;
});

test("viewer: forced 2D fallback draws a non-blank 2D canvas", async (env) => {
  await openViewer(env, { init: "(() => { const g = HTMLCanvasElement.prototype.getContext; HTMLCanvasElement.prototype.getContext = function (t, o) { if (String(t) === 'webgl' || String(t) === 'experimental-webgl') return null; return g.call(this, t, o); }; })();" });
  const fp = await canvasFp(env);
  assert.strictEqual(fp.mode, "2d", "no automatic 2D fallback: " + fp.mode);
  assert(fp.colors > 3, "2D fallback nearly blank (distinct colors): " + fp.colors);
  await (await env.page.$("#panel")).screenshot({ path: path.join(SCREENS, "viewer_fallback.png") });
  return "colors=" + fp.colors;
});

test("viewer: non-panel run shows the note", async (env) => {
  await env.open({ checkJson: SAMPLE });
  await env.panel.click("#tab-check");
  await env.mock(() => window.__mock.pushRun({ id: "chk-9", action: "check_program", state: "succeeded", progress: 1,
    result: { verdict: "ready", summary: "Clean.", attention: [] }, files: ["check.json", "preview.png", "view.bin", "view.json"] }));
  await env.waitText("#check-runs", /not started in this panel/, 5000);
  assert.strictEqual(await env.panel.$(".v3d-canvas"), null, "a viewer canvas appeared for a run the panel did not start");
});

test("viewer: layer toggles change pixels", async (env) => {
  await openViewer(env);
  const before = await canvasFp(env);
  await env.panel.uncheck(".v3d-stock");
  await env.panel.waitForTimeout(150);
  const after = await canvasFp(env);
  assert(before.sum !== after.sum, "hiding the stock layer did not change the canvas");
  await env.panel.check(".v3d-stock");
  await env.panel.uncheck(".v3d-path");
  await env.panel.waitForTimeout(150);
  const after2 = await canvasFp(env);
  assert(after.sum !== after2.sum, "hiding the path layer did not change the canvas");
  await env.panel.check(".v3d-path");
  await env.panel.uncheck(".v3d-markers");
  await env.panel.waitForTimeout(150);
  const after3 = await canvasFp(env);
  assert(after2.sum !== after3.sum, "hiding the markers layer did not change the canvas");
  return "sums " + before.sum + "/" + after.sum + "/" + after2.sum + "/" + after3.sum;
});

test("viewer: no network, storage or console errors while showing a run", async (env) => {
  await openViewer(env);
  const files = (await env.sent("run.file")).map((m) => m.params.name);
  assert(files.includes("view.bin") && files.includes("view.json"), "viewer did not fetch both files: " + files.join(","));
});

test("viewer: panel bundle <= 2 MB", () => {
  const files = [];
  (function walk(d) { for (const n of fs.readdirSync(d)) { const p = path.join(d, n); fs.statSync(p).isDirectory() ? walk(p) : files.push(p); } })(PANEL_DIR);
  const total = files.reduce((s, f) => s + fs.statSync(f).size, 0);
  assert(files.length <= 50, "too many files: " + files.length);
  assert(total <= 2 * 1024 * 1024, "too big: " + total);
  return { files: files.length, bytes: total };
});

// ================================================================== runner ==
(async () => {
  browser = await chromium.launch();
  const t0 = Date.now();
  const only = process.env.ONLY ? new RegExp(process.env.ONLY) : null;
  for (const t of tests.filter((x) => !only || only.test(x.name))) {
    let env = null, note = "";
    const start = Date.now();
    try {
      if (t.fn.length === 0) note = await t.fn();
      else {
        env = await newEnv();
        note = await t.fn(env);
        if (!t.opts.ownContext) {
          const problems = await env.clean();
          assert.deepStrictEqual(problems, [], "bridge rules broken: " + problems.join("; "));
        }
      }
      RESULTS.passed++;
      console.log("PASS  " + t.name + (note ? "  [" + (typeof note === "string" ? note : JSON.stringify(note)) + "]" : "") + "  (" + (Date.now() - start) + " ms)");
    } catch (e) {
      RESULTS.failed++;
      RESULTS.failures.push({ name: t.name, error: e.stack || String(e) });
      console.log("FAIL  " + t.name + "\n      " + String((process.env.STACK ? e.stack : e.message) || e).split("\n").join("\n      "));
    } finally {
      if (env) await env.ctx.close().catch(() => {});
    }
  }
  await browser.close();
  fs.writeFileSync(path.join(TESTDATA, "panel_default_inputs.json"), JSON.stringify(DEFAULT_INPUTS, null, 2) + "\n");
  console.log(`\n${RESULTS.passed} passed, ${RESULTS.failed} failed, ${tests.length} total (${((Date.now() - t0) / 1000).toFixed(1)} s)`);
  fs.writeFileSync(path.join(SCREENS, "last_run.json"), JSON.stringify(RESULTS, null, 2));
  process.exit(RESULTS.failed ? 1 : 0);
})();
