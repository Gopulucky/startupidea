from __future__ import annotations

import json
from pathlib import Path

import laspy
import numpy as np
import trimesh
from pyproj import CRS, Transformer
from scipy.spatial import cKDTree


def _load_geometry(path: Path) -> tuple[np.ndarray, np.ndarray | None, trimesh.Trimesh | None]:
    loaded = trimesh.load(path, process=False)
    if isinstance(loaded, trimesh.Scene):
        loaded = loaded.dump(concatenate=True)
    vertices = np.asarray(loaded.vertices, dtype=np.float64)
    colors = None
    if hasattr(loaded.visual, "vertex_colors") and len(loaded.visual.vertex_colors) == len(vertices):
        colors = np.asarray(loaded.visual.vertex_colors)[:, :3]
    return vertices, colors, loaded if isinstance(loaded, trimesh.Trimesh) else None


def _utm_crs(latitude: float, longitude: float) -> CRS:
    zone = int((longitude + 180) // 6) + 1
    return CRS.from_epsg((32600 if latitude >= 0 else 32700) + zone)


def _fill_small_dsm_holes(dsm: np.ndarray, iterations: int = 2) -> np.ndarray:
    """Fill only small interior gaps using neighbouring surface elevations."""
    filled = dsm.copy()
    for _ in range(iterations):
        missing = ~np.isfinite(filled)
        if not missing.any():
            break
        padded = np.pad(filled, 1, constant_values=np.nan)
        neighbours = np.stack([
            padded[:-2, 1:-1], padded[2:, 1:-1],
            padded[1:-1, :-2], padded[1:-1, 2:],
            padded[:-2, :-2], padded[:-2, 2:],
            padded[2:, :-2], padded[2:, 2:],
        ])
        support = np.isfinite(neighbours).sum(axis=0)
        candidates = missing & (support >= 4)
        if not candidates.any():
            break
        estimates = np.nanmedian(neighbours, axis=0)
        filled[candidates] = estimates[candidates]
    return filled


def _filter_statistical_outliers(
    points: np.ndarray,
    colors: np.ndarray | None = None,
    neighbours: int = 12,
    mad_multiplier: float = 4.0,
) -> tuple[np.ndarray, np.ndarray | None, dict]:
    """Remove isolated dense-cloud points using a robust local-distance limit."""
    points = np.asarray(points, dtype=np.float64)
    if len(points) < max(32, neighbours + 2):
        return points, colors, {
            "input_points": int(len(points)), "points": int(len(points)),
            "removed_points": 0, "method": "skipped_small_cloud",
        }
    k = min(neighbours + 1, len(points))
    tree = cKDTree(points)
    local_distance = np.empty(len(points), dtype=np.float64)
    # Query in batches so multi-million-point reconstructions do not allocate
    # one huge neighbour matrix.
    for start in range(0, len(points), 200_000):
        stop = min(start + 200_000, len(points))
        distances, _ = tree.query(points[start:stop], k=k, workers=-1)
        local_distance[start:stop] = np.mean(distances[:, 1:], axis=1)
    median = float(np.median(local_distance))
    mad = float(np.median(np.abs(local_distance - median)))
    robust_sigma = 1.4826 * mad
    threshold = median + mad_multiplier * robust_sigma
    if robust_sigma <= np.finfo(float).eps:
        threshold = float(np.percentile(local_distance, 99.5))
    keep = local_distance <= threshold
    # Never let a pathological threshold erase a reconstruction.
    if keep.sum() < max(32, int(0.5 * len(points))):
        keep = local_distance <= float(np.percentile(local_distance, 99.5))
    filtered_colors = np.asarray(colors)[keep] if colors is not None else None
    return points[keep], filtered_colors, {
        "input_points": int(len(points)),
        "points": int(keep.sum()),
        "removed_points": int((~keep).sum()),
        "removed_fraction": float((~keep).mean()),
        "neighbours": int(k - 1),
        "median_neighbour_distance_m": median,
        "distance_threshold_m": float(threshold),
        "method": "median_plus_4_scaled_mad",
    }


def _clean_mesh(mesh: trimesh.Trimesh) -> tuple[trimesh.Trimesh, dict]:
    """Remove implausibly long faces and tiny disconnected mesh islands."""
    cleaned = mesh.copy()
    original_faces = len(cleaned.faces)
    removed_oversized = 0
    edge_p95 = edge_max = edge_limit = None
    if original_faces:
        triangles = np.asarray(cleaned.vertices)[np.asarray(cleaned.faces)]
        face_edges = np.stack([
            np.linalg.norm(triangles[:, 0] - triangles[:, 1], axis=1),
            np.linalg.norm(triangles[:, 1] - triangles[:, 2], axis=1),
            np.linalg.norm(triangles[:, 2] - triangles[:, 0], axis=1),
        ], axis=1)
        longest = face_edges.max(axis=1)
        median_edge = float(np.median(longest))
        edge_p95 = float(np.percentile(longest, 95))
        edge_max = float(longest.max())
        edge_limit = max(edge_p95 * 2.25, median_edge * 6.0)
        plausible = longest <= edge_limit
        removed_oversized = int((~plausible).sum())
        if plausible.any() and not plausible.all():
            cleaned.update_faces(plausible)
            cleaned.remove_unreferenced_vertices()

    faces_after_edge_filter = len(cleaned.faces)
    components = trimesh.graph.connected_components(
        cleaned.face_adjacency,
        nodes=np.arange(faces_after_edge_filter),
        min_len=1,
    )
    largest = max((len(component) for component in components), default=0)
    minimum_faces = max(2, min(100, int(largest * 0.001)))
    keep = np.zeros(faces_after_edge_filter, dtype=bool)
    for component in components:
        if len(component) >= minimum_faces:
            keep[np.asarray(component, dtype=int)] = True
    if keep.any() and not keep.all():
        cleaned.update_faces(keep)
        cleaned.remove_unreferenced_vertices()
    cleaned.fix_normals()
    remaining_components = trimesh.graph.connected_components(
        cleaned.face_adjacency,
        nodes=np.arange(len(cleaned.faces)),
        min_len=1,
    )
    return cleaned, {
        "original_faces": int(original_faces),
        "faces": int(len(cleaned.faces)),
        "vertices": int(len(cleaned.vertices)),
        "removed_oversized_faces": removed_oversized,
        "removed_fragment_faces": int(faces_after_edge_filter - len(cleaned.faces)),
        "longest_edge_p95_m": edge_p95,
        "longest_edge_max_before_m": edge_max,
        "longest_edge_limit_m": edge_limit,
        "components_before": int(len(components)),
        "components_after": int(len(remaining_components)),
        "watertight": bool(cleaned.is_watertight),
        "textured": bool(getattr(cleaned.visual, "kind", None) == "texture"),
    }


def clean_mesh_file(input_path: str | Path, output_path: str | Path) -> dict:
    """Clean a mesher output before texturing and final product export."""
    _, _, mesh = _load_geometry(Path(input_path))
    if mesh is None:
        raise ValueError(f"No triangle mesh found in {input_path}")
    cleaned, quality = _clean_mesh(mesh)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    cleaned.export(output_path)
    return quality


def export_products(
    point_cloud_path: str | Path,
    mesh_path: str | Path | None,
    output_dir: str | Path,
    origin: dict,
    dsm_resolution_m: float = 0.5,
    origin_policy: str = "first_frame_reference",
    textured_mesh_path: str | Path | None = None,
    texture_path: str | Path | None = None,
) -> dict:
    """Export metric ENU products to LAS, GLB, OBJ and a UTM DSM GeoTIFF."""
    from rasterio.transform import from_origin
    import rasterio

    point_cloud_path, output_dir = Path(point_cloud_path), Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    points, colors, _ = _load_geometry(point_cloud_path)
    points, colors, point_filter = _filter_statistical_outliers(points, colors)
    point_cloud_output = output_dir / "point_cloud.ply"
    vertex_colors = colors if colors is not None else None
    trimesh.points.PointCloud(points, colors=vertex_colors).export(point_cloud_output)
    lat, lon, altitude = origin["latitude"], origin["longitude"], origin["altitude_m"]
    utm = _utm_crs(lat, lon)
    to_utm = Transformer.from_crs("EPSG:4326", utm, always_xy=True)
    origin_e, origin_n = to_utm.transform(lon, lat)
    projected = points.copy()
    projected[:, 0] += origin_e
    projected[:, 1] += origin_n
    projected[:, 2] += altitude

    header = laspy.LasHeader(point_format=2, version="1.4")
    header.scales = np.array([0.001, 0.001, 0.001])
    header.offsets = projected.min(axis=0)
    header.add_crs(utm)
    las = laspy.LasData(header)
    las.x, las.y, las.z = projected[:, 0], projected[:, 1], projected[:, 2]
    if colors is not None:
        las.red, las.green, las.blue = [colors[:, index].astype(np.uint16) * 257 for index in range(3)]
    las_path = output_dir / "point_cloud.las"
    las.write(las_path)

    x_min, y_min = projected[:, 0].min(), projected[:, 1].min()
    x_max, y_max = projected[:, 0].max(), projected[:, 1].max()
    width = max(1, int(np.ceil((x_max - x_min) / dsm_resolution_m)) + 1)
    height = max(1, int(np.ceil((y_max - y_min) / dsm_resolution_m)) + 1)
    if width * height > 100_000_000:
        raise ValueError("DSM grid exceeds 100 million cells; increase dsm_resolution_m")
    col = np.clip(((projected[:, 0] - x_min) / dsm_resolution_m).astype(int), 0, width - 1)
    row = np.clip(((y_max - projected[:, 1]) / dsm_resolution_m).astype(int), 0, height - 1)
    dsm = np.full((height, width), -np.inf, dtype=np.float32)
    np.maximum.at(dsm, (row, col), projected[:, 2].astype(np.float32))
    dsm[~np.isfinite(dsm)] = np.nan
    raw_valid_cells = int(np.isfinite(dsm).sum())
    dsm = _fill_small_dsm_holes(dsm)
    valid_cells = int(np.isfinite(dsm).sum())
    geotiff = output_dir / "dsm.tif"
    with rasterio.open(
        geotiff,
        "w",
        driver="GTiff",
        width=width,
        height=height,
        count=1,
        dtype="float32",
        crs=utm,
        transform=from_origin(x_min, y_max, dsm_resolution_m, dsm_resolution_m),
        nodata=np.nan,
        compress="deflate",
    ) as dataset:
        dataset.write(dsm, 1)

    outputs = {
        "las": str(las_path),
        "geotiff_dsm": str(geotiff),
        "crs": utm.to_string(),
        "point_count": int(len(points)),
        "point_cloud_ply": str(point_cloud_output),
        "point_filter": point_filter,
        "local_bounds_m": {"minimum": points.min(axis=0).tolist(), "maximum": points.max(axis=0).tolist()},
        "dsm": {
            "width": int(width),
            "height": int(height),
            "resolution_m": float(dsm_resolution_m),
            "raw_valid_cells": raw_valid_cells,
            "valid_cells": valid_cells,
            "valid_fraction": float(valid_cells / dsm.size),
            "hole_fill_method": "neighbour_median_two_iterations",
        },
    }
    if mesh_path and Path(mesh_path).is_file():
        _, _, mesh = _load_geometry(Path(mesh_path))
        if mesh is not None:
            mesh, mesh_quality = _clean_mesh(mesh)
            mesh_output = output_dir / "mesh.ply"
            glb_path, obj_path = output_dir / "model.glb", output_dir / "model.obj"
            mesh.export(mesh_output)
            mesh.export(glb_path)
            mesh.export(obj_path)
            outputs.update({
                "glb": str(glb_path),
                "obj": str(obj_path),
                "mesh_ply": str(mesh_output),
                "mesh_vertices": int(len(mesh.vertices)),
                "mesh_faces": int(len(mesh.faces)),
                "mesh_quality": mesh_quality,
            })
    if textured_mesh_path and Path(textured_mesh_path).is_file():
        textured_dir = output_dir / "textured"
        textured_dir.mkdir(parents=True, exist_ok=True)
        textured_output = textured_dir / "mesh.ply"
        import shutil
        shutil.copy2(textured_mesh_path, textured_output)
        outputs["textured_mesh_ply"] = str(textured_output)
        if texture_path and Path(texture_path).is_file():
            texture_output = textured_dir / Path(texture_path).name
            shutil.copy2(texture_path, texture_output)
            outputs["texture_image"] = str(texture_output)
        try:
            textured_geometry = trimesh.load(Path(textured_mesh_path), process=False)
            textured_glb = output_dir / "model.glb"
            textured_geometry.export(textured_glb)
            outputs["glb"] = str(textured_glb)
            outputs["textured_glb"] = bool(
                getattr(textured_geometry.visual, "kind", None) == "texture"
                if isinstance(textured_geometry, trimesh.Trimesh)
                else any(
                    getattr(item.visual, "kind", None) == "texture"
                    for item in textured_geometry.geometry.values()
                )
            )
        except Exception as error:
            outputs["textured_glb"] = False
            outputs["textured_glb_error"] = str(error)
    (output_dir / "georeference.json").write_text(
        json.dumps({
            "local_frame": "ENU",
            "origin": origin,
            "origin_policy": origin_policy,
            "projected_crs": utm.to_string(),
        }, indent=2),
        encoding="utf-8",
    )
    return outputs
