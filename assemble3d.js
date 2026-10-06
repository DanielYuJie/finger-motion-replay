// 双手虚拟装机 3D：可视化手部光标 + 正式机箱
import * as THREE from "./vendor/three.module.js";

const PARTS = [
  {
    id: "motherboard",
    label: "主板",
    color: 0x1f5c3d,
    size: [2.55, 0.1, 2.15],
    slot: [0, 1.42, -0.12],
    slotRot: [0, 0, 0],
    hint: "主板对准背板铜柱，平放进机箱",
  },
  {
    id: "cpu",
    label: "CPU",
    color: 0xb8c0cc,
    size: [0.58, 0.14, 0.58],
    slot: [0.18, 1.56, -0.38],
    slotRot: [0, 0, 0],
    hint: "CPU 缺角对准插槽标记后放下",
  },
  {
    id: "ram",
    label: "内存条",
    color: 0x2b7fd4,
    size: [0.16, 0.78, 0.14],
    slot: [-0.72, 1.62, -0.18],
    slotRot: [0, 0, 0],
    hint: "内存垂直插入卡槽",
  },
  {
    id: "gpu",
    label: "显卡",
    color: 0x141820,
    size: [2.15, 0.38, 0.58],
    slot: [0.05, 1.08, 0.38],
    slotRot: [0, 0, 0],
    hint: "显卡对准 PCIe 槽，金手指朝下",
  },
  {
    id: "psu",
    label: "电源",
    color: 0x2a3038,
    size: [1.15, 0.72, 1.05],
    slot: [0, 0.58, -0.88],
    slotRot: [0, 0, 0],
    hint: "电源放入底部仓位，风扇朝下",
  },
  {
    id: "cooler",
    label: "散热器",
    color: 0x9aa3b0,
    size: [0.92, 0.48, 0.92],
    slot: [0.18, 1.98, -0.38],
    slotRot: [0, 0, 0],
    hint: "散热器压住 CPU，四角扣具对齐",
  },
];

class AssembleGame {
  constructor(canvas) {
    this.canvas = canvas;
    this.mirror = true;
    this.state = "idle";
    this.parts = {};
    this.grabbed = { L: null, R: null, M: null };
    this.handL = null;
    this.handR = null;

    this.initThree();
    this.buildRoom();
    this.buildCase();
    this.buildGuides();
    this.spawnParts();

    this.animate = this.animate.bind(this);
    requestAnimationFrame(this.animate);
    window.addEventListener("resize", () => this.resize());
    this.bindMouse();
  }

  initThree() {
    const w = this.canvas.clientWidth || 900;
    const h = this.canvas.clientHeight || 560;
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x0b1016);
    this.scene.fog = new THREE.Fog(0x0b1016, 18, 48);

    this.camera = new THREE.PerspectiveCamera(38, w / h, 0.1, 80);
    this.camera.position.set(3.6, 3.4, 7.8);
    this.camera.lookAt(0, 1.35, 0);

    this.renderer = new THREE.WebGLRenderer({ canvas: this.canvas, antialias: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.setSize(w, h, false);
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.05;

    this.scene.add(new THREE.AmbientLight(0xa8c4e8, 0.45));
    const key = new THREE.DirectionalLight(0xffffff, 1.15);
    key.position.set(7, 14, 9);
    key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048);
    key.shadow.camera.left = -10;
    key.shadow.camera.right = 10;
    key.shadow.camera.top = 10;
    key.shadow.camera.bottom = -10;
    this.scene.add(key);

    const rim = new THREE.DirectionalLight(0x5aadff, 0.55);
    rim.position.set(-9, 5, -4);
    this.scene.add(rim);

    const warm = new THREE.PointLight(0xffc27a, 0.55, 20);
    warm.position.set(2, 4, 3);
    this.scene.add(warm);
  }

