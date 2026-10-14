/**
 * pages/capture/index.js — 视觉主端（小程序版）
 *
 * 分工与网页端一致：
 *   微信 VisionKit 人手检测（本机、21 点）→ 关节角 → 3 级稳定链路 → 画面/读数
 *   算法核心来自 ../../core，与浏览器端同一套，已在 Node 里量化验证过。
 *
 * ────────────────────────────────────────────────────────────────
 * 真机踩过的两个坑（都已按官方示例改掉，勿回退）
 *
 *  1) 不能用 <camera> 组件做预览。
 *     官方「通过摄像头实时检测」示例（miniprogram-demo/packageAPI/pages/ar/hand-detect）
 *     的 WXML 里没有 camera 组件，只有一块 <canvas type="webgl">。
 *     实时模式下摄像头画面由 VKSession 自己产出，必须：
 *        wx.createVKSession({ track:{hand:{mode:1}}, version:'v1', gl })
 *        const frame = session.getVKFrame(w, h)
 *        const { yTexture, uvTexture } = frame.getCameraTexture(gl, 'yuv')
 *     用 <camera> 的后果：它独占摄像头，session.start 返回 0（成功），
 *     但 updateAnchors 永不触发 —— 表现为「状态采集中、有画面、零回调」。
 *
 *  2) anchor.points 是 **0–1 归一化**坐标，不是像素。
 *     官方示例的换算 x*2-1 / 1-y*2 正是 0..1→NDC。所以 POINTS_ARE_PIXELS=false。
 *     又因 getVKFrame(canvas.width, canvas.height) 按画布取帧，
 *     归一化点 × 画布尺寸 即为画布像素位置，无需 cover/letterbox 换算。
 * ────────────────────────────────────────────────────────────────
 */

var handCore = require('../../core/hand.js');
var stab = require('../../core/stability.js');
var glview = require('../../core/glview.js');

// 见上文坑 2：VisionKit 的 points 已是 0–1 归一化
var POINTS_ARE_PIXELS = false;

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

function windowInfo() {
  try {
    if (typeof wx.getWindowInfo === 'function') return wx.getWindowInfo();
  } catch (e) { /* 回退 */ }
  try { return wx.getSystemInfoSync(); } catch (e) { return {}; }
}

/**
 * `session.start` 的 errno 文案（取自官方 VKSession.start 状态表与公共错误码）。
 * 保留原始码便于对照文档 —— 这几个码的成因差别很大，只报数字等于没报。
 */
var VK_ERRNO = {
  104: '用户取消了授权',
  112: '相机未在「小程序隐私协议」里声明 —— 去小程序后台补「摄像头」用途声明并重新发布',
  1025: '小程序隐私接口被封禁',
  1026: '小游戏隐私接口被封禁',
  2000000: '系统错误',
  2000001: '参数错误',
  2000002: '设备不支持 VisionKit',
  2000003: '系统不支持 VisionKit',
  2000004: '设备不支持 VisionKit',
  2003000: '会话不可用（页面上可能还有未销毁的 VKSession，退出重进页面再试）',
  2003001: '未开启系统相机权限 —— 去系统设置里给微信开相机',
  2003002: '未开启小程序相机权限'
};

function errnoText(e) {
  return (VK_ERRNO[e] || '未知原因') + '（errno=' + e + '）';
}

