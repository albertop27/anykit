"""Give baked-opaque glass windows (instrument dials, gauge glasses, lamp lenses) a real glass layer. Blender script.

    blender -b --factory-startup --python kit/tools/fix_glass_screens.py -- --glass scenes/kit/glass.json \
        --items out/items_fixed --out out/items_fixed [--ids field_radio] [--blend]

glass.json: {"windows": [{"id", "item", "view", "shape": "ellipse"|"rect", "center": [u, v], "size": [w, h] m
                          (u right, v up from the item's bbox centre in that view; ortho_views.py + ortho_grid.py show
                          the grid), "recess": [min, max] m (default [0.0012, 0.015]), "lift": m (default 0.003)}]}
How it works (no UV islands needed; the generators bake the dial into the same atlas as everything else):
  * the window's plane depth is measured by raycasting the ring around it (the housing face);
  * every front-facing triangle whose centroid is inside the window shape AND recessed `recess` metres behind that plane
    is the dial face (rims and knobs/hubs stand proud of it, so they are left out);
  * those triangles are duplicated, flattened to a plane `lift` m in front of the housing face, and given a second
    material slot: a thin Principled glass (transmission 1, roughness 0.03, IOR 1.5). The printed dial stays opaque
    underneath; the glass adds the reflections and highlights that were missing. Exported as KHR transmission.
Items with no entry are copied unchanged. Screens (emissive content) are not implemented: no item in the
Polyarnik kit has one. Works on LOD0 and LOD1 (the recess criterion is geometric).
"""
import json
import os
import shutil
import sys

import bmesh
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


GLASS = os.path.abspath(opt("--glass", "scenes/kit/glass.json"))
ITEMS = os.path.abspath(opt("--items", "out/items_fixed"))
OUT = os.path.abspath(opt("--out", ITEMS))
spec = json.load(open(GLASS, encoding="utf-8"))
wins = spec["windows"]
ids = opt("--ids", None, n=True) if "--ids" in argv else sorted({w["item"] for w in wins})
VIEWS = {"front": ((0, -1, 0), (1, 0, 0), (0, 0, 1)), "back": ((0, 1, 0), (-1, 0, 0), (0, 0, 1)),
         "left": ((-1, 0, 0), (0, -1, 0), (0, 0, 1)), "right": ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
         "top": ((0, 0, 1), (1, 0, 0), (0, 1, 0))}


def glass_material():
    m = bpy.data.materials.new("Glass")
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (1, 1, 1, 1)
    b.inputs["Roughness"].default_value = 0.03
    b.inputs["IOR"].default_value = 1.5
    b.inputs["Transmission Weight"].default_value = 1.0
    b.inputs["Metallic"].default_value = 0.0
    return m


def process(src, dst, wlist, blend=None):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=src)
    ob = next(o for o in bpy.context.scene.objects if o.type == "MESH")
    assert np.allclose(np.array(ob.matrix_world), np.eye(4), atol=1e-5), "item object must have identity transform"
    bvh = BVHTree.FromObject(ob, bpy.context.evaluated_depsgraph_get())
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bm.faces.ensure_lookup_table()
    allv = np.array([v.co[:] for v in bm.verts])
    ctr = (allv.min(0) + allv.max(0)) / 2
    gmat = glass_material()
    ob.data.materials.append(gmat)
    gi = len(ob.data.materials) - 1
    total = 0
    for w in wlist:
        vdir, right, up = (np.array(v, float) for v in VIEWS[w["view"]])
        cu, cv = w["center"]
        sw, sh = w["size"]
        lo, hi = w.get("recess", [0.0012, 0.015])
        lift = w.get("lift", 0.003)
        # housing plane: raycast the ring around the window, toward the item
        depths = []
        for k in range(16):
            ang = k / 16 * 2 * np.pi
            ru = cu + np.cos(ang) * sw * 0.65
            rv = cv + np.sin(ang) * sh * 0.65
            o = ctr + right * ru + up * rv + vdir * 0.5
            hit = bvh.ray_cast(Vector(o), Vector(-vdir))
            if hit[0] is not None:
                depths.append(float((np.array(hit[0]) - ctr) @ vdir))
        if not depths:
            print("window", w["id"], "no housing hit"); continue
        plane = float(np.median(depths))  # depth toward the camera of the housing face
        sel = []
        for f in bm.faces:
            if len(f.verts) < 3:
                continue
            c = np.array(f.calc_center_median()[:])
            n = np.array(f.normal[:])
            if n @ vdir < 0.6:
                continue
            q = c - ctr
            s, t, d = q @ right, q @ up, q @ vdir
            if w.get("shape", "ellipse") == "ellipse":
                if ((s - cu) / (sw / 2)) ** 2 + ((t - cv) / (sh / 2)) ** 2 > 1:
                    continue
            elif abs(s - cu) > sw / 2 or abs(t - cv) > sh / 2:
                continue
            rec = plane - d  # how far behind the housing plane
            if lo <= rec <= hi:
                sel.append(f)
        if not sel:
            print("window", w["id"], "no recessed faces found (plane", round(plane, 4), ")"); continue
        ret = bmesh.ops.duplicate(bm, geom=sel)
        newv = [g for g in ret["geom"] if isinstance(g, bmesh.types.BMVert)]
        newf = [g for g in ret["geom"] if isinstance(g, bmesh.types.BMFace)]
        target = plane + lift
        for v in newv:  # flatten onto the glass plane (move along the view axis)
            dd = (np.array(v.co[:]) - ctr) @ vdir
            v.co = Vector(np.array(v.co[:]) + vdir * (target - dd))
        for f in newf:
            f.material_index = gi
        total += len(newf)
        print(f"  window {w['id']}: {len(sel)} faces -> glass at {target:.4f} (housing {plane:.4f})", flush=True)
    bm.to_mesh(ob.data)
    bm.free()
    ob.data.update()
    for o in bpy.context.scene.objects:
        o.select_set(False)
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=dst, export_format="GLB", use_selection=True, export_apply=True,
                              export_image_format="AUTO", export_yup=True)
    if blend:
        bpy.ops.wm.save_as_mainfile(filepath=blend, compress=True)
    return total


for iid in ids:
    mine = [w for w in wins if w["item"] == iid]
    for variant in (iid, iid + "_lod1"):
        src = os.path.join(ITEMS, iid, variant + ".glb")
        if not os.path.exists(src):
            continue
        dst = os.path.join(OUT, iid, variant + ".glb")
        n = process(src, dst, mine, os.path.join(OUT, iid, iid + ".blend") if ("--blend" in argv and variant == iid) else None)
        print("GLASS", variant, n, "glass faces", flush=True)
    if OUT != ITEMS and os.path.exists(os.path.join(ITEMS, iid, "stats.json")):
        shutil.copy(os.path.join(ITEMS, iid, "stats.json"), os.path.join(OUT, iid, "stats.json"))
