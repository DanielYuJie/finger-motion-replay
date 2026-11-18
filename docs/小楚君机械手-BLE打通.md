# 小楚君机械手 · BLE 打通记录（网页端）

> 目标：把本仓库的视觉端（MediaPipe 21 点 → flex 0–100）接到小楚君固件（ESP32-C3 + PCA9685 + 5×SG90）。
> 本文覆盖**网页端**；小程序移植另开文档。

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

## 4. 网页端实现

### 4.1 数据流

```
MediaPipe 21 点
  → computeFingerAngles：flex = min(100, (mcp + pip + dip) / 2.7)
  → ble-bridge.js：angle = open + flex/100 * (closed - open)
  → ASCII "servo_<ch>=<angle>"（≤ 12 字节）
  → BLE 写特征（无响应写）
```

### 4.2 `ble-bridge.js`

全局 `window.BleHand`：

| 方法 | 说明 |
| --- | --- |
| `connect()` | `requestDevice`（namePrefix `xiaochu`）→ GATT → Service → 写特征 |
| `disconnect()` | 主动断开并清状态 |
| `send(fingers)` | 接收 `{thumb:{flex}, ...}`；节流 10 Hz；角度变化 ≤1° 不重复写；`null` 触发全指回伸直位 |
| `sendRaw(cmd)` | 直接写一条字符串，调试用 |
| `setEnabled(bool)` / `isEnabled()` | 视觉驱动开关 |
| `onStatus(cb)` / `isConnected()` | 状态回调与连接查询 |
| `flexToAngle(finger, flex)` | 暴露换算函数 |
| `FINGERS` | 标定表（与固件一致） |

内部：单飞循环（`flushing`）合并高频帧，避免 30 Hz 视觉帧压垮写队列；`gattserverdisconnected` 自动清空特征并把状态置为断开。

### 4.3 页面接线

- `capture.html`：MC 桥接上方新增「BLE 机械手」面板（连接/断开、视觉驱动复选框、状态、调试页入口）；`ble-bridge.js` 在 `app.js` 之前加载。
- `app.js`：检测到手的帧（`pushBridge(angles)` 之后）调用 `BleHand.send(angles)`；丢手帧（`pushBridge(null)` 之后）调用 `BleHand.send(null)` 回伸直位；末尾 `initBlePanel()` 绑定按钮与状态。
- `ble-test.html`：不依赖摄像头的通路调试页（五指滑杆、角度直发、单条指令、日志）。

## 5. 调试步骤

1. 仓库根目录启动 `python -m http.server 8000`。
2. 打开 `http://127.0.0.1:8000/ble-test.html`。
3. 点「连接机械手」，弹窗中选 `xiaochu`。
4. 「单条指令」发 `servo_0=90`，看拇指是否转动 → 验通道。
5. 拖动五指滑杆，核对每根手指方向是否与滑杆一致 → 验标定。
6. 打开 `http://127.0.0.1:8000/capture.html`，连接后在面板勾选「视觉驱动」→ 验视觉到机械手。

## 6. 限制与下一步

- Web Bluetooth 仅桌面 Chrome / Edge；页面须 `localhost` 或 https。
- 单帧 ≤ 20 字节，5 指需 5 条写入；当前 10 Hz 节流 + 变化去重。
- 下一步（小程序）：`wx.openBluetoothAdapter` → `startBluetoothDevicesDiscovery` → `createBLEConnection` → `getBLEDeviceServices` / `getBLEDeviceCharacteristics` → `writeBLECharacteristicValue`，参数与本文契约一致。
- 固件可选小修：按各指 `maxOpen` 上电归位、批量帧（一条 `s0,90,90,...`）、断线/超时回中位。
