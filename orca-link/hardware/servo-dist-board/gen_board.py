"""ORCA 17 路舵机供电分配板 —— 板级几何生成器（v0.2）。

v0.2 相比 v0.1 补的三项缺口：
  1. 4 个 M3 安装孔（NPTH Ø3.2，单独出一份钻孔文件）
  2. 丝印文字（自写描边字体）—— 位号 J1..J18 / C1 / C2 / Q1 / R1、极性、标题
  3. 防反接 P-MOSFET（TO-220）：Drain 接输入、Source 接负载、Gate 经 R1 下拉到 GND

关于 P-FET 的方向（容易接反，写清楚）：
  P 沟道的体二极管从 Drain 指向 Source。所以 **Drain 接输入正、Source 接负载**：
  正接时体二极管先导通给负载，Vgs = 0 − Vload ≈ −Vin，沟道随即打开、把二极管短掉；
  反接时 Vgs ≈ 0 不导通，体二极管反偏，阻断。
  接反了（D/S 互换）会变成"反接能通、正接不通"。
  Vgs 额定要 ≥ 供电电压：12 V 级供电用 ±20 V 的管子即可；若上 24 V，
  必须换成 ±30 V 以上的管子，或在 S–G 之间外加稳压管钳位（v0.1 曾计划板上放 D1，
  为减少走线风险已去掉，见 README）。

诚实边界
--------
· 这不是 KiCad 工程，打不开也改不了走线；改设计就改这里的参数后重跑。
· **没有工业 DRC**，只有 self_check()（越界 / 异网间距 / 走线穿异盘 / 环宽 / 孔到铜间距）。
· 丝印字体是自写的简易描边字，只为可读，不追求美观。
"""
from __future__ import annotations

import math
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent / 'out'

# ---------------- 板框与规则 ----------------
BW, BH = 112.0, 50.0
EDGE_SAFE = 1.6
MIN_CLEAR = 0.25
TRUNK_W = 2.4        # 见 v0.1 注释：2.54mm 间距下的几何上限约 2.5mm
SIG_W = 0.4
PAD_HDR, DRILL_HDR = 1.8, 1.0
PAD_TERM, DRILL_TERM = 2.6, 1.3
PAD_BULK, DRILL_BULK = 2.2, 1.0
PAD_CER, DRILL_CER = 1.6, 0.8
PAD_TO220, DRILL_TO220 = 2.1, 1.1   # 2.4 时与邻盘只余 0.14mm，自检判死
PAD_AX, DRILL_AX = 2.0, 1.0
MOUNT_D = 3.2

# ---------------- 版图 ----------------
ROWS = [40.0, 26.0, 12.0]
ROW_COUNTS = [6, 6, 5]
ROW_X0 = [52.0, 52.0, 57.0]
ROW_PITCH = 9.5
XD_V, XD_G, XD_S = 49.0, 46.0, 101.0

MOUNTS = [(6.0, 6.0), (106.0, 6.0), (4.5, 42.0), (106.0, 44.0)]
# 左上那个原本在 (6,44)，会压到 J1 的 GND 盘与 GND 走线（自检报 -0.63 / 0.07）

