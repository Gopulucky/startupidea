import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { DRACOLoader } from 'three/examples/jsm/loaders/DRACOLoader.js';
import { GLTFExporter } from 'three/examples/jsm/exporters/GLTFExporter.js';
import {
  MeshBVH,
  StaticGeometryGenerator,
  acceleratedRaycast,
} from 'three-mesh-bvh';

// Accelerated raycasting (used for camera occlusion checks against the collision mesh)
THREE.Mesh.prototype.raycast = acceleratedRaycast;

// ---------------------------------------------------------------------------
// Renderer / scene / camera
// ---------------------------------------------------------------------------
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
document.body.appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color('#a8c8e8');
scene.fog = new THREE.Fog('#a8c8e8', 45, 95);

const camera = new THREE.PerspectiveCamera(55, window.innerWidth / window.innerHeight, 0.1, 200);

const hemi = new THREE.HemisphereLight('#cfe4ff', '#8f7f60', 0.85);
scene.add(hemi);

const sun = new THREE.DirectionalLight('#fff4e0', 1.6);
sun.position.set(14, 20, 10);
sun.castShadow = true;
sun.shadow.mapSize.set(2048, 2048);
sun.shadow.camera.left = -22;
sun.shadow.camera.right = 22;
sun.shadow.camera.top = 22;
sun.shadow.camera.bottom = -22;
sun.shadow.camera.far = 60;
sun.shadow.bias = -0.0004;
scene.add(sun);

// ---------------------------------------------------------------------------
// The VISUAL LAYER — a procedural test house.
// In production this group is replaced by a scanned mesh (photogrammetry /
// LiDAR GLB) or accompanied by a Gaussian splat. Everything below still works
// unchanged, because collision is generated FROM whatever is in this group.
// ---------------------------------------------------------------------------
const world = new THREE.Group();
scene.add(world);

const MAT = {
  grass: new THREE.MeshStandardMaterial({ color: '#7fb069', roughness: 1 }),
  path: new THREE.MeshStandardMaterial({ color: '#c8bfae', roughness: 1 }),
  wall: new THREE.MeshStandardMaterial({ color: '#e8e0d2', roughness: 0.9, side: THREE.DoubleSide }),
  innerWall: new THREE.MeshStandardMaterial({ color: '#d8e2e8', roughness: 0.9, side: THREE.DoubleSide }),
  floor: new THREE.MeshStandardMaterial({ color: '#c9a06c', roughness: 0.8 }),
  step: new THREE.MeshStandardMaterial({ color: '#b58a5a', roughness: 0.8 }),
  rail: new THREE.MeshStandardMaterial({ color: '#f0ece2', roughness: 0.7 }),
  sofa: new THREE.MeshStandardMaterial({ color: '#5b7fa6', roughness: 0.9 }),
  table: new THREE.MeshStandardMaterial({ color: '#8a6f4d', roughness: 0.8 }),
  counter: new THREE.MeshStandardMaterial({ color: '#9aa5ad', roughness: 0.6 }),
  bed: new THREE.MeshStandardMaterial({ color: '#d9788a', roughness: 0.9 }),
  pillow: new THREE.MeshStandardMaterial({ color: '#f5f2ec', roughness: 1 }),
  trunk: new THREE.MeshStandardMaterial({ color: '#7a5a3a', roughness: 1 }),
  leaves: new THREE.MeshStandardMaterial({ color: '#4e8f4a', roughness: 1 }),
};

function addBox(mat, w, h, d, x, y, z) {
  const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat);
  m.position.set(x, y, z);
  m.castShadow = true;
  m.receiveShadow = true;
  world.add(m);
  return m;
}