Page({
  data: {
    running: false,
    status: '未开启',
    statusState: 'idle',
    handVisible: false,
    fps: '—',
    frameCount: '—',
    pointCount: '—',
    sdkVersion: '—',
    mirror: false,          // 官方示例不对点做镜像；如画面感觉左右反了，打开这个开关
    showAngles: true,
    fingerLabels: FINGER_LABELS,
    fingerIndex: 0,
    focusFlex: '—',
    angleCards: buildCards(),
    tips: []
  },

  /* ---------------- 生命周期 ---------------- */

  onLoad: function () {
    this.lm = new stab.LandmarkSmoother();
    this.ang = new stab.AngleSmoother();
    this.disp = new stab.DisplayHysteresis(0.4);
    this.gate = new stab.PresenceGate({ graceMs: 250, reacquireMs: 700 });

    this.session = null;
    this.glv = null;
    this.gaugeCtx = null;

    this._running = false;
    this._frames = 0;
    this._fpsAt = 0;
    this._lastPush = 0;
    this._gfxFrames = 0;      // getVKFrame 成功取到画面的帧数
    this._gfxNull = 0;        // getVKFrame 返回 null 的次数
    this._lastGfxPush = 0;
    this._handVisible = false;
    this._fps = 0;

    var app = getApp();
    this.setData({ sdkVersion: (app && app.globalData && app.globalData.sdkVersion) || '—' });
  },

  // 节点查询必须在 onReady 之后做，否则拿不到 canvas node
  onReady: function () {
    this.initCanvases();
  },

  onUnload: function () { this.stopSession(); },
  onHide: function () { this.stopSession(); },

  /* ---------------- canvas ---------------- */

  initCanvases: function () {
    var self = this;
    var q = wx.createSelectorQuery();
    q.select('#gfx').fields({ node: true, size: true });
    q.select('#gauge').fields({ node: true, size: true });
    q.exec(function (res) {
      var info = windowInfo();
      var dpr = info.pixelRatio || 1;

      // ---- WebGL 画布：相机预览 + 骨架 ----
      var g = res && res[0];
      if (!g || !g.node) {
        self.setData({ tips: ['取不到 #gfx 画布节点，无法创建 WebGL 上下文'] });
        return;
      }
      var gc = g.node;
      gc.width = Math.max(1, Math.round(g.width * dpr));
      gc.height = Math.max(1, Math.round(g.height * dpr));

      var view = new glview.GLView(gc);
      view.dpr = dpr;
      if (!view.init()) {
        // 如实把 GL 失败原因显示出来，而不是静默黑屏
        self.setData({ tips: ['WebGL 初始化失败：' + view.error] });
        return;
      }
      self.glv = view;

      // ---- 2D 画布：仪表盘（与 GL 画布不重叠，无叠层问题）----
      var gg = res && res[1];
      if (gg && gg.node) {
        var ggc = gg.node;
        ggc.width = Math.max(1, Math.round(gg.width * dpr));
        ggc.height = Math.max(1, Math.round(gg.height * dpr));
        self.gaugeCanvas = ggc;
        self.gaugeCtx = ggc.getContext('2d');
        self.gaugeDpr = dpr;
        self.drawGauge(0);
      }
    });
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
    if (!this.glv || !this.glv.ok) {
      this.fail('WebGL 未就绪' + (this.glv && this.glv.error ? '：' + this.glv.error : '（画布节点可能还未创建，稍等一秒再点）'));
      return;
    }
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
    this.setData({ status: '启动中…', statusState: 'loading', tips: [] });

    var session;
    try {
      // 与官方一致：version + gl 都要给，VKSession 需要 gl 来产出相机纹理
      session = wx.createVKSession({
        track: { hand: { mode: 1 } },
        version: 'v1',
        gl: this.glv.gl
      });
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
        // 排障期务必留日志：errno 是唯一能区分「权限 / 隐私协议 / 机型不支持」的线索
        console.error('[VK] session.start errno =', errno);
        self.session = null;
        self.fail('session.start 失败：' + errnoText(errno));
        return;
      }
      self._running = true;
      self._frames = 0;
      self._gfxFrames = 0;
      self._gfxNull = 0;
      self._fpsAt = 0;
      self.setData({
        running: true,
        status: '采集中 · 识别中',
        statusState: 'live',
        tips: []
      });
      self.startRenderLoop();
    });
  },

  /** 逐帧：取 VK 帧 → 画相机 + 骨架。官方示例用 session.requestAnimationFrame 驱动。 */
  startRenderLoop: function () {
    var self = this;
    var session = this.session;
    if (!session) return;
    var raf = (typeof session.requestAnimationFrame === 'function')
      ? function (cb) { session.requestAnimationFrame(cb); }
      : function (cb) { self.glv.canvas.requestAnimationFrame(cb); };

    var onFrame = function () {
      if (!self._running || !self.session || !self.glv) return;

      var frame = null;
      try {
        frame = session.getVKFrame(self.glv.canvas.width, self.glv.canvas.height);
      } catch (e) {
        frame = null;
      }
      if (frame) self._gfxFrames++; else self._gfxNull++;

      try {
        self.glv.render(frame, handCore.HAND_CONNECTIONS, self.data.mirror);
      } catch (e) {
        // 渲染异常不要每帧刷屏，停掉循环并报错
        self._running = false;
        self.fail('渲染异常：' + (e && e.message ? e.message : e));
        return;
      }

      self.updateFrameReadout();
      raf(onFrame);
    };
    raf(onFrame);
  },

  /** 「画面帧」读数：区分「相机没来帧」与「来了帧但没检测到手」，这是排障关键。 */
  updateFrameReadout: function () {
    var now = Date.now();
    if (now - this._lastGfxPush < 500) return;
    this._lastGfxPush = now;
    this.setData({
      frameCount: this._gfxFrames > 0 ? (this._gfxFrames + ' 帧') : ('0 帧(空' + this._gfxNull + ')')
    });
  },

  stopSession: function () {
    this._running = false;
    if (this.session) {
      try { this.session.destroy(); } catch (e) { /* 忽略 */ }
      this.session = null;
    }
    if (this.gate) this.gate.reset();
    if (this.lm) this.lm.reset();
    if (this.ang) this.ang.reset();
    if (this.disp) this.disp.reset();
    if (this.glv) this.glv.setPoints(null, -1);

    this._gfxFrames = 0;
    this._gfxNull = 0;

    this.setData({
      running: false,
      status: '未开启',
      statusState: 'idle',
      handVisible: false,
      fps: '—',
      frameCount: '—',
      pointCount: '—',
      focusFlex: '—',
      angleCards: buildCards()
    });
    this.drawGauge(0);
  },

  onStop: function () { this.stopSession(); },

  fail: function (msg) {
    this._running = false;
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
    var raw = (a && a.points && a.points.length >= 21) ? a.points : null;

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
        if (this.glv) this.glv.setPoints(null, -1);
        this.setData({ handVisible: false, focusFlex: '—', angleCards: buildCards() });
        this.drawGauge(0);
      }
      return;
    }

    // mode === 'track'
    var norm = handCore.normalizePoints(raw, 0, 0, POINTS_ARE_PIXELS);
    var smooth = this.lm.filter(norm, now);
    var angles = this.ang.filter(handCore.computeFingerAngles(smooth), now);

    if (this.glv) this.glv.setPoints(smooth, this.focusTipIndex());
    this.pushUI(angles, raw.length, now);
  },

  focusTipIndex: function () {
    var key = FINGER_KEYS[this.data.fingerIndex];
    if (!key) return -1;
    return handCore.FINGER_DEFS[key].ids[3];
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
   *   · 画面（相机/骨架/环表）走 canvas，不走 setData
   *   · 数字读数节流到 ~150ms，且经显示滞回，本来也不需要每帧刷
   */
  pushUI: function (angles, pointCount, now) {
    if (now - this._lastPush < 150) return;
    this._lastPush = now;

    var cards = handCore.FINGER_ORDER.map(function (name) {
      var def = handCore.FINGER_DEFS[name];
      var d = angles[name];
      return {
        key: name,
        label: def.label,
        tag: def.joints.map(function (j) { return j.toUpperCase(); }).join(' · '),
        joints: def.joints.map(function (j, i) {
          var deg = d.angles[i];
          var shown = this.disp.value(name + '-' + j, deg);
          return {
            k: j.toUpperCase(),
            v: shown.toFixed(1),
            pct: Math.max(0, Math.min(100, (shown / 120) * 100)).toFixed(1)
          };
        }, this)
      };
    }, this);

    var focusKey = FINGER_KEYS[this.data.fingerIndex];
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
