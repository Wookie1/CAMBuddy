/* SP-K1: compiled kernel for load_limit._stamp_move (speed only).
 * SP-K1B: fast path (cell classification without hypot, per-row column
 * skip, per-cell cannot-cut skip) plus a batch entry point that stamps a
 * whole move list in one call.
 *
 * Reproduces the Python body bit for bit, same operations in the same
 * order: per-sample window, flat/bull disk stamp, removed-area/depth
 * measurement against the LIVE stock. Build with
 *   clang -O3 -ffp-contract=off -fno-fast-math -shared -o libstamp.dylib stamp.c
 * (no FMA contraction, no fast-math: IEEE-exact double ops, as numpy does).
 */
#include <math.h>
#include <stdlib.h>
#include <string.h>

/* The n+1 sample points of np.linspace(0.0, 1.0, n + 1) in numpy 1.26:
 * step = 1.0/n, t_i = (double)i*step + 0.0, last = 1.0 (verified equal in
 * test_sp_k1 (a)). n >= 1. out must hold n + 1 doubles. */
void sample_ts(long n, double *out)
{
    long i;
    double step;
    if (n <= 0) {
        out[0] = 0.0;
        return;
    }
    step = 1.0 / (double)n;
    for (i = 0; i <= n; ++i)
        out[i] = (double)i * step + 0.0;
    out[n] = 1.0;
}

/* One G1 move stamped into L, mirroring load_limit._stamp_move exactly.
 * gxbuf/gybuf are per-call scratch of length 2*kR+1 each (NULL -> malloc).
 * The hot loop keeps the old semantics bit for bit:
 *  - per cell s = gx*gx + gy*gy: s > T*T*(1+1e-9) is certainly outside
 *    (hypot(gx,gy) > R + 1e-9), so newv = +inf: no cut, no write; only a
 *    +inf or NaN stock cell there can matter (cut = NaN -> dmax = NaN, and
 *    fmin(NaN, +inf) = +inf), which the marker reproduces.
 *  - flat (cr == 0): s < T*T*(1-1e-9) is certainly inside, newv = sz + 0.0.
 *  - bull: s < a0*a0*(1-1e-9) gives o = fmax(dd - a0, 0) == 0 exactly, so
 *    surf == surf0 = cr - sqrt(fmax(cr*cr - 0.0*0.0, 0.0)) (computed once).
 *  - every other cell takes the exact old expressions with dd = hypot.
 *  - a cell with w <= sz (finite) cannot cut (newv >= sz everywhere) and
 *    fmin(w, newv) = w, so it needs no newv at all; NaN cells still run the
 *    full path so fmin/fmax semantics stay identical to the old loop.
 *  - per window row the columns certainly outside the circle (same margin)
 *    only take the +inf/NaN marker check.
 */