function buildDemoHouse() {
// --- terrain + walkway
addBox(MAT.grass, 60, 0.2, 60, 0, -0.1, 0);
addBox(MAT.path, 1.3, 0.12, 3.2, -3.05, 0.05, 5.9);

// --- ground floor slab (top at y = 0.15 — small step up from the lawn)
addBox(MAT.floor, 11, 0.3, 9, 0, 0, 0);

// --- ground-floor walls (height 0.15 → 2.85). Openings are built by
//     composing wall segments, so doors/windows are real holes.
const WY = 1.5; // wall center y
// front wall (z = +4): door at x [-3.6,-2.5], window at x [1.2,2.8]
addBox(MAT.wall, 1.475, 2.7, 0.15, -4.3375, WY, 4);
addBox(MAT.wall, 3.7, 2.7, 0.15, -0.65, WY, 4);
addBox(MAT.wall, 2.275, 2.7, 0.15, 3.9375, WY, 4);
addBox(MAT.wall, 1.1, 0.6, 0.15, -3.05, 2.55, 4);   // door lintel
addBox(MAT.wall, 1.6, 0.9, 0.15, 2.0, 0.6, 4);      // window sill wall
addBox(MAT.wall, 1.6, 0.6, 0.15, 2.0, 2.55, 4);     // window head
// back wall (z = -4): windows at x [-3.3,-1.7] and [1.7,3.3]
addBox(MAT.wall, 1.775, 2.7, 0.15, -4.1875, WY, -4);
addBox(MAT.wall, 3.4, 2.7, 0.15, 0, WY, -4);
addBox(MAT.wall, 1.775, 2.7, 0.15, 4.1875, WY, -4);
for (const wx of [-2.5, 2.5]) {
  addBox(MAT.wall, 1.6, 0.9, 0.15, wx, 0.6, -4);
  addBox(MAT.wall, 1.6, 0.6, 0.15, wx, 2.55, -4);
}
// left wall (x = -5): window at z [-0.8, 0.8]
addBox(MAT.wall, 0.15, 2.7, 3.125, -5, WY, -2.3625);
addBox(MAT.wall, 0.15, 2.7, 3.125, -5, WY, 2.3625);
addBox(MAT.wall, 0.15, 0.9, 1.6, -5, 0.6, 0);
addBox(MAT.wall, 0.15, 0.6, 1.6, -5, 2.55, 0);
// right wall (x = +5): solid — the staircase runs along it
addBox(MAT.wall, 0.15, 2.7, 7.85, 5, WY, 0);
// interior partition at x = 1.2 (open toward the front of the house)
addBox(MAT.innerWall, 0.12, 2.7, 3.425, 1.2, WY, -2.2125);

// --- staircase along the right wall: 13 solid steps, riser ≈ 0.208
const RISER = 2.7 / 13;
for (let i = 0; i < 13; i++) {
  const h = (i + 1) * RISER;
  addBox(MAT.step, 1.15, h, 0.27, 4.375, 0.15 + h / 2, 1.6 - i * 0.27 - 0.135);
}

// --- second-floor slab (top at y = 2.85) with a stairwell opening
addBox(MAT.floor, 8.675, 0.25, 8.15, -0.7375, 2.725, 0);
addBox(MAT.floor, 1.475, 0.25, 2.025, 4.3375, 2.725, -3.0625);
addBox(MAT.floor, 1.475, 0.25, 2.025, 4.3375, 2.725, 3.0625);
// railing guarding the stairwell opening
addBox(MAT.rail, 0.08, 0.95, 4.1, 3.62, 3.325, 0);
addBox(MAT.rail, 1.4, 0.95, 0.08, 4.4, 3.325, 2.07);

// --- upstairs parapet walls (no roof, so you can peek in from outside)
addBox(MAT.wall, 10.15, 1.0, 0.15, 0, 3.35, 4);
addBox(MAT.wall, 10.15, 1.0, 0.15, 0, 3.35, -4);
addBox(MAT.wall, 0.15, 1.0, 7.85, -5, 3.35, 0);
addBox(MAT.wall, 0.15, 1.0, 7.85, 5, 3.35, 0);

// --- furniture (also collidable, automatically)
addBox(MAT.sofa, 2.4, 0.75, 0.95, -3, 0.525, 2.2);
addBox(MAT.table, 1.2, 0.4, 0.6, -3, 0.35, 0.6);
addBox(MAT.counter, 4.0, 0.9, 0.8, -2.6, 0.6, -3.45);
addBox(MAT.bed, 1.9, 0.5, 1.5, -3.4, 3.1, -2.6);
addBox(MAT.pillow, 0.5, 0.18, 1.1, -4.0, 3.44, -2.6);

// --- a few trees outside
for (const [tx, tz] of [[-9, 6], [8, -7], [-8, -8], [9, 5]]) {
  addBox(MAT.trunk, 0.35, 1.6, 0.35, tx, 0.8, tz);
  // note: keep every geometry indexed — StaticGeometryGenerator requires
  // all-indexed or all-non-indexed input to merge into one collision mesh
  const leaves = new THREE.Mesh(new THREE.SphereGeometry(1.1, 8, 6), MAT.leaves);
  leaves.position.set(tx, 2.2, tz);
  leaves.castShadow = true;
  world.add(leaves);
}
}

