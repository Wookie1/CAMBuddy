# STEVE panel bridge (from the steve-connectors skill, 2026-10-18)

Panel = index.html + scripts/styles/images at relative paths (<= 50 files, 2 MB). Sandboxed on its own origin:
no network (fetch/XHR/WebSocket/remote images blocked: bundle everything), no storage/cookies/popups, cannot
navigate (a panel that navigates is closed). Fills the pane, ~300-600 px wide. Follow context.theme ("light"/"dark").

The panel posts to window.parent and listens for answers and pushes:

```js
let next = 0;
const waiting = new Map();
function call(method, params = {}) {
  const id = ++next;
  window.parent.postMessage({ steve: 1, id, method, params }, '*');
  return new Promise((resolve, reject) => waiting.set(id, { resolve, reject }));
}
window.addEventListener('message', (event) => {
  const message = event.data;
  if (event.source !== window.parent || !message || message.steve !== 1) return;
  if (message.id !== undefined && waiting.has(message.id)) {
    const { resolve, reject } = waiting.get(message.id);
    waiting.delete(message.id);
    message.error ? reject(message.error) : resolve(message.result);
  } else if (message.event === 'event') {
    show(message.name, message.data);            // a connector event, as it arrives
  } else if (message.event === 'run') {
    showRun(message.run);                         // a run this panel started, as it changes
  } else if (message.event === 'context') {
    applyTheme(message.context.theme);
  }
});
```

| Method | Params | Result |
| --- | --- | --- |
| context | none | {panel, connector, document, theme}; document = open STEVE doc {id, kind, revision} only when the connector has a document-taking action allowed for the panel, else null |
| actions | none | this connector's actions: id, name, title, inputs, allowed (for panel), needs_confirmation, sends_open_document_on_click |
| events | none | latest of each event: {name, data, at} |
| run | {action, inputs, note} | {id, state, progress, message, result, error, files}; then `run` pushes until it ends |
| run.get | {id} | a run this panel started |
| run.file | {id, name} | {name, media_type, bytes, blob} (<= 20 MB); show with URL.createObjectURL(blob) |
| cancel | {id} | cancels a run this panel started |

Errors: {code, message}: caller_not_allowed, rate_limited (<= 20 runs/min), action_not_found.
A run needing confirmation is `awaiting_confirmation` until the person confirms in STEVE: show it plainly
("Waiting for you to confirm in STEVE"). A run sending a STEVE document passes {"document_id", "revision"}; it goes
at once only if started in the click handler itself with context().document (STEVE checks the click was real).
On load: context, then events, then actions. Keep a button disabled from click until its run ends
(succeeded, failed, rejected, cancelled, expired), including while awaiting confirmation.
