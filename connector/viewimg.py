"""TASK VIEW3D-IMG: render view_iso.png / view_top.png from a run's
view.bin/view.json.

DISPLAY ONLY: reads the run's view files (never engine input) and writes two
PNGs, ~1600 px on the long side. Rendered in-process with PIL + numpy (no
matplotlib, no subprocess): the data is a heightfield + polylines, PIL's PNG
writer is byte-deterministic (no timestamps), and the caller's failure guard
keeps a render error from ever failing a run.

Both pictures show: the part hill-shaded; the stock left (stock - part) as a
heat map with a colour key in mm (below-part in RED, keyed as such); the
toolpaths thin and see-through, coloured per program, with a legend naming
each program/op and its tool; the check.json markers drawn and NUMBERED, the
numbers listed next to their codes in the caption. view_top.png is the top
view; view_iso.png the same scene in an angled (axonometric) view: surface
cells drawn back-to-front, the front wall extruded to the scene floor.
"""
import json
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H = 1600, 1000            # long side 1600 px (test window 1500-1700)
PANEL_X = 1170               # info panel (colour key, legend, caption) starts
BG = (247, 248, 250)
INK = (30, 33, 38)
PROG_COLORS = [(31, 119, 180), (214, 70, 30), (44, 140, 60), (150, 80, 190),
               (200, 130, 10), (20, 140, 150), (180, 60, 140), (110, 115, 40)]
RED = (214, 40, 40)          # below-part (gouge) colour, keyed as such
HEAT_ANCHORS = [(38, 90, 200), (40, 185, 200), (170, 205, 70),
                (240, 220, 60)]      # stock-left ramp: little -> a lot
ISO_ANGLE = 28.0             # deg, rotation about z for the angled view
ISO_SINE = 0.42              # elevation squash of the depth axis
ISO_COSINE = 0.90            # vertical gain of z
ISO_MAX_GRID = 280           # iso surface cells per side (display only)
FEED_ALPHA, RAPID_ALPHA = 170, 70
MARKER_R = 11
MAX_CAPTION = 12             # caption lines before "+N more"


def load_view(json_path, bin_path):
    """Decode view.json/view.bin: (hdr, part, stock, programs, markers);
    nodata cells become nan, z = offset + q*scale."""
    with open(json_path) as fh:
        hdr = json.load(fh)
    with open(bin_path, "rb") as fh:
        raw = fh.read()
    g, z = hdr["grid"], hdr["z"]
    nx, ny = g["nx"], g["ny"]
    npix = nx * ny
    off, sc = z["offset"], z["scale"]
    nd = z.get("nodata", 65535)   # the committed fixture predates the key

    def grid(o):
        q = np.frombuffer(raw[o:o + npix * 2], dtype="<u2").reshape(ny, nx)
        a = q.astype(np.float64) * sc + off
        a[q == nd] = np.nan
        return a

    part = grid(hdr["offsets"]["part"])
    stock = grid(hdr["offsets"]["stock"])
    programs = []
    for p in hdr["programs"]:
        n = p["points"]
        pts = (np.frombuffer(raw[p["xyz_offset"]:p["xyz_offset"] + n * 12],
                             dtype="<f4").reshape(n, 3).astype(np.float64)
               if n else np.zeros((0, 3)))
        flags = (np.frombuffer(raw[p["flags_offset"]:p["flags_offset"] + n],
                               dtype=np.uint8) if n
                 else np.zeros(0, dtype=np.uint8))
        programs.append({"name": p["name"], "points": pts, "flags": flags})
    return hdr, part, stock, programs, hdr.get("markers", [])


def _font(size=15):
    return ImageFont.load_default(size=size)


