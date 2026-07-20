#!/usr/bin/env node
// Standalone OBJ→GLB converter (also used as the pipeline's final stage).
import fs from 'node:fs';
import obj2gltf from 'obj2gltf';

const [objPath, outPath] = process.argv.slice(2);
if (!objPath || !outPath) {
  console.error('usage: node pipeline/obj2glb.mjs <input.obj> <output.glb>');
  process.exit(1);
}
console.log(`Converting ${objPath} → ${outPath} ...`);
const glb = await obj2gltf(objPath, { binary: true, unlit: true });
fs.writeFileSync(outPath, Buffer.from(glb.buffer, glb.byteOffset, glb.byteLength));
console.log(`Done: ${(fs.statSync(outPath).size / 1e6).toFixed(1)} MB`);
