# 小楚君机械手 · BLE 打通记录（网页端 + 小程序）

> 目标：把本仓库的视觉端（MediaPipe / VisionKit 21 点 → flex 0–100）接到小楚君固件（ESP32-C3 + PCA9685 + 5×SG90）。
> 网页端与小程序共用同一套指令契约与标定表，**都不需要改固件**。

## 1. 固件结构（四层）

源码：`小楚君机械手开源/主控代码/sketch_26_7_4/sketch_26_7_4.ino`（270 行）

| 层 | 职责 | 关键点 |
| --- | --- | --- |
| BLE 层 | 广播设备名 `xiaochu`，1 个 Service + 1 个写特征 | 无读特征、无 notify |
| 指令层 | `onWrite` 解析字符串 | 两类指令：`servo_i=angle` / 11 个手势名 |
| 模型层 | `Finger`（channel / maxOpen / maxClosed / direction）+ `Hand` 管 5 指 | 五指标定表 |
| 运动层 | 每 10 ms 以 2° 步长线性逼近 target，再写 PCA9685 | 约 200°/s，比 SG90 慢 |
| 硬件层 | I2C `SDA=GPIO8` / `SCL=GPIO9`；PCA9685 `0x40`、50 Hz | 脉宽 150–500 tick |

BLE 标识：

- 设备名：`xiaochu`
- Service：`89d60870-9908-4472-8f8c-e5b3e6573cd1`
- 写特征：`39dea685-a63e-44b2-8819-9a202581f8fe`（`WRITE | WRITE_NR`）

## 2. 指令契约

| 指令 | 示例 | 行为 | 是否走标定层 |
| --- | --- | --- | --- |
| 角度直发 | `servo_2=90` | 直接设 0–180° 目标 | 否，**安全** |
| 手势预设 | `fist` / `five` / `ok` / `rock` / `love` / `one` / `two` / `three` / `four` / `scratch` / `come` | 5 指归一化 0/100 | 是，踩 bug |

五指标定表（角度直发与 flex 换算共用）：

| 指 | 通道 | MAX_OPEN | MAX_CLOSED | direction |
| --- | --- | --- | --- | --- |
| 拇指 | 0 | 30° | 180° | 1 |
| 食指 | 1 | 10° | 180° | 1 |
| 中指 | 2 | 180° | 0° | -1 |
| 无名指 | 3 | 0° | 180° | 1 |
| 小指 | 4 | 180° | 35° | -1 |

## 3. 已知固件问题

1. **归一化反转**：`direction` 与 `maxOpen/maxClosed` 方向语义重复，中指/小指被翻两次。只影响 11 个手势键；`servo_i=angle` 直发绕开。
2. **上电甩手约 0.9 s**：`setup()` 统一写 0°，各指「开」位是 30/10/180/0/180。
3. **断线无保护**：BLE 断开后停在最后姿态；`PCA9685 not found` 会死循环。

## 4. 两端共用的换算

```
flex ∈ [0,100]（0 = 伸直，100 = 握拳）
angle = round(open + flex / 100 * (closed - open))，clamp 到 0–180
```

边界值（已单测）：拇指 0→30 / 100→180；中指 0→180 / 100→0；小指 0→180 / 100→35。

## 5. 网页端实现

### 5.1 数据流

```
MediaPipe 21 点
  → computeFingerAngles：flex = min(100, (mcp + pip + dip) / 2.7)
  → ble-bridge.js：flex → angle
  → ASCII "servo_<ch>=<angle>"（≤ 12 字节）
  → BLE 写特征（无响应写）
```

### 5.2 `ble-bridge.js`

全局 `window.BleHand`：

| 方法 | 说明 |
| --- | --- |
| `connect()` | `requestDevice`（namePrefix `xiaochu`）→ GATT → Service → 写特征 |
| `disconnect()` | 主动断开并清状态 |
| `send(fingers)` | 接收 `{thumb:{flex}, ...}`；10 Hz 节流；角度变化 ≤1° 不重复写；`null` 触发全指回伸直位 |
| `sendRaw(cmd)` | 直接写一条字符串，调试用 |
| `setEnabled(bool)` / `isEnabled()` | 视觉驱动开关 |
| `onStatus(cb)` / `isConnected()` | 状态回调与连接查询 |
| `flexToAngle(finger, flex)` / `FINGERS` | 换算函数与标定表 |

