/**
 * core/stability.js — 识别稳定性三级链路（平台无关）
 *
 * 与浏览器端 app.js 里的实现是同一套算法，只是抽成了可单独测试的模块：
 *   1. OneEuro            —— 自适应低通，静止强抑抖、快速移动自动跟手
 *   2. LandmarkSmoother   —— 21 点 × 3 轴各自滤波
 *   3. AngleSmoother      —— 关节角平滑（无偏）
 *   4. DisplayHysteresis  —— 只作用于显示，避免读数与刻度抖动
 *   5. PresenceGate       —— 漏检宽限，避免单帧丢失造成画面闪烁
 *
 * 设计要点（踩过的坑，别改回去）：
 *   · 关节角**不设**死区。早期版本用「指数平滑 + 死区」，死区会把数值卡住不放，
 *     实测保持静止姿势时可偏离真值约 7°，对驱动机械手不可接受。
 *     现在死区只放在 DisplayHysteresis，3D/桥接拿到的始终是真实平滑值。
 */

function OneEuro(minCutoff, beta, dCutoff) {
  this.minCutoff = minCutoff;
  this.beta = beta;
  this.dCutoff = dCutoff;
  this.reset();
}

OneEuro.prototype.reset = function () {
  this.tPrev = null;
  this.xPrev = null;
  this.xHat = null;
  this.dxHat = 0;
};

OneEuro.prototype.alpha = function (cutoff, dt) {
  var tau = 1 / (2 * Math.PI * cutoff);
  return 1 / (1 + tau / dt);
};

OneEuro.prototype.filter = function (x, tMs) {
  if (this.tPrev === null) {
    this.tPrev = tMs;
    this.xPrev = x;
    this.xHat = x;
    this.dxHat = 0;
    return x;
  }
  var dt = (tMs - this.tPrev) / 1000;
  if (!(dt > 0)) dt = 1 / 30;         // 小程序帧率通常 15–30fps
  dt = Math.min(dt, 0.25);

  var dx = (x - this.xPrev) / dt;
  var aD = this.alpha(this.dCutoff, dt);
  this.dxHat = aD * dx + (1 - aD) * this.dxHat;

  var cutoff = this.minCutoff + this.beta * Math.abs(this.dxHat);
  var a = this.alpha(cutoff, dt);
  this.xHat = a * x + (1 - a) * this.xHat;

  this.tPrev = tMs;
  this.xPrev = x;
  return this.xHat;
};

/* ------------------------------------------------------------------ */
/* 关节点平滑：21 点 × 3 轴                                             */
/* ------------------------------------------------------------------ */

function LandmarkSmoother(opts) {
  opts = opts || {};
  // 小程序帧率通常 15–30fps，dt 比浏览器 60fps 大一倍，
  // 若沿用 60fps 时的 minCutoff 会明显偏「跟手而不够稳」，故这里取更低的值。
  this.minCutoff = opts.minCutoff != null ? opts.minCutoff : 1.1;
  this.beta = opts.beta != null ? opts.beta : 0.04;
  this.dCutoff = opts.dCutoff != null ? opts.dCutoff : 1.0;
  this.points = 21;
  this.filters = [];
  this._build();
}

LandmarkSmoother.prototype._build = function () {
  this.filters = [];
  for (var i = 0; i < this.points; i++) {
    this.filters.push({
      x: new OneEuro(this.minCutoff, this.beta, this.dCutoff),
      y: new OneEuro(this.minCutoff, this.beta, this.dCutoff),
      z: new OneEuro(this.minCutoff, this.beta, this.dCutoff)
    });
  }
};

LandmarkSmoother.prototype.reset = function () {
  for (var i = 0; i < this.filters.length; i++) {
    this.filters[i].x.reset();
    this.filters[i].y.reset();
    this.filters[i].z.reset();
  }
};

LandmarkSmoother.prototype.filter = function (hand, tMs) {
  var out = new Array(hand.length);
  for (var i = 0; i < hand.length; i++) {
    var p = hand[i];
    var f = this.filters[i];
    if (!p || !f) { out[i] = { x: 0, y: 0, z: 0 }; continue; }
    out[i] = {
      x: f.x.filter(p.x, tMs),
      y: f.y.filter(p.y, tMs),
      z: typeof p.z === 'number' ? f.z.filter(p.z, tMs) : 0
    };
  }
  return out;
};

