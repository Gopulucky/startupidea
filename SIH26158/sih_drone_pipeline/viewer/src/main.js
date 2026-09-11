import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { PLYLoader } from 'three/examples/jsm/loaders/PLYLoader.js';

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setSize(innerWidth, innerHeight);
renderer.outputColorSpace = THREE.SRGBColorSpace;
document.body.prepend(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color('#071018');
const camera = new THREE.PerspectiveCamera(50, innerWidth / innerHeight, 0.01, 1_000_000);
camera.position.set(25, 20, 25);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.08;
scene.add(new THREE.HemisphereLight('#c9ecff', '#28331f', 2.2));
const sun = new THREE.DirectionalLight('#ffffff', 2.2);
sun.position.set(100, 150, 80);
scene.add(sun);
scene.add(new THREE.GridHelper(200, 100, '#325970', '#173142'));
scene.add(new THREE.AxesHelper(5));

const content = new THREE.Group();
scene.add(content);
const raycaster = new THREE.Raycaster();
raycaster.params.Points.threshold = 0.15;
const pointer = new THREE.Vector2();
const measurePoints = [];
const measurementLayer = new THREE.Group();
scene.add(measurementLayer);

const ui = Object.fromEntries(
  ['model-name', 'vertices', 'processing', 'registration', 'reprojection', 'gps-rmse', 'gpu', 'accuracy', 'origin', 'cursor', 'distance', 'status']
    .map(id => [id, document.getElementById(id)])
);

function disposeContent() {
  while (content.children.length) {
    const object = content.children[0];
    content.remove(object);
    object.traverse?.(child => {
      child.geometry?.dispose();
      if (Array.isArray(child.material)) child.material.forEach(material => material.dispose());
      else child.material?.dispose();
    });
  }
}

function vertexCount(object) {
  let count = 0;
  object.traverse(child => { if (child.geometry?.attributes?.position) count += child.geometry.attributes.position.count; });
  return count;
}

function fitView(object) {
  const box = new THREE.Box3().setFromObject(object);
  if (box.isEmpty()) return;
  const sphere = box.getBoundingSphere(new THREE.Sphere());
  const distance = Math.max(2, sphere.radius / Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) * 1.3);
  controls.target.copy(sphere.center);
  camera.near = Math.max(0.01, distance / 10_000);
  camera.far = Math.max(1_000, distance * 20);
  camera.updateProjectionMatrix();
  camera.position.copy(sphere.center).add(new THREE.Vector3(1, 0.8, 1).normalize().multiplyScalar(distance));
  controls.update();
}

function acceptModel(object, name) {
  disposeContent();
  content.add(object);
  ui['model-name'].textContent = name;
  ui.vertices.textContent = vertexCount(object).toLocaleString();
  ui.status.textContent = 'Metric model loaded. Coordinates are displayed in the local ENU frame.';
  clearMeasurement();
  fitView(object);
}

async function loadModelFile(file) {
  const url = URL.createObjectURL(file);
  try {
    if (/\.ply$/i.test(file.name)) {
      const geometry = await new PLYLoader().loadAsync(url);
      geometry.computeVertexNormals?.();
      const hasFaces = Boolean(geometry.index);
      const hasColors = Boolean(geometry.attributes.color);
      const object = hasFaces
        ? new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({ vertexColors: hasColors, color: hasColors ? '#ffffff' : '#b8c9d1', side: THREE.DoubleSide }))
        : new THREE.Points(geometry, new THREE.PointsMaterial({ size: 0.06, vertexColors: hasColors, color: hasColors ? '#ffffff' : '#b8c9d1' }));
      acceptModel(object, file.name);
    } else {
      const gltf = await new GLTFLoader().loadAsync(url);
      acceptModel(gltf.scene, file.name);
    }
  } finally {
    URL.revokeObjectURL(url);
  }
}

