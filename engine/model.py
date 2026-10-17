"""Model handling: STEP -> cached STL (0.01 mm) via freecadcmd, ocl.STLSurf.

The STL and heightfield sidecars are cached in out/ so the next round's
finishing can reuse them without re-tessellating.
"""
import os
import subprocess
import sys

VIBE_BIN = "/Applications/VibeCAD.app/Contents/Resources/bin"
VIBE_LIB = os.path.join(VIBE_BIN, "..", "lib")

# make `import area` work under VibeCAD's plain python3.11
if VIBE_LIB not in sys.path and os.path.isdir(VIBE_LIB):
    sys.path.insert(0, VIBE_LIB)


def freecadcmd():
    return os.path.join(VIBE_BIN, "freecadcmd")


def python311():
    return os.path.join(VIBE_BIN, "python")


def step_to_stl(step, out_dir="out", tol=0.01):
    """Tessellate `step` to <out_dir>/<stem>.stl at deflection `tol` (cached)."""
    stem = os.path.splitext(os.path.basename(step))[0]
    stl = os.path.join(out_dir, stem + ".stl")
    if os.path.exists(stl) and os.path.getsize(stl) > 0:
        return stl
    os.makedirs(out_dir, exist_ok=True)
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "_tessellate.py")
    env = dict(os.environ, STEP_IN=step, STL_OUT=stl, TOL=str(tol))
    r = subprocess.run([freecadcmd(), script], env=env,
                      capture_output=True, text=True)
    if not (os.path.exists(stl) and os.path.getsize(stl) > 0):
        raise RuntimeError("tessellation failed: %s\n%s" % (r.stdout[-2000:],
                                                            r.stderr[-2000:]))
    return stl


def load_surf(stl):
    """Read an STL into an ocl.STLSurf."""
    from opencamlib import ocl
    surf = ocl.STLSurf()
    ocl.STLReader(stl, surf)
    if surf.size() == 0:
        raise RuntimeError("no triangles read from %s" % stl)
    return surf


def surf_bounds(surf):
    """(xmin, xmax, ymin, ymax, zmin, zmax) of the triangulated surface."""
    bb = surf.getBounds()
    return (bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax)
