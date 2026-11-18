# PC 推理服务（MediaPipe 手部识别）

小程序里塞不进 MediaPipe 模型，但小楚君上位机（`XiaochuHand.exe`）用的就是它。
这个服务把模型留在电脑，把「接口」交给小程序：**小程序抓帧 → 本服务推理 → 回传五指角度**。

## 为什么值得做

| 场景 | 小程序 VisionKit | 本服务（MediaPipe） |
| --- | --- | --- |
| 手掌正对镜头、五指张开 | 有残余（曾需要死区压） | 五指全 0 |
| 握拳 | 有偏差 | 90 / 100 / 100 / 100 / 100 |
| 手背朝镜头、手指被遮挡 | 明显变差 | 明显更稳 |

模型是**官方 `hand_landmarker.task`（7.46 MB）**，直接从 `XiaochuHand.exe` 解包目录里复制过来的，与作者用的是同一个文件。

## 安装 / 启动

```powershell
# 依赖（只需一次）
& "D:\tools\miniconda\envs\orca-teleop\python.exe" -m pip install mediapipe numpy

# 启动（默认 0.0.0.0:8767）
cd "D:\DSPersonal Project Area\finger-motion-replay\pc-server"
& "D:\tools\miniconda\envs\orca-teleop\python.exe" hand_server.py
```

启动后终端会打印本机局域网地址，例如：

```
  手机用 http://192.168.1.9:8767
```

把这个地址填进小程序「PC 推理模式」页。

> 模型文件放在 `models/hand_landmarker.task`，缺失时服务会直接退出并提示。

## 接口

### `GET /health`

```json
{"ok": true, "model": "hand_landmarker.task", "modelExists": true,
 "stats": {"calls": 12, "errors": 0, "last_ms": 21.2, "last_hand": true}}
```

### `POST /infer`

请求（小程序 `onCameraFrame` 给的就是 RGBA）：

```json
{"w": 240, "h": 180, "data": "<base64 RGBA>"}
```

响应：

```json
{"ok": true, "hand": true, "ms": 21.2,
 "flex": {"thumb": 0, "index": 0, "middle": 0, "ring": 0, "pinky": 0},
 "angles": {"index": [12.3, 8.1, 4.0], ...},
 "ratio": {"index": 0.994, ...},
 "points": [[x, y, z], ...]}
```

- `flex` 是 0–100 的屈曲度，已做**软死区 + 5% 量化**，可直接喂 `core/ble-hand.js`。
- `hand=false` 时只有 `ok / hand / ms` 三个字段。
- 服务端会校验 `w * h * 4 == base64 解出的字节数`，尺寸不符直接 400（避免小程序侧尺寸算错还静默出结果）。

## 实测（本机 CPU）

| 项目 | 数值 |
| --- | --- |
| 模型加载 | 首次约 81 ms（含预热） |
| 单帧推理 | **21–24 ms**（预热后） |
| 本地回环总耗时 | 24–42 ms |
| 手机 → PC（同 Wi-Fi，待真机实测） | 预计 100–300 ms |

## 角度口径

与 `miniprogram/core/hand.js` **完全一致**，两端结果可以直接对比：

1. 三点向量夹角（带 z）→ 屈曲角；
2. 叠加 curl 比值 `直线(根→尖) / 折线(根→P1→P2→尖)`；
3. `flex = 0.6 × 关节角 + 0.4 × 曲率比`（拇指 CMC 权重 0.35）；
4. 软死区 `≤8 → 0`、`≥92 → 100`，再按 5% 取整。

## 小程序侧

页面：`miniprogram/pages/remote/`（采集页 →「PC 推理模式」）

- 摄像头取流用 `<camera frame-size="small">` + `onCameraFrame`，**不是** VisionKit（VisionKit 的帧拿不到像素）
- 5 Hz 上传（`THROTTLE_MS = 200`），上一帧没回来就丢帧，不排队
- 返回的 flex 可勾选「用识别结果驱动机械手」直接推 BLE
- 停止抓帧 / 页面隐藏会自动把机械手写回伸直位

开发者工具里记得勾「详情 → 本地设置 → 不校验合法域名」，否则 `http://` 请求会被拦。

## 已知限制

- PC 必须常开且与手机同一 Wi-Fi；跨网段/公网需要另做端口映射（不建议）。
- 每帧 240×180 RGBA ≈ 172 KB，base64 后 ≈ 230 KB；5 Hz 约 1.1 MB/s。若网络吃紧，把 `THROTTLE_MS` 调到 300–400。
- 服务端不使用线程池模型多开（`HandLandmarker` 非线程安全，已加锁串行）。
