# WalkThru — Playable 3D Property Tours

> **One-line pitch:** Instead of scrolling photos of a house, you open a link and
> walk a little character through a real, 3D-scanned version of the property —
> like a video game level, right in the browser, no app install.

This README is the **single source of truth** for the project. It is written so
that any person — or any future AI model — can read it top to bottom and continue
the work with zero prior context. Everything we have built, every dead end we
hit, and every decision we made is recorded here.

**Last updated:** 2026-07-19
**Working directory:** `D:\startupidea`
**Status:** Core prototype working. Own photogrammetry pipeline built; GPU
version running on Google Colab (see Section 10).

> 🔴 **CONTINUITY: if you are a new AI model or person picking this project up,
> read [`HANDOFF.md`](HANDOFF.md) FIRST.** It contains the live state at the
> last handoff, the exact next actions, the full roadmap, all known bugs with
> their fixes, and how to work with the project owner. This README is the full
> history; HANDOFF.md is the baton.

---

## 1. What this project is, and where it's going

### The idea
Real-estate listings today are flat photos or, at best, Matterport "click between
fixed points" tours. **WalkThru** replaces that with a controllable third-person
character who walks freely through a 3D model of the actual property. It's more
fun, more immersive, and especially valuable for:
- Younger buyers who expect game-like experiences.
- **Off-plan / under-construction properties** (builders selling homes that don't
  physically exist yet — there's nothing to photograph, so a 3D walkthrough is the
  *only* way to show it).
- Remote / overseas buyers who can't visit in person.

### The end goal (the full product)
1. An agent or builder **scans a property** with a phone (a video walk-through).
2. Our **pipeline** turns that footage into a walkable 3D model automatically.
3. The model is published to a **shareable link**.
4. A buyer opens the link and **walks through the home** with a character, on any
   phone or laptop, no install.

### Why we build our own pipeline (the strategic decision)
Commercial scan apps (Polycam, Luma) cost money per scan and lock us in. The core
science behind them is **open-source** (COLMAP, OpenMVS, Gaussian splatting
research). By owning the pipeline end-to-end we get: no per-scan cost, full control
over quality, and a genuine technical moat. This is the single most important
strategic choice in the project. See Section 6.

---

## 2. The core technical problem (and why it's solved)

The hardest part was never "show a 3D model in a browser." It was:

> **A 3D scan (LiDAR mesh or Gaussian splat) is just a visual surface. A character
> would fall straight through it. You need a separate COLLISION layer so the
> character stands on floors and is blocked by walls.**

**This is solved.** Our architecture uses two decoupled layers:

| Layer | What it is | How it's made |
|---|---|---|
| **Visual layer** | What you see — the house mesh / scan / (future) splat | Loaded from a GLB file, or generated procedurally for the demo |
| **Collision layer** | Invisible geometry the character physically interacts with | **Auto-generated** from the visual layer at load time |

The collision layer is built by merging every triangle of the visual model
(`StaticGeometryGenerator`), indexing them in a bounding-volume hierarchy
(`MeshBVH` from `three-mesh-bvh`), and representing the character as a **capsule**
that gets pushed out of any triangle it penetrates. One uniform rule handles
floors, walls, stairs, and furniture. **Verified working against a real
1,000,000-triangle scan** (see Section 4, Phase 2).

Because the two layers are decoupled, the visual layer can be *anything* —
procedural house, photogrammetry mesh, or later a Gaussian splat paired with a
mesh — and collision "just works" without changes.

---

## 3. How to run it (for the next person)

```bash
cd D:\startupidea
npm install
npm run dev
# open http://localhost:5173
```

**Controls:** `W A S D` / arrows to move, `Shift` run, `Space` jump, drag to orbit
camera, wheel to zoom, `C` to toggle the collision-layer view, `R` to reset,
`[` / `]` to shrink / grow the character.

