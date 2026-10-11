/**
 * pages/capture/index.js — 视觉主端（小程序版）
 *
 * 与网页端的分工完全一致：
 *   微信 VisionKit 人手检测（本机、免费、21 点）→ 关节角 → 3 级稳定链路 → 画面/读数
 * 算法核心来自 ../../core，与浏览器端是同一套，已在 Node 里量化验证过。
 *
 * ────────────────────────────────────────────────────────────────
 * ⚠️ 首次真机调试必须确认的两件事（我无法在此环境验证）
 *
 *  1) POINTS_ARE_PIXELS
 *     文档写 VisionKit 的 points 是「图像中的 (x,y) 坐标」，即像素。
 *     若你的基础库返回的其实已是 0–1 归一化，把这里改成 false 即可。
 *
 *  2) FRAME
 *     归一化与「cover」映射都需要知道检测帧的尺寸。
 *     若真机上骨架整体偏移/缩放不对，就调这两个值（常见为 720×1280 或 480×640）。
 * ────────────────────────────────────────────────────────────────
 */

var handCore = require('../../core/hand.js');
var stab = require('../../core/stability.js');

var POINTS_ARE_PIXELS = true;
var FRAME = { w: 720, h: 1280 };

/**
 * 是否用 <camera> 组件渲染预览。
 * VisionKit 只负责「检测」，不负责画画面，所以通常需要 camera 组件做预览。
 * 但两者同时占用摄像头在个别机型上可能冲突；若 session.start 返回的 errno
 * 指向摄像头被占用，把这个开关改成 false，只保留骨架覆盖层试试。
 */
var SHOW_CAMERA_PREVIEW = true;

var FINGER_LABELS = ['全部', '食指', '中指', '无名指', '小指', '拇指'];
var FINGER_KEYS = [null, 'index', 'middle', 'ring', 'pinky', 'thumb'];

function buildCards() {
  return handCore.FINGER_ORDER.map(function (name) {
    var def = handCore.FINGER_DEFS[name];
    return {
      key: name,
      label: def.label,
      tag: def.joints.map(function (j) { return j.toUpperCase(); }).join(' · '),
      joints: def.joints.map(function (j) {
        return { k: j.toUpperCase(), v: '—', pct: 0 };
      })
    };
  });
}

