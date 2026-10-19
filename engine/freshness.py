"""Freshness guards (task HC): a reused run dir never accepts stale output.

Every heightfield build must remove_stale() its .npy + .json sidecar before
the build and require_fresh() both afterwards: the sidecar must carry
step_sha256 (the STEP that was rasterised) and cell/tess_tol equal to what
was requested. STLs are content-keyed by engine.model.step_to_stl; for a
direct _tessellate.py build the run removes the stale file first and then
asserts a fresh non-empty file exists. Failures raise OSError, which fails
the run (connector catches OSError; the CLI exits non-zero).
"""
import hashlib
import json
import os


def sha256_file(path):
    """sha256 hex digest of a file's contents."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def remove_stale(out):
    """Remove a build output and its .json sidecar before rebuilding."""
    for p in (out, os.path.splitext(out)[0] + ".json"):
        try:
            os.remove(p)
        except FileNotFoundError:
            pass


def require_fresh(out, step_sha256=None, cell=None, tess_tol=None):
    """Fail unless `out` and its sidecar exist and the sidecar matches.

    The sidecar must carry step_sha256 equal to `step_sha256` (when given)
    and cell / tess_tol equal to the requested values (when given).
    Returns the parsed sidecar meta; raises OSError otherwise.
    """
    if not os.path.exists(out):
        raise OSError("build produced no %s (stale file removed)" % out)
    sidecar = os.path.splitext(out)[0] + ".json"
    if not os.path.exists(sidecar):
        raise OSError("build produced no sidecar %s for %s" % (sidecar, out))
    with open(sidecar) as fh:
        meta = json.load(fh)
    if step_sha256 is not None and meta.get("step_sha256") != step_sha256:
        raise OSError(
            "stale %s: sidecar step_sha256 %r does not match the STEP this "
            "run rasterised (%r)" % (out, meta.get("step_sha256"),
                                      step_sha256))
    if cell is not None:
        got = meta.get("cell")
        if got is None or float(got) != float(cell):
            raise OSError("stale %s: sidecar cell %r != requested %r"
                          % (out, got, cell))
    if tess_tol is not None:
        got = meta.get("tess_tol")
        if got is None or float(got) != float(tess_tol):
            raise OSError("stale %s: sidecar tess_tol %r != requested %r"
                          % (out, got, tess_tol))
    return meta


def require_stl(out):
    """Assert a freshly built STL exists and is non-empty (the stale file
    was removed before the build, so existence means this build wrote it)."""
    if not (os.path.exists(out) and os.path.getsize(out) > 0):
        raise OSError("build produced no non-empty STL %s" % out)
