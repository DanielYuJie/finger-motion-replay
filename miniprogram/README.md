# 手指运动采集 · 微信小程序版

把视觉主端（[`../capture.html`](../capture.html)）的功能移植到微信小程序。

---

## 结论先说

**能移植，但要换掉检测引擎 —— 而且换来的是更好的东西。**

| | 网页版 | 小程序版 |
|---|---|---|
| 手部检测 | MediaPipe HandLandmarker | **微信 VisionKit 人手检测** |
| 模型体积 | 7.6 MB（随包分发） | **0**（系统能力，本机推理） |
| 关键点 | 21 点 | **21 点，与 OpenPose 同定义** |
| 依赖 | WASM + WebGL | 无（系统 API） |

关键发现：微信 VisionKit 从**基础库 2.28.0** 起提供人手检测，2D 关键点是
**21 点、与 OpenPose 定义相同**；而 OpenPose 的 21 点顺序与 MediaPipe HandLandmarker
**完全一致**（0 手腕 · 1-4 拇指 · 5-8 食指 · 9-12 中指 · 13-16 无名指 · 17-20 小指）。

这意味着浏览器端那套关节角算法可以**原样搬过来**，不用重写。

---

## 移植对照

| 能力 | 网页版 | 小程序版 | 状态 |
|---|---|---|---|
| 手部检测 | MediaPipe WASM | VisionKit（mode 1 摄像头实时） | ✅ 已替换 |
| 21 点关键点 | HandLandmarker | `anchor.points`（同定义） | ✅ 1:1 |
| 关节角解算 | `app.js` | [`core/hand.js`](core/hand.js) | ✅ 1:1，已量化验证 |
| 稳定链路 | `app.js` | [`core/stability.js`](core/stability.js) | ✅ 1:1，已量化验证 |
| 骨架覆盖层 | canvas 2D | canvas 2D | ✅ 已移植 |
| 关节角仪表 / 环表 | CSS + DOM | WXSS + canvas 圆环 | ✅ 已移植 |
| 3D 复现 | Three.js | — | ❌ 见下 |
| MC 桥接 | 本机 HTTP :8765 | — | ❌ 见下 |

### 为什么 3D 复现没移植

小程序没有 DOM，Three.js 需要 WebGL canvas 加一层适配（社区有 `threejs-miniprogram`，
但是基于较旧版本的三方移植）。要做得动用 canvas 2D 的等距投影重画参数化手指更稳、体积更小。
当前版本先画骨架叠加层，3D 留作下一步。

### 为什么 MC 桥接没移植

两道硬约束：

1. 小程序的 `wx.request` **不能访问 `127.0.0.1` / `localhost`**；
2. 请求域名必须在小程序后台配置为**「request 合法域名」且必须是 HTTPS**。

所以要让真手驱动 Minecraft，需要把 [`../bridge_server.py`](../bridge_server.py) 部署到一台
公网服务器上，小程序 POST 到 `https://your.domain/update`。这一条完全可行，但需要你有域名和服务器。

---

## 文件与验证状态

我把「能验证的」和「没法验证的」分得很清楚：

| 文件 | 内容 | 验证状态 |
|---|---|---|
| [`core/hand.js`](core/hand.js) | 21 点定义、关节角解算、坐标归一化 | ✅ **Node 量化验证** |
| [`core/stability.js`](core/stability.js) | One-Euro、显示滞回、出现/离开判定 | ✅ **Node 量化验证** |
| [`app.json`](app.json) / [`app.js`](app.js) / [`app.wxss`](app.wxss) | 全局配置、基础库检查、设计令牌 | ⚠️ 仅语法 / JSON 校验 |
| [`pages/capture/`](pages/capture/) | 页面：VKSession + canvas + 仪表 UI | ⚠️ 逻辑已用桩件集成测试，真机未验证 |
| [`test/verify.js`](test/verify.js) | 自检脚本（纯 Node，43 项断言） | ✅ **43/43 通过** |
| [`project.config.json`](project.config.json) | appid 占位 | ⚠️ 需你填写 |

### 核心的量化验证结果

`core/` 两个文件是平台无关的纯 JS，我用 Node 跑了与浏览器端同一套基准
（静止姿态 + 高斯噪声 σ=0.008，30fps，220 帧）：

| 指标 | 原始 | 平滑后 | 改善 |
|---|---|---|---|
| 关节点抖动（伸直） | 0.00749 | 0.00202 | **↓73.0%** |
| 关节点抖动（弯曲） | 0.00817 | 0.00283 | **↓65.3%** |
| 关节角抖动（伸直） | 7.79° | 1.68° | **↓78.4%** |
| 关节角抖动（弯曲） | 10.02° | 1.99° | **↓80.2%** |
| 读数变化次数 / 120 帧 | 99 | 41 | **↓58.6%** |
| 伸直手指均值误差 | 10.63° | 3.68° | 更接近真值 |

