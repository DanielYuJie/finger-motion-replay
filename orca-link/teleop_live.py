"""机器人侧常驻进程：官方 pipeline + Windows 可用配方。

跑起来后它会：
  1. 在 0.0.0.0:<port> 上开 orca_teleop 的 IngressServer（默认 50051）
  2. 用官方 retargeter_worker 把进来的 21 点重定向成 17 个 ORCA 关节角
  3. 交给这里的 sink 消费：只打印 / 驱动 MockOrcaHand / 驱动真机

编排本身是 orca_teleop 的 `pipeline.run()`，这个文件只补一个 sink 和 Windows 上的
模型/URDF/配置组合（原因见 README 的三个坑）。

用法：
    # 只看（不碰硬件），配合 orca_bridge.py --sink grpc 使用
    <conda env>\\python.exe teleop_live.py --drive print

    # 内存里的假手，验证整条链路
    <conda env>\\python.exe teleop_live.py --drive mock

    # 真机（会连接、会标定、会动）
    <conda env>\\python.exe teleop_live.py --drive real
"""

from __future__ import annotations

import argparse
import os
import queue
import sys
import time
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")  # conda OpenMP 与 torch 共存，见 README

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from orca_paths import core_config, description_dir, urdf  # noqa: E402

V2_CFG = core_config("v2", "right")
V1_URDF = urdf("v1", "right")
DESC = description_dir()
WIN_CFG = HERE / "configs" / "adaptive_analytical_orca_windows.yaml"

os.environ.setdefault("ORCAHAND_DESCRIPTION_DIR", str(DESC))


class JointSink:
    """消费重定向后的关节目标。

    实现 orca_teleop 的 RobotSink 协议（connect / run_loop / close），
    所以可以直接喂给官方的 pipeline.run(sink=...)。
    """

    def __init__(self, drive: str, model_path: Path, hz: float, neutral_on_loss: bool) -> None:
        self.drive = drive
        self.retarget_model_path = str(model_path)  # pipeline.run 会读取这个属性
        self._period = 1.0 / max(hz, 0.1)
        self._neutral_on_loss = neutral_on_loss
        self._hand = None
        self._joint_ids: list[str] = []
        self._actions = 0
        self._last_action = None
        self._last_log = 0.0
        self.stale_timeout_s = 1.0

    # -- RobotSink 协议 ----------------------------------------------------

    def connect(self) -> None:
        if self.drive == "print":
            print("[live] sink=print：只打印关节角，不碰硬件")
            return

        from orca_core import load_hand

        mock = self.drive == "mock"
        self._hand = load_hand(config_path=str(V2_CFG), mock=mock)
        try:
            self._hand.connect(interactive=False)
        except TypeError:
            self._hand.connect()
        self._joint_ids = list(self._hand.config.joint_ids)
        self._hand.init_joints()
        print(f"[live] sink={self.drive}：已连接{'（MockOrcaHand，内存里跑）' if mock else ''}，关节数 {len(self._joint_ids)}")
        print(f"[live] 关节顺序（config.joint_ids）: {self._joint_ids}")

    def run_loop(self, actions_q: "queue.Queue", stop_event) -> None:
        print("[live] 等待 publisher 经 gRPC 送来第一帧……（前 30 帧是标定期，不会有输出）")
        last_rx = 0.0
        while not stop_event.is_set():
            try:
                action = actions_q.get(timeout=self._period)
                last_rx = time.time()
            except queue.Empty:
                if self._hand is not None and self._neutral_on_loss and last_rx:
                    if time.time() - last_rx > self.stale_timeout_s:
                        self._hand.set_neutral_position()
                        print("[live] 超过 1s 没有新帧，回中立位")
                        last_rx = 0.0
                continue

            # worker 退出时会往队列里塞一个哨兵对象（orca_teleop._SHUTDOWN），
            # 它不是关节目标，遇到就收工，否则会在属性访问上炸掉。
            if not hasattr(action, "as_array"):
                print("[live] 重定向 worker 已退出（收到关闭哨兵），停止")
                stop_event.set()
                break

            self._actions += 1
            self._last_action = action

            # 顺序安全：OrcaJointPositions 内部顺序是四指在前、wrist 最后，
            # 与 config.joint_ids 不一致，所以一律按 joint_ids 显式取数组。
            if self._hand is not None:
                values = action.as_array(self._joint_ids) if self._joint_ids else None
                if values is not None:
                    self._hand.set_joint_positions(dict(zip(self._joint_ids, values)))

            now = time.time()
            if now - self._last_log >= 0.5:
                self._last_log = now
                self._log()

    def close(self) -> None:
        print(f"[live] 结束：共下发 {self._actions} 帧关节目标")
        if self._hand is not None:
            try:
                self._hand.disconnect()
            except Exception:
                pass

    # -- 展示 --------------------------------------------------------------

    def _log(self) -> None:
        action = self._last_action
        if action is None:
            return
        now = time.time()
        if self._actions == 1:
            print("[live] 标定期结束，开始输出关节角（若刚才是 'None' 属正常）")
        order = self._joint_ids or list(action.as_dict().keys())
        values = action.as_array(order)
        body = "  ".join(
            f"{name.split('_')[0][:2]}·{name.split('_')[-1]}={v:6.1f}" for name, v in zip(order, values)
        )
        print(f"[live] #{self._actions:<6} {body}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ORCA 机器人侧常驻进程（官方 pipeline）")
    parser.add_argument("--drive", choices=["print", "mock", "real"], default="print")
    parser.add_argument("--port", type=int, default=50051)
    parser.add_argument("--hz", type=float, default=30.0, help="关节目标下发频率上限")
    parser.add_argument("--model", default=str(V2_CFG), help="ORCA 手配置（默认 v2 右手）")
    parser.add_argument("--urdf", default=str(V1_URDF), help="URDF（必须 v1：v2 是 CAD 命名）")
    parser.add_argument("--retarget-config", default=str(WIN_CFG))
    parser.add_argument("--backend", default="adaptive_analytical", choices=["adaptive_analytical", "rmsprop"])
    parser.add_argument("--neutral-on-loss", action="store_true", help="手离开 1s 后回中立位")
    parser.add_argument("--visualize-landmarks", action="store_true")
    args = parser.parse_args(argv)

    for label, path in (("model", args.model), ("urdf", args.urdf), ("retarget-config", args.retarget_config)):
        if not Path(path).exists():
            print(f"[live] 缺少 {label}: {path}", file=sys.stderr)
            return 1

    from orca_teleop.pipeline import run

    sink = JointSink(args.drive, Path(args.model), args.hz, args.neutral_on_loss)
    print(f"[live] 监听 0.0.0.0:{args.port}（gRPC HandFrame）")
    print(f"[live] backend={args.backend}  model={Path(args.model).name}  urdf={Path(args.urdf).name}")
    print(f"[live] 另一侧请运行: orca_bridge.py --sink grpc   （默认推 localhost:50051）")
    run(
        model_path=args.model,
        urdf_path=args.urdf,
        port=args.port,
        sink=sink,
        visualize_landmarks=args.visualize_landmarks,
        retargeter_backend=args.backend,
        retargeter_config_path=args.retarget_config,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
