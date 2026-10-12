# 手指运动采集 · 3D 复现 · 机械手

从**视觉采集真实手指运动**，到**3D 数字复现**，再到**低成本机械手设计与 Minecraft 联动**。
所有页面均为纯静态资源，**全程离线**：手部模型在本地推理，视频不上传。

```
真实手 ──▶ 摄像头 ──▶ MediaPipe 21 关节点 ──▶ 关节屈曲角 θ(t)
                                                  │
                    ┌─────────────────────────────┼─────────────────────────────┐
                    ▼                             ▼                             ▼
              3D 数字复现                    Minecraft 机械手              机械手硬件设计
            (Three.js 骨架)                (Create + CC:Tweaked)        (3D打印 / 冰糕棒)
```

---

## 页面

| 页面 | 入口 | 说明 |
|------|------|------|
| **视觉主端** | [`capture.html`](capture.html) | 摄像头 + 21 关节点 + 关节屈曲角 + 3D 复现 + MC 桥接开关 |
| **硬件设计** | [`index.html`](index.html) | 3D 打印交付包：零件图、可交互结构演示、BOM、可复制下单文案 |
| **MC 方案** | [`mc-hand.html`](mc-hand.html) | 用 Create 模组复现机械手机构（坐标表 + 避坑） |
| **桥接指南** | [`mc-bridge-guide.html`](mc-bridge-guide.html) | 让真手驱动游戏内机械手的完整链路 |
| **技术报告** | [`report.html`](report.html) | 方案调研、验证过程与下一步路线 |

五个页面共用同一套导航与设计系统，任意页面都能一键回到视觉主端。

---

## 1. 视觉主端

**入口：[`capture.html`](capture.html)**　·　核心：`app.js` + `replay3d.js` + `app.css`

- 摄像头预览、设备切换、镜像、截图、全屏
- **MediaPipe HandLandmarker** 21 关节点，本地推理（模型在 `vendor/`，无需外网）
- 实时解算五指关节角：拇指 CMC / MCP / IP，其余四指 MCP / PIP / DIP
- 指尖轨迹、骨架叠加、角度标注
- **3D 复现**：关节点驱动骨架 + 按关节角弯曲的参数化手指，球坐标轨道相机

### 关节角的口径

界面里显示的是**屈曲角**，与机器人学习惯一致：

| 值 | 含义 |
|----|------|
| `0°` | 完全伸直 |
| 数值变大 | 弯曲变多 |

MediaPipe 输出的是关节**内角**（伸直时约 180°），`app.js` 中的 `toFlexion()` 统一换算成屈曲角，
再驱动 3D 模型与 MC 桥接。三个角分别取自真实的三个关节顶点，**没有一个是复用或估算的**；
近端关节（拇指 CMC / 四指 MCP）以手腕 landmark 0 作为掌骨方向的参考点。

### 识别稳定性

MediaPipe 逐帧输出的关节点本身带噪声，直接使用会让骨架、读数、3D 模型一起抖。
`app.js` 里有一条三级稳定链路：

| 环节 | 做法 | 作用 |
|------|------|------|
| 关节点 | **One Euro 滤波器**（21 点 × 3 轴各自独立） | 静止时强抑制抖动，快速移动时自动放宽以保持跟手 |
| 关节角 | 同样用 One Euro，且**不设死区** | 无偏地平滑；实测伸直手指的估计误差由约 11.7° 降到约 3.0° |
| 显示 | 0.4° 显示滞回 + 丢失手后 250ms 宽限 | 数字与刻度不跳；单帧漏检不会让读数闪成「—」 |

关键点是**死区只作用于显示**：3D 复现与 MC 桥接拿到的始终是真实的平滑值，
不会因为界面「看起来稳」而被卡住不更新。

可调参数集中在 `app.js` 顶部：`LM_MIN_CUTOFF` / `LM_BETA`（关节点）、
`ANGLE_MIN_CUTOFF` / `ANGLE_BETA`（关节角）、`DISPLAY_DEADBAND`（显示滞回）、
`MISS_GRACE_MS`（丢失宽限）。想更跟手就调大 `*_BETA` 与 `DISPLAY_DEADBAND`。

### 快速开始

```bash
python -m http.server 8000
# 打开 http://localhost:8000/capture.html
```

> 摄像头权限需要 `https` 或 `localhost`。

---

## 2. 机械手硬件设计

**入口：[`index.html`](index.html)**　·　文档：[`淘宝3D打印交付包.md`](淘宝3D打印交付包.md) · [`最小可抄文件清单.md`](最小可抄文件清单.md)

- **方案**：欠驱动腱绳五指手，每指三节，单腱绳牵引、弹簧回位，舵机置腕部
- **两条路线**：3D 打印版（约 ¥85–110）／ 冰糕棒版（约 ¥25–40）
- **交付物**：零件图纸（SVG）、BOM、打印参数、**可直接复制的淘宝下单文案**
- **实物效果图**：`mech-hand-icecream-stick.png`（冰糕棒版）
- **开源对标**：FreeHand / InMoov / Galileo / tendra-hand 的最小下载清单