// ---------------------------------------------------------------------------
// The COLLISION LAYER — generated automatically from whatever is in `world`,
// whether that's the demo house or a real photogrammetry scan.
// StaticGeometryGenerator merges every mesh into one geometry, and MeshBVH
// builds a bounding-volume hierarchy over its triangles so capsule sweeps
// stay fast even against scan-sized meshes (millions of triangles).
// ---------------------------------------------------------------------------
const colliderMaterial = new THREE.MeshBasicMaterial({
  color: '#38e07d', wireframe: true, transparent: true, opacity: 0.35,
});
let collider = null;

function rebuildCollider() {
  if (collider) {
    scene.remove(collider);
    collider.geometry.dispose();
  }
  world.updateMatrixWorld(true); // bake transforms BEFORE merging — the generator reads matrixWorld
  const staticGen = new StaticGeometryGenerator(world);
  staticGen.attributes = ['position'];
  const colliderGeom = staticGen.generate();
  colliderGeom.boundsTree = new MeshBVH(colliderGeom);
  collider = new THREE.Mesh(colliderGeom, colliderMaterial);
  collider.visible = false;
  scene.add(collider);
}

buildDemoHouse();
rebuildCollider();

// ---------------------------------------------------------------------------
// Character — visual doll + invisible capsule used for physics
// ---------------------------------------------------------------------------
const player = new THREE.Group();
player.capsuleInfo = {
  radius: 0.35,
  segment: new THREE.Line3(new THREE.Vector3(0, 1.35, 0), new THREE.Vector3(0, 0.35, 0)),
};
scene.add(player);

const doll = new THREE.Group();
player.add(doll);
{
  const bodyMat = new THREE.MeshStandardMaterial({ color: '#ff8a5c', roughness: 0.6 });
  const skinMat = new THREE.MeshStandardMaterial({ color: '#ffd9b8', roughness: 0.7 });
  const body = new THREE.Mesh(new THREE.CapsuleGeometry(0.28, 0.55, 6, 16), bodyMat);
  body.position.y = 0.78;
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.24, 24, 18), skinMat);
  head.position.y = 1.44;
  const eyeMat = new THREE.MeshStandardMaterial({ color: '#222831' });
  for (const ex of [-0.09, 0.09]) {
    const eye = new THREE.Mesh(new THREE.SphereGeometry(0.035, 10, 10), eyeMat);
    eye.position.set(ex, 1.48, 0.21);
    doll.add(eye);
  }
  const cap = new THREE.Mesh(
    new THREE.SphereGeometry(0.25, 20, 12, 0, Math.PI * 2, 0, Math.PI * 0.45),
    new THREE.MeshStandardMaterial({ color: '#3d5a80', roughness: 0.6 })
  );
  cap.position.y = 1.5;
  for (const fx of [-0.13, 0.13]) {
    const foot = new THREE.Mesh(new THREE.SphereGeometry(0.12, 12, 10), bodyMat);
    foot.scale.set(1, 0.55, 1.3);
    foot.position.set(fx, 0.08, 0.05);
    doll.add(foot);
  }
  doll.add(body, head, cap);
  doll.traverse((o) => { if (o.isMesh) o.castShadow = true; });
}

// ---------------------------------------------------------------------------
// Character scale — the doll/capsule are modeled at ~1.7 world-units tall
// (a real human in metres). BASE holds every size- and speed-constant coupled
// to that; applyCharacterScale(s) rescales all of them together so the
// character can be sized to whatever a given scan's units turn out to be.
// ---------------------------------------------------------------------------
const BASE = {
  radius: 0.35,      // capsule radius
  top: 1.35,         // capsule upper sphere-centre (also the physics y-offset)
  bottom: 0.35,      // capsule lower sphere-centre
  height: 1.7,       // full standing height (top + radius)
  camTargetY: 1.5,   // where the camera looks (eye level)
  camMin: 1.6, camMax: 12, camStart: 5.5,
  walk: 3.4, run: 6.0, jump: 8.5,
};
let characterScale = 1;