`PresenceGate`（漏检宽限）**9/9 断言通过**：33ms 与 200ms 漏检都保持读数不闪，
超过 250ms 才清空，重新出现能恢复。

### 自己重跑这些验证

自检脚本是纯 Node 的，**不需要微信开发者工具**：

```bash
node miniprogram/test/verify.js
```

当前结果：**43/43 通过**（exit code 0）。它覆盖：

- **A 算法核心**：抖动抑制、精度、显示滞回、`PresenceGate` 九种时序、坐标归一化、关节角契约
- **B 页面逻辑**：用桩件加载**真实的** `pages/capture/index.js`，跑通
  生命周期 → `VKSession` 接线（含 `mode:1`）→ `updateAnchors` → 稳定链路 → `setData` 载荷，
  以及 WXML 绑定的事件/字段与页面是否对得上、关闭时是否释放会话、canvas 缺失时是否容错

改完 `minCutoff` / `beta` 等参数后跑一遍，就能立刻看到抖动抑制比例有没有变差。

> 注意：小程序帧率通常 15–30fps，dt 比浏览器 60fps 大一倍。若沿用浏览器端的
> `minCutoff`，平滑会明显变弱 —— 所以这里把 `minCutoff` 从 1.5/1.2 调到 **1.1/0.9**，
> 上表就是在 30fps 下调好参数后的结果。

### 必须坦白的一点

**本机没有安装微信开发者工具，也没有小程序 AppID，所以页面层我没能真正跑起来。**
`core/` 是平台无关的，我做了上面的量化验证；`pages/` 也用桩件加载真实页面模块做了
43 项集成测试（生命周期、会话接线、防闪烁、载荷结构、释放、容错）。
但**真机专属的部分——canvas 节点 API、camera 组件、VisionKit 的坐标口径——未经任何验证**。
第一次在开发者工具里打开时请按下一节逐条确认。

---

## 首次运行要确认的 4 件事

这四处是我在无法真机验证的情况下必须做的假设，都集中在
[`pages/capture/index.js`](pages/capture/index.js) 顶部，改起来都是一行：

1. **`POINTS_ARE_PIXELS`**（默认 `true`）
   官方文档写 `points` 是「人手 2D 关键点在**图像中的** (x,y) 坐标」，即像素。
   若骨架整体缩成一小团或跑到角落，说明返回的其实已是 0–1 归一化 → 改成 `false`。

2. **`FRAME`**（默认 `720 × 1280`）
   归一化与「cover」映射都需要检测帧尺寸。骨架整体偏移/缩放不对就调这两个值。
   手机竖屏前置摄像头常见 720×1280 或 480×640。

3. **`SHOW_CAMERA_PREVIEW`**（默认 `true`）
   VisionKit 只负责检测、不负责画画面，所以通常要用 `<camera>` 组件预览。
   但两者同时占用摄像头在个别机型上可能冲突 —— 若 `session.start` 的 errno
   指向摄像头被占用，改成 `false` 试试。

4. **镜像**
   前置摄像头预览是镜像的，骨架覆盖层必须跟着镜像，否则左右反。
   代码里按 `mirror` 开关做了映射；若发现骨架与手反着走，就是这里的映射要调。

---

## 怎么跑起来

1. 安装[微信开发者工具](https://developers.weixin.qq.com/miniprogram/dev/devtools/download.html)
2. 导入本目录（`miniprogram/`）作为项目根目录
3. 填写 AppID，或在导入时选择**「测试号」**
4. 调试基础库设为 **≥ 2.28.0**（`app.js` 启动时会检查并弹窗提示）
5. 编译 → 手机上点「开启摄像头」→ 允许权限

---

## 如果继续往下做

| 方向 | 说明 |
|---|---|
| **3D 复现** | canvas 2D 等距投影最稳；要真 3D 就接 `threejs-miniprogram` |
| **MC 桥接** | 公网中继 + request 合法域名（需服务器与域名） |
| **3D 关键点** | 微信 ≥8.1.0 提供 `points3d`（MANO-16 关节定义）——**这是网页版没有的能力**，可做真正的立体手势 |
| **手势分类** | VisionKit 的 `anchor.gesture` 直接给出分类，网页版还需要自己算 ——**同样是白捡的** |
| **静态图片检测** | `mode: 2` + `detectHand({frameBuffer,...})`，可做「拍照识别手势」 |

---

## 设计一致性

界面沿用了网页端的设计令牌（`app.wxss` 里那套 CSS 变量直接搬自
[`../tokens.css`](../tokens.css)）：同一个深色「应用」主题、同一组品牌铜色与功能蓝、
同样的刻度条与环形表语言（环表改用 canvas 画弧，不依赖 CSS 渐变）。
