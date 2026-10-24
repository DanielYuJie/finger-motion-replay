"""用 MuJoCo 渲染 ORCA 右手的 3D 演示：360° 转台 GIF + 高分辨率主图 + 拼图。

为什么不用 Blender：本机没装（winget 可装），而 MuJoCo 的离屏渲染已经可用——
场景 XML 里 37 个网格、31 个几何、17 个关节都是现成的装配体，直接转台最省事。
需要更产品化的材质/景深时再把 GLB 导给 Blender（本脚本同时导出 GLB）。

坑：orca_sim 的 scene XML 没写 <visual><global offwidth/offheight>，
默认离屏帧缓冲是 640×480，直接要更大分辨率会报
"Image width > framebuffer width"。这里在创建 Renderer 之前改 model.vis.global_。

用法：
    python render_turntable.py                 # 默认 36 帧、800x800
    python render_turntable.py --frames 48 --size 1000
"""

from __future__ import annotations

import argparse
import os

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import mujoco
import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
SCENE = os.path.join(
    os.path.dirname(HERE), "orca-ecosystem", "orca_sim", "src", "orca_sim",
    "scenes", "v2", "scene_right.xml",
)
# 也允许更浅层级的检出
SCENE_FALLBACKS = [
    r"D:\DSPersonal Project Area\orca-ecosystem\orca_sim\src\orca_sim\scenes\v2\scene_right.xml",
]
OUT_DIR = os.path.join(HERE, "docs")



def find_scene() -> str:
    for p in [SCENE, *SCENE_FALLBACKS]:
        if os.path.exists(p):
            return p
    raise FileNotFoundError("找不到 scene_right.xml，请检查 orca_sim 检出位置")


def apply_pose(model: mujoco.MjModel, data: mujoco.MjData, frac: float = 0.35) -> None:
    """按每个关节自身行程等比例屈曲（frac=0 全开，1 全屈）。

    不用固定弧度是因为各关节行程差很多（mcp 到 1.75 rad、abd 只有 ±0.5），
    统一给一个弧度会让手指掐成一团"鹰爪"。
    """
    for i in range(model.njnt):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, i) or ""
        adr = int(model.jnt_qposadr[i])
        lo, hi = (float(v) for v in model.jnt_range[i])
        if name.endswith("-abd") or name.endswith("wrist"):
            val = 0.0
        else:
            val = lo + frac * (hi - lo)
        data.qpos[adr] = float(np.clip(val, lo, hi))
    mujoco.mj_forward(model, data)


def scene_bounds(model: mujoco.MjModel, data: mujoco.MjData):
    """用网格真实顶点算世界坐标 AABB，得到准确的中心和半径。

    踩过两个坑：
    1) 地面平面必须排除，否则半径被地板撑到几十厘米，相机会退得极远。
    2) 不能用 geom_xpos + geom_rbound —— geom_xpos 是几何坐标系原点，
       和网格质心可能差很远，包围球会被虚大（实测 0.269 m，实际手只有 ~0.18 m）。
    """
    lo = np.full(3, 1e9)
    hi = np.full(3, -1e9)
    for g in range(model.ngeom):
        gtype = model.geom_type[g]
        if gtype == mujoco.mjtGeom.mjGEOM_PLANE:
            continue
        if gtype == mujoco.mjtGeom.mjGEOM_MESH:
            mid = int(model.geom_dataid[g])
            if mid < 0:
                continue
            adr = int(model.mesh_vertadr[mid])
            num = int(model.mesh_vertnum[mid])
            verts = np.asarray(model.mesh_vert[adr:adr + num])       # 局部坐标
            rot = np.asarray(data.geom_xmat[g]).reshape(3, 3)        # 世界
            world = verts @ rot.T + np.asarray(data.geom_xpos[g])
            lo = np.minimum(lo, world.min(axis=0))
            hi = np.maximum(hi, world.max(axis=0))
        else:
            c = np.asarray(data.geom_xpos[g])
            r = float(model.geom_rbound[g])
            lo = np.minimum(lo, c - r)
            hi = np.maximum(hi, c + r)
    center = (lo + hi) / 2.0
    radius = float(np.linalg.norm(hi - lo) / 2.0)
    return center, radius