function applyCharacterScale(s) {
  characterScale = s;
  player.capsuleInfo.radius = BASE.radius * s;
  player.capsuleInfo.segment.start.set(0, BASE.top * s, 0);
  player.capsuleInfo.segment.end.set(0, BASE.bottom * s, 0);
  doll.scale.setScalar(s);
  updateSizeHud();
}

// ?char=<height> sets the character's standing height in the scan's units
// (e.g. ?char=1.7 for a real 1.7 m person in a metric scan). Overrides auto-fit.
const charParam = new URLSearchParams(location.search).get('char');
const charOverride = charParam != null ? parseFloat(charParam) / BASE.height : null;

// HUD line reporting the current character height
const sizeEl = document.getElementById('size');
function updateSizeHud() {
  if (sizeEl) sizeEl.textContent = `character ≈ ${(BASE.height * characterScale).toFixed(2)} units tall · [ / ] to resize`;
}

const spawnPoint = new THREE.Vector3(-3.05, 0.5, 6.5); // demo-house default; recomputed per scan
const playerVelocity = new THREE.Vector3();
let playerIsOnGround = false;

function resetPlayer() {
  playerVelocity.set(0, 0, 0);
  player.position.copy(spawnPoint);
  camAzimuth = Math.PI; // look toward the house (-z)
  camPolar = 1.05;
  camRadius = BASE.camStart * characterScale;
}

// ---------------------------------------------------------------------------
// REAL-SCAN LOADER — the production pipeline.
// Drop a .glb exported from a phone scan app (Polycam / Luma / Kiri /
// Scaniverse) onto the page, or pass ?model=<url>. The scan becomes the
// visual world AND the collision source; nothing else changes.
// ---------------------------------------------------------------------------
const dracoLoader = new DRACOLoader().setDecoderPath('/draco/');
const gltfLoader = new GLTFLoader().setDRACOLoader(dracoLoader);
const bannerEl = document.getElementById('banner');

function findSpawn() {
  // probe a small grid for a walkable floor: needs a surface below and
  // enough headroom above it for the 1.7m capsule
  const rc = new THREE.Raycaster();
  const box = new THREE.Box3().setFromObject(world);
  const candidates = [[0, 0]];
  for (const r of [1, 2, 3, 4, 6]) {
    candidates.push([r, 0], [-r, 0], [0, r], [0, -r], [r, r], [-r, -r], [r, -r], [-r, r]);
  }
  for (const [x, z] of candidates) {
    rc.set(new THREE.Vector3(x, box.max.y + 1, z), new THREE.Vector3(0, -1, 0));
    rc.far = Infinity;
    const hits = rc.intersectObject(collider, false);
    if (!hits.length) continue;
    // prefer the LOWEST surface with enough headroom — the ground floor of
    // an interior, not the roof of a closed scan
    for (let i = hits.length - 1; i >= 0; i--) {
      const floorY = hits[i].point.y;
      const headroom = (i === 0 ? Infinity : hits[i - 1].point.y) - floorY;
      if (headroom > 1.9) return new THREE.Vector3(x, floorY + 0.1, z);
    }
  }
  return new THREE.Vector3(0, box.max.y + 0.5, 0); // fall back: drop from above
}

// The transform loadScan applies to a GLB is remembered here, so a Gaussian
// splat loaded alongside a collision mesh can be aligned the exact same way.
let lastFit = null;

