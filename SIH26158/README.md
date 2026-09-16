# SIH26158 - Single-Pass Drone Video to Accurate 3D Model

This repository is a Colab-first implementation of SIH problem statement 26158. It converts one continuous drone video plus mandatory GPS/flight telemetry into a georeferenced dense point cloud, 3D mesh, GIS products, a browser-viewable model, and a machine-readable performance report.

## Start here

You only need **one notebook** for a normal run:

> `notebooks/SIH26158_Colab.ipynb`

That notebook is the user interface. The actual implementation lives in `sih_drone_pipeline/`; do not copy code out of the notebook. Optional dataset notebooks are local experiment material and are not part of the core Git repository.

The command entry point is `sih_drone_pipeline/__main__.py`, which dispatches through `cli.py`; the reconstruction workflow itself is orchestrated by `colmap_pipeline.py`.

To inspect the local command interface:

```bash
python -m sih_drone_pipeline --help
```

## Inputs

- Drone video: 1080p or 4K, one continuous flight path.
- Telemetry: DJI-style `.srt` or CSV containing `time_s, latitude, longitude, altitude_m`.
- Optional independent distance checks for proving the one-metre accuracy target.

Camera intrinsics, IMU, barometric altitude, and RTK/PPK are useful but are not required by this implementation.

## Colab workflow

1. Upload this cleaned project folder to `MyDrive/SIH26158/`.
2. Upload the video and matching `.srt`/`.csv` telemetry to `MyDrive/SIH26158/input/`.
3. Open `notebooks/SIH26158_Colab.ipynb` in Google Colab.
4. Select a T4 GPU runtime and execute cells in order. The Conda installation cell intentionally restarts the runtime once.
5. Edit only the input filenames in the configuration cell.
6. Run the pipeline cell. Final files are written to `MyDrive/SIH26158/outputs/<run-name>/`.

Optional dataset demonstrations and verification material are kept locally but are intentionally excluded from the core-code Git repository.

When `--target-frames` is omitted, selection is duration-aware at one frame per second, capped at 600 frames for `draft` and 1200 for `full`. Use `--sample-fps 2` for fast/low flights or set an explicit frame budget for quick debugging. `full` enables geometric dense consistency and tries Poisson meshing with an automatic Delaunay fallback. Processing time still depends strongly on scene length, motion and hardware; the verifier reports the 15-minute target instead of assuming it passes.

## Pipeline

```text
video + timed GPS telemetry
        |
sharp ordered keyframes + per-frame GPS
        |
COLMAP sequential SfM
        |
GPS alignment in local East-North-Up metres
        |
GPU dense stereo + fusion
        |
filtered point cloud + cleaned mesh + optional texture atlas
        |
PLY / LAS / GLB / OBJ / GeoTIFF DSM + reports
```

The one-command interface used by the notebook is:

```bash
python -m sih_drone_pipeline run \
  --video /content/input/flight.mp4 \
  --telemetry /content/input/flight.srt \
  --workspace /content/sih_work \
  --output /content/drive/MyDrive/SIH26158/outputs/demo \
  --target-frames 120 \
  --quality draft \
  --ai-mask-dynamic
```

For the optimized, reproducible path use `--profile verified-fast`. It enables geometry-aware
keyframes, forward-only decoding, robust multi-model GPS pose-prior mapping, the accepted reduced
bundle-adjustment schedule, adaptive dense stride two with `1088 / 4 / 15 / 10` PatchMatch settings,
and Delaunay `max_proj_dist=20`. It deliberately does not use the rejected 96/92-reference cap,
1024-pixel dense images, fewer iterations/samples/sources, or `window_step=2`. `--profile
high-detail` retains more dense evidence when runtime is not the primary constraint. Every run
writes `capture_quality.json`; add `--strict-capture-quality` to stop before COLMAP when blur,
exposure, overlap, or telemetry gates fail.

Capture can also be screened without running reconstruction:

```bash
python -m sih_drone_pipeline assess \
  --video flight.mp4 --telemetry flight.csv \
  --output capture_quality.json
```

Current COLMAP builds can also be screened with learned local features and the newer surface
mesher, without changing the protected defaults:

```bash
python -m sih_drone_pipeline run \
  --video flight.mp4 --telemetry flight.csv --output outputs/learned_frontend \
  --target-frames 253 --max-width 1920 \
  --feature-type aliked-n16rot --feature-matcher lightglue \
  --mesher advancing-front
```

