// 经典脚本：避免 ES module 加载失败导致按钮无响应
(function () {
  "use strict";

  function $(id) {
    return document.getElementById(id);
  }

  const video = $("video");
  const overlay = $("overlay");
  const viewport = $("viewport");
  const placeholder = $("placeholder");
  const handBadge = $("handBadge");
  const statusEl = $("status");
  const statusText = $("statusText");
  const resolutionEl = $("resolution");
  const fpsEl = $("fps");
  const inferMsEl = $("inferMs");
  const deviceNameEl = $("deviceName");
  const deviceSelect = $("deviceSelect");
  const fingerSelect = $("fingerSelect");
  const mirrorCheck = $("mirror");
  const showAnglesCheck = $("showAngles");
  const showTrailCheck = $("showTrail");
  const btnStart = $("btnStart");
  const btnStop = $("btnStop");
  const btnSnapshot = $("btnSnapshot");
  const btnFullscreen = $("btnFullscreen");
  const errorBox = $("errorBox");
  const errorText = $("errorText");
  const focusAngleEl = $("focusAngle");
  const focusGaugeEl = $("focusGauge");
  const angleCards = Array.from(document.querySelectorAll(".angle-card"));

  console.log("[mc] script start");

  if (!btnStart) {
    console.error("[mc] btnStart missing");
    return;
  }

  // 本地 vendor 资源（import 需绝对/相对 URL）
  const MODEL_URL = new URL("./vendor/hand_landmarker.task", window.location.href).href;
  // 注意：不加尾斜杠，vision_bundle 会再拼 "/<name>.js"，否则会出现 // 双斜杠
  const WASM_BASE = new URL("./vendor/wasm", window.location.href).href;
  const VISION_CANDIDATES = [
    new URL("./vendor/vision_bundle.mjs", window.location.href).href,
    "./vendor/vision_bundle.mjs",
  ];

  function describeError(err) {
    if (!err) return "未知错误";
    if (typeof err === "string") return err;
    if (err.name && err.message) return err.name + ": " + err.message;
    if (err.message) return String(err.message);
    if (err.type || err.target) {
      const target = err.target && (err.target.src || err.target.href);
      return "资源加载失败 Event" + (target ? " → " + target : "") +
        (err.type ? " (" + err.type + ")" : "");
    }
    try {
      return JSON.stringify(err);
    } catch (e) {
      return String(err);
    }
  }

  const HAND_CONNECTIONS = [
    [0, 1], [1, 2], [2, 3], [3, 4],
    [0, 5], [5, 6], [6, 7], [7, 8],
    [5, 9], [9, 10], [10, 11], [11, 12],
    [9, 13], [13, 14], [14, 15], [15, 16],
    [13, 17], [17, 18], [18, 19], [19, 20],
    [0, 17],
  ];

  const FINGER_DEFS = {
    thumb: { label: "拇指", ids: [1, 2, 3, 4], joints: ["cmc", "mcp", "ip"] },
    index: { label: "食指", ids: [5, 6, 7, 8], joints: ["mcp", "pip", "dip"] },
    middle: { label: "中指", ids: [9, 10, 11, 12], joints: ["mcp", "pip", "dip"] },
    ring: { label: "无名指", ids: [13, 14, 15, 16], joints: ["mcp", "pip", "dip"] },
    pinky: { label: "小指", ids: [17, 18, 19, 20], joints: ["mcp", "pip", "dip"] },
  };

  const FINGER_BY_INDEX = {
    0: "thumb",
    1: "index",
    2: "middle",
    3: "ring",
    4: "pinky",
  };

  const WRIST = 0; // landmark 0，近端关节的掌骨方向参考点

  let stream = null;
  let handLandmarker = null;
  let landmarkerReady = false;
  let rafId = 0;
  let activeDeviceId = null;
  let lastVideoTime = -1;
  let detectTimestamp = 0;
  let lastLandmarks = null;
  let fpsFrames = 0;
  let fpsLastTime = performance.now();
  let fpsRafId = 0;
  const trail = new Map();

  function setStatus(state, text) {
    if (!statusEl) return;
    statusEl.dataset.state = state;
    statusText.textContent = text;
  }

  function showError(message) {
    errorText.textContent = message;
    errorBox.hidden = false;
    setStatus("error", "出错了");
  }

  function clearError() {
    errorBox.hidden = true;
    errorText.textContent = "";
  }

  function applyMirror() {
    const on = mirrorCheck.checked;
    video.classList.toggle("mirrored", on);
    overlay.classList.toggle("mirrored", on);
  }

  function fmtAngle(deg) {
    return Number.isFinite(deg) ? deg.toFixed(1) : "—";
  }

  function angleBetween(a, b, c) {
    const abx = a.x - b.x;
    const aby = a.y - b.y;
    const cbx = c.x - b.x;
    const cby = c.y - b.y;
    const dot = abx * cbx + aby * cby;
    const mag = Math.hypot(abx, aby) * Math.hypot(cbx, cby);
    if (mag < 1e-8) return 0;
    const cos = Math.min(1, Math.max(-1, dot / mag));
    return (Math.acos(cos) * 180) / Math.PI;
  }

  // MediaPipe 给出的是关节「内角」：手指伸直时约 180°，弯曲时变小。
  // 全项目（3D 复现的旋转、综合弯曲角、MC 桥接的驱动量）需要的都是「屈曲角」，
  // 即 0° = 完全伸直、数值越大弯曲越多，所以在这里统一换算一次。
  function toFlexion(interior) {
    return Math.max(0, 180 - interior);
  }

  function computeFingerAngles(lm) {
    const out = {};
    for (const name of Object.keys(FINGER_DEFS)) {
      const def = FINGER_DEFS[name];
      const [i0, i1, i2, i3] = def.ids;
      // 近端关节（拇指 CMC / 其余四指 MCP）需要一个比掌指关节更靠近手腕的
      // 参考点，取手腕 landmark 0 作为掌骨方向。
      const angles = [
        toFlexion(angleBetween(lm[WRIST], lm[i0], lm[i1])),
        toFlexion(angleBetween(lm[i0], lm[i1], lm[i2])),
        toFlexion(angleBetween(lm[i1], lm[i2], lm[i3])),
      ];
      out[name] = {
        angles: angles,
        flex: Math.min(100, (angles[0] + angles[1] + angles[2]) / 2.7),
      };
    }
    return out;
  }

  function updateAngleUI(fingerAngles) {
    for (const name of Object.keys(FINGER_DEFS)) {
      const def = FINGER_DEFS[name];
      const data = fingerAngles && fingerAngles[name];
      def.joints.forEach((joint, idx) => {
        const el = $(name + "-" + joint);
        const deg = data ? data.angles[idx] : null;
        if (el) el.textContent = deg === null ? "—" : fmtAngle(deg);
        // 驱动刻度条：满量程按 120° 屈曲
        const row = el && el.closest(".angle-row");
        if (row) {
          row.style.setProperty(
            "--pct",
            deg === null ? "0" : Math.min(100, (deg / 120) * 100).toFixed(1)
          );
        }
      });
    }

    const focus = fingerSelect.value;
    const focusName = focus === "-1" ? null : FINGER_BY_INDEX[focus];
    angleCards.forEach((card) => {
      card.classList.toggle(
        "focused",
        Boolean(focusName) && card.dataset.finger === focusName
      );
    });

    if (!fingerAngles) {
      focusAngleEl.textContent = "—";
      setGauge(0);
      return;
    }

    // flex 本身就是 0–100 的归一化弯曲量，可直接当作环形表的百分比
    if (focusName) {
      const flex = fingerAngles[focusName].flex;
      focusAngleEl.textContent = fmtAngle(flex);
      setGauge(flex);
    } else {
      const sum =
        Object.values(fingerAngles).reduce((acc, d) => acc + d.flex, 0) / 5;
      focusAngleEl.textContent = fmtAngle(sum);
      setGauge(sum);
    }
  }

  function setGauge(pct) {
    if (!focusGaugeEl) return;
    focusGaugeEl.style.setProperty(
      "--pct",
      Math.max(0, Math.min(100, pct || 0)).toFixed(1)
    );
  }

  function resizeOverlay() {
    const rect = viewport.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    overlay.width = Math.round(rect.width * dpr);
    overlay.height = Math.round(rect.height * dpr);
    overlay.style.width = rect.width + "px";
    overlay.style.height = rect.height + "px";
  }

  function drawOverlay(landmarksList) {
    const ctx = overlay.getContext("2d");
    const w = overlay.width;
    const h = overlay.height;
    ctx.clearRect(0, 0, w, h);

    if (!landmarksList || landmarksList.length === 0) {
      handBadge.hidden = true;
      updateAngleUI(null);
      return;
    }

    handBadge.hidden = false;
    const dpr = window.devicePixelRatio || 1;
    const focus = fingerSelect.value;
    const focusName = focus === "-1" ? null : FINGER_BY_INDEX[focus];

    for (const landmarks of landmarksList) {
      ctx.lineWidth = 3 * dpr;
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      ctx.strokeStyle = "rgba(62, 207, 142, 0.9)";

      for (let k = 0; k < HAND_CONNECTIONS.length; k++) {
        const i = HAND_CONNECTIONS[k][0];
        const j = HAND_CONNECTIONS[k][1];
        const a = landmarks[i];
        const b = landmarks[j];
        if (!a || !b) continue;
        ctx.beginPath();
        ctx.moveTo(a.x * w, a.y * h);
        ctx.lineTo(b.x * w, b.y * h);
        ctx.stroke();
      }

      for (let idx = 0; idx < landmarks.length; idx++) {
        const p = landmarks[idx];
        const def = focusName ? FINGER_DEFS[focusName] : null;
        const isFocusTip = def && def.ids[def.ids.length - 1] === idx;
        const r = isFocusTip ? 7 * dpr : 4.5 * dpr;
        ctx.beginPath();
        ctx.fillStyle = isFocusTip ? "#f0b429" : "#5ad1ff";
        ctx.arc(p.x * w, p.y * h, r, 0, Math.PI * 2);
        ctx.fill();
        ctx.lineWidth = 1.5 * dpr;
        ctx.strokeStyle = "rgba(10, 14, 18, 0.65)";
        ctx.stroke();
      }

      const fingerAngles = computeFingerAngles(landmarks);

      if (showAnglesCheck.checked) {
        ctx.font = 11 * dpr + "px Consolas, monospace";
        ctx.textBaseline = "middle";
        for (const name of Object.keys(FINGER_DEFS)) {
          if (focusName && name !== focusName) continue;
          const def = FINGER_DEFS[name];
          const mid = landmarks[def.ids[1]];
          const label = def.label + " " + fingerAngles[name].flex.toFixed(0) + "°";
          const x = mid.x * w + 10 * dpr;
          const y = mid.y * h - 12 * dpr;
          const tw = ctx.measureText(label).width;
          ctx.fillStyle = "rgba(15, 20, 25, 0.72)";
          ctx.fillRect(x - 4 * dpr, y - 9 * dpr, tw + 8 * dpr, 18 * dpr);
          ctx.fillStyle = focusName === name ? "#f0b429" : "#e8eef5";
          ctx.fillText(label, x, y);
        }
      }

      if (showTrailCheck.checked) {
        const tipIdxs = focusName
          ? [FINGER_DEFS[focusName].ids[3]]
          : [4, 8, 12, 16, 20];
        for (const tip of tipIdxs) {
          const p = landmarks[tip];
          if (!trail.has(tip)) trail.set(tip, []);
          const arr = trail.get(tip);
          arr.push({ x: p.x, y: p.y });
          if (arr.length > 40) arr.shift();
          ctx.beginPath();
          ctx.strokeStyle = "rgba(240, 180, 41, 0.75)";
          ctx.lineWidth = 2 * dpr;
          for (let i = 0; i < arr.length; i++) {
            if (i === 0) ctx.moveTo(arr[i].x * w, arr[i].y * h);
            else ctx.lineTo(arr[i].x * w, arr[i].y * h);
          }
          ctx.stroke();
        }
      } else if (trail.size) {
        trail.clear();
      }

      updateAngleUI(fingerAngles);
      lastLandmarks = landmarks;
    }
  }

  function startFpsMeter() {
    stopFpsMeter();
    fpsFrames = 0;
    fpsLastTime = performance.now();
    function tick(now) {
      fpsFrames += 1;
      const elapsed = now - fpsLastTime;
      if (elapsed >= 1000) {
        fpsEl.textContent = Math.round((fpsFrames * 1000) / elapsed) + " fps";
        fpsFrames = 0;
        fpsLastTime = now;
      }
      fpsRafId = requestAnimationFrame(tick);
    }
    fpsRafId = requestAnimationFrame(tick);
  }

  function stopFpsMeter() {
    if (fpsRafId) cancelAnimationFrame(fpsRafId);
    fpsRafId = 0;
    fpsEl.textContent = "—";
  }

  async function listCameras(selectedId) {
    if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return;
    const devices = await navigator.mediaDevices.enumerateDevices();
    const cameras = devices.filter(function (d) {
      return d.kind === "videoinput";
    });
    deviceSelect.innerHTML = "";
    if (!cameras.length) {
      deviceSelect.innerHTML = '<option value="">未找到摄像头</option>';
      deviceSelect.disabled = true;
      return;
    }
    cameras.forEach(function (cam, index) {
      const option = document.createElement("option");
      option.value = cam.deviceId;
      option.textContent = cam.label || "摄像头 " + (index + 1);
      if (selectedId && cam.deviceId === selectedId) option.selected = true;
      deviceSelect.appendChild(option);
    });
    deviceSelect.disabled = false;
  }

  function updateMeta() {
    const track = stream && stream.getVideoTracks()[0];
    if (!track) {
      resolutionEl.textContent = "—";
      deviceNameEl.textContent = "—";
      return;
    }
    const s = track.getSettings ? track.getSettings() : {};
    const w = s.width || video.videoWidth;
    const h = s.height || video.videoHeight;
    resolutionEl.textContent = w && h ? w + " × " + h : "—";
    deviceNameEl.textContent = track.label || "未知设备";
  }

  async function ensureLandmarker() {
    if (handLandmarker) return handLandmarker;
    setStatus("loading", "加载手部模型…");

    let HandLandmarker;
    let FilesetResolver;
    let lastImportErr = null;

    for (const url of VISION_CANDIDATES) {
      try {
        console.log("[mc] import", url);
        const vision = await import(url);
        HandLandmarker = vision.HandLandmarker;
        FilesetResolver = vision.FilesetResolver;
        if (HandLandmarker && FilesetResolver) break;
        lastImportErr = new Error("module exports incomplete");
      } catch (err) {
        lastImportErr = err;
        console.warn("[mc] import failed", url, err);
      }
    }

    if (!HandLandmarker || !FilesetResolver) {
      throw new Error(
        "MediaPipe 模块加载失败：" + describeError(lastImportErr)
      );
    }

    const fileset = await FilesetResolver.forVisionTasks(WASM_BASE);
    const delegates = ["GPU", "CPU"];
    for (const delegate of delegates) {
      try {
        console.log("[mc] create landmarker", delegate);
        handLandmarker = await HandLandmarker.createFromOptions(fileset, {
          baseOptions: { modelAssetPath: MODEL_URL, delegate: delegate },
          runningMode: "VIDEO",
          numHands: 1,
          minHandDetectionConfidence: 0.5,
          minHandPresenceConfidence: 0.5,
          minTrackingConfidence: 0.5,
        });
        landmarkerReady = true;
        detectTimestamp = performance.now();
        console.log("[mc] landmarker ready", delegate);
        return handLandmarker;
      } catch (err) {
        console.warn("[mc] create failed", delegate, err);
        if (delegate === "CPU") {
          throw new Error("HandLandmarker 创建失败：" + describeError(err));
        }
      }
    }
  }

  function detectLoop() {
    rafId = requestAnimationFrame(detectLoop);
    if (!stream || !landmarkerReady || !handLandmarker) return;
    const t = video.currentTime;
    if (video.readyState < 2 || t === lastVideoTime) return;
    lastVideoTime = t;
    detectTimestamp = Math.max(detectTimestamp + 1, performance.now());
    const t0 = performance.now();
    let result;
    try {
      result = handLandmarker.detectForVideo(video, detectTimestamp);
    } catch (err) {
      console.warn("[mc] detect error", err);
      return;
    }
    inferMsEl.textContent = (performance.now() - t0).toFixed(0) + " ms";
    const lms = result && result.landmarks ? result.landmarks : [];
    drawOverlay(lms);

    // 驱动 3D 复现（replay3d.js 提供）
    if (lms.length) {
      const first = lms[0];
      const ang = computeFingerAngles(first);
      const focus = fingerSelect.value;
      const focusName = focus === "-1" ? null : FINGER_BY_INDEX[focus];
      if (typeof window.__replayUpdate === "function") {
        window.__replayUpdate(first, ang, focusName);
      }
      pushBridge(ang);
    } else {
      if (typeof window.__replayUpdate === "function") {
        window.__replayUpdate(null, null, null);
      }
      pushBridge(null);
    }
  }

  // ---------- 桥接：把关节角推给 CC:Tweaked 中继服务 ----------
  const BRIDGE_URL = "http://127.0.0.1:8765/update";
  let bridgeLast = 0;
  let bridgeOk = 0;
  let bridgeErr = 0;

  // 单一事实来源：只看复选框本身。原先还有一个 window.__bridgeOn 影子开关，
  // 两个来源可能不一致，已移除。
  function bridgeEnabled() {
    const cb = document.getElementById("bridgeEnable");
    return Boolean(cb && cb.checked);
  }

  function setBridgeStatus(text, kind) {
    const el = document.getElementById("bridgeStatus");
    if (!el) return;
    el.textContent = text;
    el.dataset.kind = kind || "";
  }

  function pushBridge(ang) {
    if (!bridgeEnabled()) return;
    const now = performance.now();
    if (now - bridgeLast < 33) return;   // 约 30Hz
    bridgeLast = now;

    const payload = { hand: !!ang, source: "webcam-mediapipe", fingers: {} };
    if (ang) {
      for (const name of Object.keys(FINGER_DEFS)) {
        const d = ang[name];
        payload.fingers[name] = {
          flex: d ? d.flex : 0,
          mcp: d ? d.angles[0] : 0,
          pip: d ? d.angles[1] : 0,
          dip: d ? d.angles[2] : 0,
        };
      }
    }

    fetch(BRIDGE_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then((r) => {
        if (!r.ok) throw new Error("HTTP " + r.status);
        bridgeOk++;
        setBridgeStatus("已连接 · " + bridgeOk + " 帧", "ok");
      })
      .catch(() => {
        bridgeErr++;
        if (bridgeErr % 30 === 1) {
          setBridgeStatus("未连接（先启动 bridge_server.py）", "err");
        }
      });
  }

  function stopCamera() {
    if (rafId) cancelAnimationFrame(rafId);
    rafId = 0;
    if (stream) {
      stream.getTracks().forEach(function (t) {
        t.stop();
      });
      stream = null;
    }
    video.srcObject = null;
    lastVideoTime = -1;
    lastLandmarks = null;
    trail.clear();
    placeholder.classList.remove("hidden");
    handBadge.hidden = true;
    overlay.getContext("2d").clearRect(0, 0, overlay.width, overlay.height);

    btnStart.disabled = false;
    btnStart.textContent = "开启摄像头";
    btnStop.disabled = true;
    btnSnapshot.disabled = true;
    btnFullscreen.disabled = true;

    stopFpsMeter();
    resolutionEl.textContent = "—";
    deviceNameEl.textContent = "—";
    inferMsEl.textContent = "—";
    updateAngleUI(null);
    if (typeof window.__replayUpdate === "function") {
      window.__replayUpdate(null, null, null);
    }
    setStatus("idle", "未开启");
    console.log("[mc] camera stopped");
  }

  async function startCamera(deviceId) {
    clearError();
    console.log("[mc] startCamera, deviceId=", deviceId);

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      showError(
        "当前环境不支持摄像头 API。请用 Chrome/Edge，并通过 https 或 localhost 打开页面。"
      );
      return;
    }

    // 权限状态提示（有的浏览器静默拒绝）
    try {
      if (navigator.permissions && navigator.permissions.query) {
        const perm = await navigator.permissions.query({ name: "camera" });
        console.log("[mc] camera permission state =", perm.state);
        if (perm.state === "denied") {
          showError(
            "浏览器已拒绝摄像头权限，不会再次弹窗。请点地址栏左侧图标 → 摄像头改为「允许」，然后刷新。"
          );
          return;
        }
      }
    } catch (e) {
      console.log("[mc] permissions query skipped", e);
    }

    if (stream) stopCamera();

    btnStart.disabled = true;
    btnStart.textContent = "启动中…";
    setStatus("loading", "请求摄像头权限…");

    // 先用最简约束，失败再按设备指定
    const attempts = [
      { audio: false, video: true },
      {
        audio: false,
        video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: "user" },
      },
    ];
    if (deviceId) {
      attempts.push({
        audio: false,
        video: {
          deviceId: { exact: deviceId },
          width: { ideal: 1280 },
          height: { ideal: 720 },
        },
      });
    }

    let opened = false;
    let lastErr = null;

    for (let i = 0; i < attempts.length; i++) {
      try {
        console.log("[mc] getUserMedia attempt", i, attempts[i]);
        stream = await navigator.mediaDevices.getUserMedia(attempts[i]);
        opened = true;
        console.log("[mc] getUserMedia ok", stream.getVideoTracks().map(function (t) { return t.label; }));
        break;
      } catch (err) {
        lastErr = err;
        console.warn("[mc] getUserMedia attempt failed", i, err);
      }
    }

    if (!opened) {
      stopCamera();
      const err = lastErr || {};
      let msg = "无法打开摄像头。";
      if (err.name === "NotAllowedError") {
        msg =
          "没有获得摄像头权限。若浏览器未弹窗：1) 地址栏左侧允许摄像头；2) 系统设置→隐私→相机；3) 刷新后再点开启。已拒绝过的站点需手动改回允许。";
      } else if (err.name === "NotFoundError") {
        msg = "未检测到摄像头设备。";
      } else if (err.name === "NotReadableError") {
        msg = "摄像头被其他程序占用（微信/会议软件等），请关闭后重试。";
      } else if (err.name === "OverconstrainedError") {
        msg = "设备约束不满足，请换一个摄像头设备。";
      } else if (err.name === "SecurityError") {
        msg = "安全策略拦截。请用 https 或 localhost 打开，不要用 file://。";
      } else if (err.message) {
        msg = "无法打开摄像头：" + (err.name || "") + " " + err.message;
      }
      showError(msg);
      return;
    }

    try {
      video.srcObject = stream;
      await video.play();
    } catch (playErr) {
      console.warn("[mc] video.play failed", playErr);
    }

    placeholder.classList.add("hidden");
    try {
      activeDeviceId = stream.getVideoTracks()[0].getSettings().deviceId || deviceId || null;
    } catch (e) {
      activeDeviceId = deviceId || null;
    }
    applyMirror();
    resizeOverlay();
    updateMeta();
    try {
      await listCameras(activeDeviceId);
    } catch (e) {
      console.warn("[mc] listCameras", e);
    }

    btnStart.disabled = false;
    btnStart.textContent = "重新开启";
    btnStop.disabled = false;
    btnSnapshot.disabled = false;
    btnFullscreen.disabled = false;

    setStatus("live", "采集中（准备识别…）");
    startFpsMeter();
    if (!rafId) detectLoop();

    try {
      await ensureLandmarker();
      setStatus("live", "采集中 · 识别中");
    } catch (modelErr) {
      console.error("[mc] model failed", modelErr);
      setStatus("live", "采集中 · 无识别");
      showError("摄像头已开启，识别模型加载失败：" + describeError(modelErr));
    }
  }

  function snapshot() {
    if (!stream || !video.videoWidth) return;
    const w = video.videoWidth;
    const h = video.videoHeight;
    const out = document.createElement("canvas");
    out.width = w;
    out.height = h;
    const ctx = out.getContext("2d");
    if (mirrorCheck.checked) {
      ctx.translate(w, 0);
      ctx.scale(-1, 1);
    }
    ctx.drawImage(video, 0, 0, w, h);

    if (lastLandmarks) {
      ctx.save();
      if (mirrorCheck.checked) {
        ctx.setTransform(-1, 0, 0, 1, w, 0);
      } else {
        ctx.setTransform(1, 0, 0, 1, 0, 0);
      }
      ctx.lineWidth = 3;
      ctx.strokeStyle = "rgba(62, 207, 142, 0.95)";
      for (let k = 0; k < HAND_CONNECTIONS.length; k++) {
        const i = HAND_CONNECTIONS[k][0];
        const j = HAND_CONNECTIONS[k][1];
        const a = lastLandmarks[i];
        const b = lastLandmarks[j];
        if (!a || !b) continue;
        ctx.beginPath();
        ctx.moveTo(a.x * w, a.y * h);
        ctx.lineTo(b.x * w, b.y * h);
        ctx.stroke();
      }
      for (const p of lastLandmarks) {
        ctx.beginPath();
        ctx.fillStyle = "#5ad1ff";
        ctx.arc(p.x * w, p.y * h, 5, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.restore();
    }

    out.toBlob(function (blob) {
      if (!blob) return;
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
      a.href = url;
      a.download = "finger-capture-" + ts + ".png";
      a.click();
      URL.revokeObjectURL(url);
    }, "image/png");
  }

  async function toggleFullscreen() {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await viewport.requestFullscreen();
    } catch (err) {
      showError("全屏失败：" + (err.message || err));
    }
  }

  // ---- 先绑定，保证任何情况下按钮可点 ----
  btnStart.addEventListener("click", function () {
    console.log("[mc] start clicked");
    startCamera(deviceSelect.value || activeDeviceId);
  });
  btnStop.addEventListener("click", stopCamera);
  btnSnapshot.addEventListener("click", snapshot);
  btnFullscreen.addEventListener("click", toggleFullscreen);

  deviceSelect.addEventListener("change", function () {
    if (deviceSelect.value) startCamera(deviceSelect.value);
  });
  mirrorCheck.addEventListener("change", applyMirror);

  // MC 桥接开关（原先写在 capture.html 的内联脚本里，现已并入主脚本）
  const bridgeCheck = document.getElementById("bridgeEnable");
  if (bridgeCheck) {
    bridgeCheck.addEventListener("change", function () {
      bridgeOk = 0;
      bridgeErr = 0;
      setBridgeStatus(bridgeCheck.checked ? "等待数据…" : "未启用", "");
    });
  }

  fingerSelect.addEventListener("change", function () {
    const focus = fingerSelect.value;
    const focusName = focus === "-1" ? null : FINGER_BY_INDEX[focus];
    angleCards.forEach(function (card) {
      card.classList.toggle(
        "focused",
        Boolean(focusName) && card.dataset.finger === focusName
      );
    });
    if (lastLandmarks) updateAngleUI(computeFingerAngles(lastLandmarks));
  });

  video.addEventListener("loadedmetadata", function () {
    updateMeta();
    resizeOverlay();
  });
  window.addEventListener("resize", resizeOverlay);
  window.addEventListener("beforeunload", stopCamera);

  if (navigator.mediaDevices && navigator.mediaDevices.addEventListener) {
    navigator.mediaDevices.addEventListener("devicechange", function () {
      listCameras(activeDeviceId).catch(function () {});
    });
  }

  applyMirror();
  resizeOverlay();
  updateAngleUI(null);
  listCameras().catch(function () {});
  console.log(
    "[mc] ready. getUserMedia=",
    !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia),
    "origin=",
    location.origin
  );

  window.__mcStart = startCamera;
  // 供自检/联调使用：可传入 21 个 landmark 直接验算关节角，或直接渲染一组角度
  window.__mcAngles = computeFingerAngles;
  window.__mcRender = updateAngleUI;
})();
