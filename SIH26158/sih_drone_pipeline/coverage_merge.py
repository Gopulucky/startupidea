from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Sequence


def _nearest_distances(first, second):
    import numpy as np
    from scipy.spatial import cKDTree

    first = np.asarray(first, dtype=np.float64)
    second = np.asarray(second, dtype=np.float64)
    if not len(first) or not len(second):
        return np.empty(0, dtype=np.float64)
    return cKDTree(second).query(first, k=1)[0]


def enu_transform(origin, common_origin):
    """Rigid conversion between two local ENU frames via WGS84 ECEF."""
    import numpy as np
    from pyproj import Transformer
    def basis(value):
        lat, lon = np.radians([value['latitude'],value['longitude']])
        return np.array([[-np.sin(lon), -np.sin(lat)*np.cos(lon), np.cos(lat)*np.cos(lon)],
                         [np.cos(lon), -np.sin(lat)*np.sin(lon), np.cos(lat)*np.sin(lon)],
                         [0, np.cos(lat), np.sin(lat)]])
    to_ecef = Transformer.from_crs('EPSG:4979','EPSG:4978',always_xy=True)
    def ecef(value):
        return np.asarray(to_ecef.transform(value['longitude'],value['latitude'],value['altitude_m']))
    common_basis = basis(common_origin)
    transform = np.eye(4)
    transform[:3,:3] = common_basis.T @ basis(origin)
    transform[:3,3] = common_basis.T @ (ecef(origin)-ecef(common_origin))
    return transform


def _scene_geometries(loaded):
    """Preserve GLB scene-node transforms, including repeated mesh instances."""
    import trimesh
    if not isinstance(loaded, trimesh.Scene):
        return [loaded.copy()]
    result = []
    for node in loaded.graph.nodes_geometry:
        transform, name = loaded.graph[node]
        geometry = loaded.geometry[name].copy()
        geometry.apply_transform(transform)
        result.append(geometry)
    return result


def component_pair_diagnostics(
    first_vertices,
    second_vertices,
    *,
    seam_tolerance_m: float = 2.0,
    duplicate_tolerance_m: float = 0.05,
) -> dict:
    """Measure overlap/seam evidence without creating unsupported bridge faces."""
    import numpy as np

    first = np.asarray(first_vertices, dtype=np.float64)
    second = np.asarray(second_vertices, dtype=np.float64)
    if first.ndim != 2 or second.ndim != 2 or first.shape[1:] != (3,) or second.shape[1:] != (3,):
        raise ValueError("Component vertices must be Nx3 arrays")
    if not len(first) or not len(second):
        return {"overlap_status": "empty_component", "pair_pass": False}
    first_bounds = np.vstack((first.min(axis=0), first.max(axis=0)))
    second_bounds = np.vstack((second.min(axis=0), second.max(axis=0)))
    xy_overlap = np.minimum(first_bounds[1, :2], second_bounds[1, :2]) - np.maximum(
        first_bounds[0, :2], second_bounds[0, :2]
    )
    has_xy_overlap = bool(np.all(xy_overlap > 0))
    if not has_xy_overlap:
        return {
            "overlap_status": "disconnected_no_visual_seam_expected",
            "xy_overlap_area_sqm": 0.0,
            "pair_pass": True,
            "bridge_faces_added": False,
        }
    # Compare only the shared footprint. Comparing whole components penalizes
    # perfectly aligned tiles merely for containing different, nonoverlapping areas.
    lower = np.maximum(first_bounds[0,:2],second_bounds[0,:2])
    upper = np.minimum(first_bounds[1,:2],second_bounds[1,:2])
    first_overlap = first[np.all((first[:,:2] >= lower) & (first[:,:2] <= upper),axis=1)]
    second_overlap = second[np.all((second[:,:2] >= lower) & (second[:,:2] <= upper),axis=1)]
    if not len(first_overlap) or not len(second_overlap):
        return {'overlap_status':'bounding_boxes_overlap_without_surface_support',
                'pair_pass':False,'bridge_faces_added':False}
    first_sample = first_overlap[np.linspace(0,len(first_overlap)-1,min(2000,len(first_overlap)),dtype=int)]
    second_sample = second_overlap[np.linspace(0,len(second_overlap)-1,min(2000,len(second_overlap)),dtype=int)]
    distances = np.concatenate((
        _nearest_distances(first_sample, second_overlap),
        _nearest_distances(second_sample, first_overlap),
    ))
    median_distance = float(np.median(distances))
    p95_distance = float(np.percentile(distances, 95))
    duplicate_risk = bool(median_distance <= duplicate_tolerance_m)
    seam_pass = p95_distance <= seam_tolerance_m
    return {
        "overlap_status": "overlap_measured",
        "xy_overlap_area_sqm": float(xy_overlap.prod()),
        "median_bidirectional_seam_distance_m": median_distance,
        "p95_bidirectional_seam_distance_m": p95_distance,
        "seam_tolerance_m": seam_tolerance_m,
        "seam_pass": bool(seam_pass),
        "duplicate_surface_risk": duplicate_risk,
        "pair_pass": bool(seam_pass and not duplicate_risk),
        "bridge_faces_added": False,
        "measurement_scope": "vertices_in_intersection_of_xy_bounds; density-dependent diagnostic",
    }


