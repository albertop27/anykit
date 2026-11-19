"""Orthographic Workbench views of kit items, for picking label rectangles (CPU only, no GPU).

    blender -b --factory-startup --python kit/tools/ortho_views.py -- --items out/items --out scenes/kit/ortho \
        [--ids field_radio toolbox] [--views front back left right top] [--size 900] [--glb-name <id>.glb]

Writes <out>/<id>_<view>.png and <out>/<id>_views.json (the pixel -> metre mapping per view: item-space metres,
right/up axes). Overlay a metre grid with kit/tools/ortho_grid.py (plain Python + Pillow) and read rectangles off it.
View conventions (item frame: front faces -Y, Z up): front = camera at -Y (right = +X); back = at +Y (right = -X);
left = at -X (right = -Y); right = at +X (right = +Y); top = above (right = +X, up = +Y).
"""
import json
import math
import os
import sys

import bpy
from mathutils import Vector

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


ITEMS = os.path.abspath(opt("--items", "out/items"))
OUT = os.path.abspath(opt("--out", "scenes/kit/ortho"))
VIEWS = opt("--views", ["front", "back", "left", "right", "top"], n=True) if "--views" in argv else \
    ["front", "back", "left", "right", "top"]
SIZE = int(opt("--size", 900))
NAME = opt("--glb-name", "{id}.glb")
ids = opt("--ids", None, n=True) if "--ids" in argv else sorted(d for d in os.listdir(ITEMS) if os.path.isdir(os.path.join(ITEMS, d)))

# camera direction (from item toward camera), up vector, right vector, in item space
DIRS = {"front": ((0, -1, 0), (0, 0, 1)), "back": ((0, 1, 0), (0, 0, 1)), "left": ((-1, 0, 0), (0, 0, 1)),
        "right": ((1, 0, 0), (0, 0, 1)), "top": ((0, 0, 1), (0, 1, 0))}

os.makedirs(OUT, exist_ok=True)
for iid in ids:
    glb = os.path.join(ITEMS, iid, NAME.format(id=iid))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb)
    sc = bpy.context.scene
    obs = [o for o in sc.objects if o.type == "MESH"]
    pts = [o.matrix_world @ Vector(c) for o in obs for c in o.bound_box]
    lo = Vector([min(p[i] for p in pts) for i in range(3)])
    hi = Vector([max(p[i] for p in pts) for i in range(3)])
    ctr = (lo + hi) / 2
    scale = max(hi - lo) * 1.12
    sc.render.engine = "BLENDER_WORKBENCH"
    sc.display.shading.light = "FLAT"
    sc.display.shading.color_type = "TEXTURE"
    sc.display.shading.show_object_outline = False
    sc.render.resolution_x = sc.render.resolution_y = SIZE
    sc.render.film_transparent = False
    sc.view_settings.view_transform = "Standard"
    sc.world = bpy.data.worlds.new("w")
    sc.world.color = (0.5, 0.5, 0.5)
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    sc.collection.objects.link(cam)
    sc.camera = cam
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = scale
    cam.data.clip_end = 100
    info = {"center": list(ctr), "scale": scale, "size": SIZE, "bbox_lo": list(lo), "bbox_hi": list(hi), "views": {}}
    for v in VIEWS:
        d, up = DIRS[v]
        d, up = Vector(d), Vector(up)
        cam.location = ctr + d * 5
        cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler() if v != "top" else (0, 0, 0)
        if v != "top":
            # track -Z at the item with Z up
            q = (-d).to_track_quat("-Z", "Y")
            cam.rotation_euler = q.to_euler()
        bpy.context.view_layer.update()
        right = Vector(cam.matrix_world.to_3x3() @ Vector((1, 0, 0)))
        info["views"][v] = {"right": [round(c) for c in right], "up": [round(c) for c in (cam.matrix_world.to_3x3() @ Vector((0, 1, 0)))]}
        sc.render.filepath = os.path.join(OUT, f"{iid}_{v}.png")
        bpy.ops.render.render(write_still=True)
    json.dump(info, open(os.path.join(OUT, f"{iid}_views.json"), "w"), indent=1)
    print("ORTHO", iid, info["views"], flush=True)
