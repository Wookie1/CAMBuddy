# Local model setup (2026-10-18)

- Coding sessions (OpenCode, isolated: `XDG_CONFIG_HOME=<repo>/.oc-config`, project `opencode.json` only) use the
  **M5 Max at 192.168.0.14:8010** (oMLX, Qwen3.8-Flash-Next-oQ4e-mtp) for all coding until James says otherwise.
- The **M4 Max's local oMLX (127.0.0.1:8010) is being replaced by MTPLX** running "Qwen3.8-27B Optimized Speed V2"
  (James installing, 2026-10-18). Do not point any opencode.json at 127.0.0.1:8010 until James confirms MTPLX is
  ready; then add it as a separate provider entry.
- Engine compute (OpenCAMLib, libarea, zmap) runs on the M4 regardless; it does not use a model server.
