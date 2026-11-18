/**
 * core/ble-hand.js — 小楚君机械手 BLE 直连（微信小程序）
 *
 * 与网页端 ble-bridge.js 同一套契约：
 *   flex(0-100) → angle = open + flex/100 * (closed-open)
 *   → ASCII "servo_<ch>=<angle>" → 写入特征
 *
 * 走 servo_i=angle 角度直发，绕开固件归一化层的 direction bug。
 * 10Hz 节流；角度变化 ≤1° 不重写；手丢失时全指回伸直位。
 *
 * 典型用法：
 *   var bleMod = require('../../core/ble-hand.js');
 *   this.ble = bleMod.createBleHand({ onStatus: function (t, k) { ... } });
 *   this.ble.connect(function (err) { ... });
 *   this.ble.setEnabled(true);
 *   this.ble.send(angles);   // angles[name].flex
 *   this.ble.send(null);     // 手离开画面
 */

var DEVICE_NAME = 'xiaochu';
var SERVICE_UUID = '89d60870-9908-4472-8f8c-e5b3e6573cd1';
var WRITE_UUID = '39dea685-a63e-44b2-8819-9a202581f8fe';

var FINGERS = [
  { name: 'thumb',  label: '拇指',   ch: 0, open: 30,  closed: 180 },
  { name: 'index',  label: '食指',   ch: 1, open: 10,  closed: 180 },
  { name: 'middle', label: '中指',   ch: 2, open: 180, closed: 0   },
  { name: 'ring',   label: '无名指', ch: 3, open: 0,   closed: 180 },
  { name: 'pinky',  label: '小指',   ch: 4, open: 180, closed: 35  }
];

var SEND_INTERVAL_MS = 100;
var CHANGE_EPS = 1;
var SCAN_TIMEOUT_MS = 20000;

function sameUuid(a, b) {
  return String(a || '').toLowerCase() === String(b || '').toLowerCase();
}

function flexToAngle(finger, flex) {
  var v = Math.max(0, Math.min(100, Number(flex) || 0));
  return Math.round(finger.open + (finger.closed - finger.open) * v / 100);
}

