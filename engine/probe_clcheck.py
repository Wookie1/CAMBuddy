"""Probe CL check: verify that posted finish CL points are not below the
part surface by more than 0.005 mm.

Old CLI (backward compatible):  probe_clcheck.py <ngc> <step_mm>
  Uses 6 mm ball cutter, repo STL (out/model.stl), text output on stdout.

New CLI:  probe_clcheck.py <ngc> <stl> <tool_diameter>
  Outputs JSON on stdout, text diagnostics on stderr.
"""
import json, math, os, re, sys, time
import numpy as np
from opencamlib import ocl

# ---------------------------------------------------------------------------
# Argument parsing: detect old vs new CLI
# ---------------------------------------------------------------------------
if len(sys.argv) == 3:
    # Old CLI: probe_clcheck.py <ngc> <step_mm>
    gcode_path = sys.argv[1]
    step = float(sys.argv[2])
    # never a name-keyed cache: tessellate samples/core_front_setup.step fresh (content-keyed cache)
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from engine import model as _model
    stl_path = _model.step_to_stl(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                               "samples", "core_front_setup.step"))
    tool_dia = 6.0
    old_cli = True
elif len(sys.argv) == 4:
    # New CLI: probe_clcheck.py <ngc> <stl> <tool_diameter>
    gcode_path = sys.argv[1]
    stl_path = sys.argv[2]
    tool_dia = float(sys.argv[3])
    step = 0.5
    old_cli = False
else:
    print("Usage: probe_clcheck.py <ngc> <step_mm>          (old, 6mm ball)")
    print("       probe_clcheck.py <ngc> <stl> <tool_dia>   (new)",
          file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Load STL
# ---------------------------------------------------------------------------
s = ocl.STLSurf()
ocl.STLReader(stl_path, s)

# ---------------------------------------------------------------------------
# Parse G-code into CL points
# ---------------------------------------------------------------------------
P = {'X': None, 'Y': None, 'Z': None}
mode = '0'
prev = None
xs, ys, zs, ln = [], [], [], []
for n, line in enumerate(open(gcode_path), 1):
    if line.startswith('('):
        continue
    g = re.search(r'\bG0?([0-3])\b', line)
    if g:
        mode = g.group(1)
    for a in 'XYZ':
        v = re.search(a + r'(-?[\d.]+)', line)
        if v:
            P[a] = float(v.group(1))
    if None in P.values():
        continue
    cur = (P['X'], P['Y'], P['Z'])
    if prev and mode in '123':
        dist = math.hypot(cur[0] - prev[0], cur[1] - prev[1])
        m = max(1, int(dist / step))
        t = np.arange(1, m + 1) / m
        xs.append(prev[0] + (cur[0] - prev[0]) * t)
        ys.append(prev[1] + (cur[1] - prev[1]) * t)
        zs.append(prev[2] + (cur[2] - prev[2]) * t)
        ln.append(np.full(m, n))
    prev = cur

if not xs:
    if old_cli:
        print("points 0")
        print("secs 0  points below CL by >0.005 mm: 0  max 0.000")
    else:
        print(json.dumps({"below_cl": 0, "points": 0, "max_depth_mm": 0.0}))
    sys.exit(0)

x = np.concatenate(xs)
y = np.concatenate(ys)
z = np.concatenate(zs)
L = np.concatenate(ln)

print("points", len(x))
t0 = time.time()

# ---------------------------------------------------------------------------
# Batch drop cutter: compute CL Z for each point
# ---------------------------------------------------------------------------
cl = np.empty(len(x))
CH = 400000
for a in range(0, len(x), CH):
    bd = ocl.BatchDropCutter()
    bd.setSTL(s)
    bd.setCutter(ocl.BallCutter(tool_dia, tool_dia * 10.0))
    bd.setThreads(8)
    for i in range(a, min(len(x), a + CH)):
        bd.appendPoint(ocl.CLPoint(float(x[i]), float(y[i]), -100.0))
    bd.run()
    cl[a:a + CH] = [p.z for p in bd.getCLPoints()]

# Depth = CL_z - programmed_z; positive = below part surface
d = cl - z
bad = d > 0.005
max_depth = float(d.max()) if len(d) > 0 else 0.0
elapsed = time.time() - t0

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
if old_cli:
    # Old text output on stdout (what supervisor scripts expect)
    print("secs %.0f  points below CL by >0.005 mm: %d  max %.3f"
          % (elapsed, int(bad.sum()), max_depth))
    for k in np.argsort(-d)[:5]:
        print("  under %.3f at x=%.3f y=%.3f z=%.3f line %d"
              % (d[k], x[k], y[k], z[k], L[k]))
else:
    # New: text diagnostics on stderr, JSON on stdout
    print("secs %.0f  points below CL by >0.005 mm: %d  max %.3f"
          % (elapsed, int(bad.sum()), max_depth), file=sys.stderr)
    print(json.dumps({
        "below_cl": int(bad.sum()),
        "points": len(x),
        "max_depth_mm": max_depth,
    }))