"""生成带标注的等距效果图（SVG + HTML 展示页）"""
import math

S = 30
COS30 = math.cos(math.radians(30))
SIN30 = math.sin(math.radians(30))

def project(x, y, z):
    return (x - z) * COS30 * S, (x + z) * SIN30 * S - y * S

PALETTE = {
    "grass":    ("#6aab3c", "#4e8a2a", "#3d6f20"),
    "dirt":     ("#8b6a45", "#6f5436", "#57412a"),
    "palm":     ("#9a9a94", "#7d7d80", "#63636a"),
    "brass":    ("#e0b45c", "#c39442", "#9e7830"),
    "casing":   ("#b98b4e", "#9a7139", "#7a582b"),
    "motor":    ("#5f6b7a", "#4a5461", "#38404a"),
    "segment":  ("#c9b48c", "#ac9772", "#8a7757"),
    "hub":      ("#e2d4b4", "#c4b494", "#9c9074"),
    "shaft":    ("#8d8d95", "#71717a", "#58585f"),
    "redstone": ("#c0392b", "#9c2e22", "#7a231a"),
    "lever":    ("#cfcfcf", "#a8a8a8", "#878787"),
}

cubes = []
def add(x, y, z, kind, tag=None):
    cubes.append({"x": x, "y": y, "z": z, "k": kind, "tag": tag})

# 地面
for gx in range(-6, 12):
    for gz in range(-8, 18):
        add(gx, -1, gz, "grass")
        add(gx, -2, gz, "dirt")

# 掌板
for bx in range(-1, 2):
    for bz in range(-3, 14):
        add(bx, 0, bz, "palm", "palm" if (bx == 0 and bz == 5) else None)

FINGERS = [0, 3, 6, 9]
for i, fz in enumerate(FINGERS):
    add(0, 0, fz - 1, "motor", "motor" if i == 0 else None)
    add(0, 0, fz, "casing", "bearing" if i == 0 else None)
    add(0, 0, fz + 1, "hub", "hub" if i == 0 else None)
    for k in range(1, 4):
        add(k, 0, fz + 1,
            "brass" if k == 3 else "segment",
            "finger" if (i == 0 and k == 2) else None)

# 拇指
add(-2, 0, -2, "motor", "thumbmotor")
add(-1, 0, -2, "casing", "thumbbearing")
add(-1, 0, -1, "hub", "thumbhub")
for k in range(1, 4):
    add(-1, 0, -1 + k, "segment", "thumb" if k == 2 else None)

# 主轴
for sz in range(-3, 14):
    add(2, 0, sz, "shaft", "shaft" if sz == 6 else None)
for fz in FINGERS:
    add(1, 0, fz - 1, "brass", "gear" if fz == 6 else None)
    add(2, 0, fz - 1, "brass")

# 控制台
for i, fz in enumerate(FINGERS):
    add(3, 0, fz - 1, "casing")
    add(3, 1, fz - 1, "lever", "lever" if i == 0 else None)
add(3, 0, 12, "redstone", "redstone")

cubes.sort(key=lambda c: (c["x"] + c["z"], c["y"]))

def face_pts(x, y, z, which):
    if which == "top":
        p = [(x, y+1, z), (x+1, y+1, z), (x+1, y+1, z+1), (x, y+1, z+1)]
    elif which == "x":
        p = [(x+1, y, z), (x+1, y, z+1), (x+1, y+1, z+1), (x+1, y+1, z)]
    else:
        p = [(x, y, z+1), (x+1, y, z+1), (x+1, y+1, z+1), (x, y+1, z+1)]
    return " ".join(f"{px:.1f},{py:.1f}" for px, py in (project(*q) for q in p))

allpts = []
for c in cubes:
    for dx in (0, 1):
        for dy in (0, 1):
            for dz in (0, 1):
                allpts.append(project(c["x"]+dx, c["y"]+dy, c["z"]+dz))
minx = min(p[0] for p in allpts); maxx = max(p[0] for p in allpts)
miny = min(p[1] for p in allpts); maxy = max(p[1] for p in allpts)
PADL, PADR = 150, 330
PADT, PADB = 90, 120
vb = (minx - PADL, miny - PADT,
      (maxx - minx) + PADL + PADR, (maxy - miny) + PADT + PADB)

out = []
out.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb[0]:.0f} {vb[1]:.0f} {vb[2]:.0f} {vb[3]:.0f}" '
           f'font-family="PingFang SC, Microsoft YaHei, sans-serif">')
out.append('<defs>'
           '<linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">'
           '<stop offset="0" stop-color="#12202c"/><stop offset="1" stop-color="#1d2f3d"/>'
           '</linearGradient>'
           '<radialGradient id="glow" cx="0.45" cy="0.3" r="0.75">'
           '<stop offset="0" stop-color="#3f6a86" stop-opacity="0.35"/>'
           '<stop offset="1" stop-color="#12202c" stop-opacity="0"/>'
           '</radialGradient>'
           '</defs>')
