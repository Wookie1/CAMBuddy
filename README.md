# CAMBuddy

CAMBuddy makes CNC toolpaths from a STEP model: adaptive (constant-engagement)
roughing, slope-split ball finishing, and a check of each program against the
model. It is written for a 3-axis mill with an LNC controller.

It also includes a small connector so the toolpaths can be run from an
agent-first CAD tool such as STEVE (stevecad.studio), with a side panel and a
macOS menu-bar app. CAMBuddy is an independent project and is not affiliated
with STEVE.

**Nothing is sent to a machine.** Always check every program in a simulator and
dry-run it above the part before cutting.

- `engine/` – toolpath engine (`python -m engine.cli`)
- `verify/` – stock simulation used to check programs
- `connector/` – connector, panel and plain-words guide (`connector/README.md`)
- `menubar/` – macOS menu-bar app and launch agent

MIT License – see `LICENSE`.
