"""orca-link 验证：映射正确性 + 真机代码路径 + MockOrcaHand 端到端。

跑法（必须用本目录的 .venv，Python 3.12 / protobuf 4.25）：
    .venv\\Scripts\\python.exe verify.py

三段验证：
  1. 映射：ROM 夹取、拇指键语义、flex 兜底、限速、顺序对齐
  2. gRPC：把帧推给 orca_teleop 真实的 IngressServer（加载其 server.py 原件），
     确认服务端收到的 HandLandmarks 是 (21,3)、数值逐点一致
  3. 端到端：走 OrcaSink + MockOrcaHand，确认命令值真的落到关节上
"""

from __future__ import annotations

import importlib.util
import json
import queue
import sys
import threading
import time
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from orca_paths import core_config, teleop_src  # noqa: E402

# 用上游 orcahand/orca_core：N-B-Studio 的 fork 落后 35 个提交且 scs225 支持加载不了。
# 该 config.yaml 在 fork 与上游逐字节相同（sha256 419e7669…），所以映射结论不变。
ORCA_CORE_CFG = core_config("v2", "right")
TELEOP_SRC = teleop_src()

sys.path.insert(0, str(HERE / "proto_gen"))

from orca_hand_map import ABDUCTION_JOINTS, OrcaJointMap, Tuning  # noqa: E402

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASS.append(name)
        print(f"  [OK]   {name}{(' — ' + detail) if detail else ''}")
    else:
        FAIL.append(name)
        print(f"  [FAIL] {name}{(' — ' + detail) if detail else ''}")


def pose(flexions: dict[str, tuple[float, float, float]] | None = None, hand: bool = True) -> dict:
    """造一帧与 app.js pushBridge 同形的 payload。"""
    payload = {"hand": hand, "source": "webcam-mediapipe", "fingers": {}}
    base = {"thumb": (8.0, 18.0, 31.0), "index": (14.0, 22.0, 19.0),
            "middle": (13.0, 21.0, 18.0), "ring": (12.0, 20.0, 17.0), "pinky": (11.0, 18.0, 15.0)}
    for finger, triple in (flexions or base).items():
        payload["fingers"][finger] = {
            "flex": sum(triple) / 2.7, "mcp": triple[0], "pip": triple[1], "dip": triple[2],
        }
    return payload


# ---------------------------------------------------------------------------
# 1. 映射
# ---------------------------------------------------------------------------

