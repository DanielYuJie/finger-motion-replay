"""PWM 前臂 v3 ——「塔」式布局（按用户选定的方案 B）

v1 实心浴缸壳、v2 平板都被否掉：用户要的是原 ORCA 那种**立起来的塔**。

关键修正（v2 漏算的量）
----------------------
舵机安装孔在耳朵上、距中心 ±24.25mm（跨距 48.5），所以沿**舵机长度方向**的
实际栅距是 **54.5mm**（含耳总长），不是 40mm。v2 按 40mm 排导致过密。

v3 布局（方案 B）
-----------------
    6 列 (X) × 3 排 (Z) = 18 格，17 颗舵机（16 指 + 1 腕）
    舵机朝向：输出轴统一朝 +Y（线轴全部在同一侧面，便于接腱绳）
      舵机 L(40) -> Z 轴    含耳总长 54.5 决定 Z 向栅距
      舵机 W(20) -> X 轴    决定 X 向栅距
      舵机 H(40) -> Y 轴    轴长 = 塔深
    栅距：X 22.0 / Z 56.5
    塔体：132 (X) × 44 (Y) × 170 (Z) + 顶部腕叉
    安装板在 +Y 面：17 轴孔 Ø8 + 68 安装孔 Ø4.5（每颗 4 个）
    舵机从 -Y 侧装入，耳朵压在安装板背面

用法
----
    python gen_forearm_v3.py [--check]
输出：out/forearm_v3.stl, out/forearm_v3_report.json
"""

from __future__ import annotations

import argparse
import json
import os

import numpy as np
import trimesh

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")

# ============ 舵机（外形尺寸图）============
SERVO = dict(
    L=40.0, W=20.0, H=40.0,
    EAR=7.25,             # 每侧耳外伸 -> 含耳 54.5
    HOLE_D=4.4,
    HOLE_W_SP=10.0,       # 4 孔沿 W 间距 -> ±5
    HOLE_L_SPAN=48.5,     # 4 孔沿 L 跨距 -> ±24.25
    SHAFT_D=7.0,
    SHAFT_OFF_END=10.0,   # 轴心距轴端面（沿 L）-> 相对格心 +10
)

CLEAR = 0.4
CELL_X = SERVO["W"] + 2 * CLEAR + 1.2          # 22.0
CELL_Z = SERVO["L"] + 2 * SERVO["EAR"] + 1.2   # 56.5
COLS_X, ROWS_Z = 6, 3                          # 18 格
N_USED = 17
EMPTY_CELL = (0, 0)                            # 空一格（-X/-Z 角）

PLATE_T = 4.0          # 安装板厚（+Y 面）
CAVITY = SERVO["H"] + 2.0                      # 42 舵机腔深（沿 -Y）
RIB_W = 5.0            # 加强梁宽
SIDE_WALL = 10.0       # 侧向半高墙

SHAFT_HOLE_D = SERVO["SHAFT_D"] + 1.0
MOUNT_HOLE_D = SERVO["HOLE_D"] + 0.1
CUT_LEN = PLATE_T + 12.0

# 腕叉（+Z 端）
FORK_GAP = 26.0
FORK_EAR_T = 6.0
FORK_H = 24.0
FORK_PIN_D = 3.2
FORK_LEN = 20.0

TX = COLS_X * CELL_X + 2 * RIB_W           # 塔宽 X
TZ = ROWS_Z * CELL_Z + 2 * RIB_W           # 塔高 Z
TY = PLATE_T + CAVITY                      # 塔深 Y


def box(sx, sy, sz, c):
    m = trimesh.creation.box(extents=(sx, sy, sz))
    m.apply_translation(c)
    return m


def cyl_axis(d, length, axis, center):
    m = trimesh.creation.cylinder(radius=d / 2.0, height=length, sections=48)
    if axis == "z":
        pass
    elif axis == "y":
        m.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0]))
    elif axis == "x":
        m.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0]))
    m.apply_translation(center)
    return m


def cell_center(col, row):
    """+Y 安装板上的格心（X, Z 平面）。"""
    x = -TX / 2 + RIB_W + CELL_X * (col + 0.5)
    z = -TZ / 2 + RIB_W + CELL_Z * (row + 0.5)
    return x, z


