/**
 * miniprogram/test/verify.js — 自检脚本（纯 Node，不需要微信开发者工具）
 *
 *   node miniprogram/test/verify.js
 *
 * 覆盖两部分：
 *   A. 算法核心：抖动抑制、精度、出现/离开判定、坐标归一化、关节角契约
 *   B. 页面逻辑：用桩件加载真实的 pages/capture/index.js，
 *      跑通 生命周期 → VKSession 接线 → updateAnchors → 稳定链路 → setData 载荷
 *
 * 页面里真正依赖真机的部分（canvas 节点 API、camera 组件、VisionKit 的坐标口径）
 * 无法在这里验证，需要真机/开发者工具确认 —— 见 README「首次运行要确认的 4 件事」。
 */

var path = require('path');
var fs = require('fs');

var ROOT = path.join(__dirname, '..');
var hand = require(path.join(ROOT, 'core', 'hand.js'));
var stab = require(path.join(ROOT, 'core', 'stability.js'));

var results = [];
function check(label, cond, extra) {
  results.push({ label: label, ok: !!cond, extra: extra === undefined ? '' : String(extra) });
  console.log('  ' + (cond ? 'PASS' : 'FAIL') + '  ' + label + (extra !== undefined ? '   ' + extra : ''));
}
function section(t) { console.log('\n' + t); }

/* ---------------- 工具 ---------------- */
var seed = 12345;
function gauss() {
  seed = (seed * 1103515245 + 12345) & 0x7fffffff;
  var u1 = (seed % 100000) / 100000 + 1e-9;
  seed = (seed * 1103515245 + 12345) & 0x7fffffff;
  var u2 = (seed % 100000) / 100000;
  return Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
}
function std(a) {
  var m = a.reduce(function (x, y) { return x + y; }, 0) / a.length;
  return Math.sqrt(a.reduce(function (x, y) { return x + (y - m) * (y - m); }, 0) / a.length);
}
function pose(kind) {
  var h = new Array(21);
  h[0] = { x: 0.50, y: 0.92, z: 0 };
  var xs = [0.34, 0.42, 0.50, 0.58];
  for (var f = 0; f < 4; f++) {
    var x = xs[f];
    h[5 + f * 4] = { x: x, y: 0.62, z: 0 };
    if (kind === 'bent' && f === 0) {
      h[6 + f * 4] = { x: x, y: 0.52, z: 0 };
      h[7 + f * 4] = { x: x + 0.09, y: 0.46, z: 0 };
      h[8 + f * 4] = { x: x + 0.16, y: 0.42, z: 0 };
    } else {
      h[6 + f * 4] = { x: x, y: 0.53, z: 0 };
      h[7 + f * 4] = { x: x, y: 0.45, z: 0 };
      h[8 + f * 4] = { x: x, y: 0.37, z: 0 };
    }
  }
  h[1] = { x: 0.42, y: 0.78, z: 0 }; h[2] = { x: 0.36, y: 0.70, z: 0 };
  h[3] = { x: 0.31, y: 0.63, z: 0 }; h[4] = { x: 0.27, y: 0.57, z: 0 };
  return h;
}

/* ================= A. 算法核心 ================= */
section('=== A1. 抖动抑制与精度（30fps，σ=0.008） ===');
var SIGMA = 0.008, N = 220, FPS = 30, WARM = 80;
['straight', 'bent'].forEach(function (kind) {
  var clean = pose(kind);
  var truth = hand.computeFingerAngles(clean).index.angles[1];
  var frames = [];
  for (var i = 0; i < N; i++) {
    frames.push(clean.map(function (p) { return { x: p.x + gauss() * SIGMA, y: p.y + gauss() * SIGMA, z: 0 }; }));
  }
  var lm = new stab.LandmarkSmoother();
  var ang = new stab.AngleSmoother();
  var rawTip = [], filtTip = [], rawAng = [], smAng = [];
  for (var i = 0; i < N; i++) {
    var t = i * (1000 / FPS);
    rawTip.push(frames[i][8].x);
    rawAng.push(hand.computeFingerAngles(frames[i]).index.angles[1]);
    var f = lm.filter(frames[i], t);
    filtTip.push(f[8].x);
    smAng.push(ang.filter(hand.computeFingerAngles(f), t).index.angles[1]);
  }
  var rT = std(rawTip.slice(WARM)), fT = std(filtTip.slice(WARM));
  var rA = std(rawAng.slice(WARM)), fA = std(smAng.slice(WARM));
  var redT = 100 * (1 - fT / rT), redA = 100 * (1 - fA / rA);
  check('[' + kind + '] 关节点抖动降低 > 60%', redT > 60, redT.toFixed(1) + '%');
  check('[' + kind + '] 关节角抖动降低 > 70%', redA > 70, redA.toFixed(1) + '%');
  var rawErr = Math.abs(rawAng.slice(WARM).reduce(function (a, b) { return a + b; }, 0) / (N - WARM) - truth);
  var smErr = Math.abs(smAng.slice(WARM).reduce(function (a, b) { return a + b; }, 0) / (N - WARM) - truth);
  check('[' + kind + '] 平滑后的均值误差不劣于原始', smErr <= rawErr + 1e-6,
    '原始 ' + rawErr.toFixed(2) + '° -> 平滑 ' + smErr.toFixed(2) + '°');
});

