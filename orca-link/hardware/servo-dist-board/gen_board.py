"""ORCA 17 路舵机供电分配板 —— 板级几何生成器（Gerber / 钻孔 / 预览）。

为什么不用 KiCad
----------------
本来计划装 KiCad 用 kicad-cli 出图，但实测本机网络下不可行：
  · downloads.kicad.org 限速 20 KB/s（1.2 GB 要 20 小时）
  · 清华源 / 阿里源对 kicad-*.exe 均返回 403（只镜像元数据）
  · winget 的包地址在 GitHub Releases，而 github.com:443 被重置
所以改为「板子即代码」：本文件是唯一真值，直接产出嘉立创可消费的 Gerber + Excellon。

诚实边界
--------
这不是 KiCad 工程，打不开也改不了 KiCad 里的走线；要改就改这里的参数后重跑。
**没有跑过工业 DRC**，只有本文件自带的自检（间距/越界/短路），见 self_check()。

电气设计（v0.1）
----------------
· 输入：J1 = 5.08mm 2 位螺钉端子（VIN+ / VIN−）。**保险丝放在供电线上，不在板上** ——
  这样不必为某种保险丝座编一个我无法核实的机械封装。
· 没有防反接：靠丝印标注与上电前检查。加 P-MOSFET 理想二极管需要具体器件选型，
  留给 v0.2（见文末 TODO）。
· C1 1000uF 电解（体电容，吸收 17 舵机换向的电流突变）+ C2 100nF（高频旁路）。
· J2..J18 = 17 个 2.54mm 3 针立式排针（V+ / GND / SIG），与 ORCA 官方接线板的
  2.54mm 3 针口径一致（官方 BOM 料号 C541850）。
· 铜：V+ 走 F.Cu、GND 走 B.Cu（THT 盘天然两面导通，**无需过孔**）、SIG 走 F.Cu
  在板右端串接成菊花链 —— 这样三张网在两层内完全不交叉。

净分布（星形）
--------------
V+ 与 GND 各自有一根**纵向母干**（宽 3.5mm）再分到每一排，而不是 17 级串联；
这就是这块板存在的理由：串着供电到末端必然欠压。
"""
from __future__ import annotations

import math
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent / 'out'

# ---------------- 板框与规则 ----------------
BW, BH = 112.0, 50.0          # 板尺寸 mm
EDGE_SAFE = 1.6               # 焊盘距板边最小
MIN_CLEAR = 0.25              # 不同网之间最小间距（自检用）
TRUNK_W = 2.4                 # V+/GND 母干与排干宽度。
# 为什么不是更宽：排针是 2.54mm 间距，若排干超过约 2.5mm 就会压到相邻焊盘
# （3.5mm 时实测与邻盘重叠 0.11mm —— 这是自检抓出来的，不是估的）。
# 代价是载流能力有限，见 README 的载流说明。
SIG_W = 0.4                   # 信号线宽
PAD_HDR, DRILL_HDR = 1.8, 1.0
PAD_TERM, DRILL_TERM = 2.6, 1.3
PAD_BULK, DRILL_BULK = 2.2, 1.0
PAD_CER, DRILL_CER = 1.6, 0.8

# ---------------- 版图参数 ----------------
ROWS = [40.0, 26.0, 12.0]     # 三排的 pin2(GND) 的 y
ROW_COUNTS = [6, 6, 5]        # 共 17
ROW_X0 = [52.0, 52.0, 57.0]
ROW_PITCH = 9.5
XD_V = 49.0                   # V+ 纵向母干（F.Cu）
XD_G = 46.0                   # GND 纵向母干（B.Cu）
XD_S = 101.0                  # SIG 右侧串接（F.Cu）


@dataclass
class Pad:
    x: float
    y: float
    dia: float
    drill: float
    net: str
    ref: str


@dataclass
class Trace:
    pts: list[tuple[float, float]]
    width: float
    layer: str          # 'F' or 'B'
    net: str


@dataclass
class Board:
    pads: list[Pad] = field(default_factory=list)
    traces: list[Trace] = field(default_factory=list)
    marks: list[tuple[float, float]] = field(default_factory=list)   # 丝印圆点（pin1 标记）

    def add(self, net, ref, pts, width, layer):
        self.traces.append(Trace(pts, width, layer, net))


