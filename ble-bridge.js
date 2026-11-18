// 小楚君机械手 · Web Bluetooth 适配层
// 职责：把视觉端的 flex(0-100) 换算成 servo_i=角度，写入 xiaochu 的 BLE 写特征。
// 只依赖浏览器 Web Bluetooth，不改固件。
// 固件契约见 docs/小楚君机械手-BLE打通.md

(function () {
  "use strict";

  const DEVICE_NAME = "xiaochu";
  const SERVICE_UUID = "89d60870-9908-4472-8f8c-e5b3e6573cd1";
  const WRITE_UUID = "39dea685-a63e-44b2-8819-9a202581f8fe";

  // 与固件 setup() 的标定表一致：open=伸直位置，closed=握拳位置
  // 走 servo_i=angle 直发，绕开固件归一化层的 direction bug
  const FINGERS = [
    { name: "thumb",  label: "拇指",   ch: 0, open: 30,  closed: 180 },
    { name: "index",  label: "食指",   ch: 1, open: 10,  closed: 180 },
    { name: "middle", label: "中指",   ch: 2, open: 180, closed: 0   },
    { name: "ring",   label: "无名指", ch: 3, open: 0,   closed: 180 },
    { name: "pinky",  label: "小指",   ch: 4, open: 180, closed: 35  },
  ];

  const SEND_INTERVAL_MS = 100; // 10 Hz，避开 30 Hz 视觉帧写入压力
  const CHANGE_EPS = 1;         // 角度变化 <= 1° 不重复写
  const CAL_KEY = "bleHandCal_v1";

  // 复刻作者上位机 XiaochuHand.exe 的 PRESET_ANGLES（反编译自 main.pyc）
  // 每指 0-100：0=伸直，100=握拳；顺序 = 拇指/食指/中指/无名指/小指
  // 作者公式：angle = round(v * 1.8)，五指同一映射，无每指特判
  const PRESET_FLEX = {
    five:    [0,   0,   0,   0,   0  ],
    four:    [100, 0,   0,   0,   0  ],
    three:   [100, 0,   0,   0,   100],
    two:     [100, 0,   0,   100, 100],
    one:     [100, 0,   100, 100, 100],
    ok:      [0,   100, 100, 100, 100],
    rock:    [100, 0,   100, 100, 0  ],
    love:    [0,   0,   100, 100, 0  ],
    fist:    [100, 100, 100, 100, 100],
    scratch: [0,   100, 0,   0,   0  ],
    come:    [0,   0,   100, 0,   0  ],
  };
  const PRESET_NAMES = ["five", "four", "three", "two", "one", "ok", "rock", "love", "fist", "scratch", "come"];

  function clampAngle(v) {
    return Math.max(0, Math.min(180, Math.round(Number(v) || 0)));
  }

  // 标定可覆盖：舵机装配方向不同，逐指 open/closed 需要现场重标
  (function loadCalibration() {
    try {
      if (typeof localStorage === "undefined") return;
      const raw = localStorage.getItem(CAL_KEY);
      if (!raw) return;
      const cal = JSON.parse(raw);
      for (const f of FINGERS) {
        const c = cal[f.name];
        if (!c) continue;
        if (c.open !== undefined) f.open = clampAngle(c.open);
        if (c.closed !== undefined) f.closed = clampAngle(c.closed);
      }
    } catch (err) {
      console.warn("[ble] load calibration failed", err);
    }
  })();

  let device = null;
  let server = null;
  let characteristic = null;
  let enabled = false;
  let statusCb = null;

  let latest = null;
  let hasPending = false;
  let flushing = false;
  let lastFlush = 0;
  let lastWritten = {};
  let stats = { frames: 0, writes: 0, errors: 0 };

  function setStatus(text, kind) {
    if (typeof statusCb === "function") statusCb(text, kind || "");
  }

  function flexToAngle(finger, flex) {
    const v = Math.max(0, Math.min(100, Number(flex) || 0));
    return Math.round(finger.open + (finger.closed - finger.open) * v / 100);
  }

  function sleep(ms) {
    return new Promise(function (resolve) { setTimeout(resolve, ms); });
  }

  async function writeText(text) {
    if (!characteristic) return false;
    const bytes = new TextEncoder().encode(text);
    try {
      const props = characteristic.properties || {};
      if (props.writeWithoutResponse && typeof characteristic.writeValueWithoutResponse === "function") {
        await characteristic.writeValueWithoutResponse(bytes);
      } else {
        await characteristic.writeValue(bytes);
      }
      stats.writes += 1;
      return true;
    } catch (err) {
      stats.errors += 1;
      console.warn("[ble] write failed:", text, err);
      return false;
    }
  }

  async function connect() {
    if (!navigator.bluetooth) {
      throw new Error("浏览器不支持 Web Bluetooth，请用桌面版 Chrome / Edge 并通过 localhost 打开");
    }
    if (characteristic && device && device.gatt && device.gatt.connected) {
      setStatus("已连接 " + (device.name || DEVICE_NAME), "ok");
      return true;
    }

    setStatus("搜索设备…", "wait");
    device = await navigator.bluetooth.requestDevice({
      filters: [{ namePrefix: DEVICE_NAME }],
      optionalServices: [SERVICE_UUID],
    });
    device.addEventListener("gattserverdisconnected", onDisconnected);

    setStatus("连接中…", "wait");
    server = await device.gatt.connect();
    const service = await server.getPrimaryService(SERVICE_UUID);
    characteristic = await service.getCharacteristic(WRITE_UUID);

    lastWritten = {};
    stats = { frames: 0, writes: 0, errors: 0 };
    setStatus("已连接 " + (device.name || DEVICE_NAME), "ok");
    return true;
  }

  function onDisconnected() {
    characteristic = null;
    server = null;
    enabled = false;
    setStatus("设备已断开", "err");
  }

  async function disconnect() {
    enabled = false;
    try {
      if (device && device.gatt && device.gatt.connected) device.gatt.disconnect();
    } catch (err) { /* 忽略 */ }
    characteristic = null;
    server = null;
    setStatus("未连接", "");
  }

  function send(fingers) {
    latest = fingers;
    hasPending = true;
    if (!flushing) flushLoop();
  }

  async function flushLoop() {
    flushing = true;
    try {
      while (hasPending) {
        hasPending = false;
        const data = latest;
        const now = performance.now();
        const wait = SEND_INTERVAL_MS - (now - lastFlush);
        if (wait > 0) await sleep(wait);
        lastFlush = performance.now();
        await applyFrame(data);
      }
    } finally {
      flushing = false;
    }
  }

  async function applyFrame(fingers) {
    if (!enabled || !characteristic) return;

    // 丢手：全部回伸直位，避免手停在最后姿态
    if (!fingers) {
      for (const f of FINGERS) {
        if (lastWritten[f.name] === f.open) continue;
        if (await writeText("servo_" + f.ch + "=" + f.open)) lastWritten[f.name] = f.open;
      }
      return;
    }

    for (const f of FINGERS) {
      const node = fingers[f.name];
      const angle = flexToAngle(f, node ? node.flex : 0);
      if (lastWritten[f.name] !== undefined && Math.abs(lastWritten[f.name] - angle) <= CHANGE_EPS) {
        continue;
      }
      if (await writeText("servo_" + f.ch + "=" + angle)) {
        lastWritten[f.name] = angle;
        stats.frames += 1;
      }
    }
  }

  function sendPreset(name) {
    const vals = PRESET_FLEX[name];
    if (!vals) return false;
    const frame = {};
    for (let i = 0; i < FINGERS.length; i += 1) {
      frame[FINGERS[i].name] = { flex: vals[i] };
    }
    send(frame);
    return true;
  }

  window.BleHand = {
    connect: connect,
    disconnect: disconnect,
    send: send,
    sendRaw: writeText,
    sendPreset: sendPreset,
    PRESET_FLEX: PRESET_FLEX,
    PRESET_NAMES: PRESET_NAMES,
    setEnabled: function (v) { enabled = !!v; },
    isEnabled: function () { return enabled; },
    isConnected: function () { return !!characteristic; },
    onStatus: function (cb) { statusCb = cb; },
    flexToAngle: flexToAngle,
    FINGERS: FINGERS,
    getStats: function () { return Object.assign({}, stats); },
    supports: function () { return !!navigator.bluetooth; },
    setCalibration: function (cal, persist) {
      if (!cal) return;
      for (const f of FINGERS) {
        const c = cal[f.name];
        if (!c) continue;
        if (c.open !== undefined) f.open = clampAngle(c.open);
        if (c.closed !== undefined) f.closed = clampAngle(c.closed);
      }
      lastWritten = {};
      if (persist !== false) {
        try {
          localStorage.setItem(CAL_KEY, JSON.stringify(getCalibration()));
        } catch (err) { /* 忽略 */ }
      }
    },
    getCalibration: getCalibration,
    resetCalibration: function () {
      try { localStorage.removeItem(CAL_KEY); } catch (err) { /* 忽略 */ }
      location.reload();
    },
  };

  function getCalibration() {
    const out = {};
    for (const f of FINGERS) out[f.name] = { open: f.open, closed: f.closed };
    return out;
  }

  console.log("[ble] BleHand ready, supports =", !!navigator.bluetooth);
})();