section('=== A2. 显示滞回降低读数抖动 ===');
(function () {
  var clean = pose('straight');
  var frames = [];
  for (var i = 0; i < 120; i++) {
    frames.push(clean.map(function (p) { return { x: p.x + gauss() * SIGMA, y: p.y + gauss() * SIGMA, z: 0 }; }));
  }
  var lm = new stab.LandmarkSmoother(), ang = new stab.AngleSmoother(), disp = new stab.DisplayHysteresis(0.4);
  var shown = [], naive = [];
  for (var i = 0; i < frames.length; i++) {
    var t = i * (1000 / FPS);
    var f = lm.filter(frames[i], t);
    var a = ang.filter(hand.computeFingerAngles(f), t);
    shown.push(disp.value('index-pip', a.index.angles[1]).toFixed(1));
    naive.push(hand.computeFingerAngles(frames[i]).index.angles[1].toFixed(1));
  }
  var ds = new Set(shown).size, dn = new Set(naive).size;
  check('120 帧内读数变化次数减少 > 40%', 1 - ds / dn > 0.4, dn + ' -> ' + ds);
})();

section('=== A3. PresenceGate 出现/离开判定 ===');
(function () {
  var g = new stab.PresenceGate({ graceMs: 250, reacquireMs: 700 });
  var t0 = 1000;
  var cases = [
    ['首帧有手', g.update(true, t0), 'acquire'],
    ['连续跟踪', g.update(true, t0 + 33), 'track'],
    ['单帧漏检 33ms', g.update(false, t0 + 66), 'hold'],
    ['累计 200ms 漏检', g.update(false, t0 + 233), 'hold'],
    ['超过宽限 400ms', g.update(false, t0 + 433), 'lost'],
    ['已清空后重复', g.update(false, t0 + 500), 'idle'],
    ['重新出现', g.update(true, t0 + 600), 'acquire'],
    ['紧接着再来', g.update(true, t0 + 633), 'track'],
    ['隔久重现 >700ms', g.update(true, t0 + 633 + 800), 'acquire']
  ];
  cases.forEach(function (c) { check(c[0], c[1] === c[2], 'got=' + c[1] + ' want=' + c[2]); });
})();

section('=== A4. 坐标归一化 ===');
(function () {
  var px = [{ x: 320, y: 240, z: 0 }, { x: 640, y: 480, z: 0 }];
  var a = hand.normalizePoints(px, 640, 480, true);
  var b = hand.normalizePoints(px, 640, 480, false);
  check('像素输入被正确归一化', a[0].x === 0.5 && a[1].y === 1, JSON.stringify(a[0]) + ' ' + JSON.stringify(a[1]));
  check('已归一化输入保持原样', b[0].x === 320 && b[1].y === 480);
})();

section('=== A5. 关节角契约 ===');
(function () {
  var s = hand.computeFingerAngles(pose('straight')).index;
  var b = hand.computeFingerAngles(pose('bent')).index;
  check('伸直时 PIP/DIP 为 0', Math.abs(s.angles[1]) < 1e-6 && Math.abs(s.angles[2]) < 1e-6,
    '[' + s.angles.map(function (v) { return v.toFixed(1); }).join(', ') + ']');
  check('DIP 与 PIP 不同（不是复制的假值）', b.angles[2] !== b.angles[1],
    '[' + b.angles.map(function (v) { return v.toFixed(1); }).join(', ') + ']');
})();

/* ================= B. 页面逻辑 ================= */
section('=== B1. WXML ↔ 页面 契约 ===');
var pageDef = null;
var sessionObj = null;
var modalCalls = [];
var NOW = 1000000;
var realNow = Date.now;
Date.now = function () { return NOW; };

