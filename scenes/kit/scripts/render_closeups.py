"""CPU close-up renders of the label areas (no GPU): Cycles CPU, small, few samples.
blender -b --factory-startup --python scenes/kit/scripts/render_closeups.py -- --items <dir with <id>/<id>.glb> --out <dir> --tag before|after
Writes <out>/<id>_<name>_<tag>.png."""
import math, os, sys
import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
ITEMS, OUT, TAG = [os.path.abspath(argv[argv.index(k) + 1]) if k != "--tag" else argv[argv.index(k) + 1] for k in ("--items", "--out", "--tag")]
SAMPLES = int(argv[argv.index("--spp") + 1]) if "--spp" in argv else 24
# id -> [(name, at (offset from bbox centre, item frame), az deg (+ = camera to the item's right), el deg, dist m)]
CLOSE = {
    "field_radio": [("panel", (0.0, -0.07, -0.01), 22, 14, 0.40), ("plate", (0.065, -0.072, -0.012), 18, 10, 0.20),
                    ("dials", (0.0, -0.07, 0.04), 14, 8, 0.28)],
    "heater": [("front", (0.0, -0.125, 0.02), 24, 12, 0.34)],
    "toolbox": [("front", (0.0, -0.11, -0.056), 26, 16, 0.46), ("lid", (0.0, -0.03, 0.12), 12, 58, 0.5)],
}
os.makedirs(OUT, exist_ok=True)
for iid, shots in CLOSE.items():
    glb = os.path.join(ITEMS, iid, iid + ".glb")
    if not os.path.exists(glb):
        continue
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb)
    sc = bpy.context.scene
    obs = [o for o in sc.objects if o.type == "MESH"]
    pts = [o.matrix_world @ Vector(c) for o in obs for c in o.bound_box]
    ctr = Vector([(min(p[i] for p in pts) + max(p[i] for p in pts)) / 2 for i in range(3)])
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = SAMPLES
    sc.cycles.use_denoising = True
    sc.render.resolution_x, sc.render.resolution_y = 800, 600
    sc.view_settings.view_transform = "Filmic" if "Filmic" in bpy.types.ColorManagedViewSettings.bl_rna.properties["view_transform"].enum_items else "AgX"
    w = bpy.data.worlds.new("w"); sc.world = w; w.use_nodes = True
    w.node_tree.nodes["Background"].inputs[0].default_value = (0.75, 0.78, 0.82, 1)
    w.node_tree.nodes["Background"].inputs[1].default_value = 0.8
    sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN")); sc.collection.objects.link(sun)
    sun.data.energy = 3.0; sun.rotation_euler = (math.radians(55), 0, math.radians(-35))
    fill = bpy.data.objects.new("fill", bpy.data.lights.new("fill", "AREA")); sc.collection.objects.link(fill)
    fill.data.energy = 40; fill.data.size = 1.0; fill.location = ctr + Vector((-0.6, -0.8, 0.5))
    fill.rotation_euler = (math.radians(70), 0, math.radians(-35))
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); sc.collection.objects.link(cam); sc.camera = cam
    cam.data.lens = 60
    for name, at, az, el, dist in shots:
        tgt = ctr + Vector(at)
        a, e = math.radians(az), math.radians(el)
        d = Vector((math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e)))
        cam.location = tgt + d * dist
        cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
        sc.render.filepath = os.path.join(OUT, f"{iid}_{name}_{TAG}.png")
        bpy.ops.render.render(write_still=True)
        print("RENDERED", sc.render.filepath, flush=True)