def _shaded(z, cell):
    """Lambert hillshade of a heightfield (nan-safe): (ny,nx,3) uint8."""
    fin = np.isfinite(z)
    fill = float(np.nanmin(z)) if fin.any() else 0.0
    zf = np.where(fin, z, fill)
    dzdy, dzdx = np.gradient(zf, cell)
    a, b, c = -dzdx, -dzdy, np.ones_like(zf)
    norm = np.sqrt(a * a + b * b + c * c)
    lx, ly, lz = -0.42, -0.52, 0.74
    li = math.sqrt(lx * lx + ly * ly + lz * lz)
    inten = np.clip((a * lx + b * ly + c * lz) / (norm * li), 0.0, 1.0)
    g = (55.0 + 185.0 * inten).astype(np.uint8)
    blue = np.clip(g.astype(np.int32) + 6, 0, 255).astype(np.uint8)
    return np.stack([g, g, blue], axis=-1)


def _heat(resid):
    """Heat map of the stock left (mm): (ny,nx,3) uint8 + alpha in [0,1];
    below-part cells RED, positive stock a fixed ramp, zero/nan alpha 0."""
    out = np.zeros(resid.shape + (3,), dtype=np.uint8)
    a = np.zeros(resid.shape, dtype=np.float64)
    below = np.isfinite(resid) & (resid < 0.0)
    pos = np.isfinite(resid) & (resid > 0.0)
    out[below] = RED
    a[below] = 0.62
    if pos.any():
        pmax = max(float(resid[pos].max()), 1e-9)
        t = np.clip(resid[pos] / pmax, 0.0, 1.0)
        an = np.asarray(HEAT_ANCHORS, dtype=np.float64)
        seg = t * (len(an) - 1)
        i0 = np.clip(seg.astype(int), 0, len(an) - 2)
        f = (seg - i0)[:, None]
        out[pos] = (an[i0] * (1 - f) + an[i0 + 1] * f).astype(np.uint8)
        a[pos] = 0.55 + 0.25 * t
    return out, a


def _blend(rgb, resid):
    """Composite the stock-left heat map over the shaded surface."""
    heat, ha = _heat(resid)
    vis = (np.isfinite(resid) & (resid != 0.0))[..., None]
    mixed = rgb * (1.0 - ha[..., None]) + heat * ha[..., None]
    return np.where(vis, mixed.astype(np.uint8), rgb)


def _scene_bbox(part, stock, programs, markers, g):
    xs, ys = [], []
    for a in (part, stock):
        jj, ii = np.nonzero(np.isfinite(a))
        if len(ii):
            xs.extend([g["x0"] + (ii.min() + 0.5) * g["cell"],
                       g["x0"] + (ii.max() + 0.5) * g["cell"]])
            ys.extend([g["y0"] + (jj.min() + 0.5) * g["cell"],
                       g["y0"] + (jj.max() + 0.5) * g["cell"]])
    for p in programs:
        if len(p["points"]):
            xs.extend([p["points"][:, 0].min(), p["points"][:, 0].max()])
            ys.extend([p["points"][:, 1].min(), p["points"][:, 1].max()])
    for m in markers:
        xs.append(m["x"])
        ys.append(m["y"])
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    pad = 0.03 * max(x1 - x0, y1 - y0, 1.0)
    return x0 - pad, x1 + pad, y0 - pad, y1 + pad


def _draw_paths(draw, programs, proj):
    """Thin see-through polylines: feed solid-ish, rapid thinner and fainter.

    proj(points (n,3)) -> (u, v) screen coordinate arrays."""
    for k, p in enumerate(programs):
        pts = p["points"]
        if len(pts) < 2:
            continue
        col = PROG_COLORS[k % len(PROG_COLORS)]
        u, v = proj(pts)
        xy = np.column_stack([u, v])
        chg = np.flatnonzero(p["flags"][1:] != p["flags"][:-1]) + 1
        bounds = np.concatenate([[0], chg, [len(pts)]])
        for a, b in zip(bounds[:-1], bounds[1:]):
            if b - a < 2:
                continue
            flat = list(xy[a:b].ravel())
            if p["flags"][a]:
                draw.line(flat, fill=col + (FEED_ALPHA,), width=2)
            else:
                draw.line(flat, fill=col + (RAPID_ALPHA,), width=1)


