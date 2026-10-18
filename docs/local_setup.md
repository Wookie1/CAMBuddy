# Local model setup (2026-10-18)

- Coding sessions (OpenCode, isolated: `XDG_CONFIG_HOME=<repo>/.oc-config`, project `opencode.json` only) use the
  **M5 Max at 192.168.0.14:8010** (oMLX, Qwen3.8-Flash-Next-oQ4e-mtp) for all coding until James says otherwise.
- The **M4 Max now runs MTPLX on 127.0.0.1:8005** (no API key), model id `mtplx-qwen36-27b-optimized-speed-v2`
  (James's "Qwen3.8-27B Optimized Speed V2"; ~48 tok/s on a 200-token reply). OpenCode provider `mtplx` in
  opencode.json; used as the second coder for rounds that run in their own worktree (e.g. connector-gates).
  The M5 Flash-Next stays the project default. The M4's old oMLX on :8010 is not used.
- Engine compute (OpenCAMLib, libarea, zmap) runs on the M4 regardless; it does not use a model server.
