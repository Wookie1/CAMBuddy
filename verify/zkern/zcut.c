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

/* ---------------------------------------------------------------------
 * task SP-K2B: the WHOLE per-sample loop of simulate() for ONE move in C.
 *
 * For each sample (sx, sy, sz) of the move, in the Python order:
 *   1. near-mask precheck: floor((sx-x0)/cell), floor((sy-y0)/cell) out of
 *      the grid or outside the dilated window mask -> air (cutting adds
 *      seg_len) and skip the sample;
 *   2. the shank block (cutting & shank_on): window of radius ks,
 *      vsh = where(dd <= Rs + 0.75*cell, np.maximum(stock, part), -inf),
 *      vtop = max (NaN-poisoned like np.max); HIT if vtop > sz + flute + 0.01;
 *      running max excess picks shank_worst_xy;
 *   3. the holder block (cutting & holder_on): Bstat pretest at the clipped
 *      centre cell, then vH = where(dd <= Rh, max(where(isfinite(stock),
 *      stock, -inf), part), -inf); HIT if vtop > nose = sz + stickout;
 *      running max intrusion picks holder_worst_xy;
 *   4. the SP-K2 cut block (zcut_sample above), its per-sample scalars
 *      folded into the move accumulators exactly as the Python loop does.
 *
 * worst-xy pick reproduces np.argmin's tie rule: among equal minima of
 *     cand = dd + where(part >= vtop - 1e-9, 0.0, 1e6)
 *     cand = where(vsh/vH >= vtop - 1e-9, cand, inf)
 * the FIRST index in row-major order (j outer, i inner, strict <) wins.
 * Air length accumulates by repeated += seg_len in the same order as the
 * Python loop within a move (the per-move sum is folded into air_length).
 * ------------------------------------------------------------------- */

/* per-move parameters; layout must match zkern.ZMoveParams in __init__.py */
typedef struct {
    double *stock;          /* (ny, nx) row-major, live grid */
    const double *part;     /* (ny, nx) part top-Z */
    const double *xs;       /* nx cell-centre x */
    const double *ys;       /* ny cell-centre y */
    const unsigned char *wm;    /* window mask uint8 grid or NULL */
    const unsigned char *nearm; /* dilated window mask uint8 grid or NULL */
    const double *bstat;    /* holder static bound grid or NULL */
    int64_t nx, ny;
    double x0, y0, cell;
    double R;               /* tool radius */
    int64_t tool;           /* 0 flat, 1 bull, 2 ball */
    double corner;
    int64_t k;              /* cut window radius */
    double eps;             /* REMOVE_EPS */
    double fwd_bin;         /* FWD_BIN_MM */
    int64_t shank_on;
    double Rs;              /* shank radius */
    double flute;
    int64_t ks;             /* shank window radius */
    int64_t holder_on;
    double Rh;              /* holder envelope radius */
    double stickout;
    int64_t kH;             /* holder window radius */
    /* per-move (set by the caller before each zcut_move call) */
    int64_t cutting;
    int64_t engage_track;
    int64_t zb_on;
    double dx_t, dy_t;      /* unit travel direction */
    const double *pre;      /* ZE2B pre-move snapshot or NULL */
    int64_t pre_stride, pre_ilo, pre_jlo;
    /* scratch, (2k+1)^2 */
    double *scr_v;
    unsigned char *scr_m;
} ZMoveParams;

/* per-move outputs; layout must match zkern.ZMoveOut in __init__.py */
typedef struct {
    double move_area;
    double move_max_depth;
    double move_max_engage;
    int64_t move_shank;
    int64_t move_holder;
    int64_t move_collided;
    int64_t hist_any;       /* some sample had nrem > 0 */
} ZMoveOut;

/* cross-move running state; layout must match zkern.ZRunState.
 * air_length accumulates ONE SEG_LEN AT A TIME in call order, so the C
 * path's air_length is BIT-identical to the Python loop's running sum. */
typedef struct {
    double shank_depth;
    int64_t shank_worst_set;
    double shank_worst_x, shank_worst_y;
    double holder_intrusion;
    int64_t holder_worst_set;
    double holder_worst_x, holder_worst_y;
    double air_length;
} ZRunState;

