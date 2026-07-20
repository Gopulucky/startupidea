# HANDOFF — read this first, then continue the mission

**To whichever model reads this:** you are taking over an active, momentum-critical
project. The human (Hardik, beginner developer, learning fast) and the previous
model built all of this together on 2026-07-19. Your job is to CONTINUE, not
restart. Read this file, then `README.md` (full project history), then act.
Do not re-derive, re-download, or rebuild anything that already works.

---

## 0. NEWEST (2026-07-20) — the room-video notebook is THE one to run now

`pipeline/WalkThru_Room_Video.ipynb` is the definitive, video-first, one-shot
notebook (built by `scratchpad/build_room_nb.py` via a generator for valid JSON;
14 cells). The user has a real room video in Drive and is running this. It bakes
in EVERY lesson: condacolab pin removal, libfaiss+openimageio, resumable cells +
Drive checkpoints, auto-find video in MyDrive/WalkThru/, ffmpeg frame extraction
with numpy-Laplacian BLUR FILTERING (verified on real jpgs: dropped 9/140), no
intrinsics.json (OPENCV self-calibration — correct for phone video), exhaustive
match ≤160 frames, relaxed-init SfM fallback, NO PoissonMeshing.trim, trimesh
(not open3d) crop+Y-flip+GLB export. Also checkpoints the sparse solve so
`WalkThru_Colab_Splats.ipynb` can reuse it. Waiting on the user's CELL 6 report.

## 1. LIVE STATE at handoff (2026-07-19 ~16:30)

The user is running our GPU reconstruction notebook
(`pipeline/WalkThru_Colab.ipynb`) in Google Colab on a free T4, cell by cell,
pasting outputs back for debugging. **This is working.** Status:

- Cells 1–6 PASSED. **SfM succeeded on Colab** (the stage that failed 4× locally).
- Cell 7 (`patch_match_stereo`, GPU dense depth) was RUNNING at handoff.
  Expect 5–15 min for 140 photos @1600×1000.
- Remaining: stereo_fusion (same cell), Cell 8 (poisson mesh), Cell 9 (GLB
  export → Drive + download).
