"""SP-K1: ctypes loader for the compiled load_limit._stamp_move kernel.

get_lib() returns the loaded CDLL, or None when engine/ckern/libstamp.dylib
is missing (build it with engine/ckern/build.sh). Callers must also honour
STEVECAM_NO_CKERN (load_limit does)."""
import ctypes
import os

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_DYLIB = os.path.join(_HERE, "libstamp.dylib")

_LIB = None
if os.path.exists(_DYLIB):
    try:
        _LIB = ctypes.CDLL(_DYLIB)
    except OSError:
        _LIB = None
if _LIB is not None:
    _d = ctypes.c_double
    _l = ctypes.c_long
    _LIB.sample_ts.argtypes = [_l, ctypes.POINTER(_d)]
    _LIB.sample_ts.restype = None
    _LIB.stamp_move.argtypes = [ctypes.POINTER(_d), _l, _l, _d, _d, _d, _d,
                                _d, _d, _l, _l, ctypes.POINTER(_d),
                                ctypes.POINTER(_d), _d, ctypes.POINTER(_d),
                                ctypes.POINTER(_d)]
    _LIB.stamp_move.restype = ctypes.c_int


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
