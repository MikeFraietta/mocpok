#!/usr/bin/env python3
"""Build a 4-color 3D-printable Williamsburg property board for a Bambu Lab X1 Carbon + AMS.

Output: a Bambu Studio 3MF (one object, four parts, colors pre-assigned) and one STL per color.
  AMS 1 white = base plate   AMS 2 blue = lines and text
  AMS 3 teal  = color bands  AMS 4 gold = color bands, "?" marks, card boxes
Needs: fonttools, mapbox_earcut, numpy (pip install fonttools mapbox_earcut numpy).
Usage: python make_williamsburg_board.py OUTPUT_DIR [TEMPLATE_PROJECT_3MF]
"""
from __future__ import annotations

import json
import re
import struct
import sys
import uuid
import zipfile
from pathlib import Path

import mapbox_earcut
import numpy as np
from fontTools.pens.basePen import BasePen
from fontTools.ttLib import TTFont

SIZE = 180.0          # board width/depth, mm
CORNER = 30.0         # corner square, mm
SIDE = (SIZE - 2 * CORNER) / 5
BASE_Z = 1.2          # white plate thickness
TOP_Z = 1.6           # raised details are 0.4 mm (two 0.2 mm layers)
LINE = 0.9            # divider line width
BAND = 6.0            # color band depth
FONT_PATH = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"

LANDMARKS = [  # cheapest first; pairs share a band
    "Havemeyer|Street", "Grand|Street", "Kellogg's|Diner", "Nitehawk|Cinema",
    "McCarren|Pool", "McCarren|Park", "Brooklyn|Bowl", "Music Hall of|Williamsburg",
    "Smorgas-|burg", "Brooklyn|Brewery", "Grand Ferry|Park", "Marsha P.|Johnson Park",
    "Bedford|Avenue", "Peter|Luger", "Domino|Park", "Williamsburg|Bridge",
]
TRANSIT = ["L Train|Bedford Av", "NYC Ferry|Landing"]
CORNERS = [("START", "+$2"), ("REST|STOP", ""), ("LUCKY|RIDE", ""), ("TRAFFIC|JAM", "")]

# ---------------- geometry helpers ----------------
parts: dict[str, list] = {"white": [], "blue": [], "teal": [], "gold": []}


def area(ring):
    a = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        a += x1 * y2 - x2 * y1
    return a / 2


def add_polygon(color, outer, holes=(), z0=BASE_Z, z1=TOP_Z):
    """Extrude one polygon with holes (3D coordinates, y up) into a closed prism."""
    outer = list(outer)
    if area(outer) < 0:
        outer.reverse()
    holes = [list(h) if area(h) < 0 else list(reversed(h)) for h in holes]
    rings = [outer] + holes
    verts = np.array([p for r in rings for p in r], dtype=np.float64)
    ends = np.cumsum([len(r) for r in rings]).astype(np.uint32)
    tris = mapbox_earcut.triangulate_float64(verts, ends).reshape(-1, 3)
    out = parts[color]
    for a, b, c in tris:
        pa, pb, pc = verts[a], verts[b], verts[c]
        if (pb[0] - pa[0]) * (pc[1] - pa[1]) - (pb[1] - pa[1]) * (pc[0] - pa[0]) < 0:
            pb, pc = pc, pb
        out.append(((pa[0], pa[1], z1), (pb[0], pb[1], z1), (pc[0], pc[1], z1)))   # top, normal +z
        out.append(((pa[0], pa[1], z0), (pc[0], pc[1], z0), (pb[0], pb[1], z0)))   # bottom, normal -z
    for ring in rings:  # outer CCW, holes CW -> walls face outward
        for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
            out.append(((x1, y1, z0), (x2, y2, z0), (x2, y2, z1)))
            out.append(((x1, y1, z0), (x2, y2, z1), (x1, y1, z1)))


def S(x, y):
    """Screen coordinates (origin top-left, y down, mm) -> board coordinates (centered, y up)."""
    return (x - SIZE / 2, SIZE / 2 - y)


def rect(color, x, y, w, h):
    add_polygon(color, [S(x, y + h), S(x + w, y + h), S(x + w, y), S(x, y)])


def frame(color, x, y, w, h, t):
    outer = [S(x, y + h), S(x + w, y + h), S(x + w, y), S(x, y)]
    inner = [S(x + t, y + h - t), S(x + w - t, y + h - t), S(x + w - t, y + t), S(x + t, y + t)]
    add_polygon(color, outer, [inner])