def _draw_markers(draw, markers, proj, z_at):
    """Numbered marker dots: number i+1 matches the caption list."""
    for i, m in enumerate(markers):
        z = m["z"] if m["z"] is not None else z_at(m["x"], m["y"])
        u, v = proj(np.array([m["x"]]), np.array([m["y"]]), np.array([z]))
        x, y = float(u[0]), float(v[0])
        draw.ellipse([x - MARKER_R, y - MARKER_R, x + MARKER_R, y + MARKER_R],
                     fill=(255, 200, 0, 235), outline=(20, 20, 20, 255),
                     width=2)
        s = str(i + 1)
        f = _font(16)
        bb = draw.textbbox((0, 0), s, font=f)
        draw.text((x - (bb[2] - bb[0]) / 2.0 - bb[0],
                   y - (bb[3] - bb[1]) / 2.0 - bb[1]), s, fill=(15, 15, 15),
                  font=f)


def _panel(base, draw, title, legend, markers, pmax, nmin):
    """Colour key (mm, below-part red keyed as such), per-program legend and
    the numbered marker caption."""
    d = draw
    x0 = PANEL_X + 16
    d.text((x0, 18), title, fill=INK, font=_font(19))
    d.text((x0, 46), "stock left (mm)", fill=INK, font=_font(15))
    kx, ky, kw, kh = x0, 70, 34, 260
    an = np.asarray(HEAT_ANCHORS, dtype=np.float64)
    ramp = np.zeros((kh, kw, 3), dtype=np.uint8)
    for yy in range(kh):                       # top = pmax, bottom = 0
        t = 1.0 - yy / (kh - 1.0)
        seg = t * (len(an) - 1)
        i0 = min(int(seg), len(an) - 2)
        f = seg - i0
        ramp[yy] = (an[i0] * (1 - f) + an[i0 + 1] * f).astype(np.uint8)
    base.paste(Image.fromarray(ramp).convert(base.mode), (kx, ky))
    rb = 78                                    # red band: below part
    base.paste(Image.new(base.mode, (kw, rb), RED), (kx, ky + kh))
    d.rectangle([kx, ky, kx + kw, ky + kh + rb], outline=INK, width=1)
    f12 = _font(13)
    d.text((kx + kw + 8, ky - 4), "+%.2f" % pmax, fill=INK, font=f12)
    d.text((kx + kw + 8, ky + kh / 2.0 - 6), "+%.2f" % (pmax / 2.0),
           fill=INK, font=f12)
    d.text((kx + kw + 8, ky + kh - 6), "0", fill=INK, font=f12)
    d.text((kx + kw + 8, ky + kh + rb / 2.0 - 7),
           "below part, to -%.2f" % nmin, fill=INK, font=f12)
    y = ky + kh + rb + 26
    d.text((x0, y), "programs / tools", fill=INK, font=_font(15))
    y += 24
    for i, (name, tool) in enumerate(legend):
        col = PROG_COLORS[i % len(PROG_COLORS)]
        d.line([(x0, y + 7), (x0 + 26, y + 7)], fill=col, width=3)
        d.text((x0 + 34, y), name + (" - " + tool if tool else ""), fill=INK,
               font=_font(14))
        y += 20
    d.line([(x0, y + 7), (x0 + 26, y + 7)], fill=(150, 150, 150), width=1)
    d.text((x0 + 34, y), "rapid moves (fainter)", fill=INK, font=_font(14))
    y += 30
    d.text((x0, y), "check.json markers", fill=INK, font=_font(15))
    y += 24
    if not markers:
        d.text((x0, y), "none (all gates clean)", fill=INK, font=_font(14))
    for i, m in enumerate(markers[:MAX_CAPTION]):
        d.ellipse([x0, y + 1, x0 + 14, y + 15], fill=(255, 200, 0),
                  outline=INK, width=1)
        d.text((x0 + 4, y + 1), str(i + 1), fill=INK, font=_font(12))
        d.text((x0 + 22, y), "%s at x=%.1f y=%.1f" % (m["code"], m["x"],
                                                      m["y"]),
               fill=INK, font=_font(14))
        y += 20
    if len(markers) > MAX_CAPTION:
        d.text((x0, y), "+%d more" % (len(markers) - MAX_CAPTION), fill=INK,
               font=_font(14))