async function loadScan(url, { scale, visible = true } = {}) {
  bannerEl.textContent = visible ? 'Loading scan…' : 'Loading collision mesh…';
  try {
    const gltf = await gltfLoader.loadAsync(url);
    const root = gltf.scene;

    // orientation: some scan pipelines export Z-up (habitat, several LiDAR
    // tools). A room's height is normally its smallest span — if the Z span
    // is smallest while Y is not, stand the model upright.
    root.updateMatrixWorld(true);
    const s0 = new THREE.Box3().setFromObject(root).getSize(new THREE.Vector3());
    const zUp = s0.z < s0.y * 0.65 && s0.z <= s0.x;
    if (zUp) {
      root.rotation.x = -Math.PI / 2;
      root.updateMatrixWorld(true);
    }

    // normalize units: phone scans are metric, but many downloaded models
    // are not — rescale anything implausibly big or small for a building
    let box = new THREE.Box3().setFromObject(root);
    let size = box.getSize(new THREE.Vector3());
    let s = scale || 1;
    const maxDim = Math.max(size.x, size.y, size.z);
    if (!scale && maxDim > 80) s = 30 / maxDim;
    if (!scale && maxDim < 1.5) s = 8 / maxDim;
    root.scale.setScalar(s);
    root.updateMatrixWorld(true);

    // center on origin, floor at y = 0
    box = new THREE.Box3().setFromObject(root);
    const offset = new THREE.Vector3(
      -(box.min.x + box.max.x) / 2,
      -box.min.y,
      -(box.min.z + box.max.z) / 2
    );
    root.position.copy(offset);

    // remember the exact fit so a paired splat can be aligned identically
    lastFit = { zUp, scale: s, offset: offset.clone() };

    // scans mix indexed/non-indexed primitives; the merger needs uniformity.
    // Materials become UNLIT: photogrammetry textures already contain the
    // real room's light — re-lighting them just makes everything dark.
    root.traverse((o) => {
      if (o.isMesh) {
        if (o.geometry.index) o.geometry = o.geometry.toNonIndexed();
        const map = o.material && o.material.map;
        const hasVertexColors = !!o.geometry.attributes.color;
        o.material = new THREE.MeshBasicMaterial({
          map: map || null,
          vertexColors: hasVertexColors,
          color: map || hasVertexColors ? 0xffffff : 0x999999,
          side: THREE.DoubleSide,
        });
      }
    });

    world.clear();
    world.add(root);
    world.visible = visible;           // collision-only meshes are hidden (a splat draws the visuals)
    rebuildCollider();

    // size the character to the loaded scan. A real human is BASE.height tall;
    // keep that whenever the space is tall enough (correct for metric scans),
    // and only shrink for unusually short models so the doll always fits.
    if (charOverride != null) {
      applyCharacterScale(charOverride);
    } else {
      const sceneH = new THREE.Box3().setFromObject(world).getSize(new THREE.Vector3()).y || BASE.height;
      const targetH = Math.max(0.4, Math.min(BASE.height, 0.6 * sceneH));
      applyCharacterScale(targetH / BASE.height);
    }

    spawnPoint.copy(findSpawn());
    resetPlayer();
    const tris = collider.geometry.attributes.position.count / 3;
    if (visible) {
      bannerEl.textContent = `Scan loaded — ${(tris / 1000).toFixed(0)}k collision triangles. Walk around!`;
    }
    return lastFit;
  } catch (err) {
    bannerEl.textContent = 'Could not load that file: ' + err.message;
    console.error(err);
  }
}

// ---------------------------------------------------------------------------
// GAUSSIAN SPLAT visual layer (the photoreal look). A splat has NO surfaces,
// so it can never provide collision — it is paired with a collision mesh:
//   ?splat=<url>                      -> just look (no walking)
//   ?splat=<url>&collision=<glb url>  -> walk the mesh, see the splat
// The splat is aligned to the collision mesh's fit so the two line up.
// ---------------------------------------------------------------------------
let splatViewer = null;

async function loadSplat(url, fit) {
  bannerEl.textContent = 'Loading Gaussian splat… (first load is heavy)';
  try {
    const GS = await import('@mkkellogg/gaussian-splats-3d');
    if (splatViewer) {
      scene.remove(splatViewer);
      splatViewer.dispose?.();
    }
    // DropInViewer integrates with our own renderer/scene/camera and
    // self-updates via onBeforeRender. sharedMemory off = no COOP/COEP needed.
    splatViewer = new GS.DropInViewer({
      gpuAcceleratedSort: true,
      sharedMemoryForWorkers: false,
    });
    // COLMAP/gsplat splats are Y-down like our raw mesh; match the mesh's flip.
    const orient = [0, 0, 0, 1];
    const rot = new THREE.Quaternion().setFromEuler(new THREE.Euler(Math.PI, 0, 0));
    await splatViewer.addSplatScene(url, {
      showLoadingUI: false,
      splatAlphaRemovalThreshold: 5,
      rotation: [rot.x, rot.y, rot.z, rot.w],
      scale: fit ? [fit.scale, fit.scale, fit.scale] : [1, 1, 1],
    });
    scene.add(splatViewer);
    world.visible = false; // splat is the visual layer; any mesh stays as invisible collision
    bannerEl.textContent = fit
      ? 'Splat + collision loaded — walk around! (press C for the collision view)'
      : 'Splat loaded — walking on demo-house collision. Add &collision=<mesh.glb> for real collision.';
  } catch (err) {
    bannerEl.textContent = 'Could not load splat: ' + err.message;
    console.error(err);
  }
}