  buildRoom() {
    const floor = new THREE.Mesh(
      new THREE.CircleGeometry(16, 64),
      new THREE.MeshStandardMaterial({ color: 0x121820, roughness: 0.88, metalness: 0.08 })
    );
    floor.rotation.x = -Math.PI / 2;
    floor.receiveShadow = true;
    this.scene.add(floor);

    const grid = new THREE.GridHelper(20, 40, 0x243040, 0x18202a);
    grid.position.y = 0.01;
    this.scene.add(grid);

    // workbench
    const top = new THREE.Mesh(
      new THREE.BoxGeometry(9.2, 0.18, 4.8),
      new THREE.MeshStandardMaterial({ color: 0x2c3542, roughness: 0.55, metalness: 0.25 })
    );
    top.position.set(0, 0.22, 0.2);
    top.receiveShadow = true;
    top.castShadow = true;
    this.scene.add(top);

    const edge = new THREE.Mesh(
      new THREE.BoxGeometry(9.2, 0.08, 4.8),
      new THREE.MeshStandardMaterial({ color: 0x1a222c, roughness: 0.4, metalness: 0.5 })
    );
    edge.position.set(0, 0.12, 0.2);
    this.scene.add(edge);

    // soft area light panel (emissive)
    const panel = new THREE.Mesh(
      new THREE.BoxGeometry(3.2, 0.06, 2.2),
      new THREE.MeshStandardMaterial({
        color: 0x87b7e8,
        emissive: 0x2a4a6a,
        emissiveIntensity: 0.55,
        transparent: true,
        opacity: 0.35,
      })
    );
    panel.position.set(-4.2, 0.33, 1.6);
    this.scene.add(panel);
  }