# ---------------- text ----------------
font = TTFont(FONT_PATH)
glyphs = font.getGlyphSet()
cmap = font.getBestCmap()
UPM = font["head"].unitsPerEm
CAP = getattr(font["OS/2"], "sCapHeight", 0) or int(UPM * 0.716)


class FlatPen(BasePen):
    def __init__(self, glyphset):
        super().__init__(glyphset)
        self.contours, self.cur = [], []

    def _moveTo(self, p):
        self.cur = [p]

    def _lineTo(self, p):
        self.cur.append(p)

    def _qCurveToOne(self, p1, p2):
        p0 = self.cur[-1]
        for i in range(1, 5):
            t = i / 4
            self.cur.append(((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
                             (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1]))

    def _curveToOne(self, p1, p2, p3):
        p0 = self.cur[-1]
        for i in range(1, 7):
            t = i / 6
            mt = 1 - t
            self.cur.append((mt ** 3 * p0[0] + 3 * mt * mt * t * p1[0] + 3 * mt * t * t * p2[0] + t ** 3 * p3[0],
                             mt ** 3 * p0[1] + 3 * mt * mt * t * p1[1] + 3 * mt * t * t * p2[1] + t ** 3 * p3[1]))

    def _closePath(self):
        ring = []
        for p in self.cur:
            if not ring or (abs(p[0] - ring[-1][0]) > 1e-6 or abs(p[1] - ring[-1][1]) > 1e-6):
                ring.append(p)
        if len(ring) > 1 and abs(ring[0][0] - ring[-1][0]) < 1e-6 and abs(ring[0][1] - ring[-1][1]) < 1e-6:
            ring.pop()
        if len(ring) >= 3:
            self.contours.append(ring)
        self.cur = []

    _endPath = _closePath


def inside(pt, ring):
    x, y = pt
    hit = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            hit = not hit
    return hit


def line_width(text):
    return sum(font["hmtx"][cmap.get(ord(ch), ".notdef")][0] for ch in text)


def text(color, s, cx, cy, cap, max_w):
    """Centered multi-line text ('|' splits lines). cap = capital height in mm; shrinks to fit max_w."""
    lines = s.split("|")
    widest = max(line_width(l) for l in lines)
    cap = min(cap, max_w * CAP / widest) if widest else cap
    scale = cap / CAP
    gap = cap * 1.45
    top_baseline = cy - (len(lines) - 1) * gap / 2 + cap / 2
    for i, l in enumerate(lines):
        x = cx - line_width(l) * scale / 2
        base = top_baseline + i * gap
        for ch in l:
            name = cmap.get(ord(ch), ".notdef")
            pen = FlatPen(glyphs)
            glyphs[name].draw(pen)
            rings = [[S(x + px * scale, base - py * scale) for px, py in r] for r in pen.contours]
            # A ring nested inside an odd number of other rings is a hole (e.g. the middle of "o").
            depth = [sum(1 for k, other in enumerate(rings) if k != i2 and inside(r[0], other)) for i2, r in enumerate(rings)]
            outers = [i2 for i2, d in enumerate(depth) if d % 2 == 0]
            for oi in outers:
                mine = [rings[hi2] for hi2, d in enumerate(depth) if d % 2 == 1 and inside(rings[hi2][0], rings[oi])
                        and all(not (inside(rings[hi2][0], rings[o2]) and abs(area(rings[o2])) < abs(area(rings[oi])))
                                for o2 in outers if o2 != oi)]
                add_polygon(color, rings[oi], mine)
            x += font["hmtx"][name][0] * scale


# ---------------- board layout ----------------
add_polygon("white", [S(0, SIZE), S(SIZE, SIZE), S(SIZE, 0), S(0, 0)], z0=0.0, z1=BASE_Z)
frame("blue", 0, 0, SIZE, SIZE, 1.4)
frame("blue", CORNER - LINE / 2, CORNER - LINE / 2, SIZE - 2 * CORNER + LINE, SIZE - 2 * CORNER + LINE, LINE)
lo, hi = CORNER, SIZE - CORNER
for j in range(6):  # dividers between spaces, incl. the corner edges
    v = lo + j * SIDE
    # Overlap the border frames by 0.25 mm so no edges are shared (shared edges = non-manifold).
    rect("blue", v - LINE / 2, 1.15, LINE, CORNER - 1.15 - LINE / 2 + 0.25)                 # top row
    rect("blue", v - LINE / 2, hi + LINE / 2 - 0.25, LINE, CORNER - 1.15 - LINE / 2 + 0.25)  # bottom row
    rect("blue", 1.15, v - LINE / 2, CORNER - 1.15 - LINE / 2 + 0.25, LINE)                 # left column
    rect("blue", hi + LINE / 2 - 0.25, v - LINE / 2, CORNER - 1.15 - LINE / 2 + 0.25, LINE)  # right column

# Spaces clockwise from START (bottom-right corner).
pattern = [("L", "L", "S", "L", "L"), ("L", "L", "T", "L", "L"), ("L", "L", "S", "L", "L"), ("L", "L", "T", "L", "L")]
li = ti = 0
pad = LINE / 2 + 0.5
for s in range(4):
    for j in range(5):
        if s == 0:   # bottom row, right to left; band on top (toward center)
            x, y, w, h = hi - (j + 1) * SIDE, hi, SIDE, CORNER
        elif s == 1:  # left column, bottom to top; band on right
            x, y, w, h = 0, hi - (j + 1) * SIDE, CORNER, SIDE
        elif s == 2:  # top row, left to right; band on bottom
            x, y, w, h = lo + j * SIDE, 0, SIDE, CORNER
        else:        # right column, top to bottom; band on left
            x, y, w, h = hi, lo + j * SIDE, CORNER, SIDE
        kind = pattern[s][j]
        cx, cy = x + w / 2, y + h / 2
        if kind == "L":
            band_color = "teal" if (li // 2) % 2 == 0 else "gold"
            price = f"${li // 2 + 1}"
            if s == 0:
                rect(band_color, x + pad, y + pad, w - 2 * pad, BAND)
                text("blue", LANDMARKS[li], cx, y + BAND + 9, 2.4, w - 3)
                text("blue", price, cx, y + h - 4.5, 2.6, w - 4)
            elif s == 2:
                rect(band_color, x + pad, y + h - pad - BAND, w - 2 * pad, BAND)
                text("blue", LANDMARKS[li], cx, y + 9, 2.4, w - 3)
                text("blue", price, cx, y + h - BAND - 4.5, 2.6, w - 4)
            elif s == 1:
                rect(band_color, x + w - pad - BAND, y + pad, BAND, h - 2 * pad)
                text("blue", LANDMARKS[li], x + (w - BAND) / 2 + 0.5, cy - 3, 2.4, w - BAND - 4)
                text("blue", price, x + (w - BAND) / 2 + 0.5, y + h - 4.2, 2.6, w - BAND - 4)
            else:
                rect(band_color, x + pad, y + pad, BAND, h - 2 * pad)
                text("blue", LANDMARKS[li], x + BAND + (w - BAND) / 2 - 0.5, cy - 3, 2.4, w - BAND - 4)
                text("blue", price, x + BAND + (w - BAND) / 2 - 0.5, y + h - 4.2, 2.6, w - BAND - 4)
            li += 1
        elif kind == "T":
            text("blue", TRANSIT[ti], cx, cy, 2.4, w - 4)
            ti += 1
        else:
            text("gold", "?", cx, cy - 3, 7, w - 4)
            text("blue", "Surprise", cx, cy + 7, 2.2, w - 4)

corner_xy = [(hi, hi), (0, hi), (0, 0), (hi, 0)]
for (name, note), (x, y) in zip(CORNERS, corner_xy):
    if name == "START":
        text("teal", name, x + CORNER / 2, y + CORNER / 2 - 3, 4.2, CORNER - 5)
        text("blue", note, x + CORNER / 2, y + CORNER / 2 + 6, 3.0, CORNER - 6)
    else:
        text("blue", name, x + CORNER / 2, y + CORNER / 2, 3.4, CORNER - 5)

c = SIZE / 2
text("blue", "WILLIAMSBURG", c, c - 26, 8.5, SIZE - 2 * CORNER - 12)
text("blue", "WONDERS", c, c - 12, 8.5, SIZE - 2 * CORNER - 12)
text("teal", "Brooklyn, NY", c, c + 2, 4.0, 80)
frame("gold", c - 46, c + 12, 40, 26, 1.0)
frame("gold", c + 6, c + 12, 40, 26, 1.0)
text("gold", "SURPRISE|CARDS", c - 26, c + 25, 3.0, 34)
text("gold", "BANK", c + 26, c + 25, 3.6, 34)
text("teal", "Made by Teddy & Hugo with MocPok", c, c + 48, 2.6, SIZE - 2 * CORNER - 10)


# ---------------- export ----------------
def mesh_arrays(tris):
    index, verts, faces = {}, [], []
    for tri in tris:
        ids = []
        for p in tri:
            key = (round(p[0], 5), round(p[1], 5), round(p[2], 5))
            if key not in index:
                index[key] = len(verts)
                verts.append(key)
            ids.append(index[key])
        if len(set(ids)) == 3:
            faces.append(ids)
    return verts, faces


def write_stl(path, tris):
    with open(path, "wb") as f:
        f.write(b"MocPok Williamsburg board".ljust(80, b" "))
        f.write(struct.pack("<I", len(tris)))
        for a, b, c3 in tris:
            f.write(struct.pack("<12fH", 0, 0, 0, *a, *b, *c3, 0))


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else ".").expanduser()
    template = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    out.mkdir(parents=True, exist_ok=True)
    order = [("white", 1), ("blue", 2), ("teal", 3), ("gold", 4)]
    meshes = {}
    for color, _ in order:
        write_stl(out / f"williamsburg_board_{_}_{color}.stl", parts[color])
        meshes[color] = mesh_arrays(parts[color])
        print(color, len(parts[color]), "triangles,", len(meshes[color][0]), "vertices")

    cx, cy = 98.0, 152.0  # board at back-left; prime tower goes front-right
    objs = []
    for i, (color, _) in enumerate(order, start=1):
        verts, faces = meshes[color]
        v = "".join(f'<vertex x="{x:.5f}" y="{y:.5f}" z="{z:.5f}" />' for x, y, z in verts)
        t = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c3}" />' for a, b, c3 in faces)
        objs.append(f'<object id="{i}" type="model"><mesh><vertices>{v}</vertices><triangles>{t}</triangles></mesh></object>')
    object_model = ('<?xml version="1.0" encoding="UTF-8"?>\n<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" unit="millimeter">'
                    f'<resources>{"".join(objs)}</resources></model>')
    comps = "".join(f'<component p:path="/3D/Objects/object_1.model" objectid="{i}" p:UUID="{uuid.uuid4()}" transform="1 0 0 0 1 0 0 0 1 0 0 0" />'
                    for i in range(1, 5))
    main_model = ('<?xml version="1.0" encoding="UTF-8"?>\n<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
                  'xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" unit="millimeter" xml:lang="en-US" requiredextensions="p">'
                  '<metadata name="Application">BambuStudio-02.07.01.62</metadata><metadata name="BambuStudio:3mfVersion">1</metadata>'
                  '<metadata name="Title">Williamsburg Wonders board</metadata><metadata name="Designer">MocPok</metadata>'
                  f'<resources><object id="5" type="model" p:UUID="{uuid.uuid4()}"><components>{comps}</components></object></resources>'
                  f'<build p:UUID="{uuid.uuid4()}"><item objectid="5" p:UUID="{uuid.uuid4()}" transform="1 0 0 0 1 0 0 0 1 {cx} {cy} 0" printable="1" /></build></model>')
    part_xml = ""
    for i, (color, ext) in enumerate(order, start=1):
        part_xml += (f'<part id="{i}" subtype="normal_part"><metadata key="name" value="{color}" />'
                     f'<metadata key="matrix" value="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1" /><metadata key="extruder" value="{ext}" /></part>')
    settings = ('<?xml version="1.0" encoding="UTF-8"?>\n<config><plate><metadata key="plater_id" value="1" /><metadata key="plater_name" value="Williamsburg board" />'
                '<metadata key="locked" value="false" /><model_instance><metadata key="object_id" value="5" /><metadata key="instance_id" value="0" />'
                '<metadata key="identify_id" value="5" /></model_instance></plate>'
                f'<object id="5"><metadata key="name" value="Williamsburg Wonders board" /><metadata key="extruder" value="1" />{part_xml}</object></config>')
    files = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                               '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                               '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>',
        "_rels/.rels": '<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                       '<Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>',
        "3D/_rels/3dmodel.model.rels": '<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                                       '<Relationship Target="/3D/Objects/object_1.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>',
        "3D/3dmodel.model": main_model,
        "3D/Objects/object_1.model": object_model,
        "Metadata/model_settings.config": settings,
    }
    if template and template.is_file():
        with zipfile.ZipFile(template) as z:
            cfg = json.loads(z.read("Metadata/project_settings.config"))
        cfg["filament_colour"] = ["#FFFFFF", "#2F55D4", "#24A88F", "#EAB542"]
        cfg["layer_height"] = "0.2"
        cfg["initial_layer_print_height"] = "0.2"
        cfg["wipe_tower_x"] = ["205"]
        cfg["wipe_tower_y"] = ["15"]
        cfg["flush_volumes_matrix"] = ["0" if r == k else "350" for r in range(4) for k in range(4)]
        files["Metadata/project_settings.config"] = json.dumps(cfg, indent=4)
    target = out / "Williamsburg_Board_4color.3mf"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    print("wrote", target)


if __name__ == "__main__":
    main()
