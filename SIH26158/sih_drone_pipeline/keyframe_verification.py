"""
keyframe_verification.py — cheap ORB + local Lucas-Kanade sanity check
for the telemetry-selected candidates from frame_selection.py.

WHY THIS EXISTS
---------------
Telemetry-based footprint overlap (frame_selection.py) guarantees
*geometric* coverage -- it has no idea whether there's anything to match
in the images. GPS can say "80% overlap" over open water, a blank wall,
or a lens-flare frame, and COLMAP will still fail to register that pair.
This stage runs a cheap, local visual check ONLY on the handful of
telemetry-selected candidates (never the whole video) to catch that.

WHAT THIS DELIBERATELY LEAVES OUT
-----------------------------------
- Does not decode the whole video. Only the selected candidates, plus a
  tiny local burst (+/- BURST_RADIUS frames) around any candidate that
  needs a trackability check.
- Does not run SIFT or SuperPoint here. ORB is enough to answer "is
  there texture here at all" -- save SIFT for the reconstruction
  hand-off (extract once, feed straight into COLMAP's database instead
  of letting COLMAP re-extract) and SuperPoint for the rare
  texture-poor regions this stage flags as inconclusive after an ORB
  + LK check, not as a first pass over everything.

DECISION LOGIC PER CANDIDATE
-----------------------------
1. ORB keypoints on the candidate frame -> spatial coverage score
   (fraction of an NxN grid containing at least MIN_KEYPOINTS_PER_CELL
   strong keypoints). Cheap texture-presence check, no motion needed.
2. If coverage is borderline, decode one nearby frame and run
   Lucas-Kanade forward tracking from the candidate. The fraction of
   ORB keypoints that survive tracking with low error is the
   "trackability score" -- catches motion blur / exposure shifts that
   a single static frame's keypoint count won't reveal.
3. Combined score = min(coverage, trackability) when both were
   computed, else just coverage. Below REJECT_THRESHOLD, the candidate
   is swapped for the nearest textured neighbor -- a local repair, not
   a global re-run of frame_selection.py.

This module doesn't know how you decode frames (ffmpeg CLI vs.
cv2.VideoCapture vs. PyAV) -- you provide a `decode_frame(index) ->
np.ndarray (BGR)` callback so it stays decoupled from your I/O layer.
"""

import numpy as np
import cv2
from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence


GRID_SIZE = 4                  # NxN grid for spatial coverage scoring
MIN_KEYPOINTS_PER_CELL = 3      # a cell counts as "textured" past this
COVERAGE_BORDERLINE = 0.55      # below this, run the LK trackability check
REJECT_THRESHOLD = 0.30         # below this, candidate gets swapped
BURST_RADIUS = 2                 # frame offset used for the LK check
MAX_LOCAL_SWAP_RADIUS = 6       # how far to search for a replacement


@dataclass
class VerifiedFrame:
    original_index: int
    final_index: int
    coverage_score: float
    trackability_score: Optional[float]
    swapped: bool
    unresolved: bool = False


