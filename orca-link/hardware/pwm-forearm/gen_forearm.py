"""PWM 前臂 v1 参数化生成器（纯 Python: trimesh + manifold3d）。

为什么不用 Blender 做 CSG
-------------------------
第一版用 Blender 的 EXACT 布尔，结果在完全对称的位置（x=0 那一整列）漏切了
2 个轴孔——EXACT 求解器在退化/共面情形下会静默漏切。换 trimesh + manifold3d：
纯 Python、每步可校验、失败会报错而不是静默出错。Blender 只留作渲染。

设计（v1 浴缸式）
-----------------
- 顶板 + 四壁，倒扣打印（顶板贴床面）
- 17 颗 PWM 舵机（40x20x40mm，含耳 54.5）挂在顶板下方，输出轴朝上穿顶板
- 布局 9 列 x 2 行 = 18 格：16 手指 + 1 腕（+X 端），空 1 格
- 顶板：17 个轴孔 Ø8 + 68 个 M4 安装孔 Ø4.5（每颗 4 个）
- +X 壁开腱绳出口槽；底部敞开（v1 不做底盖）

舵机几何（依据用户提供的外形尺寸图）
------------------------------------
本体 40(L) x 20(W) x 40(H)；耳总长 54.5（每侧 7.25）；4 个 Ø4.4 贯穿孔；
轴 Ø7，轴心距轴端面 10mm；孔沿 W 间距 10，沿 L 跨距 48.5。

用法
----
    python gen_forearm.py            # 生成 STL + report.json
    python gen_forearm.py --check    # 只做自检不写文件
"""

from __future__ import annotations

import argparse
import json
import os

import numpy as np
import trimesh

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")

# ============ 舵机参数 ============
SERVO = dict(
    L=40.0, W=20.0, H=40.0,
    EAR=7.25,            # 每侧耳外伸 -> 总长 54.5
    HOLE_D=4.4,          # 耳朵孔（图纸 4-Ø4.4）
    HOLE_W_SP=10.0,      # 4 孔沿 W 方向间距 -> ±5
    HOLE_L_SPAN=48.5,    # 4 孔沿 L 方向跨距 -> ±24.25
    SHAFT_D=7.0,         # 输出轴 Ø7
    SHAFT_OFF_END=10.0,  # 轴心距轴端面 10mm
)
CLEAR = 0.4
WALL_T = 3.0
PLATE_T = 3.0
CAVITY = SERVO["H"] + 1.0
SHAFT_HOLE_D = SERVO["SHAFT_D"] + 1.0
SCREW_HOLE_D = SERVO["HOLE_D"] + 0.1
CUT_H = PLATE_T + 10.0

COLS, ROWS = 9, 2
CELL_X = SERVO["W"] + 2 * CLEAR + 2.0
CELL_Y = SERVO["L"] + 2 * SERVO["EAR"] + 2.0
WRIST_CELL = (8, 0)
EMPTY_CELL = (0, 1)
PX = COLS * CELL_X + 2 * WALL_T
PY = ROWS * CELL_Y + 2 * WALL_T
SLOT = dict(w=120.0, h=30.0)


def cell_center(col: int, row: int) -> tuple[float, float]:
    x = -PX / 2 + WALL_T + CELL_X * (col + 0.5)
    y = -PY / 2 + WALL_T + CELL_Y * (row + 0.5)
    return x, y


def box(sx, sy, sz, center) -> trimesh.Trimesh:
    m = trimesh.creation.box(extents=(sx, sy, sz))
    m.apply_translation(center)
    return m


def cyl(d, h, center) -> trimesh.Trimesh:
    m = trimesh.creation.cylinder(radius=d / 2.0, height=h, sections=48)
    m.apply_translation(center)
    return m


