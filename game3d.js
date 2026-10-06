// 体感搭积木 3D 场景（Three.js）
import * as THREE from "./vendor/three.module.js";

const DIFF = {
  easy: { w: 2.2, d: 2.2, h: 0.55, speed: 1.1, fall: 7.5 },
  normal: { w: 1.7, d: 1.7, h: 0.5, speed: 1.55, fall: 8.2 },
  hard: { w: 1.25, d: 1.25, h: 0.45, speed: 2.15, fall: 9.2 },
};

class StackGame {
  constructor(canvas) {
    this.canvas = canvas;
    this.diff = DIFF.normal;
    this.mirror = true;
    this.state = "idle"; // idle | playing | paused | over
    this.stack = [];
    this.score = 0;
    this.perfects = 0;
    this.height = 0;
    this.hand = null;
    this.dropLatch = false;
    this._animT = 0;
    // 手部运动监测：静止则不给控制权
    this._handPrevX = null;
    this._handSpeed = 0;
    this._handActiveUntil = 0;
    // 握拳：急刹/定住
    this._brakeUntil = 0;
    this._fistLatch = false;

    this.initThree();
    this.buildWorld();
    this.spawnBlock();

    this.animate = this.animate.bind(this);
    requestAnimationFrame(this.animate);
    window.addEventListener("resize", () => this.resize());
  }

  initThree() {
    const w = this.canvas.clientWidth || 800;
    const h = this.canvas.clientHeight || 560;

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x0c1218);
    this.scene.fog = new THREE.Fog(0x0c1218, 18, 42);

    this.camera = new THREE.PerspectiveCamera(42, w / h, 0.1, 100);
    this.camTarget = new THREE.Vector3(0, 3, 0);
    this.camera.position.set(7.5, 6.5, 10.5);
    this.camera.lookAt(this.camTarget);

