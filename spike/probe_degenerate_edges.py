import Part, sys
s = Part.read("samples/core_front.step")
bad = []
for i, e in enumerate(s.Edges):
    try:
        c = e.Curve
        _ = c.__class__.__name__
    except Exception as exc:
        bad.append((i + 1, str(exc), e.BoundBox))
print("total edges:", len(s.Edges), "bad:", len(bad))
for b in bad[:10]:
    print(b)
# faces whose Curve access on any edge fails
badf = set()
for fi, f in enumerate(s.Faces):
    for e in f.Edges:
        try:
            _ = e.Curve
        except Exception:
            badf.add(fi + 1)
print("faces with bad edges:", sorted(badf)[:20], "of", len(s.Faces))

# try repairs
import Part as P
try:
    s2 = s.removeSplitter()
    n = 0
    for e in s2.Edges:
        try:
            _ = e.Curve
        except Exception:
            n += 1
    print("after removeSplitter bad:", n, "edges:", len(s2.Edges))
except Exception as exc:
    print("removeSplitter failed:", exc)

s3 = s.copy()
ok = s3.fix(1e-7, 1e-7, 1e-7)
n = 0
for e in s3.Edges:
    try:
        _ = e.Curve
    except Exception:
        n += 1
print("after fix():", ok, "bad:", n, "edges:", len(s3.Edges), "valid:", s3.isValid())

# reproduce the exact CAM-side failures (supervisor round 2 record):
import Path.Geom as PathGeom
for fi, f in enumerate(s.Faces):
    try:
        PathGeom.isVertical(f)
    except Exception as exc:
        print("face[%d] (%s) Path.Geom.isVertical -> %s: %s"
              % (fi, type(f.Surface).__name__, type(exc).__name__, exc))
import Path.Op.Adaptive as A
for z in (-11.62, -8.0, 10.16, 22.0):
    try:
        r = A._getSolidProjection(s, z)
        print("_getSolidProjection(z=%.2f) ok, faces=%d" % (z, len(r.Faces)))
    except Exception as exc:
        print("_getSolidProjection(z=%.2f) FAILED: %s: %s"
              % (z, type(exc).__name__, exc))