ALIKED and LightGlue require an ONNX-enabled COLMAP build; advancing-front meshing requires CGAL.
`preflight` reports these capabilities before a long run. SIFT plus brute-force matching and the
profile-selected Delaunay/Poisson path remain the defaults. Treat these switches as controlled A/B
candidates and promote them only through the fixed-workload and independent-evidence gates below.

Add `--validation-distances validation_distances.csv` for known-distance validation, or `--validation-checkpoints checkpoint_measurements.csv` for direct surveyed-vs-reconstructed XYZ checkpoint validation. At least three populated checkpoint rows are required for this project's minimal one-metre evidence gate; this is not a standards-compliance claim. The expected CSV columns are documented by each command's `--help` output.

### Camera calibration and positioning uncertainty

Normalized telemetry CSV may additionally contain `horizontal_accuracy_m`,
`vertical_accuracy_m`, `position_source` (for example `RTK_FIXED`, `RTK_FLOAT`, `PPK`, or
`GPS`), and `altitude_datum`. Pose-prior mapping automatically uses the median supplied uncertainty. It can be overridden
with `--gps-prior-horizontal-std-m` and `--gps-prior-vertical-std-m`.
Use `--telemetry-altitude-offset-m` only for a known geoid/vertical-datum correction and record the
datum in the CSV; the software cannot infer a missing datum safely.

Use `--camera-calibration camera.json` to supply stable intrinsics instead of relying only on
self-calibration:

```json
{
  "model": "OPENCV",
  "params": [1450.2, 1448.9, 960.0, 540.0, -0.08, 0.02, 0.0, 0.0],
  "width": 1920,
  "height": 1080,
  "fixed_intrinsics": true,
  "rolling_shutter_readout_ms": 12.4,
  "digital_stabilization": false,
  "source": "checkerboard calibration 2026-09-13"
}
```

### GCP correction versus independent checkpoints

`--gcp-control-points gcp.csv` robustly fits a 3D similarity correction before point-cloud, mesh,
LAS, GLB, OBJ, and DSM export. These control points influence the result and therefore cannot prove
accuracy. Keep at least three different surveyed points in `--validation-checkpoints` as a holdout
test.

GCP rows require `control_id,reconstructed_x_m,reconstructed_y_m,reconstructed_z_m` plus either
`known_x_m,known_y_m,known_z_m` in the reconstruction ENU frame or
`known_latitude,known_longitude,known_altitude_m`. Outliers are rejected using
`--gcp-inlier-threshold-m`. A 25% scale-change safety gate rejects likely coordinate-frame or
point-labelling mistakes; adjust it deliberately with `--gcp-max-scale-change-percent` only when
the initial model scale is known to be worse.

### Post-run accuracy validation

Independent checkpoints can be added to a completed reconstruction without rerunning COLMAP or
dense stereo:

```bash
python -m sih_drone_pipeline validate-checkpoints \
  --output outputs/demo \
  --checkpoints checkpoint_measurements.csv
```

Checkpoint validation performs a direct comparison in the existing metric coordinate frame; it
does not align or rescale the measurements. The report includes RMSE for X, Y, Z, horizontal,
vertical and 3D error, East/North/Up bias, per-checkpoint 3D error, and mean, median, population
standard deviation, minimum, maximum and p95 distributions. CSV rows may also include the optional
`x_uncertainty_m`, `y_uncertainty_m`, `z_uncertainty_m`, `horizontal_uncertainty_m`, and
`vertical_uncertainty_m` fields. Those uncertainty values are summarized exactly as supplied; the
software does not infer or convert their confidence level.

Three independent checkpoints are only this project's minimum evidence gate for the one-metre
target. The separate `asprs_checkpoint_count_status` requires at least 30 checkpoints, but its
scope is explicitly `checkpoint_count_only`. A passing count is not full ASPRS compliance:
checkpoint distribution, survey quality, confidence level, product class and the other standard
requirements must still be verified separately.

When an independently surveyed/reference point cloud or mesh is available, evaluate the entire
dense surface with:

```bash
python -m sih_drone_pipeline validate-geometry \
  --output outputs/demo \
  --reference reference_surface.ply \
  --reconstruction outputs/demo/point_cloud.ply \
  --threshold-m 0.10 \
  --threshold-m 0.25 \
  --max-samples 100000
```

`--reconstruction` is optional and defaults to `OUTPUT/point_cloud.ply`; `--threshold-m` may be
repeated. The command records bidirectional distance summaries
plus precision, completeness/recall and F1 at every requested distance threshold. Both inputs must
already share the same metric coordinate frame: no registration, similarity alignment or scale
correction is performed during validation. Their SHA-256 identities and the complete sampling
protocol are stored for reproducibility. A byte-identical reconstruction/reference pair is retained
as a diagnostic but rejected as independent benchmark evidence. The project's conservative
one-metre dense gate requires the maximum sampled distance in both directions to be at most 1 m;
this is a project acceptance rule, not a claim that a universal dense-reconstruction standard uses
that threshold.

