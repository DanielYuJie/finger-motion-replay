"""从 gen_board.py 的权威焊盘/网络定义生成**电路原理图**（PNG + SVG）。

为什么需要它
------------
这块板是「板子即代码」：`gen_board.py` 直接产出 Gerber，走的是**没有原理图**的路子
（README「为什么不是 KiCad 工程」一节说明了原因）。后果是：
  * 嘉立创**下单打板不需要原理图**，Gerber 就够 —— 这条不影响你
  * 但**没有一张能读的图**用来接线、复查、或交给别人看
  * 也没有 BOM/CPL —— 走贴片服务时才会卡住

这个脚本把 `gen_board.build()` 里的焊盘按位号分组、按网络连线，画成原理图。
所以图里的连接关系**与板子同源**，不是另画一份。

用法
----
    python gen_schematic.py            # 出 out/schematic.png + out/schematic.svg
"""

from __future__ import annotations

import os
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Circle

# DejaVu Sans 没有 CJK 字形，中文会变方块
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

import gen_board as gb

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"

# ---- 配色（暗底，和 preview.png 一致）----
BG = "#12161c"
FG = "#e6eef6"
DIM = "#8fa3b8"
NET_COLORS = {
    "VIN": "#ffb74d",
    "V+": "#e57373",
    "GND": "#8fa3b8",
    "SIG": "#81c784",
    "GATE": "#ba68c8",
}
SYM = "#1b232c"
WIRE = 1.6


def net_color(net: str) -> str:
    return NET_COLORS.get(net, "#4fc3f7")


def wire(ax, pts, net, lw=WIRE):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    ax.plot(xs, ys, color=net_color(net), lw=lw, solid_capstyle="round", zorder=2)


def junction(ax, x, y, net):
    ax.add_patch(Circle((x, y), 0.45, color=net_color(net), zorder=4))


def label(ax, x, y, text, color=FG, size=8, ha="center", va="center", weight="normal",
          rot=0):
    ax.text(x, y, text, color=color, fontsize=size, ha=ha, va=va, rotation=rot,
            weight=weight, zorder=5)


def box(ax, x, y, w, h, title, subtitle="", edge="#3a4d5e"):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.4,rounding_size=1.0",
                                fc=SYM, ec=edge, lw=1.2, zorder=3))
    label(ax, x + w / 2, y + h * 0.62, title, FG, 9, weight="bold")
    if subtitle:
        label(ax, x + w / 2, y + h * 0.30, subtitle, DIM, 7.5)


def resistor_v(ax, x, y1, y2, ref, val):
    """IEC 矩形电阻，竖放。"""
    cy = (y1 + y2) / 2
    ax.add_patch(FancyBboxPatch((x - 1.6, cy - 3.0), 3.2, 6.0,
                                boxstyle="round,pad=0.2,rounding_size=0.6",
                                fc=SYM, ec=FG, lw=1.3, zorder=3))
    label(ax, x + 3.6, cy + 0.6, ref, FG, 8.5, ha="left", weight="bold")
    label(ax, x + 3.6, cy - 1.8, val, DIM, 7.5, ha="left")


def cap_v(ax, x, y1, y2, ref, val, polarized=False):
    """电容，竖放。polarized 时画一条弧板并标 +。"""
    cy = (y1 + y2) / 2
    ax.plot([x - 2.6, x + 2.6], [cy + 0.9, cy + 0.9], color=FG, lw=1.8, zorder=3)
    if polarized:
        ax.plot([x - 2.6, x + 2.6], [cy - 0.9, cy - 0.9], color=FG, lw=1.8, zorder=3)
        label(ax, x - 3.6, cy + 1.8, "+", "#ffb74d", 9, ha="center", weight="bold")
    else:
        ax.plot([x - 2.6, x + 2.6], [cy - 0.9, cy - 0.9], color=FG, lw=1.8, zorder=3)
    label(ax, x, cy - 3.2, ref, FG, 8.5, ha="center", weight="bold")
    label(ax, x, cy - 5.4, val, DIM, 7.2, ha="center")


def terminal(ax, x, y, net, name, side="left"):
    """接线端子/排针焊盘：小方块 + 网络名。"""
    ax.add_patch(FancyBboxPatch((x - 0.9, y - 0.9), 1.8, 1.8,
                                boxstyle="round,pad=0.1,rounding_size=0.4",
                                fc=net_color(net), ec=FG, lw=0.9, zorder=4))
    if side == "left":
        label(ax, x - 2.0, y, name, DIM, 7.5, ha="right")
    else:
        label(ax, x + 2.0, y, name, DIM, 7.5, ha="left")


