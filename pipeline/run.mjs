#!/usr/bin/env node
// WalkThru reconstruction pipeline: photos in → walkable textured GLB out.
// This is the same class of pipeline Polycam/Luma run server-side, built
// from open-source parts:
//   COLMAP  — camera pose estimation (structure-from-motion)
//   OpenMVS — dense point cloud, mesh, texture
//   obj2gltf — final GLB for the WalkThru viewer
//
// Usage: node pipeline/run.mjs <images_dir> <output.glb> [--fast]

import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import obj2gltf from 'obj2gltf';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const COLMAP = path.join(ROOT, 'tools', 'colmap', 'bin', 'colmap.exe');
const MVS = path.join(ROOT, 'tools', 'openmvs', 'vc17', 'x64', 'Release');

const [imagesDirArg, outputArg] = process.argv.slice(2).filter((a) => !a.startsWith('--'));
const FAST = process.argv.includes('--fast');
if (!imagesDirArg || !outputArg) {
  console.error('usage: node pipeline/run.mjs <images_dir> <output.glb> [--fast]');
  process.exit(1);
}
const imagesDir = path.resolve(imagesDirArg);
const outputGlb = path.resolve(outputArg);
const work = path.join(path.dirname(imagesDir), path.basename(imagesDir) + '_work');
fs.rmSync(work, { recursive: true, force: true });
fs.mkdirSync(work, { recursive: true });

const t0 = Date.now();
function run(title, exe, args, cwd = work, allowFail = false) {
  const t = Date.now();
  console.log(`\n=== ${title} ===`);
  const res = spawnSync(exe, args, { cwd, stdio: ['ignore', 'inherit', 'inherit'] });
  if (res.status !== 0) {
    if (allowFail) {
      console.log(`(stage failed with exit ${res.status}, continuing) ${title}`);
      return res.status || 1;
    }
    console.error(`FAILED (exit ${res.status}): ${title}`);
    process.exit(res.status || 1);
  }
  console.log(`--- ${title} done in ${((Date.now() - t) / 1000).toFixed(0)}s`);
  return 0;
}

// optional known intrinsics from the capture rig (intrinsics.json in images dir)
let cameraArgs = [];
const intrinsicsPath = path.join(imagesDir, 'intrinsics.json');
if (fs.existsSync(intrinsicsPath)) {
  const { model, params } = JSON.parse(fs.readFileSync(intrinsicsPath, 'utf8').replace(/^﻿/, ''));
  cameraArgs = [
    '--ImageReader.camera_model', model,
    '--ImageReader.camera_params', params.join(','),
  ];
  console.log(`Using known intrinsics: ${model} [${params.join(', ')}]`);
}

const db = path.join(work, 'db.db');

// 1. find distinctive visual features in every photo
run('COLMAP: extract features', COLMAP, [
  'feature_extractor',
  '--database_path', db,
  '--image_path', imagesDir,
  '--ImageReader.single_camera', '1',
  ...cameraArgs,
  '--FeatureExtraction.use_gpu', '0',
]);

// 2. match features between every pair of photos
run('COLMAP: match features', COLMAP, [
  'exhaustive_matcher',
  '--database_path', db,
  '--FeatureMatching.use_gpu', '0',
]);

// 3. solve camera positions + sparse 3D points (structure-from-motion)
fs.mkdirSync(path.join(work, 'sparse'), { recursive: true });
const mapperArgs = [
  'mapper',
  '--database_path', db,
  '--image_path', imagesDir,
  '--output_path', path.join(work, 'sparse'),
];
const mapperStatus = run('COLMAP: solve camera poses (SfM)', COLMAP, mapperArgs, work, true);
if (mapperStatus !== 0 || !fs.existsSync(path.join(work, 'sparse', '0'))) {
  // difficult sets (low parallax / repetitive texture) need looser bootstrap
  run('COLMAP: SfM retry with relaxed init', COLMAP, [
    ...mapperArgs,
    '--Mapper.init_min_num_inliers', '50',
    '--Mapper.init_min_tri_angle', '4',
  ]);
}

// 4. undistort images for dense reconstruction
run('COLMAP: undistort images', COLMAP, [
  'image_undistorter',
  '--image_path', imagesDir,
  '--input_path', path.join(work, 'sparse', '0'),
  '--output_path', path.join(work, 'dense'),
  '--output_type', 'COLMAP',
]);

// 5-8. OpenMVS: densify → mesh → texture
run('OpenMVS: import scene', path.join(MVS, 'InterfaceCOLMAP.exe'), [
  '-i', path.join(work, 'dense'),
  '-o', 'scene.mvs',
  '--image-folder', path.join(work, 'dense', 'images'),
  '-w', work,
]);

run('OpenMVS: densify point cloud', path.join(MVS, 'DensifyPointCloud.exe'), [
  'scene.mvs',
  '-w', work,
  '--resolution-level', FAST ? '3' : '2',
  '--number-views-fuse', '2',
]);

run('OpenMVS: reconstruct mesh', path.join(MVS, 'ReconstructMesh.exe'), [
  'scene_dense.mvs',
  '-w', work,
]);

run('OpenMVS: texture mesh', path.join(MVS, 'TextureMesh.exe'), [
  'scene_dense.mvs',
  '--mesh-file', 'scene_dense_mesh.ply',
  '-w', work,
  '--export-type', 'obj',
]);

// 9. convert to GLB for the viewer
const obj = fs.readdirSync(work).find((f) => f.endsWith('.obj'));
if (!obj) {
  console.error('No OBJ produced by TextureMesh');
  process.exit(1);
}
console.log(`\n=== Convert ${obj} → GLB ===`);
const glb = await obj2gltf(path.join(work, obj), { binary: true, unlit: true });
fs.writeFileSync(outputGlb, Buffer.from(glb.buffer, glb.byteOffset, glb.byteLength));
console.log(`\nDONE in ${((Date.now() - t0) / 60000).toFixed(1)} min → ${outputGlb} (${(fs.statSync(outputGlb).size / 1e6).toFixed(1)} MB)`);
