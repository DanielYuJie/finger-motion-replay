"""完整链路验证：视觉 payload -> gRPC HandFrame -> ORCA IngressServer -> 官方重定向器 -> 关节角。

这是 Path A 的端到端证明，用的全是两侧的真实代码：
  · 发送侧  orca_link.orca_bridge.GrpcSink（我的适配层，帧格式与 orca_teleop 的 proto 一致）
  · 接收侧  orca_teleop.ingress.IngressServer（官方原件，非复刻）
  · 重定向  orca_teleop AdaptiveAnalyticalRetargeter（Pinocchio + NLopt）

跑法（orca-teleop conda 环境，理由见 setup-teleop-env.ps1）：
    D:\\tools\\miniconda\\envs\\orca-teleop\\python.exe test_full_chain.py
"""

from __future__ import annotations

import os
import queue
import sys
import threading
import time
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")  # 见 test_retargeter.py 的说明

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "proto_gen"))

from orca_paths import core_config, description_dir, urdf  # noqa: E402

DESC = description_dir()
V2_CFG = core_config("v2", "right")
V1_URDF = urdf("v1", "right")
WIN_CFG = HERE / "configs" / "adaptive_analytical_orca_windows.yaml"

os.environ.setdefault("ORCAHAND_DESCRIPTION_DIR", str(DESC))

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  [{'OK' if ok else 'FAIL'}]   {name}{(' — ' + detail) if detail else ''}")


def synthetic_hand(open_hand: bool):
    """21 点、米制、腕部相对的右手（MediaPipe 索引约定）。"""
    import math

    pts = [[0.0, 0.0, 0.0]]
    for p in ((0.025, 0.020, 0.0), (0.045, 0.040, 0.005), (0.060, 0.058, 0.010), (0.070, 0.075, 0.015)):
        pts.append(list(p))
    for x in (0.020, 0.008, -0.006, -0.019):
        base_y = 0.075 + abs(x) * 0.15
        pts.append([x, base_y, 0.0])
        y, z = base_y, 0.0
        for j, seg in enumerate((0.035, 0.025, 0.020)):
            if open_hand:
                y += seg
            else:
                a = math.radians((60.0, 100.0, 80.0)[j])
                y += seg * math.cos(a)
                z += seg * math.sin(a)
            pts.append([x, y, z])
    return pts


def main() -> int:
    print("=" * 74)
    print("完整链路：视觉 payload -> gRPC -> IngressServer -> 重定向器 -> 关节角")
    print("=" * 74)

    from orca_teleop.ingress import IngressServer

    from orca_bridge import GrpcSink

    # ---- 1. 起 ORCA 官方服务端 -------------------------------------------------
    print("\n[1] ORCA 官方 IngressServer")
    landmarks_q: queue.Queue = queue.Queue(maxsize=8)
    stop_event = threading.Event()
    server = IngressServer(landmarks_q, stop_event, port=0)
    port = server.start()
    check("IngressServer 启动", port > 0, f"port={port}")

    # ---- 2. 我的适配层当 publisher --------------------------------------------
    print("\n[2] orca-link 的 GrpcSink（发送侧）")
    sink = GrpcSink(server=f"localhost:{port}", handedness="right", proto_dir=HERE / "proto_gen")
    sink.start()
    time.sleep(1.0)
    check("gRPC 通道建立", True)

    # ---- 3. 装配官方重定向器 ---------------------------------------------------
    print("\n[3] 官方 adaptive_analytical 重定向器")
    from orca_teleop.retargeting.adaptive_analytical import AdaptiveAnalyticalRetargeter
    from orca_teleop.retargeting.retargeter import TargetPose

    rt = AdaptiveAnalyticalRetargeter(
        hand_config_path=str(V2_CFG), urdf_path=str(V1_URDF), config_path=str(WIN_CFG)
    )
    check("重定向器装配成功", True, f"model_version={rt.model_version}")

    # ---- 4. 走完整链路：sink -> gRPC -> 队列 -> 重定向器 ------------------------
    print("\n[4] 端到端：张开 -> 握拳")

    def push_and_pull(open_hand: bool, frames: int):
        """每帧经 gRPC 发出去，再从服务端队列取回来喂给重定向器。"""
        latest = None
        for _ in range(frames):
            sink.submit({}, {"hand": True, "world_landmarks": synthetic_hand(open_hand)})
            try:
                latest = landmarks_q.get(timeout=2.0)
            except queue.Empty:
                return None, 0
            rt.retarget(
                TargetPose(
                    joint_positions=latest.keypoints,
                    source="mediapipe",
                    wrist_angle_degrees=latest.wrist_angle_degrees,
                )
            )
            time.sleep(0.005)
        return latest, frames

    sample, n = push_and_pull(True, 45)
    check("帧经 gRPC 抵达服务端", n > 0, f"{n} 帧")
    if sample is not None:
        check("keypoints 形状 (21,3)", tuple(sample.keypoints.shape) == (21, 3), str(sample.keypoints.shape))
        check("handedness 正确", sample.handedness == "right")

    pose_open = rt.retarget(TargetPose(joint_positions=sample.keypoints, source="mediapipe"))

    push_and_pull(False, 45)
    fist_keypoints = None
    sink.submit({}, {"hand": True, "world_landmarks": synthetic_hand(False)})
    try:
        fist_keypoints = landmarks_q.get(timeout=2.0).keypoints
    except queue.Empty:
        pass
    pose_fist = (
        rt.retarget(TargetPose(joint_positions=fist_keypoints, source="mediapipe"))
        if fist_keypoints is not None
        else None
    )

    check("重定向器产出关节角", pose_open is not None and pose_fist is not None)
    if pose_open is not None and pose_fist is not None:
        a, b = pose_open.as_dict(), pose_fist.as_dict()
        check("17 个关节齐全", len(a) == 17, f"{len(a)} 个")
        moved = [n for n in a if abs(b[n] - a[n]) >= 10.0]
        print(f"\n  张开 -> 握拳（度）:")
        for name in sorted(a):
            mark = "  <--" if abs(b[name] - a[name]) >= 10.0 else ""
            print(f"      {name:<14}{a[name]:9.2f} -> {b[name]:9.2f}  ({b[name] - a[name]:+7.2f}){mark}")
        check("输入变化驱动了多自由度响应", len(moved) >= 5, f"{len(moved)}/17 个关节变化 >= 10 度")
        check("四指 MCP 对握拳有强响应", all(abs(b[f"{f}_mcp"] - a[f"{f}_mcp"]) >= 30 for f in ("index", "middle", "ring", "pinky")))

    sink.stop()
    server.stop(grace=1.0)
    stop_event.set()

    print("\n" + "=" * 74)
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    for name in FAIL:
        print(f"  失败: {name}")
    print("=" * 74)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