The character auto-sizes to each scan (real-human 1.7 units in metric scans like
Scaniverse/Polycam exports; auto-shrinks only for unusually short models). Override
the standing height with `?char=<height-in-scan-units>` (e.g. `?char=1.7`), or tune
it live with `[` / `]`. Physics, camera distance, and walk/run/jump speeds all scale
with it.

**Load a real scan:** drag any `.glb` / `.gltf` onto the page, or use
`?model=<url>`. Bundled real example (a genuine photogrammetry scan of the hall of
Skokloster Castle, Sweden — CC0):
```
http://localhost:5173/?model=/scans/castle-clean.glb
```

**Run the photos→3D pipeline (our own Polycam):**
```bash
node pipeline/run.mjs <folder_of_photos> <output.glb> [--fast]
```

---

## 4. Everything we have done so far (chronological)

All work below happened on **2026-07-19**.

### Phase 0 — Groundwork
- Confirmed environment: Node v22, npm 11. Laptop is an **i7-13620H (16 cores),
  16 GB RAM, NO NVIDIA GPU** (Intel UHD only). This CPU-only constraint shapes
  every later decision (all reconstruction runs on CPU; future Gaussian-splat
  training will need a rented cloud GPU).

### Phase 1 — The collision core (the make-or-break prototype)
- Built a **Three.js** viewer (`src/main.js`) with the two-layer architecture.
- Created a **procedural demo house** (walls with real door/window openings, a
  13-step staircase, a second floor with a railed stairwell, furniture).
- Implemented **capsule-vs-BVH physics** with substeps, gravity, jumping, running,
  and a third-person orbit camera with wall-occlusion (camera pulls in so walls
  never block your view).
- **Verified** with automated in-browser tests: character spawns on the ground,
  lands on the upper floor when dropped, is ejected from inside walls, rests on
  stairs, and never falls through. All passed.

### Phase 2 — Loading REAL scanned houses
- Added a **scan-ingestion loader** (`loadScan` in `src/main.js`) that accepts any
  GLB/GLTF and makes it both the visual and collision source. It handles the messy
  reality of real scan files:
  - **Z-up detection** (many scanners export sideways) → auto-stands upright.
  - **Unit auto-rescale** (downloaded models come in random scales).
  - **Centering + floor-grounding.**
  - **Indexed/non-indexed normalization** (scans mix both; the merger needs
    uniformity).
  - **Draco decompression** support (decoders in `public/draco/`).
  - **Unlit materials** — photogrammetry textures already contain the room's real
    baked lighting; re-lighting them just makes everything dark. This one insight
    is what made real scans look real.
  - **Headroom-probed auto-spawn** — finds a walkable floor with clearance,
    preferring the lowest floor so a roofed scan doesn't spawn you on the roof.
- Downloaded a **real CC0 photogrammetry scan**: the hall of Skokloster Castle,
  from Meta AI's public `habitat-test-scenes.zip` (94.6 MB). Extracted
  `skokloster-castle.glb` (38 MB) → `public/scans/castle-clean.glb`.
- **Verified**: the character walks the real castle hall — standing on the real
  marble floor, blocked by real walls, 1,000,000 collision triangles handled fine.

### Phase 3 — Building OUR OWN photos→3D pipeline
- Installed the open-source toolchain into `tools/`:
  - **COLMAP 4.1.1** (no-CUDA build) — camera-pose estimation
    (structure-from-motion).
  - **OpenMVS 2.4.0** — dense point cloud, mesh, and texturing.
  - **obj2gltf** + **@gltf-transform/cli** — convert and compress to web GLB.
- Wrote the orchestrator **`pipeline/run.mjs`**: one command runs the whole chain
  (see Section 7 for exactly what each step does).
- Built a **synthetic test-photo generator**: added `renderFrom()` to the viewer so
  it can act as a virtual camera and "photograph" the loaded castle from chosen
  positions. Because these are renders of a *real* scan, they're honest stand-ins
  for phone photos — and we know the ground truth, so we can judge quality.

---

## 5. Every reconstruction attempt — what failed, why, and the fix

