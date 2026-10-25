"""PWM 前臂 v2 参数化生成器（trimesh + manifold3d，Blender 只做渲染）。

相对 v1 的修正
--------------
v1 是实心浴缸壳，丢掉了原 ORCA 前臂的「框架笼（frame cage）」拓扑和腕部接口。
v2 按用户要求在原模型思路基础上重做：

1. **框架笼拓扑**：顶板 + 纵向/横向加强梁 + 半开侧壁（不是实心四壁）
2. **腕部接口**：+X 端一个腕叉（fork），两耳带 Ø3.2 销孔，耳内间距可调，
   对应腕轴 —— 已打印手掌的 `CORE-L/R` 靠 8×13×4 轴承坐在 3×50 销上
3. **舵机腔**：17 个格位（16 手指 + 1 腕），每格 4 个 Ø4.5 安装孔 + 1 个 Ø8 轴孔

硬约束（来自实测/权威数据）
--------------------------
- 腕轴方向：沿 Y（左右横向）；行程 -65°..+35°
- 掌骨侧腱绳入口由已打印件决定，前臂侧自由（PTFE 管可弯）

舵机几何（依据用户提供的外形尺寸图）
------------------------------------
40(L) x 20(W) x 40(H)；含耳 54.5（每侧 7.25）；4 x Ø4.4 孔（沿宽 ±5、沿长 ±24.25）；
轴 Ø7，轴心距轴端面 10mm。

用法
----
    python gen_forearm_v2.py            # 生成 STL + 自检 + report.json
    python gen_forearm_v2.py --check    # 只自检
输出：out/forearm_v2.stl, out/forearm_v2_report.json
"""

from __future__ import annotations

import argparse
import json
import os

import numpy as np
import trimesh

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")

# ============ 舵机 ============
SERVO = dict(
    L=40.0, W=20.0, H=40.0,
    EAR=7.25,
    HOLE_D=4.4,
    HOLE_W_SP=10.0,     # 4 孔沿宽 -> ±5
    HOLE_L_SPAN=48.5,   # 4 孔沿长跨距 -> ±24.25
    SHAFT_D=7.0,
    SHAFT_OFF_END=10.0,  # 轴心距轴端面
)

# ============ 布局 ============
CLEAR = 0.4
CELL_X = SERVO["W"] + 2 * CLEAR + 2.0        # 22.8  沿 X 排舵机厚度
CELL_Y = SERVO["L"] + 2 * SERVO["EAR"] + 2.0  # 56.5  沿 Y 排舵机长度
COLS, ROWS = 8, 2            # 手指：8 列 x 2 行
N_FINGER = COLS * ROWS        # 16
WRIST_SERVO_AT = (COLS, 0)    # 腕舵机：X 端外侧第 1 格

# ============ 结构 ============
PLATE_T = 3.0
CAVITY = SERVO["H"] + 1.0     # 41
RAIL_W = 6.0                  # 加强梁宽
SIDE_WALL_H = 14.0            # 半开侧壁高度（不是全高，方便走线与散热）
END_WALL_T = 4.0

# 腕叉（对应已打印手掌的 CORE-L/R + 8x13x4 轴承 + 3x50 销）
FORK_GAP = 26.0        # 两耳内侧间距（待实测确认）
FORK_EAR_T = 6.0
FORK_H = 26.0
FORK_PIN_D = 3.2       # 3mm 销过孔
FORK_LEN = 18.0

SHAFT_HOLE_D = SERVO["SHAFT_D"] + 1.0
SCREW_HOLE_D = SERVO["HOLE_D"] + 0.1
CUT_H = PLATE_T + 10.0

# 板面
PX = COLS * CELL_X + END_WALL_T + CELL_X + FORK_LEN   # 8列 + 端墙 + 腕格 + 腕叉
PY = ROWS * CELL_Y + 2 * RAIL_W


def box(sx, sy, sz, c) -> trimesh.Trimesh:
    m = trimesh.creation.box(extents=(sx, sy, sz))
    m.apply_translation(c)
    return m


def cyl(d, h, c) -> trimesh.Trimesh:
    m = trimesh.creation.cylinder(radius=d / 2.0, height=h, sections=48)
    m.apply_translation(c)
    return m


