# Task HC: a run can never use a stale heightfield or STL. Do not commit.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase; no bypass flags; never relax or delete tests.
Today engine/cli.py prepare (part_hf.npy) and connector/runner.py step 2 (part_hf01.npy) rebuild heightfields per run
in runs/<run_id>, then only check os.path.exists(out). If the run dir is reused (a redelivered run id) and the build
fails, the old file is accepted.
Fix: before each build, remove the output .npy and its .json sidecar; after it, require both to exist AND the sidecar
to carry "step_sha256" (add it in verify/heightfield.py's meta: sha256 of the STEP it rasterised), "tess_tol" and
"cell" equal to what was requested; else fail the run. Same for any STL the run uses (engine/model.step_to_stl is
already content-keyed - just assert it). Tests (connector/test_connector.py or engine/test_post.py, no FreeCAD needed
if you mock the spawn): a planted stale part_hf01.npy + sidecar with the wrong step_sha256 is rejected; a failing
build with a stale file present fails the run. Run /opt/homebrew/bin/python3 -m pytest verify connector
engine/test_post.py -q. Short outputs.
