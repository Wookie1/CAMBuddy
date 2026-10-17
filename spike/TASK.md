# Spike task: headless FreeCAD CAM on a mold core

Write `spike/run_cam.py` and `spike/NOTES.md`. Work only inside this folder.

FreeCAD lives at /Applications/VibeCAD.app (FreeCAD 26.3.1 fork, Python 3.11).
- Headless binary: /Applications/VibeCAD.app/Contents/Resources/bin/freecadcmd
- CAM sources to read for real API/property names: /Applications/VibeCAD.app/Contents/Resources/Mod/CAM/
  (Path/Op/Adaptive.py has ModelAwareExperiment / FinishingProfile; Path/Op/SteepShallow.py; Path/Main/Job.py, Path/Main/Stock.py,
  Path/Tool/, Path/Post/). Grep these instead of guessing. Use GUI-free modules only (no FreeCADGui).
- OpenCAMLib imports as `opencamlib`, not `ocl`.

Run as:
  /Applications/VibeCAD.app/Contents/Resources/bin/freecadcmd spike/run_cam.py samples/core_front.step out/
If freecadcmd does not pass script args, read env vars STEP_IN and OUT_DIR instead (support both).

The script must:
1. Import samples/core_front.step (mold core ~253 x 140 mm, Z -11.92..34.93, features up). Create a CAM Job,
   box stock = part bounding box + 2 mm on X/Y each side and +1 mm on top.
2. Two tool controllers: 12.7 mm flat end mill (5000 rpm, 1500 mm/min) and 6 mm ball end mill (10000 rpm, 1200 mm/min).
3. Op A: Adaptive roughing of the whole part, 12.7 flat, model-aware/3D mode ON, stepdown 3 mm,
   0.3 mm stock to leave, optimal load ~15% of diameter.
4. Op B: SteepShallow finishing, 6 mm ball, default angle split (45 deg if required), 0.3 mm stepover/stepdown.
5. Recompute, then post both ops to out/core_front.ngc with the bundled linuxcnc post (generic post if that fails).
6. Print a JSON summary: per op name, number of path commands, min/max X/Y/Z of cutter moves, seconds to compute;
   post file path and size.
Time limit: if a run takes over 15 minutes, use coarser settings (e.g. bigger sample interval / stepover) rather than wait.

NOTES.md (<60 lines): API calls and property names that actually worked for Job, stock, tool controllers,
Adaptive (model-aware), SteepShallow and posting; anything that failed or looks experimental.

Acceptance (verify yourself by running the command before saying done):
- exits 0; both ops > 100 path commands; every cutter Z >= about -12 mm; every X/Y within stock (+ a few mm lead-in);
  out/core_front.ngc exists and is non-empty.
Iterate: run, read the error, fix, rerun, until acceptance passes. Then report the JSON summary.
