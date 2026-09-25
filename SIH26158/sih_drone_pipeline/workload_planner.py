from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from statistics import median
from typing import Mapping, Sequence


def _number(row: Mapping[str, object], key: str, default: float = 0.0) -> float:
    try:
        value = float(row.get(key, default))
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


@dataclass(frozen=True)
class ConnectivityEdge:
    left_index: int
    right_index: int
    time_gap_s: float
    path_gap_m: float
    tracked_fraction: float
    parallax_px: float
    weak: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class PlannedWindow:
    start_index: int
    end_index: int
    frame_count: int
    start_s: float
    end_s: float
    planning_reason: str


def connectivity_edges(
    rows: Sequence[Mapping[str, object]],
    *,
    minimum_tracked_fraction: float = 0.35,
    maximum_time_gap_s: float = 10.0,
    maximum_path_gap_m: float = 20.0,
) -> list[ConnectivityEdge]:
    """Classify adjacent selected-frame links before sparse reconstruction."""
    edges = []
    for right in range(1, len(rows)):
        left = right - 1
        time_gap = max(
            0.0,
            _number(rows[right], "time_s") - _number(rows[left], "time_s"),
        )
        path_gap = max(0.0, _number(rows[right], "baseline_m"))
        tracked = _number(rows[right], "tracked_fraction")
        parallax = _number(rows[right], "parallax_px")
        reasons = []
        if tracked < minimum_tracked_fraction:
            reasons.append("low_tracked_fraction")
        if time_gap > maximum_time_gap_s:
            reasons.append("large_time_gap")
        if path_gap > maximum_path_gap_m:
            reasons.append("large_path_gap")
        edges.append(ConnectivityEdge(
            left_index=left,
            right_index=right,
            time_gap_s=time_gap,
            path_gap_m=path_gap,
            tracked_fraction=tracked,
            parallax_px=parallax,
            weak=bool(reasons),
            reasons=tuple(reasons),
        ))
    return edges


def _bounded_windows(
    rows: Sequence[Mapping[str, object]],
    segment_start: int,
    segment_end: int,
    *,
    maximum_frames: int,
    maximum_seconds: float,
    overlap_frames: int,
    reason: str,
) -> list[PlannedWindow]:
    windows = []
    start = segment_start
    while start <= segment_end:
        end = start
        start_s = _number(rows[start], "time_s")
        while end + 1 <= segment_end:
            candidate_count = end - start + 2
            candidate_span = _number(rows[end + 1], "time_s") - start_s
            if candidate_count > maximum_frames or candidate_span > maximum_seconds:
                break
            end += 1
        windows.append(PlannedWindow(
            start_index=start,
            end_index=end,
            frame_count=end - start + 1,
            start_s=start_s,
            end_s=_number(rows[end], "time_s"),
            planning_reason=reason,
        ))
        if end >= segment_end:
            break
        start = max(start + 1, end - overlap_frames + 1)
    return windows