- Input photos: `walkthru_photos_test5.zip` (in user's Drive under `WalkThru/`)
  = 140 synthetic photos of the Skokloster castle scan, 1600×1000,
  SIMPLE_PINHOLE f=960.49 cx=800 cy=500. Ground truth exists
  (`public/scans/castle-clean.glb`) so quality can be compared.

**Waiting on from the user:** Cell 6 model report (Registered images should be
~140/140, reprojection error < 1px), Cell 7 fused.ply size, then the final
`walkthru_colab.glb`.

**When the GLB arrives:** user drags it onto the viewer (`npm run dev` →
localhost:5173). Banner should say "Scan loaded — Nk collision triangles."
Character must walk inside it. Then capture screenshots (Section 5 tooling) and
update README Section 5 with the v5-Colab result.

### Colab bugs already fixed this session (do NOT re-debug)
1. **condacolab python pin mismatch** → `rm /usr/local/conda-meta/pinned`
   before mamba install (baked into Cell 3).
2. **conda colmap missing runtime libs** → install `libfaiss` and `openimageio`
   explicitly alongside colmap (baked into Cell 3).
3. **Colab VM recycling** wipes installs silently → Cells 3/5 now assert their
   tools exist and print recovery instructions.

### Likely NEXT bug (be ready)
COLMAP's world orientation is arbitrary — the rebuilt model may load **tilted**
(the viewer's Z-up heuristic only fixes 90° cases). If so: add
`colmap model_orientation_aligner` after the mapper in the notebook (Manhattan-
world alignment), or as a quick hack rotate the GLB in the viewer. Also, scale
is arbitrary (monocular ambiguity): if the character looks giant/tiny inside the
rebuilt model, that's why — see roadmap C3.

---

## 2. THE MISSION (unchanged)

Startup: **WalkThru** — real-estate listings as walkable 3D tours: a little
third-person character walks through a scanned property in the browser.
Strategy decided by the user: **own the entire photos→3D pipeline** (no
Polycam/Luma dependency, no per-scan fees). The collision core and viewer are
DONE and verified; the pipeline is the current frontier.

Money constraint: ₹0 budget. Everything free-tier (open-source tools, Colab
free GPU). User's laptop has NO GPU (i7-13620H, 16GB) — heavy compute goes to
Colab.

---

## 3. ROADMAP — what I would do next, in order

### Phase A — close the current loop (hours)
1. Get `walkthru_colab.glb` from the user, load in viewer, verify walkable.
2. Screenshot side-by-side with ground truth (`castle-clean.glb`).
3. Record results (README Section 5). If quality is poor: raise poisson trim
   (8–9) to cut floaters, or lower to 5–6 if holes; consider
   `--PatchMatchStereo.max_image_size 1200` if Cell 7 was slow/OOM.

### Phase B — FIRST REAL-WORLD SCAN (the big milestone)
The user films their own room with their phone (video, not photos):
1. Add a notebook cell: upload video → `ffmpeg -i video.mp4 -vf "fps=2" f_%04d.jpg`
   (2–3 fps; optionally drop blurry frames via variance-of-Laplacian).
2. No intrinsics.json for phone footage → notebook already handles intr=None;
   use `--ImageReader.camera_model OPENCV` + `single_camera 1`.
3. **Capture protocol to teach the user** (we PROVED these rules by failing):
   - MOVE while filming; never pivot in place (pure rotation = degenerate).
   - Slow, smooth, sideways-drifting arcs; 70%+ overlap between moments.
   - Close the loop (end where you started).
   - Good light, no mirrors/glass/blank walls as main subjects.
   - 1080p is plenty; lock exposure if the phone allows.
4. Run the same notebook on those frames → their own room, walkable. That's the
   product demo.

### Phase C — quality ladder (pick per need)
1. **Texture atlas** (photo-real instead of vertex colors): OpenMVS on Colab.
   Cell 10 in the notebook is a ready diagnostic (downloads OpenMVS Ubuntu
   binaries, runs ldd). Missing libs likely fixable with
   `LD_LIBRARY_PATH=/usr/local/lib` (conda) or apt. Flow:
   `InterfaceCOLMAP -i dense → DensifyPointCloud --resolution-level 2 →
   ReconstructMesh → TextureMesh --export-type obj` then obj2gltf (script
   exists: `pipeline/obj2glb.mjs`) + `gltf-transform optimize` (proven: 104MB→0.5MB).
2. **Mesh cleanup**: trimesh — keep largest component (Cell 9 does), fill small
   holes, `fast-simplification` if too heavy.
3. **True scale**: reconstruction scale is arbitrary. Fixes: (a) user measures one
   real distance (door height ~2.03m) and we scale the GLB; (b) later, phone AR
   capture (ARCore poses) gives metric scale for free. Add a `?scale=` override
   in the viewer loadScan (already supported via loadScan options — wire a URL param).
4. **Gravity alignment**: `model_orientation_aligner` (see Section 1).

### Phase D — Gaussian splatting (the "wow" visual tier)
T4 CAN train 3DGS (~30–60 min/scene). Path: reuse the SAME COLMAP sparse output
(cells 5–6) → train with **gsplat** (pip, most Colab-friendly) or Brush →
export .ply/.splat → render in viewer with `@mkkellogg/gaussian-splats-3d`
(three.js-compatible) → **collision still comes from the mesh pipeline**
(dual output: splat = visuals, poisson mesh = physics). The viewer's two-layer
architecture was designed for exactly this; loadScan grows a sibling loadSplat.

### Phase E — productize (when pipeline is proven on real rooms)
1. Deploy viewer: `npm run build` → static host (Vercel/Netlify/GitHub Pages,
   all free). Models: Cloudflare R2 free tier. Shareable links = the demo.
2. Mobile controls: virtual joystick (nipplejs) + drag-look; the viewer is
   already responsive.
3. Later: upload portal that runs the pipeline server-side (rented GPU per job)
   — the notebook IS the blueprint for that worker.

### Phase F — validation (do not skip; the user needs this nudge eventually)
Record a 30s screen capture of the castle walkthrough + (once done) their own
room. Show it to 3–5 real-estate agents or one off-plan builder. Off-plan
builders are the sharpest wedge: they have NOTHING to photograph, so a walkable
3D preview is their only option. The demo link is the pitch.

---

## 4. HOW TO WORK WITH THIS USER (important)

- Beginner-friendly ALWAYS: short sentences, explain any term of art once,
  analogies help ("photos in → 3D out", "Drive is permanent, the machine is not").
- They run Colab and paste outputs. Design every cell to end with a ✅ line and
  print the numbers you need. **Fail loudly** — silent `!command` failures
  already burned us once.
- Give time estimates for anything > 1 min, and narrate stage progress —
  silence confuses and worries them (they said so explicitly).
- Momentum over ceremony: make reasonable decisions yourself; ask only when the
  answer genuinely changes direction (they've approved: toolchain downloads,
  castle sample download, Colab pivot).
- Downloads require asking first (state file/source/size). Already approved and
  present: COLMAP+OpenMVS in `tools/`, castle scan, all npm deps.
- Update `README.md` (source of truth) and the memory files as things land.
  The attempt log (README §5) must stay honest — failures included.

---

## 5. TECHNICAL CROWN JEWELS (verified working — protect these)

- **Two-layer architecture** (`src/main.js`): visual world group + collision
  mesh auto-generated via StaticGeometryGenerator→MeshBVH; capsule character
  (feet-origin, segment y=0.35..1.35, r=0.35, the `newPosition.y -= 1.35`
  offset matters); 5 physics substeps; camera occlusion raycast.
- **`world.updateMatrixWorld(true)` BEFORE StaticGeometryGenerator** — without
  it every mesh merges at the origin (cost us the first debugging session).
- **loadScan()** normalizes any GLB: Z-up detect, unit rescale, center/ground,
  toNonIndexed uniformity, Draco (`public/draco/`), unlit materials
  (photogrammetry textures contain real light — NEVER relight), vertex-color
  support, headroom-probed spawn (lowest floor wins).
- **In-page test harness** `window.__walkthru`: probeDown(x,z), step(frames),
  renderFrom(...)→jpeg dataURL, snapshot(), setCam, worldBox, loadScan,
  exportGLB. Verify EVERYTHING with it before telling the user something works.
  Screenshot path: run `scratchpad/shot-server.mjs` (port 5999; recreate
  anywhere — 30 lines) and POST dataURLs to it, then Read the saved PNGs.
- **Local pipeline** `pipeline/run.mjs` (COLMAP 4.1.1 + OpenMVS 2.4 in `tools/`)
  works end-to-end on CPU — proven on the 40-photo v1 set (SfM: 40/40 @0.20px).
  Keep for small/offline jobs; Colab is the production path.
- **Capture protocol laws** (each learned by a failure): translation between
  every shot (never pivot in place); intrinsics must match actual pixel size
  (the 402×378 disaster); texture-rich viewpoints; overlap.

## 6. FILE MAP

| File | What |
|---|---|
| `README.md` | Full project story, attempt log §5, gotchas §9, Colab §10 |
| `HANDOFF.md` | This file |
| `src/main.js` | Entire viewer: physics, camera, loadScan, __walkthru hook |
| `pipeline/WalkThru_Colab.ipynb` | THE production pipeline (GPU, cell-by-cell) |
| `pipeline/run.mjs` | Local CPU pipeline (works, slow) |
| `pipeline/obj2glb.mjs` | OBJ→GLB converter (for OpenMVS texture route) |
| `public/scans/castle-clean.glb` | Ground-truth real scan (CC0), 1M tris |
| `captures/test1,test5/` | Good synthetic photo sets (+intrinsics.json) |
| `captures/test2,test3,test4/` | Broken sets (402×378) — kept as evidence, deletable |
| `walkthru_photos_test5.zip` | What the user uploaded to Drive |
| `tools/colmap`, `tools/openmvs` | Local binaries (Windows) |

---

## 7. UPDATE (2026-07-19 night) — Section 1's mission is COMPLETE ✅

The Colab run finished: 140/140 registered, 0.331px error, 4.18M fused points,
587 MB mesh.ply. Post-processed locally with the NEW tool `pipeline/ply2glb.py`
(bowl crop + largest component + **`--flip`** for COLMAP's Y-down world) +
`gltf-transform optimize` → `public/scans/rebuilt-colab.glb` (385 KB).
**Verified walkable in the viewer.** The predicted orientation bug happened
exactly as written above and `--flip` is the fix.

**The full loop — photos → own pipeline → walkable 3D house — is PROVEN.**

New next steps, in order:
1. **Real room scan** (Phase B below) — the user films their room, ffmpeg cell,
   same notebook. This is now the top priority.
2. Quality: vertex colors look washed out (suspect sRGB-vs-linear on COLOR_0 in
   the viewer, worth a 5-min check: set `material.vertexColors` texture...
   actually try `geometry.attributes.color.normalized` / convertSRGBToLinear on
   colors) and detail is over-simplified (retry gltf-transform with
   --simplify-error 0.0001; raw GLB kept at public/scans/rebuilt-colab-raw.glb
   — 478 MB, gitignore it / don't commit).
3. Texture atlas via OpenMVS (Phase C1) for the real quality jump.

**Continue from Section 7's next steps. Keep the momentum.**

---

## 8. UPDATE (2026-07-20) — video input, notebook v2, splat track built

**Forensics of the user's executed Colab run** (`WalkThru_Colab (2).ipynb` in
project root) produced hard lessons, now baked into the rewritten notebooks:
- `--PoissonMeshing.trim` CRASHES (RunSurfaceTrimmer abort) in the conda COLMAP
  build — never use it; crop with trimesh instead (the 587MB bowl mesh survived
  only because the crash came after the write).
- patch_match_stereo = 64.7 min on T4 @1600px/140 imgs (draft mode ~15 min).
- open3d can NEVER import on the condacolab kernel — trimesh only.
- intrinsics.json must not sit in the images dir (COLMAP reads it as an image).
- Colab wipes installs on VM recycle → all cells resumable + checkpoints to
  Drive (`WalkThru/runs/<RUN_NAME>/`: images, sparse, db, fused.ply, mesh glb).

**`pipeline/WalkThru_Colab.ipynb` v2 (mesh):** VIDEO input (ffmpeg → frames,
TARGET_FRAMES knob) or photo zip; sequential matcher for video; QUALITY
draft/full knob; separate resumable cells; in-Colab trimesh crop+FLIP+GLB
export (no more 587MB downloads — Cell 11 outputs a ready GLB).

**`pipeline/WalkThru_Colab_Splats.ipynb` (NEW):** trains 3D Gaussian Splats with
gsplat's simple_trainer on the SAME Drive checkpoint (fresh runtime, system
python — NEVER share a runtime with the condacolab mesh notebook). Output:
`<RUN_NAME>_splat.ply`. Untested until the user runs it — expect 1-2 debug
rounds (gsplat example CLI evolves).

**Viewer splat support (`src/main.js`):** `@mkkellogg/gaussian-splats-3d`
DropInViewer integrated. Modes: `?model=` (mesh), `?splat=` (view), 
`?splat=&collision=` (walk mesh + see splat, aligned via `lastFit` + baked
π-about-X flip). Drag-drop now also accepts .ply/.splat/.ksplat/.spz.
Mesh path regression-tested ✓ (castle 1M tris walks). Splat DATA path verified
(parse → 1178 splats → GPU textures → sort worker ran). **Final visual render
NOT yet confirmed** — the embedded browser pane suspends rAF so the sorter's
per-frame apply loop can't be observed there; verify in a real browser:
`http://localhost:5173/?splat=/scans/test-splat.ply` should show a colorful
hollow cube (synthetic test splat, regenerable via
`python pipeline/make_test_splat.py`). If it renders there, the pane was the
only issue; if not, debug `updateRenderIndexes` never firing (sort-worker
message → geometry.instanceCount stays 0).
