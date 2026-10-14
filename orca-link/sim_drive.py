"""把视觉主端的关节角直接驱动 orca_sim 的 MuJoCo 仿真。

为什么不直接用 `teleop_live.py --drive sim`
--------------------------------------------
官方那条路是：gRPC → `orca_teleop.IngressServer` → `AdaptiveAnalyticalRetargeter`
→ 关节角。重定向器要的是 **米制、腕部相对的 `world_landmarks`**，而
微信小程序走 VisionKit **2D**，只有 0–1 归一化的图像坐标，拿不到 world_landmarks
（VisionKit 3D 要微信 ≥ 8.1.0）。

但 `orca_sim` 的 env **直接吃关节位置**，而 `orca_hand_map.from_vision_payload()`
已经能把小程序的 payload 映射成 17 个关节目标 —— 所以这里直接喂 env，
跳过整个重定向器。副作用是连 torch / pinocchio / nlopt / grpcio 都不需要装。

数据来源
--------
轮询 `orca_bridge` 的 `GET /orca_joints`（默认 8766），**不新开端口**，保持单一入口：
小程序 / drive_gestures / 网页端 都照旧 POST 到 bridge，本脚本只是另一个消费者。
bridge 的 `miss_grace_ms` 宽限到期后会回中立位，仿真因此也会跟着回中立 —— 这是期望行为。

用法
----
    # 终端1：桥接（数据入口）
    python orca_bridge.py --sink print --host 0.0.0.0

    # 终端2：本脚本（驱动仿真）。--render human 会弹出 MuJoCo 交互窗口
    python sim_drive.py --render human
    python sim_drive.py --seconds 8 --snapshot-dir sim_frames --snapshot-every 15

需要：mujoco + gymnasium + orca_sim + orca_core（见 orca-link/README「仿真」一节）。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# 执行器名 → orca_core config joint_id 的翻译。
# 照抄 orca_teleop/src/orca_teleop/sim.py 的 _sim_joint_to_config_id（同上游规则），
# 因为 import orca_teleop 会经 __init__ 拖进 torch —— 我们要避开那整条栈。
# ---------------------------------------------------------------------------
_SIM_FINGER_LETTERS = {"t": "thumb", "i": "index", "m": "middle", "r": "ring", "p": "pinky"}


def sim_joint_to_config_id(core_name: str, valid_ids: set[str]) -> str | None:
    """把（去掉手别前缀的）MuJoCo 关节名翻译成 config.joint_ids 里的名字。

    v1 名字与 config 一致（thumb_mcp / wrist）；v2 把「指+节」缩写成
    `<字母>-<节>`（t-mcp / p-abd）。拇指远端在模型里叫 `t-pip`，而 config 里叫
    `thumb_dip` —— 这个特例单独处理。结果会用 valid_ids 校验，命名漂移会直接报错
    而不是静默驱动错误的关节。
    """
    if core_name in valid_ids:  # v1
        return core_name
    if "-" in core_name:  # v2: '<finger-letter>-<segment>'
        letter, _, segment = core_name.partition("-")
        finger = _SIM_FINGER_LETTERS.get(letter)
        if finger is not None:
            candidate = f"{finger}_{segment}"
            if candidate in valid_ids:
                return candidate
            if finger == "thumb" and segment == "pip" and "thumb_dip" in valid_ids:
                return "thumb_dip"
    return None


def resolve_config_path(env_name: str, version: str) -> Path:
    """orca_core 里对应手别/版本的 config.yaml。

    ⚠️ 目录名是**连字符** `orcahand-right`，而上游 sim sink 拼的是下划线
    `orcahand_right`，于是拿不到路径并抛 RuntimeError（orca-link/README 的「坑 5」）。
    teleop_live.py 用子类覆盖绕开；这里直接拼对。
    """
    import orca_core

    cfg = (
        Path(orca_core.__file__).resolve().parent
        / "models"
        / version
        / f"orcahand-{env_name}"
        / "config.yaml"
    )
    if not cfg.exists():
        raise SystemExit(f"找不到 orca_core 手配置：{cfg}")
    return cfg


def map_actuators(mujoco, model, valid_ids: set[str], env_name: str):
    """把 MuJoCo 执行器（ctrl 顺序）映射到 config 的 joint_id。

    返回 (每个执行器对应的 config joint_id, 每个执行器传动关节的 qpos 地址)，
    两者都在 MuJoCo 执行器顺序上，保证 ctrl 向量与读数对齐。
    """
    prefix = f"{env_name}_"
    joint_names: list[str] = []
    qpos_adr: list[int] = []
    unmapped: list[str] = []

    for actuator in range(model.nu):
        jnt_id = int(model.actuator_trnid[actuator, 0])
        mj_name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, jnt_id)
        core = mj_name.removeprefix(prefix) if mj_name is not None else ""
        config_id = sim_joint_to_config_id(core, valid_ids)
        if config_id is None:
            unmapped.append(mj_name)
            continue
        joint_names.append(config_id)
        qpos_adr.append(int(model.jnt_qposadr[jnt_id]))

    if unmapped:
        raise SystemExit(
            f"这些执行器在 config 里找不到对应 joint_id：{unmapped}（命名可能已漂移）"
        )
    if set(joint_names) != valid_ids or len(set(joint_names)) != len(joint_names):
        raise SystemExit(
            "执行器 → joint_id 不是一一覆盖："
            f"映射到 {sorted(joint_names)}，config 是 {sorted(valid_ids)}"
        )
    return joint_names, np.array(qpos_adr, dtype=np.int64)


def fetch_joints(url: str, timeout: float = 2.0) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description="用 orca_bridge 的关节目标驱动 orca_sim 仿真")
    ap.add_argument("--bridge", default="http://127.0.0.1:8766/orca_joints",
                    help="orca_bridge 的 /orca_joints 地址")
    ap.add_argument("--env", dest="env_name", default="right", choices=["right", "left"])
    ap.add_argument("--version", default="v2")
    ap.add_argument("--render", default="human", choices=["human", "rgb_array", "none"],
                    help="human = 弹 MuJoCo 交互窗口；none = 不开窗（仍可截图）；"
                         "rgb_array = 走 env 自带渲染")
    ap.add_argument("--fps", type=float, default=30.0, help="仿真步进/渲染频率")
    ap.add_argument("--seconds", type=float, default=0.0, help="0 = 一直跑")
    ap.add_argument("--snapshot-dir", default=None, help="把渲染帧存成 PNG（需要 Pillow）")
    ap.add_argument("--snapshot-every", type=int, default=10, help="每 N 帧存一张")
    ap.add_argument("--print-every", type=float, default=2.0, help="每 N 秒打一行状态")
    args = ap.parse_args()

    import mujoco
    import orca_core
    from orca_sim import OrcaHandLeft, OrcaHandRight

    cfg_path = resolve_config_path(args.env_name, args.version)
    hand = orca_core.OrcaHand(str(cfg_path))
    valid_ids = set(hand.config.joint_ids)
    print(f"[sim] 手配置 {cfg_path.name}  joint_ids={len(valid_ids)}")

    builders = {"left": OrcaHandLeft, "right": OrcaHandRight}
    # orca_sim 只接受 None / "human" / "rgb_array"（见 orca_sim/envs.py 的校验）
    render_mode = None if args.render == "none" else args.render
    env = builders[args.env_name](version=args.version, render_mode=render_mode)
    env.reset()
    model, data = env.model, env.data

    actuator_joint_names, qpos_adr = map_actuators(mujoco, model, valid_ids, args.env_name)
    print(f"[sim] 执行器 {model.nu} 个，已逐一映射到 config joint_id")
    print(f"[sim] 执行器顺序: {actuator_joint_names}")

    renderer = None
    camera = None
    out_dir = None
    if args.snapshot_dir:
        from PIL import Image  # noqa: F401  (只在需要截图时要求 Pillow)
        out_dir = Path(args.snapshot_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        renderer = mujoco.Renderer(model, height=480, width=640)
        camera = mujoco.MjvCamera()
        mujoco.mjv_defaultFreeCamera(model, camera)
        print(f"[sim] 截图输出: {out_dir}")

    dt = 1.0 / max(1e-6, args.fps)
    t0 = time.time()
    frame = 0
    got = 0
    last_print = 0.0
    last_reported = None

    print(f"[sim] 开始：轮询 {args.bridge}，{args.fps:.0f} Hz"
          + (f"，跑 {args.seconds:.0f}s" if args.seconds else "，Ctrl-C 退出"))
    try:
        while True:
            loop_start = time.time()

            payload = fetch_joints(args.bridge)
            if payload and payload.get("joints"):
                got += 1
                last_reported = payload
                joints = payload["joints"]
                # bridge 给的是物理角度（度），MuJoCo 用弧度
                ctrl = np.deg2rad(
                    np.array([float(joints[j]) for j in actuator_joint_names], dtype=np.float64)
                )
            else:
                ctrl = None

            if ctrl is not None:
                env.step(ctrl)

            if renderer is not None and frame % max(1, args.snapshot_every) == 0:
                renderer.update_scene(data, camera=camera)
                img = renderer.render()
                Image.fromarray(img).save(out_dir / f"sim-{frame:05d}.png")

            frame += 1
            now = time.time()
            if now - last_print >= args.print_every:
                last_print = now
                if last_reported:
                    j = last_reported["joints"]
                    print(
                        f"[sim] #{frame:<5} hand={last_reported.get('hand')} "
                        f"i-mcp={j['index_mcp']:6.1f} i-pip={j['index_pip']:6.1f} "
                        f"t-cmc={j['thumb_cmc']:6.1f} p-pip={j['pinky_pip']:6.1f} "
                        f"(bridge 命中 {got} 次)"
                    )
                else:
                    print(f"[sim] #{frame:<5} 尚未连上桥接 {args.bridge}")

            if args.seconds and (now - t0) >= args.seconds:
                break
            sleep_for = dt - (time.time() - loop_start)
            if sleep_for > 0:
                time.sleep(sleep_for)
    except KeyboardInterrupt:
        print("\n[sim] 收到 Ctrl-C")
    finally:
        if renderer is not None:
            renderer.close()
        env.close()

    print(f"[sim] 结束：共 {frame} 帧，{got} 帧拿到了桥接数据")
    if out_dir is not None:
        n = len(list(out_dir.glob('sim-*.png')))
        print(f"[sim] 截图 {n} 张 -> {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