out.append(f'<rect x="{vb[0]:.0f}" y="{vb[1]:.0f}" width="{vb[2]:.0f}" height="{vb[3]:.0f}" fill="url(#sky)"/>')
out.append(f'<rect x="{vb[0]:.0f}" y="{vb[1]:.0f}" width="{vb[2]:.0f}" height="{vb[3]:.0f}" fill="url(#glow)"/>')

for c in cubes:
    top, fx, fz_ = PALETTE[c["k"]]
    out.append(f'<polygon points="{face_pts(c["x"], c["y"], c["z"], "x")}" fill="{fx}"/>')
    out.append(f'<polygon points="{face_pts(c["x"], c["y"], c["z"], "z")}" fill="{fz_}"/>')
    out.append(f'<polygon points="{face_pts(c["x"], c["y"], c["z"], "top")}" fill="{top}"/>')
    out.append(f'<polygon points="{face_pts(c["x"], c["y"], c["z"], "top")}" fill="none" '
               f'stroke="#000" stroke-opacity="0.14" stroke-width="0.9"/>')

# ---------- 标注 ----------
LABELS = {
    "palm":         ("掌板（固定基座）", "left"),
    "bearing":      ("机械轴承 · 轴=Z", "left"),
    "hub":          ("轮毂（落在轴上）", "left"),
    "finger":       ("指节 · 垂直伸出才转", "right"),
    "motor":        ("动力（电机 / 舵机位）", "left"),
    "thumb":        ("拇指（轴转90°对掌）", "left"),
    "shaft":        ("主轴（贯穿传动）", "right"),
    "gear":         ("齿轮盘（分动）", "right"),
    "lever":        ("拉杆 = 单指开关", "right"),
    "redstone":     ("红石信号", "right"),
}

anchors = {}
for c in cubes:
    if c["tag"]:
        pts = face_pts(c["x"], c["y"], c["z"], "top").split()
        xs = [float(p.split(",")[0]) for p in pts]
        ys = [float(p.split(",")[1]) for p in pts]
        anchors[c["tag"]] = (sum(xs)/4, sum(ys)/4)