This is the honest log. Building a photogrammetry pipeline is an iterative tuning
process; each failure isolated one variable. **The pipeline plumbing has worked
end-to-end since v1 — the failures from v2 on were about CAPTURE QUALITY and one
resolution bug, not the code.**

### Bugs fixed inside the very first run (v1, `captures/test1`, 40 photos)
1. **BOM crash.** PowerShell wrote `intrinsics.json` with a UTF-8 BOM byte;
   `JSON.parse` rejected it. → Made the reader strip the BOM.
2. **Renamed CLI flags.** COLMAP 4.x renamed options: it's
   `--FeatureExtraction.use_gpu` / `--FeatureMatching.use_gpu`, not the older
   `--SiftExtraction.*` / `--SiftMatching.*`. → Updated the flags.
3. **Texture-stage filename mismatch.** OpenMVS `ReconstructMesh` writes
   `scene_dense_mesh.ply`, but `TextureMesh` was invoked expecting a `.mvs`. → Fixed
   to `TextureMesh scene_dense.mvs --mesh-file scene_dense_mesh.ply`.

### v1 — RESULT: pipeline completed, but the model looked bad
- **Capture:** 40 photos, two outward-facing rings from 2 fixed spots, 1600×1000.
- **Stage timings:** features 14s · matching 154s · **SfM 36s (registered all
  40/40 cameras at 0.20px reprojection error — excellent)** · densify 135s · mesh
  40s · texture (after fix) OK.
- **Output:** a 104.8 MB textured GLB, compressed to **539 KB** via gltf-transform
  (weld + simplify + Draco + WebP). Character **loaded it and walked on it**.
- **Problem:** geometry came out as a **crumpled crater** and textures were mostly
  **black**. Root cause: **bad capture coverage.** Two clustered outward rings give
  almost no parallax and never see most surfaces from multiple angles, so OpenMVS
  couldn't reconstruct clean surfaces or color them. Lesson: **capture pattern is
  everything.**

### v2 — `captures/test2`, 70 photos — SfM FAILED
- **Capture:** 14 positions spread across the floor × 5 directions each (72° steps).
- **Failure:** COLMAP reported *"No good initial image pair found."* Two causes:
  (a) 72° between shots = too little image overlap; (b) **unknown to us at the
  time, the browser pane had shrunk and the photos were saved at 402×378, not
  1600×1000.**

### v3 — `captures/test3`, 140 photos — SfM FAILED
- **Capture:** 14 positions × 10 directions (36° steps) — much denser angular
  coverage. **But still 402×378 (tiny), and each position was pure camera
  rotation** (no translation between a position's own 10 shots, which is
  geometrically degenerate for depth).
- **Failure:** same *"No good initial image pair."*

### v4 — `captures/test4`, 140 photos — SfM FAILED (both attempts)
- **Capture:** camera now **orbits a 0.55 m circle** at each position (so there's
  translation in every neighboring pair, like a person moving a phone while
  filming) + random jitter. **Still 402×378.**
- Added an automatic **relaxed-init fallback** to the pipeline (retries SfM with
  looser bootstrap thresholds).
- **Failure:** both default and relaxed SfM failed. **This forced the real
  diagnosis.**

### The root-cause discovery (why v2–v4 all failed)
Checked the actual pixel dimensions of every capture set:
```
test1: 1600 x 1000   (worked)
test2: 402 x 378     (failed)
test3: 402 x 378     (failed)
test4: 402 x 378     (failed)
```
The **browser preview pane had resized down to 402×378**, so every capture after v1
was tiny — and worse, the `intrinsics.json` still claimed a focal length of 960.49
(measured for the 1600-px image). We were **telling COLMAP the wrong camera optics
for the actual images**, which poisons the geometry solve. Fix: resized the pane
back to 1600×1000 and re-verified image dimensions before capturing.

