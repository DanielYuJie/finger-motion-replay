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
| MC 桥接 | wx.request → 局域网中继 :8765 | — | ✅ 已实现（局域网方案，见下） |

### 为什么 3D 复现没移植

小程序没有 DOM，Three.js 需要 WebGL canvas 加一层适配（社区有 `threejs-miniprogram`，
但是基于较旧版本的三方移植）。要做得动用 canvas 2D 的等距投影重画参数化手指更稳、体积更小。
当前版本先画骨架叠加层，3D 留作下一步。

### 局域网桥接（已实现，可驱动 MC 机械手与 ORCA 灵巧手）

两道硬约束依然存在，但**开发/真机验证阶段有零成本绕法**：

1. 小程序的 `wx.request` **不能访问 `127.0.0.1` / `localhost`** → 电脑上以 `--host 0.0.0.0` 启动中继，小程序填**电脑的局域网 IP**；
2. 请求域名必须是 HTTPS 合法域名 → 开发者工具「详情 → 本地设置」勾选**「不校验合法域名」**（真机调试/预览同样生效）。

已在 `pages/capture/index.js` 实现「上行到 ORCA / 机械手」开关 + 地址输入 + 状态显示，
payload 与网页端 `app.js` 完全一致（`source: 'miniprogram-visionkit'`），10Hz 节流推送，
手丢失/关闭时推 `hand:false` 让机械手回零。

**地址填哪个决定驱动谁**（两个中继默认都只监听 `127.0.0.1`，不开 `--host 0.0.0.0` 手机永远连不上）：

| 填的地址 | 中继 | 效果 |
|---|---|---|
| `IP:8765` | `bridge_server.py` | 只驱动 MC 机械手 |
| `IP:8766` | `orca-link/orca_bridge.py` | 驱动 ORCA（映射到 17 个关节），**并异步把原始 payload 转发给 8765**，MC 机械手照样动 |

想「一只手同时驱动两边」就填 **8766**。

联调步骤：
1. 电脑起中继（ORCA 那条要另开一个窗口起 MC 中继以接收转发）：
   - `python bridge_server.py --host 0.0.0.0`
   - `python orca-link/orca_bridge.py --sink print --host 0.0.0.0`
2. （仅 MC）Minecraft + CC 电脑执行 `mc_hand.lua`（轮询 `127.0.0.1:8765/angles` 不变）
3. iPhone 与电脑连**同一 Wi-Fi**；开发者工具勾选不校验合法域名
4. 小程序开启上行开关，地址填 `电脑局域网IP:8766`（查 IP：电脑上 `ipconfig`）

> 正式发布时上述绕法失效（合法域名强制 HTTPS），仍需把中继部署到公网服务器，
> 小程序 POST `https://your.domain/update` —— 需要域名和服务器，留待后续。

---

## 文件与验证状态

我把「能验证的」和「没法验证的」分得很清楚：

| 文件 | 内容 | 验证状态 |
|---|---|---|
| [`core/hand.js`](core/hand.js) | 21 点定义、关节角解算、坐标归一化 | ✅ **Node 量化验证** |
| [`core/stability.js`](core/stability.js) | One-Euro、显示滞回、出现/离开判定 | ✅ **Node 量化验证** |
| [`app.json`](app.json) / [`app.js`](app.js) / [`app.wxss`](app.wxss) | 全局配置、基础库检查、设计令牌 | ⚠️ 仅语法 / JSON 校验 |
| [`pages/capture/`](pages/capture/) | 页面：VKSession + WebGL 画面/骨架 + 仪表 UI | ✅ **iPhone 真机验证通过** |
| [`core/glview.js`](core/glview.js) | WebGL 渲染层：YUV 相机预览 + 骨架（照官方 `yuvBehavior.js`） | ✅ **iPhone 真机验证通过** |
| [`test/verify.js`](test/verify.js) | 自检脚本（纯 Node，51 项断言） | ✅ **51/51 通过** |
| [`project.config.json`](project.config.json) | appid 与编译配置 | ✅ 已填 |

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

当前结果：**51/51 通过**（exit code 0）。它覆盖：