/* shank worst-xy: np.argmin(cand), first equal minimum in row-major order */
static void shank_worst(const ZMoveParams *p, int64_t slo, int64_t shi,
                        int64_t tlo, int64_t thi, double sx, double sy,
                        double pad, double vt, double *wx, double *wy)
{
    const double INF = INFINITY;
    double best = INF;
    int64_t bj = tlo, bi = slo;
    for (int64_t j = tlo; j < thi; j++) {
        double gy = p->ys[j] - sy;
        for (int64_t i = slo; i < shi; i++) {
            double dd = hypot(p->xs[i] - sx, gy);
            double c = dd + (p->part[j * p->nx + i] >= vt ? 0.0 : 1e6);
            double vsh = dd <= pad
                         ? nm(p->stock[j * p->nx + i], p->part[j * p->nx + i])
                         : -INF;
            if (!(vsh >= vt)) c = INF;
            if (c < best) { best = c; bj = j; bi = i; }
        }
    }
    *wx = p->xs[bi];
    *wy = p->ys[bj];
}

/* holder worst-xy: same argmin tie rule, holder masks */
static void holder_worst(const ZMoveParams *p, int64_t slo, int64_t shi,
                         int64_t tlo, int64_t thi, double sx, double sy,
                         double vt, double *wx, double *wy)
{
    const double INF = INFINITY;
    double best = INF;
    int64_t bj = tlo, bi = slo;
    for (int64_t j = tlo; j < thi; j++) {
        double gy = p->ys[j] - sy;
        for (int64_t i = slo; i < shi; i++) {
            double dd = hypot(p->xs[i] - sx, gy);
            double c = dd + (p->part[j * p->nx + i] >= vt ? 0.0 : 1e6);
            double s = p->stock[j * p->nx + i];
            double vH = dd <= p->Rh
                        ? nm(isfinite(s) ? s : -INF, p->part[j * p->nx + i])
                        : -INF;
            if (!(vH >= vt)) c = INF;
            if (c < best) { best = c; bj = j; bi = i; }
        }
    }
    *wx = p->xs[bi];
    *wy = p->ys[bj];
}

