"""Author scenes/kit/labels.json (metres in each view's plane, from the bbox centre) for the Polyarnik kit.
Run with plain Python:  python scenes/kit/scripts/make_labels.py
Rectangles were read off scenes/kit/ortho/<id>_<view>_grid.png (kit/tools/ortho_views.py + ortho_grid.py); the radio's
were read off a 1800 px front render, hence the px helper below."""
import json
import os

here = os.path.dirname(os.path.abspath(__file__))
orth = os.path.join(here, "..", "ortho")
radio = json.load(open(os.path.join(orth, "field_radio_views.json")))
RS = radio["scale"]


def px(x0, y0, x1, y1, size=1800, ox=420, oy=520):
    """Rect in a size x size front ortho render (optionally a crop offset by ox, oy) -> (center, size) in metres."""
    ppm = size / RS
    x0, x1, y0, y1 = x0 + ox, x1 + ox, y0 + oy, y1 + oy
    return [round(((x0 + x1) / 2 - size / 2) / ppm, 4), round((size / 2 - (y0 + y1) / 2) / ppm, 4)], \
        [round((x1 - x0) / ppm, 4), round((y1 - y0) / ppm, 4)]


L = []
CREAM_INK = "#dcd5b0"
# ---- toolbox: stencil on olive paint
L.append(dict(id="toolbox_front", item="toolbox", view="front", center=[-0.005, -0.056], size=[0.245, 0.085],
              style="stencil", color=CREAM_INK, wear=0.45, tol=0.004, line_gap=0.0075,
              lines=[dict(text="ПОЛЯРНИК-3", cap=0.026, track=0.06), dict(text="ИНСТРУМЕНТ", cap=0.019, track=0.08),
                     dict(text="ЗАВОД СЕВЕР  №0417", cap=0.008, track=0.1)]))
L.append(dict(id="toolbox_lid_wipeA", item="toolbox", view="top", center=[0.017, 0.051], size=[0.09, 0.055], tol=0.004, occlusion=False))
L.append(dict(id="toolbox_lid_wipeB", item="toolbox", view="top", center=[0.018, -0.027], size=[0.1, 0.05], tol=0.0025, occlusion=False))
L.append(dict(id="toolbox_lid_front", item="toolbox", view="top", center=[0.0, -0.066], size=[0.30, 0.04], tol=0.004,
              style="stencil", color=CREAM_INK, wear=0.5,
              lines=[dict(text="ЗАВОД СЕВЕР", cap=0.017, track=0.12)]))
L.append(dict(id="toolbox_lid_back", item="toolbox", view="top", center=[0.0, 0.07], size=[0.22, 0.03], tol=0.004,
              style="stencil", color=CREAM_INK, wear=0.5,
              lines=[dict(text="МАКС. 15 КГ", cap=0.012, track=0.1)]))
# ---- heater: stencil on the cylinder
L.append(dict(id="heater_front", item="heater", view="front", mode="cylinder", center=[0.003, 0.018], size=[0.1, 0.05],
              tol=0.004, ring=0.008, style="stencil", color=CREAM_INK, wear=0.45, line_gap=0.006,
              lines=[dict(text="ПОЛЯРНИК-3", cap=0.0132, track=0.06), dict(text="ОБОГРЕВАТЕЛЬ", cap=0.0096, track=0.05),
                     dict(text="ЗАВОД СЕВЕР", cap=0.0058, track=0.1)]))
# ---- radio: printed panel legends (black ink on cream enamel). Crop coords of the 1800 px front render.
INK = "#17150f"
c, s = px(700, 432, 922, 500)
L.append(dict(id="radio_plate", item="field_radio", view="front", center=c, size=s, tol=0.0025, style="print",
              color=INK, wear=0.05, line_gap=0.0025, ground="auto",
              lines=[dict(text="РП-3", cap=0.0068, track=0.1), dict(text="ПОЛЯРНИК", cap=0.0048, track=0.1)]))
for lid, rect, txt in [("radio_leg_tone", (128, 478, 250, 548), "ТОН"), ("radio_leg_noise", (775, 505, 965, 565), "ШУМ"),
                       ("radio_leg_vol", (120, 790, 305, 858), "ГРОМК."), ("radio_leg_tune", (425, 790, 635, 858), "НАСТР."),
                       ("radio_leg_band", (705, 790, 935, 858), "ДИАП.")]:
    c, s = px(*rect)
    L.append(dict(id=lid, item="field_radio", view="front", center=c, size=s, tol=0.0025, style="print", color=INK,
                  wear=0.05, lines=[dict(text=txt, cap=0.0058, track=0.12)]))
for lid, rect in [("radio_wipe_mid", (308, 895, 440, 985)), ("radio_wipe_mid2", (626, 895, 760, 985))]:
    c, s = px(*rect)
    L.append(dict(id=lid, item="field_radio", view="front", center=c, size=s, tol=0.0025))
for l in L:  # ground fit: light enamel on the radio (chips are darker), dark paint on the rest (chips/old stencil lighter)
    l["ground_bias"] = "light" if l["item"] == "field_radio" else "dark"
json.dump({"kit": "Polyarnik", "labels": L}, open(os.path.join(here, "..", "labels.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print(len(L), "labels")
