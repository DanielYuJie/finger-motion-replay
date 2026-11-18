// pages/pad/index.js — 小程序端上位机（对应网页 hand-pad 与作者 XiaochuHand）
var core = require('../../core/ble-hand');

var ZH = {
  five: '张开', four: '四', three: '三', two: '二', one: '一',
  ok: 'OK', rock: '摇滚', love: '比心', fist: '握拳', scratch: '挠', come: '过来'
};

// 与作者上位机 PRESET_ANGLES 相同，每指 0-100（0=伸直，100=握拳）
var PRESET_FLEX = {
  five:    [0, 0, 0, 0, 0],
  four:    [100, 0, 0, 0, 0],
  three:   [100, 0, 0, 0, 100],
  two:     [100, 0, 0, 100, 100],
  one:     [100, 0, 100, 100, 100],
  ok:      [0, 100, 100, 100, 100],
  rock:    [100, 0, 100, 100, 0],
  love:    [0, 0, 100, 100, 0],
  fist:    [100, 100, 100, 100, 100],
  scratch: [0, 100, 0, 0, 0],
  come:    [0, 0, 100, 0, 0]
};

var PRESET_NAMES = ['five', 'four', 'three', 'two', 'one', 'ok', 'rock', 'love', 'fist', 'scratch', 'come'];

Page({
  data: {
    connected: false,
    status: '未连接',
    statusKind: '',
    fingers: [],
    cals: [],
    presets: [],
    customText: '',
    logs: []
  },

  onLoad: function () {
    var self = this;
    this.hand = core.createBleHand({
      onStatus: function (text, kind) {
        self.setData({
          status: text,
          statusKind: kind || '',
          connected: self.hand.isConnected()
        });
        self.log('状态：' + text);
      }
    });

    this.setData({
      fingers: core.FINGERS.map(function (f) {
        return { name: f.name, label: f.label, ch: f.ch, flex: 0, angle: f.open };
      }),
      cals: core.FINGERS.map(function (f) {
        return { name: f.name, label: f.label, ch: f.ch, open: f.open, closed: f.closed };
      }),
      presets: PRESET_NAMES.map(function (n) {
        return { name: n, zh: ZH[n] || n };
      })
    });
  },

  onUnload: function () {
    if (this.hand) this.hand.destroy();
  },

  /* ---------------- 工具 ---------------- */

  log: function (msg) {
    var t = new Date();
    var hh = ('0' + t.getHours()).slice(-2);
    var mm = ('0' + t.getMinutes()).slice(-2);
    var ss = ('0' + t.getSeconds()).slice(-2);
    var logs = this.data.logs.slice();
    logs.unshift('[' + hh + ':' + mm + ':' + ss + '] ' + msg);
    this.setData({ logs: logs.slice(0, 10) });
  },

  pushFingers: function () {
    if (!this.hand || !this.hand.isConnected()) return;
    var frame = {};
    this.data.fingers.forEach(function (f) {
      frame[f.name] = { flex: f.flex };
    });
    this.hand.setEnabled(true);
    this.hand.send(frame);
  },

  refreshAngles: function () {
    var fingers = this.data.fingers.map(function (f, i) {
      var af = core.FINGERS[i];
      return { name: f.name, label: f.label, ch: f.ch, flex: f.flex, angle: core.flexToAngle(af, f.flex) };
    });
    this.setData({ fingers: fingers });
  },

  /* ---------------- 连接 ---------------- */

  onConnect: function () {
    var self = this;
    this.log('开始连接 xiaochu…');
    this.hand.connect(function (err) {
      if (err) {
        self.log('连接失败');
        return;
      }
      self.setData({ connected: self.hand.isConnected() });
      self.hand.setEnabled(true);
      self.log('已连接');
    });
  },

  onDisconnect: function () {
    this.hand.disconnect();
    this.setData({ connected: false });
  },

  /* ---------------- 滑杆 ---------------- */

  onSlider: function (e) {
    var name = e.currentTarget.dataset.name;
    var v = Number(e.detail.value);
    var fingers = this.data.fingers.map(function (f, i) {
      if (f.name !== name) return f;
      return { name: f.name, label: f.label, ch: f.ch, flex: v, angle: core.flexToAngle(core.FINGERS[i], v) };
    });
    this.setData({ fingers: fingers });
    this.pushFingers();
  },

  /* ---------------- 预设 ---------------- */

  onPreset: function (e) {
    var name = e.currentTarget.dataset.name;
    var vals = PRESET_FLEX[name];
    if (!vals) return;
    var fingers = this.data.fingers.map(function (f, i) {
      return { name: f.name, label: f.label, ch: f.ch, flex: vals[i], angle: core.flexToAngle(core.FINGERS[i], vals[i]) };
    });
    this.setData({ fingers: fingers });
    this.pushFingers();
    this.log('预设 ' + name + ' → [' + vals.join(',') + ']');
  },

  /* ---------------- 自定义指令 ---------------- */

  onCustomInput: function (e) {
    this.setData({ customText: e.detail.value });
  },

  onCustomSend: function () {
    var self = this;
    var cmd = String(this.data.customText || '').trim();
    if (!cmd) return;
    if (!this.hand.isConnected()) {
      this.log('未连接，未发送');
      return;
    }
    this.hand.sendRaw(cmd, function (ok) {
      self.log('TX ' + cmd + (ok ? '  OK' : '  失败'));
    });
  },

  /* ---------------- 标定 ---------------- */

  onCalInput: function (e) {
    var name = e.currentTarget.dataset.name;
    var prop = e.currentTarget.dataset.prop;
    var raw = e.detail.value;
    var v = parseInt(raw, 10);
    if (!isFinite(v)) v = 0;
    var cals = this.data.cals.map(function (c) {
      if (c.name !== name) return c;
      var next = { name: c.name, label: c.label, ch: c.ch, open: c.open, closed: c.closed };
      next[prop] = v;
      return next;
    });
    this.setData({ cals: cals });
  },

  onTestAngle: function (e) {
    var self = this;
    var name = e.currentTarget.dataset.name;
    var prop = e.currentTarget.dataset.prop;
    var cal = null;
    for (var i = 0; i < this.data.cals.length; i++) {
      if (this.data.cals[i].name === name) { cal = this.data.cals[i]; break; }
    }
    if (!cal) return;
    var raw = prop === 'open' ? cal.open : cal.closed;
    var v = Math.max(0, Math.min(180, Math.round(Number(raw) || 0)));
    if (!this.hand.isConnected()) {
      this.log('未连接，未发送');
      return;
    }
    this.hand.sendRaw('servo_' + cal.ch + '=' + v, function (ok) {
      self.log(cal.label + ' 试发 ' + v + '°' + (ok ? '' : '  失败'));
    });
  },

  onApplyCal: function () {
    var cal = {};
    this.data.cals.forEach(function (c) {
      cal[c.name] = {
        open: Math.max(0, Math.min(180, Math.round(Number(c.open) || 0))),
        closed: Math.max(0, Math.min(180, Math.round(Number(c.closed) || 0)))
      };
    });
    this.hand.setCalibration(cal, true);
    this.refreshAngles();
    this.pushFingers();
    this.log('已应用标定');
  },

  onResetCal: function () {
    this.hand.resetCalibration();
    this.setData({
      cals: core.FINGERS.map(function (f) {
        return { name: f.name, label: f.label, ch: f.ch, open: f.open, closed: f.closed };
      })
    });
    this.refreshAngles();
    this.log('已恢复默认标定');
  }
});