void zcut_move(const ZMoveParams *p, const double *samples, int64_t nsamp,
               double seg_len, ZMoveOut *out, ZRunState *run,
               double *zb, unsigned int *move_hist)
{
    const double INF = INFINITY;
    const int64_t nx = p->nx, ny = p->ny;
    const int cutting = (int)p->cutting;
    unsigned int hist[FWD_NBINS];
    ZOut zout;
    double wx, wy;

    memset(out, 0, sizeof(*out));
    memset(move_hist, 0, FWD_NBINS * sizeof(unsigned int));

    for (int64_t s = 0; s < nsamp; s++) {
        const double sx = samples[3 * s];
        const double sy = samples[3 * s + 1];
        const double sz = samples[3 * s + 2];
        const int64_t i0 = (int64_t)floor((sx - p->x0) / p->cell);
        const int64_t j0 = (int64_t)floor((sy - p->y0) / p->cell);

        /* 1. near-mask precheck (dilated window): cannot touch a window
         * cell -> air for a cutting sample, skip everything else */
        if (p->nearm && (i0 < 0 || j0 < 0 || i0 >= nx || j0 >= ny ||
                         !p->nearm[j0 * nx + i0])) {
            if (cutting) run->air_length += seg_len;
            continue;
        }

        /* 2. shank block: material within Rs + 0.75*cell above flute top */
        if (cutting && p->shank_on) {
            int64_t slo = i0 - p->ks, shi = i0 + p->ks + 1;
            int64_t tlo = j0 - p->ks, thi = j0 + p->ks + 1;
            if (slo < 0) slo = 0;
            if (shi > nx) shi = nx;
            if (tlo < 0) tlo = 0;
            if (thi > ny) thi = ny;
            if (slo < shi && tlo < thi) {
                const double pad = p->Rs + 0.75 * p->cell;
                int vnan = 0;
                double vtop = -INF;
                for (int64_t j = tlo; j < thi; j++) {
                    double gy = p->ys[j] - sy;
                    for (int64_t i = slo; i < shi; i++) {
                        double dd = hypot(p->xs[i] - sx, gy);
                        if (dd <= pad) {
                            double v = nm(p->stock[j * nx + i],
                                          p->part[j * nx + i]);
                            if (isnan(v)) vnan = 1;
                            else if (v > vtop) vtop = v;
                        }
                    }
                }
                if (!vnan && vtop > sz + p->flute + 0.01) {
                    out->move_shank = 1;
                    double excess = vtop - (sz + p->flute);
                    if (excess > run->shank_depth) {
                        run->shank_depth = excess;
                        shank_worst(p, slo, shi, tlo, thi, sx, sy,
                                    pad, vtop - 1e-9, &wx, &wy);
                        run->shank_worst_x = wx;
                        run->shank_worst_y = wy;
                        run->shank_worst_set = 1;
                    }
                }
            }
        }

        /* 3. holder block: envelope material above the nose at tip+stickout */
        if (cutting && p->holder_on) {
            const double nose = sz + p->stickout;
            int64_t ioc = i0 < 0 ? 0 : (i0 > nx - 1 ? nx - 1 : i0);
            int64_t joc = j0 < 0 ? 0 : (j0 > ny - 1 ? ny - 1 : j0);
            if (p->bstat[joc * nx + ioc] > nose) {
                int64_t slo = i0 - p->kH, shi = i0 + p->kH + 1;
                int64_t tlo = j0 - p->kH, thi = j0 + p->kH + 1;
                if (slo < 0) slo = 0;
                if (shi > nx) shi = nx;
                if (tlo < 0) tlo = 0;
                if (thi > ny) thi = ny;
                if (slo < shi && tlo < thi) {
                    int vnan = 0;
                    double vtop = -INF;
                    for (int64_t j = tlo; j < thi; j++) {
                        double gy = p->ys[j] - sy;
                        for (int64_t i = slo; i < shi; i++) {
                            double dd = hypot(p->xs[i] - sx, gy);
                            if (dd <= p->Rh) {
                                double st = p->stock[j * nx + i];
                                double v = nm(isfinite(st) ? st : -INF,
                                              p->part[j * nx + i]);
                                if (isnan(v)) vnan = 1;
                                else if (v > vtop) vtop = v;
                            }
                        }
                    }
                    if (!vnan && vtop > nose) {
                        out->move_holder = 1;
                        double intr = vtop - nose;
                        if (intr > run->holder_intrusion) {
                            run->holder_intrusion = intr;
                            holder_worst(p, slo, shi, tlo, thi, sx, sy,
                                         vtop - 1e-9, &wx, &wy);
                            run->holder_worst_x = wx;
                            run->holder_worst_y = wy;
                            run->holder_worst_set = 1;
                        }
                    }
                }
            }
        }

        /* 4. the SP-K2 cut block, then fold its scalars into the move
         * accumulators exactly as the Python per-sample code does */
        zcut_sample(p->stock, nx, ny, i0, j0, p->k, p->xs, p->ys,
                    sx, sy, sz, p->R, p->tool, p->corner, p->wm,
                    cutting, (int)p->engage_track, (int)p->zb_on, p->cell,
                    p->eps, p->fwd_bin, p->dx_t, p->dy_t,
                    (cutting && p->zb_on) ? p->pre : NULL,
                    p->pre_stride, p->pre_ilo, p->pre_jlo,
                    zb, hist, p->scr_v, p->scr_m, &zout);
        if (zout.air) run->air_length += seg_len;
        if (cutting) {
            out->move_area += (double)zout.nrem * p->cell * p->cell;
            if (zout.hist_any) {
                out->hist_any = 1;
                for (int b = 0; b < FWD_NBINS; b++)
                    move_hist[b] += hist[b];
            }
            if (zout.dmax_valid && zout.dmax > out->move_max_depth)
                out->move_max_depth = zout.dmax;
            if (zout.ew_valid && zout.ew > out->move_max_engage)
                out->move_max_engage = zout.ew;
        } else if (zout.collided) {
            out->move_collided = 1;
        }
    }
}
