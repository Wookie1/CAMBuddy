"""SP-K1: ctypes loader for the compiled load_limit._stamp_move kernel.
SP-K1B: auto-builds libstamp.dylib when it is missing or older than
stamp.c (clang via xcrun or PATH, same flags as build.sh; the build lands
in a temp file in engine/ckern/ and is renamed atomically; on any failure
the Python fallback stays in use), and exposes the batch entry point.

get_lib() returns the loaded CDLL, or None when the kernel could not be
built or loaded. Callers must also honour STEVECAM_NO_CKERN (load_limit
does)."""
import ctypes
import os
import shutil
import subprocess
import sys
import tempfile

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(_HERE, "stamp.c")
_DYLIB = os.path.join(_HERE, "libstamp.dylib")
# the exact flags of engine/ckern/build.sh (IEEE-exact double ops)
_FLAGS = ["-O3", "-ffp-contract=off", "-fno-fast-math", "-shared"]


def _clang():
    """clang via PATH (the same shim build.sh runs, which resolves the SDK
    itself), else via xcrun; None if neither works. Returns an argv prefix."""
    cc = shutil.which("clang")
    if cc is not None:
        return [cc]
    try:
        r = subprocess.run(["xcrun", "--find", "clang"],
                           capture_output=True, text=True, timeout=60)
        if r.returncode == 0 and r.stdout.strip():
            return ["xcrun", "clang"]     # xcrun supplies the SDK env
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def _needs_build():
    if not os.path.exists(_SRC):
        return False
    if not os.path.exists(_DYLIB):
        return True
    try:
        return os.path.getmtime(_DYLIB) < os.path.getmtime(_SRC)
    except OSError:
        return False


def ensure_built():
    """Compile libstamp.dylib when stale/missing: temp file in engine/ckern/
    + atomic os.replace. Never raises - any failure just leaves the library
    unbuilt (callers fall back to Python)."""
    if not _needs_build():
        return
    cc = _clang()
    if cc is None:
        return
    fd, tmp = tempfile.mkstemp(prefix=".libstamp.", suffix=".tmp", dir=_HERE)
    os.close(fd)
    try:
        r = subprocess.run(cc + _FLAGS + ["-o", tmp, _SRC],
                           capture_output=True, text=True, timeout=300)
        if r.returncode == 0:
            os.replace(tmp, _DYLIB)          # atomic rename into place
        else:
            sys.stderr.write("ckern: build failed: %s\n" % r.stderr[-300:])
    except (OSError, subprocess.SubprocessError) as exc:
        sys.stderr.write("ckern: build failed: %s\n" % exc)
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


ensure_built()

_LIB = None
if os.path.exists(_DYLIB):
    try:
        _LIB = ctypes.CDLL(_DYLIB)
    except OSError:
        _LIB = None
if _LIB is not None:
    _d = ctypes.c_double
    _l = ctypes.c_long
    _dp = ctypes.POINTER(_d)
    _LIB.sample_ts.argtypes = [_l, _dp]
    _LIB.sample_ts.restype = None
    _LIB.stamp_move.argtypes = [_dp, _l, _l, _d, _d, _d, _d,
                                _d, _d, _l, _l, _dp, _dp, _d, _dp, _dp]
    _LIB.stamp_move.restype = ctypes.c_int
    _LIB.stamp_batch.argtypes = [_dp, _l, _l, _d, _d, _d, _d,
                                 _d, _d, _l, _l, _l, _dp, ctypes.POINTER(_l),
                                 _d, _dp, _dp]
    _LIB.stamp_batch.restype = ctypes.c_int


def get_lib():
    """The loaded kernel library, or None if it is not built."""
    return _LIB


def sample_ts(n):
    """The n+1 linspace samples the C kernel uses (test (a) partner)."""
    out = np.empty(n + 1, dtype=np.float64)
    _LIB.sample_ts(n, out.ctypes.data_as(ctypes.POINTER(ctypes.c_double)))
    return out


def stamp_move(L, x0, y0, fine, R, cr, a0, kR, pad2, p, cur, remove_eps):
    """C twin of load_limit._stamp_move; returns (area, depth)."""
    assert L.dtype == np.float64, "ckern: L must be float64"
    assert L.flags["C_CONTIGUOUS"], "ckern: L must be C-contiguous"
    H, W = L.shape
    pp = (ctypes.c_double * 3)(p[0], p[1], p[2])
    cc = (ctypes.c_double * 3)(cur[0], cur[1], cur[2])
    area = ctypes.c_double(0.0)
    depth = ctypes.c_double(0.0)
    rc = _LIB.stamp_move(
        L.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        H, W, x0, y0, fine, R, cr, a0, kR, pad2, pp, cc, remove_eps,
        ctypes.byref(area), ctypes.byref(depth))
    if rc != 0:
        raise RuntimeError("ckern stamp_move failed (%d)" % rc)
    return area.value, depth.value


def stamp_batch(L, x0, y0, fine, R, cr, a0, kR, pad2, xyz, flags,
                remove_eps):
    """Stamp a whole move list in one C call (program order, live stock).

    xyz: (n, 3) float64 array, the current position of every move;
    flags: (n,) int64, 1 on the G1 moves stamped from xyz[i-1] to xyz[i]
    (flags[0] must be 0). Returns (area, depth) float64 arrays of length n,
    0.0 on unstamped moves."""
    assert L.dtype == np.float64, "ckern: L must be float64"
    assert L.flags["C_CONTIGUOUS"], "ckern: L must be C-contiguous"
    H, W = L.shape
    n = int(flags.shape[0])
    xyz = np.ascontiguousarray(xyz, dtype=np.float64).reshape(n, 3)
    flags = np.ascontiguousarray(flags, dtype=np.int64)
    area = np.empty(n, dtype=np.float64)
    depth = np.empty(n, dtype=np.float64)
    rc = _LIB.stamp_batch(
        L.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        H, W, x0, y0, fine, R, cr, a0, kR, pad2, n,
        xyz.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        flags.ctypes.data_as(ctypes.POINTER(ctypes.c_long)),
        remove_eps,
        area.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        depth.ctypes.data_as(ctypes.POINTER(ctypes.c_double)))
    if rc != 0:
        raise RuntimeError("ckern stamp_batch failed (%d)" % rc)
    return area, depth
