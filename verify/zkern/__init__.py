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


class ZMoveParams(ctypes.Structure):
    """Task SP-K2B. Layout must match ZMoveParams in zcut.c."""
    _fields_ = [
        ("stock", _P),
        ("part", _P),
        ("xs", _P),
        ("ys", _P),
        ("wm", _P),
        ("nearm", _P),
        ("bstat", _P),
        ("nx", _I),
        ("ny", _I),
        ("x0", _D),
        ("y0", _D),
        ("cell", _D),
        ("R", _D),
        ("tool", _I),
        ("corner", _D),
        ("k", _I),
        ("eps", _D),
        ("fwd_bin", _D),
        ("shank_on", _I),
        ("Rs", _D),
        ("flute", _D),
        ("ks", _I),
        ("holder_on", _I),
        ("Rh", _D),
        ("stickout", _D),
        ("kH", _I),
        ("cutting", _I),
        ("engage_track", _I),
        ("zb_on", _I),
        ("dx_t", _D),
        ("dy_t", _D),
        ("pre", _P),
        ("pre_stride", _I),
        ("pre_ilo", _I),
        ("pre_jlo", _I),
        ("scr_v", _P),
        ("scr_m", _P),
    ]


class ZMoveOut(ctypes.Structure):
    """Layout must match ZMoveOut in zcut.c."""
    _fields_ = [
        ("move_area", ctypes.c_double),
        ("move_max_depth", ctypes.c_double),
        ("move_max_engage", ctypes.c_double),
        ("move_shank", ctypes.c_int64),
        ("move_holder", ctypes.c_int64),
        ("move_collided", ctypes.c_int64),
        ("hist_any", ctypes.c_int64),
    ]


class ZRunState(ctypes.Structure):
    """Layout must match ZRunState in zcut.c."""
    _fields_ = [
        ("shank_depth", ctypes.c_double),
        ("shank_worst_set", ctypes.c_int64),
        ("shank_worst_x", ctypes.c_double),
        ("shank_worst_y", ctypes.c_double),
        ("holder_intrusion", ctypes.c_double),
        ("holder_worst_set", ctypes.c_int64),
        ("holder_worst_x", ctypes.c_double),
        ("holder_worst_y", ctypes.c_double),
        ("air_length", ctypes.c_double),
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

_ARGTYPES_MOVE = [
    ctypes.POINTER(ZMoveParams),     # params struct
    _P, _I,                          # samples (n,3) flat, nsamp
    _D,                              # seg_len
    ctypes.POINTER(ZMoveOut),        # per-move outputs
    ctypes.POINTER(ZRunState),       # cross-move running state
    _P,                              # zb state (4 doubles)
    _P,                              # move hist out (100 u32)
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
        fn2 = lib.zcut_move          # task SP-K2B: per-move whole-loop kernel
        fn2.restype = None
        fn2.argtypes = _ARGTYPES_MOVE
    except Exception:
        return None
    return lib
