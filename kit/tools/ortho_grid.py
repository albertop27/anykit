"""Overlay a metre grid on the ortho views from ortho_views.py so label rectangles can be read off in item metres.

    python kit/tools/ortho_grid.py scenes/kit/ortho [--step 0.02]

For each <id>_<view>.png writes <id>_<view>_grid.png: lines every `step` m (labelled every 5th) in the view's own
right/up axes, relative to the item bbox centre (label coordinates in labels.json are the same: u to the right,
v up, in metres from the bbox centre of that view's plane).
"""
import glob
import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont

d = sys.argv[1]
step = float(sys.argv[sys.argv.index("--step") + 1]) if "--step" in sys.argv else 0.02
font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 13)
for jf in glob.glob(os.path.join(d, "*_views.json")):
    iid = os.path.basename(jf)[:-len("_views.json")]
    info = json.load(open(jf))
    for v in info["views"]:
        p = os.path.join(d, f"{iid}_{v}.png")
        if not os.path.exists(p):
            continue
        im = Image.open(p).convert("RGB")
        dr = ImageDraw.Draw(im, "RGBA")
        S, sc = info["size"], info["scale"]
        ppm = S / sc
        n = int(sc / 2 / step) + 1
        for k in range(-n, n + 1):
            x = S / 2 + k * step * ppm
            major = k % 5 == 0
            col = (255, 0, 255, 150 if major else 60)
            dr.line([(x, 0), (x, S)], fill=col, width=1)
            dr.line([(0, S - x), (S, S - x)], fill=col, width=1)
            if major:
                dr.text((x + 2, 2), f"{k * step:+.2f}", fill=(255, 255, 0, 255), font=font)
                dr.text((2, S - x + 1), f"{k * step:+.2f}", fill=(0, 255, 255, 255), font=font)
        im.save(os.path.join(d, f"{iid}_{v}_grid.png"))