def _marker_z_at(zsurf, g, shape):
    """Nearest-cell surface z (mm) for a marker without its own z."""
    ny, nx = shape

    def z_at(x, y):
        jj = int(np.clip((y - g["y0"]) / g["cell"], 0, ny - 1))
        ii = int(np.clip((x - g["x0"]) / g["cell"], 0, nx - 1))
        v = zsurf[jj, ii]
        return float(v) if np.isfinite(v) else 0.0
    return z_at


def render_images(view_json, view_bin, out_iso, out_top, tools=None):
    """Render the run's two pictures from view.json/view.bin to out_iso /
    out_top; tools: {program name: tool label} for the legend. Returns the
    caption strings actually drawn (checkable without OCR):
    {"view_iso.png", "view_top.png", "markers": [{number, code}], "legend":
    ["name - tool", ...], "color_key_mm": {...}}."""
    hdr, part, stock, programs, markers = load_view(view_json, view_bin)
    g = hdr["grid"]
    resid = stock - part
    finr = resid[np.isfinite(resid)]
    pmax = float(finr[finr > 0].max()) if (finr > 0).any() else 0.0
    nmin = float(-finr[finr < 0].min()) if (finr < 0).any() else 0.0
    tools = tools or {}
    legend = [(p["name"], tools.get(p["name"])) for p in programs]
    caption = [{"number": i + 1, "code": m["code"]}
               for i, m in enumerate(markers)]
    bx0, bx1, by0, by1 = _scene_bbox(part, stock, programs, markers, g)
    plot = (40, 40, PANEL_X - 20, H - 40)
    zsurf = np.where(np.isfinite(part), part, stock)
    z_at = _marker_z_at(zsurf, g, part.shape)

    # ------------------------------------------------------------ top view
    base = Image.new("RGB", (W, H), BG)
    sc = min((plot[2] - plot[0]) / max(bx1 - bx0, 1e-9),
             (plot[3] - plot[1]) / max(by1 - by0, 1e-9))
    ox = (plot[0] + plot[2]) / 2.0 - (bx0 + bx1) / 2.0 * sc
    oy = (plot[1] + plot[3]) / 2.0 + (by0 + by1) / 2.0 * sc

    def top_uv(xs, ys, zs=None):
        return ox + np.asarray(xs, dtype=np.float64) * sc, \
            oy - np.asarray(ys, dtype=np.float64) * sc

    rgb = _blend(_shaded(zsurf, g["cell"]), resid)
    rgb[~np.isfinite(zsurf)] = BG
    gi = Image.fromarray(rgb[::-1])            # image row 0 = max y
    gw = max(int(round(part.shape[1] * g["cell"] * sc)), 1)
    gh = max(int(round(part.shape[0] * g["cell"] * sc)), 1)
    gi = gi.resize((gw, gh), Image.BILINEAR)
    base.paste(gi, (int(round(ox + g["x0"] * sc)),
                    int(round(oy - (g["y0"] + part.shape[0] * g["cell"])
                              * sc))))
    _panel(base, ImageDraw.Draw(base), "top view - part shaded, stock left",
           legend, markers, max(pmax, 0.01), max(nmin, 0.01))
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    _draw_paths(d, programs, lambda p: top_uv(p[:, 0], p[:, 1]))
    _draw_markers(d, markers, top_uv, z_at)
    Image.alpha_composite(base.convert("RGBA"), ov).convert("RGB").save(
        out_top, "png")

    # ------------------------------------------------------------ iso view
    base = Image.new("RGB", (W, H), BG)
    k = max(1, int(math.ceil(max(part.shape) / float(ISO_MAX_GRID))))
    ipart, istock, ou, od = _iso_grids(part, stock, k)
    ny, nx = ipart.shape
    cell = g["cell"] * k
    ca = math.cos(math.radians(ISO_ANGLE))
    sa = math.sin(math.radians(ISO_ANGLE))
    zs = np.where(np.isfinite(ipart), ipart, istock)
    finite = np.isfinite(zs)
    zmin = float(np.nanmin(zs)) if finite.any() else 0.0
    zmax = float(np.nanmax(zs)) if finite.any() else 1.0
    zref = (zmin + zmax) / 2.0
    # the rotation keeps the ORIGINAL grid centre fixed; block i covers
    # original cells [i*k, (i+1)*k)
    bx, by = (part.shape[1] - 1) / 2.0, (part.shape[0] - 1) / 2.0

    def iso_uv(xm, ym, zm):
        ix = (np.asarray(xm, dtype=np.float64) - g["x0"]) / g["cell"] - bx
        iy = (np.asarray(ym, dtype=np.float64) - g["y0"]) / g["cell"] - by
        X = (ix * ca - iy * sa) / k             # rotated, block-grid units
        Y = (ix * sa + iy * ca) / k
        u = (X - ou) * cell
        v = (Y - od) * cell * ISO_SINE \
            - (np.asarray(zm, dtype=np.float64) - zref) * ISO_COSINE
        return u, v

    def iso_px(u, v):
        return ox + u * sc, oy - v * sc

    # fit: finite surface cells (+ wall floor) + paths + markers
    fi = np.nonzero(finite.any(axis=0))[0]
    fj = np.nonzero(finite.any(axis=1))[0]
    if len(fi):
        u_lo = int(fi.min()) * cell
        u_hi = (int(fi.max()) + 1) * cell
        v_lo = int(fj.min()) * cell * ISO_SINE - (zmax - zref) * ISO_COSINE
        v_hi = (int(fj.max()) + 1) * cell * ISO_SINE \
            + (zref - zmin) * ISO_COSINE
    else:
        u_lo, u_hi, v_lo, v_hi = 0.0, 1.0, 0.0, 1.0
    for p in programs:
        if len(p["points"]):
            uu, vv = iso_uv(p["points"][:, 0], p["points"][:, 1],
                            p["points"][:, 2])
            u_lo = min(u_lo, float(np.min(uu)))
            u_hi = max(u_hi, float(np.max(uu)))
            v_lo = min(v_lo, float(np.min(vv)))
            v_hi = max(v_hi, float(np.max(vv)))
    for m in markers:
        uu, _ = iso_uv(m["x"], m["y"], 0.0)
        u_lo = min(u_lo, float(uu))
        u_hi = max(u_hi, float(uu))
    sc = min((plot[2] - plot[0]) / max(u_hi - u_lo, 1e-9),
             (plot[3] - plot[1]) / max(v_hi - v_lo, 1e-9))
    ox = (plot[0] + plot[2]) / 2.0 - (u_lo + u_hi) / 2.0 * sc
    oy = (plot[1] + plot[3]) / 2.0 + (v_lo + v_hi) / 2.0 * sc

    colr = _blend(_shaded(zs, cell), istock - ipart)
    dark = (colr.astype(np.float64) * 0.55).astype(np.uint8)
    d = ImageDraw.Draw(base)

    def v_of(jidx, zv):
        return (jidx * cell * ISO_SINE - (zv - zref) * ISO_COSINE) * sc

    for j in range(ny):                        # painter: back row first
        for i in range(nx):
            if not finite[j, i]:
                continue
            zv = float(zs[j, i])
            x0 = ox + i * cell * sc
            x1 = ox + (i + 1) * cell * sc
            c = tuple(int(x) for x in colr[j, i])
            d.polygon([x0, oy - v_of(j, zv), x1, oy - v_of(j, zv),
                       x1, oy - v_of(j + 1, zv), x0, oy - v_of(j + 1, zv)],
                      fill=c, outline=c)
            # viewer-facing wall where the surface drops (or ends) ahead
            zn = float(zs[j + 1, i]) if j + 1 < ny and finite[j + 1, i] \
                else zmin
            if zv > zn + 1e-12:
                c = tuple(int(x) for x in dark[j, i])
                d.polygon([x0, oy - v_of(j + 1, zv), x1, oy - v_of(j + 1, zv),
                           x1, oy - v_of(j + 1, zn), x0,
                           oy - v_of(j + 1, zn)], fill=c, outline=c)
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dd = ImageDraw.Draw(ov)

    def iso_proj(pts):
        return iso_px(*iso_uv(pts[:, 0], pts[:, 1], pts[:, 2]))

    _draw_paths(dd, programs, iso_proj)
    _draw_markers(dd, markers,
                  lambda xs, ys, zs_: iso_px(*iso_uv(xs, ys, zs_)), z_at)
    base = base.convert("RGBA")
    base = Image.alpha_composite(base, ov)
    _panel(base, ImageDraw.Draw(base),
           "iso view - part shaded, stock left", legend, markers,
           max(pmax, 0.01), max(nmin, 0.01))
    base.convert("RGB").save(out_iso, "png")
    return {"view_iso.png": out_iso, "view_top.png": out_top,
            "markers": caption,
            "legend": [n + (" - " + t if t else "") for n, t in legend],
            "color_key_mm": {"max_stock_left": pmax,
                             "max_below_part": nmin}}