static int stamp_one(double *L, long H, long W,
                     double x0, double y0, double fine,
                     double R, double cr, double a0,
                     long kR, long pad2,
                     const double *p, const double *cur,
                     double remove_eps,
                     double *area_out, double *depth_out,
                     double *gxbuf, double *gybuf)
{
    double dx = cur[0] - p[0], dy = cur[1] - p[1], dz = cur[2] - p[2];
    double length = sqrt((dx * dx + dy * dy) + dz * dz);
    long n = (length <= 0.0) ? 1 : (long)ceil(length / (fine / 4.0));
    double step, Rlim, cr2, Tt, Tf, Tb, surf0, A, area = 0.0, depth = 0.0;
    long s, i, j;
    int flat, own = 0;

    if (n < 2)
        n = 2;
    step = 1.0 / (double)n;
    Rlim = R + 1e-9;                    /* the inside test's sum, once */
    cr2 = cr * cr;                      /* same product numpy recomputes */
    Tt = Rlim * Rlim * (1.0 + 1e-9);    /* s > Tt: certainly outside */
    flat = (cr == 0.0);
    Tf = Rlim * Rlim * (1.0 - 1e-9);    /* flat: s < Tf: certainly inside */
    Tb = a0 * a0 * (1.0 - 1e-9);        /* bull: s < Tb: o == 0 exactly */
    surf0 = cr - sqrt(fmax(cr2 - 0.0 * 0.0, 0.0));
    if (!gxbuf) {
        gxbuf = (double *)malloc((size_t)(2 * kR + 1) * sizeof(double));
        gybuf = (double *)malloc((size_t)(2 * kR + 1) * sizeof(double));
        if (!gxbuf || !gybuf) {
            free(gxbuf); free(gybuf);
            return 1;
        }
        own = 1;
    }
    for (s = 0; s <= n; ++s) {
        double t = (s == n) ? 1.0 : (double)s * step + 0.0;
        double sx = p[0] + dx * t, sy = p[1] + dy * t, sz = p[2] + dz * t;
        long ci = (long)floor((sx - x0) / fine) + pad2;
        long cj = (long)floor((sy - y0) / fine) + pad2;
        long i0 = ci - kR, i1 = ci + kR + 1;
        long j0 = cj - kR, j1 = cj + kR + 1;
        long ni, nj, count = 0;
        double dmax = 0.0;
        int have = 0;
        if (i0 < 0) i0 = 0;
        if (i1 > W) i1 = W;
        if (j0 < 0) j0 = 0;
        if (j1 > H) j1 = H;
        if (i0 >= i1 || j0 >= j1)
            continue;
        ni = i1 - i0;
        nj = j1 - j0;
        A = x0 - sx;                    /* gx(i) = A + ((i-pad2)+0.5)*fine */
        for (i = 0; i < ni; ++i)
            gxbuf[i] = x0 + (((double)(i0 + i - pad2)) + 0.5) * fine - sx;
        for (j = 0; j < nj; ++j)
            gybuf[j] = y0 + (((double)(j0 + j - pad2)) + 0.5) * fine - sy;
        for (j = 0; j < nj; ++j) {
            double *row = L + (j0 + j) * W;
            double gy = gybuf[j], gy2 = gy * gy;
            double rem = Tt - gy2;      /* columns need gx*gx <= rem */
            long clo = i0, chi = i0;    /* [clo,chi): possibly-inside cols */
            if (rem > 0.0) {
                double lim = sqrt(rem);
                long lo = (long)floor(((-lim - A) / fine - 0.5) + (double)pad2) - 1;
                long hi = (long)ceil(((lim - A) / fine - 0.5) + (double)pad2) + 2;
                if (lo < i0) lo = i0;
                if (hi > i1) hi = i1;
                if (lo < hi) {
                    clo = lo;
                    chi = hi;
                }
            }
            for (i = i0; i < clo; ++i) {        /* certainly outside */
                double w = row[i];
                if (w == INFINITY) { dmax = NAN; have = 1; }
                else if (w != w) { row[i] = INFINITY; dmax = NAN; have = 1; }
            }
            for (i = chi; i < i1; ++i) {        /* certainly outside */
                double w = row[i];
                if (w == INFINITY) { dmax = NAN; have = 1; }
                else if (w != w) { row[i] = INFINITY; dmax = NAN; have = 1; }
            }
            for (i = clo; i < chi; ++i) {
                double w = row[i];
                double newv;
                int outside = 0;
                if (w <= sz && w == w)
                    continue;           /* cannot cut, fmin(w, newv) == w */
                double gxv = gxbuf[i - i0];
                double s2 = gxv * gxv + gy2;
                if (s2 > Tt) {
                    outside = 1;
                } else if (flat ? (s2 < Tf) : (s2 < Tb)) {
                    newv = sz + (flat ? 0.0 : surf0);
                } else {
                    double dd = hypot(gxv, gy);
                    if (dd > Rlim) {
                        outside = 1;
                    } else if (cr != 0.0) {
                        double o = fmax(dd - a0, 0.0);
                        newv = sz + (cr - sqrt(fmax(cr2 - o * o, 0.0)));
                    } else {
                        newv = sz + 0.0;
                    }
                }
                if (outside) {
                    /* newv = +inf: finite w cannot cut and keeps w. */
                    if (w == INFINITY) { dmax = NAN; have = 1; }
                    else if (w != w) { row[i] = INFINITY; dmax = NAN; have = 1; }
                    continue;
                }
                double cut = w - newv;
                if (cut > remove_eps)
                    ++count;
                if (!have || cut > dmax || isnan(cut)) {
                    dmax = cut;
                    have = 1;
                }
                row[i] = fmin(w, newv);
            }
        }
        if (count > 0) {
            area += ((double)count * fine) * fine;
            if (isfinite(dmax) && dmax > depth)
                depth = dmax;
        }
    }
    if (own) {
        free(gxbuf);
        free(gybuf);
    }
    *area_out = area;
    *depth_out = depth;
    return 0;
}

/* One G1 move stamped into L (H rows x W cols, C-contiguous float64),
 * mirroring load_limit._stamp_move exactly; see its docstring. p/cur are
 * 3-element [x, y, z] arrays. Returns 0 on success. */
int stamp_move(double *L, long H, long W,
               double x0, double y0, double fine,
               double R, double cr, double a0,
               long kR, long pad2,
               const double *p, const double *cur,
               double remove_eps,
               double *area_out, double *depth_out)
{
    return stamp_one(L, H, W, x0, y0, fine, R, cr, a0, kR, pad2, p, cur,
                     remove_eps, area_out, depth_out, NULL, NULL);
}

/* SP-K1B: stamp a whole move list in one call, in program order. xyz holds
 * the 3*n current [x, y, z] positions (C-contiguous); flags[i] != 0 marks a
 * G1 move stamped from xyz[i-1] to xyz[i] (flags[0] must be 0). area_out
 * and depth_out (each n long) get the per-move (area, depth); unstamped
 * moves get 0.0, exactly as the per-move loop in limit_feeds leaves them.
 * Live-stock semantics: move i sees the stock after moves 0..i-1, identical
 * to the per-move calls. Scratch is allocated once per batch. 0 on success. */
int stamp_batch(double *L, long H, long W,
                double x0, double y0, double fine,
                double R, double cr, double a0,
                long kR, long pad2,
                long n, const double *xyz, const long *flags,
                double remove_eps,
                double *area_out, double *depth_out)
{
    double *gxbuf, *gybuf;
    long i;
    int rc = 0;

    if (n < 0)
        return 2;
    memset(area_out, 0, (size_t)n * sizeof(double));
    memset(depth_out, 0, (size_t)n * sizeof(double));
    if (n == 0)
        return 0;
    gxbuf = (double *)malloc((size_t)(2 * kR + 1) * sizeof(double));
    gybuf = (double *)malloc((size_t)(2 * kR + 1) * sizeof(double));
    if (!gxbuf || !gybuf) {
        free(gxbuf); free(gybuf);
        return 1;
    }
    for (i = 1; i < n; ++i) {
        if (!flags[i])
            continue;
        rc = stamp_one(L, H, W, x0, y0, fine, R, cr, a0, kR, pad2,
                       xyz + 3 * (i - 1), xyz + 3 * i, remove_eps,
                       area_out + i, depth_out + i, gxbuf, gybuf);
        if (rc)
            break;
    }
    free(gxbuf);
    free(gybuf);
    return rc;
}