# ---------------- 描边字体（4 宽 × 6 高 单位网格） ----------------
G: dict[str, list[list[tuple[float, float]]]] = {
    '0': [[(1, 0), (3, 0), (4, 1), (4, 5), (3, 6), (1, 6), (0, 5), (0, 1), (1, 0)]],
    '1': [[(1, 4), (2, 6), (2, 0)], [(0, 0), (4, 0)]],
    '2': [[(0, 5), (1, 6), (3, 6), (4, 5), (4, 4), (0, 1), (0, 0), (4, 0)]],
    '3': [[(0, 6), (4, 6), (2, 4)], [(2, 4), (4, 3), (4, 1), (3, 0), (1, 0), (0, 1)]],
    '4': [[(3, 0), (3, 6), (0, 2), (4, 2)]],
    '5': [[(4, 6), (0, 6), (0, 3), (3, 3), (4, 2), (4, 1), (3, 0), (1, 0), (0, 1)]],
    '6': [[(4, 5), (3, 6), (1, 6), (0, 5), (0, 1), (1, 0), (3, 0), (4, 1), (4, 2), (3, 3), (0, 3)]],
    '7': [[(0, 6), (4, 6), (1, 0)]],
    '8': [[(1, 3), (0, 2), (0, 1), (1, 0), (3, 0), (4, 1), (4, 2), (3, 3), (1, 3),
           (0, 4), (0, 5), (1, 6), (3, 6), (4, 5), (4, 4), (3, 3)]],
    '9': [[(4, 3), (1, 3), (0, 4), (0, 5), (1, 6), (3, 6), (4, 5), (4, 1), (3, 0), (1, 0), (0, 1)]],
    'A': [[(0, 0), (0, 4), (2, 6), (4, 4), (4, 0)], [(0, 3), (4, 3)]],
    'C': [[(4, 5), (3, 6), (1, 6), (0, 5), (0, 1), (1, 0), (3, 0), (4, 1)]],
    'D': [[(0, 0), (0, 6), (2, 6), (4, 4), (4, 2), (2, 0), (0, 0)]],
    'E': [[(4, 6), (0, 6), (0, 0), (4, 0)], [(0, 3), (3, 3)]],
    # 'F' 最初漏了 —— 未定义字符会静默渲染成空白，于是 "P-FET" 印成了 "P- ET"
    'F': [[(4, 6), (0, 6), (0, 0)], [(0, 3), (3, 3)]],
    'G': [[(4, 5), (3, 6), (1, 6), (0, 5), (0, 1), (1, 0), (3, 0), (4, 1), (4, 3), (2, 3)]],
    'I': [[(2, 0), (2, 6)]],
    'J': [[(4, 6), (4, 1), (3, 0), (1, 0), (0, 1)]],
    'L': [[(0, 6), (0, 0), (4, 0)]],
    'M': [[(0, 0), (0, 6), (2, 3), (4, 6), (4, 0)]],
    'N': [[(0, 0), (0, 6), (4, 0), (4, 6)]],
    'O': [[(1, 0), (3, 0), (4, 1), (4, 5), (3, 6), (1, 6), (0, 5), (0, 1), (1, 0)]],
    'P': [[(0, 0), (0, 6), (3, 6), (4, 5), (4, 3), (3, 2), (0, 2)]],
    'Q': [[(1, 0), (3, 0), (4, 1), (4, 5), (3, 6), (1, 6), (0, 5), (0, 1), (1, 0)],
          [(2, 2), (4, 0)]],
    'R': [[(0, 0), (0, 6), (3, 6), (4, 5), (4, 3), (3, 2), (0, 2)], [(2, 2), (4, 0)]],
    'S': [[(4, 5), (3, 6), (1, 6), (0, 5), (0, 4), (1, 3), (3, 3), (4, 2), (4, 1),
           (3, 0), (1, 0), (0, 1)]],
    'T': [[(0, 6), (4, 6)], [(2, 6), (2, 0)]],
    'V': [[(0, 6), (2, 0), (4, 6)]],
    'X': [[(0, 0), (4, 6)], [(0, 6), (4, 0)]],
    '+': [[(2, 1), (2, 5)], [(0, 3), (4, 3)]],
    '-': [[(0, 3), (4, 3)]],
    '.': [[(1.6, 0), (2.4, 0), (2.4, 0.8), (1.6, 0.8), (1.6, 0)]],
    ' ': [],
}


def text_polys(s: str, x: float, y: float, h: float, gap_units: float = 1.4):
    """把文字转成板坐标折线。h = 字高 mm；字宽按 4:6 比例。"""
    unit = h / 6.0
    adv = (4 + gap_units) * unit
    out = []
    cx = x
    for ch in s.upper():
        for poly in G.get(ch, []):
            out.append([(cx + px * unit, y + py * unit) for (px, py) in poly])
        cx += adv
    return out, cx


# ---------------- 数据结构 ----------------
@dataclass
class Pad:
    x: float
    y: float
    dia: float
    drill: float
    net: str
    ref: str


@dataclass
class Hole:
    x: float
    y: float
    dia: float
    label: str


@dataclass
class Trace:
    pts: list[tuple[float, float]]
    width: float
    layer: str
    net: str


@dataclass
class Board:
    pads: list[Pad] = field(default_factory=list)
    traces: list[Trace] = field(default_factory=list)
    npth: list[Hole] = field(default_factory=list)
    silk: list[list[tuple[float, float]]] = field(default_factory=list)

    def add(self, net, pts, width, layer):
        self.traces.append(Trace(pts, width, layer, net))

    def txt(self, s, x, y, h):
        polys, _ = text_polys(s, x, y, h)
        self.silk.extend(polys)


