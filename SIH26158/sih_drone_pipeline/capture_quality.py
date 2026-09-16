from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Iterable

import numpy as np


def _distance_m(left, right) -> float:
    latitude = math.radians((left.latitude + right.latitude) / 2.0)
    north = math.radians(right.latitude - left.latitude) * 6378137.0
    east = math.radians(right.longitude - left.longitude) * 6378137.0 * math.cos(latitude)
    up = right.altitude_m - left.altitude_m
    return float(math.sqrt(east * east + north * north + up * up))


def telemetry_quality(samples: list) -> dict:
    times = np.asarray([sample.time_s for sample in samples], dtype=float)
    gaps = np.diff(times)
    distances = np.asarray([
        _distance_m(left, right) for left, right in zip(samples, samples[1:])
    ], dtype=float)
    speeds = np.divide(distances, gaps, out=np.full_like(distances, np.nan), where=gaps > 0)
    positive_gaps = gaps[gaps > 0]
    median_gap = float(np.median(positive_gaps)) if len(positive_gaps) else None
    horizontal = [sample.horizontal_accuracy_m for sample in samples if sample.horizontal_accuracy_m is not None]
    vertical = [sample.vertical_accuracy_m for sample in samples if sample.vertical_accuracy_m is not None]
    maximum_gap = float(gaps.max()) if len(gaps) else 0.0
    speed_p95 = float(np.nanpercentile(speeds, 95)) if np.isfinite(speeds).any() else None
    jump_threshold = max(20.0, (speed_p95 or 0.0) * 3.0)
    jump_count = int(np.sum(speeds > jump_threshold)) if len(speeds) else 0
    return {
        "samples": len(samples),
        "duration_s": float(times[-1] - times[0]) if len(times) else 0.0,
        "duplicate_or_reversed_timestamps": int(np.sum(gaps <= 0)),
        "median_sample_gap_s": median_gap,
        "maximum_sample_gap_s": maximum_gap,
        "telemetry_gap_count": int(np.sum(gaps > max(2.0, 5 * median_gap))) if median_gap else 0,
        "speed_mps_median": float(np.nanmedian(speeds)) if np.isfinite(speeds).any() else None,
        "speed_mps_p95": speed_p95,
        "probable_position_jumps": jump_count,
        "horizontal_accuracy_m_median": float(np.median(horizontal)) if horizontal else None,
        "vertical_accuracy_m_median": float(np.median(vertical)) if vertical else None,
        "has_per_sample_accuracy": bool(horizontal or vertical),
    }


