import re, math, sys, time, numpy as np
from opencamlib import ocl
src, step = sys.argv[1], float(sys.argv[2])
s = ocl.STLSurf(); ocl.STLReader("out/core_front_setup.stl", s)
P = {'X': None, 'Y': None, 'Z': None}; mode = '0'; prev = None; xs = []; ys = []; zs = []; ln = []
for n, l in enumerate(open(src), 1):
    if l.startswith('('): continue
    g = re.search(r'\bG0?([0-3])\b', l)
    if g: mode = g.group(1)
    for a in 'XYZ':
        v = re.search(a + r'(-?[\d.]+)', l)
        if v: P[a] = float(v.group(1))
    if None in P.values(): continue
    cur = (P['X'], P['Y'], P['Z'])
    if prev and mode in '123':
        m = max(1, int(math.hypot(cur[0]-prev[0], cur[1]-prev[1]) / step))
        t = np.arange(1, m + 1) / m
        xs.append(prev[0] + (cur[0]-prev[0])*t); ys.append(prev[1] + (cur[1]-prev[1])*t); zs.append(prev[2] + (cur[2]-prev[2])*t); ln.append(np.full(m, n))
    prev = cur
x = np.concatenate(xs); y = np.concatenate(ys); z = np.concatenate(zs); L = np.concatenate(ln)
print("points", len(x)); t0 = time.time()
cl = np.empty(len(x)); CH = 400000
for a in range(0, len(x), CH):
    bd = ocl.BatchDropCutter(); bd.setSTL(s); bd.setCutter(ocl.BallCutter(6.0, 60.0)); bd.setThreads(8)
    for i in range(a, min(len(x), a + CH)): bd.appendPoint(ocl.CLPoint(float(x[i]), float(y[i]), -100.0))
    bd.run(); cl[a:a + CH] = [p.z for p in bd.getCLPoints()]
d = cl - z; bad = d > 0.005
print("secs %.0f  points below CL by >0.005 mm: %d  max %.3f" % (time.time()-t0, int(bad.sum()), float(d.max())))
for k in np.argsort(-d)[:5]: print("  under %.3f at x=%.3f y=%.3f z=%.3f line %d" % (d[k], x[k], y[k], z[k], L[k]))
fl = np.abs(z - 24.765) < 1e-6
print("of which at Z 24.765:", int((bad & fl).sum()), " elsewhere:", int((bad & ~fl).sum()), " max elsewhere %.3f" % (float(d[~fl].max()) if (~fl).any() else 0))
ef = bad & ~fl
print("elsewhere worst:")
for k in np.argsort(-np.where(ef, d, -1))[:6]: print("  under %.3f at x=%.3f y=%.3f z=%.3f line %d" % (d[k], x[k], y[k], z[k], L[k]))
zz = np.round(z[ef], 2); u, c = np.unique(zz, return_counts=True); o = np.argsort(-c)[:8]
print("most common Z of elsewhere-bad points:", [(float(u[i]), int(c[i])) for i in o])
print("depth histogram elsewhere (mm):", np.histogram(d[ef], bins=[0.005, 0.02, 0.1, 0.5, 2, 20])[0].tolist())