def build() -> Board:
    b = Board()

    for (mx, my) in MOUNTS:
        b.npth.append(Hole(mx, my, MOUNT_D, 'M3'))

    # ---- 17 个 3 针排针：pin1=V+ (上), pin2=GND (中), pin3=SIG (下) ----
    HEADERS = []
    n = 0
    for ry, cnt, x0 in zip(ROWS, ROW_COUNTS, ROW_X0):
        for i in range(cnt):
            n += 1
            x = x0 + i * ROW_PITCH
            HEADERS.append((n, x, ry))
            b.pads.append(Pad(x, ry + 2.54, PAD_HDR, DRILL_HDR, 'V+', f'J{n + 1}'))
            b.pads.append(Pad(x, ry, PAD_HDR, DRILL_HDR, 'GND', f'J{n + 1}'))
            b.pads.append(Pad(x, ry - 2.54, PAD_HDR, DRILL_HDR, 'SIG', f'J{n + 1}'))
            b.silk.append([(x - 1.15, ry + 3.9), (x + 1.15, ry + 3.9),
                           (x + 1.15, ry + 4.4), (x - 1.15, ry + 4.4), (x - 1.15, ry + 3.9)])
            b.txt(f'J{n + 1}', x - 2.2, ry - 5.8, 1.5)   # 位号在 SIG 行下方
    assert len(HEADERS) == 17

    # ---- 输入 / 保护 / 储能 ----
    b.pads.append(Pad(8.0, 40.0, PAD_TERM, DRILL_TERM, 'VIN', 'J1'))     # VIN+
    b.pads.append(Pad(8.0, 45.08, PAD_TERM, DRILL_TERM, 'GND', 'J1'))    # VIN-
    b.pads.append(Pad(12.0, 8.0, PAD_TO220, DRILL_TO220, 'GATE', 'Q1'))  # G
    b.pads.append(Pad(12.0, 10.54, PAD_TO220, DRILL_TO220, 'VIN', 'Q1'))  # D <- 输入
    b.pads.append(Pad(12.0, 13.08, PAD_TO220, DRILL_TO220, 'V+', 'Q1'))   # S -> 负载
    b.pads.append(Pad(20.0, 8.0, PAD_AX, DRILL_AX, 'GATE', 'R1'))
    b.pads.append(Pad(20.0, 18.16, PAD_AX, DRILL_AX, 'GND', 'R1'))
    b.pads.append(Pad(28.0, 34.0, PAD_BULK, DRILL_BULK, 'V+', 'C1'))
    b.pads.append(Pad(28.0, 39.08, PAD_BULK, DRILL_BULK, 'GND', 'C1'))
    b.pads.append(Pad(28.0, 26.0, PAD_CER, DRILL_CER, 'V+', 'C2'))
    b.pads.append(Pad(28.0, 28.54, PAD_CER, DRILL_CER, 'GND', 'C2'))

    # ---- VIN（F.Cu）：J1+ 下行到 Q1.D；Q1.G 经 R1 到地 ----
    b.add('VIN', [(8.0, 40.0), (8.0, 10.54)], 1.2, 'F')
    b.add('VIN', [(8.0, 10.54), (12.0, 10.54)], 1.2, 'F')
    b.add('GATE', [(12.0, 8.0), (20.0, 8.0)], 1.0, 'F')
    b.add('GND', [(20.0, 18.16), (XD_G, 18.16)], 1.0, 'B')

    # ---- V+（F.Cu）：Q1.S → 左侧上行 → 顶边横干 → 母干 ----
    b.add('V+', [(12.0, 13.08), (16.0, 13.08)], 1.5, 'F')
    b.add('V+', [(16.0, 13.08), (16.0, 44.0)], 1.5, 'F')
    b.add('V+', [(16.0, 44.0), (XD_V, 44.0)], TRUNK_W, 'F')
    b.add('V+', [(XD_V, 14.54), (XD_V, 44.0)], TRUNK_W, 'F')
    # C2+ 左引到 x=16 竖干；C1+ 右引再上行（避免与 C1- 同 x 相撞）
    b.add('V+', [(28.0, 26.0), (16.0, 26.0)], 1.0, 'F')
    b.add('V+', [(28.0, 34.0), (33.0, 34.0)], 1.0, 'F')
    b.add('V+', [(33.0, 34.0), (33.0, 44.0)], 1.0, 'F')

    for (_, x, ry) in HEADERS:
        b.add('V+', [(XD_V, ry + 2.54), (x, ry + 2.54)], 1.5, 'F')
    by_row: dict[float, list[float]] = {}
    for (_, x, ry) in HEADERS:
        by_row.setdefault(ry, []).append(x)
    for ry, xs in by_row.items():
        xs.sort()
        b.add('V+', [(xs[0], ry + 2.54), (xs[-1], ry + 2.54)], TRUNK_W, 'F')
        b.add('GND', [(xs[0], ry), (xs[-1], ry)], TRUNK_W, 'B')
        b.add('SIG', [(xs[0], ry - 2.54), (xs[-1], ry - 2.54)], SIG_W, 'F')

    # ---- GND（B.Cu）：J1- / C1- / C2- / R1 → 纵向母干 → 每排 pin2 ----
    b.add('GND', [(8.0, 45.08), (XD_G, 45.08)], 1.2, 'B')
    b.add('GND', [(28.0, 39.08), (XD_G, 39.08)], 1.0, 'B')
    b.add('GND', [(28.0, 28.54), (XD_G, 28.54)], 1.0, 'B')
    b.add('GND', [(XD_G, 12.0), (XD_G, 45.08)], TRUNK_W, 'B')
    # 母干下界必须到最下一排(ry=12)—— 原先只到 18.16，第三排的 GND 桩悬空，
    # 整排 GND 没接上。间距检查抓不到这种"没接"，是连通性检查揪出来的。
    for ry, xs in by_row.items():
        b.add('GND', [(XD_G, ry), (xs[0], ry)], 1.5, 'B')

    # ---- SIG（F.Cu）：每排串接，右端跨排 ----
    xsA = sorted([x for (_, x, ry) in HEADERS if ry == ROWS[0]])
    xsB = sorted([x for (_, x, ry) in HEADERS if ry == ROWS[1]])
    xsC = sorted([x for (_, x, ry) in HEADERS if ry == ROWS[2]])
    b.add('SIG', [(xsA[-1], 37.46), (XD_S, 37.46), (XD_S, 23.46), (xsB[-1], 23.46)], SIG_W, 'F')
    b.add('SIG', [(xsB[-1], 23.46), (XD_S, 23.46), (XD_S, 9.46), (xsC[-1], 9.46)], SIG_W, 'F')

    # ---- 丝印 ----
    b.txt('ORCA 17X SERVO DIST V0.2', 52.0, 46.4, 1.9)
    b.txt('VIN+', 10.5, 40.6, 1.6)
    b.txt('VIN-', 10.5, 43.2, 1.6)
    b.txt('J1', 3.0, 42.0, 1.6)
    b.txt('Q1', 13.6, 8.4, 1.5)
    b.txt('R1', 21.0, 11.0, 1.5)
    b.txt('C1', 29.4, 35.8, 1.5)
    b.txt('C2', 29.4, 27.0, 1.5)
    b.txt('V+', 50.0, 30.0, 1.5)
    b.txt('GND', 43.0, 30.0, 1.5)
    b.txt('SIG', 50.0, 4.0, 1.5)
    b.txt('P-FET REV PROTECT', 6.0, 2.0, 1.3)
    return b


