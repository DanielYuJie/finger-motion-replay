"""分配板的直流（DC）电路仿真：逐舵机电压降、铜损、器件损耗。

这是什么、不是什么
------------------
· 是：把板子当成**电阻网络 + 恒流负载**，用真实几何算线段电阻，做径向(ladder)
  压降求解。回答的是「末端舵机会不会欠压」这个真正的工程问题。
· 不是：SPICE。**没有**瞬态、没有电机换向浪涌、没有伺服控制器动态、
  没有温度反馈（铜阻只按给的温度系数取一个值）。

几何全部取自 gen_board.py，不是估的。

用法
----
    python power_sim.py              # 跑默认对比场景
    python power_sim.py --oz 2 --rds 0.020
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

# ---- 铜与几何（与 gen_board.py 一致）----
RHO_CU_20 = 1.72e-8       # Ω·m
ALPHA_CU = 0.00393        # /K
T_CU = 50.0               # 假设铜温 °C（跑热了电阻会大）
OZ_TO_M = 35e-6           # 1 oz = 35 µm

TRUNK_MM = 2.4
STUB_MM = 1.5
THIN_MM = 1.2

# ---- 板子几何（mm）----
ROWS = [40.0, 26.0, 12.0]
ROW_COUNTS = [6, 6, 5]
ROW_X0 = [52.0, 52.0, 57.0]
PITCH = 9.5
XD_V, XD_G = 49.0, 46.0

# 公共通路（从输入端子到母干），单位 mm
VIN_SEGS = [
    ("J1+ → Q1 下方", 29.46, THIN_MM),
    ("J1+ 拐入 Q1.D", 4.0, THIN_MM),
    ("Q1.S → 左侧竖干", 4.0, STUB_MM),
    ("左侧竖干 上引", 30.92, STUB_MM),
    ("顶边横干 → V+ 母干", 33.0, TRUNK_MM),
]
GND_SEGS = [("J1- → GND 母干", 38.0, THIN_MM)]

# ---- 连接件与线束（每个舵机一份）----
R_HEADER = 0.020          # 2.54 排针单次接触 ~20 mΩ
R_LEAD_PER_M = 0.084      # 24 AWG 单根 ≈ 84 mΩ/m
LEAD_LEN_M = 0.15         # 假设舵机线长 150 mm


def r_of(length_mm: float, width_mm: float, oz: float, temp_c: float = T_CU) -> float:
    """线段电阻 Ω。"""
    t = oz * OZ_TO_M
    rho = RHO_CU_20 * (1 + ALPHA_CU * (temp_c - 20.0))
    return rho * (length_mm / 1000.0) / ((width_mm / 1000.0) * t)


def servo_positions():
    out = []
    for r, (ry, cnt, x0) in enumerate(zip(ROWS, ROW_COUNTS, ROW_X0)):
        for i in range(cnt):
            out.append((r, ry, x0 + i * PITCH))
    return out


@dataclass
class Result:
    name: str
    v_supply: float
    i_total: float
    v_min: float
    v_min_label: str
    drop_common: float
    drop_row_max: float
    p_fet: float
    p_copper: float


def simulate(name: str, v_supply: float, i_per_servo: float, oz: float, rds: float) -> Result:
    servos = servo_positions()
    r_hdr = R_HEADER
    r_lead = R_LEAD_PER_M * LEAD_LEN_M

    # 每个舵机的负载电流（A）
    loads = {k: i_per_servo for k in range(len(servos))}
    i_total = sum(loads.values())

    # 公共通路压降（承载总电流）
    drop_common = 0.0
    p_copper = 0.0
    for _, L, w in VIN_SEGS + GND_SEGS:
        R = r_of(L, w, oz)
        drop_common += i_total * R
        p_copper += i_total ** 2 * R
    # 母干竖段：每排一段，承载该排及以下电流；这里简化按"每排独立支路"计
    for r, (ry, cnt, x0) in enumerate(zip(ROWS, ROW_COUNTS, ROW_X0)):
        L = 44.0 - (ry + 2.54)
        R = r_of(max(L, 0.1), TRUNK_MM, oz)
        i_row = sum(loads[k] for k, (rr, _, _) in enumerate(servos) if rr == r)
        drop_common += i_row * R
        p_copper += i_row ** 2 * R

    # 每排 ladder
    drop_row: dict[int, float] = {}
    for r, (ry, cnt, x0) in enumerate(zip(ROWS, ROW_COUNTS, ROW_X0)):
        xs = [x0 + i * PITCH for i in range(cnt)]
        d = 0.0
        prev = XD_V
        for j, x in enumerate(xs):
            L = x - prev
            R = r_of(max(L, 0.3), TRUNK_MM, oz)
            i_seg = sum(loads[k] for k, (rr, _, xx) in enumerate(servos)
                        if rr == r and xx >= x)
            d += i_seg * R
            p_copper += i_seg ** 2 * R
            drop_row[(r, j)] = d
            prev = x

    p_fet = i_total ** 2 * rds

    # 逐舵机总压降
    worst, worst_lbl = 1e9, ""
    for k, (r, ry, x) in enumerate(servos):
        j = round((x - ROW_X0[r]) / PITCH)
        v = (v_supply
             - drop_common
             - drop_row.get((r, j), 0.0)
             - i_per_servo * (rds + 2 * r_hdr + 2 * r_lead))
        if v < worst:
            worst, worst_lbl = v, f"第{r + 1}排最远舵机 J{k + 2}@x={x:.1f}"

    drop_row_max = max(drop_row.values()) if drop_row else 0.0
    return Result(name, v_supply, i_total, worst, worst_lbl,
                  drop_common, drop_row_max, p_fet, p_copper)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--v", type=float, default=12.0, help="母线电压 V（你的舵机手册为准）")
    ap.add_argument("--oz", type=float, default=1.0, help="铜厚 oz（1 或 2）")
    ap.add_argument("--rds", type=float, default=0.065, help="P-FET 导通电阻 Ω（如 0.065 / 0.020）")
    args = ap.parse_args()

    print(f"  母线 {args.v} V · 铜厚 {args.oz} oz · P-FET Rds(on) {args.rds * 1000:.0f} mΩ")
    print(f"  假设：铜温 {T_CU:.0f} °C、排针接触 {R_HEADER * 1000:.0f} mΩ/次、"
          f"舵机线 {LEAD_LEN_M * 1000:.0f} mm×24AWG")
    print()
    hdr = f"  {'场景':34s} {'总电流':>8} {'最差舵机压':>10} {'压降占比':>8} {'P-FET':>8} {'铜损':>8}"
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))

    scenarios = [
        ("全 17 舵机 @ 900 mA（默认限流）", 0.900),
        ("全 17 舵机 @ 500 mA", 0.500),
        ("全 17 舵机 @ 300 mA", 0.300),
        ("全 17 舵机 @ 280 mA（≈4.8 A 目标）", 0.280),
        ("全 17 舵机 @ 150 mA（静止保持）", 0.150),
    ]
    for label, i in scenarios:
        r = simulate(label, args.v, i, args.oz, args.rds)
        pct = (1 - r.v_min / args.v) * 100
        print(f"  {label:34s} {r.i_total:7.2f}A {r.v_min:9.3f}V {pct:7.2f}% "
              f"{r.p_fet:7.2f}W {r.p_copper:7.3f}W")
        print(f"      最弱点：{r.v_min_label}   公共段压降 {r.drop_common * 1000:.0f} mV"
              f"   最远排内压降 {r.drop_row_max * 1000:.0f} mV")

    print()
    print("  ── 同场景换 2 oz 铜 + 20 mΩ 的管子 ──")
    for label, i in scenarios[:3]:
        r = simulate(label, args.v, i, 2.0, 0.020)
        pct = (1 - r.v_min / args.v) * 100
        print(f"  {label:34s} {r.i_total:7.2f}A {r.v_min:9.3f}V {pct:7.2f}% "
              f"{r.p_fet:7.2f}W {r.p_copper:7.3f}W")

    print()
    print("  ⚠️ 判断阈值要查你舵机手册的「最低工作电压」——本脚本只给压降，")
    print("     不替你判定「是否欠压」，因为 HLS3915/3930 的欠压阈值我没有可靠来源。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
