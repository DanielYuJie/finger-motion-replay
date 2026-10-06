"""把等距体素场景渲染为 PNG（Pillow）"""
import math
from PIL import Image, ImageDraw, ImageFilter

S = 46
COS30 = math.cos(math.radians(30))
SIN30 = math.sin(math.radians(30))

def project(x, y, z):
    return (x - z) * COS30 * S, (x + z) * SIN30 * S - y * S

PALETTE = {
    "grass":    ((122, 178, 74), (86, 138, 48), (62, 108, 34)),
    "dirt":     ((150, 116, 78), (118, 90, 58), (92, 68, 42)),
    "andesite": ((176, 176, 172), (142, 142, 146), (110, 110, 118)),
    "palm":     ((166, 166, 160), (134, 134, 138), (104, 104, 112)),
    "brass":    ((232, 190, 106), (198, 152, 66), (158, 118, 44)),
    "casing":   ((196, 150, 88), (160, 118, 62), (124, 90, 44)),
    "motor":    ((104, 116, 132), (78, 90, 104), (58, 68, 80)),
    "accent":   ((86, 172, 224), (62, 130, 176), (44, 100, 138)),
    "segment":  ((214, 194, 152), (180, 160, 122), (142, 124, 92)),
    "hub":      ((226, 212, 178), (196, 180, 146), (156, 142, 114)),
    "shaft":    ((150, 150, 158), (116, 116, 126), (90, 90, 98)),
    "lever":    ((212, 212, 212), (170, 170, 170), (134, 134, 134)),
    "redstone": ((196, 62, 46), (156, 46, 34), (120, 36, 26)),
}

cubes = []
def add(x, y, z, kind):
    cubes.append((x, y, z, kind))

GX0, GX1 = -6, 12
GZ0, GZ1 = -8, 18
for gx in range(GX0, GX1):
    for gz in range(GZ0, GZ1):
        add(gx, -1, gz, "grass")
        add(gx, -2, gz, "dirt")

for bx in range(-1, 2):
    for bz in range(-3, 14):
        add(bx, 0, bz, "palm")

FINGERS = [0, 3, 6, 9]
for fz in FINGERS:
    add(0, 0, fz - 1, "motor")
    add(0, 0, fz, "casing")
    add(0, 0, fz + 1, "hub")
    for k in range(1, 4):
        add(k, 0, fz + 1, "brass" if k == 3 else "segment")

add(-2, 0, -2, "motor")
add(-1, 0, -2, "casing")
add(-1, 0, -1, "hub")
for k in range(1, 4):
    add(-1, 0, -1 + k, "segment")

for sz in range(-3, 14):
    add(2, 0, sz, "shaft")
for fz in FINGERS:
    add(1, 0, fz - 1, "brass")
    add(2, 0, fz - 1, "brass")

for fz in FINGERS:
    add(3, 0, fz - 1, "casing")
    add(3, 1, fz - 1, "lever")
add(3, 0, 12, "redstone")

cubes.sort(key=lambda c: (c[0] + c[2], c[1]))

# 包围盒
allpts = []
for (x, y, z, _k) in cubes:
    for dx in (0, 1):
        for dy in (0, 1):
            for dz in (0, 1):
                allpts.append(project(x + dx, y + dy, z + dz))
minx = min(p[0] for p in allpts); maxx = max(p[0] for p in allpts)
miny = min(p[1] for p in allpts); maxy = max(p[1] for p in allpts)
PAD = 90
W = int(maxx - minx + 2 * PAD)
H = int(maxy - miny + 2 * PAD)
OX = -minx + PAD
OY = -miny + PAD

def sp(x, y, z):
    px, py = project(x, y, z)
    return px + OX, py + OY

img = Image.new("RGB", (W, H), (16, 26, 36))
dr = ImageDraw.Draw(img, "RGBA")

# 天光渐变
for i in range(H):
    t = i / H
    r = int(16 + 34 * (1 - t) * (1 - t))
    g = int(26 + 46 * (1 - t) * (1 - t))
    b = int(36 + 60 * (1 - t) * (1 - t))
    dr.line([(0, i), (W, i)], fill=(r, g, b))

def face(x, y, z, which):
    if which == "top":
        pts = [(x, y + 1, z), (x + 1, y + 1, z), (x + 1, y + 1, z + 1), (x, y + 1, z + 1)]
    elif which == "x":
        pts = [(x + 1, y, z), (x + 1, y, z + 1), (x + 1, y + 1, z + 1), (x + 1, y + 1, z)]
    else:
        pts = [(x, y, z + 1), (x + 1, y, z + 1), (x + 1, y + 1, z + 1), (x, y + 1, z + 1)]
    return [sp(*p) for p in pts]

for (x, y, z, kind) in cubes:
    top, fx, fz_ = PALETTE[kind]
    dr.polygon(face(x, y, z, "x"), fill=fx)
    dr.polygon(face(x, y, z, "z"), fill=fz_)
    dr.polygon(face(x, y, z, "top"), fill=top)
    dr.line(face(x, y, z, "top") + [face(x, y, z, "top")[0]],
            fill=(0, 0, 0, 34), width=1)

# 轻微泛光
glow = img.filter(ImageFilter.GaussianBlur(18))
img = Image.blend(img, glow, 0.16)
img.save("mc-create-hand-render.png")
print("尺寸:", img.size)
print("方块:", len(cubes))
print("已写入 mc-create-hand-render.png")
