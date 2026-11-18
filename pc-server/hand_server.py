"""
PC 端手部推理服务（MediaPipe HandLandmarker）。

为什么需要它：
  微信小程序的 VisionKit 只有官方那一套模型，手背朝镜头 / 手指被手背遮挡时识别很弱。
  而小楚君上位机（XiaochuHand.exe）用的就是 MediaPipe 的 hand_landmarker.task —— 同一个模型
  在 PC 上跑得好得多。模型没法塞进小程序，于是把它留在电脑，把「接口」搬进小程序：
  小程序实时抓帧 → POST 到本服务 → 拿回五指角度 → 直接推 BLE 驱动机械手。

接口
  GET  /health                 → {"ok":true,"model":"...","fps":...}
  POST /infer                  → 请求体 JSON
        {"w":240,"h":180,"data":"<base64 RGBA>"}   原始帧（小程序 onCameraFrame 的格式）
        {"w":..,"h":..,"rgb":true,...}             若已是 RGB 则带 rgb:true
      响应 {"ok":true,"hand":bool,"ms":..,"flex":{...},"angles":{...},"ratio":{...}}

启动
  python hand_server.py                 # 0.0.0.0:8767
  python hand_server.py --port 8767     # 指定端口

依赖
  pip install mediapipe numpy
  models/hand_landmarker.task   ← 直接用 XIAOCHUHAND.EXE 里解出来的官方模型

角度口径与小程序 core/hand.js 完全一致：
  三点 3D 夹角 → 屈曲角；再叠加 curl 比值；最后软死区 + 5% 量化。
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = os.path.join(HERE, "models", "hand_landmarker.task")

# ─────────────────────────── 角度算法（与 core/hand.js 同口径）───────────────────────────

WRIST = 0
FINGER_DEFS = {
    "thumb":  {"ids": [1, 2, 3, 4],   "label": "拇指",   "joints": ["CMC", "MCP", "IP"]},
    "index":  {"ids": [5, 6, 7, 8],   "label": "食指",   "joints": ["MCP", "PIP", "DIP"]},
    "middle": {"ids": [9, 10, 11, 12], "label": "中指",   "joints": ["MCP", "PIP", "DIP"]},
    "ring":   {"ids": [13, 14, 15, 16], "label": "无名指", "joints": ["MCP", "PIP", "DIP"]},
    "pinky":  {"ids": [17, 18, 19, 20], "label": "小指",   "joints": ["MCP", "PIP", "DIP"]},
}
FINGER_ORDER = ["thumb", "index", "middle", "ring", "pinky"]
FLEX_LO, FLEX_HI, FLEX_STEP = 8.0, 92.0, 5


def _vec(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def angle_between(a, b, c):
    v1, v2 = _vec(a, b), _vec(c, b)
    dot = v1[0] * v2[0] + v1[1] * v2[1] + v1[2] * v2[2]
    n1 = math.sqrt(sum(x * x for x in v1))
    n2 = math.sqrt(sum(x * x for x in v2))
    if n1 * n2 < 1e-9:
        return 0.0
    cos = max(-1.0, min(1.0, dot / (n1 * n2)))
    return math.degrees(math.acos(cos))


def path_ratio(pts, ids):
    base, tip = pts[ids[0]], pts[ids[3]]
    path = sum(math.dist(pts[ids[i]], pts[ids[i + 1]]) for i in range(3))
    if path < 1e-9:
        return 1.0
    return min(1.0, math.dist(base, tip) / path)


def compute_finger_angles(pts):
    """pts: [(x, y, z)] × 21，已归一化。"""
    out = {}
    for name in FINGER_ORDER:
        ids = FINGER_DEFS[name]["ids"]
        i0, i1, i2, i3 = ids
        angles = [
            max(0.0, 180.0 - angle_between(pts[WRIST], pts[i0], pts[i1])),
            max(0.0, 180.0 - angle_between(pts[i0], pts[i1], pts[i2])),
            max(0.0, 180.0 - angle_between(pts[i1], pts[i2], pts[i3])),
        ]
        w0 = 0.35 if name == "thumb" else 0.8
        avg = (angles[0] * w0 + angles[1] + angles[2]) / (w0 + 2.0)
        angle_flex = min(100.0, max(0.0, avg * 1.11))
        ratio = path_ratio(pts, ids)
        curl_flex = min(100.0, max(0.0, ((1.0 - ratio) / 0.55) * 100.0))
        flex = 0.6 * angle_flex + 0.4 * curl_flex
        out[name] = {"angles": [round(a, 1) for a in angles],
                     "ratio": round(ratio, 3),
                     "flex": min(100.0, max(0.0, flex))}
    return out


def sharpen(values):
    """软死区 + 量化，与小程序 sharpenFlex 一致。"""
    res = {}
    for name, f in values.items():
        if f <= FLEX_LO:
            v = 0.0
        elif f >= FLEX_HI:
            v = 100.0
        else:
            v = ((f - FLEX_LO) / (FLEX_HI - FLEX_LO)) * 100.0
        res[name] = int(round(v / FLEX_STEP) * FLEX_STEP)
    return res


# ─────────────────────────── MediaPipe ───────────────────────────

_lock = threading.Lock()
_landmarker = None
_stats = {"calls": 0, "errors": 0, "last_ms": 0.0, "last_ts": 0.0, "last_hand": False}


def get_landmarker():
    global _landmarker
    if _landmarker is not None:
        return _landmarker
    import mediapipe as mp
    from mediapipe.tasks import python as mp_tasks
    from mediapipe.tasks.python import vision

    if not os.path.exists(MODEL):
        raise SystemExit(f"模型不存在：{MODEL}\n把 XiaochuHand.exe 里的 hand_landmarker.task 放到 models/ 下。")

    opts = vision.HandLandmarkerOptions(
        base_options=mp_tasks.BaseOptions(model_asset_path=MODEL),
        running_mode=vision.RunningMode.IMAGE,   # 每帧全量检测：丢帧立刻重找，最不易"手丢了"
        num_hands=1,
        min_hand_detection_confidence=0.5,
        min_hand_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    _landmarker = vision.HandLandmarker.create_from_options(opts)
    return _landmarker


def infer_rgba(raw: bytes, w: int, h: int, is_rgb: bool = False):
    import mediapipe as mp

    t0 = time.time()
    if is_rgb:
        arr = np.frombuffer(raw, dtype=np.uint8).reshape(h, w, 3)
        rgb = arr
    else:
        arr = np.frombuffer(raw, dtype=np.uint8).reshape(h, w, 4)
        rgb = arr[:, :, :3]
    mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))

    with _lock:
        lm = get_landmarker()
        result = lm.detect(mp_img)

    ms = (time.time() - t0) * 1000.0
    _stats["calls"] += 1
    _stats["last_ms"] = round(ms, 1)
    _stats["last_ts"] = time.time()

    if not result.hand_landmarks:
        _stats["last_hand"] = False
        return {"ok": True, "hand": False, "ms": round(ms, 1)}

    pts = [(p.x, p.y, p.z) for p in result.hand_landmarks[0]]  # 归一化坐标，z 为相对深度
    raw_angles = compute_finger_angles(pts)
    flex = sharpen({k: v["flex"] for k, v in raw_angles.items()})

    _stats["last_hand"] = True
    return {
        "ok": True,
        "hand": True,
        "ms": round(ms, 1),
        "flex": flex,
        "angles": {k: v["angles"] for k, v in raw_angles.items()},
        "ratio": {k: v["ratio"] for k, v in raw_angles.items()},
        "points": [[round(x, 4), round(y, 4), round(z, 4)] for (x, y, z) in pts],
    }


# ─────────────────────────── HTTP ───────────────────────────


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "content-type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "content-type")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if self.path.split("?")[0] in ("/health", "/"):
            self._send(200, {"ok": True, "model": os.path.basename(MODEL),
                             "modelExists": os.path.exists(MODEL), "stats": _stats})
        else:
            self._send(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        if self.path.split("?")[0] != "/infer":
            self._send(404, {"ok": False, "error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > 32 * 1024 * 1024:
                self._send(400, {"ok": False, "error": "bad content-length"})
                return
            req = json.loads(self.rfile.read(length).decode("utf-8"))
            w, h = int(req.get("w") or 0), int(req.get("h") or 0)
            b64 = req.get("data") or ""
            if w <= 0 or h <= 0 or not b64:
                self._send(400, {"ok": False, "error": "need w/h/data"})
                return
            raw = base64.b64decode(b64)
            ch = 3 if req.get("rgb") else 4
            if len(raw) != w * h * ch:
                self._send(400, {"ok": False,
                                 "error": f"size mismatch: got {len(raw)}, expect {w * h * ch}"})
                return
            self._send(200, infer_rgba(raw, w, h, bool(req.get("rgb"))))
        except Exception as e:  # 不让单帧异常打断服务
            _stats["errors"] += 1
            self._send(500, {"ok": False, "error": f"{type(e).__name__}: {e}"})

    def log_message(self, fmt, *args):
        return  # 静音默认日志，避免每帧刷屏


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8767)
    ap.add_argument("--host", default="0.0.0.0")
    args = ap.parse_args()

    print("=" * 62)
    print("手部推理服务（MediaPipe HandLandmarker）")
    print(f"  模型   {MODEL}  {'OK' if os.path.exists(MODEL) else '缺失！'}")
    print(f"  监听   http://{args.host}:{args.port}")
    print(f"  手机用 http://{lan_ip()}:{args.port}")
    print("=" * 62)
    sys.stdout.flush()

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n退出")


if __name__ == "__main__":
    main()