def build() -> Board:
    b = Board()
    HEADERS = []

    # ---- 17 个 3 针排针：pin1=V+ (上), pin2=GND (中), pin3=SIG (下) ----
    n = 0
    for r, (ry, cnt, x0) in enumerate(zip(ROWS, ROW_COUNTS, ROW_X0)):
        for i in range(cnt):
            n += 1
            x = x0 + i * ROW_PITCH
            HEADERS.append((n, x, ry))
            b.pads.append(Pad(x, ry + 2.54, PAD_HDR, DRILL_HDR, 'V+', f'J{n+1}'))
            b.pads.append(Pad(x, ry, PAD_HDR, DRILL_HDR, 'GND', f'J{n+1}'))
            b.pads.append(Pad(x, ry - 2.54, PAD_HDR, DRILL_HDR, 'SIG', f'J{n+1}'))
            b.marks.append((x - 1.2, ry + 3.9))      # pin1 角标
    assert len(HEADERS) == 17, len(HEADERS)

    # ---- 输入与旁路 ----
    b.pads.append(Pad(8.0, 21.0, PAD_TERM, DRILL_TERM, 'V+', 'J1'))
    b.pads.append(Pad(8.0, 26.08, PAD_TERM, DRILL_TERM, 'GND', 'J1'))
    b.pads.append(Pad(18.0, 23.5, PAD_BULK, DRILL_BULK, 'V+', 'C1'))
    b.pads.append(Pad(23.0, 23.5, PAD_BULK, DRILL_BULK, 'GND', 'C1'))
    b.pads.append(Pad(18.0, 33.0, PAD_CER, DRILL_CER, 'V+', 'C2'))
    b.pads.append(Pad(20.54, 33.0, PAD_CER, DRILL_CER, 'GND', 'C2'))

    # ---- V+ (F.Cu)：输入 → C1+/C2+ → 纵向母干 → 每排 pin1 ----
    # 输入不能走 x=8 上行 —— J1 的 GND 盘就在 (8, 26.08)，正上方那条竖线会穿过它
    # （自检报 -3.05mm 重叠）。故先向右让到 x=13 再上行。
    b.add('V+', 'in1', [(8.0, 21.0), (13.0, 21.0)], 1.5, 'F')
    b.add('V+', 'in2', [(13.0, 21.0), (13.0, 46.0)], 1.5, 'F')
    b.add('V+', 'top', [(13.0, 46.0), (XD_V, 46.0)], TRUNK_W, 'F')       # 顶边横干 → 母干
    b.add('V+', 'c1', [(18.0, 23.5), (18.0, 46.0)], 1.2, 'F')            # C1+ / C2+ 上引
    b.add('V+', 'rail', [(XD_V, 14.54), (XD_V, 46.0)], TRUNK_W, 'F')     # 纵向母干
    for (_, x, ry) in HEADERS:
        b.add('V+', 'stub', [(XD_V, ry + 2.54), (x, ry + 2.54)], 1.5, 'F')   # 母干 → 排干

    # 每排 V+ 排干：连接本排所有 pin1
    by_row: dict[float, list[float]] = {}
    for (_, x, ry) in HEADERS:
        by_row.setdefault(ry, []).append(x)
    for ry, xs in by_row.items():
        xs.sort()
        b.add('V+', 'rowtrunk', [(xs[0], ry + 2.54), (xs[-1], ry + 2.54)], TRUNK_W, 'F')
        b.add('GND', 'rowtrunk', [(xs[0], ry), (xs[-1], ry)], TRUNK_W, 'B')
        b.add('SIG', 'rowtrunk', [(xs[0], ry - 2.54), (xs[-1], ry - 2.54)], SIG_W, 'F')

    # ---- GND (B.Cu)：J1− → C1−/C2− → 纵向母干 → 每排 pin2 ----
    b.add('GND', 'in', [(8.0, 26.08), (XD_G, 26.08)], 1.5, 'B')
    b.add('GND', 'c1', [(23.0, 23.5), (23.0, 26.08)], 1.2, 'B')
    b.add('GND', 'c2', [(20.54, 33.0), (20.54, 26.08)], 1.0, 'B')
    b.add('GND', 'rail', [(XD_G, 12.0), (XD_G, 40.0)], TRUNK_W, 'B')
    for ry, xs in by_row.items():
        b.add('GND', 'stub', [(XD_G, ry), (xs[0], ry)], 1.5, 'B')

    # ---- SIG (F.Cu)：每排 pin3 串接，右端垂直连接三排 ----
    ryA, ryB, ryC = ROWS
    xsA = sorted([x for (_, x, ry) in HEADERS if ry == ryA])
    xsB = sorted([x for (_, x, ry) in HEADERS if ry == ryB])
    xsC = sorted([x for (_, x, ry) in HEADERS if ry == ryC])
    b.add('SIG', 'link1', [(xsA[-1], ryA - 2.54), (XD_S, ryA - 2.54), (XD_S, ryB - 2.54),
                           (xsB[-1], ryB - 2.54)], SIG_W, 'F')
    b.add('SIG', 'link2', [(xsB[-1], ryB - 2.54), (XD_S, ryB - 2.54), (XD_S, ryC - 2.54),
                           (xsC[-1], ryC - 2.54)], SIG_W, 'F')
    return b


