"""Render preview images for the generated forearm STL (Blender headless).

ASCII-only on purpose: Windows PowerShell 5.1 reads .ps1/.py output in GBK and
mangles non-ASCII console text. Run with:

    blender --background --factory-startup --python render_preview.py
"""

import math
import os

import bpy
from mathutils import Vector

import sys
BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "out")
_argv = [a for a in sys.argv[sys.argv.index("--") + 1:]] if "--" in sys.argv else []
STEM = _argv[0] if _argv else "forearm_v1"
STL = os.path.join(OUT, STEM + ".stl")

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_mesh.stl(filepath=STL)
ob = bpy.context.selected_objects[0]
bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY", center="BOUNDS")
ob.location = (0, 0, 0)

bb = [ob.matrix_world @ Vector(c) for c in ob.bound_box]
lo = Vector([min(v[i] for v in bb) for i in range(3)])
hi = Vector([max(v[i] for v in bb) for i in range(3)])
size = hi - lo
print("BBOX %.1f %.1f %.1f" % (size.x, size.y, size.z))

sc = bpy.context.scene
# EEVEE produces blank frames in --background mode (no GL context). Use Cycles CPU.
sc.render.engine = "CYCLES"
sc.cycles.device = "CPU"
sc.cycles.samples = 24
sc.cycles.use_denoising = True
sc.render.resolution_x = 1100
sc.render.resolution_y = 1100
sc.render.film_transparent = False
if sc.world is None:
    sc.world = bpy.data.worlds.new("W")
sc.world.use_nodes = True
sc.world.node_tree.nodes["Background"].inputs[0].default_value = (0.06, 0.07, 0.09, 1)

# material: neutral grey so holes read clearly
mat = bpy.data.materials.new("m")
mat.use_nodes = True
bsdf = mat.node_tree.nodes["Principled BSDF"]
bsdf.inputs["Base Color"].default_value = (0.55, 0.57, 0.60, 1.0)
bsdf.inputs["Roughness"].default_value = 0.55
ob.data.materials.append(mat)

cam_data = bpy.data.cameras.new("cam")
cam_data.type = "ORTHO"
cam_data.ortho_scale = max(size) * 1.18
# model is in millimetres -> 100+ Blender units; default clip_end=100 clips it away
cam_data.clip_start = 1.0
cam_data.clip_end = 10000.0
cam = bpy.data.objects.new("cam", cam_data)
sc.collection.objects.link(cam)
sc.camera = cam

sun = bpy.data.lights.new("sun", "SUN")
sun.energy = 4.0
sun_ob = bpy.data.objects.new("sun", sun)
sc.collection.objects.link(sun_ob)
sun_ob.rotation_euler = (math.radians(50), 0, math.radians(30))

key = bpy.data.lights.new("key", "AREA")
key.energy = 200000
key.size = 3.0
key_ob = bpy.data.objects.new("key", key)
sc.collection.objects.link(key_ob)
key_ob.location = (2.0, -2.0, 2.5)
key_ob.rotation_euler = (math.radians(50), 0, math.radians(45))

dist = max(size) * 1.3
views = [("top", 0, 90), ("iso", 45, 28), ("side", 0, 0), ("bottom", 180, 25)]
for name, az, el in views:
    th, ph = math.radians(az), math.radians(el)
    d = Vector((math.sin(th) * math.cos(ph),
                math.cos(th) * math.cos(ph),
                math.sin(ph)))
    cam.location = d * dist
    # to_track_quat aligns -Z with the given vector; camera sits at d*dist
    # and must LOOK BACK toward the origin -> use -d, not d.
    cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
    sc.render.filepath = os.path.join(OUT, STEM + "_%s.png" % name)
    bpy.ops.render.render(write_still=True)
    print("rendered %s" % name)