The notebooks also run these verification commands automatically:

```bash
python -m sih_drone_pipeline preflight --video flight.mp4 --telemetry flight.srt \
  --workspace /content/sih_work --output preflight.json
python -m sih_drone_pipeline verify --output /path/to/completed/output
```

`preflight` checks CUDA COLMAP, NVIDIA visibility, video metadata, telemetry coverage and free disk space. `verify` separately reports structural artifact validity, quality thresholds, and `production_ready`. A readable file is not treated as proof of map quality.

## Outputs

| File | Purpose |
|---|---|
| `point_cloud.ply` | Coloured dense point cloud |
| `mesh.ply` | Full mesh |
| `textured/mesh.ply` + `texture.png` | COLMAP UV mesh and texture atlas when supported |
| `point_cloud.las` | UTM GIS point cloud with CRS metadata |
| `dsm.tif` | UTM GeoTIFF digital surface model |
| `confidence.tif` | UTM point-density confidence proxy from 0 to 1 |
| `confidence_summary.json` | Coverage and high-confidence-area statistics |
| `capture_quality.json` | Blur, exposure, overlap, telemetry and GPS-jump gates |
| `gcp_alignment.json` | Robust control-point fit, residuals and scale change when GCPs are used |
| `model.glb` | Browser-ready 3D model in local metric ENU coordinates |
| `model.obj` | Interoperable mesh |
| `georeference.json` | ENU origin and projected CRS |
| `run_report.json` | Stage timings, registration, reprojection and validation metrics |
| `viewer_metadata.json` | Compact metadata for the web viewer |
| `logs/*.log` | Full console output for every COLMAP stage |
| `gpu_usage.csv` | NVIDIA utilization, VRAM, temperature and power sampled every second |
| `gpu_usage.summary.json` | Mean and maximum GPU statistics |
| `preflight.json` | CUDA, COLMAP, video, telemetry coverage and disk checks |
| `verification_report.json` | Pass/fail checks plus GPU utilization/VRAM statistics for each stage |

FBX is intentionally not generated because it would add a proprietary conversion dependency; OBJ, PLY and GLB cover mesh interoperability while LAS and GeoTIFF cover GIS use.

## Telemetry CSV

```csv
time_s,latitude,longitude,altitude_m,yaw_deg,pitch_deg,roll_deg,horizontal_accuracy_m,vertical_accuracy_m,position_source,altitude_datum
0.000,28.613900,77.209000,122.4,90.0,-35.0,0.3,0.03,0.06,RTK_FIXED,WGS84_ELLIPSOID
0.100,28.613901,77.209003,122.5,90.2,-35.1,0.2,0.03,0.06,RTK_FIXED,WGS84_ELLIPSOID
```

Only the first four columns are mandatory. Times are seconds from the start of the video. DJI `.srt` telemetry is parsed directly when it contains timestamped latitude, longitude and altitude fields.

## Capture protocol

- Fly slowly and continuously; do not rotate from a stationary point.
- Target about 80% forward overlap and 70% side overlap; increase it for vegetation or complex terrain.
- Keep the camera angle stable and avoid sudden yaw.
- Prefer daylight without strong moving shadows.
- Include oblique views of facades; a purely nadir path cannot recover vertical surfaces.
- Keep GPS recording and video recording synchronized from the same flight.
- Avoid moving vehicles and crowds where possible.

The Colab notebook enables AI dynamic-object segmentation by default. It masks people, vehicles, and animals before feature extraction, directly addressing one of the problem statement's key challenges.

Surfaces never visible in the single pass cannot be measured reliably. The system reports observable reconstruction quality rather than silently inventing geometry.

Before export, isolated dense-cloud points are rejected with a robust local-neighbour test. Mesh faces whose longest edge is an extreme outlier are removed before disconnected-fragment cleanup and COLMAP texturing. The report preserves the removed point/face counts; this prevents the large bridging triangles seen when Delaunay closes unsupported gaps.

## Viewer

```bash
cd sih_drone_pipeline/viewer
npm install
npm run dev
```

Open or drop `model.glb`/`mesh.ply`, then open `viewer_metadata.json`. Shift-click two surface points to measure. The viewer preserves model scale and reports local ENU coordinates; it never auto-rescales geometry.

## Accuracy evidence

