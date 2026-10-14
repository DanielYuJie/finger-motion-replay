"""orca-link：把 finger-motion-replay 的视觉采集接到 ORCA Hand。

接收你现有视觉主端会 POST 的那份 JSON（fingers.<name>.{flex,mcp,pip,dip}），
额外可选地带 world_landmarks；映射成 ORCA 的 17 个关节角，再交给某个 sink：

  print  只打印，用来对表
  orca   驱动 orca_core（mock=True 时不碰硬件，纯内存跑）
  grpc   作为 publisher 走 orca_teleop 的 ingress，把世界坐标 landmark 推给
         机器人侧的 IngressServer，由官方重定向器求解关节角

端口默认 8766：你自己的 MC 桥接占着 8765。
"""

from __future__ import annotations

import argparse
import json
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

import yaml

from orca_hand_map import OrcaJointMap, Tuning

FINGER_ORDER = ("thumb", "index", "middle", "ring", "pinky")


# ---------------------------------------------------------------------------
# sinks
# ---------------------------------------------------------------------------

class Sink:
    """关节目标的下游。submit 必须非阻塞，指挥在各自线程里做。"""

    name = "base"

    def start(self) -> None:
        pass

    def submit(self, joint_target: Mapping[str, float], payload: Mapping[str, Any] | None) -> None:
        pass

    def stop(self) -> None:
        pass


class PrintSink(Sink):
    """按 command_hz 打印目标，剩下的时间不做事。"""

    name = "print"

    def __init__(self, joint_ids: tuple[str, ...], hz: float = 2.0) -> None:
        self._joint_ids = joint_ids
        self._period = 1.0 / max(hz, 0.1)
        self._last = 0.0

    def submit(self, joint_target, payload) -> None:
        now = time.time()
        if now - self._last < self._period:
            return
        self._last = now
        summary = " ".join(f"{j}={joint_target[j]:6.1f}" for j in self._joint_ids)
        print(f"[orca-link] {summary}")


class OrcaSink(Sink):
    """驱动 orca_core 的 hand 对象。

    mock=True 时是 MockOrcaHand：不探测串口、不发串口包，关节状态在内存里，
    可以拿来先把映射和限速跑通，再插实体手。
    """

    name = "orca"

    def __init__(
        self,
        joint_ids: tuple[str, ...],
        hand_config: str | None,
        mock: bool,
        hz: float,
        connect_interactive: bool = False,
    ) -> None:
        from orca_core import load_hand

        self._joint_ids = joint_ids
        config_path = str(hand_config) if hand_config and Path(hand_config).exists() else None
        self._hand = load_hand(config_path=config_path, mock=mock)
        self._interactive = connect_interactive
        self._period = 1.0 / max(hz, 0.1)
        self._queue: queue.Queue = queue.Queue(maxsize=1)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_error: str | None = None

    def start(self) -> None:
        self._connect()
        self._thread = threading.Thread(target=self._loop, name="orca-command", daemon=True)
        self._thread.start()

    def _connect(self) -> None:
        try:
            self._hand.connect(interactive=self._interactive)
        except TypeError:
            self._hand.connect()
        self._hand.init_joints()

    def submit(self, joint_target, payload) -> None:
        try:
            self._queue.put_nowait(dict(joint_target))
        except queue.Full:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(dict(joint_target))
            except queue.Full:
                pass

    def _loop(self) -> None:
        next_tick = time.time()
        while not self._stop.is_set():
            try:
                target = self._queue.get(timeout=self._period)
            except queue.Empty:
                continue
            try:
                self._hand.set_joint_positions(
                    {j: float(target[j]) for j in self._joint_ids}, num_steps=1
                )
                self._last_error = None
            except Exception as exc:  # 硬件异常不该打死指挥线程
                self._last_error = f"{type(exc).__name__}: {exc}"

            next_tick += self._period
            sleep_for = next_tick - time.time()
            if sleep_for > 0:
                time.sleep(sleep_for)
            else:
                next_tick = time.time()

    def status(self) -> dict[str, Any]:
        out: dict[str, Any] = {"sink": self.name, "last_error": self._last_error}
        try:
            measured = self._hand.get_joint_position().as_dict()
            out["measured"] = {j: measured.get(j) for j in self._joint_ids}
        except Exception as exc:
            out["measured_error"] = f"{type(exc).__name__}: {exc}"
        return out

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        try:
            self._hand.disconnect()
        except Exception:
            pass


