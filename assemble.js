// 双手虚拟装机：MediaPipe 双手 → 抓取/释放零件
(function () {
  "use strict";

  function $(id) {
    return document.getElementById(id);
  }

  const video = $("video");
  const handOverlay = $("handOverlay");
  const statusEl = $("status");
  const statusText = $("statusText");
  const errorBox = $("errorBox");
  const errorText = $("errorText");
  const btnStartCam = $("btnStartCam");
  const btnPlay = $("btnPlay");
  const btnReset = $("btnReset");
  const btnNext = $("btnNext");
  const mirrorCheck = $("mirror");
  const hudProgress = $("hudProgress");
  const hudScore = $("hudScore");
  const hudHint = $("hudHint");
  const gameOverlay = $("gameOverlay");
  const stL = $("stL");
  const stR = $("stR");
  const stGrab = $("stGrab");
  const tagL = $("tagL");
  const tagR = $("tagR");
  const partsList = $("partsList");

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
  let grabCooldown = 0;

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
    if (err.name && err.message) return err.name + ": " + err.message;
    return err.message || String(err);
  }

  function applyMirror() {
    const on = mirrorCheck.checked;
    video.classList.toggle("mirrored", on);
    handOverlay.classList.toggle("mirrored", on);
    if (window.__assemble3d) window.__assemble3d.setMirror(on);
  }

  function resizeOverlay() {
    const rect = video.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    handOverlay.width = Math.round(rect.width * dpr);
    handOverlay.height = Math.round(rect.height * dpr);
    handOverlay.style.width = rect.width + "px";
    handOverlay.style.height = rect.height + "px";
  }

  function dist(a, b) {
    return Math.hypot(a.x - b.x, a.y - b.y);
  }

  function drawHands(list) {
    const ctx = handOverlay.getContext("2d");
    const w = handOverlay.width;
    const h = handOverlay.height;
    ctx.clearRect(0, 0, w, h);
    if (!list || !list.length) return;
    const dpr = window.devicePixelRatio || 1;
    const colors = ["#5ad1ff", "#c792ea"];

    list.forEach((lm, hi) => {
      const col = colors[hi % 2];
      ctx.lineWidth = 2 * dpr;
      ctx.strokeStyle = col;
      for (const [i, j] of HAND_CONNECTIONS) {
        const a = lm[i];
        const b = lm[j];
        if (!a || !b) continue;
        ctx.beginPath();
        ctx.moveTo(a.x * w, a.y * h);
        ctx.lineTo(b.x * w, b.y * h);
        ctx.stroke();
      }
      for (const p of lm) {
        ctx.beginPath();
        ctx.fillStyle = col;
        ctx.arc(p.x * w, p.y * h, 2.5 * dpr, 0, Math.PI * 2);
        ctx.fill();
      }
      // pinch markers
      ctx.fillStyle = "#f0b429";
      for (const idx of [4, 8]) {
        ctx.beginPath();
        ctx.arc(lm[idx].x * w, lm[idx].y * h, 4 * dpr, 0, Math.PI * 2);
        ctx.fill();
      }
    });
  }

  function classifyHand(lm) {
    const pinch = dist(lm[4], lm[8]);
    const wrist = lm[0];
    const tips = [8, 12, 16, 20];
    const fistDist = tips.reduce((acc, i) => acc + dist(lm[i], wrist), 0) / tips.length;
    return {
      pinch,
      pinching: pinch < 0.06,
      fist: fistDist < 0.22,
      x: (lm[9].x + lm[0].x) / 2,
      y: (lm[9].y + lm[12].y) / 2,
    };
  }

  function onHands(list) {
    const g = window.__assemble3d;
    if (!list || !list.length) {
      drawHands(null);
      stL.textContent = "未检测";
      stR.textContent = "未检测";
      stGrab.textContent = "—";
      if (g) g.setHands(null, null);
      return;
    }

    drawHands(list);

    // 左右：镜像后画面左=玩家左手
    const scored = list.map((lm) => {
      const info = classifyHand(lm);
      let x = info.x;
      if (mirrorCheck.checked) x = 1 - x;
      return {
        ...info,
        x,
        y: info.y,
        raw: lm,
      };
    });
    scored.sort((a, b) => a.x - b.x); // left to right

    const left = scored[0] || null;
    const right = scored[1] || scored[0] || null;

    if (left) {
      stL.textContent = left.pinching ? "捏合抓取" : left.fist ? "握拳吸附" : "张开";
      tagL.textContent = left.pinching ? "左手 🤏" : "左手 ✋";
    } else {
      stL.textContent = "未检测";
      tagL.textContent = "左手 —";
    }
    if (right && scored.length > 1) {
      stR.textContent = right.pinching ? "捏合抓取" : right.fist ? "握拳吸附" : "张开";
      tagR.textContent = right.pinching ? "右手 🤏" : "右手 ✋";
    } else {
      stR.textContent = "未检测";
      tagR.textContent = "右手 —";
    }

    const now = performance.now();
    let grabbing = "—";
    if (left && left.pinching && now > grabCooldown) {
      grabCooldown = now + 380;
      if (g) g.tryGrabOrRelease("L", left);
      grabbing = "左手";
    } else if (left && !left.pinching) {
      if (g) g.onHandOpen("L");
    }
    if (right && scored.length > 1 && right.pinching && now > grabCooldown + 50) {
      grabCooldown = now + 380;
      if (g) g.tryGrabOrRelease("R", right);
      grabbing = grabbing === "左手" ? "双手" : "右手";
    } else if (right && scored.length > 1 && !right.pinching) {
      if (g) g.onHandOpen("R");
    }
    stGrab.textContent = grabbing;

    if (g) {
      g.setHands(
        left ? { x: left.x, y: left.y, fist: left.fist, pinching: left.pinching } : null,
        right && scored.length > 1
          ? { x: right.x, y: right.y, fist: right.fist, pinching: right.pinching }
          : right
            ? null
            : null
      );
      // continuous follow while holding
      g.followHands(
        left ? { x: left.x, y: left.y } : null,
        scored.length > 1 && right ? { x: right.x, y: right.y } : null
      );
    }
  }

  function ensureLandmarker() {
    if (handLandmarker) return Promise.resolve(handLandmarker);
    setStatus("loading", "加载双手模型…");
    return import(VISION_URL)
      .then((vision) => {
        const { HandLandmarker, FilesetResolver } = vision;
        return FilesetResolver.forVisionTasks(WASM_BASE).then((fileset) =>
          HandLandmarker.createFromOptions(fileset, {
            baseOptions: { modelAssetPath: MODEL_URL, delegate: "GPU" },
            runningMode: "VIDEO",
            numHands: 2,
            minHandDetectionConfidence: 0.5,
            minHandPresenceConfidence: 0.5,
            minTrackingConfidence: 0.5,
          })
        );
      })
      .then((lm) => {
        handLandmarker = lm;
        landmarkerReady = true;
        detectTimestamp = performance.now();
        setStatus("live", "双手识别中");
        return lm;
      })
      .catch((err) => {
        console.warn("[asm] GPU fail", err);
        return import(VISION_URL).then((vision) => {
          const { HandLandmarker, FilesetResolver } = vision;
          return FilesetResolver.forVisionTasks(WASM_BASE).then((fileset) =>
            HandLandmarker.createFromOptions(fileset, {
              baseOptions: { modelAssetPath: MODEL_URL, delegate: "CPU" },
              runningMode: "VIDEO",
              numHands: 2,
            })
          );
        }).then((lm) => {
          handLandmarker = lm;
          landmarkerReady = true;
          detectTimestamp = performance.now();
          setStatus("live", "双手识别中（CPU）");
          return lm;
        });
      });
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
      console.warn("[asm] detect", err);
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
    if (window.__assemble3d) window.__assemble3d.setHands(null, null);
  }

  function startCamera() {
    clearError();
    if (!navigator.mediaDevices?.getUserMedia) {
      showError("请用 Chrome/Edge + https/localhost 打开。");
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
        resizeOverlay();
        btnStartCam.disabled = false;
        btnStartCam.textContent = "重新开启";
        return ensureLandmarker();
      })
      .then(() => {
        if (!rafId) detectLoop();
      })
      .catch((err) => {
        console.error("[asm]", err);
        stopCamera();
        showError("摄像头/模型失败：" + describeError(err));
        setStatus("error", "出错了");
      });
  }

  // UI bridge
  window.__asmUI = {
    setHud(done, total, hint) {
      hudProgress.textContent = done + "/" + total;
      hudScore.textContent = String(done);
      if (hint) hudHint.textContent = hint;
    },
    setParts(parts) {
      if (!partsList) return;
      [...partsList.children].forEach((li) => {
        const id = li.getAttribute("data-part");
        const p = parts && parts[id];
        li.classList.remove("active", "done", "wrong");
        if (!p) return;
        if (p.done) li.classList.add("done");
        else if (p.active) li.classList.add("active");
        if (p.wrongFlash) li.classList.add("wrong");
      });
    },
    onFinished() {
      gameOverlay.style.display = "flex";
      gameOverlay.classList.remove("hidden");
      const card = gameOverlay.querySelector(".overlay-card");
      if (card) {
        card.querySelector("h2").textContent = "装配完成！";
        card.querySelector("p").innerHTML =
          "六件核心硬件已就位。可以重置再来，或回到采集页继续研究关节角。";
        const btn = $("btnPlay");
        if (btn) btn.textContent = "再装一次";
      }
    },
    setOverlay(show) {
      gameOverlay.style.display = show ? "flex" : "none";
      gameOverlay.classList.toggle("hidden", !show);
    },
  };

  btnStartCam.addEventListener("click", startCamera);
  btnPlay.addEventListener("click", () => {
    if (window.__assemble3d) {
      window.__assemble3d.start();
      window.__asmUI.setOverlay(false);
    }
  });
  btnReset.addEventListener("click", () => {
    if (window.__assemble3d) {
      window.__assemble3d.reset();
      window.__asmUI.setOverlay(false);
    }
  });
  btnNext.addEventListener("click", () => {
    if (window.__assemble3d) window.__assemble3d.focusNext();
  });

  mirrorCheck.addEventListener("change", applyMirror);
  window.addEventListener("resize", resizeOverlay);

  // mouse fallback for demo without camera
  window.addEventListener("keydown", (e) => {
    if (!window.__assemble3d) return;
    if (e.key === "r" || e.key === "R") window.__assemble3d.reset();
    if (e.key === "n" || e.key === "N") window.__assemble3d.focusNext();
  });

  applyMirror();
  resizeOverlay();
  setStatus("idle", "摄像头未开启");
  console.log("[asm] ready");
})();
