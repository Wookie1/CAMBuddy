/* zcut.c -- per-sample stock-cut kernel for verify/zmap.py (task SP-K2).
 *
 * Independently written for SP-K2. One call does, for ONE sample, exactly
 * what the Python block in simulate() does from
 *     ilo, ihi = max(0, i0 - k)...
 * through the in-place stock update:
 *   - window clip (empty window -> status 0, like Python's `continue`)
 *   - early-out: no cell above sz + 1e-6 -> air (status 1)
 *   - d = hypot(gx, gy), mask d <= R + 1e-9, optional window mask AND;
 *     empty mask -> status 3, like Python's `continue` (no air)
 *   - tool surface: flat (sz + 0.0), bull dz(d), ball sz + R - sqrt(...)
 *     replaying the exact numpy op chain (mul, sub, max 0, sqrt, sub, add)
 *   - cut = win - newv (newv = +inf outside the mask)
 *   - removed = sum of clip(cut, 0, None) over the whole window
 *   - nrem = count of cut > eps; FWD histogram when engage_track
 *   - dmax = max of cut (NaN-poisoned like np.max), validity = isfinite
 *   - ZE2B (zb_on): vol from the finite cut>eps sum; a/ext/dext from the
 *     pre-move snapshot where msk & isfinite(sub) & sub - newv > 0.01
 *   - engagement (cutting): msk_e = d <= R + 0.75*cell (& window mask),
 *     engaged = max(win over msk_e) > sz + 1e-6, chord ew over
 *     msk_e & (win > sz + 1e-6), clamped to [0, 2R]
 *   - air flag: early-out (cutting) or cutting & !engaged
 *   - rapid: collided = any(cut > eps)
 *   - stock update (cutting, removed > eps): win = np.minimum(win, newv)
 *     on the masked cells (outside the mask np.minimum(win, +inf) == win,
 *     bit-for-bit, so those cells are left untouched).
 *
 * Element-wise ops use the same order as the numpy block so the stock grid
 * stays BIT-identical. Sums (removed, zb vol) are sequential here and
 * pairwise in numpy, so they may differ in the last bits (allowed).
 *
 * NaN rules mirrored from numpy:
 *   np.max propagates NaN; np.minimum/np.maximum propagate NaN; on equal
 *   zeros np.minimum returns -0 and np.maximum returns +0; np.clip(a,0,None)
 *   maps -0 and negatives to +0 and keeps NaN.
 */
#include <math.h>
#include <stdint.h>
#include <string.h>

#define FWD_NBINS 100

/* output scalars; layout must match zkern.ZOut in __init__.py */
typedef struct {
    double removed;     /* sum of clip(cut, 0, None) over the window */
    double dmax;        /* max of cut over the window (NaN-poisoned) */
    double ew;          /* engagement chord, clamped (valid iff ew_valid) */
    int64_t status;     /* 0 empty window, 1 early air, 3 empty mask, 2 done */
    int64_t air;        /* add one segment length to the air length */
    int64_t collided;   /* rapid sample cut into material */
    int64_t nrem;       /* cells with cut > eps */
    int64_t hist_any;   /* FWD histogram was filled (nrem > 0) */
    int64_t dmax_valid; /* dmax is finite */
    int64_t engaged;    /* cutting, processed: stock at/over footprint edge */
    int64_t ew_valid;   /* ew is meaningful (cutting & engage_track & engaged) */
    int64_t updated;    /* stock window was written */
} ZOut;

/* np.maximum: NaN-propagating max, +0 wins over -0 */
static double nm(double a, double b)
{
    if (isnan(a) || isnan(b)) return NAN;
    if (a > b) return a;
    if (b > a) return b;
    return signbit(a) ? b : a;
}

/* np.minimum: NaN-propagating min, -0 wins over +0 */
static double nn(double a, double b)
{
    if (isnan(a) || isnan(b)) return NAN;
    if (a < b) return a;
    if (b < a) return b;
    return signbit(a) ? a : b;
}

/* np.clip(a, 0.0, None): NaN stays, everything <= 0 (incl. -0) becomes +0 */
static double clip0(double a)
{
    if (isnan(a)) return a;
    return a <= 0.0 ? 0.0 : a;
}

/*
 * tool: 0 = flat, 1 = bull (corner given), 2 = ball.
 * a = R - corner, cc = corner * corner, RR = R * R (precomputed by caller).
 * Mirrors the exact numpy expression chain of tool_dz()/the ball_surf block.
 */
