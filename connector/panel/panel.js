"use strict";
// STEVE panel bridge (docs/steve_panel_bridge.md). No network: all data
// comes from STEVE via postMessage to the parent frame.

let next = 0;
const waiting = new Map();
function call(method, params = {}) {
  const id = ++next;
  window.parent.postMessage({ steve: 1, id, method, params }, "*");
  return new Promise((resolve, reject) => waiting.set(id, { resolve, reject }));
}

let ctx = null;          // context() result
let openDoc = null;      // {id, kind, revision} or null
let runActive = false;

const $ = (id) => document.getElementById(id);

window.addEventListener("message", (event) => {
  const message = event.data;
  if (event.source !== window.parent || !message || message.steve !== 1) return;
  if (message.id !== undefined && waiting.has(message.id)) {
    const { resolve, reject } = waiting.get(message.id);
    waiting.delete(message.id);
    message.error ? reject(message.error) : resolve(message.result);
  } else if (message.event === "event") {
    showEvent(message.name, message.data);
  } else if (message.event === "run") {
    showRun(message.run);
  } else if (message.event === "context") {
    applyTheme(message.context.theme);
    setDocument(message.context.document);
  }
});

function applyTheme(theme) {
  document.body.classList.toggle("dark", theme === "dark");
}

function setDocument(doc) {
  openDoc = doc;
  $("doc-line").textContent = doc
    ? "Open document: " + doc.kind + " (id " + doc.id + ")"
    : "No open document. Open a STEP model in STEVE to enable roughing.";
  updateButton();
}

function updateButton() {
  $("rough-open").disabled = runActive || !openDoc;
}

// ------------------------------------------------------------ form ------
const NUM_FIELDS = ["tool_diameter", "corner_radius", "stock_xy", "stock_top",
                    "stock_bottom", "floor_z", "stepdown", "optimal_load",
                    "stock_to_leave", "rpm", "feed"];

$("rough-form").addEventListener("submit", (event) => {
  event.preventDefault();
  if (!openDoc || runActive) return;
  const inputs = { model: { document_id: openDoc.id, revision: openDoc.revision } };
  const form = new FormData($("rough-form"));
  for (const key of NUM_FIELDS) {
    const raw = form.get(key);
    if (raw !== null && raw !== "") inputs[key] = Number(raw);
  }
  for (const key of ["orientation", "tool_type", "units"]) {
    inputs[key] = form.get(key);
  }
  // started in the click handler itself with context().document so STEVE
  // can send the open document without asking (when allowed):
  call("run", { action: "adaptive_rough", inputs, note: "from panel" })
    .then((run) => showRun(run))
    .catch((err) => { $("run-message").textContent = "Could not start the run: " + (err.message || err.code); });
});

$("cancel-btn").addEventListener("click", () => {
  const id = $("run-card").dataset.runId;
  if (id) call("cancel", { id }).catch(() => {});
});

// ------------------------------------------------------------- runs -----
const DONE = ["succeeded", "failed", "rejected", "cancelled", "expired"];

function showRun(run) {
  if (!run || !run.id) return;
  const card = $("run-card");
  card.classList.remove("hidden");
  card.dataset.runId = run.id;
  runActive = !DONE.includes(run.state);
  updateButton();

  $("run-state").textContent =
    run.state === "awaiting_confirmation"
      ? "Waiting for you to confirm in STEVE"
      : run.state;
  $("run-progress").value = run.progress || 0;
  $("run-message").textContent = run.message || "";
  $("cancel-btn").style.display = runActive ? "" : "none";

  if (run.state === "succeeded" && run.result) {
    const s = run.result;
    $("run-summary").textContent = JSON.stringify(s, null, 2);
    $("run-summary").classList.remove("hidden");
    showPreview(run.id);
  } else if (run.error) {
    $("run-summary").textContent =
      "Run failed (" + run.error.code + "): " + (run.error.message || "");
    $("run-summary").classList.remove("hidden");
  }
}

function showPreview(id) {
  call("run.file", { id, name: "preview.png" })
    .then((f) => {
      const url = URL.createObjectURL(f.blob);
      const img = $("run-preview");
      img.src = url;
      img.classList.remove("hidden");
    })
    .catch(() => {});
}

// ------------------------------------------------------------ events ----
function showEvent(name, data) {
  if (name === "engine_state" && data) {
    const pill = $("engine-state");
    pill.textContent = data.state +
      (data.action ? " · " + data.action : "");
    pill.className = "pill " + data.state;
    if (data.state === "busy" && data.progress != null) {
      $("run-progress").value = data.progress;
    }
  }
}

// ------------------------------------------------------------- load -----
(async function load() {
  try {
    ctx = await call("context");
    applyTheme(ctx.theme);
    setDocument(ctx.document || null);
    const latest = await call("events");
    for (const item of latest || []) showEvent(item.name, item.data);
    const actions = await call("actions");
    const rough = (actions || []).find((a) => a.name === "adaptive_rough");
    if (rough && rough.allowed === false) {
      $("rough-open").disabled = true;
      $("rough-open").title = "Not allowed for this panel";
    }
  } catch (err) {
    $("doc-line").textContent = "Not connected to STEVE: " + (err.message || err.code);
  }
})();