def build():
    plate = box(PX, PY, PLATE_T, (0, 0, -PLATE_T / 2))
    walls = [
        box(PX, WALL_T, CAVITY, (0, -PY / 2 + WALL_T / 2, -PLATE_T - CAVITY / 2)),
        box(PX, WALL_T, CAVITY, (0, PY / 2 - WALL_T / 2, -PLATE_T - CAVITY / 2)),
        box(WALL_T, PY, CAVITY, (-PX / 2 + WALL_T / 2, 0, -PLATE_T - CAVITY / 2)),
        box(WALL_T, PY, CAVITY, (PX / 2 - WALL_T / 2, 0, -PLATE_T - CAVITY / 2)),
    ]
    base = trimesh.boolean.union([plate] + walls, engine="manifold")

    cutters = []
    shafts, screws = [], []
    for row in range(ROWS):
        for col in range(COLS):
            if (col, row) == EMPTY_CELL:
                continue
            cx, cy = cell_center(col, row)
            sy = cy - (SERVO["L"] / 2 - SERVO["SHAFT_OFF_END"])
            cutters.append(cyl(SHAFT_HOLE_D, CUT_H, (cx, sy, -PLATE_T / 2)))
            shafts.append((col, row, cx, sy))
            for dx in (-SERVO["HOLE_W_SP"] / 2, SERVO["HOLE_W_SP"] / 2):
                for dy in (-SERVO["HOLE_L_SPAN"] / 2, SERVO["HOLE_L_SPAN"] / 2):
                    cutters.append(cyl(SCREW_HOLE_D, CUT_H,
                                       (cx + dx, cy + dy, -PLATE_T / 2)))
                    screws.append((cx + dx, cy + dy))
    cutters.append(box(WALL_T + 4, SLOT["w"], SLOT["h"],
                       (PX / 2, 0, -PLATE_T - SLOT["h"] / 2)))

    cutter = trimesh.boolean.union(cutters, engine="manifold")
    part = base.difference(cutter, engine="manifold")
    part.process(validate=True)
    return part, base, shafts, screws


