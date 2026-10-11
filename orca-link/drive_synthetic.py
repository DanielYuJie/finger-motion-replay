"""模拟 capture.html 往 orca_bridge 推帧，用于在没有摄像头时联调整条链路。

它发的 payload 形状与你浏览器里 pushBridge 产出的完全一致（含 world_landmarks），
所以这条路径通了 = 你的网页接上去就通。

用法：
    <python> drive_synthetic.py [--url http://127.0.0.1:8766/update] [--seconds 8] [--hz 30]
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request

from test_full_chain import synthetic_hand


def post(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="模拟浏览器向 orca_bridge 推帧")
    parser.add_argument("--url", default="http://127.0.0.1:8766/update")
    parser.add_argument("--seconds", type=float, default=8.0)
    parser.add_argument("--hz", type=float, default=30.0)
    args = parser.parse_args()

    period = 1.0 / args.hz
    total = int(args.seconds * args.hz)
    ok = 0
    t0 = time.time()
    print(f"向 {args.url} 推 {total} 帧（约 {args.seconds}s）：张开 -> 握拳 -> 张开")

    for i in range(total):
        phase = i / max(total - 1, 1)
        # 前半张开、中间握拳、后半再张开，让动作有明显的往返
        open_hand = not (0.3 <= phase < 0.7)
        payload = {
            "hand": True,
            "source": "webcam-mediapipe",
            "world_landmarks": synthetic_hand(open_hand=open_hand),
            "fingers": {
                name: {"flex": 0.0, "mcp": 0.0, "pip": 0.0, "dip": 0.0}
                for name in ("thumb", "index", "middle", "ring", "pinky")
            },
        }
        try:
            post(args.url, payload)
            ok += 1
        except Exception as exc:
            print(f"  第 {i} 帧失败: {type(exc).__name__}: {exc}")
            break
        target = t0 + (i + 1) * period
        sleep_for = target - time.time()
        if sleep_for > 0:
            time.sleep(sleep_for)

    elapsed = time.time() - t0
    print(f"完成：成功 {ok}/{total} 帧，用时 {elapsed:.1f}s（{ok / elapsed:.1f} fps）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
