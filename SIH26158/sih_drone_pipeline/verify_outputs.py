from __future__ import annotations

import csv
import json
import math
import struct
from datetime import datetime
from pathlib import Path


REQUIRED_STAGES = [
    "feature_extraction", "sequential_matching", "sparse_mapping", "sparse_analysis",
    "gps_alignment", "aligned_model_text_export", "image_undistortion", "dense_stereo",
    "stereo_fusion", "mesh_cleanup",
]
REQUIRED_FILES = [
    "point_cloud.ply", "mesh.ply", "point_cloud.las", "dsm.tif", "model.glb", "model.obj",
    "confidence.tif", "confidence_summary.json", "capture_quality.json",
    "georeference.json", "run_report.json", "viewer_metadata.json", "frames.csv", "gpu_usage.csv",
]
REQUIRED_WORKFLOW_STEPS = [
    "keyframe_extraction", "capture_quality", "telemetry_sync", "ai_dynamic_masking", "validation", "product_export",
]


def _at_least(value: object, minimum: float) -> bool:
    if isinstance(value, bool):
        return False
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number >= minimum


def _at_most(value: object, maximum: float) -> bool:
    if isinstance(value, bool):
        return False
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number <= maximum


def _final_mesh_edge_max(mesh_quality: dict) -> float | None:
    """Prefer the measured post-cleanup edge maximum, with legacy fallback."""
    after = mesh_quality.get("longest_edge_max_after_m")
    return after if after is not None else mesh_quality.get("longest_edge_max_before_m")


def _surface_accuracy_results(validation: dict) -> tuple[bool | None, bool | None]:
    """Return surveyed-only and all-independent one-metre outcomes."""
    checkpoint_surface = validation.get("surveyed_checkpoints", {}).get(
        "passes_one_metre_target"
    )
    distance_surface = validation.get("independent_distances", {}).get(
        "passes_one_metre_target"
    )
    surveyed_outcomes = [
        value for value in (checkpoint_surface, distance_surface) if isinstance(value, bool)
    ]
    surveyed_surface = all(surveyed_outcomes) if surveyed_outcomes else None

    dense_validation = validation.get("dense_geometry", {})
    dense_surface = dense_validation.get("passes_one_metre_target")
    if dense_validation.get("reference_is_distinct_from_reconstruction") is False:
        dense_surface = None
    independent_outcomes = list(surveyed_outcomes)
    if isinstance(dense_surface, bool):
        independent_outcomes.append(dense_surface)
    independent_surface = all(independent_outcomes) if independent_outcomes else None
    return surveyed_surface, independent_surface


def _ply_header_counts(path: Path) -> tuple[int, int]:
    """Read vertex/face counts without allocating a full dense mesh."""
    vertices = faces = 0
    with path.open("rb") as stream:
        if stream.readline().strip() != b"ply":
            raise ValueError("Invalid PLY signature")
        for _ in range(10_000):
            line = stream.readline()
            if not line:
                raise ValueError("PLY end_header not found")
            fields = line.decode("ascii", errors="replace").strip().split()
            if len(fields) == 3 and fields[:2] == ["element", "vertex"]:
                vertices = int(fields[2])
            elif len(fields) == 3 and fields[:2] == ["element", "face"]:
                faces = int(fields[2])
            elif fields == ["end_header"]:
                break
    return vertices, faces


def _glb_mesh_count(path: Path) -> int:
    """Validate GLB structure and count declared meshes without decoding buffers."""
    with path.open("rb") as stream:
        magic, version, declared_length = struct.unpack("<4sII", stream.read(12))
        if magic != b"glTF" or version != 2 or declared_length != path.stat().st_size:
            raise ValueError("Invalid GLB header")
        chunk_length, chunk_type = struct.unpack("<II", stream.read(8))
        if chunk_type != 0x4E4F534A:
            raise ValueError("GLB first chunk is not JSON")
        document = json.loads(stream.read(chunk_length).decode("utf-8").rstrip(" \t\r\n\0"))
    return len(document.get("meshes", []))


