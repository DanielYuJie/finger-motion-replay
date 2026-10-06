# 手指运动采集 · 3D 复现 · 机械手

从**视觉采集真实手指运动**，到**3D 数字复现**，再到**低成本机械手设计与 Minecraft 联动**的完整探索。
所有网页均可离线运行，媒体与推理全部在本地完成。

```
真实手 ──▶ 摄像头 ──▶ MediaPipe 21 关节点 ──▶ 关节角 θ(t)
                                                  │
                    ┌─────────────────────────────┼─────────────────────────────┐
                    ▼                             ▼                             ▼
              3D 数字复现                    Minecraft 机械手              机械手硬件设计
            (Three.js 骨架)                (Create + CC:Tweaked)        (3D打印 / 冰糕棒)
```

---

## 目录

| 模块 | 入口 | 说明 |
|------|------|------|
| **[视觉采集](#1-视觉采集主端)** | `capture.html` | 摄像头 + 手部关节点 + 关节角 + MC 桥接开关 |
| **3D 数字复现** | 同上页内嵌 | Three.js 骨架 + 参数化手指，实时跟随 |
| **[体感游戏](#3-体感游戏)** | `games.html` | 游戏中心（搭积木 / 切水果） |
| **[机械手硬件设计](#4-机械手硬件设计)** | `index.html` | 图纸、BOM、淘宝下单文案、冰糕棒替代方案 |
| **[Minecraft 方案](#5-minecraft-机械手)** | `mc-hand.html` | Create 机构设计（坐标表 + 避坑） |
| **[MC 桥接](#6-mc-桥接路线-a)** | `mc-bridge-guide.html` | 让真手驱动游戏内机械手（完整指南） |
| **技术报告** | `report.html` | 当日工作总结（图文） |
| **[双手虚拟装机](#3-体感游戏)** | `assemble.html` | 两手协作装配（实验性） |

---

## 1. 视觉采集（主端）

**入口：`capture.html`**　·　核心：`app.js` + `replay3d.js` + `styles.css`

- 摄像头预览、设备切换、镜像、截图、全屏
- **MediaPipe HandLandmarker** 21 关节点，本地推理（模型在 `vendor/`）
- 实时解算五指 **MCP / PIP / DIP**（拇指 CMC / MCP / IP）关节角
- 指尖轨迹、骨架叠加、角度标注
- **3D 复现**：关节点驱动骨架 + 按关节角弯曲的参数化手指，球坐标轨道相机（阻尼、指针捕获）

### 关键实现点

| 问题 | 处理 |
|------|------|
| CDN 版本号不存在导致 404 | 下载真实存在的 `tasks-vision@0.10.21` + 模型到 `vendor/` |
| `import('vendor/…')` 被当包名 | 改用 `new URL('./vendor/…', location.href).href` |
| 检测循环跑一帧就停 | `videoTime` 非标准属性，改用 `currentTime` |
| 模型加载失败显示 `[object Event]` | 增加错误序列化，区分 Event / Error |
| GPU delegate 失败 | 自动回退 CPU |
| 摄像头权限不弹窗 | 脚本与模型解耦，事件优先绑定 |

---

## 3. 体感游戏

**入口：`games.html`**（游戏中心）

| 游戏 | 文件 | 玩法 |
|------|------|------|
| 体感搭积木 | `game.html` + `game3d.js` | 手掌牵引方块、捏合放置；方块持续横移，手静止即脱控；握拳急刹 |
| 体感切水果 | `fruit.html` | 手势轨迹切割 |
| 双手虚拟装机 | `assemble.html` | 两手各自抓取硬件零件，装入机箱卡槽（实验性） |

---

## 4. 机械手硬件设计

**入口：`index.html`**　·　文档：[`淘宝3D打印交付包.md`](淘宝3D打印交付包.md) · [`最小可抄文件清单.md`](最小可抄文件清单.md)

- **方案**：欠驱动腱绳五指手，每指三节，单腱绳牵引、弹簧回位，舵机置腕部
- **两条路线**：3D 打印版（约 ¥85–110）／ 冰糕棒版（约 ¥25–40）
- **交付物**：零件图纸（SVG）、BOM、打印参数、**可直接复制的淘宝下单文案**
- **实物效果图**：`mech-hand-icecream-stick.png`（冰糕棒版）
- **开源对标**：FreeHand / InMoov / Galileo / tendra-hand 的最小下载清单

---

## 5. Minecraft 机械手

**入口：`mc-hand.html`**　·　效果图：`mc-hand-render.html` / `mc-hand-render.png`

用 Create 模组把硬件方案在方块世界里复现：

| 实物 | Create 对应 |
|------|-------------|
| 关节 | 机械轴承（朝向 = 旋转轴） |
| 指骨 | 从轮毂**垂直伸出**的方块 |
| 舵机 | 创造马达 / 转速控制器 |
| 使能信号 | 离合器 + 拉杆 |
| 角度控制 | 序列换挡（1 脉冲 = 固定角度） |
| 腱绳 | 绳索滑轮 |

**关键规则**：轴承朝向决定旋转轴；正面那块是「轮毂」落在轴上；**只有垂直于轴伸出的方块才会被带动**。组装方式为右键轴承。

效果图由坐标数据程序化渲染（等距投影，1051 个方块），生成脚本见 `render_*.py`。

---

## 6. MC 桥接（路线 A）

**入口：`mc-bridge-guide.html`**　·　代码：`bridge_server.py` + `mc_hand.lua`

让**真实的手驱动游戏内机械手**：

```
摄像头 → MediaPipe（浏览器） → POST /update
                                    ↓
                         bridge_server.py (127.0.0.1:8765)
                                    ↓ GET /angles
                         CC:Tweaked 电脑（mc_hand.lua）
                                    ↓ 红石脉冲 ×5 面
                         Create 序列换挡 → 机械手跟随
```

**核心难点**：Create 没有角度传感器，只能**增量式**控制——脚本内部记录每指当前累计角度，每次只补「还差几个脉冲」。

| 文件 | 作用 |
|------|------|
| `bridge_server.py` | 零依赖中继服务（纯标准库），30Hz 收角度、供轮询，1 秒无数据自动判定手离开 |
| `mc_hand.lua` | CC 控制脚本：轮询 → 增量换算 → 5 面红石驱动五指 |
| `capture.html` | 采集页，勾选「MC 桥接」即开始推送 |

### 快速启动

```bash
# 1) 启动中继服务
python bridge_server.py          # 监听 127.0.0.1:8765

# 2) 浏览器打开 capture.html，开摄像头，勾选「MC 桥接」
# 3) 游戏内：CC 电脑执行 mc_hand.lua
```

依赖：Minecraft 1.20.1 + Forge + **Create 6.0.8** + **CC:Tweaked 1.120.2**，
且 `config/computercraft-server.toml` 中 `http.enabled = true` 并放行 `127.0.0.1`。

---

## 快速开始

本仓库所有网页均为纯静态 + 本地资源，**无需联网、无需构建**。
用任意静态服务器托管根目录后打开入口页即可：

```bash
python -m http.server 8000
# 然后访问 http://localhost:8000/capture.html
```

> 注意：`vendor/` 已内置 MediaPipe（tasks-vision + 手部模型 + WASM）与 Three.js，
> 因此识别与 3D 全部离线可用。模型推理在浏览器内完成，**视频不上传**。

---

## 目录结构

```
├── capture.html / app.js / styles.css     # 视觉采集主端
├── replay3d.js                            # Three.js 3D 复现
├── games.html / game.html / game3d.js     # 体感游戏
├── fruit.html / assemble.html             # 切水果 / 双手装机
├── index.html / hand-design.*             # 机械手硬件设计页
├── mc-hand.html                           # Create 机械手方案
├── mc-hand-render.html                    # 结构效果图（带标注）
├── mc-bridge-guide.html                   # MC 桥接完整指南
├── bridge_server.py                       # 关节角中继服务
├── mc_hand.lua                            # CC:Tweaked 控制脚本
├── report.html                            # 技术报告
├── render_*.py                            # 等距体素渲染脚本
├── 淘宝3D打印交付包.md                     # 硬件采购/下单文档
├── 最小可抄文件清单.md                     # 开源参考清单
└── vendor/                                # MediaPipe + Three.js（离线）
```

---

## 环境要求

| 场景 | 要求 |
|------|------|
| 网页（采集 / 游戏 / 3D） | Chrome / Edge / Firefox，需摄像头权限，建议 https 或 localhost |
| MC 桥接 | Python 3.9+（仅标准库）；Minecraft 1.20.1 + Forge + Create + CC:Tweaked |
| 3D 打印 | 桌面 FDM 打印机，PLA，层高 0.2mm |
