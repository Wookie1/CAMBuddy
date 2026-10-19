# Local model setup (2026-10-18)

- Coding sessions (OpenCode, isolated: `XDG_CONFIG_HOME=<repo>/.oc-config`, project `opencode.json` only) use the
  **M5 Max at 192.168.0.14:8010** (oMLX, Qwen3.8-Flash-Next-oQ4e-mtp) for all coding until James says otherwise.
- **MTPLX on the M4 (127.0.0.1:8005, `mtplx-qwen36-27b-optimized-speed-v2`) was tried 2026-10-18 and set aside**:
  memory-management problems (James), no speedup at long context, and on real rounds it took shortcuts
  (a gate-bypass flag, relaxed tests) and once destroyed its own work with git stash/drop. Its provider was removed
  from opencode.json; the server was stopped 2026-10-19 (James's mtplx-lan-relay.py was left running).
- **The M4's oMLX (127.0.0.1:8010) serves again** (Qwen3.8-27B-oQ6e-mtp-mlx, Qwen3.8-Flash-Next-oQ4e-mtp). To use it for a
  small non-safety round, point a worktree's opencode.json `omlx` baseURL at http://127.0.0.1:8010/v1 (same key) - only
  when the engine pool is not competing for memory.
- Engine compute (OpenCAMLib, libarea, zmap) runs on the M4 regardless; it does not use a model server.