def plan_connectivity_windows(
    rows: Sequence[Mapping[str, object]],
    *,
    maximum_frames: int = 72,
    maximum_seconds: float = 180.0,
    overlap_frames: int = 6,
    minimum_window_frames: int = 12,
    minimum_tracked_fraction: float = 0.35,
    maximum_time_gap_s: float = 10.0,
    maximum_path_gap_m: float = 20.0,
) -> dict:
    """Cut at observed weak links before invoking expensive COLMAP mapping."""
    if len(rows) < minimum_window_frames:
        raise ValueError("Not enough selected frames for a defensible sparse window")
    if maximum_frames < minimum_window_frames:
        raise ValueError("maximum_frames must be at least minimum_window_frames")
    if not 0 <= overlap_frames < maximum_frames:
        raise ValueError("overlap_frames must be in [0, maximum_frames)")
    times = [_number(row, "time_s") for row in rows]
    if any(left >= right for left, right in zip(times, times[1:])):
        raise ValueError("Selected-frame times must be strictly increasing")

    edges = connectivity_edges(
        rows,
        minimum_tracked_fraction=minimum_tracked_fraction,
        maximum_time_gap_s=maximum_time_gap_s,
        maximum_path_gap_m=maximum_path_gap_m,
    )
    observed_weak_boundaries = [edge.right_index for edge in edges if edge.weak]

    # Consecutive weak edges describe one weak region, not dozens of independent
    # reconstruction segments. Collapse each region to one representative cut.
    # This prevents a low-density deadline selection from becoming N overlapping
    # minimum-size windows (and therefore N expensive COLMAP invocations).
    minimum_precut_frames = max(
        minimum_window_frames,
        min(maximum_frames // 2, max(minimum_window_frames, len(rows) // 3)),
    )
    clusters: list[list[int]] = []
    for boundary in observed_weak_boundaries:
        if not clusters or boundary - clusters[-1][-1] >= minimum_precut_frames:
            clusters.append([boundary])
        else:
            clusters[-1].append(boundary)
    representatives = [cluster[len(cluster) // 2] for cluster in clusters]
    weak_boundaries = []
    previous = 0
    for boundary in representatives:
        if (
            boundary - previous >= minimum_precut_frames
            and len(rows) - boundary >= minimum_window_frames
        ):
            weak_boundaries.append(boundary)
            previous = boundary
    raw_segments = []
    start = 0
    for boundary in weak_boundaries:
        raw_segments.append((start, boundary - 1))
        start = boundary
    raw_segments.append((start, len(rows) - 1))

    # Give short segments enough neighboring context to be testable without
    # recreating a single large parent window across several weak boundaries.
    expanded_segments = []
    for start, end in raw_segments:
        # Retain common camera identities across precuts as well as ordinary
        # windows. Without these bridge images, model merging cannot use common
        # registered cameras even when the capture has sufficient overlap.
        start = max(0, start - overlap_frames // 2)
        end = min(len(rows) - 1, end + (overlap_frames + 1) // 2)
        missing = max(0, minimum_window_frames - (end - start + 1))
        left = min(start, (missing + 1) // 2)
        right = min(len(rows) - 1 - end, missing - left)
        if left + right < missing:
            left += min(start - left, missing - left - right)
            right += min(len(rows) - 1 - end - right, missing - left - right)
        expanded_segments.append((start - left, end + right))

    windows = []
    seen = set()
    for index, (start, end) in enumerate(expanded_segments):
        reason = "stable_connectivity"
        if weak_boundaries:
            reason = "precut_at_weak_connectivity"
        for window in _bounded_windows(
            rows,
            start,
            end,
            maximum_frames=maximum_frames,
            maximum_seconds=maximum_seconds,
            overlap_frames=overlap_frames,
            reason=reason,
        ):
            identity = (window.start_index, window.end_index)
            if identity not in seen:
                seen.add(identity)
                windows.append(window)
    windows.sort(key=lambda item: (item.start_index, item.end_index))
    return {
        "windows": [asdict(window) for window in windows],
        "edges": [asdict(edge) for edge in edges],
        "weak_link_count": len(weak_boundaries),
        "observed_weak_edge_count": len(observed_weak_boundaries),
        "observed_weak_boundaries": observed_weak_boundaries,
        "weak_boundaries": weak_boundaries,
        "minimum_precut_frames": minimum_precut_frames,
        "strategy": "precut_before_colmap_mapping",
    }


def assess_dense_feasibility(
    rows: Sequence[Mapping[str, object]],
    *,
    minimum_frames: int = 12,
    minimum_median_tracked_fraction: float = 0.35,
    minimum_median_parallax_px: float = 0.75,
    minimum_median_baseline_m: float = 0.50,
    maximum_near_duplicate_fraction: float = 0.50,
) -> dict:
    """Predict degenerate dense output before PatchMatch consumes GPU time."""
    tracked = [_number(row, "tracked_fraction") for row in rows[1:]]
    parallax = [_number(row, "parallax_px") for row in rows[1:]]
    baselines = [_number(row, "baseline_m") for row in rows[1:]]
    tracked_median = median(tracked) if tracked else 0.0
    parallax_median = median(parallax) if parallax else 0.0
    baseline_median = median(baselines) if baselines else 0.0
    near_duplicate_fraction = (
        sum(value < minimum_median_parallax_px for value in parallax) / len(parallax)
        if parallax else 1.0
    )
    checks = {
        "enough_frames": len(rows) >= minimum_frames,
        "tracked_fraction_sufficient": (
            tracked_median >= minimum_median_tracked_fraction
        ),
        "parallax_sufficient": parallax_median >= minimum_median_parallax_px,
        "baseline_sufficient": baseline_median >= minimum_median_baseline_m,
        "near_duplicate_fraction_bounded": (
            near_duplicate_fraction <= maximum_near_duplicate_fraction
        ),
    }
    missing_evidence = bool(rows) and not any(
        value > 0 for value in tracked + parallax + baselines
    )
    if missing_evidence:
        checks["geometry_evidence_present"] = False
    return {
        "ready": all(checks.values()),
        "checks": checks,
        "metrics": {
            "frames": len(rows),
            "tracked_fraction_median": tracked_median,
            "parallax_px_median": parallax_median,
            "baseline_m_median": baseline_median,
            "near_duplicate_fraction": near_duplicate_fraction,
        },
        "decision": "run_dense" if all(checks.values()) else "skip_dense",
    }


def plan_workload(
    *,
    video_duration_minutes: float,
    trajectory_length_m: float,
    quality_frame_budget: int,
    weak_link_count: int,
    deadline_minutes: float,
    mode: str = "auto",
    base_minutes: float = 1.2,
    minutes_per_frame: float = 0.065,
    minutes_per_weak_link: float = 0.35,
) -> dict:
    """Compare quality workload with a measured hardware deadline budget."""
    if mode not in {"auto", "deadline", "quality"}:
        raise ValueError("mode must be auto, deadline, or quality")
    if min(video_duration_minutes, trajectory_length_m, quality_frame_budget) < 0:
        raise ValueError("Workload inputs must be non-negative")
    connectivity_penalty = weak_link_count * minutes_per_weak_link
    estimated = (
        base_minutes
        + quality_frame_budget * minutes_per_frame
        + connectivity_penalty
    )
    affordable = max(
        0,
        math.floor(
            (deadline_minutes - base_minutes - connectivity_penalty)
            / minutes_per_frame
        ),
    )
    conflict = quality_frame_budget > affordable
    if mode == "quality":
        selected_budget = quality_frame_budget
        decision = "run_quality"
    elif mode == "deadline":
        selected_budget = min(quality_frame_budget, affordable)
        decision = "run_deadline_partial" if conflict else "run_complete"
    elif conflict:
        selected_budget = min(quality_frame_budget, affordable)
        decision = "run_auto_deadline_partial"
    else:
        selected_budget = quality_frame_budget
        decision = "run_complete"
    return {
        "video_duration_minutes": video_duration_minutes,
        "trajectory_length_m": trajectory_length_m,
        "quality_frame_budget": quality_frame_budget,
        "deadline_frame_budget": affordable,
        "selected_frame_budget": selected_budget,
        "weak_link_count": weak_link_count,
        "estimated_quality_runtime_minutes": estimated,
        "deadline_minutes": deadline_minutes,
        "constraint_conflict": conflict,
        "mode": mode,
        "decision": decision,
        "calibration": {
            "base_minutes": base_minutes,
            "minutes_per_frame": minutes_per_frame,
            "minutes_per_weak_link": minutes_per_weak_link,
        },
    }


def plan_bounded_rescue(
    *,
    elapsed_minutes: float,
    deadline_minutes: float,
    expected_rescue_minutes: float,
    dense_feasibility_ready: bool,
    current_coverage_fraction: float,
    target_coverage_fraction: float,
    recoverable_coverage_fraction: float,
    maximum_rescue_attempts: int = 1,
    completed_rescue_attempts: int = 0,
    safety_margin_minutes: float = 0.5,
) -> dict:
    """Fail closed when rescue cannot meet both geometry and time objectives."""
    remaining = max(0.0, deadline_minutes - elapsed_minutes)
    predicted_coverage = min(
        1.0, current_coverage_fraction + max(0.0, recoverable_coverage_fraction)
    )
    checks = {
        "dense_feasibility_ready": dense_feasibility_ready,
        "attempt_available": completed_rescue_attempts < maximum_rescue_attempts,
        "deadline_budget_available": (
            expected_rescue_minutes + safety_margin_minutes <= remaining
        ),
        "can_reach_coverage_target": predicted_coverage >= target_coverage_fraction,
    }
    if not checks["dense_feasibility_ready"]:
        decision = "skip_rescue_dense_infeasible"
    elif not checks["attempt_available"]:
        decision = "skip_rescue_attempt_limit"
    elif not checks["deadline_budget_available"]:
        decision = "skip_rescue_deadline_budget"
    elif not checks["can_reach_coverage_target"]:
        decision = "skip_rescue_insufficient_benefit"
    else:
        decision = "run_single_bounded_rescue"
    return {
        "decision": decision,
        "checks": checks,
        "elapsed_minutes": elapsed_minutes,
        "deadline_minutes": deadline_minutes,
        "remaining_minutes": remaining,
        "expected_rescue_minutes": expected_rescue_minutes,
        "safety_margin_minutes": safety_margin_minutes,
        "current_coverage_fraction": current_coverage_fraction,
        "predicted_coverage_fraction": predicted_coverage,
        "target_coverage_fraction": target_coverage_fraction,
        "maximum_rescue_attempts": maximum_rescue_attempts,
        "completed_rescue_attempts": completed_rescue_attempts,
    }
