"""ctypes loader for the SP-K2 zcut C kernel (verify/zkern).

Independently written for SP-K2 (no relation to any other kernel loader).
Auto-builds zcut.c next to this file when the shared library is missing or
older than the source; returns None (caller falls back to pure Python) when
the env var ZMAP_NO_CKERN is set, no compiler is available, or the build or
load fails for any reason.

Build flags are exactly: -O3 -ffp-contract=off -fno-fast-math
(no fast math: the kernel must reproduce numpy's double results bit for bit
on every element-wise operation).
"""
import ctypes
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "zcut.c")
LIB = os.path.join(HERE, "libzcut.dylib" if os.uname().sysname == "Darwin"
                   else "libzcut.so")

FWD_NBINS = 100  # must match FWD_NBINS in zcut.c and zmap.py


class ZOut(ctypes.Structure):
    """Layout must match ZOut in zcut.c."""
    _fields_ = [
        ("removed", ctypes.c_double),
        ("dmax", ctypes.c_double),
        ("ew", ctypes.c_double),
        ("status", ctypes.c_int64),
        ("air", ctypes.c_int64),
        ("collided", ctypes.c_int64),
        ("nrem", ctypes.c_int64),
        ("hist_any", ctypes.c_int64),
        ("dmax_valid", ctypes.c_int64),
        ("engaged", ctypes.c_int64),
        ("ew_valid", ctypes.c_int64),
        ("updated", ctypes.c_int64),
    ]


_D = ctypes.c_double
_I = ctypes.c_int64
_P = ctypes.c_void_p

_ARGTYPES = [
    _P, _I, _I, _I, _I, _I,          # stock, nx, ny, i0, j0, k
    _P, _P,                          # xs, ys
    _D, _D, _D,                      # sx, sy, sz
    _D, _I, _D,                      # R, tool, corner
    _P,                              # window mask (uint8 grid) or None
    _I, _I, _I,                      # cutting, engage_track, zb_on
    _D, _D, _D,                      # cell, eps, fwd_bin
    _D, _D,                          # dx_t, dy_t
    _P, _I, _I, _I,                  # zb pre snapshot, stride, its ilo/jlo
    _P, _P,                          # zb state (4 doubles), hist out (100 u32)
    _P, _P,                          # scratch: surface doubles, mask bytes
    ctypes.POINTER(ZOut),
]


def _build():
    cc = os.environ.get("CC", "cc")
    shared = "-dynamiclib" if os.uname().sysname == "Darwin" else "-shared"
    tmp = "%s.tmp%d" % (LIB, os.getpid())
    cmd = [cc, "-O3", "-ffp-contract=off", "-fno-fast-math", shared,
           "-o", tmp, SRC]
    subprocess.run(cmd, check=True, capture_output=True)
    os.replace(tmp, LIB)  # atomic: concurrent workers each build, then win


def load():
    """Return the loaded zcut lib (with argtypes set) or None."""
    if "ZMAP_NO_CKERN" in os.environ:
        return None
    try:
        if (not os.path.exists(LIB)
                or os.path.getmtime(LIB) < os.path.getmtime(SRC)):
            _build()
        lib = ctypes.CDLL(LIB)
        fn = lib.zcut_sample
        fn.restype = None
        fn.argtypes = _ARGTYPES
    except Exception:
        return None
    return lib
