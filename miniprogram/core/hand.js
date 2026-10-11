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

function angleBetween(a, b, c) {
  var abx = a.x - b.x;
  var aby = a.y - b.y;
  var cbx = c.x - b.x;
  var cby = c.y - b.y;
  var dot = abx * cbx + aby * cby;
  var mag = Math.sqrt(abx * abx + aby * aby) * Math.sqrt(cbx * cbx + cby * cby);
  if (mag < 1e-8) return 0;
  var cos = Math.min(1, Math.max(-1, dot / mag));
  return (Math.acos(cos) * 180) / Math.PI;
}

// MediaPipe / VisionKit 给出的是关节「内角」：伸直时约 180°。统一换算为屈曲角。
function toFlexion(interior) {
  return Math.max(0, 180 - interior);
}

/**
 * 由 21 个归一化关键点算出五指关节角。
 * 近端关节（拇指 CMC / 四指 MCP）以手腕 landmark 0 作为掌骨方向参考点。
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
    out[name] = {
      angles: angles,
      flex: Math.min(100, (angles[0] + angles[1] + angles[2]) / 2.7)
    };
  }
  return out;
}

module.exports = {
  WRIST: WRIST,
  FINGER_DEFS: FINGER_DEFS,
  FINGER_ORDER: FINGER_ORDER,
  FINGER_BY_INDEX: FINGER_BY_INDEX,
  HAND_CONNECTIONS: HAND_CONNECTIONS,
  normalizePoints: normalizePoints,
  angleBetween: angleBetween,
  toFlexion: toFlexion,
  computeFingerAngles: computeFingerAngles
};
