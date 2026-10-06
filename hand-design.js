// 机械手结构 3D 演示（Three.js）
import * as THREE from "./vendor/three.module.js";

const canvas = document.getElementById("handCanvas");
if (!canvas) {
  console.warn("[hand] canvas missing");
} else {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.shadowMap.enabled = true;

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0xe8eef5);

  const camera = new THREE.PerspectiveCamera(40, 1, 0.1, 100);
  const target = new THREE.Vector3(0, 0.2, 0);
  const sph = { r: 4.2, theta: 0.7, phi: 1.15 };
  const sphT = { ...sph };

  // lights
  scene.add(new THREE.AmbientLight(0xffffff, 0.55));
  const key = new THREE.DirectionalLight(0xffffff, 0.95);
  key.position.set(5, 8, 6);
  key.castShadow = true;
  scene.add(key);
  const fill = new THREE.DirectionalLight(0x3d6b8c, 0.35);
  fill.position.set(-6, 3, -4);
  scene.add(fill);

  // floor grid
  const grid = new THREE.GridHelper(8, 16, 0xb8c4d0, 0xd0d8e0);
  grid.position.y = -1.35;
  scene.add(grid);

  // materials
  const matShell = new THREE.MeshStandardMaterial({
    color: 0xdfe8f0,
    metalness: 0.08,
    roughness: 0.55,
  });
  const matAccent = new THREE.MeshStandardMaterial({
    color: 0x3d6b8c,
    metalness: 0.25,
    roughness: 0.4,
  });
  const matServo = new THREE.MeshStandardMaterial({
    color: 0x2a4a66,
    metalness: 0.35,
    roughness: 0.45,
  });
  const matTendon = new THREE.MeshStandardMaterial({
    color: 0xc45c26,
    metalness: 0.1,
    roughness: 0.5,
  });
  const matJoint = new THREE.MeshStandardMaterial({
    color: 0x1c2430,
    metalness: 0.5,
    roughness: 0.35,
  });

  const hand = new THREE.Group();
  scene.add(hand);

  // --- palm plates ---
  function makePalm() {
    const g = new THREE.Group();
    const shape = new THREE.Shape();
    shape.moveTo(-1.15, 1.35);
    shape.lineTo(1.15, 1.35);
    shape.lineTo(1.35, 0.4);
    shape.lineTo(1.25, -1.05);
    shape.lineTo(-1.25, -1.05);
    shape.lineTo(-1.35, 0.4);
    shape.closePath();
    const geo = new THREE.ExtrudeGeometry(shape, {
      depth: 0.12,
      bevelEnabled: true,
      bevelThickness: 0.02,
      bevelSize: 0.02,
      bevelSegments: 1,
    });
    geo.center();
    const left = new THREE.Mesh(geo, matShell);
    left.position.x = -0.22;
    left.rotation.y = Math.PI / 2;
    left.castShadow = left.receiveShadow = true;
    const right = left.clone();
    right.position.x = 0.22;
    g.add(left, right);

    // bridge
    const bridge = new THREE.Mesh(
      new THREE.BoxGeometry(0.36, 2.2, 0.55),
      matShell
    );
    bridge.position.set(0, 0.15, 0);
    bridge.castShadow = true;
    g.add(bridge);

    // servo bay
    const bay = new THREE.Mesh(
      new THREE.BoxGeometry(0.55, 1.1, 0.7),
      matServo
    );
    bay.position.set(0, 0.15, 0);
    g.add(bay);

    for (let i = 0; i < 5; i++) {
      const s = new THREE.Mesh(
        new THREE.BoxGeometry(0.28, 0.35, 0.28),
        matServo
      );
      s.position.set(-0.55 + i * 0.28, 0.55, 0.1);
      g.add(s);
    }

    // thumb mount
    const thumb = new THREE.Mesh(
      new THREE.BoxGeometry(0.22, 0.7, 0.45),
      matShell
    );
    thumb.position.set(-1.35, -0.15, 0.35);
    thumb.rotation.z = 0.55;
    thumb.rotation.y = -0.35;
    g.add(thumb);

    return g;
  }

  const palm = makePalm();
  hand.add(palm);

  // --- finger builder ---
  function buildFinger(len, x, y, z, scale = 1) {
    const root = new THREE.Group();
    root.position.set(x, y, z);

    const segs = [];
    const lens = [len * 0.42, len * 0.32, len * 0.26];
    const widths = [0.22, 0.19, 0.16];

    let parent = root;
    for (let i = 0; i < 3; i++) {
      const pivot = new THREE.Group();
      pivot.position.y = i === 0 ? 0 : lens[i - 1];
      parent.add(pivot);

      const mesh = new THREE.Mesh(
        new THREE.BoxGeometry(widths[i], lens[i], widths[i]),
        matShell
      );
      mesh.position.y = lens[i] / 2;
      mesh.castShadow = mesh.receiveShadow = true;
      pivot.add(mesh);

      // hinge
      const hinge = new THREE.Mesh(
        new THREE.CylinderGeometry(0.07, 0.07, widths[i] + 0.06, 10),
        matJoint
      );
      hinge.rotation.z = Math.PI / 2;
      pivot.add(hinge);

      // tendon line on top
      const line = new THREE.Mesh(
        new THREE.BoxGeometry(0.035, lens[i] * 0.9, 0.035),
        matTendon
      );
      line.position.y = lens[i] / 2;
      line.position.z = widths[i] / 2 + 0.02;
      pivot.add(line);

      segs.push(pivot);
      parent = pivot;
    }

    // tip pad
    const tip = new THREE.Mesh(
      new THREE.SphereGeometry(0.1, 10, 8),
      matAccent
    );
    tip.position.y = lens[2] + 0.04;
    parent.add(tip);

    root.userData.segs = segs;
    root.userData.scale = scale;
    root.scale.setScalar(scale);
    return root;
  }

  const fingers = [];
  const fingerSpec = [
    { x: -0.85, z: 0, len: 1.55, s: 0.92 },
    { x: -0.35, z: 0, len: 1.75, s: 1.0 },
    { x: 0.15, z: 0, len: 1.85, s: 1.05 },
    { x: 0.65, z: 0, len: 1.65, s: 0.98 },
    { x: 1.1, z: 0, len: 1.25, s: 0.82 },
  ];

  fingerSpec.forEach((spec, i) => {
    const f = buildFinger(spec.len, spec.x, 1.35, 0.05, spec.s);
    hand.add(f);
    fingers.push(f);
  });

  // thumb (2 segments, lateral)
  const thumbRoot = buildFinger(1.35, -1.45, -0.1, 0.55, 0.95);
  thumbRoot.rotation.z = 0.85;
  thumbRoot.rotation.x = -0.35;
  hand.add(thumbRoot);
  fingers.push(thumbRoot);

  // explode parts tracking
  const explodeParts = [
    { obj: palm, base: new THREE.Vector3(0, 0, 0) },
  ];
  fingers.forEach((f) => {
    explodeParts.push({ obj: f, base: f.position.clone() });
  });

  let exploded = false;
  let grip = 0.15; // 0 open, 1 fist
  let gripT = 0.15;

  function applyGrip() {
    fingers.forEach((f, idx) => {
      const segs = f.userData.segs || [];
      const isThumb = idx === fingers.length - 1;
      segs.forEach((seg, si) => {
        const base = isThumb ? -0.15 : -0.05;
        const amp = isThumb ? 0.55 : 1.15;
        seg.rotation.x = base - grip * amp * (0.75 + si * 0.35);
      });
    });
  }

  function applyExplode() {
    explodeParts.forEach((p, i) => {
      const dir = new THREE.Vector3(
        (i % 2 === 0 ? -1 : 1) * (0.35 + i * 0.08),
        exploded ? 0.25 + i * 0.12 : 0,
        exploded ? (i % 3) * 0.35 : 0
      );
      p.obj.position.copy(p.base).add(exploded ? dir : new THREE.Vector3());
    });
    palm.position.y = exploded ? 0.35 : 0;
  }

  function applyCamera() {
    sph.r += (sphT.r - sph.r) * 0.15;
    sph.theta += (sphT.theta - sph.theta) * 0.15;
    sph.phi += (sphT.phi - sph.phi) * 0.15;
    const r = sph.r;
    camera.position.set(
      target.x + r * Math.sin(sph.phi) * Math.sin(sph.theta),
      target.y + r * Math.cos(sph.phi),
      target.z + r * Math.sin(sph.phi) * Math.cos(sph.theta)
    );
    camera.lookAt(target);
  }

  function resize() {
    const w = canvas.clientWidth || 640;
    const h = canvas.clientHeight || 420;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h, false);
  }

  // controls
  const pointers = new Map();
  let lastX = 0;
  let lastY = 0;

  canvas.style.touchAction = "none";
  canvas.addEventListener("pointerdown", (e) => {
    canvas.setPointerCapture?.(e.pointerId);
    pointers.set(e.pointerId, e);
    lastX = e.clientX;
    lastY = e.clientY;
    e.preventDefault();
  });
  canvas.addEventListener("pointermove", (e) => {
    if (!pointers.has(e.pointerId)) return;
    const dx = e.clientX - lastX;
    const dy = e.clientY - lastY;
    lastX = e.clientX;
    lastY = e.clientY;
    sphT.theta -= dx * 0.008;
    sphT.phi = Math.min(Math.PI - 0.2, Math.max(0.2, sphT.phi - dy * 0.008));
    e.preventDefault();
  });
  const up = (e) => {
    pointers.delete(e.pointerId);
    try {
      canvas.releasePointerCapture?.(e.pointerId);
    } catch (_) {}
  };
  canvas.addEventListener("pointerup", up);
  canvas.addEventListener("pointercancel", up);
  canvas.addEventListener(
    "wheel",
    (e) => {
      e.preventDefault();
      sphT.r = Math.min(8, Math.max(2.2, sphT.r * (1 + e.deltaY * 0.0012)));
    },
    { passive: false }
  );
  canvas.addEventListener("dblclick", () => {
    sphT.r = 4.2;
    sphT.theta = 0.7;
    sphT.phi = 1.15;
    target.set(0, 0.2, 0);
  });

  // UI buttons
  document.getElementById("btnViewIso")?.addEventListener("click", () => {
    sphT.theta = 0.7;
    sphT.phi = 1.15;
    sphT.r = 4.2;
  });
  document.getElementById("btnViewFront")?.addEventListener("click", () => {
    sphT.theta = 0;
    sphT.phi = 1.35;
    sphT.r = 3.8;
  });
  document.getElementById("btnViewSide")?.addEventListener("click", () => {
    sphT.theta = Math.PI / 2;
    sphT.phi = 1.25;
    sphT.r = 3.9;
  });
  document.getElementById("btnGrip")?.addEventListener("click", (e) => {
    gripT = gripT > 0.5 ? 0.1 : 1;
    e.target.textContent = gripT > 0.5 ? "张开" : "握拳/张开";
  });
  document.getElementById("btnExplode")?.addEventListener("click", (e) => {
    exploded = !exploded;
    e.target.textContent = exploded ? "合并" : "分解";
    applyExplode();
  });

  let last = performance.now();
  function tick(now) {
    requestAnimationFrame(tick);
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now;
    grip += (gripT - grip) * Math.min(1, dt * 6);
    applyGrip();
    applyCamera();
    renderer.render(scene, camera);
  }

  resize();
  window.addEventListener("resize", resize);
  requestAnimationFrame(tick);
  console.log("[hand] 3D ready");
}
