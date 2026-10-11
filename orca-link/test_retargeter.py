"""真跑官方重定向器：验证它能否在 Windows 上装配并产出 ORCA 关节角。

背景：orca_teleop 的 adaptive_analytical 后端按 `robot_frames_by_version` 解析 URDF 帧，
v2 那块要的是 right_index_mcp / right_index_pip 这类语义名。而 orcahand_description 里
v2 的 URDF/MJCF 用的是 CAD 名（I-AP-R_d95d02d1 / right_i-mcp_actuator），v1 才是语义名。
所以本脚本 v2、v1 各试一次，把真实结果打出来，而不是靠读代码猜。

跑法（必须在 orca-teleop conda 环境里）：
    D:\\tools\\miniconda\\envs\\orca-teleop\\python.exe test_retargeter.py
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from orca_paths import core_models_dir, description_dir  # noqa: E402

DESC = description_dir()
CORE = core_models_dir()

os.environ.setdefault("ORCAHAND_DESCRIPTION_DIR", str(DESC))

# conda 提供的 pinocchio/nlopt 会带 libomp.dll，torch 自带 libiomp5md.dll，
# 同一进程里两个 OpenMP 运行时初始化就会 OMP Error #15 并终止。这是 conda+pip 混装的
# 已知代价，官方给的开关就是下面这个。必须在 import torch/nlopt/pinocchio 之前设好。
# 想避免这个开关：把 nlopt 换成 pip 轮子、并让 pinocchio 不要拉 mkl（见 setup-teleop-env.ps1）。
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")


def synthetic_hand(open_hand: bool) -> "list[list[float]]":
    """造一只 21 点、米制、腕部相对的右手（MediaPipe 索引约定）。

    拇指 0/1-4，四指各 4 点。张开时手指沿 +y 伸直，握拳时指节分两段折回掌心。
    """
    import math

    pts: list[list[float]] = [[0.0, 0.0, 0.0]]  # 0 腕
    # 拇指：CMC 从腕侧伸出，MCP/IP/TIP 向前
    thumb = [(0.025, 0.020, 0.0), (0.045, 0.040, 0.005), (0.060, 0.058, 0.010), (0.070, 0.075, 0.015)]
    pts += [list(p) for p in thumb]
    # 四指：MCP 在掌骨末端排开，之后两节指骨
    mcp_x = [0.020, 0.008, -0.006, -0.019]
    seg = [0.035, 0.025, 0.020]  # 近节/中节/远节长度
    for i, x in enumerate(mcp_x):
        base_y = 0.075 + abs(x) * 0.15
        mcp = (x, base_y, 0.0)
        pts.append(list(mcp))
        y, z = base_y, 0.0
        for j, length in enumerate(seg):
            if open_hand:
                y += length
            else:
                # 握拳：近节向前、中节折回、远节再折回
                angle = math.radians([60.0, 100.0, 80.0][j])
                y += length * math.cos(angle)
                z += length * math.sin(angle)
            pts.append([x, y, z])
    return pts


def try_backend(version: str, urdf_override: Path | None = None, config_override: Path | None = None) -> None:
    label = version if urdf_override is None else f"{version} 配置 + {urdf_override.name}（显式指定）"
    if config_override is not None:
        label += f" + {config_override.name}"
    print(f"\n{'=' * 70}\n尝试 {label}\n{'=' * 70}")
    cfg = CORE / version / f"orcahand-{'right'}" / "config.yaml"
    if not cfg.exists():
        print(f"  配置不存在: {cfg}")
        return

    from orca_teleop.retargeting.adaptive_analytical import AdaptiveAnalyticalRetargeter
    from orca_teleop.retargeting.retargeter import TargetPose

    try:
        rt = AdaptiveAnalyticalRetargeter(
            hand_config_path=str(cfg),
            urdf_path=str(urdf_override) if urdf_override else None,
            config_path=str(config_override) if config_override else None,
        )
    except Exception as exc:
        print(f"  [装配失败] {type(exc).__name__}: {exc}")
        return

    print(f"  [装配成功] urdf = {rt.urdf_path}")
    print(f"  hand_type={rt.hand_type}  model_version={rt.model_version}")

    def feed(open_hand: bool, frames: int) -> None:
        for _ in range(frames):
            rt.retarget(
                TargetPose(
                    joint_positions=synthetic_hand(open_hand=open_hand),
                    source="mediapipe",
                    wrist_angle_degrees=0.0,
                )
            )

    # 前 30 帧是自动尺度标定期，retarget() 返回 None（机械手保持 init_joints 姿态）。
    feed(open_hand=True, frames=45)
    pose_open = rt.retarget(
        TargetPose(joint_positions=synthetic_hand(open_hand=True), source="mediapipe")
    )
    feed(open_hand=False, frames=45)
    pose_fist = rt.retarget(
        TargetPose(joint_positions=synthetic_hand(open_hand=False), source="mediapipe")
    )

    if pose_open is None or pose_fist is None:
        print("  [无输出] 标定后仍返回 None")
        return

    a = pose_open.as_dict()
    b = pose_fist.as_dict()
    print(f"  [成功] 收到 {len(a)} 个关节角（度）。张开 -> 握拳：")
    print(f"      {'关节':<14}{'张开':>9}{'握拳':>9}{'变化':>9}")
    for name in sorted(a):
        delta = b[name] - a[name]
        flag = "  <-- 明显变化" if abs(delta) >= 10.0 else ""
        print(f"      {name:<14}{a[name]:9.2f}{b[name]:9.2f}{delta:+9.2f}{flag}")

    moved = [n for n in a if abs(b[n] - a[n]) >= 10.0]
    print(f"  响应输入的自由度: {len(moved)}/{len(a)}（变化 >= 10 度）")
    order = list(a.keys())
    print(f"  关节顺序（供 set_joint_positions 的 ndarray 用）: {order}")


def main() -> int:
    print("ORCAHAND_DESCRIPTION_DIR =", os.environ["ORCAHAND_DESCRIPTION_DIR"])
    import numpy, torch, pinocchio, nlopt

    print("numpy", numpy.__version__, "| torch", torch.__version__, "| pinocchio", pinocchio.__version__, "| nlopt", nlopt.__version__)
    v1_urdf = DESC / "v1" / "models" / "urdf" / "orcahand_right.urdf"
    win_cfg = HERE / "configs" / "adaptive_analytical_orca_windows.yaml"
    # 顺序即结论：先证伪 v2 资源搭配，再验证「v2 配置 + v1 URDF + 修正 alias」这个可用组合。
    try_backend("v2")
    try_backend("v1")
    if v1_urdf.exists():
        try_backend("v2", urdf_override=v1_urdf)
        if win_cfg.exists():
            try_backend("v2", urdf_override=v1_urdf, config_override=win_cfg)
        else:
            print(f"\n缺少 {win_cfg}")
    else:
        print(f"\n缺少 {v1_urdf}，无法验证组合方案")
    return 0


if __name__ == "__main__":
    sys.exit(main())