class GrpcSink(Sink):
    """作为 orca_teleop 的 publisher，把 world landmark 推给 IngressServer。

    只在 payload 带 world_landmarks 时有内容可发：ORCA 的 HandFrame 要的是
    21×3、米制、腕部相对的世界坐标（MediaPipe 的 worldLandmarks），不是归一化
    图像坐标。
    """

    name = "grpc"

    def __init__(self, server: str, handedness: str, proto_dir: Path) -> None:
        import importlib
        import sys

        import grpc

        # 优先用 orca_teleop 自带的桩：它一旦被 import 就把 orca_teleop.HandFrame
        # 注册进 protobuf 的 descriptor pool，再用本地生成的同名副本会报
        # "duplicate symbol"。本地副本只在没装 orca_teleop 时兜底（例如 orca-link 的 venv）。
        pb2 = pb2_grpc = None
        try:
            pb2 = importlib.import_module("orca_teleop.ingress.hand_stream_pb2")
            pb2_grpc = importlib.import_module("orca_teleop.ingress.hand_stream_pb2_grpc")
            self.proto_source = "orca_teleop"
        except Exception:
            if str(proto_dir) not in sys.path:
                sys.path.insert(0, str(proto_dir))
            pb2 = importlib.import_module("hand_stream_pb2")
            pb2_grpc = importlib.import_module("hand_stream_pb2_grpc")
            self.proto_source = str(proto_dir)

        self._grpc = grpc
        self._pb2 = pb2
        self._server = server
        self._handedness = handedness.lower()
        self._channel = grpc.insecure_channel(server)
        self._stub = pb2_grpc.HandStreamStub(self._channel)
        self._queue: queue.Queue = queue.Queue(maxsize=4)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._sent = 0
        self._dropped = 0

    def _frames(self):
        while not self._stop.is_set():
            try:
                keypoints = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            yield self._pb2.HandFrame(
                keypoints=keypoints,
                handedness=self._handedness,
                timestamp_ns=time.time_ns(),
            )

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="orca-grpc", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            self._stub.StreamHandFrames(self._frames())
        except Exception:
            pass

    def submit(self, joint_target, payload) -> None:
        landmarks = (payload or {}).get("world_landmarks") or (payload or {}).get("worldLandmarks")
        if not landmarks or len(landmarks) != 21:
            return
        flat: list[float] = []
        for point in landmarks:
            flat.extend(float(v) for v in point)
        if len(flat) != 63:
            return
        try:
            self._queue.put_nowait(flat)
            self._sent += 1
        except queue.Full:
            self._dropped += 1

    def status(self) -> dict[str, Any]:
        return {
            "sink": self.name,
            "server": self._server,
            "sent": self._sent,
            "dropped": self._dropped,
            "proto": self.proto_source,
        }

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._channel.close()


# ---------------------------------------------------------------------------
# state + HTTP
# ---------------------------------------------------------------------------

class LinkState:
    """最新一帧的映射结果，供 HTTP 层读写。"""

    def __init__(self, mapper: OrcaJointMap, sink: Sink, miss_grace_ms: float) -> None:
        self.mapper = mapper
        self.sink = sink
        self.miss_grace_ms = miss_grace_ms
        self._lock = threading.Lock()
        self._payload: dict[str, Any] | None = None
        self._received_at = 0.0
        self._previous: dict[str, float] | None = None
        self.frames = 0
        self.source: str | None = None

    def update(self, payload: Mapping[str, Any] | None) -> dict[str, float]:
        payload = dict(payload or {})
        target = self.mapper.from_vision_payload(payload)
        with self._lock:
            target = self.mapper.limit_step(target, self._previous)
            self._previous = dict(target)
            self._payload = payload
            self._received_at = time.time()
            self.frames += 1
            self.source = payload.get("source") or self.source
        self.sink.submit(target, payload)
        return target

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            payload = self._payload
            age = (time.time() - self._received_at) if self._received_at else float("inf")
            fresh = age * 1000.0 <= self.miss_grace_ms
            if payload and payload.get("hand") and fresh:
                joints = self.mapper.from_vision_payload(payload)
            else:
                joints = self.mapper.neutral_pose()
            return {
                "ok": True,
                "hand": bool(payload and payload.get("hand") and fresh),
                "age_ms": int(age * 1000) if self._received_at else -1,
                "frames": self.frames,
                "source": self.source,
                "mapping_source": self.mapper.source,
                "joint_ids": list(self.mapper.joint_ids),
                "joints": joints,
                "ordered": self.mapper.to_ordered_array(joints),
            }

    def reset(self) -> None:
        with self._lock:
            self._payload = None
            self._received_at = 0.0
            self._previous = None
            self.frames = 0