# ---------------- Gerber / Excellon ----------------
def _fmt(v: float) -> str:
    return str(int(round(v * 1e6)))


def write_gerber(path: Path, pads, traces, layer: str, name: str,
                 silk=None, mode: str = 'copper'):
    ap: dict[float, int] = {}

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
        for (x0, y0), (x1, y1) in (((0, 0), (BW, 0)), ((BW, 0), (BW, BH)),
                                   ((BW, BH), (0, BH)), ((0, BH), (0, 0))):
            body.append(f'X{_fmt(x0)}Y{_fmt(y0)}D02*')
            body.append(f'X{_fmt(x1)}Y{_fmt(y1)}D01*')
        path.write_text('\n'.join(lines + body + ['M02*', '']), encoding='ascii')
        return

    want_traces = mode == 'copper'
    want_pads = mode in ('copper', 'mask')
    want_silk = mode == 'silk' and silk

    if want_traces:
        for t in traces:
            if t.layer == layer and t.width > 0:
                dcode(t.width)
    if want_pads:
        for p in pads:
            dcode(p.dia)
    if want_silk:
        dcode(0.15)
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

    if want_silk:
        body.append(f'D{dcode(0.15)}*')
        for poly in silk:
            for i, (x, y) in enumerate(poly):
                body.append(f'X{_fmt(x)}Y{_fmt(y)}D0{2 if i == 0 else 1}*')

    path.write_text('\n'.join(lines + body + ['M02*', '']), encoding='ascii')