def verify_mapping() -> OrcaJointMap:
    print("\n[1] 映射")
    mapper = OrcaJointMap(hand_config_path=ORCA_CORE_CFG, tuning=Tuning())
    expected = ("wrist", "thumb_cmc", "thumb_abd", "thumb_mcp", "thumb_dip", "index_abd",
                "index_mcp", "index_pip", "middle_abd", "middle_mcp", "middle_pip",
                "ring_abd", "ring_mcp", "ring_pip", "pinky_abd", "pinky_mcp", "pinky_pip")
    check("关节顺序取自或对齐 ORCA config.yaml", tuple(mapper.joint_ids) == expected, f"{len(mapper.joint_ids)} 个关节")
    check("ROM 与中立位来自 config.yaml", mapper.source.endswith("config.yaml"))

    neutral = mapper.neutral_pose()
    check("hand=false 回中立位", mapper.from_vision_payload({"hand": False}) == neutral)
    check("空 payload 回中立位", mapper.from_vision_payload(None) == neutral)

    # 极值输入不得越界，且顺序数组长度正确
    worst = {"thumb": (180.0, 180.0, 180.0), "index": (180.0, 180.0, 180.0),
             "middle": (180.0, 180.0, 180.0), "ring": (180.0, 180.0, 180.0),
             "pinky": (180.0, 180.0, 180.0)}
    extreme = mapper.from_vision_payload(pose(worst))
    in_rom = all(mapper.roms[j][0] - 1e-9 <= extreme[j] <= mapper.roms[j][1] + 1e-9 for j in mapper.joint_ids)
    check("屈曲 180° 输入不越 ROM", in_rom)
    check("顺序数组与 joint_ids 对齐", len(mapper.to_ordered_array(extreme)) == len(mapper.joint_ids))

    zero = mapper.from_vision_payload(pose({f: (0.0, 0.0, 0.0) for f in ("thumb", "index", "middle", "ring", "pinky")}))
    check("全伸直 -> 各关节停在中立位", zero["index_mcp"] == neutral["index_mcp"] and zero["index_pip"] == neutral["index_pip"])

    # 单调性：屈曲增大，目标不减
    monotonic = True
    for finger, joint in (("index", "index_mcp"), ("middle", "middle_pip"), ("thumb", "thumb_cmc")):
        prev = -1e9
        for f in (0.0, 20.0, 40.0, 60.0, 80.0, 100.0):
            value = mapper.from_vision_payload(pose({finger: (f, f, f)}))[joint]
            if value < prev - 1e-9:
                monotonic = False
            prev = value
    check("屈曲角增大时目标单调不减", monotonic)

    # 拇指键语义：payload 的 mcp/pip/dip 实际是 CMC/MCP/IP
    thumb = mapper.from_vision_payload(pose({"thumb": (30.0, 0.0, 0.0)}))
    check("拇指 mcp 键驱动 thumb_cmc（不是 thumb_mcp）",
          thumb["thumb_cmc"] > neutral["thumb_cmc"] and abs(thumb["thumb_mcp"] - neutral["thumb_mcp"]) < 1e-9)
    thumb_ip = mapper.from_vision_payload(pose({"thumb": (0.0, 0.0, 50.0)}))
    check("拇指 dip 键驱动 thumb_dip", thumb_ip["thumb_dip"] > neutral["thumb_dip"])

    # 四指的 DIP 在 ORCA v2 上没有对应关节，必须被丢弃而不是误写
    dip_only = mapper.from_vision_payload(pose({"index": (0.0, 0.0, 90.0)}))
    check("四指 DIP 无对应关节、被忽略", abs(dip_only["index_pip"] - neutral["index_pip"]) < 1e-9)

    # 无视觉输入的关节保持策略
    abd_untouched = all(abs(extreme[ABDUCTION_JOINTS[f]] - neutral[ABDUCTION_JOINTS[f]]) < 1e-9
                        for f in ABDUCTION_JOINTS)
    check("外展关节按 neutral 策略保持", abd_untouched)
    check("腕按 neutral 策略保持", abs(extreme["wrist"] - neutral["wrist"]) < 1e-9)

    # flex 兜底：只给 flex 也要有输出
    flex_only = mapper.from_vision_payload({"hand": True, "fingers": {f: {"flex": 100.0} for f in ("thumb", "index", "middle", "ring", "pinky")}})
    check("仅 flex 时兜底到 ROM 上界", abs(flex_only["index_mcp"] - mapper.roms["index_mcp"][1]) < 1e-6)

    # 限速：默认开启 25°/帧，显式置 None 时放开
    limited = mapper.limit_step(extreme, neutral)
    max_delta = max(abs(limited[j] - neutral[j]) for j in mapper.joint_ids)
    check("默认限速把单帧变化压到 25° 内", max_delta <= 25.0 + 1e-9, f"实测最大 {max_delta:.1f}°")
    unlimited_map = OrcaJointMap(hand_config_path=ORCA_CORE_CFG, tuning=Tuning(max_step_deg=None))
    free = unlimited_map.limit_step(extreme, neutral)
    check("max_step_deg=null 时不限速", free == {j: extreme[j] for j in unlimited_map.joint_ids})

    # 外展估计（实验性）不得越界
    landmarks = [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0],
                 [0.02, 0.05, 0.0], [0.02, 0.08, 0.0], [0.02, 0.10, 0.0], [0.02, 0.11, 0.0],
                 [0.0, 0.05, 0.0], [0.0, 0.08, 0.0], [0.0, 0.10, 0.0], [0.0, 0.11, 0.0],
                 [-0.02, 0.05, 0.0], [-0.02, 0.08, 0.0], [-0.02, 0.10, 0.0], [-0.02, 0.11, 0.0],
                 [-0.04, 0.05, 0.0], [-0.04, 0.08, 0.0], [-0.04, 0.10, 0.0], [-0.04, 0.11, 0.0]]
    abd = mapper.abduction_from_landmarks(landmarks)
    ok = all(mapper.roms[j][0] - 1e-9 <= v <= mapper.roms[j][1] + 1e-9 for j, v in abd.items())
    check("外展估计（实验性）落在 ROM 内", ok and len(abd) >= 1, f"得到 {len(abd)} 个关节")
    return mapper


# ---------------------------------------------------------------------------
# 2. gRPC：对 ORCA 真实的 IngressServer
# ---------------------------------------------------------------------------