Page({
  data: {
    running: false,
    status: '未开启',
    statusState: 'idle',
    handVisible: false,
    showCameraPreview: SHOW_CAMERA_PREVIEW,
    fps: '—',
    inferMs: '—',
    pointCount: '—',
    sdkVersion: '—',
    mirror: true,
    showAngles: true,
    fingerLabels: FINGER_LABELS,
    fingerIndex: 0,
    focusFlex: '—',
    angleCards: buildCards(),
    tips: []
  },

  /* ---------------- 生命周期 ---------------- */

  onLoad: function () {
    // 稳定链路：和平板/浏览器端同一套参数（已按 15–30fps 重新调过）
    this.lm = new stab.LandmarkSmoother();
    this.ang = new stab.AngleSmoother();
    this.disp = new stab.DisplayHysteresis(0.4);
    this.gate = new stab.PresenceGate({ graceMs: 250, reacquireMs: 700 });

    this.session = null;
    this.overlayCtx = null;
    this.gaugeCtx = null;

    this._frames = 0;
    this._fpsAt = 0;
    this._lastPush = 0;
    this._handVisible = false;
    this._fps = 0;

    var app = getApp();
    this.setData({ sdkVersion: (app && app.globalData && app.globalData.sdkVersion) || '—' });

    this.initCanvases();
  },

  onUnload: function () {
    this.stopSession();
  },

  onHide: function () {
    // 页面不可见时释放摄像头，避免占用
    this.stopSession();
  },

  /* ---------------- canvas ---------------- */

  initCanvases: function () {
    var self = this;
    var q = wx.createSelectorQuery();
    q.select('#overlay').fields({ node: true, size: true });
    q.select('#gauge').fields({ node: true, size: true });
    q.exec(function (res) {
      var dpr = 1;
      try { dpr = wx.getWindowInfo().pixelRatio || 1; } catch (e) { dpr = 1; }

      if (res[0] && res[0].node) {
        var c = res[0].node;
        c.width = res[0].width * dpr;
        c.height = res[0].height * dpr;
        self.overlayCanvas = c;
        self.overlayCtx = c.getContext('2d');
        self.overlayDpr = dpr;
      }
      if (res[1] && res[1].node) {
        var g = res[1].node;
        g.width = res[1].width * dpr;
        g.height = res[1].height * dpr;
        self.gaugeCanvas = g;
        self.gaugeCtx = g.getContext('2d');
        self.gaugeDpr = dpr;
        self.drawGauge(0);
      }
    });
  },

  /**
   * 把检测帧坐标映射到画布（cover：铺满并裁切，避免拉伸变形）。
   * mirror 与 camera 的镜像预览保持一致，否则骨架会左右反。
   */
  makeMapper: function () {
    var c = this.overlayCanvas;
    if (!c) return null;
    var w = c.width, h = c.height;
    var scale = Math.max(w / FRAME.w, h / FRAME.h);
    var dw = FRAME.w * scale, dh = FRAME.h * scale;
    var dx = (w - dw) / 2, dy = (h - dh) / 2;
    var mirror = this.data.mirror;
    return function (p) {
      var px = mirror ? (1 - p.x) : p.x;
      return { x: dx + px * dw, y: dy + p.y * dh };
    };
  },

  drawOverlay: function (pts) {
    var ctx = this.overlayCtx;
    if (!ctx || !this.overlayCanvas) return;
    var c = this.overlayCanvas;
    ctx.clearRect(0, 0, c.width, c.height);
    if (!pts) return;

    var map = this.makeMapper();
    var dpr = this.overlayDpr || 1;

    // 骨架连线
    ctx.lineWidth = 3 * dpr;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.strokeStyle = 'rgba(62, 207, 142, 0.9)';
    var conns = handCore.HAND_CONNECTIONS;
    for (var k = 0; k < conns.length; k++) {
      var a = pts[conns[k][0]], b = pts[conns[k][1]];
      if (!a || !b) continue;
      var pa = map(a), pb = map(b);
      ctx.beginPath();
      ctx.moveTo(pa.x, pa.y);
      ctx.lineTo(pb.x, pb.y);
      ctx.stroke();
    }

    // 关节点
    var focusKey = FINGER_KEYS[this.data.fingerIndex];
    for (var i = 0; i < pts.length; i++) {
      var p = map(pts[i]);
      var isTip = focusKey && handCore.FINGER_DEFS[focusKey].ids[3] === i;
      ctx.beginPath();
      ctx.fillStyle = isTip ? '#f0b429' : '#5ad1ff';
      ctx.arc(p.x, p.y, (isTip ? 7 : 4.5) * dpr, 0, Math.PI * 2);
      ctx.fill();
    }
  },

  drawGauge: function (pct) {
    var ctx = this.gaugeCtx;
    if (!ctx || !this.gaugeCanvas) return;
    var c = this.gaugeCanvas;
    var dpr = this.gaugeDpr || 1;
    var cx = c.width / 2, cy = c.height / 2;
    var r = Math.min(cx, cy) - 8 * dpr;

    ctx.clearRect(0, 0, c.width, c.height);

    ctx.lineWidth = 12 * dpr;
    ctx.lineCap = 'round';
    ctx.strokeStyle = 'rgba(255,255,255,0.07)';
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.stroke();

    var v = Math.max(0, Math.min(100, pct || 0));
    ctx.strokeStyle = '#c97a4b';
    ctx.beginPath();
    ctx.arc(cx, cy, r, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * (v / 100));
    ctx.stroke();
  },

  /* ---------------- session ---------------- */

  onStart: function () {
    var self = this;
    wx.authorize({
      scope: 'scope.camera',
      success: function () { self.startSession(); },
      fail: function () {
        wx.showModal({
          title: '需要摄像头权限',
          content: '手部识别需要摄像头权限，请在设置中开启。',
          confirmText: '去设置',
          success: function (r) { if (r.confirm) wx.openSetting(); }
        });
      }
    });
  },

  startSession: function () {
    if (this.session) return;
    var self = this;
    this.setData({ status: '启动中…', statusState: 'loading' });

    var session;
    try {
      session = wx.createVKSession({ track: { hand: { mode: 1 } } });
    } catch (e) {
      this.fail('createVKSession 失败：' + (e && e.message ? e.message : e) +
        '（VisionKit 需要基础库 2.28.0+）');
      return;
    }
    this.session = session;

    session.on('updateAnchors', function (anchors) { self.onAnchors(anchors); });
    session.on('removeAnchors', function () { self.onRemoveAnchors(); });

    session.start(function (errno) {
      if (errno) {
        self.session = null;
        self.fail('session.start 失败，errno=' + errno +
          '（若与摄像头占用有关，把 index.js 顶部的 SHOW_CAMERA_PREVIEW 改为 false 再试）');
        return;
      }
      self._fpsAt = Date.now();
      self._frames = 0;
      self.setData({
        running: true,
        status: '采集中 · 识别中',
        statusState: 'live',
        tips: []
      });
    });
  },

  stopSession: function () {
    if (this.session) {
      try { this.session.destroy(); } catch (e) { /* 忽略 */ }
      this.session = null;
    }
    if (this.gate) this.gate.reset();
    if (this.lm) this.lm.reset();
    if (this.ang) this.ang.reset();
    if (this.disp) this.disp.reset();
    if (this.overlayCtx && this.overlayCanvas) {
      this.overlayCtx.clearRect(0, 0, this.overlayCanvas.width, this.overlayCanvas.height);
    }
    this.setData({
      running: false,
      status: '未开启',
      statusState: 'idle',
      handVisible: false,
      fps: '—',
      inferMs: '—',
      pointCount: '—',
      focusFlex: '—',
      angleCards: buildCards()
    });
    this.drawGauge(0);
  },

  onStop: function () { this.stopSession(); },

  onCameraStop: function () {
    // 用户拒绝或摄像头被占用
    this.fail('摄像头未授权或被占用');
  },

  fail: function (msg) {
    this.setData({
      running: false,
      status: '出错了',
      statusState: 'error',
      tips: [msg]
    });
  },

  /* ---------------- 每帧处理 ---------------- */

  onAnchors: function (anchors) {
    var now = Date.now();
    this.countFrame(now);

    var a = anchors && anchors[0];
    var raw = a && a.points && a.points.length >= 21 ? a.points : null;

    var mode = this.gate.update(!!raw, now);

    if (mode === 'acquire') {
      // 手刚出现/隔久重现：重置滤波器，避免从旧位置拖影过来
      this.lm.reset();
      this.ang.reset();
      this.disp.reset();
    }
    if (mode === 'hold' || mode === 'idle') {
      // 宽限期内：保持上一帧画面与读数，不闪
      return;
    }
    if (mode === 'lost') {
      if (this._handVisible) {
        this._handVisible = false;
        this.drawOverlay(null);
        this.setData({ handVisible: false, focusFlex: '—', angleCards: buildCards() });
        this.drawGauge(0);
      }
      return;
    }

    // mode === 'track'
    var norm = handCore.normalizePoints(raw, FRAME.w, FRAME.h, POINTS_ARE_PIXELS);
    var smooth = this.lm.filter(norm, now);
    var angles = this.ang.filter(handCore.computeFingerAngles(smooth), now);

    this.drawOverlay(smooth);
    this.pushUI(angles, raw.length, now);
  },

  onRemoveAnchors: function () {
    // 不在这里清空：交给 PresenceGate 的宽限期判定，避免一帧丢失就闪
  },

  countFrame: function (now) {
    this._frames++;
    if (!this._fpsAt) this._fpsAt = now;
    var dt = now - this._fpsAt;
    if (dt >= 1000) {
      this._fps = Math.round((this._frames * 1000) / dt);
      this._frames = 0;
      this._fpsAt = now;
      this.setData({ fps: this._fps + ' fps' });
    }
  },

  /**
   * 更新读数。setData 每帧调用会拖垮小程序，所以：
   *   · 画面（骨架/环表）走 canvas，不走 setData
   *   · 数字读数节流到 ~150ms，且经显示滞回，本来也不需要每帧刷
   */
  pushUI: function (angles, pointCount, now) {
    if (now - this._lastPush < 150) return;
    this._lastPush = now;

    var focusKey = FINGER_KEYS[this.data.fingerIndex];

    var cards = handCore.FINGER_ORDER.map(function (name) {
      var def = handCore.FINGER_DEFS[name];
      var d = angles[name];
      return {
        key: name,
        label: def.label,
        tag: def.joints.map(function (j) { return j.toUpperCase(); }).join(' · '),
        joints: def.joints.map(function (j, i) {
          var deg = d.angles[i];
          // 显示滞回：只影响读数与刻度，3D/桥接用的仍是真实平滑值
          var shown = this.disp.value(name + '-' + j, deg);
          return {
            k: j.toUpperCase(),
            v: shown.toFixed(1),
            pct: Math.max(0, Math.min(100, (shown / 120) * 100)).toFixed(1)
          };
        }, this)
      };
    }, this);

    var flexRaw;
    if (focusKey) {
      flexRaw = angles[focusKey].flex;
    } else {
      var sum = 0;
      for (var i = 0; i < handCore.FINGER_ORDER.length; i++) {
        sum += angles[handCore.FINGER_ORDER[i]].flex;
      }
      flexRaw = sum / handCore.FINGER_ORDER.length;
    }
    var flexShown = this.disp.value('__flex', flexRaw);

    this._handVisible = true;
    this.setData({
      angleCards: cards,
      focusFlex: flexShown.toFixed(1),
      pointCount: pointCount + ' 点',
      handVisible: true
    });
    this.drawGauge(flexShown);
  },

  /* ---------------- 交互 ---------------- */

  onFingerChange: function (e) {
    this.setData({ fingerIndex: Number(e.detail.value) });
  },

  onMirrorChange: function (e) {
    this.setData({ mirror: e.detail.value });
  },

  onShowAnglesChange: function (e) {
    this.setData({ showAngles: e.detail.value });
  }
});