def write_drill(path: Path, holes, plated: bool):
    if not holes:
        path.write_text('M48\n;empty\n%\nM30\n', encoding='ascii')
        return
    tools: dict[float, int] = {}
    for h in holes:
        tools.setdefault(round(h.dia, 3), len(tools) + 1)
    out = ['M48', f';{"PTH" if plated else "NPTH"} holes', 'FMAT,2', 'METRIC,TZ']
    for dia, n in sorted(tools.items(), key=lambda kv: kv[1]):
        out.append(f'T{n}C{dia:.3f}')
    out += ['%', 'G90', 'G05', 'M71']
    for dia, n in sorted(tools.items(), key=lambda kv: kv[1]):
        out.append(f'T{n}')
        for h in holes:
            if round(h.dia, 3) == dia:
                out.append(f'X{h.x:.3f}Y{h.y:.3f}')
    out += ['T0', 'M30', '']
    path.write_text('\n'.join(out), encoding='ascii')


# ---------------- 连通性检查 ----------------
def connectivity_problems(b: Board) -> list[str]:
    """按网做连通性：同一张网的所有焊盘必须落在同一个连通块里。

    为什么必须有这一项：间距检查只能发现「离得太近」，发现不了「线没接上」。
    实际踩到的例子 —— GND 母干原写到 y=18.16，而第三排的 GND 在 y=12，
    三者互不相连，整排 GND 悬空，间距检查全绿。

    规则：焊盘是 THT（两层都有），所以焊盘可与任一层走线相连；
    走线与走线只在同层且点落在线段上时相连。
    """
    TOL = 0.05

    def on_seg(p, a, c, tol=TOL):
        ax, ay = a
        cx, cy = c
        px, py = p
        dx, dy = cx - ax, cy - ay
        l2 = dx * dx + dy * dy
        if l2 == 0.0:
            return math.hypot(px - ax, py - ay) <= tol
        t = ((px - ax) * dx + (py - ay) * dy) / l2
        if t < -0.001 or t > 1.001:
            return False
        t = max(0.0, min(1.0, t))
        return math.hypot(px - (ax + t * dx), py - (ay + t * dy)) <= tol

    out: list[str] = []
    nets: dict[str, list[Pad]] = {}
    for p in b.pads:
        nets.setdefault(p.net, []).append(p)

    for net, pads in nets.items():
        traces = [t for t in b.traces if t.net == net and t.width > 0]
        n, m = len(pads), len(traces)
        parent = list(range(n + m))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: int, c_: int) -> None:
            ra, rb = find(a), find(c_)
            if ra != rb:
                parent[ra] = rb

        for i, p in enumerate(pads):
            for j, t in enumerate(traces):
                if any(on_seg((p.x, p.y), t.pts[k], t.pts[k + 1]) for k in range(len(t.pts) - 1)):
                    union(i, n + j)

        for j in range(m):
            for k in range(j + 1, m):
                if traces[j].layer != traces[k].layer:
                    continue
                hit = any(
                    on_seg(a_, traces[k].pts[s], traces[k].pts[s + 1])
                    for a_ in traces[j].pts for s in range(len(traces[k].pts) - 1)
                ) or any(
                    on_seg(a_, traces[j].pts[s], traces[j].pts[s + 1])
                    for a_ in traces[k].pts for s in range(len(traces[j].pts) - 1)
                )
                if hit:
                    union(n + j, n + k)

        groups: dict[int, list[str]] = {}
        for i in range(n):
            groups.setdefault(find(i), []).append(f'{pads[i].ref}')
        if len(groups) > 1:
            detail = ' | '.join(
                f'{len(v)}个({",".join(sorted(set(v))[:5])}…)'.replace(',…', '…')
                for v in groups.values()
            )
            out.append(f'网 {net} 断成 {len(groups)} 块: {detail}')
    return out