def _orb_coverage_score(image: np.ndarray, orb: cv2.ORB) -> float:
    """Fraction of an NxN spatial grid with at least MIN_KEYPOINTS_PER_CELL
    strong ORB keypoints. Cheap texture-presence check."""
    h, w = image.shape[:2]
    keypoints = orb.detect(image, None)
    if not keypoints:
        return 0.0
    cell_h, cell_w = h / GRID_SIZE, w / GRID_SIZE
    grid_counts = np.zeros((GRID_SIZE, GRID_SIZE), dtype=int)
    for kp in keypoints:
        cx, cy = kp.pt
        gx = min(int(cx // cell_w), GRID_SIZE - 1)
        gy = min(int(cy // cell_h), GRID_SIZE - 1)
        grid_counts[gy, gx] += 1
    covered_cells = np.sum(grid_counts >= MIN_KEYPOINTS_PER_CELL)
    return float(covered_cells) / (GRID_SIZE * GRID_SIZE)


def _lk_trackability_score(
    frame_a: np.ndarray,
    frame_b: np.ndarray,
    orb: cv2.ORB,
) -> float:
    """Fraction of frame_a's ORB keypoints Lucas-Kanade can still find in
    frame_b with good status and low error. Catches blur/exposure issues
    a single-frame keypoint count won't reveal."""
    gray_a = cv2.cvtColor(frame_a, cv2.COLOR_BGR2GRAY)
    gray_b = cv2.cvtColor(frame_b, cv2.COLOR_BGR2GRAY)
    keypoints = orb.detect(gray_a, None)
    if not keypoints:
        return 0.0
    points = np.float32([kp.pt for kp in keypoints]).reshape(-1, 1, 2)
    tracked, status, error = cv2.calcOpticalFlowPyrLK(
        gray_a, gray_b, points, None,
        winSize=(21, 21), maxLevel=3,
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
    )
    if status is None or error is None or tracked is None:
        return 0.0
    good = (status.reshape(-1) == 1) & (error.reshape(-1) < 12.0)
    return float(np.sum(good)) / len(keypoints)


def verify_and_repair(
    candidate_indices: Sequence[int],
    decode_frame: Callable[[int], np.ndarray],
    frame_count: int,
    allow_swaps: bool = True,
) -> List[VerifiedFrame]:
    """
    Runs the cascade on each telemetry-selected candidate. Only decodes
    the candidate itself, plus a small local burst when a trackability
    check is triggered -- never the full video.
    """
    if frame_count <= 0 or any(i < 0 or i >= frame_count for i in candidate_indices):
        raise ValueError("Candidate indices must lie inside a nonempty video")
    if list(candidate_indices) != sorted(set(candidate_indices)):
        raise ValueError("Candidates must be unique and sorted")
    orb = cv2.ORB_create(nfeatures=500)
    results = []
    reserved = set(candidate_indices)
    from functools import lru_cache
    decode = lru_cache(maxsize=16)(decode_frame)

    def score_frame(index):
        frame = decode(index)
        if frame is None or frame.size == 0:
            raise ValueError(f"Invalid decoded frame {index}")
        coverage = _orb_coverage_score(frame, orb)
        trackability = None
        neighbor = index + BURST_RADIUS
        if neighbor >= frame_count:
            neighbor = index - BURST_RADIUS
        if coverage < COVERAGE_BORDERLINE and 0 <= neighbor < frame_count:
            trackability = _lk_trackability_score(frame, decode(neighbor), orb)
        return coverage, trackability, min(coverage, trackability) if trackability is not None else coverage

    for position, idx in enumerate(candidate_indices):
        coverage, trackability, score = score_frame(idx)

        final_idx = idx
        swapped = False
        if allow_swaps and score < REJECT_THRESHOLD:
            # Local repair is a visual proposal; callers must recheck telemetry overlap.
            for offset in range(1, MAX_LOCAL_SWAP_RADIUS + 1):
                for direction in (offset, -offset):
                    trial_idx = idx + direction
                    if trial_idx < 0 or trial_idx >= frame_count or trial_idx in reserved:
                        continue
                    # Preserve ordering; a caller must separately check geometric overlap.
                    lower = results[-1].final_index if results else -1
                    upper = candidate_indices[position + 1] if position + 1 < len(candidate_indices) else frame_count
                    if not lower < trial_idx < upper:
                        continue
                    trial_coverage, trial_trackability, trial_score = score_frame(trial_idx)
                    if trial_score >= REJECT_THRESHOLD:
                        coverage, trackability, score = trial_coverage, trial_trackability, trial_score
                        final_idx = trial_idx
                        reserved.add(trial_idx)
                        swapped = True
                        break
                if swapped:
                    break

        results.append(VerifiedFrame(
            original_index=idx,
            final_index=final_idx,
            coverage_score=coverage,
            trackability_score=trackability,
            swapped=swapped,
            unresolved=score < REJECT_THRESHOLD and not swapped,
        ))

    return results


if __name__ == "__main__":
    # Smoke test: a textured frame, a blank/textureless one (should get
    # flagged and swapped for the nearby textured frame), and two more
    # textured frames as swap candidates.
    rng = np.random.default_rng(0)
    textured = rng.integers(0, 255, (480, 640, 3), dtype=np.uint8)
    blank = np.full((480, 640, 3), 128, dtype=np.uint8)

    synthetic_frames = {0: textured, 1: blank, 2: textured, 3: textured}

    def decode_frame(index):
        return synthetic_frames[index]

    verified = verify_and_repair(
        candidate_indices=[0, 1],
        decode_frame=decode_frame,
        frame_count=len(synthetic_frames),
    )
    for v in verified:
        print(v)