GPS alignment residual indicates whether reconstructed camera positions agree with flight telemetry, but it is not an independent accuracy test. For final judging, measure several known site distances or ground-control checkpoints and add them using the provided CSV template. The report only declares the one-metre surface target passed when these independent checks pass. Three checkpoints satisfy only the project's minimal evidence gate; the separate 30-checkpoint status covers count alone and does not assert complete ASPRS compliance. Relative camera-trajectory accuracy is reported separately and never substitutes for surveyed surface evidence.

## Public verification dataset

### WHU aerial-video benchmark (recommended metric test)

WHU publishes native 4K/60-fps regular and irregular UAV videos, camera calibration, ground-truth camera poses, and surveyed GCP observations. Its large archives are hosted through a browser download service, so download and extract the three official packages from [the WHU dataset page](https://gpcv.whu.edu.cn/data/WHU_Areial_Video_Dataset.html) into one Drive directory, for example `MyDrive/WHU_Aerial_Video/`.

Prepare WHU data with `python -m sih_drone_pipeline.dataset --dataset whu ...`. The adapter discovers the selected sequence, normalizes its pose timestamps, converts its local metric camera centers to GPS references using the supplied geographic origin, and writes standardized trajectory, GCP, and checkpoint files. Confirm whether the release stores translations as camera centers or world-to-camera extrinsics; the `--pose-translation-convention` option records this choice in `dataset_manifest.json`.

The first reconstruction run verifies the native video, camera trajectory, products, and runtime. For the project's minimal surface-accuracy evidence gate, identify at least three reconstructed GCP centers in the metric viewer or CloudCompare, enter their XYZ values in `whu_checkpoint_measurements.csv`, then rerun with `--validation-checkpoints`. Use at least 30 properly distributed checkpoints before treating the count status as ASPRS-style count evidence, and still verify the rest of the standard separately. Blank template rows are ignored and camera-trajectory accuracy never substitutes for checkpoint accuracy.

The WHU capture is strongest for terrain, roads, rooftops, and vegetation. Only claim façade coverage if oblique frames visibly observe those façades; use a separate oblique development dataset and one final mixed-angle continuous flight for the complete SIH demonstration.

### Zurich mechanics test

The verification notebook uses the University of Zurich Urban Micro Aerial Vehicle sample:

- Official page: https://rpg.ifi.uzh.ch/zurichmavdataset.html
- Official sample archive: https://download.ifi.uzh.ch/rpg/AGZ_data/AGZ_subset.zip
- Sample size: under 200 MB; it is downloaded to `/content`, not committed to this repository.
- Contents used: time-synchronized 1920x1080 MAV images, onboard GPS and independent metric camera trajectory.
- Required academic citation: A. L. Majdik, C. Till and D. Scaramuzza, *The Zurich Urban Micro Aerial Vehicle Dataset*, IJRR, 2017.

The public sequence verifies software behavior, GPU utilization and camera-trajectory scale. Final surface-accuracy evidence must still come from surveyed distances or checkpoints in the SIH evaluation scene.

### Controlled HF geometry A/B experiment

`notebooks/optional/SIH26158_HF_Drone_Colab.ipynb` runs three configurations on the same native
DJI video: 251.5 seconds (approximately 4.2 minutes), with a full fixed 253-frame, 1920-pixel
workload used to investigate the earlier approximately 80-minute runtime:

1. `hf_before_uniform_253`: sharpness-only keyframes, standard mapper, every dense reference.
2. `hf_after_geometry_253`: GPS-baseline/optical-flow keyframes, GPS pose-prior mapper, every dense reference.
3. `hf_after_geometry_fast_253`: the same geometry pipeline, but every second dense reference.

The first comparison isolates geometry selection and pose priors; the second measures the
dense-runtime/coverage trade-off. The notebook writes `comparison_quality.json/.md`,
`runtime_vs_historical_80_75.csv`, and
`comparison_fast.json/.md`. HF Drone has no surveyed surface truth, so these reports compare
runtime, registration, reprojection, GPS agreement, point count, DSM coverage and mesh quality
without mislabeling any of them as absolute surface accuracy.

The protected reference is the accepted robust run: the complete 251.5-second video, all 253
selected frames at 1920-pixel processing width, and a 26.92-minute runtime. The 92-frame,
15.65-minute and 66-frame, 10.3-minute trials are reduced-workload diagnostics, not comparable
winners, because they change the selected-frame count and manifest. Reaching the under-15-minute
goal on the protected workload still requires about a 44.3% runtime reduction, or approximately a
1.8x speedup, while retaining the fixed workload and independent accuracy evidence.

The five externally saved experiment notebooks supplied with this project document the path through
78.11, 52.66, 42.61 and 34.62 minutes. They do not themselves contain the 26.92-minute output; that
later result is identified by the subsequent sparse-BA/dense experiment lineage as
`full253_a3_robust_multimodel_1088`. Keep that run's `run_report.json`, `frames.csv`, verification
report and independent surface evidence together when archiving the protected baseline.
The cell-by-cell provenance and file hashes are recorded in
[`docs/notebook_experiment_audit.md`](docs/notebook_experiment_audit.md).

Completed output directories can also be compared independently:

```bash
python -m sih_drone_pipeline compare \
  --before outputs/hf_before_uniform_253 \
  --after outputs/hf_after_geometry_253 \
  --output outputs/hf_geometry_comparison.json
```

For two or more systems or configurations, normalize each result into this pipeline's report schema
and create a ranked JSON/CSV/Markdown benchmark:

```bash
python -m sih_drone_pipeline benchmark \
  --run-entry baseline=outputs/baseline \
  --run-entry ours=outputs/ours \
  --output outputs/benchmark.json
```

The first `--run-entry` is the protected reference. A candidate is eligible only when it is
production-ready and passes every fair-comparison gate: consistent metadata; the same video
identity and duration; the same target and selected-frame counts; the exact same selected-frame
manifest hash; the same frame resolution; and valid, matching independent surface-evidence sets.
Missing metadata or missing independent evidence fails closed. Only then does the benchmark select
the fastest eligible run. Dense reference geometry counts as valid evidence only when both
directional distance summaries and non-empty threshold metrics are present; dense comparisons also
lock the reference identity/hash and the evaluation thresholds, sample cap, seed and recorded
protocol. The `compare` command applies these same workload/evidence gates in addition to its
runtime and reconstruction-quality guardrails, so a shorter or lower-resolution run cannot replace
the baseline merely because it finishes sooner.

The separate follow-up notebook
`notebooks/optional/SIH26158_HF_Drone_Optimization_Colab.ipynb` compares the completed
52.62-minute geometry-fast result against an adaptive-anchor candidate. It limits dense source
views to ten, uses 1024-pixel/four-iteration PatchMatch, and requests GPU bundle adjustment when
supported. The generated decision is accepted only when runtime improves and every structural
quality guardrail passes.

The separate frontend/sparse follow-up notebook
`notebooks/optional/SIH26158_HF_Drone_Frontend_Sparse_AB_Colab.ipynb` tests a forward-only
candidate decoder against the exact accepted 253-frame manifest, then screens calibrated global
SfM before permitting a full 1088 dense reconstruction. This prevents a failed sparse experiment
from consuming dense-processing time and applies stronger 95% point-count and DSM-coverage gates
to the final candidate.

The subsequent pose-prior BA notebook
`notebooks/optional/SIH26158_HF_Drone_Sparse_BA_AB_Colab.ipynb` keeps the accepted sequential
frontend and incremental pose-prior geometry. It reuses one controlled feature database for
mapper-only screens of sparse-color removal, video-oriented global-BA scheduling,
reduced-landmark BA, and moderate iteration caps. Only a candidate that is at least 20% faster in
the mapper-only screen and passes all camera-quality gates may run the full dense pipeline.
Multi-model recovery remains enabled for fresh runs because a single-model experiment retained a
weak two-image initialization.

The dense/meshing follow-up notebook
`notebooks/optional/SIH26158_HF_Drone_Dense_Delaunay_AB_Colab.ipynb` uses the accepted
26.92-minute robust result as a read-only reference. It prepares one validated sparse and
undistorted restart cache, then screens PatchMatch iterations, samples, source-view count, exact
dense-reference count, and window step independently. The winning fused cloud is hashed and reused
unchanged for Delaunay `max_proj_dist` trials. Candidates are compared using actual bidirectional
cloud distance, a common DSM grid, and sampled mesh-surface distance rather than counts alone. Only
a repeated winner that passes the quality gates may receive one fresh end-to-end run.

The public Blender demo uses Pix4D's Belleview Avenue dataset (38 geotagged 5344x4016 images, one residential grid flight). Pix4D permits the example datasets for training; a public or promotional demonstration must display `Courtesy of Pix4D / pix4d.com` linked to their site.

## Project structure

```text
README.md                            setup, usage, and architecture overview
requirements.txt                    Python runtime dependencies
notebooks/SIH26158_Colab.ipynb       the one primary execution interface
sih_drone_pipeline/                  main Python source code
sih_drone_pipeline/viewer/           metric browser viewer source
```
