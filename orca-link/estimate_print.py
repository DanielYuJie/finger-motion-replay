"""按网格体积估算 ORCA 的打印耗材与时间量级。

为什么不能直接把 60 个 STL 加起来：仓库里同一个位置放了多种**备选件**，你只会打其中一种。

  · 左右手备选：I-AP-L / I-AP-R、L-T-AP / R-T-AP、CORE-L / CORE-R、L-Carpals / R-Carpals …
  · 舵机家族备选：WristStructure_Dynamixel / _Feetech、HullBackDynamixel / HullBackFeetech …
  · 风扇罩多选一：FanCover_ORCA / _TwoFans / _U2D2 / _Feetech 15.20.33
  · 触觉版专属：SidePlate_Touch 等（base 手用不到）

所以脚本按「右手 + Dynamixel + U2D2 风扇罩」这套配置筛出真正要打的件。

体积口径：STL 是封闭实体，先算实体体积，再乘**有效填充率**得到实际挤出量。
有效填充率不是切片里的 infill 百分比——薄壁件靠墙厚就已经很实，所以取值偏高。
默认给 0.4 / 0.55 / 0.7 三档，让你看到区间。

用法：
    python estimate_print.py
"""

from __future__ import annotations

import glob
import os
from pathlib import Path

import trimesh

HERE = Path(__file__).resolve().parent
PARTS = HERE / "docs" / "parts"

PLA_DENSITY = 1.24   # g/cm3
TPU_DENSITY = 1.21   # g/cm3

FILL_FRACTIONS = (0.40, 0.55, 0.70)
# A1 上打这类机械件的有效挤出速率（cm3/h）。区间来自：细feature多、周长多、行程多
THROUGHPUTS = (8.0, 12.0, 20.0)

LEFT_ONLY = {
    "I-AP-L.stl", "L-T-AP.stl", "T-TP-L.stl", "CORE-L.stl", "Coav-L.stl",
    "L-Carpals.stl", "L-Carpals_Skin_TPU.stl", "Carpals_L-Carpals_Skin.stl",
}
FEETECH_ONLY = {
    "WristStructure_Feetech.stl", "WristAdapter_Feetech.stl",
    "ForeArmStructure_Feetech.stl", "HullBackFeetech.stl",
    "FanCover_Feetech 15.20.33.stl",
}
# 风扇罩四选一；用 U2D2（我们走 U2D2 + PHB）
EXTRA_FAN_COVERS = {"FanCover_ORCA.stl", "FanCover_TwoFans.stl"}
# base 手用不到的触觉版件
TOUCH_ONLY = {"SidePlate_Touch.stl"}
# 被家族专用件取代的通用件
SUPERSEDED = {"HullBack.stl"}

TPU_MARKERS = ("09_Skin/", "_Skin", "_Skin_TPU")


def is_tpu(relpath: str) -> bool:
    return "09_Skin" in relpath or "_Skin" in os.path.basename(relpath)


def main() -> int:
    files = sorted(glob.glob(str(PARTS / "*.stl")))
    if not files:
        print(f"没有 STL：{PARTS}")
        return 1

    rows = []
    for f in files:
        name = os.path.basename(f)
        try:
            mesh = trimesh.load(f, force="mesh")
            vol = abs(float(mesh.volume)) / 1000.0  # mm3 -> cm3
            watertight = bool(mesh.is_watertight)
        except Exception as exc:
            print(f"  跳过 {name}: {type(exc).__name__}")
            continue
        rows.append(
            {
                "name": name,
                "vol": vol,
                "watertight": watertight,
                "tpu": is_tpu(name),
                "left": name in LEFT_ONLY,
                "feetech": name in FEETECH_ONLY,
                "extra_fan": name in EXTRA_FAN_COVERS,
                "touch": name in TOUCH_ONLY,
                "superseded": name in SUPERSEDED,
            }
        )

    def summarize(label: str, subset: list[dict]) -> tuple[float, float]:
        pla = sum(r["vol"] for r in subset if not r["tpu"])
        tpu = sum(r["vol"] for r in subset if r["tpu"])
        print(f"\n  {label}（{len(subset)} 件）")
        print(f"    PLA 实体 {pla:7.1f} cm3     TPU 实体 {tpu:6.1f} cm3")
        for fr in FILL_FRACTIONS:
            m_pla = pla * fr * PLA_DENSITY
            m_tpu = tpu * fr * TPU_DENSITY
            print(
                f"      填充 {fr:.0%}:  PLA {m_pla/1000:5.2f} kg   TPU {m_tpu/1000:5.2f} kg"
                f"   合计 {(m_pla+m_tpu)/1000:5.2f} kg"
            )
        return pla, tpu

    print("=" * 74)
    print("ORCA 打印耗材估算（按 STL 实体体积推算）")
    print("=" * 74)

    all_pla, all_tpu = summarize("全部 STL（含所有备选，作上界）", rows)

    keep = [
        r for r in rows
        if not (r["left"] or r["feetech"] or r["extra_fan"] or r["touch"] or r["superseded"])
    ]
    dropped = [r for r in rows if r not in keep]
    one_pla, one_tpu = summarize("右手 + Dynamixel + U2D2 罩（实际要打）", keep)

    print("\n  被剔除的备选件：")
    for r in sorted(dropped, key=lambda r: -r["vol"]):
        tag = "左" if r["left"] else ""
        tag += "FT" if r["feetech"] else ""
        tag += "罩" if r["extra_fan"] else ""
        tag += "触" if r["touch"] else ""
        tag += "旧" if r["superseded"] else ""
        print(f"    {r['name']:<34} {r['vol']:7.1f} cm3   [{tag}]")

    print("\n" + "=" * 74)
    print("打印时间量级（粗估，仅供排期；准确值请在 Bambu Studio 切片后读）")
    print("=" * 74)
    for fr in (0.55,):
        v = (one_pla + one_tpu) * fr
        print(f"  假设有效填充率 {fr:.0%} -> 实际挤出量约 {v:.0f} cm3")
        for thr in THROUGHPUTS:
            hours = v / thr
            print(f"    有效挤出 {thr:4.0f} cm3/h  ->  约 {hours:5.1f} 小时（{hours/24:.1f} 天连续打印）")
    print("\n  注：TPU 要慢得多（约为 PLA 的 1/3~1/2 速率），且必须外置料盘、分任务打。")

    nonwater = [r["name"] for r in rows if not r["watertight"]]
    print(f"\n  水密性：{len(rows)-len(nonwater)}/{len(rows)} 件水密"
          + (f"；不水密（体积不可信）：{nonwater}" if nonwater else "（体积全部可信）"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
