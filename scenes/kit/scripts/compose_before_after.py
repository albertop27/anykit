"""python compose_before_after.py <closeups dir> <out dir> : labels_before_after_<id>.png (rows = shots, before | after)."""
import glob, os, sys
from PIL import Image, ImageDraw, ImageFont
src, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
f = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 22)
ids = sorted({os.path.basename(p).rsplit("_", 2)[0].rsplit("_", 1)[0] if False else None for p in []})
items = {}
for p in glob.glob(os.path.join(src, "*_before.png")):
    base = os.path.basename(p)[:-len("_before.png")]
    for iid in ("field_radio", "heater", "toolbox"):
        if base.startswith(iid + "_"):
            items.setdefault(iid, []).append(base[len(iid) + 1:])
for iid, shots in items.items():
    shots.sort()
    sc = 0.75
    rows = []
    for s in shots:
        a = Image.open(os.path.join(src, f"{iid}_{s}_before.png")).convert("RGB")
        b = Image.open(os.path.join(src, f"{iid}_{s}_after.png")).convert("RGB")
        a, b = [i.resize((int(i.width * sc), int(i.height * sc))) for i in (a, b)]
        row = Image.new("RGB", (a.width * 2 + 6, a.height), (20, 20, 20))
        row.paste(a, (0, 0)); row.paste(b, (a.width + 6, 0))
        d = ImageDraw.Draw(row)
        d.text((8, 6), f"{s}: before", fill=(255, 255, 0), font=f)
        d.text((a.width + 14, 6), "after", fill=(120, 255, 120), font=f)
        rows.append(row)
    sheet = Image.new("RGB", (rows[0].width, sum(r.height + 6 for r in rows)), (20, 20, 20))
    y = 0
    for r in rows:
        sheet.paste(r, (0, y)); y += r.height + 6
    sheet.save(os.path.join(out, f"labels_before_after_{iid}.png"))
    print("wrote", iid)
