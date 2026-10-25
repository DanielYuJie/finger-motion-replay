"""Blender GUI 启动脚本：打开 PWM 前臂 v3（塔式）。

用法（GUI，非 headless）：

    blender.exe --factory-startup --python open_v3_in_blender.py

会把 out/forearm_v3.stl 导入、切实体着色 + 显示边、并框住视图。
"""

import os

import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
STL = os.path.join(HERE, "out", "forearm_v3.stl")

# 干净场景
bpy.ops.wm.read_factory_settings(use_empty=True)

if not os.path.exists(STL):
    raise SystemExit("missing STL: " + STL)

bpy.ops.import_mesh.stl(filepath=STL)
ob = bpy.context.selected_objects[0]
ob.name = "forearm_v3"

bb = [ob.matrix_world @ Vector(c) for c in ob.bound_box]
size = Vector([max(v[i] for v in bb) - min(v[i] for v in bb) for i in range(3)])
print("LOADED %s  bbox %.1f x %.1f x %.1f mm  verts=%d polys=%d"
      % (ob.name, size.x, size.y, size.z, len(ob.data.vertices), len(ob.data.polygons)))

# 材质：中性灰，孔洞靠边线看清
mat = bpy.data.materials.new("grey")
mat.use_nodes = True
mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.55, 0.57, 0.6, 1)
mat.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.5
ob.data.materials.append(mat)

# 视图：实体着色 + cavity + 边线，俯视斜角
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
            space.shading.show_object_outline = True
            space.overlay.show_floor = True
            space.overlay.show_axis_x = True
            space.overlay.show_axis_y = True
            r3d = space.region_3d
            if r3d:
                r3d.view_perspective = "PERSP"
                r3d.view_location = (0.0, 0.0, 0.0)
                r3d.view_distance = max(size) * 2.2
                r3d.view_rotation = (0.85, 0.35, 0.15, 0.36)

# 选中并框住（需要 3D 视图上下文）
bpy.ops.object.select_all(action="DESELECT")
ob.select_set(True)
bpy.context.view_layer.objects.active = ob
for scr in bpy.data.screens:
    for area in scr.areas:
        if area.type == "VIEW_3D":
            try:
                with bpy.context.temp_override(area=area):
                    bpy.ops.view3d.view_selected()
            except Exception:
                pass
            break

print("OPENED in Blender GUI")
