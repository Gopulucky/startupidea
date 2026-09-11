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

Add `--validation-distances validation_distances.csv` for known-distance validation, or `--validation-checkpoints checkpoint_measurements.csv` for direct surveyed-vs-reconstructed XYZ checkpoint validation. At least three populated checkpoint rows are required to pass the one-metre surface target. The expected CSV columns are documented by each command's `--help` output.

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
time_s,latitude,longitude,altitude_m,yaw_deg,pitch_deg,roll_deg
0.000,28.613900,77.209000,122.4,90.0,-35.0,0.3
0.100,28.613901,77.209003,122.5,90.2,-35.1,0.2
```

Only the first four columns are mandatory. Times are seconds from the start of the video. DJI `.srt` telemetry is parsed directly when it contains timestamped latitude, longitude and altitude fields.

## Capture protocol

- Fly slowly and continuously; do not rotate from a stationary point.
- Maintain at least 70% forward overlap and 60% side overlap.
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

GPS alignment residual indicates whether reconstructed camera positions agree with flight telemetry, but it is not an independent accuracy test. For final judging, measure several known site distances or ground-control checkpoints and add them using the provided CSV template. The report only declares the one-metre surface target passed when these independent checks pass. Relative camera-trajectory accuracy is reported separately and never substitutes for surveyed surface evidence.

## Public verification dataset

### WHU aerial-video benchmark (recommended metric test)

WHU publishes native 4K/60-fps regular and irregular UAV videos, camera calibration, ground-truth camera poses, and surveyed GCP observations. Its large archives are hosted through a browser download service, so download and extract the three official packages from [the WHU dataset page](https://gpcv.whu.edu.cn/data/WHU_Areial_Video_Dataset.html) into one Drive directory, for example `MyDrive/WHU_Aerial_Video/`.

Prepare WHU data with `python -m sih_drone_pipeline.dataset --dataset whu ...`. The adapter discovers the selected sequence, normalizes its pose timestamps, converts its local metric camera centers to GPS references using the supplied geographic origin, and writes standardized trajectory, GCP, and checkpoint files. Confirm whether the release stores translations as camera centers or world-to-camera extrinsics; the `--pose-translation-convention` option records this choice in `dataset_manifest.json`.

The first reconstruction run verifies the native video, camera trajectory, products, and runtime. To prove surface accuracy, identify at least three reconstructed GCP centers in the metric viewer or CloudCompare, enter their XYZ values in `whu_checkpoint_measurements.csv`, then rerun with `--validation-checkpoints`. Blank template rows are ignored and camera-trajectory accuracy never substitutes for checkpoint accuracy.

The WHU capture is strongest for terrain, roads, rooftops, and vegetation. Only claim façade coverage if oblique frames visibly observe those façades; use a separate oblique development dataset and one final mixed-angle continuous flight for the complete SIH demonstration.

### Zurich mechanics test

The verification notebook uses the University of Zurich Urban Micro Aerial Vehicle sample:

- Official page: https://rpg.ifi.uzh.ch/zurichmavdataset.html
- Official sample archive: https://download.ifi.uzh.ch/rpg/AGZ_data/AGZ_subset.zip
- Sample size: under 200 MB; it is downloaded to `/content`, not committed to this repository.
- Contents used: time-synchronized 1920x1080 MAV images, onboard GPS and independent metric camera trajectory.
- Required academic citation: A. L. Majdik, C. Till and D. Scaramuzza, *The Zurich Urban Micro Aerial Vehicle Dataset*, IJRR, 2017.

The public sequence verifies software behavior, GPU utilization and camera-trajectory scale. Final surface-accuracy evidence must still come from surveyed distances or checkpoints in the SIH evaluation scene.

The public Blender demo uses Pix4D's Belleview Avenue dataset (38 geotagged 5344x4016 images, one residential grid flight). Pix4D permits the example datasets for training; a public or promotional demonstration must display `Courtesy of Pix4D / pix4d.com` linked to their site.

## Project structure

```text
README.md                            setup, usage, and architecture overview
requirements.txt                    Python runtime dependencies
notebooks/SIH26158_Colab.ipynb       the one primary execution interface
sih_drone_pipeline/                  main Python source code
sih_drone_pipeline/viewer/           metric browser viewer source
```