class Forwarder:
    """把原始 payload 异步转发给另一个消费者（例如你的 MC 中继）。

    单独一个工作线程 + 有界队列：转发慢或对方没起，都不该拖住主链路。
    队列满就丢最旧的，与遥操作"只要最新一帧"的原则一致。
    """

    def __init__(self, url: str | None, timeout_s: float = 2.0) -> None:
        self.url = url or None
        self.sent = 0
        self.failed = 0
        self._last_error: str | None = None
        self._timeout = timeout_s
        self._queue: queue.Queue = queue.Queue(maxsize=2)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self.url is None:
            return
        self._thread = threading.Thread(target=self._loop, name="orca-forward", daemon=True)
        self._thread.start()

    def submit(self, raw: bytes) -> None:
        if self.url is None:
            return
        try:
            self._queue.put_nowait(raw)
        except queue.Full:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(raw)
            except queue.Full:
                pass

    def _loop(self) -> None:
        import urllib.request

        while not self._stop.is_set():
            try:
                raw = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            request = urllib.request.Request(
                self.url, data=raw, headers={"Content-Type": "application/json"}
            )
            try:
                with urllib.request.urlopen(request, timeout=self._timeout) as response:
                    response.read()
                self.sent += 1
                self._last_error = None
            except Exception as exc:
                self.failed += 1
                self._last_error = f"{type(exc).__name__}: {exc}"

    def status(self) -> dict[str, Any]:
        if self.url is None:
            return {}
        return {
            "forward_to": self.url,
            "forwarded": self.sent,
            "forward_failed": self.failed,
            "forward_error": self._last_error,
        }

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)


