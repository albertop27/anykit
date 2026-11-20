"""Replace smudgy pseudo-text on kit items with crisp real text (real Cyrillic, invented words). Blender script.

    blender -b --factory-startup --python kit/tools/fix_labels.py -- --labels scenes/kit/labels.json \
        --items out/items --out out/items_fixed [--ids field_radio toolbox] [--art scenes/kit/labels_art] [--blend]

Per item (LOD0 and LOD1 GLBs): for each label in labels.json (fields: see label_art.py) it
  1. finds the texels under the label rectangle: every UV triangle facing the view is rasterised, each texel gets its
     3D position (barycentric), is projected into the view plane (plane mode: right/up of the named ortho view;
     cylinder mode: arc length around the fitted vertical axis), kept if inside the rectangle (+ a ring for sampling),
     unoccluded (BVH ray toward the camera) and on the label's surface (within `tol` m of the median depth, so knobs,
     handles and dial hubs in front are left alone);
  2. paints the ground colour (median of the ring around the rectangle, or label["ground"]) with grain and soft
     low-frequency variation over the rectangle, feathered at its edge;
  3. composites the crisp text (label_art.py PNG, sampled 3x3 per texel) in the ink colour;
  4. flattens the normal map (and roughness / metal / AO) over the same texels so embossed garbage does not survive;
     the ink is rough and non-metallic.
Writes <out>/<id>/<id>.glb, <id>_lod1.glb, a stats.json copy (and <id>.blend with --blend): the layout library.py
reads. Pillow is not in Blender's Python, so label_art.py runs in a normal Python (--py, default the playground venv).
Label coordinates are item metres: u right, v up from the item's bbox centre in that view (ortho_views.py +
ortho_grid.py give an image with that grid to read them off). Per label: id, item, view, mode, center, size, tol,
ring, feather, ground, variation, grain.
"""
import json
import math
import os
import shutil
import subprocess
import sys

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

argv = sys.argv[sys.argv.index("--") + 1:]


def opt(k, d=None, n=None):
    if k not in argv:
        return d
    i = argv.index(k) + 1
    if n is None:
        return argv[i]
    out = []
    while i < len(argv) and not argv[i].startswith("--"):
        out.append(argv[i])
        i += 1
    return out


LABELS = os.path.abspath(opt("--labels", "scenes/kit/labels.json"))
ITEMS = os.path.abspath(opt("--items", "out/items"))
OUT = os.path.abspath(opt("--out", "out/items_fixed"))
ART = os.path.abspath(opt("--art", os.path.join(os.path.dirname(LABELS), "labels_art")))
# default: the playground venv two levels above this fork (vendor/anykit -> .venv); override with --py
PY = opt("--py", os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".venv", "Scripts", "python.exe")))
PPM = opt("--ppm", "9000")
spec = json.load(open(LABELS, encoding="utf-8"))
labels = spec["labels"]
ids = opt("--ids", None, n=True) if "--ids" in argv else sorted({l["item"] for l in labels})

# view name -> (direction toward the camera, right, up) in item space (front faces -Y, Z up)
VIEWS = {"front": ((0, -1, 0), (1, 0, 0), (0, 0, 1)), "back": ((0, 1, 0), (-1, 0, 0), (0, 0, 1)),
         "left": ((-1, 0, 0), (0, -1, 0), (0, 0, 1)), "right": ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
         "top": ((0, 0, 1), (1, 0, 0), (0, 1, 0))}

if not os.path.isfile(PY):
    PY = "python"
subprocess.run([PY, os.path.join(os.path.dirname(os.path.abspath(__file__)), "label_art.py"), "--labels", LABELS,
                "--out", ART, "--ppm", PPM], check=True)


def load_item(path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=path)
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    assert len(meshes) == 1, f"{path}: expected one mesh, found {len(meshes)}"
    ob = meshes[0]
    mat = ob.data.materials[0]
    nodes = mat.node_tree.nodes
    bsdf = next(n for n in nodes if n.type == "BSDF_PRINCIPLED")

    def img_into(sock):
        stack = [sock]
        while stack:
            s = stack.pop()
            for l in s.links:
                n = l.from_node
                if n.type == "TEX_IMAGE":
                    return n.image
                stack += [i for i in n.inputs if i.is_linked]
        return None
    return ob, img_into(bsdf.inputs["Base Color"]), img_into(bsdf.inputs["Roughness"]), img_into(bsdf.inputs["Normal"])


