// 体感切水果：指尖刀光 + Canvas 2D
(function () {
  "use strict";

  function $(id) {
    return document.getElementById(id);
  }

  const canvas = $("fruitCanvas");
  const video = $("video");
  const handOverlay = $("handOverlay");
  const statusEl = $("status");
  const statusText = $("statusText");
  const errorBox = $("errorBox");
  const errorText = $("errorText");
  const btnStartCam = $("btnStartCam");
  const btnPlay = $("btnPlay");
  const btnRestart = $("btnRestart");
  const btnPause = $("btnPause");
  const mirrorCheck = $("mirror");
  const difficulty = $("difficulty");
  const hudScore = $("hudScore");
  const hudCombo = $("hudCombo");
  const hudLives = $("hudLives");
  const gameOverlay = $("gameOverlay");
  const trackState = $("trackState");
  const speedState = $("speedState");
  const speedBar = $("speedBar");

  const MODEL_URL = new URL("./vendor/hand_landmarker.task", window.location.href).href;
  const WASM_BASE = new URL("./vendor/wasm/", window.location.href).href;
  const VISION_URL = new URL("./vendor/vision_bundle.mjs", window.location.href).href;

  const ctx = canvas.getContext("2d");
  const octx = handOverlay.getContext("2d");

  let W = 800;
  let H = 520;
  let dpr = Math.min(window.devicePixelRatio || 1, 2);

  function resize() {
    const rect = canvas.getBoundingClientRect();
    W = rect.width;
    H = rect.height;
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(W * dpr);
    canvas.height = Math.round(H * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const orect = handOverlay.getBoundingClientRect();
    handOverlay.width = Math.round(orect.width * dpr);
    handOverlay.height = Math.round(orect.height * dpr);
    octx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  const DIFF = {
    easy: { gravity: 0.155, spawnMs: 1500, bombChance: 0.08, speed: 0.85 },
    normal: { gravity: 0.185, spawnMs: 1150, bombChance: 0.12, speed: 1.0 },
    hard: { gravity: 0.23, spawnMs: 850, bombChance: 0.18, speed: 1.12 },
  };

  let diff = DIFF.normal;
  let state = "idle";
  let score = 0;
  let combo = 0;
  let comboTimer = 0;
  let lives = 3;
  let fruits = [];
  let particles = [];
  let splashes = [];
  let texts = [];
  let trail = [];
  let lastSpawn = 0;
  let spawnWave = 0;
  let handMode = false;
  let mouseDown = false;

  let tip = null;
  let tipSpeed = 0;
  const TIP_SMOOTH = 0.42;

  const FRUIT_TYPES = [
    { kind: "watermelon", r: 42, color: "#2ecc71", inner: "#c0392b", score: 4 },
    { kind: "orange", r: 30, color: "#e67e22", inner: "#f5b041", score: 3 },
    { kind: "apple", r: 28, color: "#e74c3c", inner: "#f1948a", score: 3 },
    { kind: "lemon", r: 26, color: "#f1c40f", inner: "#fcf3cf", score: 2 },
    { kind: "kiwi", r: 27, color: "#8e5a2b", inner: "#7dcea0", score: 2 },
    { kind: "grape", r: 22, color: "#8e44ad", inner: "#d2b4de", score: 1 },
  ];

  function setStatus(stateName, text) {
    statusEl.dataset.state = stateName;
    statusText.textContent = text;
  }

  function showError(msg) {
    errorText.textContent = msg;
    errorBox.hidden = false;
  }

  function updateHud() {
    hudScore.textContent = String(score);
    hudCombo.textContent = combo > 1 ? "x" + combo : String(combo);
    hudLives.textContent = "♥".repeat(Math.max(0, lives));
  }

  function setOverlay(show, title, html, btn) {
    gameOverlay.style.display = show ? "flex" : "none";
    gameOverlay.classList.toggle("hidden", !show);
    if (title) gameOverlay.querySelector("h2").textContent = title;
    if (html) gameOverlay.querySelector("p").innerHTML = html;
    if (btn) $("btnPlay").textContent = btn;
  }

  function spawnFruit() {
    const isBomb = Math.random() < diff.bombChance;
    const type = FRUIT_TYPES[(Math.random() * FRUIT_TYPES.length) | 0];
    const r = type.r * (0.92 + Math.random() * 0.16);

    const lane = spawnWave % 3;
    spawnWave += 1;

    let x, speedX, peakFactor;
    if (lane === 0) {
      x = W * (0.1 + Math.random() * 0.08);
      speedX = 1.45 + Math.random() * 0.55;
      peakFactor = 0.48;
    } else if (lane === 2) {
      x = W * (0.82 + Math.random() * 0.08);
      speedX = -(1.45 + Math.random() * 0.55);
      peakFactor = 0.48;
    } else {
      x = W * (0.38 + Math.random() * 0.24);
      speedX = (Math.random() - 0.5) * 1.0;
      peakFactor = 0.56;
    }

    const peakY = H * peakFactor;
    const dropFromBottom = H + r + 12;
    const rise = dropFromBottom - peakY;
    const g = diff.gravity;
    const speedY = -Math.sqrt(2 * g * Math.max(80, rise));

    fruits.push({
      x,
      y: dropFromBottom,
      vx: speedX * diff.speed,
      vy: speedY * diff.speed,
      r: isBomb ? 30 : r,
      rot: Math.random() * Math.PI,
      vr: (Math.random() - 0.5) * 0.06,
      bomb: isBomb,
      type,
      sliced: false,
      half: 0,
      life: 1,
    });
  }

  function burst(x, y, color, n) {
    for (let i = 0; i < n; i++) {
      const a = Math.random() * Math.PI * 2;
      const sp = 2 + Math.random() * 6;
      particles.push({
        x,
        y,
        vx: Math.cos(a) * sp,
        vy: Math.sin(a) * sp - 1.5,
        life: 1,
        color,
        size: 3 + Math.random() * 5,
      });
    }
    splashes.push({ x, y, r: 8, life: 1, color });
  }

  function sliceFruit(f, dirX, dirY) {
    if (f.sliced || f.half) return;

    if (f.bomb) {
      f.sliced = true;
      f.life = 0;
      lives -= 1;
      combo = 0;
      burst(f.x, f.y, "#e74c3c", 28);
      texts.push({ x: f.x, y: f.y - 20, text: "BOOM -1", color: "#e74c3c", life: 1 });
      updateHud();
      if (lives <= 0) gameOver();
      return;
    }

    const len = Math.hypot(dirX, dirY) || 1;
    const nx = dirX / len;
    const ny = dirY / len;

    f.sliced = true;
    f.life = 0;

    for (const side of [-1, 1]) {
      fruits.push({
        x: f.x + nx * side * 4,
        y: f.y + ny * side * 4,
        vx: f.vx + nx * side * 2.4 + (Math.random() - 0.5) * 0.5,
        vy: f.vy + ny * side * 1.2 - 0.8,
        r: f.r * 0.74,
        rot: f.rot,
        vr: side * 0.09,
        bomb: false,
        type: f.type,
        half: side,
        sliced: true,
        life: 1,
      });
    }

    combo = comboTimer > 0 ? combo + 1 : 1;
    comboTimer = 55;
    const gain = (f.type.score || 2) * combo;
    score += gain;
    burst(f.x, f.y, f.type.inner, 16);
    texts.push({
      x: f.x,
      y: f.y - 16,
      text: combo > 1 ? "+" + gain + " x" + combo : "+" + gain,
      color: combo > 2 ? "#f0b429" : "#3ecf8e",
      life: 1,
    });
    updateHud();
  }

  function gameOver() {
    state = "over";
    setOverlay(true, "游戏结束", "得分 <b>" + score + "</b>。再来一刀？", "再来一局");
    btnPause.textContent = "暂停";
  }

  function startGame() {
    score = 0;
    combo = 0;
    comboTimer = 0;
    lives = 3;
    fruits = [];
    particles = [];
    splashes = [];
    texts = [];
    trail = [];
    tip = null;
    tipSpeed = 0;
    spawnWave = 0;
    state = "playing";
    updateHud();
    setOverlay(false);
    btnPause.textContent = "暂停";
  }

  function pushTip(rawX, rawY) {
    const now = performance.now();

    if (!tip) {
      tip = { x: rawX, y: rawY, t: now };
      trail.push({ x: rawX, y: rawY, t: now });
      return;
    }

    const dt = Math.max(6, now - tip.t);
    const dx = rawX - tip.x;
    const dy = rawY - tip.y;
    const dist = Math.hypot(dx, dy);
    tipSpeed = tipSpeed * 0.8 + ((dist / dt) * 1000) * 0.2;

    const sx = tip.x + dx * TIP_SMOOTH;
    const sy = tip.y + dy * TIP_SMOOTH;

    const step = 7;
    const n = Math.min(16, Math.max(1, Math.floor(Math.hypot(sx - tip.x, sy - tip.y) / step)));
    const fromX = tip.x;
    const fromY = tip.y;

    for (let i = 1; i <= n; i++) {
      const t = i / n;
      const x = fromX + (sx - fromX) * t;
      const y = fromY + (sy - fromY) * t;
      trail.push({ x, y, t: tip.t + dt * t });
      cutAlong(trail[trail.length - 2], trail[trail.length - 1]);
    }

    tip.x = sx;
    tip.y = sy;
    tip.t = now;

    if (trail.length > 48) trail.splice(0, trail.length - 48);
    if (state === "playing") {
      cutAlong({ x: fromX, y: fromY }, { x: sx, y: sy });
    }
  }

  function cutAlong(a, b) {
    if (state !== "playing" || !a || !b) return;
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const dist = Math.hypot(dx, dy);
    if (dist < 0.5) return;

    const speedK = Math.min(1, tipSpeed / 850);
    const hitR = 12 + speedK * 16;

    for (const f of fruits) {
      if (f.half || f.sliced || f.life <= 0) continue;
      const t = Math.max(0, Math.min(1, ((f.x - a.x) * dx + (f.y - a.y) * dy) / (dist * dist)));
      const px = a.x + t * dx;
      const py = a.y + t * dy;
      if (Math.hypot(f.x - px, f.y - py) < f.r + hitR) {
        sliceFruit(f, dx, dy);
      }
    }
  }

  function drawTrail() {
    if (trail.length < 2) return;
    const pts = trail;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";

    const strokePath = (width, style) => {
      ctx.beginPath();
      ctx.moveTo(pts[0].x, pts[0].y);
      if (pts.length === 2) {
        ctx.lineTo(pts[1].x, pts[1].y);
      } else {
        for (let i = 0; i < pts.length - 1; i++) {
          const p1 = pts[i];
          const p2 = pts[i + 1];
          const mx = (p1.x + p2.x) / 2;
          const my = (p1.y + p2.y) / 2;
          if (i === 0) ctx.moveTo(p1.x, p1.y);
          ctx.quadraticCurveTo(p1.x, p1.y, mx, my);
          if (i === pts.length - 2) ctx.lineTo(p2.x, p2.y);
        }
      }
      ctx.strokeStyle = style;
      ctx.lineWidth = width;
      ctx.stroke();
    };

    strokePath(20, "rgba(70, 170, 255, 0.18)");
    strokePath(10, "rgba(140, 210, 255, 0.35)");
    strokePath(3.5, "rgba(210, 240, 255, 0.92)");

    const tipP = pts[pts.length - 1];
    const glow = ctx.createRadialGradient(tipP.x, tipP.y, 0, tipP.x, tipP.y, 28);
    glow.addColorStop(0, "rgba(190, 240, 255,0.65)");
    glow.addColorStop(1, "rgba(190, 240, 255,0)");
    ctx.fillStyle = glow;
    ctx.beginPath();
    ctx.arc(tipP.x, tipP.y, 28, 0, Math.PI * 2);
    ctx.fill();
  }

  const HAND_CONNECTIONS = [
    [0, 1], [1, 2], [2, 3], [3, 4],
    [0, 5], [5, 6], [6, 7], [7, 8],
    [5, 9], [9, 10], [10, 11], [11, 12],
    [9, 13], [13, 14], [14, 15], [15, 16],
    [13, 17], [17, 18], [18, 19], [19, 20],
    [0, 17],
  ];

  let stream = null;
  let handLandmarker = null;
  let landmarkerReady = false;
  let rafCam = 0;
  let lastVideoTime = -1;
  let detectTimestamp = 0;
  // 锁定追踪：避免两只手来回抢
  let lockedHandId = -1;
  let lockStableFrames = 0;

  function applyMirror() {
    video.classList.toggle("mirrored", mirrorCheck.checked);
    handOverlay.classList.toggle("mirrored", mirrorCheck.checked);
  }

  function releaseCamera() {
    if (rafCam) {
      cancelAnimationFrame(rafCam);
      rafCam = 0;
    }
    if (stream) {
      try {
        stream.getTracks().forEach((t) => t.stop());
      } catch (_) {}
      stream = null;
    }
    try {
      video.srcObject = null;
    } catch (_) {}
    handMode = false;
    lockedHandId = -1;
    lockStableFrames = 0;
  }

  /**
   * 距镜头近的得分更高。
   * MediaPipe：z 越小（越负）越靠近摄像头；手掌尺度越大也越近。
   */
  function proximityScore(lm) {
    // 取掌心附近关节点的平均 z（更稳）
    const zIdx = [0, 5, 9, 13, 17];
    let zSum = 0;
    for (const i of zIdx) {
      zSum += lm[i].z || 0;
    }
    const zAvg = zSum / zIdx.length;

    // 手掌尺度：腕 → 中指根
    const scale = Math.hypot(lm[9].x - lm[0].x, lm[9].y - lm[0].y);

    // z 越小越好 → 用 -z；scale 越大越好
    // 归一化权重：深度主导，尺度辅助
    return -zAvg * 10 + scale * 2.2;
  }

  function handKey(lm) {
    // 用腕点量化做粗 id，帮助锁定
    return (Math.round(lm[0].x * 50) << 8) ^ Math.round(lm[0].y * 50);
  }

  /**
   * 只返回「距镜头最近」的一只手：
   * 1) 若已有锁定且连续稳定，优先同一 key / 最接近锁定的
   * 2) 否则选 proximityScore 最高
   */
  function pickNearestHand(list) {
    if (!list || !list.length) {
      lockedHandId = -1;
      lockStableFrames = 0;
      return null;
    }

    if (list.length === 1) {
      lockedHandId = handKey(list[0]);
      lockStableFrames = Math.min(10, lockStableFrames + 1);
      return list[0];
    }

    // 评估所有手的近距得分
    let best = null;
    let bestScore = -Infinity;
    let bestKey = -1;
    for (const lm of list) {
      const s = proximityScore(lm);
      const key = handKey(lm);
      // 已锁定手有轻微加成，防抖动切换
      const bonus = lockedHandId >= 0 && key === lockedHandId ? 0.25 : 0;
      const total = s + bonus;
      if (total > bestScore) {
        bestScore = total;
        best = lm;
        bestKey = key;
      }
    }

    if (best) {
      if (bestKey === lockedHandId) {
        lockStableFrames = Math.min(20, lockStableFrames + 1);
      } else {
        // 只有明显更近（得分差）才切换，否则维持原手
        if (lockStableFrames < 3 || bestScore > proximityScore(best) - 0.25) {
          lockedHandId = bestKey;
          lockStableFrames = 1;
        }
      }
    }

    return best;
  }

  function drawHand(lm) {
    const orect = handOverlay.getBoundingClientRect();
    const w = orect.width;
    const h = orect.height;
    octx.clearRect(0, 0, w, h);
    if (!lm) return;

    // 高亮：标记为「最近手」
    octx.lineWidth = 2.2;
    octx.strokeStyle = "rgba(240,180,41,0.9)";
    for (const [i, j] of HAND_CONNECTIONS) {
      const a = lm[i];
      const b = lm[j];
      if (!a || !b) continue;
      octx.beginPath();
      octx.moveTo(a.x * w, a.y * h);
      octx.lineTo(b.x * w, b.y * h);
      octx.stroke();
    }
    octx.fillStyle = "#f0b429";
    octx.beginPath();
    octx.arc(lm[8].x * w, lm[8].y * h, 6, 0, Math.PI * 2);
    octx.fill();
    octx.fillStyle = "rgba(255,220,120,0.9)";
    for (const p of lm) {
      octx.beginPath();
      octx.arc(p.x * w, p.y * h, 2.8, 0, Math.PI * 2);
      octx.fill();
    }

    // 标签
    octx.fillStyle = "rgba(0,0,0,0.55)";
    octx.fillRect(6, 6, 78, 18);
    octx.fillStyle = "#ffe6a8";
    octx.font = "12px sans-serif";
    octx.fillText("最近手", 12, 19);
  }

  function onHand(lm) {
    if (!lm) {
      drawHand(null);
      return;
    }
    drawHand(lm);
    let x = lm[8].x;
    if (mirrorCheck.checked) x = 1 - x;
    pushTip(x * W, lm[8].y * H);
    handMode = true;
    const z = (lm[0].z || 0).toFixed(3);
    trackState.textContent = "最近镜头手 · z=" + z;
  }

  function ensureLandmarker() {
    if (handLandmarker) return Promise.resolve(handLandmarker);
    setStatus("loading", "加载模型…");
    return import(VISION_URL)
      .then((v) => {
        const { HandLandmarker, FilesetResolver } = v;
        return FilesetResolver.forVisionTasks(WASM_BASE).then((fs) =>
          HandLandmarker.createFromOptions(fs, {
            baseOptions: { modelAssetPath: MODEL_URL, delegate: "GPU" },
            runningMode: "VIDEO",
            numHands: 2,
            minHandDetectionConfidence: 0.5,
            minTrackingConfidence: 0.5,
          })
        );
      })
      .then((lm) => {
        handLandmarker = lm;
        landmarkerReady = true;
        detectTimestamp = performance.now();
        setStatus("live", "追踪最近手");
        return lm;
      })
      .catch(() =>
        import(VISION_URL)
          .then((v) => {
            const { HandLandmarker, FilesetResolver } = v;
            return FilesetResolver.forVisionTasks(WASM_BASE).then((fs) =>
              HandLandmarker.createFromOptions(fs, {
                baseOptions: { modelAssetPath: MODEL_URL, delegate: "CPU" },
                runningMode: "VIDEO",
                numHands: 2,
              })
            );
          })
          .then((lm) => {
            handLandmarker = lm;
            landmarkerReady = true;
            detectTimestamp = performance.now();
            setStatus("live", "追踪最近手（CPU）");
            return lm;
          })
      );
  }

  function camLoop() {
    rafCam = requestAnimationFrame(camLoop);
    if (!stream || !landmarkerReady || !handLandmarker) return;
    const t = video.currentTime;
    if (video.readyState < 2 || t === lastVideoTime) return;
    lastVideoTime = t;
    detectTimestamp = Math.max(detectTimestamp + 1, performance.now());
    try {
      const result = handLandmarker.detectForVideo(video, detectTimestamp);
      const lms = result && result.landmarks ? result.landmarks : [];
      const best = pickNearestHand(lms);
      if (best) onHand(best);
      else {
        drawHand(null);
        trackState.textContent = "未检测到手";
      }
    } catch (e) {
      console.warn("[fruit] detect", e);
    }
  }

  function describeCamError(err) {
    const name = (err && err.name) || "";
    const msg = (err && err.message) || String(err);
    if (name === "NotReadableError" || /in use/i.test(msg) || /Device/i.test(msg)) {
      return (
        "摄像头被占用（Device in use）。请：<br/>" +
        "1. 关闭其它正在用相机的页面（采集页/搭积木/装机）<br/>" +
        "2. 退出微信、腾讯会议、钉钉、OBS 等<br/>" +
        "3. 本页点「释放摄像头」后再重新开启<br/>" +
        "4. 仍不行就刷新本页或重启浏览器"
      );
    }
    if (name === "NotAllowedError") {
      return "摄像头权限被拒绝，请在地址栏允许摄像头。";
    }
    if (name === "NotFoundError") {
      return "未找到摄像头设备，请确认已连接。";
    }
    return "摄像头失败：" + msg;
  }

  async function startCamera() {
    errorBox.hidden = true;

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      showError("不支持摄像头，可改用鼠标切割。");
      return;
    }

    releaseCamera();
    await new Promise((r) => setTimeout(r, 200));

    btnStartCam.disabled = true;
    btnStartCam.textContent = "启动中…";
    setStatus("loading", "请求摄像头…");

    try {
      if (navigator.mediaDevices.enumerateDevices) {
        await navigator.mediaDevices.enumerateDevices();
      }
    } catch (_) {}

    const attempts = [
      { video: true },
      { video: { width: { ideal: 1280 }, height: { ideal: 720 } } },
    ];

    let lastErr = null;
    let got = null;

    for (const constraints of attempts) {
      try {
        got = await navigator.mediaDevices.getUserMedia(constraints);
        lastErr = null;
        break;
      } catch (err) {
        lastErr = err;
        console.warn("[fruit] getUserMedia attempt", err);
      }
    }

    if (!got) {
      btnStartCam.disabled = false;
      btnStartCam.textContent = "开启摄像头";
      setStatus("error", "出错了");
      showError(describeCamError(lastErr));
      return;
    }

    stream = got;
    video.srcObject = stream;
    try {
      await video.play();
    } catch (e) {
      console.warn("[fruit] play", e);
    }

    applyMirror();
    resize();
    btnStartCam.disabled = false;
    btnStartCam.textContent = "重新开启";

    try {
      await ensureLandmarker();
      if (!rafCam) camLoop();
    } catch (err) {
      setStatus("error", "出错了");
      showError("模型加载失败：" + (err.message || err));
    }
  }

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      releaseCamera();
      setStatus("idle", "已释放摄像头");
      trackState.textContent = "已释放摄像头";
    }
  });
  window.addEventListener("pagehide", releaseCamera);
  window.addEventListener("beforeunload", releaseCamera);

  function pointerPos(e) {
    const rect = canvas.getBoundingClientRect();
    return {
      x: ((e.clientX - rect.left) / rect.width) * W,
      y: ((e.clientY - rect.top) / rect.height) * H,
    };
  }

  canvas.addEventListener("pointerdown", (e) => {
    mouseDown = true;
    if (state === "idle" || state === "over") startGame();
    const p = pointerPos(e);
    pushTip(p.x, p.y);
  });
  canvas.addEventListener("pointermove", (e) => {
    if (!mouseDown && handMode) return;
    const p = pointerPos(e);
    pushTip(p.x, p.y);
  });
  window.addEventListener("pointerup", () => {
    mouseDown = false;
  });

  let last = performance.now();
  function loop(now) {
    requestAnimationFrame(loop);
    const dt = Math.min(40, now - last);
    last = now;
    const k = dt / 16.67;

    if (state === "playing") {
      if (now - lastSpawn > diff.spawnMs) {
        lastSpawn = now;
        spawnFruit();
        if (Math.random() < 0.3) {
          setTimeout(() => {
            if (state === "playing") spawnFruit();
          }, 180 + Math.random() * 160);
        }
      }

      for (const f of fruits) {
        f.x += f.vx * k;
        f.y += f.vy * k;
        f.vy += diff.gravity * k;
        f.rot += f.vr * k;
        if (f.y > H + f.r + 40 && f.vy > 0) {
          f.life = 0;
          if (!f.sliced && !f.bomb && !f.half) {
            lives -= 1;
            combo = 0;
            updateHud();
            texts.push({
              x: Math.min(W - 40, f.x),
              y: H - 40,
              text: "漏掉了 -1",
              color: "#e74c3c",
              life: 1,
            });
            if (lives <= 0) gameOver();
          }
        }
      }
      fruits = fruits.filter((f) => f.life > 0);

      if (comboTimer > 0) {
        comboTimer -= k;
        if (comboTimer <= 0) combo = 0;
      }
    }

    for (const p of particles) {
      p.x += p.vx * k;
      p.y += p.vy * k;
      p.vy += 0.16 * k;
      p.life -= 0.022 * k;
    }
    particles = particles.filter((p) => p.life > 0);
    for (const s of splashes) {
      s.r += 2 * k;
      s.life -= 0.038 * k;
    }
    splashes = splashes.filter((s) => s.life > 0);
    for (const t of texts) {
      t.y -= 1.1 * k;
      t.life -= 0.016 * k;
    }
    texts = texts.filter((t) => t.life > 0);

    const cutoff = now - 170;
    while (trail.length && trail[0].t < cutoff) trail.shift();

    speedState.textContent = Math.round(tipSpeed) + " px/s";
    speedBar.style.width = Math.min(100, (tipSpeed / 1100) * 100) + "%";

    draw();
  }

  function draw() {
    ctx.clearRect(0, 0, W, H);

    ctx.fillStyle = "rgba(255,255,255,0.04)";
    for (let i = 0; i < 18; i++) {
      const x = ((i * 97) % W) + ((i * 13) % 20);
      const y = (i * 53) % (H * 0.6);
      ctx.beginPath();
      ctx.arc(x, y, 1.5 + (i % 3), 0, Math.PI * 2);
      ctx.fill();
    }

    for (const f of fruits) {
      if (f.life <= 0) continue;
      ctx.save();
      ctx.translate(f.x, f.y);
      ctx.rotate(f.rot);

      if (f.bomb) {
        const g = ctx.createRadialGradient(-8, -8, 4, 0, 0, f.r);
        g.addColorStop(0, "#444");
        g.addColorStop(1, "#111");
        ctx.fillStyle = g;
        ctx.beginPath();
        ctx.arc(0, 0, f.r, 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = "#c0392b";
        ctx.lineWidth = 3;
        ctx.beginPath();
        ctx.moveTo(0, -f.r + 2);
        ctx.quadraticCurveTo(10, -f.r - 12, 4, -f.r - 18);
        ctx.stroke();
        ctx.fillStyle = "#f0b429";
        ctx.beginPath();
        ctx.arc(4, -f.r - 18, 3.5 + Math.sin(performance.now() * 0.02) * 1.5, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = "#fff";
        ctx.font = "bold 14px sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText("!", 0, 2);
      } else {
        const r = f.r;
        const g = ctx.createRadialGradient(-r * 0.35, -r * 0.35, r * 0.1, 0, 0, r);
        g.addColorStop(0, lighten(f.type.color, 25));
        g.addColorStop(1, f.type.color);
        ctx.fillStyle = g;
        ctx.beginPath();
        if (f.half) {
          ctx.arc(
            0,
            0,
            r,
            f.half > 0 ? -Math.PI / 2 : Math.PI / 2,
            f.half > 0 ? Math.PI / 2 : Math.PI * 1.5
          );
          ctx.lineTo(0, 0);
          ctx.closePath();
        } else {
          ctx.arc(0, 0, r, 0, Math.PI * 2);
        }
        ctx.fill();

        ctx.fillStyle = f.type.inner;
        if (f.half) {
          ctx.beginPath();
          ctx.ellipse(0, 0, r * 0.72, r * 0.28, 0, 0, Math.PI * 2);
          ctx.fill();
        } else {
          ctx.globalAlpha = 0.35;
          ctx.beginPath();
          ctx.arc(0, 0, r * 0.62, 0, Math.PI * 2);
          ctx.fill();
          ctx.globalAlpha = 1;
        }

        ctx.fillStyle = "rgba(255,255,255,0.22)";
        ctx.beginPath();
        ctx.ellipse(-r * 0.35, -r * 0.4, r * 0.28, r * 0.16, -0.5, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.restore();
    }

    for (const s of splashes) {
      ctx.strokeStyle = s.color;
      ctx.globalAlpha = s.life * 0.55;
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
      ctx.stroke();
      ctx.globalAlpha = 1;
    }

    for (const p of particles) {
      ctx.globalAlpha = Math.max(0, p.life);
      ctx.fillStyle = p.color;
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.size * p.life, 0, Math.PI * 2);
      ctx.fill();
      ctx.globalAlpha = 1;
    }

    for (const t of texts) {
      ctx.globalAlpha = Math.max(0, t.life);
      ctx.fillStyle = t.color;
      ctx.font = "bold 22px sans-serif";
      ctx.textAlign = "center";
      ctx.fillText(t.text, t.x, t.y);
      ctx.globalAlpha = 1;
    }

    drawTrail();
  }

  function lighten(hex, amt) {
    const c = hex.replace("#", "");
    const n = parseInt(c, 16);
    let r = (n >> 16) + amt;
    let g = ((n >> 8) & 255) + amt;
    let b = (n & 255) + amt;
    r = Math.max(0, Math.min(255, r));
    g = Math.max(0, Math.min(255, g));
    b = Math.max(0, Math.min(255, b));
    return "#" + ((r << 16) | (g << 8) | b).toString(16).padStart(6, "0");
  }

  btnStartCam.addEventListener("click", () => {
    startCamera();
  });
  btnPlay.addEventListener("click", startGame);
  btnRestart.addEventListener("click", startGame);
  btnPause.addEventListener("click", () => {
    if (state === "playing") {
      state = "paused";
      btnPause.textContent = "继续";
      setOverlay(true, "已暂停", "点击继续或按空格。", "继续");
    } else if (state === "paused") {
      state = "playing";
      btnPause.textContent = "暂停";
      setOverlay(false);
    }
  });

  mirrorCheck.addEventListener("change", applyMirror);
  difficulty.addEventListener("change", () => {
    if (DIFF[difficulty.value]) diff = DIFF[difficulty.value];
  });

  window.addEventListener("resize", resize);
  window.addEventListener("keydown", (e) => {
    if (e.code === "Space") {
      e.preventDefault();
      if (state === "playing") {
        state = "paused";
        setOverlay(true, "已暂停", "再按空格继续。", "继续");
      } else {
        startGame();
      }
    }
    if (e.key === "r" || e.key === "R") startGame();
  });

  const btnRelease = document.getElementById("btnRelease");
  if (btnRelease) {
    btnRelease.addEventListener("click", () => {
      releaseCamera();
      setStatus("idle", "已释放摄像头");
      trackState.textContent = "已释放";
      showError("摄像头已释放。请关闭其它占用相机的页面后，再点「开启摄像头」。");
    });
  }

  applyMirror();
  resize();
  updateHud();
  setStatus("idle", "摄像头未开启");
  requestAnimationFrame(loop);
  console.log("[fruit] ready v5-nearest-cam");
})();