function loadReport(report) {
  const validation = report.validation || {};
  const independent = validation.independent_distances || {};
  const metrics = report.metrics || {};
  const gpu = report.formats?.gpu_log || {};
  const processingSeconds = report.processing_seconds ?? report.wall_clock_seconds;
  ui.processing.textContent = processingSeconds == null ? '-' : `${(processingSeconds / 60).toFixed(1)} min`;
  const registration = report.registration_percent ?? report.sparse_metrics?.registration_percent ?? metrics.registration_percent;
  ui.registration.textContent = registration == null ? '-' : `${Number(registration).toFixed(1)}%`;
  const reprojection = report.sparse_metrics?.mean_reprojection_error_px ?? metrics.reprojection_error_px;
  ui.reprojection.textContent = reprojection == null ? '-' : `${Number(reprojection).toFixed(3)} px`;
  ui['gps-rmse'].textContent = validation.gps_alignment_rmse_m == null ? '-' : `${validation.gps_alignment_rmse_m.toFixed(2)} m`;
  const peakGpu = gpu.utilization_gpu_percent_max;
  const peakMemory = gpu.memory_used_mb_max;
  ui.gpu.textContent = peakGpu == null ? '-' : `${Number(peakGpu).toFixed(0)}% / ${Number(peakMemory || 0).toFixed(0)} MB`;
  const accuracyPass = independent.passes_one_metre_target ?? metrics.one_metre_accuracy;
  ui.accuracy.textContent = accuracyPass == null ? 'Unverified' : accuracyPass ? 'PASS (<= 1 m)' : 'FAIL (> 1 m)';
  const origin = report.origin;
  ui.origin.textContent = origin ? `${origin.latitude.toFixed(6)}, ${origin.longitude.toFixed(6)}` : '-';
  ui.status.textContent = 'Run metadata loaded. GPS RMSE is an alignment diagnostic; independent checks prove accuracy.';
}

function intersections(event) {
  pointer.x = (event.clientX / innerWidth) * 2 - 1;
  pointer.y = -(event.clientY / innerHeight) * 2 + 1;
  raycaster.setFromCamera(pointer, camera);
  return raycaster.intersectObject(content, true);
}

function clearMeasurement() {
  measurePoints.length = 0;
  while (measurementLayer.children.length) {
    const child = measurementLayer.children.pop();
    child.geometry?.dispose();
    child.material?.dispose();
  }
  ui.distance.textContent = '-';
}

renderer.domElement.addEventListener('pointermove', event => {
  const hit = intersections(event)[0];
  ui.cursor.textContent = hit ? `${hit.point.x.toFixed(2)}, ${hit.point.y.toFixed(2)}, ${hit.point.z.toFixed(2)} m` : '-';
});
renderer.domElement.addEventListener('click', event => {
  if (!event.shiftKey) return;
  const hit = intersections(event)[0];
  if (!hit) return;
  if (measurePoints.length === 2) clearMeasurement();
  measurePoints.push(hit.point.clone());
  const marker = new THREE.Mesh(new THREE.SphereGeometry(0.14, 16, 12), new THREE.MeshBasicMaterial({ color: '#ff5e57' }));
  marker.position.copy(hit.point);
  measurementLayer.add(marker);
  if (measurePoints.length === 2) {
    measurementLayer.add(new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(measurePoints),
      new THREE.LineBasicMaterial({ color: '#ff5e57' })
    ));
    ui.distance.textContent = `${measurePoints[0].distanceTo(measurePoints[1]).toFixed(3)} m`;
  }
});

document.getElementById('model-file').addEventListener('change', event => event.target.files[0] && loadModelFile(event.target.files[0]));
document.getElementById('report-file').addEventListener('change', async event => {
  if (event.target.files[0]) loadReport(JSON.parse(await event.target.files[0].text()));
});
document.getElementById('clear-measurement').addEventListener('click', clearMeasurement);

const drop = document.getElementById('drop');
window.addEventListener('dragover', event => { event.preventDefault(); drop.style.display = 'grid'; });
window.addEventListener('dragleave', event => { if (!event.relatedTarget) drop.style.display = 'none'; });
window.addEventListener('drop', async event => {
  event.preventDefault(); drop.style.display = 'none';
  for (const file of event.dataTransfer.files) {
    if (/\.json$/i.test(file.name)) loadReport(JSON.parse(await file.text()));
    else if (/\.(glb|ply)$/i.test(file.name)) await loadModelFile(file);
  }
});

window.addEventListener('resize', () => {
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
});
renderer.setAnimationLoop(() => { controls.update(); renderer.render(scene, camera); });
