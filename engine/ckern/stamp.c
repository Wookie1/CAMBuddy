/* SP-K1: compiled kernel for load_limit._stamp_move (speed only).
 *
 * Reproduces the Python body bit for bit, same operations in the same
 * order: per-sample window, flat/bull disk stamp, removed-area/depth
 * measurement against the LIVE stock. Build with
 *   clang -O3 -ffp-contract=off -fno-fast-math -shared -o libstamp.dylib stamp.c
 * (no FMA contraction, no fast-math: IEEE-exact double ops, as numpy does).
 */
#include <math.h>
#include <stdlib.h>

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
    double dx = cur[0] - p[0], dy = cur[1] - p[1], dz = cur[2] - p[2];
    double length = sqrt((dx * dx + dy * dy) + dz * dz);
    long n = (length <= 0.0) ? 1 : (long)ceil(length / (fine / 4.0));
    double step, Rlim, cr2, area = 0.0, depth = 0.0;
    long s, i, j;
    double *gx, *gy;

    if (n < 2)
        n = 2;
    step = 1.0 / (double)n;
    Rlim = R + 1e-9;          /* the inside test's sum, computed once */
    cr2 = cr * cr;            /* same product numpy recomputes per cell */
    gx = (double *)malloc((size_t)(2 * kR + 1) * sizeof(double));
    gy = (double *)malloc((size_t)(2 * kR + 1) * sizeof(double));
    if (!gx || !gy) {
        free(gx); free(gy);
        return 1;
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
        for (i = i0; i < i1; ++i)
            gx[i - i0] = x0 + (((double)(i - pad2)) + 0.5) * fine - sx;
        for (j = j0; j < j1; ++j)
            gy[j - j0] = y0 + (((double)(j - pad2)) + 0.5) * fine - sy;
        for (j = j0; j < j1; ++j) {
            double *row = L + j * W;
            double gyy = gy[j - j0];
            for (i = i0; i < i1; ++i) {
                double dd = hypot(gx[i - i0], gyy);
                double newv;
                if (dd <= Rlim) {
                    double surf;
                    if (cr != 0.0) {
                        double o = fmax(dd - a0, 0.0);
                        surf = cr - sqrt(fmax(cr2 - o * o, 0.0));
                    } else {
                        surf = 0.0;
                    }
                    newv = sz + surf;
                } else {
                    newv = INFINITY;
                }
                double w = row[i];
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
    free(gx);
    free(gy);
    *area_out = area;
    *depth_out = depth;
    return 0;
}
