/**
 * core/glview.js — WebGL 渲染层（相机预览 + 骨架）
 *
 * 为什么必须用 WebGL，而不是「<camera> 组件 + 2D canvas 叠骨架」：
 *   微信 VisionKit 的**实时**人手检测里，摄像头画面由 VKSession 自己产出，
 *   不是 <camera> 组件。官方示例（miniprogram-demo/packageAPI/pages/ar/hand-detect）
 *   的 WXML 里**根本没有 camera 组件**，只有一个 <canvas type="webgl">：
 *
 *     const session = wx.createVKSession({
 *       track: { hand: { mode: 1 } }, version: 'v1', gl,   // ← 必须把 gl 交给会话
 *     })
 *     session.start(err => { ... })
 *     // 逐帧：
 *     const frame = session.getVKFrame(canvas.width, canvas.height)
 *     const { yTexture, uvTexture } = frame.getCameraTexture(gl, 'yuv')
 *
 *   原先那版用了 <camera> 组件做预览，它会独占摄像头，于是 VKSession
 *   start 成功（errno=0）却永远收不到帧 —— updateAnchors 一次都不触发。
 *   这正是真机上「状态显示采集中、有画面、却零回调」的原因。
 *
 * 骨架同样画在这块 GL canvas 里：native 组件（canvas）互相叠加不保证合成，
 * 官方示例也是用 GL 画点。仪表盘（gauge）放在页面另一个不重叠的 2D canvas 里，
 * 因此不存在叠层问题。
 *
 * ────────────────────────────────────────────────────────────────
 * 坐标口径（**这是第二个坑**）：
 *   anchor.points 不是像素，是 **0–1 归一化**坐标。
 *   证据是官方示例的换算：flattenPoints.push(x * 2 - 1, 1 - y * 2)
 *   —— 这正是「0..1 → NDC(-1..1)」，若是像素值这个式子会得到巨大数。
 *   又因为 getVKFrame(canvas.width, canvas.height) 是按画布尺寸取帧的，
 *   所以归一化点乘画布尺寸即得画布像素位置，不需要再做 cover/letterbox 换算。
 * ────────────────────────────────────────────────────────────────
 */

/* ---------------- 着色器 ---------------- */

// 相机画面：YUV → RGB（照搬官方 yuvBehavior.js，含纹理单元 5/6 的约定）
var CAM_VS = [
  'attribute vec2 a_position;',
  'attribute vec2 a_texCoord;',
  'uniform mat3 displayTransform;',
  'varying vec2 v_texCoord;',
  'void main() {',
  '  vec3 p = displayTransform * vec3(a_position, 0);',
  '  gl_Position = vec4(p, 1);',
  '  v_texCoord = a_texCoord;',
  '}'
].join('\n');

var CAM_FS = [
  'precision highp float;',
  'uniform sampler2D y_texture;',
  'uniform sampler2D uv_texture;',
  'varying vec2 v_texCoord;',
  'void main() {',
  '  vec4 y_color = texture2D(y_texture, v_texCoord);',
  '  vec4 uv_color = texture2D(uv_texture, v_texCoord);',
  '  float Y, U, V, R, G, B;',
  '  Y = y_color.r;',
  '  U = uv_color.r - 0.5;',
  '  V = uv_color.a - 0.5;',
  '  R = Y + 1.402 * V;',
  '  G = Y - 0.344 * U - 0.714 * V;',
  '  B = Y + 1.772 * U;',
  '  gl_FragColor = vec4(R, G, B, 1.0);',
  '}'
].join('\n');

// 骨架连线 / 关节分别用两套程序：片元着色器对「点」用 gl_PointCoord 画圆盘，
// 而 gl_PointCoord 对「线」是未定义的，混用会把线整条丢弃。
var PRIM_VS = [
  'attribute vec2 a_pos;',
  'attribute vec4 a_color;',
  'uniform float u_pointSize;',
  'varying vec4 v_color;',
  'void main() {',
  '  gl_Position = vec4(a_pos, 0.0, 1.0);',
  '  gl_PointSize = u_pointSize;',
  '  v_color = a_color;',
  '}'
].join('\n');

var LINE_FS = [
  'precision mediump float;',
  'varying vec4 v_color;',
  'void main() { gl_FragColor = v_color; }'
].join('\n');

var DOT_FS = [
  'precision mediump float;',
  'varying vec4 v_color;',
  'void main() {',
  '  float d = distance(gl_PointCoord, vec2(0.5, 0.5));',
  '  if (d > 0.5) discard;',
  '  gl_FragColor = v_color;',
  '}'
].join('\n');

/* ---------------- 小工具 ---------------- */

function compile(gl, type, src) {
  var s = gl.createShader(type);
  gl.shaderSource(s, src);
  gl.compileShader(s);
  if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
    // 返回 null 让上层能如实报错，而不是静默画不出东西
    return { shader: null, log: gl.getShaderInfoLog(s) };
  }
  return { shader: s, log: '' };
}

