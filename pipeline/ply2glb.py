#!/usr/bin/env python
"""WalkThru post-process: raw Poisson mesh.ply -> cleaned GLB.

Poisson meshing always produces a huge low-density "bowl" hull around the
actual room (the solver closes the surface through space no camera saw).
This script crops that away, keeps the biggest connected piece, and writes
a GLB with vertex colors for the viewer / gltf-transform.

usage: python pipeline/ply2glb.py <input.ply> <output.glb> [lo_pct hi_pct]
"""
import sys
import numpy as np
import trimesh

args = [a for a in sys.argv[1:] if a != "--flip"]
FLIP = "--flip" in sys.argv  # COLMAP worlds are Y-down; flip 180° about X for Y-up viewers
inp, outp = args[0], args[1]
lo_pct = float(args[2]) if len(args) > 2 else 2.0
hi_pct = float(args[3]) if len(args) > 3 else 98.0

print(f"loading {inp} ...")
m = trimesh.load(inp, process=False)
print(f"  raw: {len(m.vertices):,} verts, {len(m.faces):,} faces")
print(f"  bounds:\n{np.round(m.bounds, 2)}")

# --- crop to the dense region (percentile bbox + margin) ------------------
lo = np.percentile(m.vertices, lo_pct, axis=0)
hi = np.percentile(m.vertices, hi_pct, axis=0)
margin = 0.15 * (hi - lo)
lo, hi = lo - margin, hi + margin
print(f"  crop box lo={np.round(lo,2)} hi={np.round(hi,2)}")

centroids = m.vertices[m.faces].mean(axis=1)
keep = np.all((centroids >= lo) & (centroids <= hi), axis=1)
m.update_faces(keep)
m.remove_unreferenced_vertices()
print(f"  after crop: {len(m.vertices):,} verts, {len(m.faces):,} faces")

# --- keep the largest connected component ---------------------------------
try:
    labels = trimesh.graph.connected_component_labels(m.face_adjacency, node_count=len(m.faces))
    counts = np.bincount(labels)
    big = counts.argmax()
    if counts[big] > 0.5 * len(m.faces) and len(counts) > 1:
        m.update_faces(labels == big)
        m.remove_unreferenced_vertices()
        print(f"  kept largest component: {len(m.faces):,} faces ({len(counts)} pieces)")
except BaseException as e:
    print("  component split skipped:", e)

if FLIP:
    print("flipping 180° about X (COLMAP Y-down -> viewer Y-up)")
    m.apply_transform(trimesh.transformations.rotation_matrix(np.pi, [1, 0, 0]))

print(f"exporting {outp} ...")
m.export(outp)
import os
print(f"done: {os.path.getsize(outp)/1e6:.1f} MB")
