from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable

import numpy as np
import trimesh
from scipy.spatial import ConvexHull, cKDTree


def file_sha256(path: str | Path) -> str:
    """Return a streaming SHA-256 digest for an experiment input."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fingerprint_files(paths: Iterable[str | Path]) -> dict:
    """Fingerprint an ordered group of files and fail if any input is absent."""
    entries = []
    aggregate = hashlib.sha256()
    for raw_path in paths:
        path = Path(raw_path)
        if not path.is_file():
            raise FileNotFoundError(path)
        item = {
            "path": str(path),
            "bytes": int(path.stat().st_size),
            "sha256": file_sha256(path),
        }
        entries.append(item)
        aggregate.update(path.name.encode("utf-8"))
        aggregate.update(str(item["bytes"]).encode("ascii"))
        aggregate.update(item["sha256"].encode("ascii"))
    return {
        "sha256": aggregate.hexdigest(),
        "file_count": len(entries),
        "bytes": int(sum(item["bytes"] for item in entries)),
        "files": entries,
    }


def ply_header_counts(path: str | Path) -> tuple[int, int]:
    """Read vertex and face counts without allocating a full PLY."""
    vertices = faces = 0
    with Path(path).open("rb") as stream:
        if stream.readline().strip() != b"ply":
            raise ValueError(f"Invalid PLY signature: {path}")
        for _ in range(10_000):
            line = stream.readline()
            if not line:
                raise ValueError(f"PLY end_header not found: {path}")
            fields = line.decode("ascii", errors="replace").strip().split()
            if len(fields) == 3 and fields[:2] == ["element", "vertex"]:
                vertices = int(fields[2])
            elif len(fields) == 3 and fields[:2] == ["element", "face"]:
                faces = int(fields[2])
            elif fields == ["end_header"]:
                return vertices, faces
    raise ValueError(f"PLY header is too long: {path}")


def _load_vertices(path: str | Path) -> np.ndarray:
    loaded = trimesh.load(Path(path), process=False)
    if isinstance(loaded, trimesh.Scene):
        loaded = loaded.dump(concatenate=True)
    vertices = np.asarray(loaded.vertices, dtype=np.float64)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or not len(vertices):
        raise ValueError(f"No 3D vertices found in {path}")
    finite = np.isfinite(vertices).all(axis=1)
    vertices = vertices[finite]
    if not len(vertices):
        raise ValueError(f"No finite 3D vertices found in {path}")
    return vertices


def _load_mesh(path: str | Path) -> trimesh.Trimesh:
    loaded = trimesh.load(Path(path), process=False)
    if isinstance(loaded, trimesh.Scene):
        loaded = loaded.dump(concatenate=True)
    if not isinstance(loaded, trimesh.Trimesh) or not len(loaded.faces):
        raise ValueError(f"No triangle mesh found in {path}")
    if not np.isfinite(np.asarray(loaded.vertices)).all():
        raise ValueError(f"Mesh contains non-finite vertices: {path}")
    return loaded


def _sample_rows(points: np.ndarray, maximum: int, seed: int) -> np.ndarray:
    if maximum < 1:
        raise ValueError("maximum must be positive")
    if len(points) <= maximum:
        return points
    indices = np.random.default_rng(seed).choice(len(points), maximum, replace=False)
    return points[np.sort(indices)]


def _distance_summary(
    source_sample: np.ndarray,
    target_points: np.ndarray,
    threshold_m: float,
) -> dict:
    distances, _ = cKDTree(target_points).query(source_sample, k=1, workers=-1)
    return {
        "samples": int(len(distances)),
        "median_m": float(np.median(distances)),
        "p95_m": float(np.percentile(distances, 95)),
        "maximum_m": float(np.max(distances)),
        "within_threshold_fraction": float(np.mean(distances <= threshold_m)),
    }


def compare_point_clouds(
    reference_path: str | Path,
    candidate_path: str | Path,
    *,
    max_samples: int = 100_000,
    distance_threshold_m: float = 0.5,
    seed: int = 26158,
) -> dict:
    """Compare actual point locations in both directions using deterministic samples."""
    if distance_threshold_m <= 0:
        raise ValueError("distance_threshold_m must be positive")
    reference = _load_vertices(reference_path)
    candidate = _load_vertices(candidate_path)
    reference_sample = _sample_rows(reference, max_samples, seed)
    candidate_sample = _sample_rows(candidate, max_samples, seed + 1)
    reference_to_candidate = _distance_summary(
        reference_sample, candidate, distance_threshold_m
    )
    candidate_to_reference = _distance_summary(
        candidate_sample, reference, distance_threshold_m
    )
    return {
        "reference_points": int(len(reference)),
        "candidate_points": int(len(candidate)),
        "point_count_ratio": float(len(candidate) / len(reference)),
        "distance_threshold_m": float(distance_threshold_m),
        "reference_to_candidate": reference_to_candidate,
        "candidate_to_reference": candidate_to_reference,
        "symmetric_median_m": float(max(
            reference_to_candidate["median_m"], candidate_to_reference["median_m"]
        )),
        "symmetric_p95_m": float(max(
            reference_to_candidate["p95_m"], candidate_to_reference["p95_m"]
        )),
        "bidirectional_coverage_fraction": float(min(
            reference_to_candidate["within_threshold_fraction"],
            candidate_to_reference["within_threshold_fraction"],
        )),
    }


def compare_dsm_rasters(
    reference_path: str | Path,
    candidate_path: str | Path,
) -> dict:
    """Compare a candidate DSM after mapping it onto the exact reference grid."""
    import rasterio
    from rasterio.warp import Resampling, reproject

    with rasterio.open(reference_path) as reference_dataset:
        if reference_dataset.crs is None:
            raise ValueError("Reference DSM has no CRS")
        reference = reference_dataset.read(1, masked=True).filled(np.nan).astype(np.float32)
        reference_crs = reference_dataset.crs
        reference_transform = reference_dataset.transform
        reference_resolution = tuple(abs(float(value)) for value in reference_dataset.res)

    with rasterio.open(candidate_path) as candidate_dataset:
        if candidate_dataset.crs is None:
            raise ValueError("Candidate DSM has no CRS")
        candidate = candidate_dataset.read(1, masked=True).filled(np.nan).astype(np.float32)
        candidate_on_reference = np.full(reference.shape, np.nan, dtype=np.float32)
        reproject(
            source=candidate,
            destination=candidate_on_reference,
            src_transform=candidate_dataset.transform,
            src_crs=candidate_dataset.crs,
            src_nodata=np.nan,
            dst_transform=reference_transform,
            dst_crs=reference_crs,
            dst_nodata=np.nan,
            resampling=Resampling.nearest,
        )
        candidate_crs = candidate_dataset.crs
        candidate_resolution = tuple(abs(float(value)) for value in candidate_dataset.res)

    reference_valid = np.isfinite(reference)
    candidate_valid = np.isfinite(candidate_on_reference)
    common = reference_valid & candidate_valid
    union = reference_valid | candidate_valid
    if not reference_valid.any() or not common.any():
        raise ValueError("DSM comparison has no common valid reference cells")
    elevation_delta = np.abs(
        candidate_on_reference[common].astype(np.float64)
        - reference[common].astype(np.float64)
    )
    return {
        "same_crs": bool(candidate_crs == reference_crs),
        "same_resolution": bool(np.allclose(candidate_resolution, reference_resolution)),
        "reference_valid_cells": int(reference_valid.sum()),
        "candidate_valid_cells_on_reference_grid": int(candidate_valid.sum()),
        "common_valid_cells": int(common.sum()),
        "valid_cell_retention": float(candidate_valid.sum() / reference_valid.sum()),
        "reference_mask_coverage": float(common.sum() / reference_valid.sum()),
        "valid_mask_iou": float(common.sum() / union.sum()),
        "elevation_abs_median_m": float(np.median(elevation_delta)),
        "elevation_abs_p95_m": float(np.percentile(elevation_delta, 95)),
        "elevation_abs_maximum_m": float(np.max(elevation_delta)),
    }


def _sample_mesh_surface(mesh: trimesh.Trimesh, count: int, seed: int) -> np.ndarray:
    triangles = np.asarray(mesh.vertices, dtype=np.float64)[np.asarray(mesh.faces)]
    cross = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    areas = 0.5 * np.linalg.norm(cross, axis=1)
    valid = np.isfinite(areas) & (areas > np.finfo(np.float64).eps)
    triangles = triangles[valid]
    areas = areas[valid]
    if not len(areas):
        raise ValueError("Mesh has no non-degenerate surface triangles")
    rng = np.random.default_rng(seed)
    face_indices = rng.choice(len(areas), size=count, replace=True, p=areas / areas.sum())
    chosen = triangles[face_indices]
    u = np.sqrt(rng.random(count))
    v = rng.random(count)
    return (
        (1.0 - u)[:, None] * chosen[:, 0]
        + (u * (1.0 - v))[:, None] * chosen[:, 1]
        + (u * v)[:, None] * chosen[:, 2]
    )


def _xy_area(vertices: np.ndarray) -> float:
    try:
        return float(ConvexHull(vertices[:, :2]).volume)
    except Exception:
        return 0.0


def _mesh_components(mesh: trimesh.Trimesh) -> int:
    components = trimesh.graph.connected_components(
        mesh.face_adjacency,
        nodes=np.arange(len(mesh.faces)),
        min_len=1,
    )
    return int(len(components))


def compare_meshes(
    reference_path: str | Path,
    candidate_path: str | Path,
    *,
    samples: int = 100_000,
    distance_threshold_m: float = 0.5,
    seed: int = 26158,
) -> dict:
    """Compare mesh surfaces geometrically rather than relying on face counts."""
    if samples < 1:
        raise ValueError("samples must be positive")
    reference = _load_mesh(reference_path)
    candidate = _load_mesh(candidate_path)
    reference_sample = _sample_mesh_surface(reference, samples, seed)
    candidate_sample = _sample_mesh_surface(candidate, samples, seed + 1)
    reference_to_candidate = _distance_summary(
        reference_sample, candidate_sample, distance_threshold_m
    )
    candidate_to_reference = _distance_summary(
        candidate_sample, reference_sample, distance_threshold_m
    )
    reference_area = float(reference.area)
    candidate_area = float(candidate.area)
    reference_xy_area = _xy_area(np.asarray(reference.vertices, dtype=np.float64))
    candidate_xy_area = _xy_area(np.asarray(candidate.vertices, dtype=np.float64))
    return {
        "reference_vertices": int(len(reference.vertices)),
        "candidate_vertices": int(len(candidate.vertices)),
        "reference_faces": int(len(reference.faces)),
        "candidate_faces": int(len(candidate.faces)),
        "reference_components": _mesh_components(reference),
        "candidate_components": _mesh_components(candidate),
        "reference_winding_consistent": bool(reference.is_winding_consistent),
        "candidate_winding_consistent": bool(candidate.is_winding_consistent),
        "surface_area_ratio": float(candidate_area / reference_area) if reference_area > 0 else None,
        "xy_area_ratio": (
            float(candidate_xy_area / reference_xy_area) if reference_xy_area > 0 else None
        ),
        "distance_threshold_m": float(distance_threshold_m),
        "reference_to_candidate": reference_to_candidate,
        "candidate_to_reference": candidate_to_reference,
        "symmetric_median_m": float(max(
            reference_to_candidate["median_m"], candidate_to_reference["median_m"]
        )),
        "symmetric_p95_m": float(max(
            reference_to_candidate["p95_m"], candidate_to_reference["p95_m"]
        )),
        "bidirectional_coverage_fraction": float(min(
            reference_to_candidate["within_threshold_fraction"],
            candidate_to_reference["within_threshold_fraction"],
        )),
    }