function link(gl, vsSrc, fsSrc) {
  var v = compile(gl, gl.VERTEX_SHADER, vsSrc);
  if (!v.shader) return { program: null, log: '顶点着色器编译失败: ' + v.log };
  var f = compile(gl, gl.FRAGMENT_SHADER, fsSrc);
  if (!f.shader) return { program: null, log: '片元着色器编译失败: ' + f.log };
  var p = gl.createProgram();
  gl.attachShader(p, v.shader);
  gl.attachShader(p, f.shader);
  gl.linkProgram(p);
  gl.deleteShader(v.shader);
  gl.deleteShader(f.shader);
  if (!gl.getProgramParameter(p, gl.LINK_STATUS)) {
    return { program: null, log: '程序链接失败: ' + gl.getProgramInfoLog(p) };
  }
  return { program: p, log: '' };
}

/* ---------------- GLView ---------------- */

function GLView(canvas) {
  this.canvas = canvas;
  this.gl = null;
  this.ok = false;
  this.error = '';
  this._points = null;      // 最新一帧的归一化关键点（画骨架用）
  this._focusTipIndex = -1; // 高亮哪一号关键点（重点手指的指尖）
}

GLView.prototype.init = function () {
  var gl = null;
  try {
    gl = this.canvas.getContext('webgl');
  } catch (e) {
    this.error = 'getContext(webgl) 抛错：' + (e && e.message ? e.message : e);
    return false;
  }
  if (!gl) {
    this.error = 'getContext(webgl) 返回 null（该环境不支持 WebGL）';
    return false;
  }
  this.gl = gl;

  // ---- 相机程序 ----
  var cam = link(gl, CAM_VS, CAM_FS);
  if (!cam.program) { this.error = cam.log; return false; }
  this._camProg = cam.program;
  gl.useProgram(this._camProg);
  this._camPosAttr = gl.getAttribLocation(this._camProg, 'a_position');
  this._camTexAttr = gl.getAttribLocation(this._camProg, 'a_texCoord');
  this._camDT = gl.getUniformLocation(this._camProg, 'displayTransform');
  // 与官方一致：y 用纹理单元 5、uv 用 6
  gl.uniform1i(gl.getUniformLocation(this._camProg, 'y_texture'), 5);
  gl.uniform1i(gl.getUniformLocation(this._camProg, 'uv_texture'), 6);

  this._camPosBuf = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, this._camPosBuf);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([1, 1, -1, 1, 1, -1, -1, -1]), gl.STATIC_DRAW);
  this._camTexBuf = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, this._camTexBuf);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([1, 1, 0, 1, 1, 0, 0, 0]), gl.STATIC_DRAW);

  // ---- 骨架程序 ----
  var line = link(gl, PRIM_VS, LINE_FS);
  if (!line.program) { this.error = line.log; return false; }
  this._lineProg = line.program;
  this._linePosAttr = gl.getAttribLocation(this._lineProg, 'a_pos');
  this._lineColAttr = gl.getAttribLocation(this._lineProg, 'a_color');
  this._lineSizeU = gl.getUniformLocation(this._lineProg, 'u_pointSize');

  var dot = link(gl, PRIM_VS, DOT_FS);
  if (!dot.program) { this.error = dot.log; return false; }
  this._dotProg = dot.program;
  this._dotPosAttr = gl.getAttribLocation(this._dotProg, 'a_pos');
  this._dotColAttr = gl.getAttribLocation(this._dotProg, 'a_color');
  this._dotSizeU = gl.getUniformLocation(this._dotProg, 'u_pointSize');

  this._lineBuf = gl.createBuffer();
  this._dotBuf = gl.createBuffer();

  gl.disable(gl.DEPTH_TEST);
  gl.enable(gl.BLEND);
  gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
  gl.clearColor(0, 0, 0, 1);
  gl.clear(gl.COLOR_BUFFER_BIT);

  this.ok = true;
  return true;
};

/** 归一化点(0–1) → NDC(-1..1)。与官方 flattenPoints.push(x*2-1, 1-y*2) 同一口径。 */
function toNDC(x, y, mirror) {
  var px = mirror ? (1 - x) : x;
  return [px * 2 - 1, 1 - y * 2];
}

GLView.prototype.setPoints = function (points, focusTipIndex) {
  this._points = points;
  this._focusTipIndex = focusTipIndex == null ? -1 : focusTipIndex;
};

