"""Measure servo bay openings of an STL by ray-mask along one axis (Blender).

Emits a .npy boolean mask: True where a ray cast along -axis passes through
the part without hitting anything (i.e. an opening).

    blender --background --factory-startup --python measure_bays.py -- <stl> <axis 0/1/2> <res>
"""

import sys

import bpy
import numpy as np
from mathutils import Vector

argv = sys.argv
argv = argv[argv.index("--") + 1:] if "--" in argv else []
STL = argv[0]
AXIS = int(argv[1])
RES = int(argv[2])
OUTNPY = argv[3]

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_mesh.stl(filepath=STL)
ob = bpy.context.selected_objects[0]
bb = [ob.matrix_world @ Vector(c) for c in ob.bound_box]
lo = Vector([min(v[i] for v in bb) for i in range(3)])
hi = Vector([max(v[i] for v in bb) for i in range(3)])

dg = bpy.context.evaluated_depsgraph_get()
scene = bpy.context.scene

u, v = [i for i in range(3) if i != AXIS]
su = (lo[u], hi[u])
sv = (lo[v], hi[v])
mask = np.zeros((RES, RES), dtype=bool)
depth = np.zeros((RES, RES), dtype=np.float32)

for i in range(RES):
    for j in range(RES):
        o = Vector((0.0, 0.0, 0.0))
        d = Vector((0.0, 0.0, 0.0))
        d[AXIS] = -1.0
        o[u] = su[0] + (i + 0.5) * (su[1] - su[0]) / RES
        o[v] = sv[0] + (j + 0.5) * (sv[1] - sv[0]) / RES
        o[AXIS] = hi[AXIS] + 1.0
        hit, loc, nrm, idx, obj, mw = scene.ray_cast(dg, o, d)
        if not hit:
            mask[j, i] = True
        else:
            depth[j, i] = hi[AXIS] - loc[AXIS]

np.save(OUTNPY, mask)
np.save(OUTNPY.replace(".npy", "_depth.npy"), depth)
print("MASK %s axis=%d res=%d open=%.1f%% span_u=%.2f span_v=%.2f" %
      (OUTNPY, AXIS, RES, mask.mean() * 100, su[1] - su[0], sv[1] - sv[0]))
np.save(OUTNPY.replace(".npy", "_span.npy"),
        np.array([su[0], su[1], sv[0], sv[1]], dtype=np.float64))
