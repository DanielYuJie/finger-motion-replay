"""连续手势驱动器：给实时动画喂平滑变化的动作。

`drive_synthetic.py` 只在"张开/握拳"两个离散姿态间跳，拿来看静态对比够用，
但实时窗口里会显得一顿一顿。这个脚本按正弦连续改变屈曲量，并提供两种模式：

  pulse  五指同步开合（像反复握拳）
  wave   五指依次屈伸（像波动手指）

landmark 仍是 21×3、米制、腕部相对，与浏览器里 MediaPipe 的输出同形。

用法：
    <python> drive_gestures.py --pattern wave --seconds 60 --hz 30
"""

from __future__ import annotations

import argparse
import json
import math
import time
import urllib.request

FINGERS = ("thumb", "index", "middle", "ring", "pinky")


def hand_landmarks(curl: dict[str, float]) -> list[list[float]]:
    """按每指的屈曲量 curl∈[0,1] 生成 21 个世界坐标点（米）。

    四指的 MCP/PIP/DIP 依次按 60°/100°/80° 的比例折向掌心；拇指另外走一套
    位置，因为它的几何朝向和四指不同。
    """
    pts: list[list[float]] = [[0.0, 0.0, 0.0]]  # 0 腕

    # 拇指：CMC 从腕侧伸出，之后三节随 curl 逐渐向掌心收
    c = curl.get("thumb", 0.0)
    thumb = [
        (0.025, 0.020, 0.0),
        (0.045 - 0.010 * c, 0.040 - 0.005 * c, 0.005 + 0.020 * c),
        (0.060 - 0.020 * c, 0.058 - 0.015 * c, 0.010 + 0.045 * c),
        (0.070 - 0.028 * c, 0.075 - 0.028 * c, 0.015 + 0.070 * c),
    ]
    pts += [list(p) for p in thumb]

    # 四指：MCP 在掌骨末端排开，之后三节指骨按 curl 折向掌心
    mcp_x = {"index": 0.020, "middle": 0.008, "ring": -0.006, "pinky": -0.019}
    seg_len = (0.035, 0.025, 0.020)
    seg_deg = (60.0, 100.0, 80.0)
    for finger in ("index", "middle", "ring", "pinky"):
        cf = curl.get(finger, 0.0)
        x = mcp_x[finger]
        y = 0.075 + abs(x) * 0.15
        z = 0.0
        pts.append([x, y, 0.0])
        for length, deg in zip(seg_len, seg_deg):
            angle = math.radians(deg * cf)
            y += length * math.cos(angle)
            z += length * math.sin(angle)
            pts.append([x, y, z])
    return pts


def curl_for(pattern: str, t: float, period_s: float) -> dict[str, float]:
    phase = (t / period_s) % 1.0
    if pattern == "pulse":
        # 五指同步：0 -> 1 -> 0
        value = 0.5 * (1.0 - math.cos(2.0 * math.pi * phase))
        return {f: value for f in FINGERS}
    # wave：每指相位依次延后，形成波浪
    offsets = {"thumb": 0.0, "index": 0.12, "middle": 0.24, "ring": 0.36, "pinky": 0.48}
    return {
        f: 0.5 * (1.0 - math.cos(2.0 * math.pi * ((phase - offsets[f]) % 1.0)))
        for f in FINGERS
    }


def payload_for(pattern: str, t: float, period_s: float) -> dict:
    curl = curl_for(pattern, t, period_s)
    world = hand_landmarks(curl)
    # 顺带把屈曲角也按 0-100 的索引报上去（ORCA 路径只用 world_landmarks，
    # 但保持与浏览器 payload 同形，方便同一个消费者复用）
    return {
        "hand": True,
        "source": "synthetic-gestures",
        "world_landmarks": world,
        "fingers": {
            f: {"flex": 100.0 * curl[f], "mcp": 0.0, "pip": 0.0, "dip": 0.0} for f in FINGERS
        },
    }


def post(url: str, payload: dict) -> None:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=5) as response:
        response.read()


def main() -> int:
    parser = argparse.ArgumentParser(description="连续手势驱动（供实时动画用）")
    parser.add_argument("--url", default="http://127.0.0.1:8766/update")
    parser.add_argument("--pattern", choices=["pulse", "wave"], default="wave")
    parser.add_argument("--seconds", type=float, default=60.0, help="0 表示一直跑")
    parser.add_argument("--hz", type=float, default=30.0)
    parser.add_argument("--period", type=float, default=3.0, help="一次完整开合的秒数")
    args = parser.parse_args()

    period = 1.0 / args.hz
    print(f"向 {args.url} 连续推送 pattern={args.pattern} 周期={args.period}s "
          f"时长={'不限' if args.seconds <= 0 else f'{args.seconds}s'}")
    t0 = time.time()
    sent = 0
    try:
        while True:
            elapsed = time.time() - t0
            if args.seconds > 0 and elapsed > args.seconds:
                break
            try:
                post(args.url, payload_for(args.pattern, elapsed, args.period))
                sent += 1
            except Exception as exc:
                print(f"  推送失败: {type(exc).__name__}: {exc}")
                break
            target = t0 + sent * period
            sleep_for = target - time.time()
            if sleep_for > 0:
                time.sleep(sleep_for)
    except KeyboardInterrupt:
        pass
    elapsed = time.time() - t0
    print(f"结束：共 {sent} 帧，用时 {elapsed:.1f}s（{sent / max(elapsed, 1e-6):.1f} fps）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