# ---------------- 自检 ----------------
def self_check(b: Board) -> list[str]:
    problems: list[str] = []

    for p in b.pads:
        if not (EDGE_SAFE <= p.x <= BW - EDGE_SAFE and EDGE_SAFE <= p.y <= BH - EDGE_SAFE):
            problems.append(f'焊盘越界 {p.ref}@({p.x},{p.y})')
        if p.dia / 2 < p.drill / 2 + 0.15:
            problems.append(f'环宽不足 {p.ref}: pad {p.dia} drill {p.drill}')

    for i in range(len(b.pads)):
        for j in range(i + 1, len(b.pads)):
            a, c = b.pads[i], b.pads[j]
            if a.net == c.net:
                continue
            d = math.hypot(a.x - c.x, a.y - c.y) - (a.dia + c.dia) / 2
            if d < MIN_CLEAR:
                problems.append(f'异网间距 {d:.2f}<{MIN_CLEAR}  {a.ref}({a.net})/{c.ref}({c.net})')

    def seg_pt(p, a, c):
        ax, ay = a
        cx, cy = c
        px, py = p
        dx, dy = cx - ax, cy - ay
        if dx == dy == 0:
            return math.hypot(px - ax, py - ay)
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
        return math.hypot(px - (ax + t * dx), py - (ay + t * dy))

    for t in b.traces:
        if t.width <= 0:
            continue
        for k in range(len(t.pts) - 1):
            for p in b.pads:
                if p.net == t.net:
                    continue
                d = seg_pt((p.x, p.y), t.pts[k], t.pts[k + 1]) - p.dia / 2 - t.width / 2
                if d < MIN_CLEAR:
                    problems.append(f'走线-焊盘 {d:.2f}<{MIN_CLEAR}  走线({t.net}) 与 {p.ref}({p.net})')

    # 安装孔到铜的间距
    for h in b.npth:
        for p in b.pads:
            d = math.hypot(h.x - p.x, h.y - p.y) - h.dia / 2 - p.dia / 2
            if d < MIN_CLEAR:
                problems.append(f'安装孔与焊盘过近 {d:.2f}  {h.label}@({h.x},{h.y}) 与 {p.ref}')
        for t in b.traces:
            if t.width <= 0:
                continue
            for k in range(len(t.pts) - 1):
                d = seg_pt((h.x, h.y), t.pts[k], t.pts[k + 1]) - h.dia / 2 - t.width / 2
                if d < MIN_CLEAR:
                    problems.append(f'安装孔与走线过近 {d:.2f}  {h.label} 与 走线({t.net})')

    problems.extend(connectivity_problems(b))

    # 丝印压到焊盘（丝印盖锡会脏，但不算废板；只提示）
    for poly in b.silk:
        for (sx, sy) in poly:
            for p in b.pads:
                if math.hypot(sx - p.x, sy - p.y) < p.dia / 2:
                    problems.append(f'丝印压焊盘 (非致命) {p.ref}@({p.x},{p.y})')
                    break
    return problems


