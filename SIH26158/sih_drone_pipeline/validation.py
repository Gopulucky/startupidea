from __future__ import annotations

import csv
import math
from pathlib import Path

import numpy as np
from pyproj import Transformer

from .telemetry import TelemetrySample, interpolate


def _camera_centers(images_txt: Path) -> dict[str, np.ndarray]:
    centers: dict[str, np.ndarray] = {}
    lines = [line for line in images_txt.read_text(encoding="utf-8").splitlines() if line and not line.startswith("#")]
    for line in lines:
        parts = line.split()
        if len(parts) < 10:
            continue
        try:
            int(parts[0])
            int(parts[8])
        except ValueError:
            continue
        qw, qx, qy, qz = map(float, parts[1:5])
        translation = np.array(list(map(float, parts[5:8])))
        rotation = np.array([
            [1 - 2 * (qy*qy + qz*qz), 2 * (qx*qy - qz*qw), 2 * (qx*qz + qy*qw)],
            [2 * (qx*qy + qz*qw), 1 - 2 * (qx*qx + qz*qz), 2 * (qy*qz - qx*qw)],
            [2 * (qx*qz - qy*qw), 2 * (qy*qz + qx*qw), 1 - 2 * (qx*qx + qy*qy)],
        ])
        centers[" ".join(parts[9:])] = -(rotation.T @ translation)
    return centers


def _to_enu(sample: TelemetrySample, origin: dict) -> np.ndarray:
    transform = Transformer.from_crs("EPSG:4979", "EPSG:4978", always_xy=True)
    x, y, z = transform.transform(sample.longitude, sample.latitude, sample.altitude_m)
    x0, y0, z0 = transform.transform(origin["longitude"], origin["latitude"], origin["altitude_m"])
    lat, lon = math.radians(origin["latitude"]), math.radians(origin["longitude"])
    rotation = np.array([
        [-math.sin(lon), math.cos(lon), 0],
        [-math.sin(lat)*math.cos(lon), -math.sin(lat)*math.sin(lon), math.cos(lat)],
        [math.cos(lat)*math.cos(lon), math.cos(lat)*math.sin(lon), math.sin(lat)],
    ])
    return rotation @ np.array([x - x0, y - y0, z - z0])


def gps_alignment_report(
    images_txt: str | Path,
    frames_csv: str | Path,
    telemetry: list[TelemetrySample],
    origin: dict,
) -> dict:
    centers = _camera_centers(Path(images_txt))
    residuals = []
    with Path(frames_csv).open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            if row["image_name"] not in centers:
                continue
            expected = _to_enu(interpolate(telemetry, float(row["time_s"])), origin)
            residuals.append(float(np.linalg.norm(centers[row["image_name"]] - expected)))
    if not residuals:
        return {"matched_cameras": 0, "warning": "No registered image names matched the frame manifest"}
    values = np.asarray(residuals)
    return {
        "matched_cameras": len(values),
        "gps_alignment_rmse_m": float(np.sqrt(np.mean(values**2))),
        "gps_alignment_median_m": float(np.median(values)),
        "gps_alignment_p95_m": float(np.percentile(values, 95)),
        "note": "GPS alignment residual is not an independent ground-control accuracy test.",
    }


def independent_distance_report(path: str | Path) -> dict:
    errors = []
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            measured = np.linalg.norm(
                np.array([float(row[f"x2_m"]), float(row[f"y2_m"]), float(row[f"z2_m"])])
                - np.array([float(row[f"x1_m"]), float(row[f"y1_m"]), float(row[f"z1_m"])])
            )
            errors.append(float(measured - float(row["known_distance_m"])))
    values = np.asarray(errors)
    return {
        "checks": len(values),
        "distance_rmse_m": float(np.sqrt(np.mean(values**2))) if len(values) else None,
        "maximum_absolute_error_m": float(np.max(np.abs(values))) if len(values) else None,
        "passes_one_metre_target": bool(len(values) and np.max(np.abs(values)) <= 1.0),
    }


