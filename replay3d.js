// 3D 手部/手指复现：关节点驱动骨架 + 参数化手指
import * as THREE from "./vendor/three.module.js";

const HAND_CONNECTIONS = [
  [0, 1], [1, 2], [2, 3], [3, 4],
  [0, 5], [5, 6], [6, 7], [7, 8],
  [5, 9], [9, 10], [10, 11], [11, 12],
  [9, 13], [13, 14], [14, 15], [15, 16],
  [13, 17], [17, 18], [18, 19], [19, 20],
  [0, 17],
];

const FINGER_DEFS = {
  thumb: { ids: [1, 2, 3, 4], color: 0xffb020 },
  index: { ids: [5, 6, 7, 8], color: 0x3d9cf0 },
  middle: { ids: [9, 10, 11, 12], color: 0x3ecf8e },
  ring: { ids: [13, 14, 15, 16], color: 0xc792ea },
  pinky: { ids: [17, 18, 19, 20], color: 0xf07178 },
};

function angleBetween(a, b, c) {
  const abx = a.x - b.x, aby = a.y - b.y, abz = (a.z || 0) - (b.z || 0);
  const cbx = c.x - b.x, cby = c.y - b.y, cbz = (c.z || 0) - (b.z || 0);
  const dot = abx * cbx + aby * cby + abz * cbz;
  const mag = Math.hypot(abx, aby, abz) * Math.hypot(cbx, cby, cbz);
  if (mag < 1e-8) return 0;
  const cos = Math.min(1, Math.max(-1, dot / mag));
  return (Math.acos(cos) * 180) / Math.PI;
}

export class HandReplay {
  constructor(canvas) {
    this.canvas = canvas;
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x0a0e12);

    const w = canvas.clientWidth || 640;
    const h = canvas.clientHeight || 400;
    this.camera = new THREE.PerspectiveCamera(40, w / h, 0.01, 100);
    this.camera.position.set(0, 0.15, 1.6);
    this.camera.lookAt(0, 0, 0);

    this.renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: true,
      alpha: true,
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.setSize(w, h, false);

    // lights
    const amb = new THREE.AmbientLight(0xffffff, 0.55);
    this.scene.add(amb);
    const key = new THREE.DirectionalLight(0xffffff, 0.85);
    key.position.set(2, 3, 4);
    this.scene.add(key);
    const fill = new THREE.DirectionalLight(0x3d9cf0, 0.35);
    fill.position.set(-3, 1, 2);
    this.scene.add(fill);

    // grid floor
    const grid = new THREE.GridHelper(2, 20, 0x2a3542, 0x1c242e);
    grid.position.y = -0.55;
    this.scene.add(grid);

    // world group for hand (tuned later)
    this.handGroup = new THREE.Group();
    this.scene.add(this.handGroup);

    // landmark joints
    this.joints = [];
    const jointGeo = new THREE.SphereGeometry(0.018, 16, 16);
    for (let i = 0; i < 21; i++) {
      const mat = new THREE.MeshStandardMaterial({
        color: 0x5ad1ff,
        metalness: 0.15,
        roughness: 0.45,
      });
      const mesh = new THREE.Mesh(jointGeo, mat);
      mesh.visible = false;
      this.handGroup.add(mesh);
      this.joints.push(mesh);
    }

    // bones
    this.bones = [];
    for (let i = 0; i < HAND_CONNECTIONS.length; i++) {
      const mat = new THREE.MeshStandardMaterial({
        color: 0x3ecf8e,
        metalness: 0.1,
        roughness: 0.5,
      });
      const mesh = new THREE.Mesh(
        new THREE.CylinderGeometry(0.012, 0.012, 1, 8),
        mat
      );
      mesh.visible = false;
      this.handGroup.add(mesh);
      this.bones.push(mesh);
    }

    // parametric single-finger rig (driven by joint angles)
    this.fingerRig = new THREE.Group();
    this.fingerRig.position.set(0.55, -0.15, 0.15);
    this.scene.add(this.fingerRig);
    this.buildFingerRig();