  buildCase() {
    this.caseGroup = new THREE.Group();
    this.caseGroup.position.set(0, 0, -0.15);
    this.scene.add(this.caseGroup);

    const shell = new THREE.MeshStandardMaterial({
      color: 0x1c2430,
      metalness: 0.62,
      roughness: 0.32,
    });
    const dark = new THREE.MeshStandardMaterial({
      color: 0x121820,
      metalness: 0.45,
      roughness: 0.5,
    });
    const accent = new THREE.MeshStandardMaterial({
      color: 0x2f6fa8,
      metalness: 0.5,
      roughness: 0.35,
      emissive: 0x0d2a40,
      emissiveIntensity: 0.35,
    });
    const glass = new THREE.MeshPhysicalMaterial({
      color: 0x88b8e8,
      metalness: 0.05,
      roughness: 0.08,
      transmission: 0.55,
      transparent: true,
      opacity: 0.22,
      thickness: 0.2,
    });

    // chassis frame panels
    const panels = [
      // [w,h,d, x,y,z, mat]
      [3.4, 0.16, 2.55, 0, 0.32, 0, shell], // bottom
      [3.4, 2.75, 0.14, 0, 1.68, -1.22, shell], // back
      [3.4, 2.75, 0.14, 0, 1.68, 1.22, dark], // front
      [0.14, 2.75, 2.55, -1.63, 1.68, 0, shell], // left
      [3.4, 0.16, 2.55, 0, 3.02, 0, shell], // top
    ];
    for (const [sx, sy, sz, x, y, z, mat] of panels) {
      const m = new THREE.Mesh(new THREE.BoxGeometry(sx, sy, sz), mat);
      m.position.set(x, y, z);
      m.castShadow = true;
      m.receiveShadow = true;
      this.caseGroup.add(m);
    }

    // tempered glass side
    const glassSide = new THREE.Mesh(new THREE.BoxGeometry(3.25, 2.55, 0.07), glass);
    glassSide.position.set(0, 1.68, 1.3);
    this.caseGroup.add(glassSide);

    // glass border
    const border = new THREE.Mesh(new THREE.BoxGeometry(3.35, 2.65, 0.04), accent);
    border.position.set(0, 1.68, 1.28);
    this.caseGroup.add(border);

    // motherboard tray + standoffs
    const tray = new THREE.Mesh(
      new THREE.BoxGeometry(2.85, 0.08, 2.25),
      new THREE.MeshStandardMaterial({ color: 0x243040, metalness: 0.55, roughness: 0.4 })
    );
    tray.position.set(0, 1.38, -0.12);
    this.caseGroup.add(tray);

    const standoffMat = new THREE.MeshStandardMaterial({
      color: 0xc9a227,
      metalness: 0.85,
      roughness: 0.3,
    });
    const so = [
      [-1.1, -0.85], [0, -0.85], [1.1, -0.85],
      [-1.1, 0], [1.1, 0],
      [-1.1, 0.85], [0, 0.85], [1.1, 0.85],
    ];
    for (const [x, z] of so) {
      const s = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.05, 0.12, 12), standoffMat);
      s.position.set(x, 1.46, z - 0.12);
      this.caseGroup.add(s);
    }

    // PCIe slots
    for (let i = 0; i < 4; i++) {
      const slot = new THREE.Mesh(
        new THREE.BoxGeometry(1.9, 0.06, 0.12),
        new THREE.MeshStandardMaterial({ color: 0x0e141c, metalness: 0.4, roughness: 0.5 })
      );
      slot.position.set(0.15, 1.08, -0.55 + i * 0.22);
      this.caseGroup.add(slot);
    }

    // RAM slots
    for (let i = 0; i < 2; i++) {
      const slot = new THREE.Mesh(
        new THREE.BoxGeometry(0.12, 0.08, 0.85),
        dark
      );
      slot.position.set(-0.72 - i * 0.14, 1.5, -0.15);
      this.caseGroup.add(slot);
    }

    // PSU shroud
    const shroud = new THREE.Mesh(new THREE.BoxGeometry(3.15, 0.55, 1.35), dark);
    shroud.position.set(0, 0.62, -0.55);
    shroud.castShadow = true;
    this.caseGroup.add(shroud);

    // front intake strips
    for (let i = 0; i < 3; i++) {
      const strip = new THREE.Mesh(
        new THREE.BoxGeometry(0.12, 2.1, 0.08),
        accent
      );
      strip.position.set(-1.1 + i * 1.1, 1.7, 1.28);
      this.caseGroup.add(strip);
    }

    // rear I/O shield
    const io = new THREE.Mesh(
      new THREE.BoxGeometry(1.6, 0.7, 0.08),
      new THREE.MeshStandardMaterial({ color: 0x3a4552, metalness: 0.7, roughness: 0.35 })
    );
    io.position.set(0, 1.85, -1.15);
    this.caseGroup.add(io);

    // fan mounts (circular rings on back/top)
    const ringGeo = new THREE.TorusGeometry(0.42, 0.04, 8, 32);
    const fanRing = new THREE.MeshStandardMaterial({
      color: 0x3d9cf0,
      metalness: 0.4,
      roughness: 0.35,
      emissive: 0x123a5c,
      emissiveIntensity: 0.6,
    });
    for (const [x, y, z, rx, ry] of [
      [0, 2.35, -1.12, 0, 0],
      [-1.62, 1.7, 0, 0, Math.PI / 2],
      [1.62, 1.7, 0, 0, Math.PI / 2],
    ]) {
      const r = new THREE.Mesh(ringGeo, fanRing);
      r.position.set(x, y, z);
      r.rotation.set(rx, ry, 0);
      this.caseGroup.add(r);
    }

    // feet
    for (const [x, z] of [[-1.4, -1], [1.4, -1], [-1.4, 1], [1.4, 1]]) {
      const foot = new THREE.Mesh(
        new THREE.CylinderGeometry(0.12, 0.15, 0.18, 12),
        dark
      );
      foot.position.set(x, 0.12, z);
      this.caseGroup.add(foot);
    }
  }

  buildGuides() {
    this.slotMarkers = {};
    this.slotLabels = {};

    // HTML overlay layer for labels
    this.labelLayer = document.getElementById("labelLayer");
    if (!this.labelLayer) {
      this.labelLayer = document.createElement("div");
      this.labelLayer.id = "labelLayer";
      this.labelLayer.className = "label-layer";
      this.canvas.parentElement.appendChild(this.labelLayer);
    }

    for (const p of PARTS) {
      const box = new THREE.Mesh(
        new THREE.BoxGeometry(p.size[0] + 0.16, p.size[1] + 0.16, p.size[2] + 0.16),
        new THREE.MeshBasicMaterial({
          color: 0x3d9cf0,
          transparent: true,
          opacity: 0.1,
          depthWrite: false,
        })
      );
      box.position.set(...p.slot);
      box.visible = false;
      this.caseGroup.add(box);

      const ring = new THREE.Mesh(
        new THREE.BoxGeometry(p.size[0] + 0.28, 0.025, p.size[2] + 0.28),
        new THREE.MeshBasicMaterial({
          color: 0x5ad1ff,
          transparent: true,
          opacity: 0.45,
        })
      );
      ring.position.set(p.slot[0], p.slot[1] - p.size[1] / 2 - 0.03, p.slot[2]);
      ring.visible = false;
      this.caseGroup.add(ring);

      // vertical guide pillar
      const pillar = new THREE.Mesh(
        new THREE.CylinderGeometry(0.03, 0.03, 1.4, 8),
        new THREE.MeshBasicMaterial({
          color: 0xf0b429,
          transparent: true,
          opacity: 0.35,
        })
      );
      pillar.position.set(p.slot[0], p.slot[1] + 0.85, p.slot[2]);
      pillar.visible = false;
      this.caseGroup.add(pillar);

      this.slotMarkers[p.id] = { box, ring, pillar };

      // DOM label
      const el = document.createElement("div");
      el.className = "slot-label";
      el.textContent = p.label + " ← " + p.hint;
      el.style.display = "none";
      this.labelLayer.appendChild(el);
      this.slotLabels[p.id] = el;
    }

    // hand cursors
    const cursorGeo = new THREE.SphereGeometry(0.14, 20, 20);
    const makeCursor = (color) => {
      const g = new THREE.Group();
      const core = new THREE.Mesh(
        cursorGeo,
        new THREE.MeshStandardMaterial({
          color,
          emissive: color,
          emissiveIntensity: 0.65,
          metalness: 0.2,
          roughness: 0.3,
          transparent: true,
          opacity: 0.92,
        })
      );
      g.add(core);
      const halo = new THREE.Mesh(
        new THREE.SphereGeometry(0.28, 16, 16),
        new THREE.MeshBasicMaterial({
          color,
          transparent: true,
          opacity: 0.12,
          depthWrite: false,
        })
      );
      g.add(halo);
      const ring = new THREE.Mesh(
        new THREE.TorusGeometry(0.22, 0.02, 8, 24),
        new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.7 })
      );
      ring.rotation.x = Math.PI / 2;
      g.add(ring);
      g.visible = false;
      this.scene.add(g);
      return g;
    };

    this.cursorL = makeCursor(0x5ad1ff);
    this.cursorR = makeCursor(0xc792ea);

    // guide line from hand to held part
    this.guideLine = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(),
        new THREE.Vector3(),
      ]),
      new THREE.LineBasicMaterial({
        color: 0xf0b429,
        transparent: true,
        opacity: 0.65,
      })
    );
    this.guideLine.visible = false;
    this.scene.add(this.guideLine);

    // path line part → slot
    this.pathLine = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(),
        new THREE.Vector3(),
      ]),
      new THREE.LineDashedMaterial({
        color: 0x3ecf8e,
        dashSize: 0.18,
        gapSize: 0.12,
        transparent: true,
        opacity: 0.8,
      })
    );
    this.pathLine.visible = false;
    this.scene.add(this.pathLine);

    // operation hint sprite-like plane (billboard text via DOM instead)
    this.opHint = document.createElement("div");
    this.opHint.className = "op-hint";
    this.opHint.textContent = "张开双手进入画面 · 捏合抓取零件";
    this.labelLayer.appendChild(this.opHint);
  }

  spawnParts() {
    for (const key of Object.keys(this.parts)) {
      const p = this.parts[key];
      if (p.mesh) this.scene.remove(p.mesh);
    }
    this.parts = {};

    PARTS.forEach((def, i) => {
      const geo = new THREE.BoxGeometry(def.size[0], def.size[1], def.size[2]);
      const mat = new THREE.MeshStandardMaterial({
        color: def.color,
        metalness: 0.35,
        roughness: 0.38,
      });
      const mesh = new THREE.Mesh(geo, mat);
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      mesh.add(
        new THREE.LineSegments(
          new THREE.EdgesGeometry(geo),
          new THREE.LineBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.28 })
        )
      );

      // detail: top plate for motherboard-like parts
      if (def.id === "motherboard") {
        const plate = new THREE.Mesh(
          new THREE.BoxGeometry(2.2, 0.04, 1.7),
          new THREE.MeshStandardMaterial({ color: 0x2d8a5c, metalness: 0.3, roughness: 0.45 })
        );
        plate.position.y = 0.07;
        mesh.add(plate);
      }
      if (def.id === "gpu") {
        const shroud = new THREE.Mesh(
          new THREE.BoxGeometry(1.6, 0.42, 0.5),
          new THREE.MeshStandardMaterial({ color: 0x222831, metalness: 0.5, roughness: 0.35 })
        );
        shroud.position.y = 0.18;
        mesh.add(shroud);
        const stripe = new THREE.Mesh(
          new THREE.BoxGeometry(1.5, 0.04, 0.08),
          new THREE.MeshStandardMaterial({
            color: 0x3ecf8e,
            emissive: 0x0f4d2e,
            emissiveIntensity: 0.7,
          })
        );
        stripe.position.set(0, 0.18, 0.3);
        mesh.add(stripe);
      }

      const side = i % 2 === 0 ? -1 : 1;
      const spawn = {
        x: side * (2.35 + (i % 3) * 0.12),
        y: 0.42 + def.size[1] / 2,
        z: 1.55 - Math.floor(i / 2) * 0.52,
      };
      mesh.position.set(spawn.x, spawn.y, spawn.z);
      this.scene.add(mesh);

      // resting glow pad
      const pad = new THREE.Mesh(
        new THREE.CircleGeometry(0.55, 24),
        new THREE.MeshBasicMaterial({
          color: 0x3d9cf0,
          transparent: true,
          opacity: 0.12,
        })
      );
      pad.rotation.x = -Math.PI / 2;
      pad.position.set(spawn.x, 0.33, spawn.z);
      this.scene.add(pad);

      this.parts[def.id] = {
        ...def,
        mesh,
        pad,
        spawn,
        done: false,
        active: false,
        wrongFlash: 0,
        heldBy: null,
      };
    });

    this.doneCount = 0;
    this.reportUI();
  }

  setMirror(on) {
    this.mirror = !!on;
  }

  start() {
    this.reset();
    this.state = "playing";
    if (window.__asmUI) window.__asmUI.setOverlay(false);
  }

  reset() {
    this.grabbed.L = null;
    this.grabbed.R = null;
    this.grabbed.M = null;
    this.spawnParts();
    this.state = "playing";
    this.reportUI();
  }

  focusNext() {
    for (const def of PARTS) {
      const p = this.parts[def.id];
      if (p && !p.done) {
        this.highlightPart(def.id);
        return;
      }
    }
  }

  highlightPart(id) {
    for (const def of PARTS) {
      const p = this.parts[def.id];
      const m = this.slotMarkers[def.id];
      const label = this.slotLabels[def.id];
      const on = def.id === id && !p.done;
      p.active = on;
      if (m) {
        m.box.visible = on;
        m.ring.visible = on;
        m.pillar.visible = on;
      }
      if (label) label.style.display = on ? "block" : "none";
    }
  }

  reportUI() {
    const total = PARTS.length;
    let hint = "捏合抓取零件";
    let nextId = null;
    for (const def of PARTS) {
      const p = this.parts[def.id];
      if (p && !p.done) {
        hint = "下一步：" + def.label;
        nextId = def.id;
        break;
      }
    }
    if (this.doneCount >= total) {
      hint = "全部完成";
      this.highlightPart(null);
      if (window.__asmUI?.onFinished) window.__asmUI.onFinished();
    } else if (nextId) {
      this.highlightPart(nextId);
    }

    if (this.opHint) {
      if (this.doneCount >= total) {
        this.opHint.textContent = "装配完成！可重置再来";
      } else if (this.handL || this.handR) {
        this.opHint.textContent =
          "移动发光圆点到零件上 · 捏合抓取 · 移到蓝色卡槽 · 松开捏合安装";
      } else {
        this.opHint.textContent = "请把双手伸入摄像头画面，圆点会显示手的位置";
      }
    }

    if (window.__asmUI) {
      window.__asmUI.setHud(this.doneCount, total, hint);
      window.__asmUI.setParts(this.parts);
    }
  }

  handToWorld(hx, hy) {
    const x = (hx - 0.5) * 6.6;
    const y = 0.4 + (1 - hy) * 2.7;
    const z = 1.25 + (hy - 0.5) * 1.5;
    return new THREE.Vector3(x, y, z);
  }

  nearestFreePart(worldPos, maxDist) {
    let best = null;
    let bestD = maxDist;
    for (const id of Object.keys(this.parts)) {
      const p = this.parts[id];
      if (p.done || p.heldBy) continue;
      const d = p.mesh.position.distanceTo(worldPos);
      if (d < bestD) {
        bestD = d;
        best = p;
      }
    }
    return best;
  }

  tryGrabOrRelease(side, hand) {
    if (this.state !== "playing") return;
    const world = this.handToWorld(hand.x, hand.y);

    if (this.grabbed[side]) {
      this.releasePart(side, world);
      return;
    }

    const part = this.nearestFreePart(world, 1.5);
    if (!part) {
      if (this.opHint) this.opHint.textContent = "靠近零件再捏合（圆点贴上零件）";
      return;
    }
    part.heldBy = side;
    this.grabbed[side] = part;
    if (this.opHint) this.opHint.textContent = "已抓住「" + part.label + "」，移向高亮卡槽";
  }

  onHandOpen() {}

  releasePart(side, worldPos) {
    const part = this.grabbed[side];
    if (!part) return;
    this.grabbed[side] = null;
    part.heldBy = null;

    const slot = new THREE.Vector3(...part.slot);
    // account for case group offset
    slot.add(this.caseGroup.position);
    const dist = worldPos.distanceTo(slot);
    const snapDist = 1.05;

    if (dist < snapDist) {
      part.mesh.position.copy(slot);
      part.mesh.rotation.set(...part.slotRot);
      part.done = true;
      part.pad.visible = false;
      this.doneCount += 1;
      part.mesh.material.emissive = new THREE.Color(0x1a4d2e);
      setTimeout(() => {
        part.mesh.material.emissive = new THREE.Color(0x000000);
      }, 320);
      if (this.opHint) this.opHint.textContent = "「" + part.label + "」安装成功";
      this.reportUI();
    } else {
      part.wrongFlash = 1;
      part.mesh.position.copy(part.spawn);
      if (this.opHint) {
        this.opHint.textContent =
          "「" + part.label + "」没对准，看蓝色卡槽和黄色光柱后再放";
      }
    }
  }

  followHands(hL, hR) {
    this.handL = hL;
    this.handR = hR;

    const move = (side, h) => {
      const part = this.grabbed[side];
      if (!part || !h) return;
      const target = this.handToWorld(h.x, h.y);
      const slot = new THREE.Vector3(...part.slot).add(this.caseGroup.position);
      const near = target.distanceTo(slot) < 1.25;
      const assist = (this.handL && this.handL.fist) || (this.handR && this.handR.fist);
      if (near || assist) target.lerp(slot, near ? 0.28 : 0.12);
      part.mesh.position.lerp(target, 0.5);
    };
    move("L", hL);
    move("R", hR);
  }

  setHands(hL, hR) {
    if (hL) this.handL = { ...this.handL, ...hL };
    if (hR) this.handR = { ...this.handR, ...hR };
    if (!hL && !this.grabbed.L) this.handL = null;
    if (!hR && !this.grabbed.R) this.handR = null;

    // cursors
    const place = (cursor, h, held) => {
      if (!h) {
        cursor.visible = false;
        return;
      }
      cursor.visible = true;
      const pos = this.handToWorld(h.x, h.y);
      cursor.position.lerp(pos, 0.45);
      const scale = h.pinching ? 0.72 : h.fist ? 0.88 : 1;
      cursor.scale.setScalar(scale + (held ? 0.15 : 0));
    };
    place(this.cursorL, this.handL, this.grabbed.L);
    place(this.cursorR, this.handR, this.grabbed.R);

    // guide line
    const held =
      this.grabbed.L || this.grabbed.R || this.grabbed.M;
    const handPos =
      (this.grabbed.L && this.cursorL.position) ||
      (this.grabbed.R && this.cursorR.position) ||
      null;

    if (held && handPos) {
      this.guideLine.visible = true;
      const pts = this.guideLine.geometry.attributes.position;
      pts.setXYZ(0, handPos.x, handPos.y, handPos.z);
      pts.setXYZ(
        1,
        held.mesh.position.x,
        held.mesh.position.y,
        held.mesh.position.z
      );
      pts.needsUpdate = true;

      // dashed path to slot
      const slot = new THREE.Vector3(...held.slot).add(this.caseGroup.position);
      this.pathLine.visible = true;
      const pp = this.pathLine.geometry.attributes.position;
      pp.setXYZ(0, held.mesh.position.x, held.mesh.position.y, held.mesh.position.z);
      pp.setXYZ(1, slot.x, slot.y + 0.75, slot.z);
      pp.needsUpdate = true;
      this.pathLine.computeLineDistances();
    } else {
      this.guideLine.visible = false;
      this.pathLine.visible = false;
    }
  }

  bindMouse() {
    const ray = new THREE.Raycaster();
    const mouse = new THREE.Vector2();
    let dragging = null;

    const toWorld = (e) => {
      const rect = this.canvas.getBoundingClientRect();
      mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
      ray.setFromCamera(mouse, this.camera);
      const plane = new THREE.Plane(new THREE.Vector3(0, 0, 1), -1.1);
      const hit = new THREE.Vector3();
      ray.ray.intersectPlane(plane, hit);
      return hit;
    };

    this.canvas.addEventListener("pointerdown", (e) => {
      if (this.state !== "playing") this.start();
      const world = toWorld(e);
      const part = this.nearestFreePart(world, 1.3);
      if (part) {
        dragging = part;
        part.heldBy = "M";
        this.grabbed.M = part;
      }
    });
    this.canvas.addEventListener("pointermove", (e) => {
      if (!dragging) return;
      dragging.mesh.position.lerp(toWorld(e), 0.65);
    });
    this.canvas.addEventListener("pointerup", () => {
      if (!dragging) return;
      this.releasePart("M", dragging.mesh.position.clone());
      dragging = null;
    });
  }

  projectLabel(el, worldPos) {
    const v = worldPos.clone().project(this.camera);
    const rect = this.canvas.getBoundingClientRect();
    const x = (v.x * 0.5 + 0.5) * rect.width;
    const y = (-v.y * 0.5 + 0.5) * rect.height;
    el.style.left = x + "px";
    el.style.top = y + "px";
  }

  resize() {
    const w = this.canvas.clientWidth || 900;
    const h = this.canvas.clientHeight || 560;
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h, false);
    if (this.labelLayer) {
      this.labelLayer.style.width = w + "px";
      this.labelLayer.style.height = h + "px";
    }
  }

  animate() {
    requestAnimationFrame(this.animate);
    const t = performance.now() * 0.003;

    for (const id of Object.keys(this.parts)) {
      const p = this.parts[id];
      const m = this.slotMarkers[id];
      if (m && m.box.visible) {
        m.box.material.opacity = 0.1 + Math.sin(t) * 0.05;
        m.ring.material.opacity = 0.35 + Math.sin(t * 1.3) * 0.15;
        m.pillar.material.opacity = 0.25 + Math.sin(t * 1.6) * 0.12;
      }
      if (p.wrongFlash > 0) {
        p.wrongFlash *= 0.92;
        p.mesh.material.emissive = new THREE.Color(0x662222).multiplyScalar(p.wrongFlash);
        if (p.wrongFlash < 0.05) {
          p.wrongFlash = 0;
          p.mesh.material.emissive = new THREE.Color(0x000000);
        }
      }
    }

    // update DOM labels
    for (const id of Object.keys(this.slotLabels || {})) {
      const el = this.slotLabels[id];
      if (!el || el.style.display === "none") continue;
      const def = PARTS.find((p) => p.id === id);
      if (!def) continue;
      const pos = new THREE.Vector3(...def.slot).add(this.caseGroup.position);
      pos.y += 1.15;
      this.projectLabel(el, pos);
    }

    // hand cursor idle pulse
    for (const c of [this.cursorL, this.cursorR]) {
      if (c && c.visible) {
        const halo = c.children[1];
        if (halo) halo.scale.setScalar(1 + Math.sin(t * 2) * 0.08);
      }
    }

    this.renderer.render(this.scene, this.camera);
  }
}

const canvas = document.getElementById("assembleCanvas");
if (canvas) {
  const game = new AssembleGame(canvas);
  window.__assemble3d = game;
  requestAnimationFrame(() => game.resize());
  if (window.__asmUI) {
    window.__asmUI.setHud(0, 6, "双手入画，捏合抓取");
    window.__asmUI.setParts(game.parts);
  }
  console.log("[assemble3d] ready v2");
}
