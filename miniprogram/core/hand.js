/**
 * core/hand.js — 手部关键点与关节角解算（平台无关，浏览器与小程序共用）
 *
 * 为什么可以直接复用：
 *   微信 VisionKit 人手检测的 2D 关键点是 **21 点、与 OpenPose 定义相同**，
 *   而 OpenPose 的 21 点顺序与 MediaPipe HandLandmarker 完全一致：
 *     0 手腕 · 1-4 拇指(CMC/MCP/IP/TIP) · 5-8 食指 · 9-12 中指 · 13-16 无名指 · 17-20 小指
 *   所以浏览器端那套 FINGER_DEFS / 关节角算法可以原样搬过来。
 *
 * 关节角口径与视觉主端一致：输出「屈曲角」，0° = 完全伸直，数值越大弯曲越多。
 * 三个角依次为近端 / 中段 / 远端关节，与 FINGER_DEFS[{name}.joints] 一一对应。
 *
 * ── 优化记录（2026-11）────────────────────────────────────────────────
 * 纯 2D 夹角有两个已知缺陷，社区（MediaPipe Hands 论文 / 多个 webcam 机械手项目）都用同一套办法兜：
 *   1) 手掌正对镜头时，手指朝镜头弯曲几乎不改变 2D 投影位置 → 判成「还伸着」。
 *      对策：角度计算统一走 3D 公式（点带 z 时自动生效，VisionKit 开 open3d 后可拿到 z）。
 *   2) 单个关节角受掌骨基准影响，伸直时仍残留 5°–20°，线性放大后舵机会微动。
 *      对策：叠加「路径曲率比（curl ratio）」做第二度量，再做软死区 + 5% 量化。
 *
 * curl ratio = 直线距离(根→尖) / 折线长度(根→P1→P2→尖)
 *   伸直 ≈ 0.95–1.00（≈0 屈曲），握拳 ≈ 0.40–0.55（≈100 屈曲）。
 *   该比值随手部尺度等比缩放，不受手掌在画面中的平移/缩放影响，比单关节角稳。
 */

var WRIST = 0;

var FINGER_DEFS = {
  thumb: { label: '拇指', ids: [1, 2, 3, 4], joints: ['cmc', 'mcp', 'ip'] },
  index: { label: '食指', ids: [5, 6, 7, 8], joints: ['mcp', 'pip', 'dip'] },
  middle: { label: '中指', ids: [9, 10, 11, 12], joints: ['mcp', 'pip', 'dip'] },
  ring: { label: '无名指', ids: [13, 14, 15, 16], joints: ['mcp', 'pip', 'dip'] },
  pinky: { label: '小指', ids: [17, 18, 19, 20], joints: ['mcp', 'pip', 'dip'] }
};

var FINGER_ORDER = ['thumb', 'index', 'middle', 'ring', 'pinky'];

var FINGER_BY_INDEX = { 0: 'thumb', 1: 'index', 2: 'middle', 3: 'ring', 4: 'pinky' };

// 21 点骨架连线（用于画覆盖层）
var HAND_CONNECTIONS = [
  [0, 1], [1, 2], [2, 3], [3, 4],
  [0, 5], [5, 6], [6, 7], [7, 8],
  [5, 9], [9, 10], [10, 11], [11, 12],
  [9, 13], [13, 14], [14, 15], [15, 16],
  [13, 17], [17, 18], [18, 19], [19, 20],
  [0, 17]
];

/**
 * VisionKit 的 points 是「图像中的 (x,y) 坐标」，即像素；MediaPipe 是 0–1 归一化。
 * 这里统一归一化到 0–1，后面的算法就与浏览器端完全一致。
 *
 * ⚠️ 首次真机调试务必确认：若你的基础库返回的已经是 0–1，把 normalize 的
 *    pixelSpace 传 false 即可（见 normalizePoints 的第二个参数）。
 */
function normalizePoints(points, width, height, pixelSpace) {
  var out = new Array(points.length);
  if (pixelSpace === false) {
    for (var i = 0; i < points.length; i++) {
      var q = points[i];
      out[i] = { x: q.x, y: q.y, z: q.z || 0 };
    }
    return out;
  }
  var w = width || 1;
  var h = height || 1;
  for (var j = 0; j < points.length; j++) {
    var p = points[j];
    out[j] = { x: p.x / w, y: p.y / h, z: p.z || 0 };
  }
  return out;
}

/** 三点夹角（deg）。z 缺失时退化为纯 2D，与旧实现完全等价。 */
function angleBetween(a, b, c) {
  var abx = a.x - b.x;
  var aby = a.y - b.y;
  var abz = (a.z || 0) - (b.z || 0);
  var cbx = c.x - b.x;
  var cby = c.y - b.y;
  var cbz = (c.z || 0) - (b.z || 0);
  var dot = abx * cbx + aby * cby + abz * cbz;
  var mag = Math.sqrt(abx * abx + aby * aby + abz * abz) *
            Math.sqrt(cbx * cbx + cby * cby + cbz * cbz);
  if (mag < 1e-8) return 0;
  var cos = Math.min(1, Math.max(-1, dot / mag));
  return (Math.acos(cos) * 180) / Math.PI;
}

// MediaPipe / VisionKit 给出的是关节「内角」：伸直时约 180°。统一换算为屈曲角。
function toFlexion(interior) {
  return Math.max(0, 180 - interior);
}