// drag & drop anywhere on the page: .glb/.gltf = walkable mesh, .ply/.splat =
// splat visual (drop a .glb too, or add ?collision=, to make it walkable)
window.addEventListener('dragover', (e) => e.preventDefault());
window.addEventListener('drop', (e) => {
  e.preventDefault();
  const files = [...e.dataTransfer.files];
  const mesh = files.find((f) => /\.(glb|gltf)$/i.test(f.name));
  const splat = files.find((f) => /\.(ply|splat|ksplat|spz)$/i.test(f.name));
  if (splat) {
    (async () => {
      const fit = mesh ? await loadScan(URL.createObjectURL(mesh), { visible: false }) : null;
      await loadSplat(URL.createObjectURL(splat), fit);
    })();
  } else if (mesh) {
    loadScan(URL.createObjectURL(mesh));
  } else {
    bannerEl.textContent = 'Drop a .glb/.gltf (walkable mesh) or .ply/.splat (Gaussian splat)';
  }
});

// URL params: ?model=<glb>  |  ?splat=<ply>[&collision=<glb>]
const params = new URLSearchParams(location.search);
const modelParam = params.get('model');
const splatParam = params.get('splat');
const collisionParam = params.get('collision');
if (splatParam) {
  (async () => {
    const fit = collisionParam ? await loadScan(collisionParam, { visible: false }) : null;
    await loadSplat(splatParam, fit);
  })();
} else if (modelParam) {
  loadScan(modelParam);
}

// ---------------------------------------------------------------------------
// Input
// ---------------------------------------------------------------------------
const keys = {};
window.addEventListener('keydown', (e) => {
  keys[e.code] = true;
  if (e.code === 'KeyC') toggleColliderView();
  if (e.code === 'KeyR') resetPlayer();
  // [ and ] shrink / grow the character live (BracketLeft / BracketRight)
  if (e.code === 'BracketLeft') applyCharacterScale(Math.max(0.05, characterScale / 1.1));
  if (e.code === 'BracketRight') applyCharacterScale(Math.min(20, characterScale * 1.1));
  if (e.code === 'Space') e.preventDefault();
});
window.addEventListener('keyup', (e) => (keys[e.code] = false));

let camAzimuth = Math.PI;
let camPolar = 1.05;   // 0 = top-down, PI/2 = horizon
let camRadius = 5.5;
let dragging = false;
renderer.domElement.addEventListener('pointerdown', (e) => {
  dragging = true;
  renderer.domElement.setPointerCapture(e.pointerId);
});
renderer.domElement.addEventListener('pointerup', () => (dragging = false));
renderer.domElement.addEventListener('pointermove', (e) => {
  if (!dragging) return;
  camAzimuth -= e.movementX * 0.005;
  camPolar = THREE.MathUtils.clamp(camPolar - e.movementY * 0.005, 0.2, 1.45);
});
renderer.domElement.addEventListener('wheel', (e) => {
  camRadius = THREE.MathUtils.clamp(camRadius + e.deltaY * 0.004 * characterScale, BASE.camMin * characterScale, BASE.camMax * characterScale);
});

const modeEl = document.getElementById('mode');
function toggleColliderView() {
  collider.visible = !collider.visible;
  world.visible = !collider.visible;
  modeEl.textContent = collider.visible
    ? 'visual layer: hidden | collision layer: BVH wireframe (this is what the character actually walks on)'
    : 'visual layer: house mesh | collision layer: hidden (press C)';
}