def _release_prefix(
    trajectory_coverage_fraction: float | None,
    coverage_target: float,
) -> tuple[str, str]:
    if not 0 < coverage_target <= 1:
        raise ValueError("coverage_target must be in (0, 1]")
    if trajectory_coverage_fraction is None:
        return "reconstruction", "UNASSESSED"
    if not 0 <= trajectory_coverage_fraction <= 1:
        raise ValueError("trajectory_coverage_fraction must be in [0, 1]")
    if trajectory_coverage_fraction >= coverage_target:
        return "complete_reconstruction", "COMPLETE_COVERAGE"
    return "partial_reconstruction", "PARTIAL_COVERAGE"


def merge_georeferenced_meshes(
    component_outputs: Sequence[str | Path],
    output_dir: str | Path,
    *,
    trajectory_coverage_fraction: float | None = None,
    coverage_target: float = 0.90,
    expected_swath_area_sqm: float | None = None,
) -> dict:
    """Merge component meshes into the first component's local ENU frame.

    Components without visual overlap remain separate geometries in the GLB
    scene, but their GPS origins place them consistently. No artificial faces
    are created between disconnected areas.
    """
    merge_started = time.perf_counter()
    import numpy as np
    import trimesh
    from pyproj import CRS, Transformer

    directories = [Path(item) for item in component_outputs]
    if not directories:
        raise ValueError("At least one component output is required")
    records = []
    for directory in directories:
        mesh_path = directory / "mesh.ply"
        georef_path = directory / "georeference.json"
        if not mesh_path.is_file() or not georef_path.is_file():
            continue
        georef = json.loads(georef_path.read_text(encoding="utf-8"))
        records.append((directory, mesh_path, georef))
    if not records:
        raise ValueError("No component contains both mesh.ply and georeference.json")

    first_origin = records[0][2]["origin"]
    crs = CRS.from_user_input(records[0][2]["projected_crs"])
    to_projected = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    first_e, first_n = to_projected.transform(
        first_origin["longitude"], first_origin["latitude"]
    )
    first_z = float(first_origin["altitude_m"])
    scene = trimesh.Scene()
    visual_scene = trimesh.Scene()
    manifest = []
    visual_sources: list[Path] = []
    transformed_component_vertices = []
    for index, (directory, mesh_path, georef) in enumerate(records):
        origin = georef["origin"]
        transform_to_common = enu_transform(origin, first_origin)
        translation = transform_to_common[:3,3]
        loaded = trimesh.load(mesh_path, process=False)
        geometries = _scene_geometries(loaded)
        for part, geometry in enumerate(geometries):
            geometry = geometry.copy()
            geometry.apply_transform(transform_to_common)
            scene.add_geometry(geometry, node_name=f"component_{index:03d}_{part:02d}")
            transformed_component_vertices.append((index, np.asarray(geometry.vertices)))
        visual_path = directory / "model.glb"
        if not visual_path.is_file():
            visual_path = mesh_path
        visual_sources.append(visual_path)
        visual_loaded = trimesh.load(visual_path, process=False)
        visual_geometries = _scene_geometries(visual_loaded)
        for part, geometry in enumerate(visual_geometries):
            geometry = geometry.copy()
            geometry.apply_transform(transform_to_common)
            visual_scene.add_geometry(
                geometry, node_name=f"visual_component_{index:03d}_{part:02d}"
            )
        manifest.append({
            "component": index,
            "source": str(directory),
            "translation_to_common_enu_m": translation.tolist(),
            "transform_to_common_enu": transform_to_common.tolist(),
            "transform_method": "WGS84_ECEF_between_local_ENU_frames",
            "origin": origin,
            "visual_source": str(visual_path),
            "control_point_transform": georef.get("control_point_transform"),
        })

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    release_prefix, release_status = _release_prefix(
        trajectory_coverage_fraction, coverage_target
    )
    glb = output / f"{release_prefix}_scene.glb"
    # A direct copy is the most reliable way to preserve the original GLB's
    # textures when only one reconstruction component exists. Multi-component
    # scenes retain each source GLB's material while applying its ENU offset.
    if len(visual_sources) == 1 and visual_sources[0].suffix.lower() == ".glb":
        shutil.copy2(visual_sources[0], glb)
    else:
        visual_scene.export(glb)
    combined = trimesh.util.concatenate(tuple(scene.geometry.values()))
    ply = output / f"{release_prefix}_mesh.ply"
    obj = output / f"{release_prefix}_mesh.obj"
    combined.export(ply)
    combined.export(obj)
    textured_geometries = sum(
        1
        for geometry in visual_scene.geometry.values()
        if getattr(getattr(geometry, "visual", None), "kind", None) == "texture"
    )
    combined_validation = {
        "vertices": int(len(combined.vertices)),
        "faces": int(len(combined.faces)),
        "geometry_components": int(len(scene.geometry)),
        "glb_geometry_components": int(len(visual_scene.geometry)),
        "glb_textured_geometries": int(textured_geometries),
        "glb_texture_preserved": bool(textured_geometries > 0 and glb.stat().st_size > 0),
        "surface_area_square_m": float(combined.area),
        "bounds_enu_m": combined.bounds.tolist(),
        "glb_bytes": glb.stat().st_size,
        "ply_bytes": ply.stat().st_size,
        "obj_bytes": obj.stat().st_size,
        "structurally_valid": bool(
            len(combined.vertices) > 0
            and len(combined.faces) > 0
            and glb.stat().st_size > 0
            and ply.stat().st_size > 0
            and obj.stat().st_size > 0
        ),
    }
    occupied_xy = np.floor(np.asarray(combined.vertices)[:, :2]).astype(np.int64)
    occupied_area_sqm = float(len(np.unique(occupied_xy, axis=0)))
    surface_coverage_fraction = (
        min(1.0, occupied_area_sqm / expected_swath_area_sqm)
        if expected_swath_area_sqm and expected_swath_area_sqm > 0 else None
    )
    combined_validation.update({
        "occupied_xy_area_sqm_1m_grid": occupied_area_sqm,
        "expected_flight_swath_area_sqm": expected_swath_area_sqm,
        "surface_coverage_fraction": surface_coverage_fraction,
        "surface_coverage_method": "occupied_1m_xy_cells_over_expected_flight_swath",
    })
    component_vertices = []
    for index in range(len(manifest)):
        arrays = [vertices for component, vertices in transformed_component_vertices if component == index]
        component_vertices.append(np.vstack(arrays) if arrays else np.empty((0, 3)))
    pairwise = [
        {
            "first_component": index,
            "second_component": index + 1,
            **component_pair_diagnostics(component_vertices[index], component_vertices[index + 1]),
        }
        for index in range(max(0, len(component_vertices) - 1))
    ]
    transform_checks = []
    for item in manifest:
        transform = item.get("control_point_transform") or {}
        scale = transform.get("scale")
        scale_error = abs(float(scale) - 1.0) if scale is not None else None
        transform_checks.append({
            "component": item["component"],
            "scale": scale,
            "scale_error_fraction": scale_error,
            "scale_pass": scale_error is None or scale_error <= 0.05,
            "rotation_status": (
                "declared" if transform.get("rotation") is not None else "enu_assumed"
            ),
        })
    merge_quality_pass = bool(
        all(item["pair_pass"] for item in pairwise)
        and all(item["scale_pass"] for item in transform_checks)
    )
    result = {
        "component_count": len(manifest),
        "common_frame": "ENU at first component origin",
        "common_origin": first_origin,
        "projected_crs": crs.to_string(),
        "glb": str(glb),
        "ply": str(ply),
        "obj": str(obj),
        "release_status": release_status,
        "trajectory_coverage_fraction": trajectory_coverage_fraction,
        "coverage_target": coverage_target,
        "components": manifest,
        "combined_mesh_validation": combined_validation,
        "component_pair_diagnostics": pairwise,
        "component_transform_checks": transform_checks,
        "merge_quality_pass": merge_quality_pass,
        "note": "Disconnected components are co-located by telemetry; no unsupported bridge faces are invented.",
        "runtime": {
            "merge_minutes": (time.perf_counter() - merge_started) / 60.0,
            "scope": "merge_only",
        },
    }
    (output / "coverage_manifest.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    return result
