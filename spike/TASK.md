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

## Starting points (confirmed paths; read these, do not grep the whole app)
C=/Applications/VibeCAD.app/Contents/Resources/Mod/CAM
- Copy setup patterns from FreeCAD's own headless tests: $C/CAMTests/TestPathAdaptive.py, TestPathSteepShallow.py,
  TestPathToolController.py, TestPathStock.py, TestLinuxCNCPost.py (and TestFanucPost.py).
- Factories: Path.Main.Job.Create (Job.py:1341), Path.Main.Stock.CreateBox(job, extent, placement) (Stock.py:494)
  or CreateFromBase(job, neg, pos) (Stock.py:464), Path.Tool.Controller.Create (Controller.py:486),
  Path.Op.Adaptive.Create(name, obj, parentJob, toolController) (Adaptive.py:2056),
  Path.Op.SteepShallow.Create(name, obj, parentJob, toolController) (SteepShallow.py:492).
- Posting: Path/Post/Processor.py PostProcessorFactory (line 218).
- STEP import: Part.read(path) -> shape, then doc.addObject("Part::Feature").Shape = shape.
Workflow: write spike/run_cam.py FIRST (best guess), run it, fix errors from the traceback, rerun. Read a named
file only when an error points at it.