function createBleHand(opts) {
  opts = opts || {};
  var onStatus = opts.onStatus || function () {};

  var deviceId = null;
  var serviceId = null;
  var charId = null;
  var enabled = false;
  var connecting = false;
  var adapterReady = false;

  var writeQueue = [];
  var writing = false;

  var latest = null;
  var hasPending = false;
  var flushing = false;
  var lastFlush = 0;
  var lastWritten = {};

  var scanTimer = null;
  var deviceFoundHandler = null;

  function status(text, kind) {
    onStatus(text, kind || '');
  }

  function resetLink() {
    deviceId = null;
    serviceId = null;
    charId = null;
    enabled = false;
    latest = null;
    hasPending = false;
    writeQueue = [];
    writing = false;
    lastWritten = {};
  }

  /* ---------------- 写入队列（小程序要求串行写） ---------------- */

  function writeText(text, cb) {
    writeQueue.push({ text: text, cb: cb });
    if (!writing) flushWrite();
  }

  function flushWrite() {
    if (!writeQueue.length) {
      writing = false;
      return;
    }
    writing = true;
    var job = writeQueue.shift();

    if (!charId || !deviceId || !serviceId) {
      if (job.cb) job.cb(false, 'not connected');
      flushWrite();
      return;
    }

    var buffer = new ArrayBuffer(job.text.length);
    var view = new Uint8Array(buffer);
    for (var i = 0; i < job.text.length; i++) view[i] = job.text.charCodeAt(i);

    wx.writeBLECharacteristicValue({
      deviceId: deviceId,
      serviceId: serviceId,
      characteristicId: charId,
      value: buffer,
      success: function () {
        if (job.cb) job.cb(true);
        flushWrite();
      },
      fail: function (err) {
        console.warn('[ble] write fail', job.text, err);
        if (job.cb) job.cb(false, err);
        flushWrite();
      }
    });
  }

  /* ---------------- 连接流程 ---------------- */

  function connect(callback) {
    if (connecting) return;
    if (charId && deviceId) {
      status('已连接', 'ok');
      if (callback) callback(null);
      return;
    }
    connecting = true;
    status('打开蓝牙…', 'wait');

    wx.openBluetoothAdapter({
      success: function () {
        adapterReady = true;
        status('扫描 xiaochu…', 'wait');
        startScan(callback);
      },
      fail: function (err) {
        connecting = false;
        var msg = '打开蓝牙失败';
        if (err && err.errCode === 10001) msg = '系统蓝牙未开启';
        else if (err && err.errCode === 10006) msg = '蓝牙不可用，请检查系统设置';
        status(msg, 'err');
        if (callback) callback(err || new Error(msg));
      }
    });
  }

  function startScan(callback) {
    wx.startBluetoothDevicesDiscovery({
      allowDuplicatesKey: false,
      success: function () {
        if (scanTimer) clearTimeout(scanTimer);
        scanTimer = setTimeout(function () {
          stopScan();
          status('未找到 xiaochu（确认设备已上电）', 'err');
          connecting = false;
          if (callback) callback(new Error('device not found'));
        }, SCAN_TIMEOUT_MS);

        listenFound(callback);
      },
      fail: function (err) {
        connecting = false;
        status('扫描启动失败', 'err');
        if (callback) callback(err);
      }
    });
  }

  function listenFound(callback) {
    if (deviceFoundHandler) {
      wx.offBluetoothDeviceFound(deviceFoundHandler);
      deviceFoundHandler = null;
    }
    deviceFoundHandler = function (res) {
      var list = (res && res.devices) || [];
      for (var i = 0; i < list.length; i++) {
        var d = list[i];
        var name = String(d.name || d.localName || '').toLowerCase();
        if (name === DEVICE_NAME || name.indexOf(DEVICE_NAME) === 0) {
          if (scanTimer) { clearTimeout(scanTimer); scanTimer = null; }
          stopScan();
          linkDevice(d.deviceId, callback);
          return;
        }
      }
    };
    wx.onBluetoothDeviceFound(deviceFoundHandler);
  }

  function stopScan() {
    try { wx.stopBluetoothDevicesDiscovery({}); } catch (e) { /* 忽略 */ }
  }

  function linkDevice(id, callback) {
    status('连接中…', 'wait');
    deviceId = id;
    wx.createBLEConnection({
      deviceId: id,
      timeout: 12000,
      success: function () {
        findService(callback);
      },
      fail: function (err) {
        deviceId = null;
        connecting = false;
        status('连接失败', 'err');
        if (callback) callback(err);
      }
    });
  }

  function findService(callback) {
    wx.getBLEDeviceServices({
      deviceId: deviceId,
      success: function (res) {
        var services = (res && res.services) || [];
        var hit = null;
        for (var i = 0; i < services.length; i++) {
          if (sameUuid(services[i].uuid, SERVICE_UUID)) { hit = services[i]; break; }
        }
        if (!hit) {
          connecting = false;
          status('未找到目标 Service', 'err');
          if (callback) callback(new Error('service not found'));
          return;
        }
        serviceId = hit.uuid;
        findChar(callback);
      },
      fail: function (err) {
        connecting = false;
        status('读取 Service 失败', 'err');
        if (callback) callback(err);
      }
    });
  }

  function findChar(callback) {
    wx.getBLEDeviceCharacteristics({
      deviceId: deviceId,
      serviceId: serviceId,
      success: function (res) {
        var chars = (res && res.characteristics) || [];
        var hit = null;
        for (var i = 0; i < chars.length; i++) {
          if (sameUuid(chars[i].uuid, WRITE_UUID)) { hit = chars[i]; break; }
        }
        if (!hit) {
          // 回退：任一带写属性的特征
          for (var j = 0; j < chars.length; j++) {
            var p = chars[j].properties || {};
            if (p.write || p.writeNoResponse) { hit = chars[j]; break; }
          }
        }
        if (!hit) {
          connecting = false;
          status('未找到可写特征', 'err');
          if (callback) callback(new Error('write characteristic not found'));
          return;
        }
        charId = hit.uuid;
        connecting = false;
        lastWritten = {};
        status('已连接', 'ok');
        watchConnection();
        if (callback) callback(null);
      },
      fail: function (err) {
        connecting = false;
        status('读取特征失败', 'err');
        if (callback) callback(err);
      }
    });
  }

  function watchConnection() {
    wx.onBLEConnectionStateChange(function (res) {
      if (res && res.deviceId === deviceId && !res.connected) {
        resetLink();
        status('设备已断开', 'err');
      }
    });
  }

  function disconnect(callback) {
    var id = deviceId;
    resetLink();
    status('未连接', '');
    if (id) {
      wx.closeBLEConnection({
        deviceId: id,
        complete: function () { if (callback) callback(); }
      });
    } else if (callback) {
      callback();
    }
  }

  /* ---------------- 帧推送 ---------------- */

  function send(angles) {
    latest = angles;
    hasPending = true;
    if (!flushing) flushLoop();
  }

  function flushLoop() {
    flushing = true;

    function step() {
      if (!hasPending) { flushing = false; return; }
      hasPending = false;
      var data = latest;
      var now = Date.now();
      var wait = SEND_INTERVAL_MS - (now - lastFlush);
      setTimeout(function () {
        lastFlush = Date.now();
        applyFrame(data, step);
      }, wait > 0 ? wait : 0);
    }

    step();
  }

  function applyFrame(angles, done) {
    if (!enabled || !charId) { done(); return; }
    var i = 0;

    function next() {
      if (i >= FINGERS.length) { done(); return; }
      var f = FINGERS[i++];
      // angles 为 null：手离开画面，全指回伸直位
      var angle = angles
        ? flexToAngle(f, angles[f.name] ? angles[f.name].flex : 0)
        : f.open;

      if (lastWritten[f.name] !== undefined && Math.abs(lastWritten[f.name] - angle) <= CHANGE_EPS) {
        next();
        return;
      }

      writeText('servo_' + f.ch + '=' + angle, function (ok) {
        if (ok) lastWritten[f.name] = angle;
        next();
      });
    }

    next();
  }

  // 回伸直位：不看 enabled，直接写 5 条，用于关闭采集时松手
  function park(cb) {
    hasPending = false;
    latest = null;
    lastWritten = {};
    var i = 0;

    function next() {
      if (i >= FINGERS.length) { if (cb) cb(); return; }
      var f = FINGERS[i++];
      writeText('servo_' + f.ch + '=' + f.open, function (ok) {
        if (ok) lastWritten[f.name] = f.open;
        next();
      });
    }

    next();
  }

  return {
    connect: connect,
    disconnect: disconnect,
    send: send,
    sendRaw: writeText,
    park: park,
    setEnabled: function (v) { enabled = !!v; },
    isEnabled: function () { return enabled; },
    isConnected: function () { return !!charId; },
    flexToAngle: flexToAngle,
    FINGERS: FINGERS,
    destroy: function () {
      disconnect();
      if (deviceFoundHandler) {
        wx.offBluetoothDeviceFound(deviceFoundHandler);
        deviceFoundHandler = null;
      }
      if (scanTimer) { clearTimeout(scanTimer); scanTimer = null; }
      if (adapterReady) {
        try { wx.closeBluetoothAdapter({}); } catch (e) { /* 忽略 */ }
        adapterReady = false;
      }
    }
  };
}

module.exports = {
  createBleHand: createBleHand,
  flexToAngle: flexToAngle,
  FINGERS: FINGERS,
  DEVICE_NAME: DEVICE_NAME,
  SERVICE_UUID: SERVICE_UUID,
  WRITE_UUID: WRITE_UUID
};