冰糕棒替代路线的详细说明见 [`report.html`](report.html) 与 [`最小可抄文件清单.md`](最小可抄文件清单.md)。

---

## 3. Minecraft 机械手

**入口：[`mc-hand.html`](mc-hand.html)**　·　效果图：`mc-hand-render.png`

用 Create 模组把硬件方案在方块世界里复现：

| 实物 | Create 对应 |
|------|-------------|
| 关节 | 机械轴承（朝向 = 旋转轴） |
| 指骨 | 从轮毂**垂直伸出**的方块 |
| 舵机 | 创造马达 / 转速控制器 |
| 使能信号 | 离合器 + 拉杆 |
| 角度控制 | 序列换挡（1 脉冲 = 固定角度） |
| 腱绳 | 绳索滑轮 |

**关键规则**：轴承朝向决定旋转轴；正面那块是「轮毂」落在轴上；**只有垂直于轴伸出的方块才会被带动**。
组装方式为右键轴承。效果图由坐标数据程序化渲染（等距投影），生成脚本见 `render_annotated_png.py`。

---

## 4. MC 桥接（让真手驱动游戏内机械手）

**入口：[`mc-bridge-guide.html`](mc-bridge-guide.html)**　·　代码：`bridge_server.py` + `mc_hand.lua`

```
摄像头 → MediaPipe（浏览器） → POST /update
                                    ↓
                         bridge_server.py (127.0.0.1:8765)
                                    ↓ GET /angles
                         CC:Tweaked 电脑（mc_hand.lua）
                                    ↓ 红石脉冲 ×5 面
                         Create 序列换挡 → 机械手跟随
```

**核心难点**：Create 没有角度传感器，只能**增量式**控制——脚本内部记录每指当前累计角度，
每次只补「还差几个脉冲」。

| 文件 | 作用 |
|------|------|
| `bridge_server.py` | 零依赖中继服务（纯标准库），30Hz 收角度、供轮询，1 秒无数据自动判定手离开 |
| `mc_hand.lua` | CC 控制脚本：轮询 → 增量换算 → 5 面红石驱动五指 |
| `capture.html` | 采集页，勾选「推送关节角到 CC:Tweaked」即开始推送 |

### 快速启动

```bash
# 1) 启动中继服务
python bridge_server.py          # 监听 127.0.0.1:8765

# 2) 浏览器打开 capture.html，开摄像头，勾选「推送关节角到 CC:Tweaked」
# 3) 游戏内：CC 电脑执行 mc_hand.lua
```

依赖：Minecraft 1.20.1 + Forge + **Create 6.0.8** + **CC:Tweaked 1.120.2**，
且 `config/computercraft-server.toml` 中 `http.enabled = true` 并放行 `127.0.0.1`。

---

## 5. ORCA 灵巧手联动（真机）