内部：单飞循环合并高频帧；`gattserverdisconnected` 自动清空特征并置为断开。

### 5.3 页面接线

- `capture.html`：MC 桥接上方新增「BLE 机械手」面板；`ble-bridge.js` 在 `app.js` 之前加载。
- `app.js`：检测帧 `pushBridge(angles)` 后调 `BleHand.send(angles)`；丢手帧调 `send(null)`；末尾 `initBlePanel()` 绑按钮与状态。
- `ble-test.html`：不依赖摄像头的通路调试页（五指滑杆、角度直发、单条指令、日志）。

## 6. 小程序实现

### 6.1 `core/ble-hand.js`

```js
var bleMod = require('../../core/ble-hand.js');
this.ble = bleMod.createBleHand({ onStatus: function (text, kind) { /* ... */ } });

this.ble.connect(function (err) { /* ... */ });  // 扫描 → 连接 → 找 Service/特征
this.ble.setEnabled(true);
this.ble.send(angles);     // angles[name].flex
this.ble.send(null);       // 手离开画面
this.ble.park();           // 强制回伸直位（关闭采集时）
// this.ble.disconnect(); / this.ble.destroy();
```

| 方法 | 说明 |
| --- | --- |
| `connect(cb)` | `wx.openBluetoothAdapter` → `startBluetoothDevicesDiscovery` → 按名字匹配 `xiaochu` → `createBLEConnection` → `getBLEDeviceServices` / `getBLEDeviceCharacteristics` |
| `disconnect(cb)` / `destroy()` | 断开连接；`destroy` 还会停扫描、关适配器 |
| `send(angles)` | 与网页端同规则：10 Hz、变化去重、`null` 回伸直位 |
| `sendRaw(text, cb)` | 直接写一条字符串 |
| `park(cb)` | 不看开关，强制五指回伸直位 |
| `setEnabled` / `isConnected` / `flexToAngle` / `FINGERS` | 同上 |

与网页端的两点差异：

1. **写入必须串行**：小程序 `wx.writeBLECharacteristicValue` 并发会失败，模块内置单条队列逐条写。
2. **扫描有 20 秒超时**：超时后停止扫描并提示「未找到 xiaochu（确认设备已上电）」；UUID 匹配大小写不敏感。

### 6.2 页面接线（`pages/capture`）

- `data`：`bleConnected` / `bleOn` / `bleStatus`
- 采集控制面板：`BLE 机械手` 行（连接/断开按钮）、`视觉驱动机械手` 开关（仅连接后显示）、`BLE 状态` 行
- `onAnchors`：`track` 帧调 `pushBle(angles)`；`lost` 帧调 `pushBle(null)`
- `stopSession`：关闭采集时 `setEnabled(false)` + `park()`，机械手回伸直位
- 与「上行到 ORCA / 机械手」的 HTTP 桥接相互独立，可同时开启

## 7. 调试步骤

**网页端**

1. 仓库根目录 `python -m http.server 8000`
2. 打开 `http://127.0.0.1:8000/ble-test.html` → 点「连接机械手」→ 选 `xiaochu`
3. 发 `servo_0=90` 看拇指 → 拖动滑杆核对方向
4. 打开 `capture.html`，连接后勾「视觉驱动」

**小程序**

1. 微信开发者工具导入 `miniprogram/`，真机预览（VisionKit 需真机）
2. 打开摄像头 → 点「BLE 机械手」的「连接」→ 状态变「已连接」
3. 打开「视觉驱动机械手」→ 手指动作应同步到机械手
4. 手离开画面 → 机械手应回伸直位

## 8. 限制与下一步

- 网页端 Web Bluetooth 仅桌面 Chrome / Edge，须 `localhost` 或 https；小程序不受此限，但 iOS 首次连接会弹系统蓝牙授权，Android 扫描通常需开启系统定位。
- 单帧 ≤ 20 字节，5 指分 5 条写入；两端都是 10 Hz 节流 + 变化去重。
- 固件可选小修：按各指 `maxOpen` 上电归位、批量帧（一条 `s0,90,90,...` 合并 5 指）、断线/超时回中位。
- 真机验证未完成：小程序端目前只有模拟 `wx` API 的 Node 单测（连接流程、指令序列、去重均通过），需在 iPhone 上实测连接与跟手延迟。