### v5 — `captures/test5`, 140 photos — IN PROGRESS at time of writing
- **Capture:** all fixes combined — orbital motion (real parallax), 14 spread
  positions × 10 directions (dense overlap), **correct 1600×1000 resolution**, and
  intrinsics that actually match the images.
- **Status:** features done in 100s (10× longer than the broken tiny images —
  confirming full resolution), currently matching. Expect SfM to now succeed.

---

## 6. How we make this real (the roadmap)

### Immediate (finishing the pipeline proof)
- Get v5 to produce a clean, correctly-textured walkable model, proving our own
  pipeline matches what Polycam does on the same input.
- Fold the working capture recipe into a documented **capture protocol** (below).

### The capture protocol (hard-won — this is core IP)
Good reconstruction needs BOTH:
- **Spread-out camera positions** (wide baselines → parallax → correct geometry).
- **Dense angular overlap** between consecutive shots (~50%+ overlap, ≤36° apart).
- **Translation between every shot** (never pure rotation from one spot).
- **Consistent, known camera optics** (resolution and focal length must match the
  intrinsics you declare).

This is exactly why commercial apps have you **shoot a slow video** while walking —
video gives massive overlap and continuous translation for free. **Our real-world
ingestion should extract frames from a phone video** (roughly every 0.3 m of
movement) rather than ask for discrete photos.

### Near-term product
- **Video-frame extraction** front end (phone video → frames → `pipeline/run.mjs`).
- **Cloud GPU worker** for the pipeline (this laptop is CPU-only; a rented GPU
  makes reconstruction minutes instead of tens of minutes, and unlocks Gaussian
  splatting).
- **Hosting + shareable links** (upload a scan, get a URL).
- **Mobile touch controls** (on-screen joystick) for the viewer.

### Gaussian splatting (the photorealistic future)
Splats look stunning but contain **zero triangles**, so a character falls through
them. The plan (already designed): render the splat as the *visual* layer, and use
the **mesh our pipeline already produces** as the invisible *collision* layer —
the two-layer architecture we built makes this a clean add-on, not a rewrite.
Splat training needs a GPU (cloud).

---

## 7. What the pipeline actually does (step by step)

`pipeline/run.mjs <photos> <out.glb>` runs this chain. When you see it "running,"
this is what's happening:

1. **COLMAP feature_extractor** — finds distinctive visual keypoints in every
   photo. (~100s for 140 full-res photos.)
2. **COLMAP exhaustive_matcher** — compares every photo pair to find shared
   keypoints. (~2–3 min; this is often the "why is it just sitting there" stage —
   it IS working, comparing thousands of pairs.)
3. **COLMAP mapper (SfM)** — the critical solve: works out where each camera was in
   3D and a sparse point cloud. Fast (seconds) when it works; **fails loudly** with
   "no good initial image pair" when the capture is bad. Has an automatic
   relaxed-threshold retry.
4. **COLMAP image_undistorter** — removes lens distortion, preps for dense step.
5. **OpenMVS InterfaceCOLMAP** — imports the solved scene into OpenMVS.
6. **OpenMVS DensifyPointCloud** — computes depth for (nearly) every pixel → a
   dense point cloud. (Heaviest CPU stage, ~2 min.)
7. **OpenMVS ReconstructMesh** — fuses the dense cloud into a solid triangle mesh.
8. **OpenMVS TextureMesh** — projects the original photos back onto the mesh as
   color textures.
9. **obj2gltf + gltf-transform** — converts to a web GLB and compresses hard
   (a ~100 MB raw model becomes well under 1 MB).

The output GLB drops straight into the viewer (`?model=/scans/<file>.glb`) and the
collision layer is generated automatically — so it's immediately walkable.

---

## 8. Project layout