function dist(a, b) {
  var dx = a.x - b.x;
  var dy = a.y - b.y;
  var dz = (a.z || 0) - (b.z || 0);
  return Math.sqrt(dx * dx + dy * dy + dz * dz);
}

/**
 * 路径曲率比：直线距离 / 折线长度。1 = 完全伸直，越小越弯。
 * 与尺度无关，因此不受手离镜头远近影响。
 */
function pathRatio(lm, ids) {
  var base = lm[ids[0]];
  var tip = lm[ids[3]];
  var pathLen = 0;
  for (var i = 0; i < 3; i++) {
    pathLen += dist(lm[ids[i]], lm[ids[i + 1]]);
  }
  if (pathLen < 1e-8) return 1;
  return Math.min(1, dist(base, tip) / pathLen);
}

// 软死区：低于 LO 归一为 0，高于 HI 归一为 100，中间线性过渡。
// 目的：吃掉伸直时的角度残差，避免舵机长期微动/嗡嗡响。
var FLEX_LO = 8;
var FLEX_HI = 92;

// 输出量化步进（%）。SG90 + 连杆的实际分辨率远低于 1%，量化后更稳。
var FLEX_STEP = 5;

/**
 * 由 21 个归一化关键点算出五指关节角。
 * 近端关节（拇指 CMC / 四指 MCP）以手腕 landmark 0 作为掌骨方向参考点。
 *
 * @param {Array} lm 21 点，元素 {x,y,z}
 * @returns {Object} { thumb:{angles:[a0,a1,a2], flex, ratio}, ... }
 */
function computeFingerAngles(lm) {
  var out = {};
  for (var k = 0; k < FINGER_ORDER.length; k++) {
    var name = FINGER_ORDER[k];
    var def = FINGER_DEFS[name];
    var i0 = def.ids[0], i1 = def.ids[1], i2 = def.ids[2], i3 = def.ids[3];
    var angles = [
      toFlexion(angleBetween(lm[WRIST], lm[i0], lm[i1])),
      toFlexion(angleBetween(lm[i0], lm[i1], lm[i2])),
      toFlexion(angleBetween(lm[i1], lm[i2], lm[i3]))
    ];
    if (!isFinite(angles[0])) angles[0] = 0;
    if (!isFinite(angles[1])) angles[1] = 0;
    if (!isFinite(angles[2])) angles[2] = 0;

    // 拇指的 CMC 关节几乎不能屈，且腕→CMC 距离很短，角度噪声大 → 降权
    var w0 = (name === 'thumb') ? 0.35 : 0.8;
    var sumW = w0 + 1 + 1;
    var avg = (angles[0] * w0 + angles[1] + angles[2]) / sumW;
    var angleFlex = Math.min(100, Math.max(0, avg * 1.11));

    var ratio = pathRatio(lm, def.ids);
    var curlFlex = Math.min(100, Math.max(0, ((1 - ratio) / 0.55) * 100));

    // 角度法看关节局部，曲率比看整指形态：各占一半，互补盲区
    var flex = 0.6 * angleFlex + 0.4 * curlFlex;

    out[name] = {
      angles: angles,
      flex: Math.min(100, Math.max(0, flex)),
      ratio: ratio
    };
  }
  return out;
}

/**
 * 把 flex 做「软死区 + 量化」，直写回 angles[name].flex。
 * 在推给 UI / 桥接 / 舵机之前调用一次即可，三处读数保持一致。
 */
function sharpenFlex(angles, opts) {
  var lo = (opts && opts.lo != null) ? opts.lo : FLEX_LO;
  var hi = (opts && opts.hi != null) ? opts.hi : FLEX_HI;
  var step = (opts && opts.step != null) ? opts.step : FLEX_STEP;
  for (var i = 0; i < FINGER_ORDER.length; i++) {
    var d = angles[FINGER_ORDER[i]];
    if (!d) continue;
    var f = d.flex;
    if (f <= lo) f = 0;
    else if (f >= hi) f = 100;
    else f = ((f - lo) / (hi - lo)) * 100;
    if (step > 0) f = Math.round(f / step) * step;
    d.flex = Math.min(100, Math.max(0, f));
  }
  return angles;
}

/**
 * 手掌朝向可用性：食指根 ↔ 小指根 的跨度 / 手腕 ↔ 中指根 的长度。
 * 手掌正对镜头时这个比值会塌到很小，此时 2D 角度最不可靠，适合给用户提示「把手侧过来」。
 * 返回 0–1，越大越「侧对镜头」。
 */
function palmPlaneScore(lm) {
  var span = dist(lm[5], lm[17]);
  var depth = dist(lm[0], lm[9]);
  if (depth < 1e-8) return 0;
  var r = span / depth;
  return Math.min(1, Math.max(0, (r - 0.35) / 0.45));
}

module.exports = {
  WRIST: WRIST,
  FINGER_DEFS: FINGER_DEFS,
  FINGER_ORDER: FINGER_ORDER,
  FINGER_BY_INDEX: FINGER_BY_INDEX,
  HAND_CONNECTIONS: HAND_CONNECTIONS,
  FLEX_LO: FLEX_LO,
  FLEX_HI: FLEX_HI,
  FLEX_STEP: FLEX_STEP,
  normalizePoints: normalizePoints,
  angleBetween: angleBetween,
  toFlexion: toFlexion,
  pathRatio: pathRatio,
  computeFingerAngles: computeFingerAngles,
  sharpenFlex: sharpenFlex,
  palmPlaneScore: palmPlaneScore
};