- **A 算法核心**：抖动抑制、精度、显示滞回、`PresenceGate` 九种时序、坐标归一化、关节角契约
- **B 页面逻辑**：用桩件加载**真实的** `pages/capture/index.js`，跑通
  生命周期 → `VKSession` 接线（含 `mode:1`、`version:'v1'`、`gl`）→ `updateAnchors`
  → 稳定链路 → `setData` 载荷，以及 WXML 绑定的事件/字段是否对得上、
  **`<camera>` 组件是否被误加回来**、`start` 后是否真的启动了帧循环、
  关闭时是否释放会话、canvas 缺失时是否容错

改完 `minCutoff` / `beta` 等参数后跑一遍，就能立刻看到抖动抑制比例有没有变差。

> 注意：小程序帧率通常 15–30fps，dt 比浏览器 60fps 大一倍。若沿用浏览器端的
> `minCutoff`，平滑会明显变弱 —— 所以这里把 `minCutoff` 从 1.5/1.2 调到 **1.1/0.9**，
> 上表就是在 30fps 下调好参数后的结果。

### 真机验证状态（已不是纸面推断）

这个页面**已经在真机 iPhone 上跑过了**，第一轮的结果是：`session.start` 返回成功、
相机画面正常，但 **`updateAnchors` 一次都没触发** —— 状态显示「采集中 · 识别中」，
而帧率与角度读数恒为 `—`。