def cell_center(col, row):
    x = -PX / 2 + END_WALL_T + CELL_X * (col + 0.5)
    y = -PY / 2 + RAIL_W + CELL_Y * (row + 0.5)
    return x, y


def build():
    # ---- 顶板 ----
    plate = box(PX, PY, PLATE_T, (0, 0, -PLATE_T / 2))
    solids = [plate]

    z_mid = -PLATE_T - SIDE_WALL_H / 2
    # ---- 两侧纵向半开矮墙 ----
    solids.append(box(PX, RAIL_W, SIDE_WALL_H,
                      (0, -PY / 2 + RAIL_W / 2, z_mid)))
    solids.append(box(PX, RAIL_W, SIDE_WALL_H,
                      (0, PY / 2 - RAIL_W / 2, z_mid)))
    # ---- 端墙（-X 端封口；+X 端让位给腕叉）----
    solids.append(box(END_WALL_T, PY, SIDE_WALL_H,
                      (-PX / 2 + END_WALL_T / 2, 0, z_mid)))
    # ---- 行间纵向加强梁（沿 X，分隔两排舵机）----
    solids.append(box(PX - END_WALL_T - CELL_X - FORK_LEN, RAIL_W, SIDE_WALL_H,
                      (-PX / 2 + END_WALL_T + (PX - END_WALL_T - CELL_X - FORK_LEN) / 2,
                       0, z_mid)))
    # ---- 每列之间横向加强梁（沿 Y）----
    n_ribs = COLS - 1
    for i in range(n_ribs):
        x = -PX / 2 + END_WALL_T + CELL_X * (i + 1)
        solids.append(box(RAIL_W, PY - 2 * RAIL_W, SIDE_WALL_H,
                          (x, 0, z_mid)))

    # ---- 腕叉：两耳 + 底连 ----
    x0 = PX / 2 - FORK_LEN
    fork_z = -PLATE_T - FORK_H / 2
    solids.append(box(FORK_LEN, FORK_GAP + 2 * FORK_EAR_T, FORK_H,
                      (x0 + FORK_LEN / 2, 0, -PLATE_T - FORK_H + 1.0)))  # 底连
    for sgn in (-1, 1):
        y = sgn * (FORK_GAP / 2 + FORK_EAR_T / 2)
        solids.append(box(FORK_LEN, FORK_EAR_T, FORK_H,
                          (x0 + FORK_LEN / 2, y, -PLATE_T - FORK_H / 2)))

    base = trimesh.boolean.union(solids, engine="manifold")

    # ---- 刀具 ----
    cutters = []
    shafts, screws = [], []
    cells = [(c, r) for r in range(ROWS) for c in range(COLS)]
    cells.append(WRIST_SERVO_AT)
    for col, row in cells:
        cx, cy = cell_center(col, row)
        sy = cy - (SERVO["L"] / 2 - SERVO["SHAFT_OFF_END"])
        cutters.append(cyl(SHAFT_HOLE_D, CUT_H, (cx, sy, -PLATE_T / 2)))
        shafts.append((col, row, cx, sy))
        for dx in (-SERVO["HOLE_W_SP"] / 2, SERVO["HOLE_W_SP"] / 2):
            for dy in (-SERVO["HOLE_L_SPAN"] / 2, SERVO["HOLE_L_SPAN"] / 2):
                cutters.append(cyl(SCREW_HOLE_D, CUT_H,
                                   (cx + dx, cy + dy, -PLATE_T / 2)))
                screws.append((cx + dx, cy + dy))
    # 腕叉销孔（沿 Y 贯穿两耳）
    for sgn in (-1, 1):
        y = sgn * (FORK_GAP / 2 + FORK_EAR_T / 2)
        m = trimesh.creation.cylinder(radius=FORK_PIN_D / 2,
                                      height=FORK_EAR_T + 8, sections=32)
        m.apply_transform(trimesh.transformations.rotation_matrix(
            np.pi / 2, [1, 0, 0]))
        m.apply_translation((x0 + FORK_LEN / 2, y, -PLATE_T - FORK_H / 2))
        cutters.append(m)
    # 腕叉下方让位（销装入空间）
    cutters.append(box(FORK_LEN + 4, FORK_GAP, FORK_H,
                       (x0 + FORK_LEN / 2, 0, -PLATE_T - FORK_H / 2)))

    cutter = trimesh.boolean.union(cutters, engine="manifold")
    part = base.difference(cutter, engine="manifold")
    part.process(validate=True)
    return part, base, shafts, screws, cells