```
D:\startupidea\
  index.html              # viewer page + HUD
  src/main.js             # the whole viewer: rendering, physics, scan loader
  pipeline/
    run.mjs               # photos -> GLB orchestrator (COLMAP + OpenMVS + convert)
    obj2glb.mjs           # standalone OBJ -> GLB converter
  public/
    scans/                # GLB models (castle-clean.glb = real reference scan)
    draco/                # Draco decompression files for compressed GLBs
  captures/
    test1 .. test5/       # synthetic photo sets + intrinsics.json (see Section 5)
  tools/
    colmap/               # COLMAP 4.1.1 binaries
    openmvs/              # OpenMVS 2.4.0 binaries
  package.json
  README.md               # this file
```

---

## 9. Known gotchas (so nobody re-debugs them)

- **COLMAP 4.x** uses `--FeatureExtraction.*` / `--FeatureMatching.*` option names
  (older docs say `--SiftExtraction.*`).
- **OpenMVS TextureMesh** takes `scene_dense.mvs --mesh-file scene_dense_mesh.ply`;
  its console is silent (it logs to files) and `-h` exits with code 1 — that is NOT
  an error.
- **PowerShell** `Set-Content`/`>` can write a UTF-8 BOM that breaks `JSON.parse`.
  Use `[System.IO.File]::WriteAllText(...)` for JSON.
- **Downloaded/old GLBs** that GLTFLoader rejects can be repaired with
  `npx gltf-transform copy broken.glb clean.glb`.
- **Capture resolution must match `intrinsics.json`.** If the images aren't the
  size the focal length was measured for, SfM fails or produces garbage. Always
  verify pixel dimensions before running.
- **This machine has no GPU.** Everything is CPU. Budget minutes per run; move to a
  cloud GPU for production speed and for Gaussian splatting.

---

## 10. Google Colab GPU path (current direction, 2026-07-19 evening)

Local CPU runs proved the pipeline but are slow (the 140-photo v5 run took ~30 min
just to match features and was abandoned mid-densify when the session restarted).
Decision: **run reconstruction on Google Colab's free T4 GPU** — this is exactly
the "cloud GPU tier" from the product plan, at zero cost.

- Notebook: **`pipeline/WalkThru_Colab.ipynb`** — upload to Colab and run cell by
  cell. Cells are numbered, each ends with a ✅ line and prints the metrics needed
  for remote debugging.
- Upload **`walkthru_photos_test5.zip`** (project root, 45.5 MB — the 140 v5
  photos + intrinsics.json) to Google Drive at `MyDrive/WalkThru/`.
- The notebook uses COLMAP's own GPU dense stereo + Poisson meshing (vertex-colored
  mesh, no OpenMVS dependency) and exports `walkthru_colab.glb` back to Drive.
- The viewer's scan loader now supports **vertex-colored meshes** (Colab output has
  per-vertex color instead of a texture atlas).
- CELL 10 of the notebook is an optional diagnostic for adding OpenMVS texture
  atlassing on Colab later (the quality upgrade over vertex colors).

### ✅ RESULT (2026-07-19 night): END-TO-END SUCCESS
The Colab run completed. Numbers: **140/140 images registered, 0.331px mean
reprojection error, 4,179,965 fused points, 587 MB Poisson mesh**. The user
drove several cells by hand when open3d wouldn't install (it can't — condacolab
python conflicts; conversion belongs on the laptop) and downloaded `mesh.ply`
directly.

Local post-processing (new tool `pipeline/ply2glb.py`): percentile-crop of the
Poisson "bowl" hull, largest-component filter, **`--flip` for COLMAP's Y-down
convention** (without it the model loads upside-down — character stands on the
sky-side of the floor), then `gltf-transform optimize` → **477.7 MB → 385 KB**
(`public/scans/rebuilt-colab.glb`).

**Verified walkable:** character spawns inside the reconstructed hall, walks
10+ m across the floor with collision, steps onto reconstructed furniture.
Chairs, frames, tables, windows all recognizable. Known quality gaps for the
next iteration: washed-out vertex colors (likely sRGB-vs-linear on COLOR_0 +
no texture atlas yet) and melted fine detail (simplify-error 0.0005 was
aggressive; try 0.0001, and add the OpenMVS texture-atlas route).
