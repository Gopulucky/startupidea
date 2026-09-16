from __future__ import annotations

import csv
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

import cv2
import numpy as np


@dataclass(frozen=True)
class FrameRecord:
    image_name: str
    source_frame: int
    time_s: float
    sharpness: float
    motion_score: float
    baseline_m: float = 0.0
    parallax_px: float = 0.0
    tracked_fraction: float = 0.0
    geometry_score: float = 0.0


def _sharpness(gray: np.ndarray) -> float:
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _distance_m(left, right) -> float:
    """Approximate short WGS84 distances, including altitude, in metres."""
    latitude = math.radians((left.latitude + right.latitude) / 2.0)
    north = math.radians(right.latitude - left.latitude) * 6378137.0
    east = math.radians(right.longitude - left.longitude) * 6378137.0 * math.cos(latitude)
    up = right.altitude_m - left.altitude_m
    return float(math.sqrt(east * east + north * north + up * up))


def _trajectory_length_m(samples: Sequence) -> float:
    # Consumer flight logs can be 10 Hz or faster. Summing every jittery GPS
    # sample greatly exaggerates path length, so estimate it at ~1 Hz.
    coarse = [samples[0]]
    for sample in samples[1:]:
        if sample.time_s - coarse[-1].time_s >= 1.0:
            coarse.append(sample)
    if coarse[-1] is not samples[-1]:
        coarse.append(samples[-1])
    return sum(_distance_m(left, right) for left, right in zip(coarse, coarse[1:]))


def _parallax(previous: np.ndarray | None, current: np.ndarray) -> tuple[float, float]:
    """Return median tracked-feature displacement and surviving track fraction."""
    if previous is None:
        return 0.0, 1.0
    points = cv2.goodFeaturesToTrack(
        previous, maxCorners=160, qualityLevel=0.01, minDistance=5, blockSize=5
    )
    if points is None or len(points) < 8:
        return 0.0, 0.0
    tracked, status, _ = cv2.calcOpticalFlowPyrLK(
        previous,
        current,
        points,
        None,
        winSize=(21, 21),
        maxLevel=3,
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 20, 0.03),
    )
    if tracked is None or status is None:
        return 0.0, 0.0
    valid = status.reshape(-1).astype(bool)
    if valid.sum() < 6:
        return 0.0, float(valid.mean())
    displacement = np.linalg.norm(tracked[valid] - points[valid], axis=2).reshape(-1)
    return float(np.median(displacement)), float(valid.mean())