def verify(part, base, shafts, screws) -> dict:
    rep = {}
    rep["watertight"] = bool(part.is_watertight)
    rep["winding_consistent"] = bool(part.is_winding_consistent)
    rep["verts"] = int(len(part.vertices))
    rep["faces"] = int(len(part.faces))
    rep["bbox_mm"] = [round(float(v), 2) for v in part.extents]
    rep["volume_mm3"] = round(float(part.volume), 1)
    rep["servo_cells"] = len(shafts)
    rep["screw_holes"] = len(screws)

    # 逐孔判定：顶板 z 区间内若有三角形盖住孔心 -> 孔被挡住
    tris = part.triangles
    zmin = tris[:, :, 2].min(axis=1)
    zmax = tris[:, :, 2].max(axis=1)
    sel = tris[(zmax > -PLATE_T) & (zmin < 0.0)]

    def covered(x, y):
        if len(sel) == 0:
            return False
        a, b, c = sel[:, 0, :2], sel[:, 1, :2], sel[:, 2, :2]
        v0, v1, v2 = b - a, c - a, np.array([x, y]) - a
        den = v0[:, 0] * v1[:, 1] - v1[:, 0] * v0[:, 1]
        ok = np.abs(den) > 1e-12
        u = np.where(ok, (v2[:, 0] * v1[:, 1] - v1[:, 0] * v2[:, 1]) / np.where(ok, den, 1), -1)
        v = np.where(ok, (v0[:, 0] * v2[:, 1] - v2[:, 0] * v0[:, 1]) / np.where(ok, den, 1), -1)
        return bool(np.any((u >= -1e-9) & (v >= -1e-9) & (u + v <= 1 + 1e-9)))

    bad_s = [(c, r, round(x, 1), round(y, 1)) for c, r, x, y in shafts if covered(x, y)]
    bad_h = [(round(x, 1), round(y, 1)) for x, y in screws if covered(x, y)]
    rep["shaft_holes"] = f"{len(shafts) - len(bad_s)}/{len(shafts)}"
    rep["mount_holes"] = f"{len(screws) - len(bad_h)}/{len(screws)}"
    if bad_s:
        rep["bad_shafts"] = bad_s
    if bad_h:
        rep["bad_screws"] = bad_h[:6]
    rep["all_holes_ok"] = not bad_s and not bad_h
    return rep


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)

    print(f"  板面 {PX:.1f} x {PY:.1f} mm  (含腕叉 {FORK_LEN}mm)")
    print(f"  格距 {CELL_X:.1f} x {CELL_Y:.1f}  舵机位 {N_FINGER}+1  腔深 {CAVITY:.0f}")
    part, base, shafts, screws, cells = build()
    rep = verify(part, base, shafts, screws)

    print(f"  水密 {rep['watertight']}  法线一致 {rep['winding_consistent']}")
    print(f"  顶点 {rep['verts']}  面 {rep['faces']}")
    print(f"  外廓 {rep['bbox_mm'][0]} x {rep['bbox_mm'][1]} x {rep['bbox_mm'][2]} mm")
    print(f"  体积 {rep['volume_mm3']:.0f} mm3")
    print(f"  轴孔 {rep['shaft_holes']} 通   安装孔 {rep['mount_holes']} 通")
    if rep.get("bad_shafts"):
        print("  !! 被挡轴孔:", rep["bad_shafts"])
    if rep.get("bad_screws"):
        print("  !! 被挡安装孔:", rep["bad_screws"])
    ok = rep["watertight"] and rep["winding_consistent"] and rep["all_holes_ok"]
    print(f"  自检: {'通过 ✓' if ok else '有问题 ✗'}")
    if args.check:
        return 0 if ok else 1
    stl = os.path.join(OUT, "forearm_v2.stl")
    part.export(stl)
    with open(os.path.join(OUT, "forearm_v2_report.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)
    print(f"  STL {os.path.getsize(stl) / 1024:.0f} KB -> {stl}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
