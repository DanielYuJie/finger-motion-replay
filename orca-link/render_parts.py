"""把 ORCA 的打印件 STL 渲染成一张对照图（用 MuJoCo 的渲染器，非 matplotlib）。

MuJoCo 能直接吃 STL 网格（MJCF 的 <asset><mesh>），而且它的渲染器在我们这套环境里
已经验证可用（仿真截图就是它出的），比 matplotlib 画三角面快得多、也好看得多。

用法（在 orca-teleop conda 环境里）：
    python render_parts.py            # 读 docs/parts/*.stl，出 docs/orca-print-parts.png
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import mujoco
import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
PARTS = HERE / "docs" / "parts"
OUT = HERE / "docs" / "orca-print-parts.png"

W, H = 420, 330
COLS = 4
# ORCA 的 STL 单位是毫米，MuJoCo 默认按米解释，所以要缩到 1/1000
SCALE = "0.001 0.001 0.001"
# 相机距离 = 包围盒半对角线 × 这个系数。太小时长条形零件会被裁掉。
CAM_MARGIN = 4.2

# PIL 默认字体没有中文字形，会渲染成方块；显式加载系统中文字体
FONT_CANDIDATES = ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf")

LABELS = {
    "I-AP-R": "index 近节 I-AP-R",
    "I-PP": "index 中节 I-PP",
    "T-DP": "拇指远节 T-DP",
    "R-T-AP": "拇指近节 R-T-AP",
    "CORE-R": "腕骨核心 CORE-R",
    "CarpalsTeeth": "腕骨齿轮",
    "WristTeeth": "腕齿轮",
    "WristAdapter_Dynamixel": "腕适配器 (Dyn)",
    "ForeArmStructure_Dynamixel": "前臂结构 (Dyn)",
    "SpoolHolder": "线轴座（打印版）",
    "HullFront": "外壳前盖",
    "BaseSpool": "线轴 BaseSpool",
    "Ratchet": "棘轮（张紧用）",
    "SpoolTensioner": "张紧器",
    "PP-Skin_I-PP-Skin_Skin": "手指皮肤（TPU）",
}


def render_one(stl: Path) -> Image.Image:
    xml = f"""<mujoco>
  <compiler meshdir="{stl.parent.as_posix()}"/>
  <asset><mesh name="part" file="{stl.name}" scale="{SCALE}"/></asset>
  <worldbody><body name="b"><geom name="g" type="mesh" mesh="part"/></body></worldbody>
</mujoco>"""
    model = mujoco.MjModel.from_xml_string(xml)
    data = mujoco.MjData(model)

    # 用网格顶点算包围盒，据此摆相机，保证不同尺寸的件都填满画面
    verts = model.mesh_vert.reshape(-1, 3)
    lo, hi = verts.min(axis=0), verts.max(axis=0)
    center = (lo + hi) / 2.0
    radius = float(np.linalg.norm(hi - lo)) / 2.0

    cam = mujoco.MjvCamera()
    mujoco.mjv_defaultFreeCamera(model, cam)
    cam.lookat[:] = center
    cam.distance = radius * CAM_MARGIN
    cam.azimuth = 135.0
    cam.elevation = -22.0

    mujoco.mj_forward(model, data)
    renderer = mujoco.Renderer(model, height=H, width=W, max_geom=64)
    try:
        renderer.update_scene(data, camera=cam)
        img = renderer.render()
    finally:
        renderer.close()
    return Image.fromarray(np.asarray(img, dtype=np.uint8))


def load_font(size: int = 17):
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def main() -> int:
    files = sorted(PARTS.glob("*.stl"))
    if not files:
        print(f"没有 STL：{PARTS}")
        return 1

    font = load_font()
    tiles: list[tuple[str, Image.Image]] = []
    for stl in files:
        label = LABELS.get(stl.stem, stl.stem)
        try:
            tiles.append((label, render_one(stl)))
            print(f"  OK   {stl.name}")
        except Exception as exc:
            print(f"  FAIL {stl.name}: {type(exc).__name__}: {exc}")

    if not tiles:
        return 1

    rows = (len(tiles) + COLS - 1) // COLS
    pad, bar = 6, 28
    sheet = Image.new(
        "RGB", (COLS * (W + pad) + pad, rows * (H + bar + pad) + pad), (20, 24, 30)
    )
    draw = ImageDraw.Draw(sheet)
    for i, (label, tile) in enumerate(tiles):
        r, c = divmod(i, COLS)
        x = pad + c * (W + pad)
        y = pad + r * (H + bar + pad)
        sheet.paste(tile, (x, y + bar))
        draw.text((x + 8, y + 5), label, fill=(228, 238, 248), font=font)

    sheet.save(OUT)
    print(f"\n已生成 {OUT}  {sheet.size}  {len(tiles)} 个零件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
