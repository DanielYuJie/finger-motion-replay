// pages/remote/index.js — PC 推理模式：本机摄像头抓帧 → 局域网 PC 跑 MediaPipe → 回传五指角度
//
// 为什么要这个页面：
//   小程序自带的 VisionKit 只有官方那一套模型，手背朝镜头 / 手指被手背挡住时识别很弱。
//   XiaochuHand.exe 用的 MediaPipe hand_landmarker.task 在同样的场景下稳得多，但模型塞不进小程序。
//   折中办法：模型留在电脑，小程序只负责「抓帧 + 显示 + 推 BLE」。
//
// 链路：camera.onCameraFrame → base64(RGBA) → POST {PC}/infer → flex → BLE
var core = require('../../core/ble-hand');

var URL_KEY = 'pcServerUrl';
var THROTTLE_MS = 200;   // 5 Hz 上传。BLE 侧本来就是 10Hz 节流，再快没意义
var REQ_TIMEOUT = 1200;

function trimUrl(u) {
  return (u || '').trim().replace(/\/+$/, '');
}

Page({
  data: {
    url: '',
    device: 'front',
    pcState: '未连接 PC',
    pcOk: false,
    running: false,
    drive: false,
    bleConnected: false,
    bleStatus: '未连接机械手',
    latency: '—',
    fps: '—',
    handVisible: false,
    flex: [],
    logs: []
  },

  onLoad: function () {
    var self = this;
    var saved = trimUrl(wx.getStorageSync(URL_KEY)) || 'http://192.168.1.9:8767';

    this.hand = core.createBleHand({
      onStatus: function (text, kind) {
        self.setData({
          bleStatus: text,
          bleConnected: self.hand.isConnected()
        });
        self.log('机械手：' + text);
      }
    });

    this.setData({
      url: saved,
      flex: core.FINGERS.map(function (f) {
        return { name: f.name, label: f.label, flex: 0 };
      })
    });

    this._busy = false;
    this._sent = 0;
    this._ok = 0;
    this._fpsAt = 0;
  },

  onUnload: function () {
    this.stopFrames();
    if (this.hand) this.hand.destroy();
  },

  onHide: function () {
    this.stopFrames();
  },

  /* ---------------- 交互 ---------------- */

  onUrlInput: function (e) {
    this.setData({ url: e.detail.value });
    wx.setStorageSync(URL_KEY, e.detail.value);
  },

  onSwitchDevice: function () {
    this.setData({ device: this.data.device === 'front' ? 'back' : 'front' });
  },

  onCamError: function (e) {
    this.setData({ pcState: '摄像头错误', pcOk: false });
    this.log('camera error：' + JSON.stringify(e.detail || {}));
  },

  onPing: function () {
    var self = this;
    var base = trimUrl(this.data.url);
    if (!base) return;
    wx.request({
      url: base + '/health',
      method: 'GET',
      timeout: 1500,
      success: function (r) {
        var d = r.data || {};
        var ok = d.ok && d.modelExists !== false;
        self.setData({
          pcOk: !!ok,
          pcState: ok ? ('PC 在线（' + (d.model || 'model') + '）') : 'PC 返回异常'
        });
        self.log(ok ? 'PC 在线' : ('PC 异常：' + JSON.stringify(d)));
      },
      fail: function (e) {
        self.setData({ pcOk: false, pcState: 'PC 不可达' });
        self.log('PC 不可达：' + (e.errMsg || e));
      }
    });
  },

  onStart: function () {
    if (this.data.running) { this.stopFrames(); return; }
    var self = this;

    // 官方 API：onCameraFrame 返回 CameraFrameListener，必须再调 start() 才真正开始收帧
    var ctx = wx.createCameraContext();
    this._listener = ctx.onCameraFrame(function (frame) {
      self.onFrame(frame);
    });
    if (this._listener && typeof this._listener.start === 'function') this._listener.start();

    this.setData({ running: true, pcState: '抓帧中，等首帧…' });
    this.log('开始抓帧（' + THROTTLE_MS + 'ms 一帧）');
    // 顺手探一下 PC
    this.onPing();
  },

  stopFrames: function () {
    if (this._listener) {
      try {
        if (typeof this._listener.stop === 'function') this._listener.stop();
      } catch (e) { /* 忽略 */ }
      this._listener = null;
    }
    this._busy = false;
    if (this.data.running) {
      this.setData({ running: false, handVisible: false, latency: '—', fps: '—' });
      if (this.hand) this.hand.send(null);   // 松手：机械手回伸直位
    }
  },

  onToggleDrive: function (e) {
    var on = !!(e.detail && e.detail.value);
    this.setData({ drive: on });
    if (this.hand) this.hand.setEnabled(on);
    this.log('驱动机械手：' + (on ? '开' : '关'));
  },

  onBleConnect: function () {
    if (this.hand && this.hand.isConnected()) {
      this.hand.disconnect();
      this.setData({ bleConnected: false });
      return;
    }
    var self = this;
    this.hand.connect(function () {
      self.setData({ bleConnected: self.hand.isConnected() });
    });
  },

  /* ---------------- 抓帧 → 上传 ---------------- */

  onFrame: function (frame) {
    if (!this._listener || !frame || !frame.data) return;
    var now = Date.now();
    if (now - (this._lastFrameAt || 0) < THROTTLE_MS) return;
    this._lastFrameAt = now;
    if (this._busy) return;                 // 上一帧还没回来，直接丢，避免请求堆积

    var w = frame.width;
    var h = frame.height;
    if (!w || !h || !frame.data.byteLength) return;

    var base64;
    try {
      base64 = wx.arrayBufferToBase64(frame.data);
    } catch (e) {
      this.log('转 base64 失败：' + (e && e.message));
      return;
    }

    var self = this;
    var t0 = now;
    this._busy = true;
    this._sent++;

    wx.request({
      url: trimUrl(this.data.url) + '/infer',
      method: 'POST',
      data: { w: w, h: h, data: base64 },
      header: { 'content-type': 'application/json' },
      timeout: REQ_TIMEOUT,
      success: function (r) {
        self._busy = false;
        var d = r.data || {};
        if (!d.ok) {
          self.setData({ pcOk: false, pcState: 'PC 报错' });
          return;
        }
        self._ok++;
        var angles = {};
        var cards = self.data.flex;
        var first = null;
        for (var i = 0; i < core.FINGERS.length; i++) {
          var f = core.FINGERS[i];
          var v = d.hand && d.flex ? (d.flex[f.name] || 0) : 0;
          angles[f.name] = { flex: v };
          cards[i].flex = v;
          if (!first) first = f.name + ' ' + v;
        }

        self.setData({
          pcOk: d.hand === true,
          pcState: d.hand ? ('识别中 · ' + (first || '')) : '未见手',
          handVisible: !!d.hand,
          latency: (Date.now() - t0) + ' ms',
          fps: self.tickFps(now),
          flex: cards
        });

        if (self.data.drive && self.hand) {
          // 手丢了也要发：ble-hand 收到 null 会把五指写回伸直位
          self.hand.send(d.hand ? angles : null);
        }
      },
      fail: function (e) {
        self._busy = false;
        self.setData({ pcOk: false, pcState: '上传失败' });
        self.log('上传失败：' + (e.errMsg || e));
      }
    });
  },

  tickFps: function (now) {
    if (!this._fpsAt) { this._fpsAt = now; return '—'; }
    var dt = now - this._fpsAt;
    if (dt < 1000) return this.data.fps;
    var v = Math.round((this._ok * 1000) / dt);
    this._ok = 0;
    this._fpsAt = now;
    return v + ' fps';
  },

  log: function (msg) {
    var logs = [{ t: new Date().toLocaleTimeString(), msg: msg }].concat(this.data.logs || []);
    this.setData({ logs: logs.slice(0, 6) });
  }
});