def make_handler(state: LinkState, sink_status, forwarder: "Forwarder | None" = None):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "orca-link/0.1"

        def log_message(self, fmt, *args):
            pass

        def _send(self, code: int, body: Any) -> None:
            raw = json.dumps(body, ensure_ascii=False, default=float).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/orca_joints":
                body = state.snapshot()
                body.update(sink_status())
                if forwarder is not None:
                    body.update(forwarder.status())
                self._send(200, body)
            elif path == "/health":
                self._send(200, {"ok": True, "fingers": list(FINGER_ORDER), "joint_count": len(state.mapper.joint_ids)})
            elif path == "/reset":
                state.reset()
                self._send(200, {"ok": True, "reset": True})
            else:
                self._send(404, {"error": "not found", "try": ["/orca_joints", "/health", "/reset"]})

        def do_POST(self):
            path = urlparse(self.path).path
            if path != "/update":
                self._send(404, {"error": "not found"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8") or "{}")
            except Exception as exc:
                self._send(400, {"error": "bad json", "detail": str(exc)})
                return
            try:
                state.update(payload)
            except Exception as exc:
                self._send(400, {"error": "map failed", "detail": f"{type(exc).__name__}: {exc}"})
                return
            # 原样转发（含 world_landmarks）给 MC 中继一类的下游
            if forwarder is not None:
                forwarder.submit(raw)
            self._send(200, {"ok": True, "frames": state.frames})

    return Handler


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def build_sink(cfg: Mapping[str, Any], joint_ids: tuple[str, ...], proto_dir: Path) -> Sink:
    kind = str(cfg.get("sink", "print"))
    hz = float(cfg.get("command_hz", 30.0))
    if kind == "print":
        return PrintSink(joint_ids, hz=min(hz, 5.0))
    if kind == "orca":
        return OrcaSink(
            joint_ids=joint_ids,
            hand_config=cfg.get("hand_config"),
            mock=bool(cfg.get("mock", True)),
            hz=hz,
        )
    if kind == "grpc":
        return GrpcSink(
            server=str(cfg.get("grpc_server", "localhost:50051")),
            handedness=str(cfg.get("handedness", "right")),
            proto_dir=proto_dir,
        )
    raise ValueError(f"未知的 sink: {kind}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="视觉屈曲角 / 世界坐标 landmark -> ORCA Hand")
    parser.add_argument("--config", default=str(Path(__file__).with_name("bridge_config.yaml")))
    parser.add_argument("--sink", choices=["print", "orca", "grpc"], default=None, help="覆盖配置里的 sink")
    parser.add_argument("--port", type=int, default=None, help="覆盖配置里的端口")
    parser.add_argument(
        "--host",
        default=None,
        help="覆盖配置里的监听地址。手机/其他设备经局域网接入时必须用 0.0.0.0"
             "（默认配置是 127.0.0.1，只收本机回环，外部连不上）",
    )
    parser.add_argument("--hand-config", default=None, help="ORCA 的 config.yaml 路径")
    parser.add_argument("--real", action="store_true", help="sink=orca 时连真机（关闭 mock）")
    args = parser.parse_args(argv)

    config_path = Path(args.config)
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    bridge_cfg = dict(raw.get("bridge") or {})
    if args.sink:
        bridge_cfg["sink"] = args.sink
    if args.port:
        bridge_cfg["port"] = args.port
    if args.host:
        bridge_cfg["host"] = args.host
    if args.hand_config:
        bridge_cfg["hand_config"] = args.hand_config
    if args.real:
        bridge_cfg["mock"] = False

    tuning = load_tuning_from(raw)
    hand_config = bridge_cfg.get("hand_config")
    if hand_config and str(hand_config).lower() not in ("auto", "none", "null"):
        # 相对路径按配置文件所在目录解析，别跟着当前工作目录漂。
        candidate = Path(hand_config)
        if not candidate.is_absolute():
            candidate = (config_path.parent / candidate).resolve()
        hand_config = str(candidate)
    else:
        # auto：交给 orca_paths 去找 orca_core 检出；找不到就退回内置 ROM 副本。
        try:
            from orca_paths import core_config

            hand_config = str(core_config("v2", "right"))
        except Exception as exc:
            print(f"[orca-link] 未找到 orca_core 检出（{type(exc).__name__}），改用内置 ROM 副本")
            hand_config = None
    mapper = OrcaJointMap(hand_config_path=hand_config, tuning=tuning)

    print(f"[orca-link] 关节定义来自: {mapper.source}")
    print(f"[orca-link] 满屈曲角 {tuning.full_flexion_deg}°, 增益 {tuning.gain}, 限速 {tuning.max_step_deg}°/帧")

    proto_dir = Path(__file__).with_name("proto_gen")
    sink = build_sink(bridge_cfg, mapper.joint_ids, proto_dir)
    sink.start()

    state = LinkState(mapper, sink, float(bridge_cfg.get("miss_grace_ms", 250)))
    forwarder = Forwarder(bridge_cfg.get("forward_to"))
    forwarder.start()
    host = str(bridge_cfg.get("host", "127.0.0.1"))
    port = int(bridge_cfg.get("port", 8766))
    server = ThreadingHTTPServer(
        (host, port),
        make_handler(
            state,
            sink.status if hasattr(sink, "status") else lambda: {},
            forwarder,
        ),
    )
    print(f"[orca-link] sink={sink.name}  监听 http://{host}:{port}  (POST /update, GET /orca_joints)")
    if forwarder.url:
        print(f"[orca-link] 同时把原始 payload 转发给 {forwarder.url}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[orca-link] 退出")
    finally:
        server.server_close()
        forwarder.stop()
        sink.stop()
    return 0


def load_tuning_from(raw: Mapping[str, Any]) -> Tuning:
    section = dict(raw.get("mapping") or {})
    return Tuning.from_mapping(section)


if __name__ == "__main__":
    raise SystemExit(main())