def extract_keyframes(
    video_path: str | Path,
    output_dir: str | Path,
    target_frames: int | None = None,
    max_width: int = 1920,
    candidates_per_bin: int = 4,
    manifest_path: str | Path | None = None,
    sample_fps: float = 1.0,
    max_frames: int = 1200,
    selection_mode: str = "uniform",
    telemetry_samples: Sequence | None = None,
    decode_mode: str = "seek",
) -> list[FrameRecord]:
    """Select sharp, evenly distributed frames while preserving flight order.

    Each timeline bin contributes one frame. ``uniform`` chooses its sharpest
    candidate. ``geometry`` balances sharpness, GPS baseline, optical-flow
    parallax, and surviving tracks. Sequential order is never changed.
    """
    video_path = Path(video_path)
    output_dir = Path(output_dir)
    if target_frames is not None and target_frames < 10:
        raise ValueError("target_frames must be at least 10")
    if sample_fps <= 0:
        raise ValueError("sample_fps must be positive")
    if max_frames < 10:
        raise ValueError("max_frames must be at least 10")
    if selection_mode not in {"uniform", "geometry"}:
        raise ValueError("selection_mode must be 'uniform' or 'geometry'")
    if decode_mode not in {"seek", "sequential"}:
        raise ValueError("decode_mode must be 'seek' or 'sequential'")
    if selection_mode == "geometry" and not telemetry_samples:
        raise ValueError("geometry selection requires telemetry_samples")
    if not video_path.is_file():
        raise FileNotFoundError(video_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    for old in output_dir.glob("frame_*.jpg"):
        old.unlink()

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"OpenCV could not open video: {video_path}")
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = float(cap.get(cv2.CAP_PROP_FPS))
    if total <= 0 or fps <= 0:
        cap.release()
        raise RuntimeError("Video has invalid frame count or frame rate")

    # A fixed frame budget undersamples long flights. When the caller does not
    # force a target, derive it from duration and cap it explicitly so compute
    # remains predictable. One frame/second is a safe draft baseline; operators
    # can increase --sample-fps for faster or lower-altitude flights.
    duration_s = total / fps
    frame_budget_mode = "fixed"
    if target_frames is None:
        target_frames = min(max_frames, max(10, int(round(duration_s * sample_fps)) + 1))
        frame_budget_mode = "duration_adaptive"

    candidate_count = min(total, max(target_frames, target_frames * candidates_per_bin))
    candidate_indices = np.unique(np.linspace(0, total - 1, candidate_count).round().astype(int))
    bins = np.array_split(candidate_indices, min(target_frames, len(candidate_indices)))
    records: list[FrameRecord] = []
    previous_small: np.ndarray | None = None
    previous_sample = None
    next_sequential_frame = 0
    decode_seconds = 0.0
    scoring_seconds = 0.0
    selection_seconds = 0.0
    jpeg_write_seconds = 0.0
    seek_operations = 0
    sequential_grabs = 0
    baseline_target_m = (
        max(0.5, _trajectory_length_m(telemetry_samples) / max(target_frames - 1, 1))
        if selection_mode == "geometry"
        else 0.0
    )

    if telemetry_samples:
        from .telemetry import interpolate

    for output_index, frame_bin in enumerate(bins):
        candidates = []
        for source_index in frame_bin:
            decode_started = time.perf_counter()
            source_index = int(source_index)
            if decode_mode == "seek":
                cap.set(cv2.CAP_PROP_POS_FRAMES, source_index)
                seek_operations += 1
            else:
                if source_index < next_sequential_frame:
                    cap.release()
                    raise RuntimeError("Sequential candidate indices must be monotonically increasing")
                while next_sequential_frame < source_index:
                    if not cap.grab():
                        break
                    next_sequential_frame += 1
                    sequential_grabs += 1
            ok, frame = cap.read()
            if decode_mode == "sequential" and ok:
                next_sequential_frame += 1
            decode_seconds += time.perf_counter() - decode_started
            if not ok:
                continue
            scoring_started = time.perf_counter()
            height, width = frame.shape[:2]
            if width > max_width:
                scale = max_width / width
                frame = cv2.resize(frame, (max_width, round(height * scale)), interpolation=cv2.INTER_AREA)
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            small = cv2.resize(gray, (160, 90), interpolation=cv2.INTER_AREA)
            sharpness = _sharpness(gray)
            sample = interpolate(telemetry_samples, int(source_index) / fps) if telemetry_samples else None
            baseline_m = _distance_m(previous_sample, sample) if previous_sample is not None else 0.0
            parallax_px, tracked_fraction = _parallax(previous_small, small)
            scoring_seconds += time.perf_counter() - scoring_started
            candidates.append({
                "sharpness": sharpness,
                "source_index": int(source_index),
                "frame": frame,
                "gray": gray,
                "small": small,
                "sample": sample,
                "baseline_m": baseline_m,
                "parallax_px": parallax_px,
                "tracked_fraction": tracked_fraction,
            })
        if not candidates:
            continue

        selection_started = time.perf_counter()
        maximum_sharpness = max(candidate["sharpness"] for candidate in candidates) or 1.0
        for candidate in candidates:
            sharpness_score = math.log1p(candidate["sharpness"]) / math.log1p(maximum_sharpness)
            if previous_small is None or selection_mode == "uniform":
                geometry_score = sharpness_score
            else:
                baseline_score = min(candidate["baseline_m"] / baseline_target_m, 1.0)
                # Useful temporal stereo has visible displacement but retains
                # enough tracks for overlap. Penalize extremely large flow.
                flow = candidate["parallax_px"]
                parallax_score = min(flow / 8.0, 1.0) * min(35.0 / max(flow, 1e-6), 1.0)
                overlap_score = min(candidate["tracked_fraction"] / 0.65, 1.0)
                geometry_score = (
                    0.40 * sharpness_score
                    + 0.30 * baseline_score
                    + 0.20 * parallax_score
                    + 0.10 * overlap_score
                )
            candidate["geometry_score"] = geometry_score

        best = max(
            candidates,
            key=(
                (lambda candidate: (candidate["geometry_score"], candidate["sharpness"]))
                if selection_mode == "geometry"
                else (lambda candidate: candidate["sharpness"])
            ),
        )
        sharpness = best["sharpness"]
        source_index = best["source_index"]
        frame = best["frame"]
        small = best["small"]
        motion = 0.0 if previous_small is None else float(np.mean(cv2.absdiff(previous_small, small)))
        previous_small = small
        previous_sample = best["sample"]
        image_name = f"frame_{output_index:04d}.jpg"
        selection_seconds += time.perf_counter() - selection_started
        write_started = time.perf_counter()
        if not cv2.imwrite(str(output_dir / image_name), frame, [cv2.IMWRITE_JPEG_QUALITY, 95]):
            raise RuntimeError(f"Failed to write {image_name}")
        jpeg_write_seconds += time.perf_counter() - write_started
        records.append(FrameRecord(
            image_name,
            source_index,
            source_index / fps,
            sharpness,
            motion,
            best["baseline_m"],
            best["parallax_px"],
            best["tracked_fraction"],
            best["geometry_score"],
        ))
    cap.release()
    if len(records) < 10:
        raise RuntimeError(f"Only {len(records)} usable frames were extracted")

    # Keep non-image files outside the COLMAP image directory. COLMAP scans
    # every entry in that directory and otherwise tries to decode frames.csv.
    manifest = Path(manifest_path) if manifest_path else output_dir / "frames.csv"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    with manifest.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=asdict(records[0]).keys())
        writer.writeheader()
        writer.writerows(asdict(record) for record in records)
    # Keep selection metadata next to the frame manifest without putting it in
    # COLMAP's image directory.
    metadata_path = manifest.with_suffix(".selection.json")
    metadata_path.write_text(
        __import__("json").dumps({
            # Keep the historical field for report compatibility and record
            # the new selection algorithm separately.
            "selection_mode": frame_budget_mode,
            "keyframe_selection_mode": selection_mode,
            "keyframe_decode_mode": decode_mode,
            "video_duration_s": duration_s,
            "source_fps": fps,
            "requested_sample_fps": sample_fps,
            "max_frames": max_frames,
            "selected_frames": len(records),
            "candidate_frames": len(candidate_indices),
            "seek_operations": seek_operations,
            "sequential_grabbed_frames": sequential_grabs,
            "timing_seconds": {
                "decode": round(decode_seconds, 2),
                "score_candidates": round(scoring_seconds, 2),
                "select_candidates": round(selection_seconds, 2),
                "write_selected_jpegs": round(jpeg_write_seconds, 2),
            },
            "effective_sample_fps": len(records) / duration_s if duration_s else None,
            "baseline_target_m": baseline_target_m if selection_mode == "geometry" else None,
            "median_selected_baseline_m": float(np.median([record.baseline_m for record in records[1:]])) if len(records) > 1 else 0.0,
            "median_selected_parallax_px": float(np.median([record.parallax_px for record in records[1:]])) if len(records) > 1 else 0.0,
            "median_tracked_fraction": float(np.median([record.tracked_fraction for record in records[1:]])) if len(records) > 1 else 0.0,
        }, indent=2),
        encoding="utf-8",
    )
    return records
