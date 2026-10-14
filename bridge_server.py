"""
关节角中继服务（CC:Tweaked 桥接）
--------------------------------
浏览器端/小程序端做手部追踪 → POST /update 推送五指关节角
CC:Tweaked 电脑 → GET /angles 轮询最新角度

只用标准库，不依赖 mediapipe / opencv。

启动：  python bridge_server.py               # 仅本机（127.0.0.1:8765）
        python bridge_server.py --host 0.0.0.0  # 局域网接入（小程序真机用）
接口：
  POST /update   浏览器/小程序推送角度（JSON）
  GET  /angles   CC 轮询，返回最新角度
  GET  /health   健康检查
  GET  /reset    清空当前状态
"""

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = "127.0.0.1"
PORT = 8765

# 实际绑定的地址/端口（main 里按命令行参数更新，供 /health 回显）
BOUND = {"host": HOST, "port": PORT}

# 数据超过这个秒数没更新，就认为手不在画面里
STALE_SECONDS = 1.0

_lock = threading.Lock()
_state = {
    "ts": 0.0,
    "hand": False,
    "fingers": {},
    "source": None,
}

FINGER_ORDER = ["thumb", "index", "middle", "ring", "pinky"]


def snapshot():
    with _lock:
        age = time.time() - _state["ts"] if _state["ts"] else 1e9
        alive = age < STALE_SECONDS
        fingers = {}
        for name in FINGER_ORDER:
            d = _state["fingers"].get(name) or {}
            fingers[name] = {
                "flex": round(float(d.get("flex", 0.0)), 2),
                "mcp": round(float(d.get("mcp", 0.0)), 2),
                "pip": round(float(d.get("pip", 0.0)), 2),
                "dip": round(float(d.get("dip", 0.0)), 2),
            }
        return {
            "hand": bool(_state["hand"] and alive),
            "age_ms": int(age * 1000) if age < 1e8 else -1,
            "fingers": fingers,
            "source": _state["source"],
        }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/angles":
            self._send(snapshot())
        elif path == "/health":
            self._send({"ok": True, "host": BOUND["host"], "port": BOUND["port"], "fingers": FINGER_ORDER})
        elif path == "/reset":
            with _lock:
                _state["ts"] = 0.0
                _state["hand"] = False
                _state["fingers"] = {}
            self._send({"ok": True, "reset": True})
        else:
            self._send({"error": "not found", "try": ["/angles", "/health", "/reset"]}, 404)

    def do_POST(self):
        path = self.path.split("?")[0]
        if path != "/update":
            self._send({"error": "not found"}, 404)
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n else b"{}"
            data = json.loads(raw.decode("utf-8"))
        except Exception as e:
            self._send({"error": "bad json", "detail": str(e)}, 400)
            return

        fingers = data.get("fingers") or {}
        clean = {}
        for name in FINGER_ORDER:
            d = fingers.get(name)
            if isinstance(d, dict):
                clean[name] = {
                    "flex": float(d.get("flex", 0.0) or 0.0),
                    "mcp": float(d.get("mcp", 0.0) or 0.0),
                    "pip": float(d.get("pip", 0.0) or 0.0),
                    "dip": float(d.get("dip", 0.0) or 0.0),
                }

        with _lock:
            _state["ts"] = time.time()
            _state["hand"] = bool(data.get("hand", bool(clean)))
            _state["fingers"] = clean
            _state["source"] = data.get("source")

        self._send({"ok": True, "got": list(clean.keys())})

    def log_message(self, fmt, *args):
        # 保持安静，避免 CC 每秒轮询刷屏
        pass


def main():
    ap = argparse.ArgumentParser(description="关节角中继服务")
    ap.add_argument("--host", default=HOST,
                    help="监听地址；默认 127.0.0.1 仅本机，小程序真机联调用 0.0.0.0")
    ap.add_argument("--port", type=int, default=PORT, help="监听端口，默认 8765")
    args = ap.parse_args()

    BOUND["host"], BOUND["port"] = args.host, args.port
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"[bridge] 监听 http://{args.host}:{args.port}")
    print(f"[bridge]   POST /update  ← 浏览器/小程序推送角度")
    print(f"[bridge]   GET  /angles  ← CC:Tweaked 轮询")
    print(f"[bridge]   GET  /health  /reset")
    print("[bridge] Ctrl+C 退出")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[bridge] 已停止")
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