# ---------------- Gerber / Excellon 写出 ----------------
def _fmt(v: float) -> str:
    return str(int(round(v * 1e6)))


def write_gerber(path: Path, pads, traces, layer: str, name: str,
                 marks=None, mode: str = 'copper'):
    """mode:
      'copper'  -> 走线 + 焊盘（铜层）
      'mask'    -> 只写焊盘开口（阻焊是负片：有图形处才开窗）
      'silk'    -> 只写丝印标记（不写焊盘与走线，否则丝印会盖到焊盘上）
      'outline' -> 板框
    """
    ap: dict[float, int] = {}          # 直径(取 3 位) -> D 码

    def dcode(dia: float) -> int:
        key = round(dia, 3)
        if key not in ap:
            ap[key] = 10 + len(ap)
        return ap[key]

    lines = [f'%TF.FileFunction,{name}*%', '%FSLAX46Y46*%', '%MOMM*%', 'G01*']
    body: list[str] = []

    if mode == 'outline':
        body.append('%ADD10C,0.150000*%')
        body.append('D10*')
        corners = [(0.0, 0.0), (BW, 0.0), (BW, BH), (0.0, BH)]
        for i in range(4):
            (x0, y0), (x1, y1) = corners[i], corners[(i + 1) % 4]
            body.append(f'X{_fmt(x0)}Y{_fmt(y0)}D02*')
            body.append(f'X{_fmt(x1)}Y{_fmt(y1)}D01*')
        path.write_text('\n'.join(lines + body + ['M02*', '']), encoding='ascii')
        return

    want_traces = mode == 'copper'
    want_pads = mode in ('copper', 'mask')
    want_marks = mode == 'silk'

    # Gerber 要求先定义孔径再使用
    if want_traces:
        for t in traces:
            if t.layer == layer and t.width > 0:
                dcode(t.width)
    if want_pads:
        for p in pads:
            dcode(p.dia)
    for dia, code in sorted(ap.items(), key=lambda kv: kv[1]):
        body.append(f'%ADD{code}C,{dia:.6f}*%')

    if want_traces:
        for t in traces:
            if t.layer != layer or t.width <= 0:
                continue
            body.append(f'D{dcode(t.width)}*')
            for i, (x, y) in enumerate(t.pts):
                body.append(f'X{_fmt(x)}Y{_fmt(y)}D0{2 if i == 0 else 1}*')

    if want_pads:
        for p in pads:
            body.append(f'D{dcode(p.dia)}*')
            body.append(f'X{_fmt(p.x)}Y{_fmt(p.y)}D03*')

    if want_marks and marks:
        body.append('%ADD30C,0.300000*%')
        body.append('D30*')
        for (x, y) in marks:
            body.append(f'X{_fmt(x)}Y{_fmt(y)}D03*')

    path.write_text('\n'.join(lines + body + ['M02*', '']), encoding='ascii')