def _iso_grids(part, stock, k):
    """Block-downsample (part: max, stock: min; display only, nan-safe) then
    rotate both by ISO_ANGLE; returns (part, stock, u-offset, v-offset)."""
    def block(a, sentinel):
        ny, nx = a.shape
        a = np.where(np.isfinite(a), a, sentinel)
        py, px = (-ny) % k, (-nx) % k
        if py or px:
            a = np.pad(a, ((0, py), (0, px)), mode="constant",
                       constant_values=sentinel)
        b = a.reshape(a.shape[0] // k, k, a.shape[1] // k, k)
        r = b.max(axis=(1, 3)) if sentinel == -np.inf \
            else b.min(axis=(1, 3))
        return np.where(np.isfinite(r), r, np.nan)
    p, u_off, v_off = _rotate(block(part, -np.inf))
    s, _, _ = _rotate(block(stock, np.inf))
    return p, s, u_off, v_off


def _rotate(a, ang_deg=ISO_ANGLE):
    """Nearest-resample rotation of a heightfield about its centre; cells
    outside the source stay nan (display only). Returns the rotated grid and
    the window offsets (min rotated u/v over the source corners)."""
    ny, nx = a.shape
    rad = math.radians(ang_deg)
    ca, sa = math.cos(rad), math.sin(rad)
    cx, cy = (nx - 1) / 2.0, (ny - 1) / 2.0
    xs = np.array([-cx, nx - 1 - cx, nx - 1 - cx, -cx])
    ys = np.array([-cy, -cy, ny - 1 - cy, ny - 1 - cy])
    uu, vv = xs * ca - ys * sa, xs * sa + ys * ca
    nx2 = int(math.ceil(uu.max() - uu.min())) + 1
    ny2 = int(math.ceil(vv.max() - vv.min())) + 1
    I = np.arange(nx2)
    J = np.arange(ny2)
    # window position (I, J) carries rotated coords (I + uu.min, J + vv.min);
    # rotate those back into source index space
    sx = np.rint((I[None, :] + uu.min()) * ca
                 + (J[:, None] + vv.min()) * sa + cx).astype(np.int64)
    sy = np.rint(-(I[None, :] + uu.min()) * sa
                 + (J[:, None] + vv.min()) * ca + cy).astype(np.int64)
    ok = (sx >= 0) & (sx < nx) & (sy >= 0) & (sy < ny)
    out = a[np.clip(sy, 0, ny - 1), np.clip(sx, 0, nx - 1)]
    return np.where(ok, out, np.nan), float(uu.min()), float(vv.min())