global.Page = function (o) { pageDef = o; };
global.getApp = function () { return { globalData: { sdkVersion: '2.30.0' } }; };
/* WebGL 上下文替身：只求「调用不炸 + 能断言画了什么」，不模拟真实渲染 */
function mockGl() {
  var gl = {
    VERTEX_SHADER: 1, FRAGMENT_SHADER: 2, COMPILE_STATUS: 3, LINK_STATUS: 4,
    ARRAY_BUFFER: 5, STATIC_DRAW: 6, DYNAMIC_DRAW: 7, FLOAT: 8,
    DEPTH_TEST: 9, BLEND: 10, SRC_ALPHA: 11, ONE_MINUS_SRC_ALPHA: 12,
    COLOR_BUFFER_BIT: 13, TEXTURE_2D: 14, TEXTURE0: 15, UNPACK_ALIGNMENT: 16,
    TRIANGLE_STRIP: 17, LINES: 18, POINTS: 19, CURRENT_PROGRAM: 20,
    ACTIVE_TEXTURE: 21, VERTEX_ARRAY_BINDING: 22,
    calls: {}, draws: 0, drawModes: []
  };
  ['shaderSource', 'compileShader', 'attachShader', 'linkProgram', 'deleteShader',
    'useProgram', 'uniform1i', 'uniform1f', 'uniformMatrix3fv', 'bindBuffer',
    'bufferData', 'disable', 'enable', 'blendFunc', 'clearColor', 'clear',
    'pixelStorei', 'activeTexture', 'bindTexture', 'vertexAttribPointer',
    'enableVertexAttribArray', 'deleteProgram', 'deleteBuffer', 'viewport'
  ].forEach(function (m) {
    gl[m] = function () { gl.calls[m] = (gl.calls[m] || 0) + 1; };
  });
  gl.createShader = function () { return {}; };
  gl.createProgram = function () { return {}; };
  gl.createBuffer = function () { return {}; };
  gl.getShaderParameter = function () { return true; };
  gl.getProgramParameter = function () { return true; };
  gl.getShaderInfoLog = function () { return ''; };
  gl.getProgramInfoLog = function () { return ''; };
  gl.getAttribLocation = function () { return 0; };
  gl.getUniformLocation = function () { return {}; };
  gl.getParameter = function () { return null; };
  gl.drawArrays = function (mode) { gl.draws++; gl.drawModes.push(mode); };
  return gl;
}

function mockCtx2d() {
  var c = { calls: {} };
  ['clearRect', 'beginPath', 'arc', 'stroke', 'fill', 'moveTo', 'lineTo'].forEach(function (m) {
    c[m] = function () { c.calls[m] = (c.calls[m] || 0) + 1; };
  });
  return c;
}

function mockCanvasNode() {
  var gl = mockGl();
  var ctx = mockCtx2d();
  return {
    width: 0, height: 0, gl: gl, ctx: ctx,
    getContext: function (t) { return t === 'webgl' ? gl : ctx; }
  };
}

var canvasNodes = [mockCanvasNode(), mockCanvasNode()];
var rafCalls = 0;
var pendingFrames = [];   // 帧回调交给测试手动驱动：mock 里真去循环会死循环

global.wx = {
  getWindowInfo: function () { return { pixelRatio: 2 }; },
  createSelectorQuery: function () {
    var q = {
      select: function () { return q; },
      fields: function () { return q; },
      exec: function (cb) {
        cb(canvasNodes.map(function (n) {
          return { node: n, width: 320, height: 240 };
        }));
      }
    };
    return q;
  },
  authorize: function (o) { o.success && o.success(); },
  showModal: function (o) { modalCalls.push(o); },
  openSetting: function () {},
  createVKSession: function (opts) {
    var handlers = {};
    sessionObj = {
      opts: opts, handlers: handlers, started: false, destroyed: false,
      frameCalls: 0, rafCalls: 0,
      on: function (e, cb) { handlers[e] = cb; },
      start: function (cb) { this.started = true; cb(null); },
      destroy: function () { this.destroyed = true; },
      getVKFrame: function () { this.frameCalls++; return null; },
      requestAnimationFrame: function (cb) { this.rafCalls++; rafCalls++; pendingFrames.push(cb); }
    };
    return sessionObj;
  }
};

require(path.join(ROOT, 'pages', 'capture', 'index.js'));

