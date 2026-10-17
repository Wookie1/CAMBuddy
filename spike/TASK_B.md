# Task B: fix the spike and judge it with verify/zmap.py

Edit spike/run_cam.py (and spike/NOTES.md). Same run command as before. Read only the named FreeCAD files
when an error or a property name points at them: C=/Applications/VibeCAD.app/Contents/Resources/Mod/CAM,
$C/Path/Op/SteepShallow.py, $C/Path/Op/Adaptive.py, $C/CAMTests/TestPathSteepShallow.py.

1. SteepShallow stops at Z 19.86 but the part has floors at Z 10.16 and -11.92. Set StartDepth/FinalDepth
   explicitly (clear expressions first, like Adaptive), then find its angle-threshold and boundary/coverage
   properties (grep `addProperty` in SteepShallow.py) and get it finishing down to those floors.
2. REMOVE the runtime monkeypatch of FreeCAD internals. Heal the shape before creating the Job instead:
   shape.fix(tol, tol, tol), shape.removeSplitter(), or Part.Shape rebuilt via ShapeFix. If model-aware
   Adaptive still fails, print the exact error text and the property/face involved and say so in NOTES.md —
   never swallow it. An op that returns an empty path must make the script exit non-zero.
3. Find the Z / floor stock-to-leave property on Adaptive so roughing stops ~0.3 mm above floors
   (it currently reaches -11.84 over a -11.92 floor).
4. Also post each op to its own file (out/core_front_rough.ngc, out/core_front_finish.ngc) besides the
   combined out/core_front.ngc, so zmap can simulate one tool per file.
5. Save the Job as out/core_front_job.FCStd (doc.saveAs).

Judge with zmap (heightfield already at out/core_front_hf.npy; regenerate with verify/heightfield.py if needed):
- Roughing alone: flat 12.7 on out/core_front_rough.ngc, stock box from the JSON summary.
- Roughing then finishing: zmap must support continuing from a saved stock state — add `--stock-in X.npy`
  and `--stock-out Y.npy` to zmap.py (with a test) and chain rough -> finish (ball 6).
Targets: 0 gouges, 0 rapid collisions; leftover after roughing ~0.3 mm on reachable areas (more in
corners); after finishing small except where a 6 mm ball cannot reach. If zmap takes > 10 min on the full
program, profile and vectorize it rather than coarsening the check.
Write both zmap JSONs to out/zmap_rough.json and out/zmap_finish.json and print them. Commit nothing; I do that.