def build():
    # ---- 安装板在 +Y 面：Z 区间 [TY/2 - PLATE_T, TY/2] ----
    y_plate = TY / 2 - PLATE_T / 2
    solids = [box(TX, PLATE_T, TZ, (0, y_plate, 0))]

    # ---- 四角立柱 + 侧壁（-Y 侧，围出舵机腔）----
    wall_y = y_plate - PLATE_T / 2 - CAVITY / 2
    # 四条边立墙（半高，留出侧面观察与散热）
    solids.append(box(RIB_W, CAVITY, TZ, (-TX / 2 + RIB_W / 2, wall_y, 0)))
    solids.append(box(RIB_W, CAVITY, TZ, (TX / 2 - RIB_W / 2, wall_y, 0)))
    solids.append(box(TX, CAVITY, RIB_W, (0, wall_y, -TZ / 2 + RIB_W / 2)))
    solids.append(box(TX, CAVITY, RIB_W, (0, wall_y, TZ / 2 - RIB_W / 2)))
    # ---- 列间纵向梁（沿 Z，分隔 6 列）----
    for i in range(COLS_X - 1):
        x = -TX / 2 + RIB_W + CELL_X * (i + 1)
        solids.append(box(RIB_W, CAVITY, TZ - 2 * RIB_W,
                          (x, wall_y, 0)))
    # ---- 排间横梁（沿 X，分隔 3 排）----
    for j in range(ROWS_Z - 1):
        z = -TZ / 2 + RIB_W + CELL_Z * (j + 1)
        solids.append(box(TX - 2 * RIB_W, CAVITY, RIB_W,
                          (0, wall_y, z)))

    # ---- 腕叉（+Z 端）----
    base = trimesh.boolean.union(solids, engine="manifold")
    fork_z = TZ / 2 + FORK_LEN / 2
    fork_solids = []
    fork_solids.append(box(FORK_GAP + 2 * FORK_EAR_T, PLATE_T + 8, FORK_LEN,
                           (0, TY / 2 - (PLATE_T + 8) / 2, fork_z)))
    for sgn in (-1, 1):
        x = sgn * (FORK_GAP / 2 + FORK_EAR_T / 2)
        fork_solids.append(box(FORK_EAR_T, PLATE_T + 8, FORK_LEN,
                               (x, TY / 2 - (PLATE_T + 8) / 2, fork_z)))
    base = trimesh.boolean.union([base] + fork_solids, engine="manifold")

    # ---- 刀具 ----
    cutters = []
    shafts, mounts = [], []
    used = []
    for row in range(ROWS_Z):
        for col in range(COLS_X):
            if (col, row) == EMPTY_CELL:
                continue
            cx, cz = cell_center(col, row)
            used.append((col, row, cx, cz))
            # 轴心相对格心沿 L(Z) 方向偏移：L/2 - 轴心距轴端面 = 20 - 10 = +10
            sz = cz + (SERVO["L"] / 2 - SERVO["SHAFT_OFF_END"])
            shaft_y = TY / 2 - PLATE_T / 2
            cutters.append(cyl_axis(SHAFT_HOLE_D, CUT_LEN, "y", (cx, shaft_y, sz)))
            shafts.append((col, row, cx, sz))
            # 4 个安装孔：±W/2 沿 X，±48.5/2 沿 Z
            for dx in (-SERVO["HOLE_W_SP"] / 2, SERVO["HOLE_W_SP"] / 2):
                for dz in (-SERVO["HOLE_L_SPAN"] / 2, SERVO["HOLE_L_SPAN"] / 2):
                    cutters.append(cyl_axis(MOUNT_HOLE_D, CUT_LEN, "y",
                                            (cx + dx, shaft_y, cz + dz)))
                    mounts.append((cx + dx, cz + dz))
    # 腕叉销孔（沿 X 贯穿两耳）
    for sgn in (-1, 1):
        x = sgn * (FORK_GAP / 2 + FORK_EAR_T / 2)
        cutters.append(cyl_axis(FORK_PIN_D, FORK_EAR_T + 10, "x",
                                (x, TY / 2 - (PLATE_T + 8) / 2, fork_z)))
    # 腕叉两耳之间让位
    cutters.append(box(FORK_GAP, PLATE_T + 8, FORK_LEN + 6,
                       (0, TY / 2 - (PLATE_T + 8) / 2, fork_z)))

    cutter = trimesh.boolean.union(cutters, engine="manifold")
    part = base.difference(cutter, engine="manifold")
    part.process(validate=True)
    return part, base, shafts, mounts, used


