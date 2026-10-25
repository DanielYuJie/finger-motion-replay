"""Blender GUI：并排打开【原版 ORCA 塔】与【我的 v3 塔】做对比。

用法：
    blender.exe --factory-startup --python open_compare_in_blender.py

左边（-X）：原版 P2 三个零件（ForeArmStructure_Feetech + WristAdapter_Feetech
            + WristStructure_Feetech），按各自 STL 的装配坐标放在一起
右边（+X）：我做的 v3（out/forearm_v3.stl），整体平移到旁边
颜色：原版深灰，v3 亮橙，便于一眼分辨
"""

import os

import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
PARTS = os.path.join(os.path.dirname(os.path.dirname(HERE)), "docs", "parts")
V3 = os.path.join(HERE, "out", "forearm_v3.stl")

ORIGINALS = [
    "ForeArmStructure_Feetech.stl",
    "WristAdapter_Feetech.stl",
    "WristStructure_Feetech.stl",
]

bpy.ops.wm.read_factory_settings(use_empty=True)


def make_mat(name, rgba):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = rgba
    b.inputs["Roughness"].default_value = 0.55
    return m


mat_orig = make_mat("orig", (0.32, 0.34, 0.37, 1.0))
mat_v3 = make_mat("v3", (0.95, 0.52, 0.15, 1.0))


def bbox_of(objs):
    pts = []
    for o in objs:
        pts += [o.matrix_world @ Vector(c) for c in o.bound_box]
    lo = Vector([min(p[i] for p in pts) for i in range(3)])
    hi = Vector([max(p[i] for p in pts) for i in range(3)])
    return lo, hi


# ---------- 原版（STL 自带装配坐标，直接叠放）----------
orig_objs = []
for name in ORIGINALS:
    p = os.path.join(PARTS, name)
    if not os.path.exists(p):
        print("skip missing:", name)
        continue
    bpy.ops.import_mesh.stl(filepath=p)
    ob = bpy.context.selected_objects[0]
    ob.name = name.replace(".stl", "")
    ob.data.materials.append(mat_orig)
    orig_objs.append(ob)
    lo, hi = bbox_of([ob])
    print("ORIG %-32s bbox %.1f x %.1f x %.1f  at (%.1f, %.1f, %.1f)"
          % (ob.name, hi.x - lo.x, hi.y - lo.y, hi.z - lo.z,
             (hi.x + lo.x) / 2, (hi.y + lo.y) / 2, (hi.z + lo.z) / 2))

ifo = bbox_of(orig_objs) if orig_objs else (Vector((0, 0, 0)), Vector((1, 1, 1)))
print("ORIG ASSEMBLY bbox %.1f x %.1f x %.1f"
      % (ifo[1].x - ifo[0].x, ifo[1].y - ifo[0].y, ifo[1].z - ifo[0].z))

# ---------- v3 ----------
if os.path.exists(V3):
    bpy.ops.import_mesh.stl(filepath=V3)
    v3 = bpy.context.selected_objects[0]
    v3.name = "forearm_v3_mine"
    v3.data.materials.append(mat_v3)
    lo3, hi3 = bbox_of([v3])
    # 摆到原版右侧，间隔 40 mm
    dx = (ifo[1].x - ifo[0].x) / 2 + (hi3.x - lo3.x) / 2 + 40.0
    v3.location.x += (ifo[1].x + lo3.x - hi3.x) / 2 + dx
    # Z 对齐到底面
    v3.location.z += ifo[0].z - lo3.z
    print("V3   %-32s bbox %.1f x %.1f x %.1f"
          % (v3.name, hi3.x - lo3.x, hi3.y - lo3.y, hi3.z - lo3.z))

allobjs = orig_objs + ([v3] if os.path.exists(V3) else [])
lo, hi = bbox_of(allobjs)

# ---------- 视图 ----------
for scr in bpy.data.screens:
    for area in scr.areas:
        if area.type != "VIEW_3D":
            continue
        for space in area.spaces:
            if space.type != "VIEW_3D":
                continue
            space.shading.type = "SOLID"
            space.shading.light = "STUDIO"
            space.shading.color_type = "MATERIAL"
            space.shading.show_cavity = True
            space.overlay.show_floor = True
            r3d = space.region_3d
            if r3d:
                r3d.view_perspective = "PERSP"
                r3d.view_location = (hi + lo) / 2
                r3d.view_distance = max(hi - lo) * 1.6
                r3d.view_rotation = (0.86, 0.33, 0.12, 0.36)

bpy.ops.object.select_all(action="DESELECT")
for o in allobjs:
    o.select_set(True)
bpy.context.view_layer.objects.active = allobjs[0]
for scr in bpy.data.screens:
    for area in scr.areas:
        if area.type == "VIEW_3D":
            try:
                with bpy.context.temp_override(area=area):
                    bpy.ops.view3d.view_selected()
            except Exception:
                pass
            break

print("OPENED compare scene: originals (grey) left, v3 (orange) right")