def render(model, data, cam, width, height, renderer) -> Image.Image:
    renderer.update_scene(data, camera=cam)
    return Image.fromarray(np.asarray(renderer.render(), dtype=np.uint8))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=36)
    ap.add_argument("--size", type=int, default=800)
    ap.add_argument("--hero", type=int, default=1400)
    ap.add_argument("--elev", type=float, default=-14.0)
    ap.add_argument("--frac", type=float, default=0.35, help="屈曲比例 0=全开 1=全屈")
    ap.add_argument("--anim", type=int, default=60, help="开合动画帧数，0 关闭")
    args = ap.parse_args()

    scene = find_scene()
    print(f"  场景: {scene}")
    model = mujoco.MjModel.from_xml_path(scene)
    data = mujoco.MjData(model)

    # 抬高离屏帧缓冲，否则超过 640x480 会报错。注意要覆盖【宽度】，
    # hero 图是 1.25 倍的横图，所以 max 里要算上 hero*1.25。
    need = max(args.size, args.hero, int(args.hero * 1.25))
    model.vis.global_.offwidth = need
    model.vis.global_.offheight = need

    apply_pose(model, data, args.frac)
    center, radius = scene_bounds(model, data)
    print(f"  装配体: nbody={model.nbody} ngeom={model.ngeom} njnt={model.njnt} "
          f"中心={np.round(center, 3)} 半径={radius:.3f} m")

    os.makedirs(OUT_DIR, exist_ok=True)

    # ---- 高分辨率主图 ----
    hero_cam = mujoco.MjvCamera()
    mujoco.mjv_defaultFreeCamera(model, hero_cam)
    hero_cam.lookat[:] = center
    hero_cam.distance = radius * 2.75
    hero_cam.azimuth, hero_cam.elevation = 320.0, args.elev
    r = mujoco.Renderer(model, height=args.hero, width=int(args.hero * 1.25),
                        max_geom=4096)
    hero = render(model, data, hero_cam, 0, 0, r)
    r.close()
    hero_path = os.path.join(OUT_DIR, "orca-blender-hero.png")
    hero.save(hero_path)
    print(f"  主图 {os.path.basename(hero_path)} {hero.size} "
          f"{os.path.getsize(hero_path)/1024:.0f} KB")

    # ---- 转台序列 ----
    r = mujoco.Renderer(model, height=args.size, width=args.size, max_geom=4096)
    cam = mujoco.MjvCamera()
    mujoco.mjv_defaultFreeCamera(model, cam)
    cam.lookat[:] = center
    cam.distance = radius * 2.75
    cam.elevation = args.elev
    frames = []
    for k in range(args.frames):
        cam.azimuth = 360.0 * k / args.frames
        frames.append(render(model, data, cam, args.size, args.size, r))
    r.close()
    print(f"  转台 {len(frames)} 帧 @ {args.size}px")

    # ---- 拼图（首行 6 帧）----
    cols = 6
    rows = (len(frames) + cols - 1) // cols
    small = args.size // 2
    pad = 4
    strip = Image.new("RGB", (cols * (small + pad) + pad, rows * (small + pad) + pad),
                      (18, 22, 28))
    for i, fr in enumerate(frames):
        rr, cc = divmod(i, cols)
        strip.paste(fr.resize((small, small), Image.LANCZOS),
                    (pad + cc * (small + pad), pad + rr * (small + pad)))
    strip_path = os.path.join(OUT_DIR, "orca-blender-turntable-strip.png")
    strip.save(strip_path)
    print(f"  拼图 {os.path.basename(strip_path)} {strip.size}")

    # ---- GIF ----
    gif_path = os.path.join(OUT_DIR, "orca-blender-turntable.gif")
    frames[0].save(gif_path, save_all=True, append_images=frames[1:],
                   duration=90, loop=0, optimize=True)
    print(f"  GIF  {os.path.basename(gif_path)} {frames[0].size} "
          f"{os.path.getsize(gif_path)/1024:.0f} KB")

    # ---- 开合动画：全开 -> 全屈 -> 全开 ----
    if args.anim > 0:
        cam.azimuth = 320.0
        # 单开一个 Renderer：转台那个已在上面 close() 过，复用会报
        # "render cannot be called after close."
        av = mujoco.Renderer(model, height=args.size, width=args.size, max_geom=4096)
        seq = []
        n = args.anim
        for k in range(n):
            ph = k / (n - 1)
            tri = 1.0 - abs(2.0 * ph - 1.0)          # 0 -> 1 -> 0 三角波
            apply_pose(model, data, 0.02 + 0.93 * tri)
            av.update_scene(data, camera=cam)
            seq.append(Image.fromarray(np.asarray(av.render(), dtype=np.uint8)))
        av.close()
        anim_path = os.path.join(OUT_DIR, "orca-blender-pose-anim.gif")
        seq[0].save(anim_path, save_all=True, append_images=seq[1:],
                    duration=70, loop=0, optimize=True)
        print(f"  开合动画 {os.path.basename(anim_path)} {seq[0].size} "
              f"{os.path.getsize(anim_path)/1024:.0f} KB ({n} 帧)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