def verify(part, base, shafts, mounts):
    rep = {
        "watertight": bool(part.is_watertight),
        "winding_consistent": bool(part.is_winding_consistent),
        "verts": int(len(part.vertices)),
        "faces": int(len(part.faces)),
        "bbox_mm": [round(float(v), 2) for v in part.extents],
        "volume_mm3": round(float(part.volume), 1),
        "servo_slots": len(shafts),
        "mount_holes": len(mounts),
    }
    # 逐孔判定：安装板 y 区间内若有三角形在 XZ 投影盖住孔心 -> 被挡
    tris = part.triangles
    y_hi, y_lo = TY / 2, TY / 2 - PLATE_T
    ymin = tris[:, :, 1].min(axis=1)
    ymax = tris[:, :, 1].max(axis=1)
    sel = tris[(ymax > y_lo) & (ymin < y_hi)]

    def covered(x, z):
        if len(sel) == 0:
            return False
        a = sel[:, 0, :][:, [0, 2]]
        b = sel[:, 1, :][:, [0, 2]]
        c = sel[:, 2, :][:, [0, 2]]
        v0, v1, v2 = b - a, c - a, np.array([x, z]) - a
        den = v0[:, 0] * v1[:, 1] - v1[:, 0] * v0[:, 1]
        ok = np.abs(den) > 1e-12
        u = np.where(ok, (v2[:, 0] * v1[:, 1] - v1[:, 0] * v2[:, 1]) / np.where(ok, den, 1), -1)
        v = np.where(ok, (v0[:, 0] * v2[:, 1] - v2[:, 0] * v0[:, 1]) / np.where(ok, den, 1), -1)
        return bool(np.any((u >= -1e-9) & (v >= -1e-9) & (u + v <= 1 + 1e-9)))

    bad_s = [(c, r, round(x, 1), round(z, 1)) for c, r, x, z in shafts if covered(x, z)]
    bad_m = [(round(x, 1), round(z, 1)) for x, z in mounts if covered(x, z)]
    rep["shaft_holes"] = f"{len(shafts) - len(bad_s)}/{len(shafts)}"
    rep["mount_holes_ok"] = f"{len(mounts) - len(bad_m)}/{len(mounts)}"
    if bad_s:
        rep["bad_shafts"] = bad_s
    if bad_m:
        rep["bad_mounts"] = bad_m[:6]
    rep["all_holes_ok"] = not bad_s and not bad_m
    return rep


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)

    print(f"  塔体 {TX:.1f} (X) x {TY:.1f} (Y) x {TZ:.1f} (Z) mm + 腕叉 {FORK_LEN}")
    print(f"  布局 {COLS_X} 列 x {ROWS_Z} 排 = {COLS_X * ROWS_Z} 格，用 {N_USED}"
          f"（空 {EMPTY_CELL}），栅距 {CELL_X:.1f} / {CELL_Z:.1f}")
    print(f"  舵机朝向：轴 +Y（线轴同侧）；腔深 {CAVITY:.0f} mm")
    part, base, shafts, mounts, used = build()
    rep = verify(part, base, shafts, mounts)

    print(f"  水密 {rep['watertight']}  法线一致 {rep['winding_consistent']}")
    print(f"  顶点 {rep['verts']}  面 {rep['faces']}")
    print(f"  外廓 {rep['bbox_mm'][0]} x {rep['bbox_mm'][1]} x {rep['bbox_mm'][2]} mm")
    print(f"  体积 {rep['volume_mm3']:.0f} mm3")
    print(f"  轴孔 {rep['shaft_holes']} 通   安装孔 {rep['mount_holes_ok']} 通")
    if rep.get("bad_shafts"):
        print("  !! 被挡轴孔:", rep["bad_shafts"])
    if rep.get("bad_mounts"):
        print("  !! 被挡安装孔:", rep["bad_mounts"])
    ok = rep["watertight"] and rep["winding_consistent"] and rep["all_holes_ok"]
    print(f"  自检: {'通过 ✓' if ok else '有问题 ✗'}")
    if args.check:
        return 0 if ok else 1
    stl = os.path.join(OUT, "forearm_v3.stl")
    part.export(stl)
    with open(os.path.join(OUT, "forearm_v3_report.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)
    print(f"  STL {os.path.getsize(stl) / 1024:.0f} KB -> {stl}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