static double surface(double d, int tool, double R, double a, double cc,
                      double corner, double sz, double RR)
{
    if (tool == 0)
        return sz + 0.0;                    /* np.where(msk, sz + dz(d), inf) */
    if (tool == 2) {                        /* ball_surf chain, same order */
        double u = RR - d * d;              /* np.subtract(R*R, d*d) */
        u = nm(u, 0.0);                     /* np.maximum(t, 0.0) */
        u = sqrt(u);                        /* np.sqrt(t) */
        return sz + (R - u);                /* np.subtract(R,t); np.add(sz,t) */
    }
    /* bull: np.where(d <= a, 0.0, corner - sqrt(max(cc - t*t, 0.0))) */
    double v;
    if (d <= a) {
        v = 0.0;
    } else {
        double t = nm(d - a, 0.0);
        double u = nm(cc - t * t, 0.0);
        v = corner - sqrt(u);
    }
    return sz + v;
}

void zcut_sample(double *stock, int64_t nx, int64_t ny,
                 int64_t i0, int64_t j0, int64_t k,
                 const double *xs, const double *ys,
                 double sx, double sy, double sz,
                 double R, int64_t tool, double corner,
                 const unsigned char *wm,
                 int64_t cutting, int64_t engage_track, int64_t zb_on,
                 double cell, double eps, double fwd_bin,
                 double dx_t, double dy_t,
                 const double *pre, int64_t pre_stride,
                 int64_t pre_ilo, int64_t pre_jlo,
                 double *zb, unsigned int *hist,
                 double *scr_v, unsigned char *scr_m,
                 ZOut *out)
{
    const double INF = INFINITY;
    memset(out, 0, sizeof(*out));
    memset(hist, 0, FWD_NBINS * sizeof(unsigned int));
    out->status = 0;

    int64_t ilo = i0 - k; if (ilo < 0) ilo = 0;
    int64_t ihi = i0 + k + 1; if (ihi > nx) ihi = nx;
    int64_t jlo = j0 - k; if (jlo < 0) jlo = 0;
    int64_t jhi = j0 + k + 1; if (jhi > ny) jhi = ny;
    if (ilo >= ihi || jlo >= jhi)
        return;                              /* Python: continue (no air) */

    int64_t nw = ihi - ilo, nh = jhi - jlo;
    double *sw = stock + jlo * nx + ilo;     /* window view, row stride nx */
    double tip = sz + 1e-6;

    /* early-out: float(win.max()) <= sz + 1e-6 -> air (NaN poisons like
     * np.max, so a NaN cell forces the block to run) */
    {
        int wnan = 0;
        double wmax = -INF;
        for (int64_t j = 0; j < nh; j++) {
            const double *row = sw + j * nx;
            for (int64_t i = 0; i < nw; i++) {
                double v = row[i];
                if (isnan(v)) wnan = 1;
                else if (v > wmax) wmax = v;
            }
        }
        if (!wnan && wmax <= tip) {
            out->status = 1;
            out->air = cutting;
            return;
        }
    }

    const double Rm = R + 1e-9;
    const double Re = R + 0.75 * cell;
    const double a = R - corner;
    const double cc = corner * corner;
    const double RR = R * R;
    const double perp_x = -dy_t, perp_y = dx_t;

    int msk_any = 0;
    double removed = 0.0;
    int64_t nrem = 0;
    int dmax_nan = 0;
    double dmax = -INF;
    int any_cut = 0;
    /* engagement over the padded footprint msk_e */
    int emax_nan = 0, eseen = 0;
    double emax = -INF;
    int pseen = 0;
    double pmin = 0.0, pmax = 0.0;
    /* ZE2B */
    double vol_sum = 0.0;
    int zseen = 0;
    double amax = 0.0, pumin = 0.0, pumax = 0.0, pvmin = 0.0, pvmax = 0.0;

    for (int64_t j = 0; j < nh; j++) {
        double gy = ys[jlo + j] - sy;
        const double *wrow = sw + j * nx;
        const double *prow = pre ? pre + (jlo + j - pre_jlo) * pre_stride
                                 : NULL;
        const unsigned char *wrowm = wm ? wm + (jlo + j) * nx : NULL;
        for (int64_t i = 0; i < nw; i++) {
            double gx = xs[ilo + i] - sx;
            double d = hypot(gx, gy);
            int mk = d <= Rm && (!wm || wrowm[ilo + i]);
            scr_m[j * nw + i] = (unsigned char)mk;
            if (mk) msk_any = 1;
            double win = wrow[i];

            if (cutting && d <= Re && (!wm || wrowm[ilo + i])) {
                if (isnan(win)) emax_nan = 1;
                else if (!eseen || win > emax) { emax = win; eseen = 1; }
                if (win > tip) {
                    double pr = gx * perp_x + gy * perp_y;
                    if (!pseen || pr < pmin) pmin = pr;
                    if (!pseen || pr > pmax) pmax = pr;
                    pseen = 1;
                }
            }

            double v = INF;
            if (mk) {
                v = surface(d, (int)tool, R, a, cc, corner, sz, RR);
                scr_v[j * nw + i] = v;
            }
            double cut = win - v;            /* -inf/NaN outside the mask */
            removed += clip0(cut);
            if (cut > eps) {
                any_cut = 1;
                nrem++;
                if (cutting && engage_track) {
                    /* numpy astype(int64) saturates: +inf -> INT64_MAX -> 99 */
                    double q = cut / fwd_bin;
                    int64_t b = q >= 9223372036854775807.0
                                ? INT64_MAX : (int64_t)q;
                    if (b > FWD_NBINS - 1) b = FWD_NBINS - 1;
                    hist[b]++;
                }
            }
            if (isnan(cut)) dmax_nan = 1;
            else if (cut > dmax) dmax = cut;

            if (cutting && zb_on && mk) {
                if (isfinite(cut) && cut > eps) vol_sum += cut;
                if (pre) {
                    double sub = prow[ilo + i - pre_ilo];
                    if (isfinite(sub) && sub - v > 0.01) {
                        double t = sub - sz;
                        if (!zseen || t > amax) amax = t;
                        double pu = dx_t * gx + dy_t * gy;
                        double pv = (-dy_t) * gx + dx_t * gy;
                        if (!zseen) {
                            pumin = pumax = pu; pvmin = pvmax = pv;
                        } else {
                            if (pu < pumin) pumin = pu;
                            if (pu > pumax) pumax = pu;
                            if (pv < pvmin) pvmin = pv;
                            if (pv > pvmax) pvmax = pv;
                        }
                        zseen = 1;
                    }
                }
            }
        }
    }

    if (!msk_any) {
        out->status = 3;                     /* Python: continue (no air) */
        memset(hist, 0, FWD_NBINS * sizeof(unsigned int));
        return;
    }
    out->status = 2;
    out->nrem = nrem;
    out->removed = removed;
    if (nrem > 0) out->hist_any = 1;
    double dmax_eff = dmax_nan ? NAN : dmax;
    out->dmax = dmax_eff;
    out->dmax_valid = isfinite(dmax_eff);

    if (!cutting) {
        out->collided = any_cut;             /* np.any(cut > REMOVE_EPS) */
        return;
    }

    double eeff = emax_nan ? NAN : (eseen ? emax : -INF);
    int engaged = eeff > tip;
    out->engaged = engaged;
    if (!engaged) out->air = 1;

    if (engage_track && engaged) {
        double ew = pseen ? pmax - pmin : NAN;
        if (!isfinite(ew)) ew = 0.0;         /* finite guard BEFORE clamp */
        if (ew < 0.0) ew = 0.0;
        double twoR = 2.0 * R;
        if (ew > twoR) ew = twoR;
        out->ew = ew;
        out->ew_valid = 1;
    }

    if (zb_on) {
        if (vol_sum > 0.0) zb[0] += (vol_sum * cell) * cell;
        if (zseen) {
            if (amax > zb[1]) zb[1] = amax;
            double extv = pvmax - pvmin;
            if (extv > zb[2]) zb[2] = extv;
            double dv = hypot(pumax - pumin, pvmax - pvmin);
            if (dv > zb[3]) zb[3] = dv;
        }
    }

    if (removed > eps) {
        for (int64_t j = 0; j < nh; j++) {
            double *wrow = sw + j * nx;
            for (int64_t i = 0; i < nw; i++)
                if (scr_m[j * nw + i])
                    wrow[i] = nn(wrow[i], scr_v[j * nw + i]);
        }
        out->updated = 1;
    }
}