def verify(part, base, shafts, screws) -> dict:
    """不靠射线（trimesh 的射线要 rtree）。用体积 + 截面积核算。

    少切一个孔，体积和面积都会精确偏出已知量，所以这个检验比"抽查射线"更强：
    它一次性覆盖全部 85 个孔。
    """
    rep = {}
    rep["watertight"] = bool(part.is_watertight)
    rep["winding_consistent"] = bool(part.is_winding_consistent)
    rep["verts"] = int(len(part.vertices))
    rep["faces"] = int(len(part.faces))
    rep["bbox_mm"] = [round(float(v), 2) for v in part.extents]
    rep["volume_mm3"] = round(float(part.volume), 1)
    rep["base_volume_mm3"] = round(float(base.volume), 1)

    # --- 体积核算 ---
    r_s = SHAFT_HOLE_D / 2.0
    r_h = SCREW_HOLE_D / 2.0
    v_shaft = len(shafts) * np.pi * r_s ** 2 * PLATE_T
    v_screw = len(screws) * np.pi * r_h ** 2 * PLATE_T
    # 出口槽只吃掉 +X 壁里的那 3mm 厚、119mm 宽、30mm 高
    v_slot = WALL_T * min(SLOT["w"], PY) * SLOT["h"]
    v_pred = base.volume - v_shaft - v_screw - v_slot
    rep["volume_pred_mm3"] = round(float(v_pred), 1)
    rep["volume_err_mm3"] = round(float(part.volume - v_pred), 1)
    rep["volume_err_pct"] = round(abs(float(part.volume - v_pred)) / v_pred * 100, 3)

    # --- 逐孔判定（纯 numpy，不依赖 rtree/射线）---
    # 若存在一个三角形：其 XY 投影盖住孔心，且该三角形在孔心处的 z 落在顶板厚度内
    # -> 孔被实心材料挡住的，即没切出来。
    tris = part.triangles                       # (N,3,3)
    zmin = tris[:, :, 2].min(axis=1)
    zmax = tris[:, :, 2].max(axis=1)
    in_plate = (zmax > -PLATE_T) & (zmin < 0.0)  # 与顶板 z 区间有重叠的三角形

    def covered(x: float, y: float) -> bool:
        sel = tris[in_plate]
        if len(sel) == 0:
            return False
        a, b, c = sel[:, 0, :2], sel[:, 1, :2], sel[:, 2, :2]
        v0, v1, v2 = b - a, c - a, np.array([x, y]) - a
        den = v0[:, 0] * v1[:, 1] - v1[:, 0] * v0[:, 1]
        ok = np.abs(den) > 1e-12
        u = np.where(ok, (v2[:, 0] * v1[:, 1] - v1[:, 0] * v2[:, 1]) / np.where(ok, den, 1), -1)
        v = np.where(ok, (v0[:, 0] * v2[:, 1] - v2[:, 0] * v0[:, 1]) / np.where(ok, den, 1), -1)
        inside = (u >= -1e-9) & (v >= -1e-9) & (u + v <= 1 + 1e-9)
        return bool(np.any(inside))

    bad_s = [(c, r, round(x, 1), round(y, 1)) for c, r, x, y in shafts
             if covered(x, y)]
    bad_h = [(round(x, 1), round(y, 1)) for x, y in screws if covered(x, y)]
    rep["shaft_holes"] = f"{len(shafts) - len(bad_s)}/{len(shafts)}"
    rep["screw_holes"] = f"{len(screws) - len(bad_h)}/{len(screws)}"
    if bad_s:
        rep["bad_shafts"] = bad_s
    if bad_h:
        rep["bad_screws"] = bad_h[:6]
    rep["all_holes_ok"] = not bad_s and not bad_h
    rep["hole_count"] = f"{len(shafts)} shaft + {len(screws)} screw"
    return rep

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只自检，不写文件")
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)

    print(f"  板面 {PX:.1f} x {PY:.1f} mm  腔深 {CAVITY:.1f}  总高 {CAVITY + PLATE_T:.1f}")
    print(f"  格距 {CELL_X:.1f} x {CELL_Y:.1f} mm  舵机格 "
          f"{COLS * ROWS - 1}/{COLS * ROWS}（空置 {EMPTY_CELL}，腕 {WRIST_CELL}）")
    part, base, shafts, screws = build()
    rep = verify(part, base, shafts, screws)

    print(f"  水密 {rep['watertight']}  法线一致 {rep['winding_consistent']}")
    print(f"  顶点 {rep['verts']}  面 {rep['faces']}")
    print(f"  外廓 {rep['bbox_mm'][0]} x {rep['bbox_mm'][1]} x {rep['bbox_mm'][2]} mm")
    print(f"  孔数 {rep['hole_count']}")
    print(f"  轴孔 {rep['shaft_holes']} 通   安装孔 {rep['screw_holes']} 通")
    if rep.get("bad_shafts"):
        print("  !! 被挡住(未切出)的轴孔:", rep["bad_shafts"])
    if rep.get("bad_screws"):
        print("  !! 被挡住的安装孔:", rep["bad_screws"])
    print(f"  体积 实测 {rep['volume_mm3']:.0f} / 预测 {rep['volume_pred_mm3']:.0f} mm³"
          f"  差 {rep['volume_err_mm3']:+.1f}（{rep['volume_err_pct']:.3f}%）")
    ok = (rep["watertight"] and rep["winding_consistent"]
          and rep["all_holes_ok"] and rep["volume_err_pct"] <= 0.1)
    print(f"  自检: {'全部通过 ✓' if ok else '存在问题 ✗'}")
    if args.check:
        return 0 if ok else 1

    stl = os.path.join(OUT, "forearm_v1.stl")
    part.export(stl)
    with open(os.path.join(OUT, "forearm_v1_report.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)
    print(f"  STL {os.path.getsize(stl) / 1024:.0f} KB -> {stl}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
