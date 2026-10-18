# Task Z1: zmap accuracy at vertical walls (verify/ only; numpy only, never import ocl or engine code)
Rules: no MCP, no questions, do not commit, probes in verify/probe_*.py. Run tests with
/opt/homebrew/bin/python3 -m pytest verify -q.
Finding (supervisor): zmap already samples the part at cell centres (barycentric) and the tool envelope at exact
distances, but verify/heightfield.py tessellated at 0.05 mm while the engine/OCL mesh is 0.01 mm, so walls differed by
the chord error; with TESS_TOL=0.01 the full finishing judgement went from 1,266 wall-edge gouge cells to 0.
1. verify/heightfield.py: make the default tessellation 0.01 mm (keep TESS_TOL env to override); record "tess_tol"
   in the .json sidecar; zmap.py prints a warning if the sidecar's tess_tol is missing or > 0.02.
2. Tests in verify/test_zmap.py on a synthetic vertical wall (analytic heightfield, 0.1 mm cells):
   a. ball path exactly r from the wall face (tip at floor) -> 0 gouges;
   b. same path moved 0.05 mm into the wall -> flagged (count > 0, depth > 0);
   c. cells away from the wall behave as before (an existing flat test still passes unchanged).
3. Keep all existing tests passing. Print the pytest summary.
