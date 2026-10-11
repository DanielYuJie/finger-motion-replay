# ORCA Hand 学习笔记 · 与「视觉采集 + 3D 复现」的结合方案

面向你那个已经跑通的 `finger-motion-replay`。结论先说：**你的视觉管线正好长在 ORCA 官方
遥操作栈所要求的输入契约上，中间只差一层协议适配。** 我已经把这层写出来并验证过了。

- 收藏（克隆）的项目：[orca_core](orca_core) — ORCA Hand 的 Python 控制器，上游
  [`orcahand/orca_core`](https://github.com/orcahand/orca_core)（602★，MIT）
- 适配层：[orca-link](../orca-link) — 28 项验证全绿，含对 ORCA 真实服务端代码的 gRPC 回环
- 生态参考：`orca_teleop` / `orca_sim`（clone 到 ORCA 根目录，见 orca-link/README.md）

---

## 一、orca_core 是什么

ORCA Hand 是一只**开源腱绳驱动灵巧手**（ETH Zurich 系）。`orca_core` 是它的控制包，只管硬件
抽象、标定与关节空间控制，**不含**模型与仿真（那些在 `orcahand_description`、`orca_sim`）。

### 硬件与控制链

| 组件 | 说明 |
|------|------|
| 电机 | Dynamixel（典型 17 个）或 Feetech（二选一，连接时自动探测） |
| 关节编码器 | 绝对角度反馈，走连接板串口，用于闭环 |
| 触觉 | 指尖 Paxini 触觉阵列，同一串口复用 |
| 控制模式 | `current_based_position`（推荐）、`position`、`multi_turn_position`、`current`、`velocity` |

v2 手是 **17 个关节 / 17 个电机一一对应**（`joint_to_motor_map` 里用负 ID 表示反向极性），
所以**关节空间没有腱绳耦合数学要处理**——这一点让直接下关节角变得可行。

### 关节命名（关键）

格式 `{finger}_{joint_type}`，腕是裸 `wrist`：

```
wrist
thumb_cmc  thumb_abd  thumb_mcp  thumb_dip
index_abd  index_mcp  index_pip
middle_abd middle_mcp middle_pip
ring_abd   ring_mcp   ring_pip
pinky_abd  pinky_mcp  pinky_pip
```

**ROM 与中立位都是「度」，且屈曲为正。** 以右手 v2 为例（`models/v2/orcahand-right/config.yaml`）：

| 关节 | ROM | 中立位 |
|------|-----|--------|
| index_mcp | −25 … 100 | 2 |
| index_pip | −15 … 107 | 6 |
| thumb_cmc | −45 … 33 | 0 |
| thumb_mcp | −25 … 100 | 33 |
| thumb_dip | −15 … 107 | 18 |
| wrist | −65 … 35 | −20 |

这个符号约定与你的 `toFlexion()` **天然一致**（0 = 伸直，变大 = 屈曲），是整个结合方案成立的前提。

### 控制 API

```python
from orca_core import load_hand

hand = load_hand(config_path=".../orcahand-right/config.yaml", mock=False)
hand.connect()
hand.init_joints()                      # 会移到中立位

hand.set_joint_positions(               # 接受 dict / OrcaJointPositions / ndarray
    {"index_mcp": 40.0, "index_pip": 55.0},
    num_steps=1,                        # >1 时线性插值，逐步 sleep
)
measured = hand.get_joint_position()    # OrcaJointPositions：.data / .as_dict() / .as_array(ids)

hand.disconnect()
```

- **ndarray 的顺序必须是 `hand.config.joint_ids`**（`wrist` 在最前），不是任意顺序。
- `set_joint_positions` 内部会**先按 ROM 夹取**再下发，这层安全网是免费的。
- **`load_hand(mock=True)` 返回 `MockOrcaHand`**：不探测串口、不发串口包、关节状态在内存里。
  这意味着**没有实体手也能把整条链路跑通**——我的验证就是这么做的。

### 工程上值得抄的地方

`CLAUDE.md` 里有一条原则写得很好，值得放到你自己的项目里：**「永远不要硬编码包能自己解析的东西」**
——手别、电机家族、串口、波特率、有哪些传感器，全部运行时探测，`config.yaml` 是唯一事实来源，
人为写死的值要记 warning 说明它覆盖了什么。我写适配层时也照这个原则做了（端口、路径、ROM 全走配置）。

---

## 二、生态地图（哪个仓库该看、哪个别碰）

我把 `orcahand` 组织下 18 个仓库都过了一遍。与你相关的：

| 仓库 | 作用 | 状态 |
|------|------|------|
| **`orca_core`** | 控制器，唯一的硬件真相来源 | 活跃，MIT，602★ |
| **`orca_teleop`** | **当前正式的遥操作栈** | 活跃（2026-08），**无 LICENSE、issues 已关** |
| `orca_sim` | MuJoCo + Gymnasium 仿真，可无硬件端到端 | 活跃，**无 LICENSE**，README 自称「还在大改」 |
| `orcahand_description` | URDF / MJCF 模型，重定向必需 | 活跃，MIT，407★ |
| `orcahand_hardware` | CAD STL / 3MF 打印件 | 活跃，215★ |
| `orca_retargeter` | 重定向器（旧） | **别碰**：README 61 字节、吃 Vision Pro 数据、输出 tendon 空间的裸 dict、调用已不存在的 API，已被 `orca_teleop` 取代 |
| `manus-client` | Manus 数据手套 SDK 客户端 | **Windows 装不了**（manylinux only），且手套本身可选 |
| `dd_system` / `rwr_system` | 早期遥操作 + ROS 实验 | `dd_system` 已归档 |

### ⚠️ 关于你收藏的这个 fork：它坏在自己唯一的功能上

你给的 `N-B-Studio/orca_core` 相对上游 **`diverged`：领先 3 个提交、落后 35 个**（分叉点
2026-09-25）。领先的 3 个提交是 `support scs-225` / `add 3d model` / `Update README.md`——
也就是说这个 fork 的**全部存在意义就是加 SCS-225 舵机支持**。而它跑不通（我实测复现）：

```
>>> OrcaHandConfig.from_config_path("orca_core/models/v2/orcahand-scs225-right/config.yaml")
HandConfigValidationError: Unknown motor_type: 'scs225'.
Expected one of ['dynamixel', 'feetech'] or omit for auto-detection.
```

原因很直白：fork 只加了 `scs225_client.py` / `dual_scs225_client.py` 两个文件，**没有**改
`constants.py` 的 `SUPPORTED_MOTOR_TYPES`（仍是 `['dynamixel','feetech']`），也没动
`motor_factory.py`——我 grep 过，工厂里**零** scs 引用，意味着那两个 client 没有任何东西会 import。
连带后果：fork 自己加的所有 `orca_rviz_*` / `orca_pose_editor` 等脚本都构造同一个 scs225 配置，
全部加载即失败。另外它的 README 让你 `git checkout scs225-dual-bus`，而那个分支在远端不存在。

还有两点值得知道：

- **fork 的 README 谎报自己的改动**：它声称修改了 `constants.py`、`motor_factory.py`、
  `hardware_hand.py`，但这些文件与**分叉点** `cc607f06` 逐字节相同（我用 blob 哈希比对过：
  `637bf1b985` / `e70d5e28a3` / `622d72046d` 逐一相同）——真正被改的只有 `README.md`
  （`a9634ccd49` → `7c9c179ab1`）。注意别拿 fork 和**当前**上游 HEAD 比，那样这两个文件
  当然不同，会得出错误结论。
- **fork 缺了上游 35 个提交**，其中包括 `hardware/config_registers.py` 和 4 个测试
  （`test_config_registers.py`、`test_feetech_servo_gains.py`、`test_hardware_version.py`、
  `test_motion_settle.py`）；`dynamixel_client.py` 是 1080 行 vs 上游 1763 行。

**建议**：

| 你的情况 | 该用哪个 |
|---|---|
| 手上是 Dynamixel 或 Feetech（ORCA 官方配置） | **用上游** `orcahand/orca_core`。而且 `orca_teleop` 的依赖本来就指向上游（`orca_core @ git+…@main`） |
| 确实要用 SCS-225 / ST3215 | 必须先给 fork 打补丁：把 `scs225` 注册进 `SUPPORTED_MOTOR_TYPES` 与 `motor_factory`，并在**根** `pyproject.toml` 补 `ftservo-python-sdk==2.0.0`（fork 只写在了嵌套的那个 pyproject 里，按它 README 装是不会装上的） |

**好消息**：这不影响我已经做好的东西。我的映射读的是
`models/v2/orcahand-right/config.yaml`——这个文件在 fork 里与上游**逐字节相同**，17 关节、
ROM、中立位全都一致，所以 28 项验证和桥接原型的结论都成立。上游副本我也放在
上游副本按 orca-link/README.md 的说明 clone 到 ORCA 根目录即可对照。

### `orca_teleop` 的架构（这是结合的目标）

```
采端（操作者）                                    机器人端
  MediaPipe / Quest / Manus  ──gRPC HandFrame──▶  IngressServer → landmarks_q
                                                        ↓
                                                  重定向器（retargeter）
                                                        ↓
                                                     actions_q → sink → ORCA 手
```

**唯一的输入契约**是 gRPC 服务 `HandStream.StreamHandFrames`：

```proto
message HandFrame {
  repeated float keypoints = 1;   // 63 个 float = 21 点 × 3，行主序
                                  // 米制、腕部相对、MediaPipe 索引约定
  string handedness = 2;          // "left" | "right"
  int64  timestamp_ns = 3;
  float  wrist_angle_degrees = 4; // 没有腕部追踪就填 0
}
```

服务端只校验三件事：长度必须是 **63**、`handedness` 必须是 `left|right`、能 reshape 成 `(21,3)`。

而下游 `retargeter_worker` 会**无条件把收到的帧标成 `source="mediapipe"`**，默认后端
`adaptive_analytical` 又**只接受 `source="mediapipe"` 的 `(21,3)` 关键点**：

```python
if target_pose.source != "mediapipe":
    raise ValueError("Adaptive analytical backend currently expects MediaPipe-format (21, 3) keypoints")
```

**所以：只要是标准 MediaPipe 21 点，官方默认重定向器开箱即用，上游一行都不用改。** 这是整个方案里
最省力的一环。

---

## 三、你的项目现状（结合前必须知道的两个坑）

### 数据契约（已逐行核对）

每帧推给本地中继的 JSON（`app.js` 的 `pushBridge`，约 30 Hz）：

```json
{"hand": true, "source": "webcam-mediapipe",
 "fingers": {"thumb": {"flex": 42.31, "mcp": 9.4, "pip": 18.2, "dip": 31.05},
             "index": {"flex": 37.8, "mcp": 14.2, "pip": 22.6, "dip": 19.3}}}
```

约定与 ORCA 对得上的部分：**度、屈曲为正、0 = 伸直**。

### 坑 1：拇指的 `mcp/pip/dip` 键名与语义不符

`app.js` 的 `FINGER_DEFS` 里拇指 `joints` 是 `cmc/mcp/ip`，但 flat payload 一律写成
`mcp/pip/dip`。所以：

| payload 键 | 拇指真实语义 | 四指真实语义 |
|---|---|---|
| `mcp` | **CMC** | MCP |
| `pip` | **MCP** | PIP |
| `dip` | **IP** | DIP |

**任何消费方都不能按字面读，必须走 `FINGER_DEFS[name].joints[i]`。** 我的映射层按语义修正了。

### 坑 2：3D 与 MC 用的是归一化图像坐标，而真机重定向要世界坐标

- 你的管线取 `result.landmarks[0]`（归一化图像坐标，x/y ∈ [0,1]，z 尺度同 x）
- ORCA 的 MediaPipe publisher 取的是 **`result.hand_world_landmarks[0]`**（**米制、腕部相对**）
- 两者不可互换：图像 z 受透视和画幅比例影响，不是度量

另外 `flex` 字段是 **0–100 的弯曲索引**（`sum/2.7` 夹到 100），不是角度——UI 上那个 `°` 后缀是误导。
ORCA 侧用不上它，但别把它当角度喂给任何东西。

---

## 四、三条结合路径

### 路径 A（推荐）：你的 app → 适配层 → gRPC → 官方重定向器

```
capture.html（已有：21 点 + 屈曲角）
      │  POST /update（比现在多带 world_landmarks，3 行改动）
      ▼
orca-link 适配层（我写的）              ← 关节角直接映射，或透传世界坐标
      │  gRPC HandFrame（63 float）
      ▼
orca_teleop IngressServer → adaptive_analytical → orca_core → 真手 / MuJoCo
```

**优点**：落在官方架构上；开箱即用地拿到官方重定向（Pinocchio FK + NLopt 逐帧优化，会自己求解
外展和拇指对掌——这是纯角度映射给不出的）；跨机器直接可用（`--server ROBOT_IP:50051`）；上游零改动。

### 路径 B（我同时实现的）：屈曲角 → ORCA 关节角直连

不走重定向器，把 15 个视觉角按仿射映射写进 17 个 ORCA 关节：

```
目标 = neutral + gain × (视觉角 / 满屈曲角) × (rom_max − neutral)    再夹到 ROM
```

**代价**：ORCA 没有视觉输入的关节只能保持中立——**五指外展**和**腕**。视觉管线算不出外展，
而外展恰恰是「灵巧」的关键；ORCA v2 的四个手指也没有 DIP 关节，你的 DIP 读数只能丢弃。
**优点**：零重依赖（不需要 torch / Pinocchio / NLopt），一条 `python orca_bridge.py` 就能跑，
适合先对表、排错、验证 ROM 与符号。

### 路径 C：交给 `orca_sim` 上 MuJoCo 无硬件验证

`orca_teleop` 的 `OrcaHandSimSink` 会把度转弧度喂给 MuJoCo，关节目标与真机同源。
`orca_sim` 需要 Python 3.11 + `gymnasium/mujoco`。适合在没有手的情况下看动作合理性。

**顺序建议**：先用 B 把符号、量程、时序对清楚（我已经跑到全绿），再接 A 拿官方重定向的质量，
最后用 C 或真机验证。

---

## 五、我已经做的与验证过的

适配层在 [orca-link](../orca-link)，`verify.py` **28 项检查全绿**：

```
[1] 映射（17 项）
    关节顺序与 ROM 直接读 ORCA config.yaml（不是硬编码）
    屈曲 180° 输入不越 ROM；屈曲增大时目标单调不减
    拇指 mcp 键确实驱动 thumb_cmc（而不是 thumb_mcp）—— 坑 1 已处理
    四指 DIP 无对应关节、被丢弃而不是误写
    外展与腕按 neutral 策略保持
    默认限速 25°/帧生效，显式置 null 可放开
[2] gRPC 回环（7 项）—— 对 ORCA 真实的 IngressServer 代码
    加载 orca_teleop 的 ingress/server.py 原件（绕开会拖 torch 的包 __init__）
    服务端收到帧；keypoints 形状 (21,3)
    63 个浮点逐点一致，最大误差 1.85e-09
[3] 端到端（4 项）—— OrcaSink + MockOrcaHand
    mock=True 未触碰串口；命令值落到关节上，最大误差 0.000°
    index_mcp 被驱动到 60.80（目标 60.80）
```

另外跑通了真实 HTTP 链路：把 `orca_bridge.py` 作为独立进程起起来，POST 你 app 的原样 payload，
`GET /orca_joints` 返回的 17 个关节角与公式逐项吻合（例如
`thumb_dip = 18 + 0.3105 × (107 − 18) = 45.6`），`hand:false` 帧正确回中立位。

### 对 `app.js` 的改动

`app.js` **新增 12 行**，让世界坐标能被送出来：

1. 取 `result.worldLandmarks[0]` 存进 `lastWorldLandmarks`
2. 声明该变量
3. `pushBridge` 里在 payload 上加 `world_landmarks`（仅当有值时）

这是纯增量改动，并且**实测确认 MC 链路不受影响**：`bridge_server.py` 只读 `fingers`，
POST 带 `world_landmarks` 的 payload 仍返回 `{"ok":true,...}`，`GET /angles` 正常。
`node --check app.js` 通过。

### 路径 A 已经在 Windows 上打通（2026 本轮实测）

原来我把「`adaptive` 额外依赖装不上」列为风险，现在有了确定答案，而且**装上了**：

**`adaptive` extra 在 Windows 上必然失败，但绕得过去。** 我查了 PyPI 上 `pin`、
`cmeel-urdfdom`、`cmeel-tinyxml2` 的**全部历史版本**，win_amd64 轮子数量为 **0**；而
`nlopt`、`torch`、`pytorch-kinematics` 都有。绕法是 Pinocchio 从 conda-forge 取
（`win-64/pinocchio-4.1.0-py312h2d15979_1.conda`，与 pip 的 `pin 4.1.0` 同版本号），
其余照常 pip，`orca_teleop` 本体用 `--no-deps`。

配方与三个坑（v2/v1 资源命名错配、上游 alias 方向反了、conda OpenMP 撞 torch）写在
[orca-link/README.md](../orca-link/README.md)。`setup-teleop-env.ps1` 可一键复现。

**完整链路验证 10/10 通过**（`orca-link/test_full_chain.py`），两侧都是真实代码：

```
合成 21×3 米制 landmark → orca_bridge 的 GrpcSink → gRPC HandFrame
  → orca_teleop 真实 IngressServer → 官方 adaptive_analytical（Pinocchio+NLopt）
  → 17 个 ORCA 关节角（度）
```

### 常驻遥操作也能跑了（三终端）

`teleop_live.py` 用**官方 `pipeline.run()`** 起机器人侧（自己只补一个 sink），配
`orca_bridge.py --sink grpc` 和你的捕获页即可。30Hz 实测 270 帧全部送达、204 次关节目标，
张开 → 握拳 → 张开的往返在关节角上清晰可见（`index_mcp` 9.2 → 83.1 → 9.1）。
命令见 [orca-link/README.md](../orca-link/README.md)。

捕获页默认发 8765（MC 中继），所以要么把 `app.js` 的 `BRIDGE_URL` 改到 8766，要么用
orca-link 的 `forward_to`（默认已开）把 payload 转发回 8765——**同一只手可以同时驱动
MC 机械手和 ORCA 灵巧手**。

**第 4 个坑（已修）**：`adaptive_analytical.py` 用 `open()` 读配置但没给 `encoding`，
中文 Windows（cp936）下**上游自带的配置本身就加载不了**——它含一个 em-dash，实测
`'gbk' codec can't decode byte 0x94 in position 2037`。GBK 解 UTF-8 是按位置对齐的，
所以这个 bug 会时隐时现（多写几行注释就可能从能读变成报错）。修复：覆盖配置保持纯 ASCII。

⚠️ **质量还没验证**：我用的是手工合成的 landmark，解剖学上不严谨——四指 MCP 对握拳有
+68~77° 响应、外展 +15~17°，但 PIP 几乎不动、拇指顶在 ROM 下界。这更像合成姿势的问题，
**不能据此判断重定向质量**。要评估必须喂真实摄像头数据。

---

## 六、下一步与已知风险

1. **拿真实摄像头数据评估重定向质量**（唯一还没做的一步）。链路与常驻进程都已就绪，
   缺的只是真输入：开 `capture.html`（我加的 12 行已让它带 `world_landmarks`）即可；
   想对照可以再跑 ORCA 自带的 `ingress/mediapipe/publisher.py`。
2. **前 30 帧重定向器返回 `None`**（自动尺度标定期），机械手保持不动。这不是卡死，别误判。
3. **返回的关节顺序与 `config.joint_ids` 不一致**（四指在前、`wrist` 在最后）。用 dict 无所谓；
   要拼 ndarray 必须走 `action.as_array(hand.config.joint_ids)`。
4. **`orca_teleop` 没有 LICENSE 文件、GitHub issues 已关闭**。要嵌进商业项目请先自行确认授权；
   出问题只能走 Discord 或上游 PR。
5. **手性必须匹配**：`handedness` 要等于 `hand.config.type`，否则上游直接丢帧。
6. **`orca_core` 的 HTTP API 有个未解决的矛盾**：`POST /joints/position` 文档字符串说 radians，
   而 `OrcaJointPositions` 和重定向器全程是度，源码里没有任何换算。上硬件前必须实测确认。
   （我绕开了这个 API，直接调 `set_joint_positions`，用度。）
7. **`KMP_DUPLICATE_LIB_OK=TRUE` 是权宜之计**：它让两个 OpenMP 运行时共存，官方措辞是
   "unsafe, unsupported... may cause crashes or silently produce incorrect results"。
   真机长跑前建议改成让 nlopt 走 pip、避免 pinocchio 拉 mkl，把这个开关去掉。
8. **Windows 串口**：`orca_core` 官方支持 Windows，但要注意 USB 驱动（usbser / FTDI VCP /
   CH340 / CP210x）、FTDI 的 16ms latency timer，以及串口独占打开。