    this.renderer = new THREE.WebGLRenderer({
      canvas: this.canvas,
      antialias: true,
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.setSize(w, h, false);
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;

    const amb = new THREE.AmbientLight(0xb8d4ff, 0.55);
    this.scene.add(amb);

    const key = new THREE.DirectionalLight(0xffffff, 1.05);
    key.position.set(8, 16, 10);
    key.castShadow = true;
    key.shadow.mapSize.set(1024, 1024);
    key.shadow.camera.left = -12;
    key.shadow.camera.right = 12;
    key.shadow.camera.top = 12;
    key.shadow.camera.bottom = -12;
    this.scene.add(key);

    const fill = new THREE.DirectionalLight(0x3d9cf0, 0.35);
    fill.position.set(-10, 6, -4);
    this.scene.add(fill);
  }

  buildWorld() {
    // ground
    const ground = new THREE.Mesh(
      new THREE.CircleGeometry(16, 48),
      new THREE.MeshStandardMaterial({ color: 0x141c26, roughness: 0.92 })
    );
    ground.rotation.x = -Math.PI / 2;
    ground.receiveShadow = true;
    this.scene.add(ground);

    const grid = new THREE.GridHelper(24, 24, 0x2a3542, 0x1a222c);
    grid.position.y = 0.01;
    this.scene.add(grid);

    // platform / pedestal
    const plat = new THREE.Mesh(
      new THREE.CylinderGeometry(2.6, 3.0, 0.35, 32),
      new THREE.MeshStandardMaterial({
        color: 0x243040,
        metalness: 0.25,
        roughness: 0.55,
      })
    );
    plat.position.y = 0.175;
    plat.castShadow = true;
    plat.receiveShadow = true;
    this.scene.add(plat);

    // soft ring
    const ring = new THREE.Mesh(
      new THREE.TorusGeometry(2.65, 0.05, 8, 64),
      new THREE.MeshStandardMaterial({
        color: 0x3d9cf0,
        emissive: 0x123048,
        metalness: 0.4,
        roughness: 0.35,
      })
    );
    ring.rotation.x = Math.PI / 2;
    ring.position.y = 0.36;
    this.scene.add(ring);

    // camera follow guide line
    this.stackRootY = 0.35;
  }

  makeBlockMesh(w, h, d, color) {
    const geo = new THREE.BoxGeometry(w, h, d);
    const mat = new THREE.MeshStandardMaterial({
      color,
      metalness: 0.18,
      roughness: 0.42,
    });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.castShadow = true;
    mesh.receiveShadow = true;

    // edge outline
    const edges = new THREE.LineSegments(
      new THREE.EdgesGeometry(geo),
      new THREE.LineBasicMaterial({ color: 0x0a0e12, transparent: true, opacity: 0.35 })
    );
    mesh.add(edges);
    return mesh;
  }

  spawnBlock() {
    const d = this.diff;
    const palette = [0x3d9cf0, 0x3ecf8e, 0xf0b429, 0xc792ea, 0xf07178, 0x5ad1ff];
    const color = palette[this.stack.length % palette.length];

    if (this.active) {
      this.scene.remove(this.active);
    }

    const top = this.stack[this.stack.length - 1];
    const y = top ? top.mesh.position.y + top.h / 2 + d.h / 2 + 1.15 : this.stackRootY + d.h / 2 + 1.4;

    // 顶层尺寸继承（可略小）
    const w = top ? top.w * (0.92 + Math.random() * 0.05) : d.w;
    const dep = top ? top.d * (0.92 + Math.random() * 0.05) : d.d;

    const mesh = this.makeBlockMesh(w, d.h, dep, color);
    mesh.position.set(0, y, 0);
    this.scene.add(mesh);

    // 方块永远带横向速度，不能靠“手不动”停在原地
    const speedBoost = Math.min(0.85, this.stack.length * 0.06);
    const baseSpeed = this.diff.speed + speedBoost;
    const dir = this.stack.length % 2 === 0 ? 1 : -1;

    this.active = {
      mesh,
      w,
      d: dep,
      h: d.h,
      x: 0,
      z: 0,
      vx: dir * baseSpeed * 1.35,
      phase: Math.random() * Math.PI * 2,
      falling: false,
      vy: 0,
    };
    this.dropLatch = false;
    this._handPrevX = null;
    this._handSpeed = 0;
    this._handActiveUntil = 0;
    this._fistLatch = false;
    this._brakeUntil = 0;
  }

  start() {
    this.restart();
    this.state = "playing";
    if (window.__gameUI) window.__gameUI.showOverlay("", "", "", false);
  }

  restart() {
    for (const b of this.stack) this.scene.remove(b.mesh);
    if (this.active) this.scene.remove(this.active.mesh);
    this.stack = [];
    this.score = 0;
    this.perfects = 0;
    this.height = 0;
    this.state = "playing";
    this.spawnBlock();
    this.reportHud();
    this.updateCamera(true);
  }

  togglePause() {
    if (this.state === "playing") {
      this.state = "paused";
      return true;
    }
    if (this.state === "paused") {
      this.state = "playing";
      return false;
    }
    return false;
  }

  getState() {
    return this.state;
  }

  setDifficulty(key) {
    if (DIFF[key]) {
      this.diff = DIFF[key];
    }
  }

  setMirror(on) {
    this.mirror = !!on;
  }

  setHand(hand) {
    this.hand = hand;
    if (!hand || !Number.isFinite(hand.x)) {
      this._handSpeed = 0;
      return;
    }

    // 估计手部横向速度（单位：归一化坐标/秒）
    const now = performance.now();
    if (this._handPrevX != null && this._lastHandTs) {
      const dt = Math.max(0.016, (now - this._lastHandTs) / 1000);
      const inst = Math.abs(hand.x - this._handPrevX) / dt;
      this._handSpeed = this._handSpeed * 0.7 + inst * 0.3;
    }
    this._handPrevX = hand.x;
    this._lastHandTs = now;

    // 手必须持续移动才拥有控制权（防原地挂机）
    if (this._handSpeed > 0.12) {
      this._handActiveUntil = now + 280;
    }

    // 握拳 → 急刹定住（有效技能）
    if (hand.fist) {
      if (!this._fistLatch) {
        this._fistLatch = true;
        this._brakeUntil = now + 1400;
      }
    } else {
      this._fistLatch = false;
    }
  }

  nudge(dir) {
    if (this.active && !this.active.falling) {
      this.active.x = THREE.MathUtils.clamp(this.active.x + dir * 0.35, -2.2, 2.2);
    }
  }

  drop() {
    if (this.state !== "playing" || !this.active || this.active.falling) return;
    this.active.falling = true;
    this.active.vy = 0;
    this.active.freezeX = this.active.x;
    this.active.freezeZ = this.active.z;
  }

  reportHud() {
    if (window.__gameUI) {
      window.__gameUI.setHud(
        Math.round(this.height * 10),
        this.score,
        this.perfects
      );
    }
  }

  updateCamera(instant) {
    const targetY = Math.max(3, this.height * 0.55 + 2.4);
    const dist = 11 + Math.min(6, this.height * 0.25);
    const t = new THREE.Vector3(0, targetY * 0.55, 0);
    const p = new THREE.Vector3(dist * 0.72, targetY, dist * 0.92);
    if (instant) {
      this.camTarget.copy(t);
      this.camera.position.copy(p);
      this.camera.lookAt(this.camTarget);
    } else {
      this.camTarget.lerp(t, 0.04);
      this.camera.position.lerp(p, 0.04);
      this.camera.lookAt(this.camTarget);
    }
  }

  settleBlock() {
    const a = this.active;
    if (!a) return;
    const top = this.stack[this.stack.length - 1];

    if (!top) {
      // first block: must land near platform center
      const err = Math.hypot(a.freezeX ?? a.x, a.freezeZ ?? a.z);
      if (err > 2.35) {
        this.gameOver();
        return;
      }
    } else {
      const ox = (a.freezeX ?? a.x) - top.x;
      const oz = (a.freezeZ ?? a.z) - top.z;
      const overlapX = Math.min(a.w, top.w) / 2 - Math.abs(ox);
      const overlapZ = Math.min(a.d, top.d) / 2 - Math.abs(oz);

      if (overlapX < 0.08 || overlapZ < 0.08) {
        // miss platform → fall away
        a.falling = true;
        a.vy = -2;
        a.missed = true;
        this.gameOver();
        return;
      }

      // perfect if nearly centered
      const shift = Math.hypot(ox, oz);
      if (shift < 0.06) {
        this.perfects += 1;
        // slight size reward on perfect streak
        if (this.perfects % 3 === 0) {
          a.w = Math.min(a.w * 1.02, this.diff.w);
          a.d = Math.min(a.d * 1.02, this.diff.d);
        }
      } else {
        // 收窄为与上层的重叠区
        a.w = Math.max(0.45, overlapX * 2 * 0.98);
        a.d = Math.max(0.45, overlapZ * 2 * 0.98);
        const gw = a.mesh.geometry.parameters.width || a.w;
        const gd = a.mesh.geometry.parameters.depth || a.d;
        a.mesh.scale.set(a.w / gw, 1, a.d / gd);
      }
    }

    // lock position
    const y = top
      ? top.mesh.position.y + top.h / 2 + a.h / 2
      : this.stackRootY + a.h / 2;
    a.mesh.position.y = y;
    a.x = a.freezeX ?? a.x;
    a.z = a.freezeZ ?? a.z;
    a.mesh.position.x = a.x;
    a.mesh.position.z = a.z;

    this.stack.push({
      mesh: a.mesh,
      w: a.w,
      d: a.d,
      h: a.h,
      x: a.x,
      z: a.z,
    });

    this.score += 1;
    this.height += a.h;
    this.active = null;
    this.reportHud();
    this.updateCamera(false);

    // color pulse on perfect
    if (this.perfects > 0 && this.score === this.perfects) {
      // noop visual cue reserved
    }

    this.spawnBlock();
  }

  gameOver() {
    this.state = "over";
    const score = this.score;
    const height = Math.round(this.height * 10);
    if (window.__gameUI) {
      window.__gameUI.onGameOver(score, height);
    }
    if (this.active) {
      this.active.falling = true;
      this.active.vy = 0;
    }
  }

  updateGame(dt) {
    if (this.state !== "playing") return;
    const a = this.active;
    if (!a) return;

    if (!a.falling) {
      const now = performance.now();
      const handHasControl =
        this.hand &&
        Number.isFinite(this.hand.x) &&
        now < this._handActiveUntil &&
        this._handSpeed > 0.1;

      const brake = now < this._brakeUntil;

      // 基础横移：始终存在（层越高越快）
      const heightBoost = Math.min(1.0, this.stack.length * 0.07);
      const baseSpeed = this.diff.speed + heightBoost;

      if (handHasControl && !brake) {
        // 手在动时“牵引”方块，但仍保持最低漂移，不能完全钉死
        const targetX = (this.hand.x - 0.5) * 4.8;
        const targetZ = (0.5 - (this.hand.y || 0.5)) * 1.4;
        const steer = 0.22;
        a.x += (targetX - a.x) * Math.min(1, dt * 5.5);
        a.z += (targetZ - a.z) * Math.min(1, dt * 4);

        // 残余漂移：手再稳也会缓慢滑走
        a.x += Math.sin(now * 0.0015 + a.phase) * baseSpeed * steer * dt * 6;
      } else if (brake) {
        // 握拳急刹：几乎停住，便于瞄准（有冷却）
        a.x += a.vx * dt * 0.08;
        a.vx *= 0.92;
        if (Math.abs(a.vx) < baseSpeed * 0.35) {
          a.vx = (a.vx >= 0 ? 1 : -1) * baseSpeed * 0.35;
        }
      } else {
        // 无有效手势 / 手静止：经典左右摆
        a.vx += Math.sin(this._animT + a.phase) * 0.15;
        // 限速
        const maxV = baseSpeed * 1.55;
        if (a.vx > maxV) a.vx = maxV;
        if (a.vx < -maxV) a.vx = -maxV;
        a.x += a.vx * dt;
        this._animT += dt * (1.2 + heightBoost);

        // 边界反弹，避免卡死在一侧
        const lim = 2.35;
        if (a.x > lim) {
          a.x = lim;
          a.vx = -Math.abs(a.vx);
        } else if (a.x < -lim) {
          a.x = -lim;
          a.vx = Math.abs(a.vx);
        }
        a.z += (Math.cos(this._animT * 0.5 + a.phase) * 0.35 - a.z) * dt * 3;
      }

      a.mesh.position.x = a.x;
      a.mesh.position.z = a.z;

      if (this.hand && this.hand.pinching && !this.dropLatch) {
        this.dropLatch = true;
        this.drop();
      }
    } else {
      a.vy -= this.diff.fall * dt;
      a.mesh.position.y += a.vy * dt;

      const top = this.stack[this.stack.length - 1];
      const restY = top
        ? top.mesh.position.y + top.h / 2 + a.h / 2
        : this.stackRootY + a.h / 2;

      if (a.missed) {
        if (a.mesh.position.y < -4) {
          this.scene.remove(a.mesh);
          this.active = null;
        }
        return;
      }

      if (a.mesh.position.y <= restY) {
        a.mesh.position.y = restY;
        this.settleBlock();
      }
    }
  }

  resize() {
    const w = this.canvas.clientWidth || 800;
    const h = this.canvas.clientHeight || 560;
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h, false);
  }

  animate() {
    requestAnimationFrame(this.animate);
    const now = performance.now();
    const dt = Math.min(0.033, (now - (this._last || now)) / 1000);
    this._last = now;

    if (this.state !== "paused") {
      this.updateGame(dt);
    }
    this.updateCamera(false);
    this.renderer.render(this.scene, this.camera);
  }
}

const canvas = document.getElementById("gameCanvas");
if (canvas) {
  const game = new StackGame(canvas);
  window.__game3d = game;
  requestAnimationFrame(() => game.resize());
  console.log("[game3d] ready");
}