把同一份视觉输出接到**真实的开源灵巧手** [ORCA Hand](https://github.com/orcahand/orca_core) 上。
代码在 [`orca-link/`](orca-link/)，完整方案与踩坑记录见 [`docs/ORCA集成方案.md`](docs/ORCA集成方案.md)。

```
capture.html ──POST /update（多带 world_landmarks）──▶ orca-link:8766
                                                        ├─▶ ORCA 官方重定向器 ─▶ 17 个关节角 ─▶ 真手 / 仿真
                                                        └─▶ 转发 8765 ─▶ CC:Tweaked 机械手
```

**同一只手可以同时驱动 Minecraft 机械手和真实灵巧手。**

与第 4 节的区别：MC 机械手每指只有一个自由度，所以只用到 `flex` 索引；ORCA 有 17 个自由度，
需要 **`worldLandmarks`**（米制、腕部相对）才能让官方重定向器（Pinocchio + NLopt 逐帧优化）
解出各指的屈伸**与外展**——外展是视觉屈曲角给不出来的。`app.js` 为此加了 12 行把世界坐标
一并带在 payload 上（`bridge_server.py` 只读 `fingers`，所以 MC 链路不受影响）。

### 快速启动

```powershell
# 0) 环境：Pinocchio 在 Windows 上没有 pip 轮子，脚本会从 conda-forge 取
powershell -File orca-link\setup-teleop-env.ps1

# 1) 机器人侧常驻（官方 orca_teleop pipeline）。没有硬件就先用 --drive sim（MuJoCo 仿真，会出画面）
<conda env>\python.exe orca-link\teleop_live.py --drive sim     # 或 mock / print / real

# 2) 适配层：收浏览器帧，经 gRPC 推给机器人侧
<conda env>\python.exe orca-link\orca_bridge.py --sink grpc

# 3) 把 app.js 的 BRIDGE_URL 改成 http://127.0.0.1:8766/update，再照第 1 节起页面
```

没有摄像头时也能验证整条链路：`python orca-link\drive_synthetic.py --seconds 9 --hz 30`

### 已验证的

| 验证 | 结果 |
|---|---|
| 屈曲角 → ORCA 关节映射（ROM 夹取、拇指键语义、限速、关节顺序） | 28/28 |
| gRPC 回环（对 orca_teleop **真实** `IngressServer` 原件） | 63 个浮点误差 1.85e-09 |
| `MockOrcaHand` 端到端（命令值落到关节） | 最大误差 0.000° |
| 完整链路 landmark → gRPC → 官方重定向器 → 17 关节角 | 10/10 |
| 常驻遥操作（三进程、30Hz） | 270 帧全送达；张开→握拳→张开在 `index_mcp` 上 9.2 → 83.1 → 9.1 |
| **MuJoCo 仿真（无硬件）** | 同一链路驱动 `orca_sim` 的 v2 手，渲染帧实测动作往返成立 ↓ |

![张开 → 握拳 → 张开](orca-link/docs/orca-sim-open-fist-open.png)

三段代表帧：驱动前（左）、推入"握拳"landmark 时（中）、推回"张开"时（右）。
跑法：`orca-link\teleop_live.py --drive sim`，渲染帧写到 `orca-link/sim_frames/`。

> 中间那帧主要是**掌指关节在弯、远端指节偏直**——不是重定向器的问题，而是合成 landmark
> 解剖学上不严谨（PIP 的命令值本身只有 -10.0 → -8.7）。屈伸分配是否合理，需要真实摄像头数据。

**尚未验证**：重定向质量。上面用的是手工合成的 landmark，解剖学上不严谨，
需要真实摄像头数据来评估。

### Windows 上的四个坑（都已在代码里绕开）

1. **`adaptive` 额外依赖装不上**：`pin` / `cmeel-urdfdom` / `cmeel-tinyxml2` 在 PyPI 上
   **从来没有 Windows 轮子**。绕法：Pinocchio 走 conda-forge，`orca_teleop` 用 `--no-deps`。
2. **模型版本要用「v2 手配置 + v1 URDF」**：`orcahand_description` 里 v2 的 URDF/MJCF 是
   CAD 命名（`I-AP-R_d95d02d1`），v2 帧表要的语义名一个都对不上；v1 URDF 才是语义命名。
3. **上游 `joint_name_aliases` 方向反了**：`{thumb_pip: thumb_cmc}` 两种组合都不生效，
   改成 `{thumb_cmc: thumb_pip}` 才打通。
4. **重定向配置必须纯 ASCII**：`adaptive_analytical.py` 用 `open()` 读配置但没给 `encoding`，
   中文 Windows（cp936）下**上游自带的配置本身就加载不了**（含 em-dash）；且 GBK 解 UTF-8
   是按字节位置对齐的，所以这个 bug 时隐时现。

授权提示：`orca_core` 与 `orcahand_description` 是 MIT；**`orca_teleop` 没有 LICENSE 文件、
issues 也已关闭**，商用前请自行确认。

---

## 目录结构

```
├── capture.html / app.js / app.css        # 视觉主端
├── replay3d.js                            # Three.js 3D 复现
├── index.html / hand-design.*             # 机械手硬件设计页
├── mc-hand.html                           # Create 机械手方案
├── mc-bridge-guide.html                   # MC 桥接完整指南
├── report.html                            # 技术报告
├── bridge_server.py                       # 关节角中继服务
├── mc_hand.lua                            # CC:Tweaked 控制脚本
├── render_annotated_png.py                # 等距体素效果图生成脚本
├── tokens.css / base.css / components.css # 设计系统
├── doc.css / report.css                   # 文档主题与报告专用样式
├── 淘宝3D打印交付包.md                     # 硬件采购/下单文档
├── 最小可抄文件清单.md                     # 开源参考清单
├── docs/ORCA集成方案.md                    # ORCA 灵巧手联动的完整方案
├── orca-link/                             # 视觉 → ORCA 灵巧手适配层（第 5 节）
└── vendor/                                # MediaPipe + Three.js（离线）
```

设计系统分三层：`tokens.css` 是唯一的颜色/字号/间距/圆角/阴影来源，
`base.css` 负责重置与排版，`components.css` 是共用组件；页面样式只负责自身布局。
主题有两套：深色「应用」主题（视觉主端）与浅色「文档」主题（其余四页）。

---

## 环境要求

| 场景 | 要求 |
|------|------|
| 网页（采集 / 3D / 文档） | Chrome / Edge / Firefox，需摄像头权限，建议 https 或 localhost |
| MC 桥接 | Python 3.9+（仅标准库）；Minecraft 1.20.1 + Forge + Create + CC:Tweaked |
| ORCA 灵巧手联动 | Python 3.12（orca_teleop 限定 `<3.13`）+ conda-forge 的 Pinocchio/NLopt；需单独 clone `orca_core` / `orca_teleop` / `orcahand_description` |
| 3D 打印 | 桌面 FDM 打印机，PLA，层高 0.2mm |