def load_real_ingress_server():
    """不执行 orca_teleop/__init__.py（它拖 torch），只加载 ingress.server 原件。"""
    import hand_stream_pb2
    import hand_stream_pb2_grpc

    pkg = types.ModuleType("orca_teleop")
    pkg.__path__ = [str(TELEOP_SRC)]
    ingress = types.ModuleType("orca_teleop.ingress")
    ingress.__path__ = [str(TELEOP_SRC / "ingress")]
    ingress.hand_stream_pb2 = hand_stream_pb2
    ingress.hand_stream_pb2_grpc = hand_stream_pb2_grpc
    sys.modules["orca_teleop"] = pkg
    sys.modules["orca_teleop.ingress"] = ingress

    def load(mod_name: str, path: Path):
        spec = importlib.util.spec_from_file_location(mod_name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = module
        spec.loader.exec_module(module)
        return module

    constants = load("orca_teleop.constants", TELEOP_SRC / "constants.py")
    pkg.constants = constants
    server = load("orca_teleop.ingress.server", TELEOP_SRC / "ingress" / "server.py")
    return server


def verify_grpc() -> None:
    print("\n[2] gRPC 回环（对 orca_teleop 真实 IngressServer）")
    try:
        ingress_server = load_real_ingress_server()
    except Exception as exc:
        check("加载 orca_teleop ingress.server", False, f"{type(exc).__name__}: {exc}")
        return
    check("加载 orca_teleop ingress.server 原件", True, "绕开了会拖 torch 的包 __init__")

    from orca_bridge import GrpcSink

    landmarks_q: queue.Queue = queue.Queue(maxsize=4)
    stop_event = threading.Event()
    server = ingress_server.IngressServer(landmarks_q, stop_event, port=0)
    port = server.start()
    check("IngressServer 监听", port > 0, f"port={port}")

    sink = GrpcSink(server=f"localhost:{port}", handedness="right", proto_dir=HERE / "proto_gen")
    sink.start()
    time.sleep(1.0)  # 建流

    world = [[i * 0.001, i * 0.002, i * 0.003] for i in range(21)]
    sink.submit({}, {"hand": True, "world_landmarks": world})

    received = None
    deadline = time.time() + 5.0
    while time.time() < deadline:
        try:
            received = landmarks_q.get(timeout=0.5)
            break
        except queue.Empty:
            continue

    check("服务端收到帧", received is not None)
    if received is not None:
        check("keypoints 形状为 (21,3)", tuple(received.keypoints.shape) == (21, 3), str(received.keypoints.shape))
        expected = [[i * 0.001, i * 0.002, i * 0.003] for i in range(21)]
        max_err = max(abs(float(received.keypoints[i][k]) - expected[i][k]) for i in range(21) for k in range(3))
        check("63 个浮点逐点一致（float32 容差内）", max_err < 1e-6, f"最大误差 {max_err:.2e}")
        check("handedness 传递正确", received.handedness == "right")
        check("timestamp_ns 有值", received.timestamp_ns > 0)

    sink.stop()
    server.stop()
    stop_event.set()


# ---------------------------------------------------------------------------
# 3. 端到端：OrcaSink + MockOrcaHand
# ---------------------------------------------------------------------------

def verify_mock_hand() -> None:
    print("\n[3] 端到端：OrcaSink + MockOrcaHand")
    from orca_bridge import OrcaSink

    mapper = OrcaJointMap(hand_config_path=ORCA_CORE_CFG, tuning=Tuning(max_step_deg=None))
    try:
        sink = OrcaSink(joint_ids=mapper.joint_ids, hand_config=str(ORCA_CORE_CFG), mock=True, hz=50.0)
        sink.start()
    except Exception as exc:
        check("构造并连接 MockOrcaHand", False, f"{type(exc).__name__}: {exc}")
        return
    check("构造并连接 MockOrcaHand", True, "mock=True，未触碰串口")

    target = mapper.from_vision_payload(pose({"index": (60.0, 70.0, 40.0), "middle": (55.0, 65.0, 35.0)}))
    sink.submit(target, {"hand": True})
    time.sleep(1.0)

    status = sink.status()
    measured = status.get("measured")
    check("MockOrcaHand 能读回关节位置", isinstance(measured, dict), status.get("measured_error", ""))
    if isinstance(measured, dict):
        err = max(abs(float(measured[j]) - target[j]) for j in mapper.joint_ids)
        check("命令值落到关节上（误差 < 1°）", err < 1.0, f"最大误差 {err:.3f}°")
        check("index_mcp 确实被驱动到 60° 附近", abs(float(measured["index_mcp"]) - target["index_mcp"]) < 1.0,
              f"measured={float(measured['index_mcp']):.2f} target={target['index_mcp']:.2f}")
    sink.stop()


def main() -> int:
    print("=" * 74)
    print("orca-link 验证")
    print("=" * 74)
    verify_mapping()
    verify_grpc()
    verify_mock_hand()
    print("\n" + "=" * 74)
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        for name in FAIL:
            print(f"  失败: {name}")
    print("=" * 74)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