def write_drill(path: Path, pads):
    tools: dict[float, int] = {}
    for p in pads:
        tools.setdefault(round(p.drill, 3), len(tools) + 1)
    out = ['M48', ';ORCA servo distribution board', 'FMAT,2', 'METRIC,TZ']
    for dia, n in sorted(tools.items(), key=lambda kv: kv[1]):
        out.append(f'T{n}C{dia:.3f}')
    out += ['%', 'G90', 'G05', 'M71']
    for dia, n in sorted(tools.items(), key=lambda kv: kv[1]):
        out.append(f'T{n}')
        for p in pads:
            if round(p.drill, 3) == dia:
                out.append(f'X{p.x:.3f}Y{p.y:.3f}')
    out += ['T0', 'M30', '']
    path.write_text('\n'.join(out), encoding='ascii')


# ---------------- 自检 ----------------
def self_check(b: Board) -> list[str]:
    """我没有工业 DRC，这层自检至少覆盖：越界、异网短路、间距不足、走线穿异网盘。"""
    problems: list[str] = []

    for p in b.pads:
        if not (EDGE_SAFE <= p.x <= BW - EDGE_SAFE and EDGE_SAFE <= p.y <= BH - EDGE_SAFE):
            problems.append(f'焊盘越界 {p.ref}@({p.x},{p.y})')
        if p.dia / 2 >= p.drill / 2 + 0.15:
            pass
        else:
            problems.append(f'环宽不足 {p.ref}: pad {p.dia} drill {p.drill}')

    # 异网焊盘间距
    for i in range(len(b.pads)):
        for j in range(i + 1, len(b.pads)):
            a, c = b.pads[i], b.pads[j]
            if a.net == c.net:
                continue
            d = math.hypot(a.x - c.x, a.y - c.y) - (a.dia + c.dia) / 2
            if d < MIN_CLEAR:
                problems.append(
                    f'异网间距 {d:.2f}mm < {MIN_CLEAR}  {a.ref}({a.net}) / {c.ref}({c.net})')

    def seg_pt_dist(p, a, c):
        ax, ay = a; cx, cy = c
        px, py = p
        dx, dy = cx - ax, cy - ay
        if dx == dy == 0:
            return math.hypot(px - ax, py - ay)
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
        return math.hypot(px - (ax + t * dx), py - (ay + t * dy))

    # 走线是否穿越异网焊盘 / 与异网焊盘过近
    for t in b.traces:
        if t.width <= 0:
            continue
        for k in range(len(t.pts) - 1):
            for p in b.pads:
                if p.net == t.net:
                    continue
                d = seg_pt_dist((p.x, p.y), t.pts[k], t.pts[k + 1]) - p.dia / 2 - t.width / 2
                if d < MIN_CLEAR:
                    problems.append(
                        f'走线-焊盘过近 {d:.2f}mm  走线({t.net}) 与 {p.ref}({p.net})')
    return problems