def get_px(img):
    a = np.empty(img.size[0] * img.size[1] * 4, np.float32)
    img.pixels.foreach_get(a)
    return a.reshape(img.size[1], img.size[0], 4)


def set_px(img, a):
    img.pixels.foreach_set(a.ravel())
    img.update()
    img.pack()  # only images we changed are repacked


def noise2(shape, cell, rng):
    h, w = shape
    sm = max(2, int(cell))
    small = rng.random((h // sm + 3, w // sm + 3)).astype(np.float32)
    ys = np.linspace(0, small.shape[0] - 1.001, h)
    xs = np.linspace(0, small.shape[1] - 1.001, w)
    y0, x0 = ys.astype(int), xs.astype(int)
    fy, fx = (ys - y0)[:, None], (xs - x0)[None, :]
    a = small[y0][:, x0] * (1 - fx) + small[y0][:, x0 + 1] * fx
    b = small[y0 + 1][:, x0] * (1 - fx) + small[y0 + 1][:, x0 + 1] * fx
    return a * (1 - fy) + b * fy


def mesh_arrays(ob):
    me = ob.data
    me.calc_loop_triangles()
    n = len(me.vertices)
    co = np.empty(n * 3, np.float32)
    me.vertices.foreach_get("co", co)
    co = co.reshape(n, 3).astype(np.float64)
    mw = np.array(ob.matrix_world, np.float64)
    co = co @ mw[:3, :3].T + mw[:3, 3]
    nt = len(me.loop_triangles)
    tv = np.empty(nt * 3, np.int32)
    tl = np.empty(nt * 3, np.int32)
    me.loop_triangles.foreach_get("vertices", tv)
    me.loop_triangles.foreach_get("loops", tl)
    uv = np.empty(len(me.loops) * 2, np.float32)
    me.uv_layers.active.data.foreach_get("uv", uv)
    uv = uv.reshape(-1, 2)
    return co, tv.reshape(-1, 3), uv[tl.reshape(-1, 3)].astype(np.float64)


def raster(uvt, P, W, H):
    """Rasterise triangles (uvt (n,3,2), P (n,3,3)) into texels -> tx, ty, pos (m,3), tri index (m,)."""
    txs, tys, pos, tri = [], [], [], []
    owner = np.full(W * H, -1, np.int32)
    for i in range(len(uvt)):
        a, b, c = uvt[i] * (W, H)
        x0, x1 = int(math.floor(min(a[0], b[0], c[0]) - 1)), int(math.ceil(max(a[0], b[0], c[0]) + 1))
        y0, y1 = int(math.floor(min(a[1], b[1], c[1]) - 1)), int(math.ceil(max(a[1], b[1], c[1]) + 1))
        x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, W - 1), min(y1, H - 1)
        if x1 < x0 or y1 < y0:
            continue
        gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        d = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(d) < 1e-12:
            continue
        l0 = ((b[1] - c[1]) * (gx - c[0]) + (c[0] - b[0]) * (gy - c[1])) / d
        l1 = ((c[1] - a[1]) * (gx - c[0]) + (a[0] - c[0]) * (gy - c[1])) / d
        l2 = 1 - l0 - l1
        m = (l0 >= -0.02) & (l1 >= -0.02) & (l2 >= -0.02)
        if not m.any():
            continue
        ix, iy = (gx[m] - 0.5).astype(int), (gy[m] - 0.5).astype(int)
        key = iy * W + ix
        free = owner[key] < 0
        if not free.any():
            continue
        owner[key[free]] = i
        l0, l1, l2 = l0[m][free], l1[m][free], l2[m][free]
        txs.append(ix[free])
        tys.append(iy[free])
        pos.append(l0[:, None] * P[i, 0] + l1[:, None] * P[i, 1] + l2[:, None] * P[i, 2])
        tri.append(np.full(free.sum(), i))
    if not txs:
        return None
    return np.concatenate(txs), np.concatenate(tys), np.concatenate(pos), np.concatenate(tri)


def fit_circle(xy):
    A = np.c_[2 * xy[:, 0], 2 * xy[:, 1], np.ones(len(xy))]
    sol = np.linalg.lstsq(A, (xy ** 2).sum(1), rcond=None)[0]
    return sol[:2], math.sqrt(max(sol[2] + sol[0] ** 2 + sol[1] ** 2, 1e-9))


def sample_art(art, s, t, rect, ppm_art, sub):
    """Bilinear-sample the art RGBA (top-origin array) at label coords (s,t) m, averaged over sub-offsets."""
    cs, ct, w, h = rect
    ah, aw = art.shape[:2]
    acc = np.zeros((len(s), 4), np.float32)
    for ds, dt in sub:
        x = (s + ds - (cs - w / 2)) * ppm_art - 0.5
        y = ((ct + h / 2) - (t + dt)) * ppm_art - 0.5
        ok = (x >= 0) & (y >= 0) & (x < aw - 1) & (y < ah - 1)
        xc, yc = np.clip(x, 0, aw - 1.001), np.clip(y, 0, ah - 1.001)
        x0, y0 = xc.astype(int), yc.astype(int)
        fx, fy = (xc - x0)[:, None], (yc - y0)[:, None]
        v = (art[y0, x0] * (1 - fx) * (1 - fy) + art[y0, x0 + 1] * fx * (1 - fy) + art[y0 + 1, x0] * (1 - fx) * fy
             + art[y0 + 1, x0 + 1] * fx * fy)
        v[~ok] = 0
        acc += v
    return acc / len(sub)


def fit_ground(s, t, cols, cs, ct, w, h, M, bias="none"):
    """Robust low-order (quadratic, or linear when the ring is lopsided) colour surface through the ring texels."""
    x, y = (s - cs) / (w / 2 + M), (t - ct) / (h / 2 + M)
    def phi(x, y, quad):
        x, y = np.clip(x, -1.4, 1.4), np.clip(y, -1.4, 1.4)
        return np.c_[np.ones_like(x), x, y, x * x, x * y, y * y] if quad else np.c_[np.ones_like(x), x, y]
    quad = x.min() < -0.8 and x.max() > 0.8 and y.min() < -0.8 and y.max() > 0.8
    P = phi(x, y, quad)
    m = np.ones(len(x), bool)
    for _ in range(4):
        coef = np.linalg.lstsq(P[m], cols[m], rcond=None)[0]
        sres = (P @ coef - cols).mean(1)  # fit - actual: > 0 where the texel is darker than the fit
        res = np.abs(sres)
        thr = max(2.5 * 1.4826 * np.median(res[m]), 0.012)
        if bias == "light":    # ground is the light paint; chips and scribbles are darker
            m = sres < thr * 0.5
        elif bias == "dark":   # ground is the dark paint; chips and old stencil are lighter
            m = sres > -thr * 0.5
        else:
            m = res < thr
        if m.sum() < 30:
            break
    thr = max(2.5 * 1.4826 * float(np.median(np.abs((P @ coef - cols).mean(1))[m])), 0.025)
    return (lambda s2, t2: phi((s2 - cs) / (w / 2 + M), (t2 - ct) / (h / 2 + M), quad) @ coef), thr


def find_texels(ob, lab, bvh, geo, W, H):
    """Texels under a label: returns dict(tx, ty, s, t, keep, inside, ring, ci, area, R) or None."""
    co, tv, uvt = geo
    vdir, right, up = (np.array(v, float) for v in VIEWS[lab["view"]])
    cs, ct = lab["center"]
    w, h = lab["size"]
    M = lab.get("ring", 0.012)
    tol = lab.get("tol", 0.004)
    cyl = lab.get("mode", "plane") == "cylinder"
    ctr = (co.min(0) + co.max(0)) / 2
    P = co[tv]
    axis = ctr.copy()
    R = 0.5 * max(co[:, 0].max() - co[:, 0].min(), co[:, 1].max() - co[:, 1].min())
    s0 = 0.0
    if cyl:
        # fit the cylinder axis to vertices on the view-facing side around the label height
        sel = (np.abs(co[:, 2] - ctr[2] - ct) < max(h, 0.05)) & (((co - ctr) @ vdir) > 0.3 * R)
        for _ in range(2):
            c2, R = fit_circle(co[sel][:, :2])
            axis = np.array([c2[0], c2[1], ctr[2]])
            r = np.hypot(co[:, 0] - c2[0], co[:, 1] - c2[1])
            sel = sel & (np.abs(r - R) < 0.01)
        s0 = float((axis - ctr) @ right)

    def st_of(p):
        if not cyl:
            q = p - ctr
            return q @ right, q @ up, q @ vdir
        qq = p[..., :2] - axis[:2]
        th = np.arctan2(qq @ right[:2], qq @ vdir[:2])
        return R * th + s0, p[..., 2] - ctr[2], np.hypot(qq[..., 0], qq[..., 1])

    s_v, t_v, _ = st_of(P)
    cand = ((s_v.max(1) >= cs - w / 2 - M) & (s_v.min(1) <= cs + w / 2 + M) & (t_v.max(1) >= ct - h / 2 - M)
            & (t_v.min(1) <= ct + h / 2 + M))
    fn = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
    area = np.linalg.norm(fn, axis=1) / 2
    fn = fn / np.maximum(np.linalg.norm(fn, axis=1, keepdims=True), 1e-12)
    cand &= (fn @ vdir) > (0.15 if not cyl else -0.2)
    ci = np.where(cand)[0]
    if len(ci) == 0:
        return None
    r = raster(uvt[ci], P[ci], W, H)
    if r is None:
        return None
    tx, ty, pos, tri = r
    s, t, d = st_of(pos)
    inx = (np.abs(s - cs) <= w / 2 + M) & (np.abs(t - ct) <= h / 2 + M)
    tx, ty, pos, s, t, d = tx[inx], ty[inx], pos[inx], s[inx], t[inx], d[inx]
    keep = np.ones(len(pos), bool)
    vd = Vector(vdir)
    if lab.get("occlusion", True):
        for i in range(len(pos)):  # unoccluded toward the camera
            if bvh.ray_cast(Vector(pos[i]) + vd * 0.0006, vd)[0] is not None:
                keep[i] = False
    inside = (np.abs(s - cs) <= w / 2) & (np.abs(t - ct) <= h / 2)
    if not (keep & inside).any():
        return None
    dmed = np.median(d[keep & inside])
    keep &= np.abs(d - dmed) <= tol
    if not (keep & inside).any():
        return None
    return dict(tx=tx, ty=ty, s=s, t=t, d=d, pos=pos, keep=keep, inside=inside, ring=keep & ~inside, ci=ci,
                area=area, R=R, dmed=dmed, axis=axis)


def flatten_relief(ob, co, lab, f):
    """The generators model embossed lettering as real relief: press the vertices under the label onto the surface
    (planar: along the view axis; cylinder: radially) so shading no longer shows the old text. Edits `co` and the mesh."""
    vdir, right, up = (np.array(v, float) for v in VIEWS[lab["view"]])
    cs, ct = lab["center"]
    w, h = lab["size"]
    tol = lab.get("tol", 0.004)
    cyl = lab.get("mode", "plane") == "cylinder"
    ctr = (co.min(0) + co.max(0)) / 2
    nv = len(co)
    nrm = np.empty(nv * 3, np.float32)
    ob.data.vertices.foreach_get("normal", nrm)
    nrm = nrm.reshape(nv, 3)
    feather = 0.003
    if not cyl:
        q = co - ctr
        s, t, d = q @ right, q @ up, q @ vdir
        face = nrm @ vdir > 0.5
        dnew = d
    else:
        c2 = f["axis"][:2]
        qq = co[:, :2] - c2
        r = np.hypot(qq[:, 0], qq[:, 1])
        s = f["R"] * np.arctan2(qq @ right[:2], qq @ vdir[:2]) + float((f["axis"] - ctr) @ right)
        t = co[:, 2] - ctr[2]
        d = r
        face = np.einsum("ij,ij->i", nrm[:, :2], qq / np.maximum(r[:, None], 1e-9)) > 0.7
    ex = np.maximum(np.abs(s - cs) - w / 2, 0)
    ey = np.maximum(np.abs(t - ct) - h / 2, 0)
    wv = np.clip(1 - np.hypot(ex, ey) / feather, 0, 1) * face * (np.abs(d - f["dmed"]) < tol)
    m = wv > 0
    if not m.any():
        return
    shift = (f["dmed"] - d[m]) * wv[m]
    if not cyl:
        co[m] += vdir[None, :] * shift[:, None]
    else:
        u = qq[m] / np.maximum(r[m, None], 1e-9)
        co[np.where(m)[0], 0] += u[:, 0] * shift
        co[np.where(m)[0], 1] += u[:, 1] * shift
    ob.data.vertices.foreach_set("co", co.astype(np.float32).ravel())
    ob.data.update()


def apply_label(ob, base, orm, nrm, lab, bvh, geo, rng, tag):
    co, tv, uvt = geo
    W, H = base.size
    f = find_texels(None, lab, bvh, geo, W, H)
    if f is None:
        print(tag, lab["id"], "NO TEXELS under the label (check view/center/size/tol)", flush=True)
        return 0
    tx, ty, s, t, keep, inside, ring, ci = (f[k] for k in ("tx", "ty", "s", "t", "keep", "inside", "ring", "ci"))
    cs, ct = lab["center"]
    w, h = lab["size"]
    ins = keep & inside
    bpx, opx, npx = get_px(base), get_px(orm), get_px(nrm)
    cur = bpx[ty, tx, :3]
    gfun, gthr = None, 0.04
    if lab.get("ground", "auto") != "auto":
        g = np.array([int(lab["ground"][i:i + 2], 16) / 255 for i in (1, 3, 5)], np.float32)
    else:
        g = np.median(cur[ring if ring.sum() > 20 else ins], axis=0)
        if ring.sum() > 80:
            gfun, gthr = fit_ground(s[ring], t[ring], cur[ring], cs, ct, w, h, lab.get("ring", 0.012), lab.get("ground_bias", "none"))
    feather = lab.get("feather", 0.002)
    ex = np.maximum(np.abs(s - cs) - w / 2, 0)
    ey = np.maximum(np.abs(t - ct) - h / 2, 0)
    wt = np.clip(1 - np.hypot(ex, ey) / feather, 0, 1) * keep
    sel = wt > 0
    gnoise = ((noise2((H, W), 40, rng) - 0.5) * 2 * lab.get("variation", 0.05)
              + (rng.random((H, W)).astype(np.float32) - 0.5) * 2 * lab.get("grain", 0.025))
    gbase = np.clip(gfun(s[sel], t[sel]), 0, 1) if gfun else g[None, :]
    ground = gbase * (1 + gnoise[ty[sel], tx[sel]][:, None])
    new = cur.copy()
    wrep = wt[sel]
    if lab.get("repaint", "selective") == "selective":
        # keep the original paint (its grain, wear and banding) and replace only what deviates from the fitted ground
        # in the direction of the old text: lighter on dark paint, darker on light paint
        dl = cur[sel].mean(1) - gbase.mean(1) if gbase.ndim == 2 and len(gbase) == sel.sum() else cur[sel].mean(1) - gbase.mean()
        bias = lab.get("ground_bias", "none")
        dev = (dl > gthr * 0.6) if bias == "dark" else (-dl > gthr * 0.6) if bias == "light" else (np.abs(dl) > gthr * 0.6)
        m0 = np.zeros((H, W), np.float32)
        m0[ty[sel], tx[sel]] = dev
        for _ in range(3):  # dilate 3 texels, then soften
            m1 = m0.copy()
            m1[1:] = np.maximum(m1[1:], m0[:-1]); m1[:-1] = np.maximum(m1[:-1], m0[1:])
            m1[:, 1:] = np.maximum(m1[:, 1:], m0[:, :-1]); m1[:, :-1] = np.maximum(m1[:, :-1], m0[:, 1:])
            m0 = m1
        m2 = m0.copy()
        m2[1:-1] = (m0[:-2] + m0[1:-1] + m0[2:]) / 3
        m0 = m2
        wrep = wt[sel] * np.clip(m0[ty[sel], tx[sel]] * 1.2, 0, 1)
    new[sel] = cur[sel] * (1 - wrep[:, None]) + ground * wrep[:, None]
    cov = np.zeros(len(tx), np.float32)
    art_path = os.path.join(ART, lab["id"] + ".png")
    if lab.get("lines") and os.path.isfile(art_path):
        im = bpy.data.images.load(art_path, check_existing=False)
        aw, ah = im.size
        art = np.empty(aw * ah * 4, np.float32)
        im.pixels.foreach_get(art)
        art = art.reshape(ah, aw, 4)[::-1].copy()  # top-origin
        bpy.data.images.remove(im)
        a_uv = 0.5 * np.abs(np.cross(uvt[ci][:, 1] - uvt[ci][:, 0], uvt[ci][:, 2] - uvt[ci][:, 0])) * W * H
        tsz = float(np.median(np.sqrt(f["area"][ci] / np.maximum(a_uv, 1e-9))))  # texel size, m
        o = tsz / 3
        sub = [(a * o, b * o) for a in (-1, 0, 1) for b in (-1, 0, 1)]
        v = sample_art(art, s, t, (cs, ct, w, h), aw / w, sub)
        cov = (v[:, 3] * ins).astype(np.float32)
        inkv = 1 + (noise2((H, W), 12, rng)[ty, tx] - 0.5) * 0.12
        new = new * (1 - cov[:, None]) + v[:, :3] * inkv[:, None] * cov[:, None]
    bpx[ty[sel], tx[sel], :3] = np.clip(new[sel], 0, 1)
    set_px(base, bpx)
    ring_orm = np.median(opx[ty[ring], tx[ring], :3] if ring.sum() > 20 else opx[ty[ins], tx[ins], :3], axis=0)
    oo = opx[ty[sel], tx[sel], :3]
    tgt = np.broadcast_to(ring_orm, oo.shape).copy()
    tgt[:, 1] = np.clip(tgt[:, 1] + 0.05, 0, 1)
    tgt = tgt * (1 - cov[sel][:, None]) + np.array([ring_orm[0], 0.8, 0.0], np.float32) * cov[sel][:, None]
    opx[ty[sel], tx[sel], :3] = oo * (1 - wt[sel][:, None]) + tgt * wt[sel][:, None]
    set_px(orm, opx)
    nn = npx[ty[sel], tx[sel], :3]
    npx[ty[sel], tx[sel], :3] = nn * (1 - wt[sel][:, None]) + np.array([0.5, 0.5, 1.0], np.float32) * wt[sel][:, None]
    set_px(nrm, npx)
    if lab.get("flatten", True):
        flatten_relief(ob, geo[0], lab, f)
    print(tag, lab["id"], f"texels {int(sel.sum())}  ink {int((cov > 0.5).sum())}  ground {np.round(g, 3).tolist()}"
          + (f"  R={f['R']:.3f}" if lab.get("mode") == "cylinder" else ""), flush=True)
    return int(sel.sum())


def export(ob, path):
    for o in bpy.context.scene.objects:
        o.select_set(False)
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=True, export_apply=True,
                              export_image_format="AUTO", export_yup=True)


if __name__ == "__main__":
    rng = np.random.default_rng(7)
    for iid in ids:
        mine = [l for l in labels if l["item"] == iid]
        os.makedirs(os.path.join(OUT, iid), exist_ok=True)
        for variant in (iid, iid + "_lod1"):
            src = os.path.join(ITEMS, iid, variant + ".glb")
            if not os.path.exists(src):
                continue
            ob, base, orm, nrm = load_item(src)
            bvh = BVHTree.FromObject(ob, bpy.context.evaluated_depsgraph_get())
            geo = mesh_arrays(ob)
            for lab in mine:
                apply_label(ob, base, orm, nrm, lab, bvh, geo, rng, variant)
            export(ob, os.path.join(OUT, iid, variant + ".glb"))
            if variant == iid and "--blend" in argv:
                bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, iid, iid + ".blend"), compress=True)
        st = os.path.join(ITEMS, iid, "stats.json")
        if os.path.exists(st):
            shutil.copy(st, os.path.join(OUT, iid, "stats.json"))
        print("FIXED", iid, flush=True)