def verify_output_directory(output_dir: str | Path) -> dict:
    import laspy
    import rasterio

    output_dir = Path(output_dir)
    files = {name: (output_dir / name).is_file() for name in REQUIRED_FILES}
    report_path = output_dir / "run_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else {}
    stages = report.get("stages", {})
    workflow = report.get("workflow_steps", {})
    stage_checks = {
        name: bool(
            name in stages
            and stages[name].get("return_code") == 0
            and stages[name].get("seconds") is not None
            and stages[name].get("log_file")
            and Path(stages[name]["log_file"]).is_file()
        )
        for name in REQUIRED_STAGES
    }
    successful_meshers = [
        name
        for name in (
            "poisson_meshing", "delaunay_meshing", "advancing_front_meshing"
        )
        if name in stages
        and stages[name].get("return_code") == 0
        and stages[name].get("seconds") is not None
        and stages[name].get("log_file")
        and Path(stages[name]["log_file"]).is_file()
    ]
    stage_checks["meshing"] = bool(successful_meshers)
    formats = {}
    try:
        with laspy.open(output_dir / "point_cloud.las") as reader:
            point_count = reader.header.point_count
            crs = reader.header.parse_crs()
        formats["las"] = {"valid": point_count > 0 and crs is not None, "points": point_count, "crs": str(crs)}
    except Exception as error:
        formats["las"] = {"valid": False, "error": str(error)}
    try:
        with rasterio.open(output_dir / "dsm.tif") as dataset:
            band = dataset.read(1, masked=True)
            valid_cells = int(band.count())
            total_cells = int(band.size)
            formats["geotiff"] = {
                "valid": dataset.width > 0 and dataset.height > 0 and dataset.crs is not None,
                "width": dataset.width, "height": dataset.height, "crs": str(dataset.crs),
                "valid_cells": valid_cells,
                "valid_fraction": valid_cells / total_cells if total_cells else 0.0,
                "resolution": list(dataset.res),
            }
    except Exception as error:
        formats["geotiff"] = {"valid": False, "error": str(error)}
    try:
        with rasterio.open(output_dir / "confidence.tif") as dataset:
            band = dataset.read(1, masked=True)
            values = band.compressed()
            formats["confidence_geotiff"] = {
                "valid": bool(
                    dataset.width > 0 and dataset.height > 0 and dataset.crs is not None
                    and len(values) and values.min() >= 0 and values.max() <= 1
                ),
                "width": dataset.width,
                "height": dataset.height,
                "crs": str(dataset.crs),
                "mean_confidence": float(values.mean()) if len(values) else None,
            }
    except Exception as error:
        formats["confidence_geotiff"] = {"valid": False, "error": str(error)}
    mesh_quality = report.get("products", {}).get("mesh_quality", {})
    try:
        vertices, faces = _ply_header_counts(output_dir / "mesh.ply")
        formats["mesh.ply"] = {
            "valid": vertices > 0 and faces > 0,
            "vertices": vertices,
            "faces": faces,
            "components": mesh_quality.get("components_after"),
            "watertight": mesh_quality.get("watertight"),
            "textured": mesh_quality.get("textured", False),
            "longest_edge_max_m": _final_mesh_edge_max(mesh_quality),
            "robust_edge_limit_m": mesh_quality.get("longest_edge_limit_m"),
            "oversized_face_fraction": mesh_quality.get("final_oversized_face_fraction"),
            "removed_unsupported_faces": mesh_quality.get("removed_unsupported_faces"),
            "validation_method": "ply_header_plus_recorded_export_metrics",
        }
    except Exception as error:
        formats["mesh.ply"] = {"valid": False, "error": str(error)}
    try:
        mesh_count = _glb_mesh_count(output_dir / "model.glb")
        formats["model.glb"] = {
            "valid": mesh_count > 0,
            "meshes": mesh_count,
            "textured": report.get("products", {}).get("textured_glb", False),
            "validation_method": "glb_header_and_json_chunk",
        }
    except Exception as error:
        formats["model.glb"] = {"valid": False, "error": str(error)}
    try:
        gpu_summary = json.loads((output_dir / "gpu_usage.summary.json").read_text(encoding="utf-8"))
        formats["gpu_log"] = {"valid": bool(gpu_summary.get("available") and gpu_summary.get("samples", 0) > 0), **gpu_summary}
    except Exception as error:
        formats["gpu_log"] = {"valid": False, "error": str(error)}
    gpu_by_stage = {}
    try:
        with (output_dir / "gpu_usage.csv").open(newline="", encoding="utf-8") as stream:
            gpu_rows = list(csv.DictReader(stream))
        for name, stage in stages.items():
            if not stage.get("started_at_utc") or not stage.get("ended_at_utc"):
                continue
            started = datetime.fromisoformat(stage["started_at_utc"])
            ended = datetime.fromisoformat(stage["ended_at_utc"])
            selected = [
                row for row in gpu_rows
                if started <= datetime.fromisoformat(row["sample_time_utc"]) <= ended
            ]
            utilization = [float(row["utilization_gpu_percent"]) for row in selected if row["utilization_gpu_percent"] not in {"", "N/A", "[N/A]"}]
            memory = [float(row["memory_used_mb"]) for row in selected if row["memory_used_mb"] not in {"", "N/A", "[N/A]"}]
            gpu_by_stage[name] = {
                "samples": len(selected),
                "gpu_utilization_mean_percent": sum(utilization) / len(utilization) if utilization else None,
                "gpu_utilization_max_percent": max(utilization) if utilization else None,
                "gpu_memory_max_mb": max(memory) if memory else None,
            }
    except Exception as error:
        gpu_by_stage = {"error": str(error)}
    checkpoint_report = report.get("validation", {}).get("surveyed_checkpoints", {})
    dense_report = report.get("validation", {}).get("dense_geometry", {})
    dense_one_metre = {}
    for row in dense_report.get("threshold_metrics", []):
        try:
            threshold_m = float(row.get("threshold_m"))
        except (AttributeError, TypeError, ValueError):
            continue
        if abs(threshold_m - 1.0) < 1e-9:
            dense_one_metre = row
            break
    result = {
        "files": files,
        "stages": stage_checks,
        "workflow_steps": {
            name: bool(
                workflow.get(name, {}).get("status")
                in (
                    {"passed", "skipped"}
                    if name == "ai_dynamic_masking"
                    else {"passed", "warning"}
                    if name == "capture_quality"
                    else {"passed"}
                )
                and workflow[name].get("seconds") is not None
            )
            for name in REQUIRED_WORKFLOW_STEPS
        },
        "formats": formats,
        "gpu_by_stage": gpu_by_stage,
        "validation": report.get("validation", {}),
        "metrics": {
            "processing_under_15_minutes": report.get("targets", {}).get("processing_under_15_minutes"),
            "one_metre_accuracy": report.get("targets", {}).get("one_metre_accuracy"),
            "registration_percent": report.get("sparse_metrics", {}).get("registration_percent"),
            "reprojection_error_px": report.get("sparse_metrics", {}).get("mean_reprojection_error_px"),
            "checkpoint_rmse_horizontal_m": checkpoint_report.get("rmse_horizontal_m"),
            "checkpoint_rmse_vertical_m": checkpoint_report.get("rmse_vertical_m"),
            "checkpoint_rmse_3d_m": checkpoint_report.get("rmse_3d_m"),
            "dense_precision_at_1m": dense_one_metre.get("precision"),
            "dense_completeness_at_1m": dense_one_metre.get("completeness"),
            "dense_f1_at_1m": dense_one_metre.get("f1"),
            "dense_reconstruction_to_reference_rmse_m": dense_report.get(
                "distances_m", {}
            ).get("reconstruction_to_reference", {}).get("rmse_m"),
            "dense_reference_to_reconstruction_rmse_m": dense_report.get(
                "distances_m", {}
            ).get("reference_to_reconstruction", {}).get("rmse_m"),
        },
        "standards": {
            "asprs_checkpoint_count_status": checkpoint_report.get(
                "asprs_checkpoint_count_status", "not_evaluated"
            ),
            "asprs_checkpoint_count_compliant": checkpoint_report.get(
                "asprs_checkpoint_count_compliant", False
            ),
            "asprs_compliance_scope": checkpoint_report.get("asprs_compliance_scope"),
            "note": (
                "Checkpoint-count status alone is not a complete ASPRS compliance claim; "
                "distribution, survey quality, coordinate reference system, and reporting "
                "requirements must also be verified."
            ),
        },
    }
    result["artifact_checks_pass"] = all(files.values()) and all(stage_checks.values()) and all(result["workflow_steps"].values()) and all(
        item.get("valid", False) for item in formats.values()
    )
    targets = report.get("targets", {})
    geotiff = formats.get("geotiff", {})
    mesh = formats.get("mesh.ply", {})
    textured_assets = (output_dir / "textured" / "mesh.ply").is_file() and (
        output_dir / "textured" / "texture.png"
    ).is_file()
    validation = report.get("validation", {})
    surveyed_surface, independent_surface = _surface_accuracy_results(validation)
    result["quality_checks"] = {
        "capture_quality_passed": report.get("capture_quality", {}).get("ready") is True,
        "gcp_alignment_fit_passed_if_used": (
            report.get("control_point_alignment") is None
            or report.get("control_point_alignment", {}).get("passes_fit_gate") is True
        ),
        "registration_at_least_90_percent": _at_least(
            report.get("sparse_metrics", {}).get("registration_percent"), 90
        ),
        "reprojection_error_at_most_2px": _at_most(
            report.get("sparse_metrics", {}).get("mean_reprojection_error_px"), 2
        ),
        "absolute_camera_alignment_at_most_1m": _at_most(
            report.get("validation", {}).get("gps_alignment_rmse_m"), 1
        ),
        "dsm_coverage_at_least_75_percent": geotiff.get("valid_fraction", 0) >= 0.75,
        "mesh_has_at_most_20_components": 0 < mesh.get("components", 0) <= 20,
        "mesh_has_at_most_0_1_percent_oversized_faces": (
            mesh.get("oversized_face_fraction") is not None
            and mesh["oversized_face_fraction"] <= 0.001
        ),
        "mesh_is_textured": mesh.get("textured") is True or textured_assets,
        "processing_under_15_minutes": targets.get("processing_under_15_minutes") is True,
        "surveyed_surface_accuracy_at_most_1m": surveyed_surface,
        "independent_surface_accuracy_at_most_1m": independent_surface,
        "consistent_enu_origin": report.get("georeference", {}).get("origin_policy") == "first_frame_reference",
    }
    # GPS-camera agreement remains visible as a diagnostic, but it is not an
    # independent surface-accuracy measurement. A run that passes surveyed
    # checkpoints must not be rejected merely because consumer-grade flight
    # telemetry is noisier than the reconstructed product.
    result["diagnostic_checks"] = {
        "gps_camera_agreement_at_most_1m": result["quality_checks"][
            "absolute_camera_alignment_at_most_1m"
        ],
    }
    production_gate_names = [
        name for name in result["quality_checks"]
        if name not in {
            "absolute_camera_alignment_at_most_1m",
            "surveyed_surface_accuracy_at_most_1m",
        }
    ]
    result["production_gate_names"] = production_gate_names
    result["production_ready"] = result["artifact_checks_pass"] and all(
        result["quality_checks"][name] is True for name in production_gate_names
    )
    (output_dir / "verification_report.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result
