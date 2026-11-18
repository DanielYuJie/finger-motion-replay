# 手机摄像头接入 PC 的几种方式（及最终选择）

记录「能不能用数据线让电脑用手机的摄像机」这个问题的调研结论与落地方式。

## 一、结论

**能**。三条路，区别在「谁跑识别、谁驱动机械手」。

| 方式 | 需要装什么 | 手机端要做的事 | 延迟 | 识别在哪 | 依赖微信？ |
| --- | --- | --- | --- | --- | --- |
| A. DroidCam / Iriun（USB 模式） | 手机 App + PC 客户端 | 插线、开 App | 30–80 ms | PC 直接 `cv2.VideoCapture` | 不需要 |
| **B. USB 网络共享（Android 原生）** | **什么都不用装** | 设置里开「USB 网络共享」 | 50–150 ms | PC（沿用现有 HTTP 服务） | 需要 |
| C. Wi-Fi | 无 | 无 | 100–300 ms | PC（沿用现有 HTTP 服务） | 需要 |

### 为什么选 B

- B 的传输介质从 Wi-Fi 换成 USB 隧道：同一条服务、同一份代码，**只改小程序里填的地址**，改动量为零。
- 不需要装任何第三方 App/驱动，Android 自带；iOS 无此功能（iOS 只能走 A 类 App 或 C）。
- A 虽然延迟最低、且能彻底脱离小程序，但要装两端软件，且免费版 DroidCam 有 640×480 限制；当前阶段属于「更彻底但更重」的方案，先不做。

### 本机现状（当时核查）

| 项 | 结果 |
| --- | --- |
| 蓝牙适配器 | ✅ 英特尔无线 Bluetooth（正常），意味着 PC 具备直连 `xiaochu` 的能力 |
| 内置摄像头 | ❌ 无 |
| 虚拟摄像头驱动 | ❌ 未安装 |

## 二、方案 B 操作步骤

### 1. 手机侧

1. 数据线连电脑，USB 模式选「文件传输」或「仅充电」皆可（网络共享要求能识别到设备）
2. 设置 → 连接与共享 / 个人热点 → 打开 **USB 网络共享**（不同机型叫「USB 共享网络」）
3. 打开小程序 → 采集页 → 「PC 推理模式」，保持该页在前台（锁屏会停帧）

### 2. 电脑侧

开机服务（已在跑就跳过）：

```powershell
cd "D:\DSPersonal Project Area\finger-motion-replay\pc-server"
& "D:\tools\miniconda\envs\orca-teleop\python.exe" hand_server.py
```

找出手机 USB 网卡对应的地址：

```powershell
Get-NetIPAddress -AddressFamily IPv4 | Select-Object InterfaceAlias, IPAddress
```

新增的那块（通常叫「以太网 x」，描述含 RNDIS / USB）的**默认网关就是手机 IP**，常见是 `192.168.42.129`。

```powershell
Get-NetRoute -AddressFamily IPv4 | Where-Object { $_.DestinationPrefix -eq '0.0.0.0/0' } | Select-Object InterfaceAlias, NextHop
```

### 3. 小程序侧

把「PC 推理模式」页的地址改成 `http://<手机IP>:8767`，点「测试」出现 `PC 在线` 即可。

> 开发者工具需勾「详情 → 本地设置 → 不校验合法域名」，否则 `http://` 请求被拦。

### 4. 防火墙（Windows 最容易卡在这一步）

USB 网卡默认被归类为「公用网络」，入站 8767 会被挡。放行一次即可（管理员 PowerShell）：

```powershell
New-NetFirewallRule -DisplayName "finger-hand-infer" -Direction Inbound `
  -LocalPort 8767 -Protocol TCP -Action Allow -Profile Any
```

验证从手机侧是否通：手机浏览器打开 `http://<手机IP>:8767/health`，能看到 JSON 就说明通了。

## 三、走 B 之后的效果预期

- 上行仍是 240×180 RGBA 的 base64，5 Hz ≈ 1.1 MB/s；USB 隧道带宽远大于此，瓶颈回到 PC 推理（本机实测 21–24 ms/帧）。
- 相对 Wi-Fi 的收益主要是**抖动和丢包**：Wi-Fi 在多人环境下 RTT 波动大，USB 共享基本稳定。
- 手机端仍需前台运行小程序（这是 B 相对 A 的唯一实质劣势）。

## 四、方案 A 的预留（本次未实现）

如果后续要彻底脱离微信，需要补两块，依赖已装好（`bleak 3.1.0` 已安装）：

1. `hand_server.py` 加 `--camera <index>`：`cv2.VideoCapture(index)` 循环读帧，复用现有角度算法，不再走 HTTP 收帧。
2. PC 蓝牙直驱：`bleak` 连 `xiaochu`
   - Service `89d60870-9908-4472-8f8c-e5b3e6573cd1`
   - Write char `39dea685-a63e-44b2-8819-9a202581f8fe`
   - 指令 `servo_<ch>=<angle>`，通道 0–4 = 拇指/食指/中指/无名指/小指
   - 伸直/握拳基准（与 `core/ble-hand.js` 一致）：拇指 30/180、食指 10/180、中指 0/180、无名指 0/180、小指 35/180

前置验证：机械手开机时 PC 蓝牙能否扫到 `xiaochu`（作者 `XiaochuHand.exe` 用 `bleak` 能连，说明可行）。
