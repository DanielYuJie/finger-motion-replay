"""电脑本地摄像头实时识别 → 关节角 → ORCA 仿真链路。

与网页端 `app.js`、小程序 `miniprogram/core/hand.js` **同一套角度口径**：
    angleBetween(a,b,c) = 向量夹角（内角，伸直约 180°）
    toFlexion(interior) = max(0, 180 - interior)        # 屈曲角，0° = 伸直
    近端关节（拇指 CMC / 四指 MCP）以手腕 landmark 0 作为掌骨方向参考
    每个关节角输出为 {flex, mcp, pip, dip}，与网页/小程序 payload 完全同形

一处**有意的改进**：这里把 MediaPipe 的归一化坐标乘回像素（乘视频宽高）再算角度。
网页端与小程序都是在 0–1 空间里算的，而 x/y 的缩放比例不同（除非画面是正方形），
会让角度有系统性偏差。知道真实分辨率就该用像素空间，几何上才是真角度。

模型：直接用仓库里已有的 `vendor/hand_landmarker.task`，**不需要联网下载**。

用法
----
    # 实时摄像头（Ctrl-C 退出）；--show 会开一个预览窗画骨架
    python webcam_drive.py --show
    # 只识别不发送（先确认能不能认出你的手）
    python webcam_drive.py --show --no-send
    # 单张图片跑一遍（用于离线验证整条链路，不需要有人举手）
    python webcam_drive.py --image some_hand.jpg --seconds 3
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.request
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python as mpp
from mediapipe.tasks.python import vision

HERE = Path(__file__).resolve().parent
DEFAULT_MODEL = HERE.parent / "vendor" / "hand_landmarker.task"
DEFAULT_URL = "http://127.0.0.1:8766/update"

WRIST = 0
# 与 app.js / core/hand.js 的 FINGER_DEFS 逐项对应
FINGER_DEFS = {
    "thumb": {"ids": (1, 2, 3, 4), "joints": ("cmc", "mcp", "ip")},
    "index": {"ids": (5, 6, 7, 8), "joints": ("mcp", "pip", "dip")},
    "middle": {"ids": (9, 10, 11, 12), "joints": ("mcp", "pip", "dip")},
    "ring": {"ids": (13, 14, 15, 16), "joints": ("mcp", "pip", "dip")},
    "pinky": {"ids": (17, 18, 19, 20), "joints": ("mcp", "pip", "dip")},
}
FINGER_ORDER = ("thumb", "index", "middle", "ring", "pinky")

# 画骨架用（与手部 21 点定义一致）
CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (17, 18), (18, 19), (19, 20),
    (0, 17),
]


def angle_between(a, b, c) -> float:
    ab = (a[0] - b[0], a[1] - b[1])
    cb = (c[0] - b[0], c[1] - b[1])
    dot = ab[0] * cb[0] + ab[1] * cb[1]
    mag = math.hypot(*ab) * math.hypot(*cb)
    if mag < 1e-8:
        return 0.0
    return math.degrees(math.acos(max(-1.0, min(1.0, dot / mag))))


def to_flexion(interior: float) -> float:
    return max(0.0, 180.0 - interior)


def compute_finger_angles(pts) -> dict:
    """pts: 21 个 (x, y)（像素空间）。返回 {finger: {flex, mcp, pip, dip}}。"""
    out = {}
    for name in FINGER_ORDER:
        i0, i1, i2, i3 = FINGER_DEFS[name]["ids"]
        angles = [
            to_flexion(angle_between(pts[WRIST], pts[i0], pts[i1])),
            to_flexion(angle_between(pts[i0], pts[i1], pts[i2])),
            to_flexion(angle_between(pts[i1], pts[i2], pts[i3])),
        ]
        out[name] = {
            # 与 hand.js 的 flex 口径一致：三角和 / 2.7，上限 100
            "flex": min(100.0, sum(angles) / 2.7),
            "mcp": angles[0],
            "pip": angles[1],
            "dip": angles[2],
        }
    return out


def build_payload(angles: dict | None, world: list | None) -> dict:
    if angles is None:
        zero = {"flex": 0.0, "mcp": 0.0, "pip": 0.0, "dip": 0.0}
        fingers = {n: dict(zero) for n in FINGER_ORDER}
        return {"hand": False, "source": "pc-webcam-mediapipe", "fingers": fingers}
    fingers = {
        n: {
            "flex": round(angles[n]["flex"], 2),
            "mcp": round(angles[n]["mcp"], 2),
            "pip": round(angles[n]["pip"], 2),
            "dip": round(angles[n]["dip"], 2),
        }
        for n in FINGER_ORDER
    }
    payload = {"hand": True, "source": "pc-webcam-mediapipe", "fingers": fingers}
    if world:
        payload["world_landmarks"] = world
    return payload


def post(url: str, payload: dict) -> bool:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            resp.read()
        return True
    except Exception:
        return False


def draw(frame, pts, angles, hand_on):
    for a, b in CONNECTIONS:
        cv2.line(frame, (int(pts[a][0]), int(pts[a][1])),
                 (int(pts[b][0]), int(pts[b][1])), (142, 207, 62), 2, cv2.LINE_AA)
    for i, (x, y) in enumerate(pts):
        cv2.circle(frame, (int(x), int(y)), 5 if i == WRIST else 4,
                   (255, 209, 90) if i else (255, 255, 255), -1, cv2.LINE_AA)
    if angles:
        y = 28
        for n in FINGER_ORDER:
            a = angles[n]
            cv2.putText(frame, f"{n:<6} mcp={a['mcp']:5.1f} pip={a['pip']:5.1f} flex={a['flex']:5.1f}",
                        (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (240, 240, 240), 1, cv2.LINE_AA)
            y += 22
    cv2.putText(frame, "HAND" if hand_on else "no hand", (12, frame.shape[0] - 14),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                (120, 230, 120) if hand_on else (120, 120, 240), 2, cv2.LINE_AA)


def make_landmarker(model: Path, hands: int, conf: float):
    if not model.exists():
        raise SystemExit(f"缺少模型文件：{model}")
    base = mpp.BaseOptions(model_asset_path=str(model))
    opts = vision.HandLandmarkerOptions(
        base_options=base,
        running_mode=vision.RunningMode.VIDEO,
        num_hands=hands,
        min_hand_detection_confidence=conf,
        min_hand_presence_confidence=conf,
        min_tracking_confidence=conf,
    )
    return vision.HandLandmarker.create_from_options(opts)


def landmarks_to_pixels(hand_landmarks, w: int, h: int):
    return [(lm.x * w, lm.y * h) for lm in hand_landmarks]


def world_to_list(hand_world_landmarks):
    if not hand_world_landmarks:
        return None
    return [[lm.x, lm.y, lm.z] for lm in hand_world_landmarks]


def main() -> int:
    ap = argparse.ArgumentParser(description="本地摄像头 → 关节角 → ORCA 桥接")
    ap.add_argument("--url", default=DEFAULT_URL, help="orca_bridge 的 /update")
    ap.add_argument("--model", default=str(DEFAULT_MODEL))
    ap.add_argument("--camera", type=int, default=0, help="摄像头序号")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--fps", type=float, default=15.0, help="上行频率（识别不必跑满帧率）")
    ap.add_argument("--image", default=None, help="单张图片模式（离线验证，不必有人举手）")
    ap.add_argument("--seconds", type=float, default=0.0, help="0 = 一直跑")
    ap.add_argument("--hands", type=int, default=1)
    ap.add_argument("--conf", type=float, default=0.5)
    ap.add_argument("--show", action="store_true", help="开预览窗（画骨架与角度）")
    ap.add_argument("--no-send", action="store_true", help="只识别不发送")
    ap.add_argument("--print-every", type=float, default=1.0)
    args = ap.parse_args()

    lm = make_landmarker(Path(args.model), args.hands, args.conf)
    print(f"[cam] 模型 {Path(args.model).name} 已加载")

    static_frame = None
    cap = None
    if args.image:
        img = cv2.imread(args.image)
        if img is None:
            raise SystemExit(f"读不到图片：{args.image}")
        static_frame = cv2.resize(img, (args.width, args.height))
        src_w, src_h = args.width, args.height
        print(f"[cam] 图片模式：{args.image}  {img.shape[1]}x{img.shape[0]} -> {args.width}x{args.height}")
    else:
        cap = cv2.VideoCapture(args.camera, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap = cv2.VideoCapture(args.camera)
        if not cap.isOpened():
            raise SystemExit(f"打不开摄像头 {args.camera}")
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
        src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or args.width
        src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or args.height
        print(f"[cam] 摄像头 {args.camera} 已打开 {src_w}x{src_h}")

    interval = 1.0 / max(1e-6, args.fps)
    t0 = time.time()
    last_send = 0.0
    last_print = 0.0
    frames = detected = sent = send_fail = 0
    last_angles = None

    print(f"[cam] 上行 {args.url} @ {args.fps:.0f}Hz" + ("（--no-send 已关闭）" if args.no_send else ""))
    try:
        while True:
            loop_t = time.time()
            if static_frame is not None:
                frame = static_frame.copy()
            else:
                ok, frame = cap.read()
                if not ok:
                    print("[cam] 读帧失败")
                    break
                h, w = frame.shape[:2]
                src_w, src_h = w, h

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
            res = lm.detect_for_video(mp_img, int(time.time() * 1000))
            frames += 1

            angles = None
            world = None
            if res.hand_landmarks:
                detected += 1
                pts = landmarks_to_pixels(res.hand_landmarks[0], src_w, src_h)
                angles = compute_finger_angles(pts)
                last_angles = angles
                world = world_to_list(res.hand_world_landmarks[0] if res.hand_world_landmarks else None)
                if args.show:
                    draw(frame, pts, angles, True)
            elif args.show:
                cv2.putText(frame, "no hand", (12, frame.shape[0] - 14),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (120, 120, 240), 2, cv2.LINE_AA)

            now = time.time()
            if (not args.no_send) and angles is not None and (now - last_send) >= interval:
                last_send = now
                if post(args.url, build_payload(angles, world)):
                    sent += 1
                else:
                    send_fail += 1
            elif (not args.no_send) and angles is None and (now - last_send) >= max(interval, 0.5):
                # 手离开画面：推一帧 hand=false，让机械手/仿真回中立位
                last_send = now
                if post(args.url, build_payload(None, None)):
                    sent += 1
                else:
                    send_fail += 1

            if now - last_print >= args.print_every:
                last_print = now
                if last_angles and res.hand_landmarks:
                    a = last_angles
                    print(f"[cam] 帧{frames:<5} 检出{detected:<4} 已发{sent:<4} 失败{send_fail:<3} "
                          f"i-mcp={a['index']['mcp']:5.1f} i-pip={a['index']['pip']:5.1f} "
                          f"t-cmc={a['thumb']['mcp']:5.1f} p-pip={a['pinky']['pip']:5.1f}")
                else:
                    print(f"[cam] 帧{frames:<5} 未检出到手（已发{sent} 失败{send_fail}）"
                          f"—— 把手放进画面中央、光照充足")

            if args.show:
                cv2.imshow("hand -> ORCA (q/Esc to quit)", frame)
                if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                    break

            if args.seconds and (time.time() - t0) >= args.seconds:
                break
            sleep_for = interval - (time.time() - loop_t)
            if sleep_for > 0:
                time.sleep(sleep_for)
    except KeyboardInterrupt:
        print("\n[cam] Ctrl-C")
    finally:
        if cap is not None:
            cap.release()
        if args.show:
            cv2.destroyAllWindows()
        # close() 在部分 mediapipe 版本上会抛异常；它发生在汇总打印之后，
        # 不处理就会把本来成功的运行变成非零退出码。
        try:
            lm.close()
        except Exception as exc:  # noqa: BLE001
            print(f"[cam] 关闭识别器时出错（忽略）：{exc}")

    print(f"[cam] 结束：{frames} 帧，检出 {detected} 帧，上行 {sent} 次（失败 {send_fail}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