    this._frame = 0;
    // 球坐标相机（目标点 + 半径 + 方位角/俯仰角）
    this._target = new THREE.Vector3(0, 0.1, 0);
    this._spherical = {
      radius: 1.85,
      theta: 0.55, // 水平
      phi: 1.15,   // 垂直（极角）
    };
    // 目标值用于阻尼插值
    this._sphericalTarget = { ...this._spherical };
    this._autoRotate = false;
    this._pointerDown = false;
    this._pointers = new Map();
    this._lastX = 0;
    this._lastY = 0;
    this._pinchDist = 0;
    this.bindPointer();
    this.applyCamera(1);

    this.animate = this.animate.bind(this);
    requestAnimationFrame(this.animate);
  }

  buildFingerRig() {
    // 简单三段式手指：掌节 + 近节 + 中节 + 远节
    const segLen = [0.12, 0.1, 0.08, 0.06];
    const segRad = [0.028, 0.024, 0.021, 0.018];
    this.fingerSegs = [];
    this.fingerPivots = [];

    let parent = this.fingerRig;
    let y = 0;

    for (let i = 0; i < 4; i++) {
      const pivot = new THREE.Group();
      pivot.position.y = y;
      parent.add(pivot);

      const mat = new THREE.MeshStandardMaterial({
        color: i === 0 ? 0x2a3542 : 0x3d9cf0,
        metalness: 0.2,
        roughness: 0.4,
        emissive: i === 0 ? 0x000000 : 0x0a2038,
      });
      const mesh = new THREE.Mesh(
        new THREE.CylinderGeometry(segRad[i], segRad[i] * 0.92, segLen[i], 12),
        mat
      );
      mesh.position.y = segLen[i] / 2;
      pivot.add(mesh);

      // joint sphere
      const j = new THREE.Mesh(
        new THREE.SphereGeometry(segRad[i] * 1.15, 12, 12),
        new THREE.MeshStandardMaterial({ color: 0x5ad1ff, roughness: 0.4 })
      );
      pivot.add(j);

      this.fingerPivots.push(pivot);
      this.fingerSegs.push(mesh);
      parent = pivot;
      y = segLen[i];
    }

    // tip marker
    const tip = new THREE.Mesh(
      new THREE.SphereGeometry(0.022, 12, 12),
      new THREE.MeshStandardMaterial({ color: 0xf0b429, emissive: 0x3a2a00 })
    );
    tip.position.y = 0.02;
    parent.add(tip);
    this.fingerTip = tip;

    // base plate
    const base = new THREE.Mesh(
      new THREE.CylinderGeometry(0.06, 0.07, 0.03, 20),
      new THREE.MeshStandardMaterial({ color: 0x1c242e, roughness: 0.8 })
    );
    base.position.y = -0.02;
    this.fingerRig.add(base);

    // label bar
    const bar = new THREE.Mesh(
      new THREE.BoxGeometry(0.18, 0.01, 0.01),
      new THREE.MeshStandardMaterial({ color: 0xf0b429 })
    );
    bar.position.set(0, -0.08, 0);
    this.fingerRig.add(bar);
  }

  bindPointer() {
    const el = this.canvas;
    // 防止页面跟随拖拽滚动
    el.style.touchAction = "none";
    el.style.userSelect = "none";

    const onDown = (e) => {
      if (e.button !== undefined && e.button !== 0 && e.button !== 1 && e.button !== 2) return;
      el.setPointerCapture?.(e.pointerId);
      this._pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      this._pointerDown = true;
      this._lastX = e.clientX;
      this._lastY = e.clientY;
      this._autoRotate = false;

      if (this._pointers.size === 2) {
        const pts = [...this._pointers.values()];
        this._pinchDist = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
      }
      e.preventDefault();
    };

    const onMove = (e) => {
      if (!this._pointers.has(e.pointerId)) return;
      this._pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });

      // 双指捏合 → 缩放
      if (this._pointers.size === 2) {
        const pts = [...this._pointers.values()];
        const dist = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
        if (this._pinchDist > 0) {
          const scale = this._pinchDist / Math.max(dist, 1);
          this._sphericalTarget.radius = THREE.MathUtils.clamp(
            this._sphericalTarget.radius * scale,
            0.7,
            4.5
          );
        }
        this._pinchDist = dist;
        e.preventDefault();
        return;
      }

      if (!this._pointerDown) return;
      const dx = e.clientX - this._lastX;
      const dy = e.clientY - this._lastY;
      this._lastX = e.clientX;
      this._lastY = e.clientY;

      // 右键 / 中键 / Shift：平移；左键：旋转
      const panMode = e.button === 2 || e.button === 1 || e.shiftKey;
      if (panMode) {
        const scale = this._sphericalTarget.radius * 0.0018;
        this._target.x -= dx * scale;
        this._target.y += dy * scale;
      } else {
        this._sphericalTarget.theta -= dx * 0.0065;
        this._sphericalTarget.phi = THREE.MathUtils.clamp(
          this._sphericalTarget.phi - dy * 0.0065,
          0.15,
          Math.PI - 0.15
        );
      }
      e.preventDefault();
    };

    const onUp = (e) => {
      this._pointers.delete(e.pointerId);
      if (this._pointers.size === 0) {
        this._pointerDown = false;
        this._pinchDist = 0;
      } else if (this._pointers.size === 1) {
        const rest = [...this._pointers.values()][0];
        this._lastX = rest.x;
        this._lastY = rest.y;
        this._pinchDist = 0;
      }
      try {
        el.releasePointerCapture?.(e.pointerId);
      } catch (_) {}
    };

    el.addEventListener("pointerdown", onDown);
    el.addEventListener("pointermove", onMove);
    el.addEventListener("pointerup", onUp);
    el.addEventListener("pointercancel", onUp);
    el.addEventListener("pointerleave", onUp);
    el.addEventListener("contextmenu", (e) => e.preventDefault());

    el.addEventListener(
      "wheel",
      (e) => {
        e.preventDefault();
        const k = e.deltaMode === 1 ? 0.08 : 0.0012;
        this._sphericalTarget.radius = THREE.MathUtils.clamp(
          this._sphericalTarget.radius * (1 + e.deltaY * k),
          0.7,
          4.5
        );
      },
      { passive: false }
    );

    // 双击复位
    el.addEventListener("dblclick", () => {
      this.resetView();
    });

    // 键盘：R 复位
    window.addEventListener("keydown", (e) => {
      if (e.key === "r" || e.key === "R") {
        const tag = (e.target && e.target.tagName) || "";
        if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
        this.resetView();
      }
    });
  }

  resetView() {
    this._target.set(0, 0.1, 0);
    this._sphericalTarget.radius = 1.85;
    this._sphericalTarget.theta = 0.55;
    this._sphericalTarget.phi = 1.15;
    this._autoRotate = false;
  }

  setAutoRotate(on) {
    this._autoRotate = !!on;
  }

  applyCamera(smooth) {
    const s = this._spherical;
    const t = this._sphericalTarget;
    const k = smooth == null ? 0.18 : smooth;
    s.radius += (t.radius - s.radius) * k;
    s.theta += (t.theta - s.theta) * k;
    s.phi += (t.phi - s.phi) * k;

    const sinPhi = Math.sin(s.phi);
    const cosPhi = Math.cos(s.phi);
    const sinTheta = Math.sin(s.theta);
    const cosTheta = Math.cos(s.theta);

    this.camera.position.set(
      this._target.x + s.radius * sinPhi * sinTheta,
      this._target.y + s.radius * cosPhi,
      this._target.z + s.radius * sinPhi * cosTheta
    );
    this.camera.lookAt(this._target);
  }

  setFocus(fingerName) {
    this.focusName = fingerName;
    for (const [name, def] of Object.entries(FINGER_DEFS)) {
      const on = !fingerName || fingerName === name || fingerName === "all";
      for (const id of def.ids) {
        const j = this.joints[id];
        if (j) {
          j.material.color.setHex(name === fingerName || fingerName === "all" ? def.color : 0x5ad1ff);
          j.scale.setScalar(on && fingerName === name ? 1.35 : 1);
        }
      }
    }
  }

  /**
   * @param {Array<{x:number,y:number,z?:number}>|null} landmarks MediaPipe 21 点
   * @param {Object|null} fingerAngles 计算得到的关节角
   * @param {string} focusKey 'thumb'|'index'|...|null
   */
  update(landmarks, fingerAngles, focusKey) {
    if (!landmarks || landmarks.length < 21) {
      for (const j of this.joints) j.visible = false;
      for (const b of this.bones) b.visible = false;
      return;
    }

    // 归一化 → 场景坐标（y 向上，z 向前）
    const pts = landmarks.map((p) => ({
      x: (p.x - 0.5) * 1.4,
      y: -(p.y - 0.5) * 1.4,
      z: (p.z || 0) * 1.4,
    }));

    // 以手腕为中心
    const origin = pts[0];
    for (let i = 0; i < 21; i++) {
      pts[i] = {
        x: pts[i].x - origin.x,
        y: pts[i].y - origin.y,
        z: pts[i].z - origin.z,
      };
    }

    // joints
    for (let i = 0; i < 21; i++) {
      const j = this.joints[i];
      j.position.set(pts[i].x, pts[i].y + 0.15, pts[i].z);
      j.visible = true;
    }

    // bones as oriented cylinders
    for (let k = 0; k < HAND_CONNECTIONS.length; k++) {
      const [a, b] = HAND_CONNECTIONS[k];
      const pa = new THREE.Vector3(pts[a].x, pts[a].y + 0.15, pts[a].z);
      const pb = new THREE.Vector3(pts[b].x, pts[b].y + 0.15, pts[b].z);
      const dir = new THREE.Vector3().subVectors(pb, pa);
      const len = dir.length();
      const mesh = this.bones[k];
      mesh.visible = true;
      mesh.position.copy(pa).add(pb).multiplyScalar(0.5);
      mesh.scale.set(1, Math.max(len, 0.001), 1);
      mesh.quaternion.setFromUnitVectors(
        new THREE.Vector3(0, 1, 0),
        dir.clone().normalize()
      );
    }

    // 选中指：高亮
    if (focusKey && FINGER_DEFS[focusKey]) {
      const ids = FINGER_DEFS[focusKey].ids;
      for (let i = 0; i < 21; i++) {
        const isFocus = ids.includes(i) || i === 0;
        this.joints[i].scale.setScalar(isFocus ? 1.25 : 0.75);
        this.bones[kSafe(i)] = this.bones[kSafe(i)];
      }
    } else {
      for (const j of this.joints) j.scale.setScalar(1);
    }

    // 参数化手指：用关节角驱动
    this.driveFinger(fingerAngles, focusKey);
  }

  driveFinger(fingerAngles, focusKey) {
    if (!fingerAngles) return;
    const name = focusKey && fingerAngles[focusKey] ? focusKey : "index";
    const data = fingerAngles[name];
    if (!data) return;

    const a = data.angles || [0, 0, 0];
    // 弯曲：绕 X 轴负方向（向掌心）
    const deg = Math.PI / 180;
    if (this.fingerPivots[0]) this.fingerPivots[0].rotation.x = -0.15;
    if (this.fingerPivots[1]) this.fingerPivots[1].rotation.x = -a[0] * deg * 0.85;
    if (this.fingerPivots[2]) this.fingerPivots[2].rotation.x = -a[1] * deg * 0.85;
    if (this.fingerPivots[3]) this.fingerPivots[3].rotation.x = -a[2] * deg * 0.85;
  }

  resize() {
    const w = this.canvas.clientWidth || 640;
    const h = this.canvas.clientHeight || 400;
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h, false);
  }

  animate() {
    requestAnimationFrame(this.animate);
    this._frame++;
    if (this._autoRotate) {
      this._sphericalTarget.theta += 0.004;
    }
    this.applyCamera(0.18);
    this.renderer.render(this.scene, this.camera);
  }
}

function kSafe() {
  return 0;
}

// bootstrap
const canvas = document.getElementById("replayCanvas");
if (canvas) {
  const replay = new HandReplay(canvas);
  window.__handReplay = replay;

  const btnRotate = document.getElementById("btnAutoRotate");
  const btnReset = document.getElementById("btnResetView");
  if (btnRotate) {
    btnRotate.addEventListener("click", () => {
      const next = !replay._autoRotate;
      replay.setAutoRotate(next);
      btnRotate.classList.toggle("active", next);
      btnRotate.textContent = next ? "停止旋转" : "自动旋转";
    });
  }
  if (btnReset) {
    btnReset.addEventListener("click", () => replay.resetView());
  }

  window.__replayUpdate = function (landmarks, fingerAngles, focusKey) {
    replay.update(landmarks, fingerAngles, focusKey);
    replay.setFocus(focusKey || "all");
  };

  window.addEventListener("resize", () => replay.resize());
  requestAnimationFrame(() => replay.resize());
}