function makeInstance(def) {
  var inst = Object.create(def);
  inst.data = JSON.parse(JSON.stringify(def.data));
  inst.setData = function (patch) { Object.assign(this.data, patch); };
  return inst;
}
function pixelHand() {
  return pose('straight').map(function (p) { return { x: p.x * 720, y: p.y * 1280, z: 0 }; });
}
/**
 * VisionKit 的 points 是 0–1 归一化（不是像素）。
 * 依据：官方 hand-detect 示例把点直接转 NDC —— flattenPoints.push(x * 2 - 1, 1 - y * 2)，
 * 该式仅在 x,y ∈ [0,1] 时成立。页面的 POINTS_ARE_PIXELS 因此为 false。
 */
function normHand() {
  return pose('straight').map(function (p) { return { x: p.x, y: p.y }; });
}

(function () {
  var wxml = fs.readFileSync(path.join(ROOT, 'pages', 'capture', 'index.wxml'), 'utf8');
  var binds = [];
  wxml.replace(/\b(?:bind|catch)[a-z]*\s*=\s*"([A-Za-z_$][\w$]*)"/g, function (m, n) { binds.push(n); return m; });
  var missingH = binds.filter(function (n) { return typeof pageDef[n] !== 'function'; });
  check('WXML 绑定的事件处理函数都存在', missingH.length === 0, missingH.join(', ') || new Set(binds).size + ' 个');

  var refs = [];
  wxml.replace(/\{\{\s*([A-Za-z_$][\w$]*)/g, function (m, n) { refs.push(n); return m; });
  var keys = Object.keys(pageDef.data);
  var local = ['item', 'j', 'index', 'true', 'false'];
  var missingD = refs.filter(function (n) { return keys.indexOf(n) < 0 && local.indexOf(n) < 0; });
  check('WXML 引用的数据字段都在 data 里', missingD.length === 0, missingD.join(', ') || new Set(refs).size + ' 个');

  var itemFields = [];
  wxml.replace(/\bitem\.([A-Za-z_$][\w$]*)/g, function (m, n) { itemFields.push(n); return m; });
  var card0 = pageDef.data.angleCards[0];
  var missingC = itemFields.filter(function (f) { return !(f in card0); });
  check('angleCards 提供 WXML 用到的字段', missingC.length === 0, missingC.join(', ') || Object.keys(card0).join(','));

  // 回归防线：真机上曾因 <camera> 组件抢占摄像头，导致 VKSession start 成功却零回调。
  // 官方所有实时 demo 的 WXML 里都没有 camera 组件，画面一律来自 session.getVKFrame。
  // 注意先剥掉注释 —— 注释里会提到 camera 这个词，不该算命中。
  var wxmlTags = wxml.replace(/<!--[\s\S]*?-->/g, '');
  check('WXML 不含 <camera> 组件（它会让 VKSession 收不到帧）', !/<camera[\s/>]/.test(wxmlTags));
  check('WXML 含 WebGL 画布 #gfx', /<canvas[^>]*type\s*=\s*"webgl"/.test(wxmlTags) && /id\s*=\s*"gfx"/.test(wxmlTags));
})();

section('=== B2. 生命周期与 VKSession 接线 ===');
var inst = makeInstance(pageDef);
(function () {
  inst.onLoad();
  check('onLoad 建立稳定链路', !!(inst.lm && inst.ang && inst.disp && inst.gate));

  // 必须先建好 WebGL 画布：gl 要交给 VKSession，相机画面也是画在这块画布上
  inst.onReady();
  check('onReady 建好 WebGL 渲染层', !!(inst.glv && inst.glv.ok), (inst.glv && inst.glv.error) || '');
  check('GL canvas 按 pixelRatio 设了尺寸',
    canvasNodes[0].width === 640 && canvasNodes[0].height === 480,
    canvasNodes[0].width + 'x' + canvasNodes[0].height);

  inst.onStart();
  check('VKSession 使用 mode:1（摄像头实时）', sessionObj && sessionObj.opts.track.hand.mode === 1);
  check('VKSession 传入 version:v1 与 gl', !!sessionObj && sessionObj.opts.version === 'v1' && !!sessionObj.opts.gl);
  check('session.start 被调用', sessionObj && sessionObj.started);
  check('注册了 updateAnchors / removeAnchors',
    typeof sessionObj.handlers.updateAnchors === 'function' && typeof sessionObj.handlers.removeAnchors === 'function');
  check('running=true 且状态 live', inst.data.running === true && inst.data.statusState === 'live');
  // 帧分析是被 getVKFrame 驱动的：不跑帧循环就永远不会有 anchor（真机踩过的坑）
  check('start 后启动了帧循环', rafCalls > 0, 'rafCalls=' + rafCalls);
})();

section('=== B3. 检测到手的输出载荷 ===');
(function () {
  sessionObj.handlers.updateAnchors([{ points: normHand() }]);
  var d = inst.data;
  check('angleCards 为 5 根手指 × 3 关节',
    d.angleCards.length === 5 && d.angleCards.every(function (c) { return c.joints.length === 3; }));
  check('读数已变成数字字符串', /^\d+\.\d$/.test(d.angleCards[1].joints[1].v), 'PIP=' + d.angleCards[1].joints[1].v);
  check('刻度百分比在 0–100', d.angleCards.every(function (c) {
    return c.joints.every(function (j) { return +j.pct >= 0 && +j.pct <= 100; });
  }));
  check('综合弯曲已输出', /^\d+\.\d$/.test(d.focusFlex), 'flex=' + d.focusFlex);
  check('伸直手指 PIP 接近 0', Number(d.angleCards[1].joints[1].v) < 1.5);
})();

section('=== B4. 漏检宽限（防闪烁） ===');
(function () {
  var before = inst.data.focusFlex;
  var cardsBefore = JSON.stringify(inst.data.angleCards);
  NOW += 33; sessionObj.handlers.removeAnchors();
  check('33ms 漏检读数不变', inst.data.focusFlex === before && JSON.stringify(inst.data.angleCards) === cardsBefore);
  NOW += 200; sessionObj.handlers.updateAnchors([]);
  check('累计 233ms 漏检读数不变', inst.data.focusFlex === before);
  NOW += 400; sessionObj.handlers.updateAnchors([]);
  check('超过宽限后清空读数', inst.data.focusFlex === '—');
  check('超过宽限后清空关节角', inst.data.angleCards.every(function (c) {
    return c.joints.every(function (j) { return j.v === '—'; });
  }));
  check('超过宽限后隐藏徽标', inst.data.handVisible === false);
})();

section('=== B5. 重新出现能恢复 ===');
(function () {
  NOW += 900;
  sessionObj.handlers.updateAnchors([{ points: normHand() }]);
  check('读数恢复', /^\d+\.\d$/.test(inst.data.focusFlex), 'flex=' + inst.data.focusFlex);
})();

section('=== B6. 关闭与释放 ===');
(function () {
  inst.onStop();
  check('session.destroy 被调用', sessionObj.destroyed === true);
  check('running=false 且状态复位', inst.data.running === false && inst.data.statusState === 'idle');
  check('释放了 session 引用', inst.session === null);
})();

section('=== B7. 画布 / WebGL 不可用时的容错 ===');
(function () {
  // 让节点查询返回空，模拟取不到 canvas（例如节点还没创建就被点了开始）
  var realQuery = wx.createSelectorQuery;
  var threw = null, tips = null, status = null;
  try {
    wx.createSelectorQuery = function () {
      var q = {
        select: function () { return q; },
        fields: function () { return q; },
        exec: function (cb) { cb([]); }
      };
      return q;
    };
    var i2 = makeInstance(pageDef);
    i2.onLoad();
    i2.onReady();          // 取不到画布 → 应写入提示，而不是抛异常
    tips = i2.data.tips;
    i2.drawGauge(50);      // 没有 gaugeCtx → 直接返回
    i2.onStart();          // 没有 GL → 应走 fail 分支并说明原因
    status = i2.data.status;
  } catch (e) { threw = e; }
  wx.createSelectorQuery = realQuery;

  check('取不到画布时不抛异常', threw === null, threw ? threw.message : '');
  check('取不到画布时给出提示', Array.isArray(tips) && tips.length > 0, (tips && tips[0]) || '');
  check('无 GL 时点开始会明确报错而非静默', status === '出错了', 'status=' + status);
})();

Date.now = realNow;

/* ---------------- 汇总 ---------------- */
var failed = results.filter(function (r) { return !r.ok; });
console.log('\n=== 汇总：' + (results.length - failed.length) + '/' + results.length + ' 通过 ===');
if (failed.length) {
  console.log('失败项：');
  failed.forEach(function (f) { console.log('  - ' + f.label + '  ' + f.extra); });
  process.exit(1);
}
console.log('全部通过。');