for tag, (text, side) in LABELS.items():
    if tag not in anchors:
        continue
    cx, cy = anchors[tag]
    if side == "left":
        ex, ey = cx - 150, cy - 30
        tx = ex - 12
        anchor = "end"
    else:
        ex, ey = cx + 150, cy - 30
        tx = ex + 12
        anchor = "start"
    out.append(f'<line x1="{cx:.0f}" y1="{cy:.0f}" x2="{ex:.0f}" y2="{ey:.0f}" '
               f'stroke="#e0b45c" stroke-width="1.6" stroke-opacity="0.85"/>')
    out.append(f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="4.5" fill="#e0b45c"/>')
    out.append(f'<circle cx="{ex:.0f}" cy="{ey:.0f}" r="3" fill="#e0b45c"/>')
    w = len(text) * 15 + 24
    bx = tx - w if anchor == "end" else tx
    out.append(f'<rect x="{bx:.0f}" y="{ey-17:.0f}" width="{w}" height="30" rx="7" '
               f'fill="#0d1720" fill-opacity="0.85" stroke="#e0b45c" stroke-opacity="0.5"/>')
    out.append(f'<text x="{tx:.0f}" y="{ey+5:.0f}" font-size="19" fill="#f0e2c4" '
               f'text-anchor="{anchor}">{text}</text>')

# 标题
out.append(f'<text x="{vb[0]+40:.0f}" y="{vb[1]+54:.0f}" font-size="34" font-weight="700" '
           f'fill="#f2ead8">Minecraft · Create 机械手结构效果图</text>')
out.append(f'<text x="{vb[0]+40:.0f}" y="{vb[1]+88:.0f}" font-size="19" '
           f'fill="#8fa8b8">超平坦世界 · 四指 + 拇指 · 轴承轴向 Z · 指节垂直伸出</text>')
out.append("</svg>")

svg = "".join(out)
with open("mc-hand-annotated.svg", "w", encoding="utf-8") as fh:
    fh.write(svg)

# HTML 展示页
html = f'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Create 机械手 · 结构效果图</title>
<style>
  :root{{--ink:#e8eef5;--muted:#8fa8b8;--brass:#e0b45c;--line:#2a3b4a;}}
  *{{box-sizing:border-box;}}
  body{{margin:0;background:#0d1720;color:var(--ink);
    font-family:"PingFang SC","Microsoft YaHei",-apple-system,sans-serif;line-height:1.7;}}
  .wrap{{max-width:1240px;margin:0 auto;padding:36px 26px 70px;}}
  .hero{{border:1px solid var(--line);border-radius:16px;overflow:hidden;background:#101d28;
    box-shadow:0 20px 50px rgba(0,0,0,.4);}}
  .hero svg{{width:100%;height:auto;display:block;}}
  h1{{font-size:1.5rem;margin:34px 0 6px;letter-spacing:-.01em;}}
  .sub{{color:var(--muted);font-size:.9rem;margin:0 0 22px;}}
  .grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:14px;margin-top:8px;}}
  @media(max-width:820px){{.grid{{grid-template-columns:1fr;}}}}
  .card{{background:#121f2b;border:1px solid var(--line);border-radius:12px;padding:16px 18px;}}
  .card h3{{margin:0 0 8px;font-size:.95rem;color:var(--brass);}}
  .card p,.card li{{color:#c3d2de;font-size:.88rem;margin:0 0 6px;}}
  .card ul{{margin:0;padding-left:18px;}}
  table{{width:100%;border-collapse:collapse;font-size:.86rem;margin-top:10px;
    background:#121f2b;border:1px solid var(--line);border-radius:12px;overflow:hidden;}}
  th,td{{padding:10px 13px;text-align:left;border-bottom:1px solid #1e2e3c;}}
  th{{background:#16242f;color:var(--muted);font-size:.76rem;letter-spacing:.05em;text-transform:uppercase;}}
  tr:last-child td{{border-bottom:0;}}
  code{{font-family:Consolas,monospace;color:var(--brass);font-size:.84rem;}}
  .note{{margin-top:20px;padding:14px 18px;border-left:3px solid var(--brass);
    background:rgba(224,180,92,.08);border-radius:0 10px 10px 0;color:#d6c9a8;font-size:.88rem;}}
  footer{{margin-top:36px;padding-top:18px;border-top:1px solid var(--line);color:var(--muted);font-size:.78rem;}}
</style></head><body><div class="wrap">
<h1>Create 机械手 · 结构效果图与搭建依据</h1>
<p class="sub">超平坦草原 · 创造模式 · 永昼 · 四指 + 拇指 · 每指独立动力</p>

<div class="hero">{svg}</div>

<h1>坐标表（相对轴承原点）</h1>
<table>
  <tr><th>部件</th><th>相对坐标</th><th>方块</th><th>朝向 / 要点</th></tr>
  <tr><td>动力</td><td><code>(0, 0, −1)</code></td><td>创造马达 / 速度控制器</td><td>输出面朝南，贴住轴承背面</td></tr>
  <tr><td>轴承</td><td><code>(0, 0, 0)</code></td><td>机械轴承</td><td>朝南 → 旋转轴 = Z</td></tr>
  <tr><td>轮毂</td><td><code>(0, 0, 1)</code></td><td>安山岩</td><td>落在轴上，几乎不自转</td></tr>
  <tr><td>指节 ×3</td><td><code>(1..3, 0, 1)</code></td><td>木质 / 安山岩</td><td><b>垂直于轴伸出</b>，才会被带动</td></tr>
  <tr><td>四指间距</td><td>z = 0 / 3 / 6 / 9</td><td>—</td><td>间隔 ≥3，避免组装时互吸</td></tr>
  <tr><td>拇指</td><td>轴转 90°</td><td>同上</td><td>指节朝北伸，与四指对掌</td></tr>
  <tr><td>主轴</td><td><code>(2, 0, −3..13)</code></td><td>传动轴</td><td>贯穿全手，分动到各指</td></tr>
  <tr><td>控制台</td><td><code>(3, 1, z−1)</code></td><td>拉杆 / 离合器</td><td>单指通断</td></tr>
</table>

<div class="grid">
  <div class="card"><h3>组装顺序</h3>
    <ul>
      <li>先铺掌板，再放轴承与轮毂</li>
      <li>指节接好后<b>右键轴承组装</b></li>
      <li>最后接动力与主轴</li>
      <li>转速从 16 rpm 起调</li>
    </ul>
  </div>
  <div class="card"><h3>四个坑</h3>
    <ul>
      <li>指节顺着轴堆 → 只自转不动</li>
      <li>手指间距太小 → 组装时互吸</li>
      <li>转速拉满 → 装置离心飞散</li>
      <li>轴承背面没动力 → 检查朝向</li>
    </ul>
  </div>
</div>

<div class="note">
  <b>与实物对应：</b>轴承 ≙ 关节，轮毂 ≙ 掌指关节，指节 ≙ 指骨，
  电机 ≙ 舵机，拉杆 ≙ 使能信号，主轴+齿轮 ≙ 传动系统。
  此图用于验证<b>动作逻辑与结构关系</b>，尺寸受力仍需实物验证。
</div>

<footer>Create 机械手 · 结构效果图 · 由坐标数据程序化渲染生成（等距投影）</footer>
</div></body></html>
'''

with open("mc-hand-render.html", "w", encoding="utf-8") as fh:
    fh.write(html)

print("方块数:", len(cubes))
print("标注点:", len(anchors))
print("已生成 mc-hand-annotated.svg 与 mc-hand-render.html")