// ---------------------------------------------------------------------------
// Physics — capsule vs. BVH triangle collision, the heart of the prototype.
// Runs in fixed substeps for stability. The capsule is swept against the
// merged collision mesh; every penetrating triangle pushes it out, which
// handles floors, walls, stairs and furniture with one uniform rule.
// ---------------------------------------------------------------------------
const GRAVITY = -26;
const WALK_SPEED = 3.4;
const RUN_SPEED = 6.0;
const JUMP_VEL = 8.5;

const upVector = new THREE.Vector3(0, 1, 0);
const tempVector = new THREE.Vector3();
const tempVector2 = new THREE.Vector3();
const tempBox = new THREE.Box3();
const tempMat = new THREE.Matrix4();
const tempSegment = new THREE.Line3();
const moveDir = new THREE.Vector3();
let facingAngle = Math.PI;

function updatePlayer(delta) {
  playerVelocity.y += playerIsOnGround ? 0 : delta * GRAVITY;
  player.position.addScaledVector(playerVelocity, delta);

  // WASD relative to the camera azimuth
  moveDir.set(0, 0, 0);
  if (keys['KeyW'] || keys['ArrowUp']) moveDir.z -= 1;
  if (keys['KeyS'] || keys['ArrowDown']) moveDir.z += 1;
  if (keys['KeyA'] || keys['ArrowLeft']) moveDir.x -= 1;
  if (keys['KeyD'] || keys['ArrowRight']) moveDir.x += 1;
  const moving = moveDir.lengthSq() > 0;
  if (moving) {
    moveDir.normalize().applyAxisAngle(upVector, camAzimuth);
    const speed = (keys['ShiftLeft'] || keys['ShiftRight'] ? RUN_SPEED : WALK_SPEED) * characterScale;
    player.position.addScaledVector(moveDir, speed * delta);
    facingAngle = Math.atan2(moveDir.x, moveDir.z);
  }
  if (playerIsOnGround && keys['Space']) {
    playerVelocity.y = JUMP_VEL * Math.sqrt(characterScale);
    playerIsOnGround = false;
  }

  player.updateMatrixWorld();

  // capsule -> collider local space
  const { radius, segment } = player.capsuleInfo;
  tempBox.makeEmpty();
  tempMat.copy(collider.matrixWorld).invert();
  tempSegment.copy(segment);
  tempSegment.start.applyMatrix4(player.matrixWorld).applyMatrix4(tempMat);
  tempSegment.end.applyMatrix4(player.matrixWorld).applyMatrix4(tempMat);
  tempBox.expandByPoint(tempSegment.start);
  tempBox.expandByPoint(tempSegment.end);
  tempBox.min.addScalar(-radius);
  tempBox.max.addScalar(radius);

  // push the capsule out of every triangle it penetrates
  collider.geometry.boundsTree.shapecast({
    intersectsBounds: (box) => box.intersectsBox(tempBox),
    intersectsTriangle: (tri) => {
      const triPoint = tempVector;
      const capsulePoint = tempVector2;
      const distance = tri.closestPointToSegment(tempSegment, triPoint, capsulePoint);
      if (distance < radius) {
        const depth = radius - distance;
        const direction = capsulePoint.sub(triPoint).normalize();
        tempSegment.start.addScaledVector(direction, depth);
        tempSegment.end.addScaledVector(direction, depth);
      }
    },
  });

  const newPosition = tempVector;
  newPosition.copy(tempSegment.start).applyMatrix4(collider.matrixWorld);
  newPosition.y -= player.capsuleInfo.segment.start.y; // capsule top sphere centre (scales with the character)

  const deltaVector = tempVector2;
  deltaVector.subVectors(newPosition, player.position);

  playerIsOnGround = deltaVector.y > Math.abs(delta * playerVelocity.y * 0.25);

  const offset = Math.max(0, deltaVector.length() - 1e-5);
  deltaVector.normalize().multiplyScalar(offset);
  player.position.add(deltaVector);

  if (!playerIsOnGround) {
    deltaVector.normalize();
    playerVelocity.addScaledVector(deltaVector, -deltaVector.dot(playerVelocity));
  } else {
    playerVelocity.set(0, 0, 0);
  }

  if (player.position.y < -12) resetPlayer();
  return moving;
}

// ---------------------------------------------------------------------------
// Third-person camera with occlusion (pulls in so walls never block the view)
// ---------------------------------------------------------------------------
const camTarget = new THREE.Vector3();
const camIdeal = new THREE.Vector3();
const raycaster = new THREE.Raycaster();
raycaster.firstHitOnly = true;

