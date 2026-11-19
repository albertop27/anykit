"""Render crisp label art (real Cyrillic text) for kit/tools/fix_labels.py. Plain Python + Pillow + numpy (not Blender).

    python kit/tools/label_art.py --labels scenes/kit/labels.json --out scenes/kit/labels_art [--ppm 9000]

For every label with "lines" it writes <out>/<label id>.png: an RGBA image of the label rectangle at --ppm pixels per
metre (default 9000), RGB = the ink colour, A = ink coverage. Styles:
  stencil  stencilled paint: bold condensed caps with stencil bridges, chipped by noise (wear 0..1)
  print    printed/enamelled ink: crisp, light speckle wear
Labels without "lines" are wipe-only (no art; fix_labels.py just repaints the ground).
Label fields: id, item, view, mode (plane|cylinder), center [u, v] m, size [w, h] m, style, color "#rrggbb",
wear, align (center|left), line_gap m, lines [{"text", "cap" (cap height, m), "track" (letter spacing, em)}].
Lines are stacked and centred in the rectangle; if they are too wide/high they are scaled down together.
Fonts: Bahnschrift Bold Condensed (real Cyrillic), fallback Arial Bold. Only invented words: no real brands.
"""
import argparse
import json
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT_BAHN = "C:/Windows/Fonts/bahnschrift.ttf"
FONT_ARIAL = "C:/Windows/Fonts/arialbd.ttf"
ROUND = set("ОСЭЮРВБДФЯЕЗ0689")  # glyphs that get stencil bridges


def get_font(px, style):
    try:
        f = ImageFont.truetype(FONT_BAHN, px)
        f.set_variation_by_name("Bold Condensed" if style == "stencil" else "SemiBold Condensed")
        return f
    except Exception:
        return ImageFont.truetype(FONT_ARIAL, px)


def draw_line(text, cap_px, style, track):
    """Return an 'L' mask image of one line with the given cap height in px."""
    f = get_font(100, style)
    capb = f.getbbox("Н")
    f = get_font(max(6, int(round(100 * cap_px / (capb[3] - capb[1])))), style)
    capb = f.getbbox("Н")
    cap_h = capb[3] - capb[1]
    adv = [f.getlength(c) for c in text]
    gap = track * f.size
    w = int(sum(adv) + gap * (len(text) - 1)) + 8
    img = Image.new("L", (w, cap_h + 8), 0)
    d = ImageDraw.Draw(img)
    x = 4.0
    bridge = max(1, int(round(cap_h * 0.085)))
    for c, a in zip(text, adv):
        d.text((x, 4 - capb[1]), c, font=f, fill=255)
        if style == "stencil" and c in ROUND:
            # stencil bridges: small gaps on the left and right of the glyph at about mid-height
            bb = f.getbbox(c)
            y0 = 4 + int(cap_h * 0.5) - bridge // 2
            d.rectangle([x + bb[0] - 1, y0, x + bb[0] + bridge * 1.1, y0 + bridge], fill=0)
            d.rectangle([x + bb[2] - bridge * 1.1 - 1, y0, x + bb[2] + 1, y0 + bridge], fill=0)
        x += a + gap
    return img, cap_h


def noise(shape, scale, rng):
    """Smooth value noise in 0..1 with feature size ~scale px."""
    h, w = shape
    sm = max(2, int(scale))
    small = rng.random((h // sm + 3, w // sm + 3)).astype(np.float32)
    im = Image.fromarray((small * 255).astype(np.uint8)).resize((w + 2 * sm, h + 2 * sm), Image.BICUBIC)
    return np.asarray(im, np.float32)[:h, :w] / 255.0


def render(lab, ppm, rng):
    W, H = int(round(lab["size"][0] * ppm)), int(round(lab["size"][1] * ppm))
    style = lab.get("style", "stencil")
    lines = lab["lines"]
    gap_px = lab.get("line_gap", 0.006) * ppm
    imgs = [draw_line(l["text"], l["cap"] * ppm, style, l.get("track", 0.04)) for l in lines]
    tot_h = sum(i[0].height - 8 for i in imgs) + gap_px * (len(imgs) - 1)
    tot_w = max(i[0].width - 8 for i in imgs)
    k = min(1.0, (W * 0.96) / tot_w, (H * 0.96) / tot_h)
    if k < 1.0:  # too big: redo smaller
        imgs = [draw_line(l["text"], l["cap"] * ppm * k, style, l.get("track", 0.04)) for l in lines]
        gap_px *= k
        tot_h = sum(i[0].height - 8 for i in imgs) + gap_px * (len(imgs) - 1)
    mask = Image.new("L", (W, H), 0)
    y = (H - tot_h) / 2
    for im, ch in imgs:
        iw = im.width - 8
        x = (W - iw) / 2 if lab.get("align", "center") == "center" else 0.02 * W
        mask.paste(im.crop((4, 4, im.width - 4, im.height - 4)), (int(x), int(y)))
        y += im.height - 8 + gap_px
    a = np.asarray(mask, np.float32) / 255.0
    # edge roughness (paint bleeds slightly) then wear
    px_mm = ppm / 1000.0
    rough = noise(a.shape, max(2, px_mm * 0.6), rng)
    a = np.clip((np.asarray(Image.fromarray((a * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(px_mm * 0.25)), np.float32) / 255.0
                 - 0.5) * 6 * (0.85 + 0.3 * rough) + 0.5, 0, 1)
    wear = lab.get("wear", 0.4 if style == "stencil" else 0.2)
    if wear > 0:
        big = noise(a.shape, px_mm * 6, rng)
        fine = noise(a.shape, px_mm * 0.8, rng)
        thr = (0.72 - 0.5 * wear) if style == "stencil" else wear * 1.2
        chip = np.clip((big * 0.6 + fine * 0.4 - thr) * 7, 0, 1)  # 1 where ink survives
        a = a * (1.0 - np.clip(1.0 - chip, 0, 1) * (0.9 if style == "stencil" else 0.7))
    rgb = tuple(int(lab.get("color", "#d8d2ae")[i:i + 2], 16) for i in (1, 3, 5))
    out = np.zeros((H, W, 4), np.uint8)
    out[..., 0], out[..., 1], out[..., 2] = rgb
    out[..., 3] = (np.clip(a, 0, 1) * 255).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--ppm", type=float, default=9000)
    ap.add_argument("--only", nargs="*")
    args = ap.parse_args()
    spec = json.load(open(args.labels, encoding="utf-8"))
    os.makedirs(args.out, exist_ok=True)
    for lab in spec["labels"]:
        if not lab.get("lines") or (args.only and lab["item"] not in args.only):
            continue
        rng = np.random.default_rng(abs(hash(lab["id"])) % (2 ** 32) if False else sum(map(ord, lab["id"])))
        render(lab, args.ppm, rng).save(os.path.join(args.out, lab["id"] + ".png"))
        print("art", lab["id"])