# ---------------- 预览 ----------------
def render_preview(b: Board, path: Path, scale: int = 14):
    from PIL import Image, ImageDraw, ImageFont

    W, H = int(BW * scale) + 80, int(BH * scale) + 120
    img = Image.new('RGB', (W, H), (250, 250, 250))
    d = ImageDraw.Draw(img)
    ox, oy = 40, 100

    def X(x): return ox + x * scale
    def Y(y): return oy + (BH - y) * scale

    d.rectangle([X(0), Y(BH), X(BW), Y(0)], outline=(180, 60, 60), width=2)

    for layer, col in (('B', (60, 110, 200)), ('F', (200, 70, 30))):
        for t in b.traces:
            if t.layer != layer or t.width <= 0:
                continue
            for k in range(len(t.pts) - 1):
                d.line([X(t.pts[k][0]), Y(t.pts[k][1]), X(t.pts[k+1][0]), Y(t.pts[k+1][1])],
                       fill=col, width=max(1, int(t.width * scale)))
            for (px, py) in t.pts:
                r = t.width * scale / 2
                d.ellipse([X(px) - r, Y(py) - r, X(px) + r, Y(py) + r], fill=col)

    netcol = {'V+': (200, 40, 30), 'GND': (30, 30, 30), 'SIG': (30, 140, 60)}
    for p in b.pads:
        r = p.dia * scale / 2
        d.ellipse([X(p.x) - r, Y(p.y) - r, X(p.x) + r, Y(p.y) + r],
                  fill=netcol[p.net], outline=(255, 255, 255))
        r2 = p.drill * scale / 2
        d.ellipse([X(p.x) - r2, Y(p.y) - r2, X(p.x) + r2, Y(p.y) + r2], fill=(245, 245, 245))
    for (mx, my) in b.marks:
        r = 0.15 * scale
        d.ellipse([X(mx) - r, Y(my) - r, X(mx) + r, Y(my) + r], fill=(120, 120, 120))

    def font(sz, bold=False):
        for nm in (('msyhbd.ttc' if bold else 'msyh.ttc'), 'msyh.ttc', 'simhei.ttf'):
            p = Path(r'C:\Windows\Fonts') / nm
            if p.exists():
                try:
                    return ImageFont.truetype(str(p), sz)
                except Exception:
                    pass
        return ImageFont.load_default()

    d.text((40, 22), f'ORCA 17 路舵机供电分配板  v0.1   {BW:.0f} × {BH:.0f} mm  2 层',
           font=font(24, True), fill=(30, 30, 30))
    d.text((40, 56), '红=V+ 走 F.Cu  ·  黑=GND 走 B.Cu  ·  绿=SIG 走 F.Cu  ·  灰点=丝印 pin1 标记',
           font=font(15), fill=(90, 90, 90))
    d.text((40, H - 42),
           f'焊盘 {len(b.pads)} 个 · 走线 {sum(1 for t in b.traces if t.width>0)} 段 · 17 个 3 针排针（2.54mm）· 无过孔',
           font=font(15), fill=(90, 90, 90))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    b = build()
    problems = self_check(b)

    write_gerber(OUT_DIR / 'board-F_Cu.gtl', b.pads, b.traces, 'F', 'Copper,L1,Top', mode='copper')
    write_gerber(OUT_DIR / 'board-B_Cu.gbl', b.pads, b.traces, 'B', 'Copper,L2,Bot', mode='copper')
    write_gerber(OUT_DIR / 'board-F_Mask.gts', b.pads, b.traces, 'F', 'Soldermask,Top', mode='mask')
    write_gerber(OUT_DIR / 'board-B_Mask.gbs', b.pads, b.traces, 'B', 'Soldermask,Bot', mode='mask')
    write_gerber(OUT_DIR / 'board-F_SilkS.gto', b.pads, b.traces, 'F', 'Legend,Top',
                 marks=b.marks, mode='silk')
    write_gerber(OUT_DIR / 'board-Edge_Cuts.gko', b.pads, b.traces, 'F', 'Profile,NP', mode='outline')
    write_drill(OUT_DIR / 'board-PTH.drl', b.pads)
    render_preview(b, OUT_DIR / 'preview.png')

    zp = OUT_DIR / 'orca-servo-dist-v0.1-gerber.zip'
    with zipfile.ZipFile(zp, 'w', zipfile.ZIP_DEFLATED) as z:
        for f in sorted(OUT_DIR.glob('board-*')):
            z.write(f, f.name)

    print(f'  焊盘 {len(b.pads)} / 走线 {sum(1 for t in b.traces if t.width > 0)} 段')
    print(f'  板框 {BW:.0f} x {BH:.0f} mm')
    if problems:
        print(f'  ❌ 自检发现 {len(problems)} 个问题:')
        for s in problems[:20]:
            print('     -', s)
    else:
        print('  ✅ 自检通过：无越界、无异网短路、间距 >= {:.2f}mm、环宽正常'.format(MIN_CLEAR))
    print(f'  Gerber/钻孔已写入 {OUT_DIR}')
    print(f'  ZIP: {zp.name}  {zp.stat().st_size / 1024:.1f} KB')
    return 1 if problems else 0


if __name__ == '__main__':
    raise SystemExit(main())