## 9. 作者上位机 XiaochuHand.exe 逆向结论

逆向量化路径：PyInstaller 解包 → `main.pyc`（Python 3.10）→ `xdis` 反汇编。自有逻辑全部在 `main.pyc` 内。

### 9.1 它只有一条指令路径

- 发送格式：`servo_<idx>=<angle>`，写特征 `39dea685-a63e-44b2-8819-9a202581f8fe`
- 默认 `write_without_response`，**不加换行**
- 手势名（`five`/`fist`/…）它**不发给固件**，而是先查本地表再逐指发角度——正好绕开固件手势名路径里 direction 与 maxOpen 语义重复的 bug

### 9.2 PRESET_ANGLES（反编译原样，顺序 = 拇指/食指/中指/无名指/小指）

| 手势 | thumb | index | middle | ring | pinky |
|---|---|---|---|---|---|
| five | 0 | 0 | 0 | 0 | 0 |
| four | 100 | 0 | 0 | 0 | 0 |
| three | 100 | 0 | 0 | 0 | 100 |
| two | 100 | 0 | 0 | 100 | 100 |
| one | 100 | 0 | 100 | 100 | 100 |
| ok | 0 | 100 | 100 | 100 | 100 |
| rock | 100 | 0 | 100 | 100 | 0 |
| love | 0 | 0 | 100 | 100 | 0 |
| fist | 100 | 100 | 100 | 100 | 100 |
| scratch | 0 | 100 | 0 | 0 | 0 |
| come | 0 | 0 | 100 | 0 | 0 |

### 9.3 换算公式（`on_send` 反汇编）

```python
for idx, v in enumerate(preset):          # idx = 0..4 直接就是舵机通道
    angle = int(round(v * 1.8))
    angle = max(0, min(180, angle))
    send(f"servo_{idx}={angle}")
```

界面上滑杆 label 显示的就是这个换算后的角度值。

### 9.4 关键结论

**五根指头共用同一套映射，没有每指偏移、没有每指反向。** 0° 一律当伸直、180° 一律当握拳。

也就是说：作者在装配阶段就把每根舵机的 0° 对齐到了该指的伸直位。这是硬件基准，不是软件魔法。

推论：

- 如果某根指发 0° 不伸直，说明它的舵盘装配基准与作者不同，属于**装配差异**，不是固件或协议问题。
- 解决办法只有两种：改发送端的每指 open/closed（本仓库 `ble-bridge.js` + `ble-test.html` 的标定），或拆舵盘把 0° 重新对齐到伸直位（与作者完全一致）。

### 9.5 与驱动无关的部分

上位机还实现了 Settings（`SETTINGS_UUID`）/ OTA（`3168e56f-6ea1-420d-98f8-08a3b34afc9b`）/ About 三个弹窗，走的是固件里没有的特征，只做配置与固件升级，**不参与手指驱动**。

### 9.6 实测修正：本机中指、小指与作者方向相反

实物驱动实测（2026-11-18）：

- 发出「伸直」值时，中指、小指反而握拳 → 这两根舵机的装配方向与作者相反
- 修正后：

| 指 | 伸直 | 握拳 | 原（作者固件表） |
|---|---|---|---|
| 拇指 | 30 | 180 | 30 / 180 |
| 食指 | 10 | 180 | 10 / 180 |
| 中指 | **0** | **180** | 180 / 0 |
| 无名指 | 0 | 180 | 0 / 180 |
| 小指 | **35** | **180** | 180 / 35 |

修正后五指都是「小角度伸直、180° 握拳」，正好等于作者 0°=伸直的统一假设。

代码位置：

- 网页：`ble-bridge.js` 的 `FINGERS`；标定存储 key 升级为 `bleHandCal_v2`，旧版标定自动失效
- 小程序：`miniprogram/core/ble-hand.js` 的 `FINGERS`
