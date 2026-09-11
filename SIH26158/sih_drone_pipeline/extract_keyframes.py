from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass(frozen=True)
class FrameRecord:
    image_name: str
    source_frame: int
    time_s: float
    sharpness: float
    motion_score: float


def _sharpness(gray: np.ndarray) -> float:
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def extract_keyframes(
    video_path: str | Path,
    output_dir: str | Path,
    target_frames: int | None = None,
    max_width: int = 1920,
    candidates_per_bin: int = 4,
    manifest_path: str | Path | None = None,
    sample_fps: float = 1.0,
    max_frames: int = 1200,
) -> list[FrameRecord]:
    """Select sharp, evenly distributed frames while preserving flight order.

    Each timeline bin contributes its sharpest frame. Motion score is retained in
    the manifest as a capture-quality diagnostic; sequential order is never changed.
    """
    video_path = Path(video_path)
    output_dir = Path(output_dir)
    if target_frames is not None and target_frames < 10:
        raise ValueError("target_frames must be at least 10")
    if sample_fps <= 0:
        raise ValueError("sample_fps must be positive")
    if max_frames < 10:
        raise ValueError("max_frames must be at least 10")
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
    selection_mode = "fixed"
    if target_frames is None:
        target_frames = min(max_frames, max(10, int(round(duration_s * sample_fps)) + 1))
        selection_mode = "duration_adaptive"

    candidate_count = min(total, max(target_frames, target_frames * candidates_per_bin))
    candidate_indices = np.unique(np.linspace(0, total - 1, candidate_count).round().astype(int))
    bins = np.array_split(candidate_indices, min(target_frames, len(candidate_indices)))
    records: list[FrameRecord] = []
    previous_small: np.ndarray | None = None

    for output_index, frame_bin in enumerate(bins):
        best: tuple[float, int, np.ndarray, np.ndarray] | None = None
        for source_index in frame_bin:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(source_index))
            ok, frame = cap.read()
            if not ok:
                continue
            height, width = frame.shape[:2]
            if width > max_width:
                scale = max_width / width
                frame = cv2.resize(frame, (max_width, round(height * scale)), interpolation=cv2.INTER_AREA)
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            score = _sharpness(gray)
            if best is None or score > best[0]:
                best = (score, int(source_index), frame, gray)
        if best is None:
            continue
        sharpness, source_index, frame, gray = best
        small = cv2.resize(gray, (160, 90), interpolation=cv2.INTER_AREA)
        motion = 0.0 if previous_small is None else float(np.mean(cv2.absdiff(previous_small, small)))
        previous_small = small
        image_name = f"frame_{output_index:04d}.jpg"
        if not cv2.imwrite(str(output_dir / image_name), frame, [cv2.IMWRITE_JPEG_QUALITY, 95]):
            raise RuntimeError(f"Failed to write {image_name}")
        records.append(FrameRecord(image_name, source_index, source_index / fps, sharpness, motion))
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
            "selection_mode": selection_mode,
            "video_duration_s": duration_s,
            "source_fps": fps,
            "requested_sample_fps": sample_fps,
            "max_frames": max_frames,
            "selected_frames": len(records),
            "effective_sample_fps": len(records) / duration_s if duration_s else None,
        }, indent=2),
        encoding="utf-8",
    )
    return records
