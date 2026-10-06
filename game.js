// 体感搭积木：摄像头 + MediaPipe 手势 → 控制 game3d.js 场景
(function () {
  "use strict";

  function $(id) {
    return document.getElementById(id);
  }

  const video = $("video");
  const handOverlay = $("handOverlay");
  const camPip = $("camPip");
  const statusEl = $("status");
  const statusText = $("statusText");
  const errorBox = $("errorBox");
  const errorText = $("errorText");
  const btnStartCam = $("btnStartCam");
  const btnPlay = $("btnPlay");
  const btnPause = $("btnPause");
  const btnRestart = $("btnRestart");
  const mirrorCheck = $("mirror");
  const difficulty = $("difficulty");
  const pinchDistEl = $("pinchDist");
  const gestureStateEl = $("gestureState");
  const pinchBar = $("pinchBar");
  const gameOverlay = $("gameOverlay");
  const overlayTitle = $("overlayTitle");
  const overlayText = $("overlayText");
  const hudHeight = $("hudHeight");
  const hudScore = $("hudScore");
  const hudPerfect = $("hudPerfect");

  console.log("[game] boot");

  // import() 必须用相对/绝对 URL，不能是裸路径 "vendor/..."
  const MODEL_URL = new URL("./vendor/hand_landmarker.task", window.location.href).href;
  const WASM_BASE = new URL("./vendor/wasm/", window.location.href).href;
  const VISION_URL = new URL("./vendor/vision_bundle.mjs", window.location.href).href;

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
  let rafId = 0;
  let lastVideoTime = -1;
  let detectTimestamp = 0;
  let pinchCooldown = 0;

  function setStatus(state, text) {
    statusEl.dataset.state = state;
    statusText.textContent = text;
  }

  function showError(msg) {
    errorText.textContent = msg;
    errorBox.hidden = false;
  }

  function clearError() {
    errorBox.hidden = true;
    errorText.textContent = "";
  }

  function describeError(err) {
    if (!err) return "未知错误";
    if (typeof err === "string") return err;
    if (err.name && err.message) return err.name + ": " + err.message;
    if (err.message) return String(err.message);
    if (err.type || err.target) {
      const target = err.target && (err.target.src || err.target.href);
      return "资源加载失败" + (target ? " → " + target : "");
    }
    return String(err);
  }

  function applyMirror() {
    const on = mirrorCheck.checked;
    video.classList.toggle("mirrored", on);
    handOverlay.classList.toggle("mirrored", on);
    if (window.__game3d) window.__game3d.setMirror(on);
  }

  function resizeHandOverlay() {
    const rect = camPip.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    handOverlay.width = Math.round(rect.width * dpr);
    handOverlay.height = Math.round(rect.height * dpr);
    handOverlay.style.width = rect.width + "px";
    handOverlay.style.height = rect.height + "px";
  }

  function drawHand(landmarks) {
    const ctx = handOverlay.getContext("2d");
    const w = handOverlay.width;
    const h = handOverlay.height;
    ctx.clearRect(0, 0, w, h);
    if (!landmarks || !landmarks.length) return;
    const dpr = window.devicePixelRatio || 1;

    ctx.lineWidth = 2 * dpr;
    ctx.strokeStyle = "rgba(62, 207, 142, 0.9)";
    for (const [i, j] of HAND_CONNECTIONS) {
      const a = landmarks[i];
      const b = landmarks[j];
      if (!a || !b) continue;
      ctx.beginPath();
      ctx.moveTo(a.x * w, a.y * h);
      ctx.lineTo(b.x * w, b.y * h);
      ctx.stroke();
    }
    for (const p of landmarks) {
      ctx.beginPath();
      ctx.fillStyle = "#5ad1ff";
      ctx.arc(p.x * w, p.y * h, 3 * dpr, 0, Math.PI * 2);
      ctx.fill();
    }
    // pinch tips
    const tip = landmarks[8];
    const thumb = landmarks[4];
    ctx.beginPath();
    ctx.fillStyle = "#f0b429";
    ctx.arc(tip.x * w, tip.y * h, 4 * dpr, 0, Math.PI * 2);
    ctx.fill();
    ctx.beginPath();
    ctx.arc(thumb.x * w, thumb.y * h, 4 * dpr, 0, Math.PI * 2);
    ctx.fill();
  }

  function ensureLandmarker() {
    if (handLandmarker) return Promise.resolve(handLandmarker);
    setStatus("loading", "加载手势模型…");

    return import(VISION_URL)
      .then((vision) => {
        const { HandLandmarker, FilesetResolver } = vision;
        return FilesetResolver.forVisionTasks(WASM_BASE).then((fileset) => {
          return HandLandmarker.createFromOptions(fileset, {
            baseOptions: {
              modelAssetPath: MODEL_URL,
              delegate: "GPU",
            },
            runningMode: "VIDEO",
            numHands: 1,
            minHandDetectionConfidence: 0.5,
            minHandPresenceConfidence: 0.5,
            minTrackingConfidence: 0.5,
          });
        });
      })
      .then((lm) => {
        handLandmarker = lm;
        landmarkerReady = true;
        detectTimestamp = performance.now();
        setStatus("live", "手势识别中");
        return lm;
      })
      .catch((err) => {
        // CPU fallback
        console.warn("[game] GPU model fail, retry CPU", err);
        return import(VISION_URL)
          .then((vision) => {
            const { HandLandmarker, FilesetResolver } = vision;
            return FilesetResolver.forVisionTasks(WASM_BASE).then((fileset) =>
              HandLandmarker.createFromOptions(fileset, {
                baseOptions: { modelAssetPath: MODEL_URL, delegate: "CPU" },
                runningMode: "VIDEO",
                numHands: 1,
              })
            );
          })
          .then((lm) => {
            handLandmarker = lm;
            landmarkerReady = true;
            detectTimestamp = performance.now();
            setStatus("live", "手势识别中（CPU）");
            return lm;
          });
      });
  }

  function distance2D(a, b) {
    return Math.hypot(a.x - b.x, a.y - b.y);
  }

  function onHands(landmarksList) {
    const g = window.__game3d;
    if (!landmarksList || !landmarksList.length) {
      drawHand(null);
      gestureStateEl.textContent = "等待手部…";
      pinchDistEl.textContent = "—";
      pinchBar.style.width = "0%";
      if (g) g.setHand(null);
      return;
    }

    const lm = landmarksList[0];
    drawHand(lm);

    const thumb = lm[4];
    const index = lm[8];
    const middle = lm[12];
    const palm = lm[9];
    const wrist = lm[0];

    const pinch = distance2D(thumb, index);
    // 归一化到 0-1 的捏合程度（越小越捏紧）
    const pinchNorm = Math.min(1, Math.max(0, pinch / 0.18));
    const isPinching = pinch < 0.055;

    // 拳头：指尖都靠近掌心
    const tips = [8, 12, 16, 20];
    const fistDist =
      tips.reduce((acc, i) => acc + distance2D(lm[i], wrist), 0) / tips.length;
    const isFist = fistDist < 0.22;

    pinchDistEl.textContent = pinch.toFixed(3);
    pinchBar.style.width = Math.round((1 - pinchNorm) * 100) + "%";

    if (isPinching) {
      gestureStateEl.textContent = "捏合 → 放下";
    } else if (isFist) {
      gestureStateEl.textContent = "握拳 → 急刹定住";
    } else {
      gestureStateEl.textContent = "手掌移动中";
    }

    // 手部中心 X：镜像后左边是画面左侧
    let handX = (palm.x + index.x) / 2;
    if (mirrorCheck.checked) handX = 1 - handX;
    const handY = (palm.y + middle.y) / 2;

    if (g) {
      g.setHand({
        x: handX,
        y: handY,
        pinch: pinch,
        pinching: isPinching && performance.now() > pinchCooldown,
        fist: isFist,
        confidence: 1,
      });
      if (isPinching && performance.now() > pinchCooldown) {
        pinchCooldown = performance.now() + 450;
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
    try {
      const result = handLandmarker.detectForVideo(video, detectTimestamp);
      onHands(result && result.landmarks ? result.landmarks : []);
    } catch (err) {
      console.warn("[game] detect", err);
    }
  }

  function stopCamera() {
    if (rafId) cancelAnimationFrame(rafId);
    rafId = 0;
    if (stream) {
      stream.getTracks().forEach((t) => t.stop());
      stream = null;
    }
    video.srcObject = null;
    btnStartCam.disabled = false;
    btnStartCam.textContent = "开启摄像头";
    setStatus("idle", "摄像头未开启");
    if (window.__game3d) window.__game3d.setHand(null);
  }

  function startCamera() {
    clearError();
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      showError("当前环境不支持摄像头，请用 Chrome/Edge + https/localhost。");
      return;
    }
    if (stream) stopCamera();
    btnStartCam.disabled = true;
    btnStartCam.textContent = "启动中…";
    setStatus("loading", "请求摄像头…");

    navigator.mediaDevices
      .getUserMedia({ video: true })
      .then((s) => {
        stream = s;
        video.srcObject = s;
        return video.play();
      })
      .then(() => {
        applyMirror();
        resizeHandOverlay();
        btnStartCam.disabled = false;
        btnStartCam.textContent = "重新开启";
        setStatus("loading", "准备手势模型…");
        return ensureLandmarker();
      })
      .then(() => {
        if (!rafId) detectLoop();
      })
      .catch((err) => {
        console.error("[game] camera/model", err);
        stopCamera();
        showError("摄像头或模型失败：" + describeError(err));
        setStatus("error", "出错了");
      });
  }

  function setHud(height, score, perfect) {
    if (hudHeight) hudHeight.textContent = String(height);
    if (hudScore) hudScore.textContent = String(score);
    if (hudPerfect) hudPerfect.textContent = String(perfect);
  }

  function showOverlay(title, text, btnLabel, show) {
    overlayTitle.textContent = title;
    overlayText.innerHTML = text;
    if (btnPlay) btnPlay.textContent = btnLabel || "开始游戏";
    gameOverlay.classList.toggle("hidden", !show);
    gameOverlay.style.display = show ? "flex" : "none";
  }

  function startGame() {
    if (!stream) {
      // 无摄像头也可用键盘玩
      if (window.__game3d) {
        window.__game3d.start();
        showOverlay("", "", "", false);
      }
      return;
    }
    if (window.__game3d) {
      window.__game3d.start();
      showOverlay("", "", "", false);
      btnPause.disabled = false;
    }
  }

  // controls
  btnStartCam.addEventListener("click", startCamera);
  btnPlay.addEventListener("click", startGame);
  btnPause.addEventListener("click", () => {
    if (!window.__game3d) return;
    const paused = window.__game3d.togglePause();
    btnPause.textContent = paused ? "继续" : "暂停";
  });
  btnRestart.addEventListener("click", () => {
    if (window.__game3d) {
      window.__game3d.restart();
      showOverlay("", "", "", false);
      btnPause.disabled = false;
      btnPause.textContent = "暂停";
    }
  });

  mirrorCheck.addEventListener("change", applyMirror);
  difficulty.addEventListener("change", () => {
    if (window.__game3d) window.__game3d.setDifficulty(difficulty.value);
  });

  window.addEventListener("resize", resizeHandOverlay);

  // keyboard fallback
  window.addEventListener("keydown", (e) => {
    if (!window.__game3d) return;
    if (e.key === " ") {
      e.preventDefault();
      if (window.__game3d.getState && window.__game3d.getState() === "playing") {
        window.__game3d.drop();
      } else {
        startGame();
      }
    }
    if (e.key === "p" || e.key === "P") {
      const paused = window.__game3d.togglePause();
      btnPause.textContent = paused ? "继续" : "暂停";
    }
    if (e.key === "r" || e.key === "R") {
      window.__game3d.restart();
      showOverlay("", "", "", false);
    }
    if (e.key === "ArrowLeft") window.__game3d.nudge(-1);
    if (e.key === "ArrowRight") window.__game3d.nudge(1);
  });

  // bridge for game3d
  window.__gameUI = {
    setHud,
    showOverlay,
    onGameOver: (score, height) => {
      showOverlay(
        "游戏结束",
        "最终层数 <b>" + score + "</b>，高度 <b>" + height + "</b>。<br/>再来一次，尽量完美对齐！",
        "再来一局",
        true
      );
      btnPause.disabled = true;
      btnPause.textContent = "暂停";
    },
  };

  applyMirror();
  resizeHandOverlay();
  setStatus("idle", "摄像头未开启");
  console.log("[game] ready");
})();
