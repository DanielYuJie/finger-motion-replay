"""生成 Minecraft Create 机械手的等距体素效果图（SVG）"""
import math

S = 30            # 每格像素
COS30 = math.cos(math.radians(30))
SIN30 = math.sin(math.radians(30))

def project(x, y, z):
    """等距投影：+x 右下，+z 左下，+y 上"""
    sx = (x - z) * COS30 * S
    sy = (x + z) * SIN30 * S - y * S
    return sx, sy

# 方块配色：(顶面, +x面, +z面)
PALETTE = {
    "grass":    ("#6aab3c", "#4e8a2a", "#3d6f20"),
    "dirt":     ("#8b6a45", "#6f5436", "#57412a"),
    "andesite": ("#a8a8a3", "#88888a", "#6e6e73"),
    "palm":     ("#9a9a94", "#7d7d80", "#63636a"),
    "brass":    ("#e0b45c", "#c39442", "#9e7830"),
    "casing":   ("#b98b4e", "#9a7139", "#7a582b"),
    "motor":    ("#5f6b7a", "#4a5461", "#38404a"),
    "accent":   ("#4a9fd8", "#3a7fae", "#2c648a"),
    "segment":  ("#c9b48c", "#ac9772", "#8a7757"),
    "hub":      ("#d8c9a8", "#b8a888", "#94886c"),
    "shaft":    ("#8d8d95", "#71717a", "#58585f"),
    "redstone": ("#c0392b", "#9c2e22", "#7a231a"),
    "lever":    ("#cfcfcf", "#a8a8a8", "#878787"),
    "glass":    ("#9fd6e8", "#7ab4c9", "#5b8fa3"),
}

cubes = []

def add(x, y, z, kind, group=None):
    cubes.append({"x": x, "y": y, "z": z, "kind": kind, "g": group})

# ---------- 地面（超平坦草原） ----------
GX0, GX1 = -6, 12
GZ0, GZ1 = -8, 18
for gx in range(GX0, GX1):
    for gz in range(GZ0, GZ1):
        add(gx, -1, gz, "grass")
        add(gx, -2, gz, "dirt")

# ---------- 掌板与基座 ----------
# 基座一层安山岩，y=0，x -1..1
for bx in range(-1, 2):
    for bz in range(-3, 14):
        add(bx, 0, bz, "palm")

# 轴承与手指
FINGERS = [0, 3, 6, 9]
for i, fz in enumerate(FINGERS):
    # 电机（轴承北侧）
    add(0, 0, fz - 1, "motor")
    add(0, 0, fz - 1, "accent") if False else None
    # 轴承本体
    add(0, 0, fz, "casing")
    # 轮毂（轴承南面）
    add(0, 0, fz + 1, "hub")
    # 三节指节，沿 +x 垂直伸出
    for k in range(1, 4):
        kind = "segment" if k < 3 else "brass"
        add(k, 0, fz + 1, kind)

# 拇指：轴转90°，位于西侧
add(-2, 0, -2, "motor")
add(-1, 0, -2, "casing")
add(-1, 0, -1, "hub")
for k in range(1, 4):
    add(-1, 0, -1 + k, "segment")

# ---------- 传动：主轴 + 齿轮 ----------
for sz in range(-3, 14):
    add(2, 0, sz, "shaft", "shaft")
# 齿轮盘
for fz in FINGERS:
    add(1, 0, fz - 1, "brass")
    add(2, 0, fz - 1, "brass")

# ---------- 控制台：离合 + 拉杆 ----------
for i, fz in enumerate(FINGERS):
    add(3, 0, fz - 1, "casing")     # 离合器
    add(3, 1, fz - 1, "lever")      # 拉杆
add(3, 0, 12, "redstone")

# ---------- 排序：画家算法（远的先画） ----------
cubes.sort(key=lambda c: (c["x"] + c["z"], c["y"]))

# ---------- 生成 SVG ----------
def face_points(x, y, z, which):
    if which == "top":
        pts = [(x, y + 1, z), (x + 1, y + 1, z), (x + 1, y + 1, z + 1), (x, y + 1, z + 1)]
    elif which == "x":
        pts = [(x + 1, y, z), (x + 1, y, z + 1), (x + 1, y + 1, z + 1), (x + 1, y + 1, z)]
    else:  # z
        pts = [(x, y, z + 1), (x + 1, y, z + 1), (x + 1, y + 1, z + 1), (x, y + 1, z + 1)]
    return " ".join(f"{px:.1f},{py:.1f}" for px, py in (project(*p) for p in pts))

# 计算包围盒以设置 viewBox
allpts = []
for c in cubes:
    for dx in (0, 1):
        for dy in (0, 1):
            for dz in (0, 1):
                allpts.append(project(c["x"] + dx, c["y"] + dy, c["z"] + dz))
minx = min(p[0] for p in allpts); maxx = max(p[0] for p in allpts)
miny = min(p[1] for p in allpts); maxy = max(p[1] for p in allpts)
pad = 46
vb = (minx - pad, miny - pad, (maxx - minx) + 2 * pad, (maxy - miny) + 2 * pad)

parts = []
parts.append(
    f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb[0]:.1f} {vb[1]:.1f} {vb[2]:.1f} {vb[3]:.1f}" '
    f'font-family="PingFang SC, Microsoft YaHei, sans-serif">'
)
# 背景天光
parts.append(
    f'<defs><linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">'
    f'<stop offset="0" stop-color="#0f1a24"/><stop offset="1" stop-color="#1b2a36"/>'
    f'</linearGradient>'
    f'<radialGradient id="glow" cx="0.5" cy="0.35" r="0.7">'
    f'<stop offset="0" stop-color="#3b5a6e" stop-opacity="0.55"/>'
    f'<stop offset="1" stop-color="#0f1a24" stop-opacity="0"/>'
    f'</radialGradient></defs>'
)
parts.append(
    f'<rect x="{vb[0]:.1f}" y="{vb[1]:.1f}" width="{vb[2]:.1f}" height="{vb[3]:.1f}" fill="url(#sky)"/>'
)
parts.append(
    f'<rect x="{vb[0]:.1f}" y="{vb[1]:.1f}" width="{vb[2]:.1f}" height="{vb[3]:.1f}" fill="url(#glow)"/>'
)

for c in cubes:
    top, fx, fz_ = PALETTE[c["kind"]]
    parts.append(f'<polygon points="{face_points(c["x"], c["y"], c["z"], "x")}" fill="{fx}"/>')
    parts.append(f'<polygon points="{face_points(c["x"], c["y"], c["z"], "z")}" fill="{fz_}"/>')
    parts.append(f'<polygon points="{face_points(c["x"], c["y"], c["z"], "top")}" fill="{top}"/>')
    # 描边强调体素块感
    parts.append(
        f'<polygon points="{face_points(c["x"], c["y"], c["z"], "top")}" fill="none" '
        f'stroke="#000" stroke-opacity="0.13" stroke-width="0.8"/>'
    )

parts.append("</svg>")
svg = "".join(parts)

with open("mc-create-hand.svg", "w", encoding="utf-8") as fh:
    fh.write(svg)

print("方块数:", len(cubes))
print("viewBox:", [round(v, 1) for v in vb])
print("已写入 mc-create-hand.svg")