/* ------------------------------------------------------------------ */
/* 关节角平滑（无偏，无死区）                                            */
/* ------------------------------------------------------------------ */

function AngleSmoother(opts) {
  opts = opts || {};
  this.minCutoff = opts.minCutoff != null ? opts.minCutoff : 0.9;
  this.beta = opts.beta != null ? opts.beta : 0.03;
  this.dCutoff = opts.dCutoff != null ? opts.dCutoff : 1.0;
  this.names = ['thumb', 'index', 'middle', 'ring', 'pinky'];
  this.filters = {};
  this._build();
}

AngleSmoother.prototype._mk = function () {
  return new OneEuro(this.minCutoff, this.beta, this.dCutoff);
};

AngleSmoother.prototype._build = function () {
  this.filters = {};
  for (var i = 0; i < this.names.length; i++) {
    this.filters[this.names[i]] = { a: [this._mk(), this._mk(), this._mk()], flex: this._mk() };
  }
};

AngleSmoother.prototype.reset = function () {
  this._build();
};

AngleSmoother.prototype.filter = function (raw, tMs) {
  var out = {};
  for (var i = 0; i < this.names.length; i++) {
    var name = this.names[i];
    var r = raw[name];
    var f = this.filters[name];
    out[name] = {
      angles: [
        f.a[0].filter(r.angles[0], tMs),
        f.a[1].filter(r.angles[1], tMs),
        f.a[2].filter(r.angles[2], tMs)
      ],
      flex: f.flex.filter(r.flex, tMs)
    };
  }
  return out;
};

/* ------------------------------------------------------------------ */
/* 显示层滞回：只影响界面读数，不影响对外输出的角度                       */
/* ------------------------------------------------------------------ */

function DisplayHysteresis(deadband) {
  this.deadband = deadband != null ? deadband : 0.4;
  this.map = {};
}

DisplayHysteresis.prototype.reset = function () {
  this.map = {};
};

DisplayHysteresis.prototype.clear = function (key) {
  delete this.map[key];
};

DisplayHysteresis.prototype.value = function (key, v) {
  var prev = this.map[key];
  if (prev === undefined || Math.abs(v - prev) >= this.deadband) {
    this.map[key] = v;
    return v;
  }
  return prev;
};

/* ------------------------------------------------------------------ */
/* 出现/离开判定（漏检宽限）                                             */
/* ------------------------------------------------------------------ */

function PresenceGate(opts) {
  opts = opts || {};
  this.graceMs = opts.graceMs != null ? opts.graceMs : 250;
  this.reacquireMs = opts.reacquireMs != null ? opts.reacquireMs : 700;
  this.lastSeenAt = 0;
  this.hadHand = false;
}

PresenceGate.prototype.reset = function () {
  this.lastSeenAt = 0;
  this.hadHand = false;
};

/**
 * 每帧调用一次，返回：
 *   'acquire' 手刚出现（或隔久重现）→ 调用方应重置滤波器，避免从旧位置拖影
 *   'track'   正常跟踪
 *   'hold'    本帧未检测到，但仍在宽限期内 → 保持上一帧画面与读数（防闪烁）
 *   'lost'    确认离开 → 调用方清空画面与读数
 *   'idle'    已清空过，无需重复处理
 */
PresenceGate.prototype.update = function (hasHand, now) {
  if (hasHand) {
    var wasAway = !this.hadHand ||
      (this.lastSeenAt && now - this.lastSeenAt > this.reacquireMs);
    this.hadHand = true;
    this.lastSeenAt = now;
    return wasAway ? 'acquire' : 'track';
  }
  var gap = this.lastSeenAt ? now - this.lastSeenAt : Infinity;
  if (gap < this.graceMs) return 'hold';
  if (this.hadHand) {
    this.hadHand = false;
    this.lastSeenAt = 0;
    return 'lost';
  }
  return 'idle';
};

module.exports = {
  OneEuro: OneEuro,
  LandmarkSmoother: LandmarkSmoother,
  AngleSmoother: AngleSmoother,
  DisplayHysteresis: DisplayHysteresis,
  PresenceGate: PresenceGate
};