def surveyed_checkpoint_report(path: str | Path) -> dict:
    """Compare reconstructed surface checkpoints with independent surveyed XYZ.

    Coordinates must already use the reconstruction's metric ENU frame. This
    intentionally performs no similarity alignment: allowing scale fitting here
    would hide the metric/georeferencing error the check is intended to expose.
    """
    errors = []
    identifiers = []
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            required = (
                "known_x_m", "known_y_m", "known_z_m",
                "reconstructed_x_m", "reconstructed_y_m", "reconstructed_z_m",
            )
            if any(row.get(field, "").strip() == "" for field in required):
                continue
            known = np.array([float(row[f"known_{axis}_m"]) for axis in "xyz"])
            reconstructed = np.array([float(row[f"reconstructed_{axis}_m"]) for axis in "xyz"])
            errors.append(float(np.linalg.norm(reconstructed - known)))
            identifiers.append(row.get("checkpoint_id") or str(len(identifiers) + 1))
    values = np.asarray(errors)
    return {
        "checks": len(values),
        "checkpoint_ids": identifiers,
        "rmse_3d_m": float(np.sqrt(np.mean(values**2))) if len(values) else None,
        "median_3d_error_m": float(np.median(values)) if len(values) else None,
        "maximum_3d_error_m": float(np.max(values)) if len(values) else None,
        "passes_one_metre_target": bool(len(values) >= 3 and np.max(values) <= 1.0),
        "minimum_checks_required": 3,
        "alignment_type": "none_direct_metric_frame_comparison",
        "note": "Surface/checkpoint accuracy evidence; blank unmeasured template rows are ignored.",
    }


def ground_truth_trajectory_report(
    images_txt: str | Path,
    frames_csv: str | Path,
    ground_truth_csv: str | Path,
) -> dict:
    """Compare camera centres with independent positions using rigid alignment only."""
    centers = _camera_centers(Path(images_txt))
    ground_truth = []
    with Path(ground_truth_csv).open(newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            ground_truth.append((float(row["time_s"]), np.array([float(row["x_m"]), float(row["y_m"]), float(row["z_m"])])))
    ground_truth.sort(key=lambda item: item[0])
    if len(ground_truth) < 3:
        return {"matched_cameras": 0, "warning": "Ground-truth trajectory has fewer than three positions"}

    def truth_at(time_s: float) -> np.ndarray:
        if time_s <= ground_truth[0][0]:
            return ground_truth[0][1]
        if time_s >= ground_truth[-1][0]:
            return ground_truth[-1][1]
        for index in range(1, len(ground_truth)):
            if ground_truth[index][0] >= time_s:
                t0, p0 = ground_truth[index - 1]
                t1, p1 = ground_truth[index]
                return p0 + (time_s - t0) / (t1 - t0) * (p1 - p0)
        return ground_truth[-1][1]

    estimated, expected = [], []
    with Path(frames_csv).open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            center = centers.get(row["image_name"])
            if center is not None:
                estimated.append(center)
                expected.append(truth_at(float(row["time_s"])))
    if len(estimated) < 3:
        return {"matched_cameras": len(estimated), "warning": "Fewer than three registered cameras matched ground truth"}
    source, target = np.asarray(estimated), np.asarray(expected)
    source_centered, target_centered = source - source.mean(axis=0), target - target.mean(axis=0)
    u, _, vt = np.linalg.svd(source_centered.T @ target_centered)
    rotation = u @ vt
    if np.linalg.det(rotation) < 0:
        u[:, -1] *= -1
        rotation = u @ vt
    aligned = source_centered @ rotation + target.mean(axis=0)
    errors = np.linalg.norm(aligned - target, axis=1)
    estimated_path = np.linalg.norm(np.diff(source, axis=0), axis=1).sum()
    truth_path = np.linalg.norm(np.diff(target, axis=0), axis=1).sum()
    scale_ratio = float(estimated_path / truth_path) if truth_path else None
    rmse = float(np.sqrt(np.mean(errors**2)))
    return {
        "matched_cameras": len(errors),
        "trajectory_rmse_m": rmse,
        "trajectory_median_error_m": float(np.median(errors)),
        "trajectory_p95_error_m": float(np.percentile(errors, 95)),
        "trajectory_scale_ratio": scale_ratio,
        "trajectory_scale_error_percent": abs(scale_ratio - 1.0) * 100 if scale_ratio is not None else None,
        "alignment_type": "rigid_rotation_translation_no_scale",
        "passes_one_metre_position_target": rmse <= 1.0,
        "note": "Independent relative camera-trajectory diagnostic; it does not prove absolute georeferencing or surface accuracy.",
    }