def analyze_selected_frames(
    images_dir: str | Path,
    frame_records: Iterable,
    telemetry_samples: list,
    output_path: str | Path | None = None,
    camera_calibration: dict | None = None,
) -> dict:
    """Create an auditable capture gate from the exact frames sent to SfM."""
    try:
        import cv2
    except ImportError as error:
        raise RuntimeError("Capture analysis requires opencv-python-headless") from error
    from .extract_keyframes import _parallax, _sharpness

    images_dir = Path(images_dir)
    records = list(frame_records)
    brightness, clipped_dark, clipped_bright, sharpness = [], [], [], []
    computed_flow, computed_tracks = [], []
    previous = None
    unreadable = 0
    for record in records:
        image = cv2.imread(str(images_dir / record.image_name), cv2.IMREAD_GRAYSCALE)
        if image is None:
            unreadable += 1
            continue
        small = cv2.resize(image, (160, 90), interpolation=cv2.INTER_AREA)
        brightness.append(float(np.mean(image)))
        clipped_dark.append(float(np.mean(image <= 5)))
        clipped_bright.append(float(np.mean(image >= 250)))
        sharpness.append(_sharpness(image))
        if previous is not None:
            flow, tracked = _parallax(previous, small)
            computed_flow.append(flow)
            computed_tracks.append(tracked)
        previous = small
    baselines = [float(record.baseline_m) for record in records[1:]]
    tracks = [float(record.tracked_fraction) for record in records[1:]] or computed_tracks
    flow = [float(record.parallax_px) for record in records[1:]] or computed_flow
    telemetry = telemetry_quality(telemetry_samples)
    median_sharpness = float(np.median(sharpness)) if sharpness else 0.0
    low_sharpness = int(sum(value < max(25.0, median_sharpness * 0.25) for value in sharpness))
    poor_exposure = int(sum(dark > 0.2 or bright > 0.2 for dark, bright in zip(clipped_dark, clipped_bright)))
    low_overlap = int(sum(value < 0.35 for value in tracks))
    near_duplicates = int(sum(value < 0.5 for value in flow))
    gates = {
        "all_frames_readable": unreadable == 0,
        "blurred_frame_fraction_at_most_10_percent": low_sharpness / max(len(sharpness), 1) <= 0.10,
        "poor_exposure_fraction_at_most_10_percent": poor_exposure / max(len(sharpness), 1) <= 0.10,
        "low_overlap_pair_fraction_at_most_10_percent": low_overlap / max(len(tracks), 1) <= 0.10,
        "near_duplicate_pair_fraction_at_most_25_percent": near_duplicates / max(len(flow), 1) <= 0.25,
        "telemetry_timestamps_monotonic": telemetry["duplicate_or_reversed_timestamps"] == 0,
        "no_large_telemetry_gaps": telemetry["telemetry_gap_count"] == 0,
        "no_probable_position_jumps": telemetry["probable_position_jumps"] == 0,
        "digital_stabilization_disabled": not bool(
            camera_calibration and camera_calibration.get("digital_stabilization") is True
        ),
        "rolling_shutter_motion_risk_acceptable": not bool(
            camera_calibration
            and (camera_calibration.get("rolling_shutter_readout_ms") or 0) > 10
            and (telemetry.get("speed_mps_p95") or 0) > 8
        ),
    }
    recommendations = []
    if not gates["blurred_frame_fraction_at_most_10_percent"]:
        recommendations.append("Use a faster shutter, slower flight, and calmer conditions.")
    if not gates["poor_exposure_fraction_at_most_10_percent"]:
        recommendations.append("Avoid clipped shadows/highlights and keep exposure consistent.")
    if not gates["low_overlap_pair_fraction_at_most_10_percent"]:
        recommendations.append("Increase overlap or sampling rate; target about 80% forward and 70% side overlap.")
    if not gates["near_duplicate_pair_fraction_at_most_25_percent"]:
        recommendations.append("Reduce redundant frames or increase the geometry baseline between anchors.")
    if not gates["no_large_telemetry_gaps"] or not gates["no_probable_position_jumps"]:
        recommendations.append("Repair telemetry timing/position outliers or use RTK/PPK before reconstruction.")
    if not gates["digital_stabilization_disabled"]:
        recommendations.append("Disable digital dewarping/stabilization or calibrate the stabilized video stream.")
    if not gates["rolling_shutter_motion_risk_acceptable"]:
        recommendations.append("Reduce flight speed/yaw rate or use a global-shutter camera.")
    result = {
        "ready": all(gates.values()),
        "frames_analyzed": len(sharpness),
        "unreadable_frames": unreadable,
        "metrics": {
            "sharpness_median": median_sharpness,
            "blurred_frame_fraction": low_sharpness / max(len(sharpness), 1),
            "brightness_median_0_255": float(np.median(brightness)) if brightness else None,
            "poor_exposure_fraction": poor_exposure / max(len(sharpness), 1),
            "tracked_fraction_median": float(np.median(tracks)) if tracks else None,
            "parallax_px_median_at_160x90": float(np.median(flow)) if flow else None,
            "baseline_m_median": float(np.median(baselines)) if baselines else None,
        },
        "telemetry": telemetry,
        "camera_calibration": camera_calibration,
        "gates": gates,
        "recommendations": recommendations,
        "note": "Capture quality is a pre-reconstruction risk screen, not an accuracy certificate.",
    }
    if output_path is not None:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result