function updateCamera() {
  camTarget.copy(player.position).add(tempVector.set(0, BASE.camTargetY * characterScale, 0));
  const sinP = Math.sin(camPolar);
  camIdeal.set(
    camTarget.x + camRadius * sinP * Math.sin(camAzimuth),
    camTarget.y + camRadius * Math.cos(camPolar),
    camTarget.z + camRadius * sinP * Math.cos(camAzimuth)
  );
  // occlusion: ray from the head toward the ideal camera spot
  tempVector.subVectors(camIdeal, camTarget);
  const dist = tempVector.length();
  raycaster.set(camTarget, tempVector.normalize());
  raycaster.far = dist;
  const hits = raycaster.intersectObject(collider, false);
  const d = hits.length ? Math.max(hits[0].distance - 0.25, 0.6) : dist;
  camera.position.copy(camTarget).addScaledVector(tempVector, d);
  camera.lookAt(camTarget);
}

// ---------------------------------------------------------------------------
// Main loop
// ---------------------------------------------------------------------------
const clock = new THREE.Clock();
const SUBSTEPS = 5;
resetPlayer();

function tick(delta) {
  let moving = false;
  for (let i = 0; i < SUBSTEPS; i++) {
    moving = updatePlayer(delta / SUBSTEPS) || moving;
  }

  // face the walk direction, with a little bounce while moving
  let a = facingAngle - player.rotation.y;
  a = Math.atan2(Math.sin(a), Math.cos(a));
  player.rotation.y += a * Math.min(1, delta * 12);
  const t = clock.elapsedTime;
  doll.position.y = moving && playerIsOnGround ? Math.abs(Math.sin(t * 9)) * 0.06 : 0;

  updateCamera();
}

renderer.setAnimationLoop(() => {
  tick(Math.min(clock.getDelta(), 1 / 30));
  renderer.render(scene, camera);
});

// debug/testing hook (harmless in production)
window.__walkthru = {
  THREE,
  player,
  playerVelocity,
  keys,
  loadScan,
  worldBox() { return new THREE.Box3().setFromObject(world); },
  setCharacterScale: applyCharacterScale,
  get characterScale() { return characterScale; },
  get characterHeight() { return BASE.height * characterScale; },
  get collider() { return collider; },
  get spawnPoint() { return spawnPoint; },
  exportGLB() {
    // round-trip test: serialize the current world to a real .glb blob URL
    return new Promise((resolve, reject) => {
      new GLTFExporter().parse(
        world,
        (buf) => resolve(URL.createObjectURL(new Blob([buf], { type: 'model/gltf-binary' }))),
        reject,
        { binary: true }
      );
    });
  },
  setCam(azimuth, polar, radius) {
    camAzimuth = azimuth;
    camPolar = polar;
    camRadius = radius;
  },
  // place the camera exactly and render one frame — used by the synthetic
  // capture rig that photographs the scene for photogrammetry testing
  renderFrom(px, py, pz, tx, ty, tz, quality = 0.92) {
    const wasVisible = player.visible;
    player.visible = false;
    camera.position.set(px, py, pz);
    camera.lookAt(tx, ty, tz);
    renderer.render(scene, camera);
    const url = renderer.domElement.toDataURL('image/jpeg', quality);
    player.visible = wasVisible;
    return url;
  },
  get camera() { return camera; },
  probeDown(x, z) {
    const rc = new THREE.Raycaster(new THREE.Vector3(x, 50, z), new THREE.Vector3(0, -1, 0));
    return rc.intersectObject(collider, false).map((h) => +(50 - h.distance).toFixed(3));
  },
  isOnGround: () => playerIsOnGround,
  step(frames = 1) {
    for (let i = 0; i < frames; i++) tick(1 / 60);
  },
  snapshot(width = 960) {
    renderer.render(scene, camera);
    const src = renderer.domElement;
    const c = document.createElement('canvas');
    const scale = width / src.width;
    c.width = width;
    c.height = Math.round(src.height * scale);
    c.getContext('2d').drawImage(src, 0, 0, c.width, c.height);
    return c.toDataURL('image/png');
  },
};

window.addEventListener('resize', () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});