# ---------------- 预览 ----------------
def render_preview(b: Board, path: Path, scale: int = 14):
    from PIL import Image, ImageDraw, ImageFont

    W, H = int(BW * scale) + 80, int(BH * scale) + 120
    img = Image.new('RGB', (W, H), (250, 250, 250))
    d = ImageDraw.Draw(img)
    ox, oy = 40, 100

    def X(x):
        return ox + x * scale

    def Y(y):
        return oy + (BH - y) * scale

    d.rectangle([X(0), Y(BH), X(BW), Y(0)], outline=(180, 60, 60), width=2)

    for layer, col in (('B', (60, 110, 200)), ('F', (200, 70, 30))):
        for t in b.traces:
            if t.layer != layer or t.width <= 0:
                continue
            for k in range(len(t.pts) - 1):
                d.line([X(t.pts[k][0]), Y(t.pts[k][1]), X(t.pts[k + 1][0]), Y(t.pts[k + 1][1])],
                       fill=col, width=max(1, int(t.width * scale)))
            for (px, py) in t.pts:
                r = t.width * scale / 2
                d.ellipse([X(px) - r, Y(py) - r, X(px) + r, Y(py) + r], fill=col)

    for poly in b.silk:
        for k in range(len(poly) - 1):
            d.line([X(poly[k][0]), Y(poly[k][1]), X(poly[k + 1][0]), Y(poly[k + 1][1])],
                   fill=(120, 120, 120), width=1)

    netcol = {'V+': (200, 40, 30), 'VIN': (220, 130, 20), 'GND': (30, 30, 30),
              'SIG': (30, 140, 60), 'GATE': (140, 60, 180)}
    for p in b.pads:
        r = p.dia * scale / 2
        d.ellipse([X(p.x) - r, Y(p.y) - r, X(p.x) + r, Y(p.y) + r],
                  fill=netcol[p.net], outline=(255, 255, 255))
        r2 = p.drill * scale / 2
        d.ellipse([X(p.x) - r2, Y(p.y) - r2, X(p.x) + r2, Y(p.y) + r2], fill=(245, 245, 245))

    for h in b.npth:
        r = h.dia * scale / 2
        d.ellipse([X(h.x) - r, Y(h.y) - r, X(h.x) + r, Y(h.y) + r], fill=(230, 230, 230),
                  outline=(90, 90, 90), width=2)

    def font(sz, bold=True):
        for nm in (('msyhbd.ttc' if bold else 'msyh.ttc'), 'msyh.ttc', 'simhei.ttf'):
            p = Path(r'C:\Windows\Fonts') / nm
            if p.exists():
                try:
                    return ImageFont.truetype(str(p), sz)
                except Exception:
                    pass
        return ImageFont.load_default()

    d.text((40, 20), f'ORCA 17 路舵机供电分配板  v0.2   {BW:.0f} × {BH:.0f} mm  2 层',
           font=font(24), fill=(30, 30, 30))
    d.text((40, 54),
           'V+ = 红(F.Cu) · VIN = 橙(保护前) · GND = 黑(B.Cu) · SIG = 绿 · GATE = 紫 · 灰线 = 丝印',
           font=font(14, False), fill=(90, 90, 90))
    d.text((40, H - 38),
           f'焊盘 {len(b.pads)} · 走线 {sum(1 for t in b.traces if t.width > 0)} 段 · '
           f'安装孔 {len(b.npth)} · 丝印折线 {len(b.silk)} · 零过孔',
           font=font(14, False), fill=(90, 90, 90))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    b = build()
    problems = self_check(b)
    fatal = [s for s in problems if '丝印压' not in s]

    write_gerber(OUT_DIR / 'board-F_Cu.gtl', b.pads, b.traces, 'F', 'Copper,L1,Top', mode='copper')
    write_gerber(OUT_DIR / 'board-B_Cu.gbl', b.pads, b.traces, 'B', 'Copper,L2,Bot', mode='copper')
    write_gerber(OUT_DIR / 'board-F_Mask.gts', b.pads, b.traces, 'F', 'Soldermask,Top', mode='mask')
    write_gerber(OUT_DIR / 'board-B_Mask.gbs', b.pads, b.traces, 'B', 'Soldermask,Bot', mode='mask')
    write_gerber(OUT_DIR / 'board-F_SilkS.gto', b.pads, b.traces, 'F', 'Legend,Top',
                 silk=b.silk, mode='silk')
    write_gerber(OUT_DIR / 'board-Edge_Cuts.gko', b.pads, b.traces, 'F', 'Profile,NP', mode='outline')
    write_drill(OUT_DIR / 'board-PTH.drl', b.pads, plated=True)
    write_drill(OUT_DIR / 'board-NPTH.drl', b.npth, plated=False)
    render_preview(b, OUT_DIR / 'preview.png')

    zp = OUT_DIR / 'orca-servo-dist-v0.2-gerber.zip'
    for old in OUT_DIR.glob('orca-servo-dist-*.zip'):
        old.unlink(missing_ok=True)
    with zipfile.ZipFile(zp, 'w', zipfile.ZIP_DEFLATED) as z:
        for f in sorted(OUT_DIR.glob('board-*')):
            z.write(f, f.name)

    print(f'  焊盘 {len(b.pads)} / 走线 {sum(1 for t in b.traces if t.width > 0)} 段 / '
          f'安装孔 {len(b.npth)} / 丝印折线 {len(b.silk)}')
    if fatal:
        print(f'  ❌ 致命问题 {len(fatal)} 个:')
        for s in fatal[:20]:
            print('     -', s)
    else:
        print(f'  ✅ 致命项通过：无越界/无异网短路/间距>={MIN_CLEAR}/环宽正常/孔与铜有间距')
    warn = [s for s in problems if '丝印压' in s]
    if warn:
        print(f'  ⚠️ 丝印压焊盘 {len(warn)} 处（非致命，建议挪）')
        for s in warn[:6]:
            print('     -', s)
    print(f'  ZIP: {zp.name}  {zp.stat().st_size / 1024:.1f} KB')
    return 1 if fatal else 0


if __name__ == '__main__':
    raise SystemExit(main())
