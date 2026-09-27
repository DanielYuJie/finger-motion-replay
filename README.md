# 手指运动采集与 3D 复现

浏览器端单指/手部运动采集原型：摄像头 → MediaPipe 关节点 → 关节角 → Three.js 骨架与参数化手指复现。

## 功能
- 摄像头采集与设备切换、截图
- 手部 21 关节点检测、骨架叠加、实时关节角
- 3D 复现建模（关节点骨架 + 参数化手指）
- 识别资源已本地化（vendor/），无需外网 CDN

## 使用
用 Chrome / Edge 打开 `index.html`（建议 https 或 localhost）。
允许摄像头后点击「开启摄像头」，将手伸入画面即可。

## 结构
- `index.html` / `styles.css` / `app.js` — 采集与识别 UI
- `replay3d.js` — Three.js 复现场景
- `vendor/` — MediaPipe tasks-vision、手部模型、WASM、Three.js

## 环境
现代浏览器（Chrome/Edge/Firefox），需摄像头权限。