根因是**架构层面的，不是算法**。对着官方实时示例源码（
[`miniprogram-demo/packageAPI/pages/ar/hand-detect`](https://github.com/wechat-miniprogram/miniprogram-demo/tree/master/miniprogram/packageAPI/pages/ar/hand-detect)）
逐行核对后确认有三处：

| # | 问题 | 依据 |
|---|---|---|
| 1 | **从不调用 `session.getVKFrame()`** | 官方文档原话：`getVKFrame`「每调用一次都会触发一次**帧分析过程**」。帧分析由它驱动 —— 不调用就永远没有 anchor，而 `start` 依然是成功的。这是「零回调」的直接原因 |
| 2 | 用了 `<camera>` 组件做预览 | 官方**所有**实时示例的 WXML 里 `<camera>` 标签数为 **0**，画面一律来自 `session.getVKFrame()`；实时模式下摄像头由 VKSession 自己持有 |
| 3 | 把 `points` 当成像素处理 | 官方示例的换算 `x * 2 - 1, 1 - y * 2` 是「0..1 → NDC」，只有 `x,y ∈ [0,1]` 才成立 → **`points` 是 0–1 归一化坐标** |

现已按官方架构重写：`createVKSession({ track:{hand:{mode:1}}, version:'v1', gl })`
→ `session.requestAnimationFrame` 帧循环 → `getVKFrame()` → `frame.getCameraTexture(gl,'yuv')`
经 YUV 着色器上屏（见 [`core/glview.js`](core/glview.js)），骨架也画在同一块 WebGL 画布内
（native canvas 互相叠加不保证合成，官方同样用 GL 画点）。

**已真机验证通过（iPhone）**。重编译后用「真机调试」运行，仪器条实测：

| 读数 | 实测值 | 说明 |
|---|---|---|
| 帧率 | **30 fps** | 跑满帧循环设定的 30fps 上限 |
| 画面帧 | **457 帧** | `getVKFrame` 稳定取帧 —— 这一环在修复前完全是死的 |
| 关键点 | **21 点** | 骨架与手对齐准确 |
| 基础库 | **3.15.3** | 手机实际版本（模拟器为 3.17.4），远高于 2.28.0 门槛 |

「已检测到手」徽标正常点亮、状态为「采集中 · 识别中」，说明相机帧链路、
帧分析、21 点检测、归一化坐标映射、YUV 上屏与 GL 骨架这一整条路径都通了。
另外 `mirror` 默认 `false` 时骨架方向正确，无需镜像。

静态测试（51/51 通过，含 `WXML 不含 <camera>`、`start 后启动了帧循环` 两条回归防线）
只覆盖接线正确性，真机结论以上面这次运行为准。

---

## 重跑时看这三个读数

仪器条上的字段是刻意按排障顺序排的，**从上到下逐级排除**：

| 读数 | 有数字说明什么 | 恒为 `—` 说明什么 |
|---|---|---|
| **画面帧**（`getVKFrame` 取到帧的次数） | 相机帧链路通了 | 相机没出帧 → 与算法无关，查会话/权限 |
| **帧率**（`updateAnchors` 触发频率） | 帧分析在跑 | 帧分析没跑 → 检查基础库 ≥ 2.28.0 |
| **关键点** | 检测到手、载荷正常 | 有帧但没识别到手 → 把手放进画面中央、光照充足 |

如果显示「出错了」，提示区会给出**中文原因**，例如：

- `112 相机未在「小程序隐私协议」里声明` —— 新小程序最常见的坑，去小程序后台补「摄像头」用途声明
- `2003001 未开启系统相机权限` —— 去系统设置里给微信开相机
- `2000002 设备不支持 VisionKit`

## 首次运行要确认的事

1. **基础库 ≥ 2.28.0**（`hand` track 的最低要求）。`app.js` 会在低于此版本时弹窗提示；
   模拟器实测为 3.17.4，正常不会触发。
2. **镜像方向**。前置摄像头预览的镜像由 `getDisplayTransform()` 负责，而关键点是按
   归一化坐标直接映射的，**官方示例不对点做镜像**，所以这里 `mirror` 默认为 `false`。
   若骨架与手左右反着走，打开「镜像显示」开关即可。
3. **`VKSession` 是单例、页面间运行周期互斥**。如果你在这一页之前用过它（或热重载残留），
   请**退出重进页面**再点开始；`onUnload` / `onHide` 里已做 `destroy()`。

---

## iOS 真机验证清单（iPhone）

小程序天然跨 iOS/Android，iPhone 上这几处要真机确认：

| # | 验证项 | 现象 → 处理 |
|---|---|---|
| 1 | **相机画面是否正常上屏** | 全黑/花屏 → 查「画面帧」是否恒为 `—`；有帧但画面异常则是 YUV 着色器或 `getDisplayTransform()` 取向问题 |
| 2 | **骨架是否与手对齐** | 左右反 → 打开「镜像显示」；整体偏移/缩放不对 → 归一化映射问题（归一化点 × 画布尺寸，无 cover 换算） |
| 3 | **帧率是否够用** | 旧机型低于 15fps → 可把帧循环限到 30fps 以内（`getVKFrame` 推荐 ≤ 30fps） |
| 4 | **是否有残留会话** | 报 `2003000 会话不可用` → 退出重进页面 |

另外两点是 iOS 特有但已静态处理好的：

- **底部安全区**：index.wxss 已加 `env(safe-area-inset-bottom)`（带 `constant()` 兜底），
  iPhone 全面屏底部按钮不会被 Home Indicator 遮挡
- **基础库检查**：`app.js` 会弹窗提示基础库 < 2.28.0

iPhone 性能预期：VisionKit 为系统能力、推理开销低，帧率主要受 WebGL 绘制与 `setData`
节流影响。**实测跑满 30 fps**（帧循环上限）。

### iPhone 真机预览

开发者工具打开本项目 → 点工具栏「预览」→ 生成二维码 → iPhone 用微信扫码即可（个人开发者账号 / 测试号均可）。首次授权摄像头时微信会弹系统级权限，允许后进入采集页。

> 排障建议用**「真机调试」**而不是「预览」：真机调试能把手机端的 `console` 回传到工具的
> 调试器里，`session.start` 的 errno 与逐帧日志都能直接看到。

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
| **MC 桥接** | 局域网中继已实现；正式发布仍需公网 HTTPS 中继 |
| **3D 关键点** | 微信 ≥8.1.0 提供 `points3d`（MANO-16 关节定义）——**这是网页版没有的能力**，可做真正的立体手势 |
| **手势分类** | VisionKit 的 `anchor.gesture` 直接给出分类，网页版还需要自己算 ——**同样是白捡的** |
| **静态图片检测** | `mode: 2` + `detectHand({frameBuffer,...})`，可做「拍照识别手势」 |

---

## 设计一致性

界面沿用了网页端的设计令牌（`app.wxss` 里那套 CSS 变量直接搬自
[`../tokens.css`](../tokens.css)）：同一个深色「应用」主题、同一组品牌铜色与功能蓝、
同样的刻度条与环形表语言（环表改用 canvas 画弧，不依赖 CSS 渐变）。