def main() -> int:
    b = gb.build()
    OUT.mkdir(exist_ok=True)

    # 按位号分组：{位号: [(网络, 焊盘坐标, 焊盘直径)]}
    by_ref: dict[str, list] = defaultdict(list)
    for p in b.pads:
        by_ref[p.ref].append((p.net, p.x, p.y, p.dia))

    print("  从 gen_board.build() 读到：")
    for ref in sorted(by_ref, key=lambda r: (r[0], len(r))):
        nets = [n for n, *_ in by_ref[ref]]
        print(f"    {ref:<4} {len(nets)} 盘  {nets}")

    fig, ax = plt.subplots(figsize=(15.5, 9.0), facecolor=BG)
    ax.set_facecolor(BG)
    ax.set_xlim(0, 155)
    ax.set_ylim(0, 90)
    ax.set_aspect("equal")
    ax.axis("off")

    label(ax, 2, 86, "ORCA 17 路舵机供电分配板 v0.2 · 电路原理图", FG, 15, ha="left",
          weight="bold")
    label(ax, 2, 82.6,
          "由 gen_board.py 的焊盘/网络定义生成（与 Gerber 同源）；"
          "PCB 层：2 层 · 112×50 mm · 无过孔",
          DIM, 9, ha="left")

    # ================= 输入 + 防反接 =================
    # J1 接线端子
    j1 = by_ref["J1"]
    y_vin, y_gnd = 62.0, 52.0
    terminal(ax, 6, y_vin, "VIN", "J1-1  VIN+")
    terminal(ax, 6, y_gnd, "GND", "J1-2  VIN−")
    label(ax, 6, 66.5, "5.08 mm 螺钉端子", DIM, 8)

    # Q1 P-MOSFET（块符号 + 体二极管方向，这是最容易接反的地方）
    qx, qy, qw, qh = 16.0, 55.0, 26.0, 12.0
    box(ax, qx, qy, qw, qh, "Q1  P 沟道 MOSFET (TO-220)",
        "")
    # 体二极管示意：D -> S
    label(ax, qx + qw / 2, qy + 4.7, "② D 接输入　③ S 接负载", FG, 7.5)
    label(ax, qx + qw / 2, qy + 2.7, "① G 经 R1 下拉到 GND", DIM, 7.5)
    label(ax, qx + qw / 2, qy + 0.9, "体二极管 D → S（反接阻断）", "#ffb74d", 7.5)

    wire(ax, [(7.0, y_vin), (qx, y_vin)], "VIN")
    wire(ax, [(7.0, y_gnd), (14.0, y_gnd), (14.0, 30.0)], "GND")

    # Gate 下拉电阻 R1
    rx = 46.0
    wire(ax, [(qx, 58.0), (rx, 58.0)], "GATE")
    junction(ax, rx, 58.0, "GATE")
    wire(ax, [(rx, 58.0), (rx, 40.5)], "GATE")
    resistor_v(ax, rx, 34.5, 40.5, "R1", "10 kΩ")
    wire(ax, [(rx, 34.5), (rx, 30.0)], "GND")
    wire(ax, [(14.0, 30.0), (rx, 30.0)], "GND")
    label(ax, (qx + qw + rx) / 2 + 3, 61.6, "Gate 下拉", DIM, 8)

    # ================= V+ 母线 + 电容 =================
    y_vp = 70.0
    wire(ax, [(qx + qw, y_vin), (56.0, y_vin), (56.0, y_vp)], "V+")
    label(ax, 53.0, y_vin - 3.0, "S → V+", DIM, 8)
    wire(ax, [(56.0, y_vp), (100.0, y_vp)], "V+", 2.6)
    label(ax, 78.0, y_vp + 2.4, "V+ 母干   2.4 mm / 1 oz", net_color("V+"), 9,
          weight="bold")

    # C1 电解
    cx1 = 62.0
    wire(ax, [(cx1, y_vp), (cx1, 63.5)], "V+")
    cap_v(ax, cx1, 57.5, 63.5, "C1", "1000 µF / ≥35 V", polarized=True)
    wire(ax, [(cx1, 57.5), (cx1, 30.0)], "GND")
    junction(ax, cx1, y_vp, "V+")
    junction(ax, cx1, 30.0, "GND")

    # C2 陶瓷
    cx2 = 82.0
    wire(ax, [(cx2, y_vp), (cx2, 63.5)], "V+")
    cap_v(ax, cx2, 57.5, 63.5, "C2", "100 nF", polarized=False)
    wire(ax, [(cx2, 57.5), (cx2, 30.0)], "GND")
    junction(ax, cx2, y_vp, "V+")
    junction(ax, cx2, 30.0, "GND")

    # ================= 17 路排针 =================
    hx, hy, hw, hh = 104.0, 26.0, 34.0, 50.0
    ax.add_patch(FancyBboxPatch((hx, hy), hw, hh,
                                boxstyle="round,pad=0.6,rounding_size=1.2",
                                fc=SYM, ec="#3a4d5e", lw=1.3, zorder=3))
    label(ax, hx + hw / 2, hy + hh - 4.0, "J2 – J18", FG, 12, weight="bold")
    label(ax, hx + hw / 2, hy + hh - 9.0, "17 × 3 针 2.54 mm 排针", DIM, 8.5)
    for i, (net, txt) in enumerate([("V+", "1  V+"), ("GND", "2  GND"), ("SIG", "3  SIG")]):
        yy = hy + hh - 17.0 - i * 9.0
        terminal(ax, hx, yy, net, txt, side="right")
        label(ax, hx + hw / 2, yy, net, net_color(net), 10, weight="bold")

    # 三条母线接入排针块
    wire(ax, [(hx, hy + hh - 17.0), (hx - 4.0, hy + hh - 17.0)], "V+")
    wire(ax, [(hx, hy + hh - 26.0), (hx - 4.0, hy + hh - 26.0)], "GND")
    wire(ax, [(hx, hy + hh - 35.0), (hx - 4.0, hy + hh - 35.0)], "SIG")

    # V+ 进排针
    wire(ax, [(100.0, y_vp), (100.0, hy + hh - 17.0), (hx, hy + hh - 17.0)], "V+")
    # GND 进排针（沿底部）
    wire(ax, [(14.0, 30.0), (100.0, 30.0), (100.0, hy + hh - 26.0),
              (hx, hy + hh - 26.0)], "GND")
    label(ax, 60.0, 27.0, "GND 回流母干 1.2 mm（⚠ 15 A 时是热点：17.4 mΩ / 4.1 W）",
          net_color("GND"), 8.5)
    wire(ax, [(126.0, hy + hh - 35.0), (140.0, hy + hh - 35.0)], "SIG")
    label(ax, 141.0, hy + hh - 35.0, "→ 各舵机\n信号线", net_color("SIG"), 8.5,
          ha="left")

    # ================= 说明块 =================
    ty = 20.0
    notes = [
        ("⚠ 最容易接反的地方", "#ffb74d"),
        ("P 沟道 MOSFET 的体二极管由 D 指向 S，正确接法是：", FG),
        ("    VIN+ → Q1.D(②)      Q1.S(③) → V+ 负载      Q1.G(①) → R1(10k) → GND", FG),
        ("D/S 接反会变成「反接能通、正接不通」——装完先用万用表二极管档量一遍。", FG),
        ("", FG),
        ("载流能力（别当 15 A 板用）", "#ffb74d"),
        ("    2.4 mm × 1 oz ≈ 3–4 A        2.4 mm × 2 oz ≈ 6–8 A", FG),
        ("    17 × 900 mA = 15.3 A 远超能力 → 建议把单舵机限流降到 280 mA（≈4.8 A）", FG),
        ("", FG),
        ("本图不含保险丝（做在供电线上：ATO / 5×20 座）", DIM),
    ]
    for i, (txt, col) in enumerate(notes):
        if txt:
            label(ax, 2, ty - i * 2.15, txt, col, 8.8, ha="left", va="top",
                  weight="bold" if txt.startswith(("⚠", "载流", "P 沟道")) else "normal")

    ax.plot([100.0, 100.0], [24, 79], color="#26303c", lw=1.0, ls=":", zorder=1)

    png = OUT / "schematic.png"
    svg = OUT / "schematic.svg"
    fig.savefig(png, dpi=150, facecolor=BG, bbox_inches="tight")
    fig.savefig(svg, facecolor=BG, bbox_inches="tight")
    plt.close(fig)
    print(f"\n  {png}  {png.stat().st_size/1024:.0f} KB")
    print(f"  {svg}  {svg.stat().st_size/1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