/** 由 index.js 在主循环里每帧调用：先画相机画面，再叠骨架。 */
GLView.prototype.render = function (frame, connections, mirror) {
  var gl = this.gl;
  if (!this.ok || !gl) return;

  // ---- 1. 相机画面 ----
  if (frame) {
    var tex = frame.getCameraTexture(gl, 'yuv');
    if (tex && tex.yTexture && tex.uvTexture) {
      gl.useProgram(this._camProg);
      gl.bindBuffer(gl.ARRAY_BUFFER, this._camPosBuf);
      gl.enableVertexAttribArray(this._camPosAttr);
      gl.vertexAttribPointer(this._camPosAttr, 2, gl.FLOAT, false, 0, 0);
      gl.bindBuffer(gl.ARRAY_BUFFER, this._camTexBuf);
      gl.enableVertexAttribArray(this._camTexAttr);
      gl.vertexAttribPointer(this._camTexAttr, 2, gl.FLOAT, false, 0, 0);

      if (typeof frame.getDisplayTransform === 'function') {
        gl.uniformMatrix3fv(this._camDT, false, frame.getDisplayTransform());
      }
      gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
      gl.activeTexture(gl.TEXTURE0 + 5);
      gl.bindTexture(gl.TEXTURE_2D, tex.yTexture);
      gl.activeTexture(gl.TEXTURE0 + 6);
      gl.bindTexture(gl.TEXTURE_2D, tex.uvTexture);

      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);

      gl.activeTexture(gl.TEXTURE0 + 5);
      gl.bindTexture(gl.TEXTURE_2D, null);
      gl.activeTexture(gl.TEXTURE0 + 6);
      gl.bindTexture(gl.TEXTURE_2D, null);
    }
  } else {
    gl.clear(gl.COLOR_BUFFER_BIT);
  }

  // ---- 2. 骨架 ----
  var pts = this._points;
  if (!pts || pts.length < 21) return;

  var dpr = this.dpr || 1;
  var i, ndc, a, b;

  // 连线
  if (connections && connections.length) {
    var lv = [];
    for (i = 0; i < connections.length; i++) {
      a = pts[connections[i][0]];
      b = pts[connections[i][1]];
      if (!a || !b) continue;
      var na = toNDC(a.x, a.y, mirror);
      var nb = toNDC(b.x, b.y, mirror);
      lv.push(na[0], na[1], 0.24, 0.81, 0.56, 0.9);
      lv.push(nb[0], nb[1], 0.24, 0.81, 0.56, 0.9);
    }
    if (lv.length) {
      gl.useProgram(this._lineProg);
      gl.uniform1f(this._lineSizeU, 1);
      gl.bindBuffer(gl.ARRAY_BUFFER, this._lineBuf);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(lv), gl.DYNAMIC_DRAW);
      gl.enableVertexAttribArray(this._linePosAttr);
      gl.vertexAttribPointer(this._linePosAttr, 2, gl.FLOAT, false, 24, 0);
      gl.enableVertexAttribArray(this._lineColAttr);
      gl.vertexAttribPointer(this._lineColAttr, 4, gl.FLOAT, false, 24, 8);
      gl.drawArrays(gl.LINES, 0, lv.length / 6);
    }
  }

  // 关节点
  var dv = [];
  for (i = 0; i < pts.length; i++) {
    ndc = toNDC(pts[i].x, pts[i].y, mirror);
    if (i === this._focusTipIndex) dv.push(ndc[0], ndc[1], 0.94, 0.71, 0.16, 1);
    else dv.push(ndc[0], ndc[1], 0.35, 0.82, 1.0, 1);
  }
  if (dv.length) {
    gl.useProgram(this._dotProg);
    gl.uniform1f(this._dotSizeU, 7 * dpr);
    gl.bindBuffer(gl.ARRAY_BUFFER, this._dotBuf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(dv), gl.DYNAMIC_DRAW);
    gl.enableVertexAttribArray(this._dotPosAttr);
    gl.vertexAttribPointer(this._dotPosAttr, 2, gl.FLOAT, false, 24, 0);
    gl.enableVertexAttribArray(this._dotColAttr);
    gl.vertexAttribPointer(this._dotColAttr, 4, gl.FLOAT, false, 24, 8);
    gl.drawArrays(gl.POINTS, 0, dv.length / 6);
  }
};

GLView.prototype.destroy = function () {
  var gl = this.gl;
  if (!gl) return;
  try {
    if (this._camProg) gl.deleteProgram(this._camProg);
    if (this._lineProg) gl.deleteProgram(this._lineProg);
    if (this._dotProg) gl.deleteProgram(this._dotProg);
    if (this._camPosBuf) gl.deleteBuffer(this._camPosBuf);
    if (this._camTexBuf) gl.deleteBuffer(this._camTexBuf);
    if (this._lineBuf) gl.deleteBuffer(this._lineBuf);
    if (this._dotBuf) gl.deleteBuffer(this._dotBuf);
  } catch (e) { /* 忽略 */ }
  this.gl = null;
  this.ok = false;
};

module.exports = { GLView: GLView };
