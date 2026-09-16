from __future__ import annotations

import csv
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

from .camera import colmap_image_reader_options
from .utils import PipelineError, run_command, write_json


_FEATURE_TYPES = {
    "sift": "SIFT",
    "aliked-n16rot": "ALIKED_N16ROT",
    "aliked-n32": "ALIKED_N32",
}


def _feature_configuration(feature_type: str, feature_matcher: str) -> tuple[str, str]:
    """Resolve a compatible COLMAP extractor/matcher enum pair."""
    if feature_type not in _FEATURE_TYPES:
        raise ValueError(f"Unsupported feature_type: {feature_type}")
    if feature_matcher not in {"bruteforce", "lightglue"}:
        raise ValueError(f"Unsupported feature_matcher: {feature_matcher}")
    family = "SIFT" if feature_type == "sift" else "ALIKED"
    matcher = f"{family}_{'LIGHTGLUE' if feature_matcher == 'lightglue' else 'BRUTEFORCE'}"
    return _FEATURE_TYPES[feature_type], matcher


def _clean_mesher_output(mesh: Path, cleaned_mesh: Path, report: dict) -> dict:
    """Record deterministic Python mesh cleanup as a timed pipeline stage."""
    from .export_gis import clean_mesh_file

    started_at = datetime.now(timezone.utc).isoformat()
    started = time.perf_counter()
    quality = clean_mesh_file(mesh, cleaned_mesh)
    elapsed = round(time.perf_counter() - started, 2)
    ended_at = datetime.now(timezone.utc).isoformat()
    log_dir = Path(report["_log_dir"])
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "mesh_cleanup.log"
    log_file.write_text(str(quality), encoding="utf-8")
    report["stages"]["mesh_cleanup"] = {
        "seconds": elapsed,
        "started_at_utc": started_at,
        "ended_at_utc": ended_at,
        "return_code": 0,
        "command": ["python", "robust_mesh_cleanup"],
        "log_tail": str(quality),
        "log_file": str(log_file),
    }
    return quality


def _require_colmap() -> str:
    executable = shutil.which("colmap")
    if not executable:
        raise PipelineError("COLMAP was not found on PATH. Run this pipeline from the supplied Colab notebook.")
    return executable


def _help_has(colmap: str, command: str, option: str) -> bool:
    import subprocess

    result = subprocess.run(
        [colmap, command, "--help"], capture_output=True, text=True, errors="replace", check=False
    )
    return option.lstrip("-") in ((result.stdout or "") + (result.stderr or ""))


def _largest_model(sparse_root: Path) -> Path:
    models = [path for path in sparse_root.iterdir() if path.is_dir()]
    if not models:
        raise PipelineError("COLMAP mapper did not create a sparse model")
    return max(models, key=lambda path: (path / "images.bin").stat().st_size if (path / "images.bin").exists() else 0)


def _frame_geometry_scores(frame_manifest: str | Path | None) -> dict[str, float]:
    if frame_manifest is None:
        return {}
    manifest = Path(frame_manifest)
    if not manifest.is_file():
        raise FileNotFoundError(manifest)
    scores = {}
    with manifest.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            # Geometry-selected manifests already contain the combined score.
            # Sharpness is only a deterministic fallback for older manifests.
            geometry = float(row.get("geometry_score") or 0.0)
            sharpness = float(row.get("sharpness") or 0.0)
            scores[row["image_name"]] = geometry if geometry > 0 else sharpness
    return scores


def _limit_patch_match_sources(line: str, maximum: int | None) -> str:
    if maximum is None:
        return line
    if line.startswith("__auto__"):
        return f"__auto__, {maximum}"
    sources = [value.strip() for value in line.split(",") if value.strip()]
    return ", ".join(sources[:maximum])


def _subsample_patch_match_references(
    dense: Path,
    stride: int,
    selection_mode: str = "uniform",
    frame_manifest: str | Path | None = None,
    max_source_images: int | None = None,
    target_references: int | None = None,
) -> dict:
    """Configure dense anchors while retaining temporal coverage and source views."""
    if selection_mode not in {"uniform", "adaptive"}:
        raise ValueError("selection_mode must be 'uniform' or 'adaptive'")
    if max_source_images is not None and max_source_images < 2:
        raise ValueError("max_source_images must be at least 2")
    if target_references is not None and target_references < 2:
        raise ValueError("target_references must be at least 2")
    if target_references is not None and stride != 1:
        raise ValueError("target_references requires stride=1 to avoid ambiguous selection")
    config = dense / "stereo" / "patch-match.cfg"
    if not config.is_file():
        raise FileNotFoundError(config)
    lines = [line.strip() for line in config.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(lines) % 2:
        raise PipelineError(f"Unexpected PatchMatch configuration format: {config}")
    pairs = [(lines[index], lines[index + 1]) for index in range(0, len(lines), 2)]
    if target_references is not None:
        target = min(target_references, len(pairs))
        if target >= len(pairs):
            selected = pairs
        elif selection_mode == "uniform":
            # Inclusive endpoints retain the start and end of the flight,
            # while rounding gives a deterministic exact-size selection.
            indices = [round(index * (len(pairs) - 1) / (target - 1)) for index in range(target)]
            selected = [pairs[index] for index in indices]
        else:
            scores = _frame_geometry_scores(frame_manifest)
            if not scores:
                raise ValueError("adaptive dense anchors require a non-empty frame manifest")
            selected = []
            for index in range(target):
                start = index * len(pairs) // target
                end = max(start + 1, (index + 1) * len(pairs) // target)
                candidates = pairs[start:end]
                selected.append(max(
                    candidates,
                    key=lambda pair: (scores.get(Path(pair[0]).name, 0.0), pair[0]),
                ))
    elif stride <= 1:
        selected = pairs
    elif selection_mode == "uniform":
        selected = pairs[::stride]
        if pairs and pairs[-1] not in selected:
            selected.append(pairs[-1])
    else:
        scores = _frame_geometry_scores(frame_manifest)
        if not scores:
            raise ValueError("adaptive dense anchors require a non-empty frame manifest")
        target = max(1, (len(pairs) + stride - 1) // stride)
        selected = []
        # Pick the strongest geometry view inside each temporal bin. Binning
        # prevents a high-score region from consuming all anchors and leaving
        # other parts of the flight without dense coverage.
        for index in range(target):
            start = index * len(pairs) // target
            end = max(start + 1, (index + 1) * len(pairs) // target)
            candidates = pairs[start:end]
            selected.append(max(
                candidates,
                key=lambda pair: (scores.get(Path(pair[0]).name, 0.0), pair[0]),
            ))
    selected = [
        (reference, _limit_patch_match_sources(sources, max_source_images))
        for reference, sources in selected
    ]
    config.write_text(
        "".join(f"{reference}\n{sources}\n" for reference, sources in selected),
        encoding="utf-8",
    )
    return {
        "stride": stride,
        "selection_mode": selection_mode,
        "max_source_images": max_source_images,
        "target_references": target_references,
        "original_references": len(pairs),
        "selected_references": len(selected),
    }


def reconstruct(
    images_dir: str | Path,
    references_path: str | Path,
    workspace: str | Path,
    quality: str = "draft",
    make_mesh: bool = True,
    masks_dir: str | Path | None = None,
    mapper_mode: str = "standard",
    gps_prior_std_m: float = 5.0,
    gps_prior_horizontal_std_m: float | None = None,
    gps_prior_vertical_std_m: float | None = None,
    camera_calibration: dict | None = None,
    spatial_matching: bool = False,
    spatial_max_distance_m: float = 100.0,
    feature_type: str = "sift",
    feature_matcher: str = "bruteforce",
    dense_frame_stride: int = 1,
    dense_anchor_mode: str = "uniform",
    dense_target_references: int | None = None,
    dense_source_images: int | None = None,
    dense_max_image_size: int | None = None,
    dense_num_iterations: int | None = None,
    dense_num_samples: int | None = None,
    dense_window_step: int | None = None,
    delaunay_max_proj_dist: float | None = None,
    delaunay_max_depth_dist: float | None = None,
    delaunay_num_threads: int | None = None,
    mesher: str = "auto",
    mapper_ba_gpu: bool = False,
    mapper_single_model: bool = False,
    mapper_no_extract_colors: bool = False,
    mapper_ba_global_frames_ratio: float | None = None,
    mapper_ba_global_points_ratio: float | None = None,
    mapper_ba_global_max_refinements: int | None = None,
    mapper_ba_global_ignore_redundant_points3d: bool = False,
    mapper_ba_local_max_num_iterations: int | None = None,
    mapper_ba_global_max_num_iterations: int | None = None,
    frame_manifest: str | Path | None = None,
    sparse_only: bool = False,
) -> dict:
    """Run an ordered, GPS-aligned COLMAP reconstruction suitable for Colab GPU."""
    images_dir, references_path, workspace = Path(images_dir), Path(references_path), Path(workspace)
    if quality not in {"draft", "full"}:
        raise ValueError("quality must be 'draft' or 'full'")
    if mapper_mode not in {"standard", "pose-prior", "global"}:
        raise ValueError("mapper_mode must be 'standard', 'pose-prior', or 'global'")
    if gps_prior_std_m <= 0:
        raise ValueError("gps_prior_std_m must be positive")
    gps_prior_horizontal_std_m = gps_prior_horizontal_std_m or gps_prior_std_m
    gps_prior_vertical_std_m = gps_prior_vertical_std_m or gps_prior_std_m
    if gps_prior_horizontal_std_m <= 0 or gps_prior_vertical_std_m <= 0:
        raise ValueError("GPS prior horizontal and vertical uncertainties must be positive")
    if spatial_max_distance_m <= 0:
        raise ValueError("spatial_max_distance_m must be positive")
    feature_type_enum, feature_matcher_enum = _feature_configuration(
        feature_type, feature_matcher
    )
    if mesher not in {"auto", "delaunay", "poisson", "advancing-front"}:
        raise ValueError(
            "mesher must be 'auto', 'delaunay', 'poisson', or 'advancing-front'"
        )
    if not make_mesh and mesher != "auto":
        raise ValueError("an explicit mesher cannot be used when make_mesh is false")
    if mesher in {"poisson", "advancing-front"} and any(
        value is not None
        for value in (
            delaunay_max_proj_dist,
            delaunay_max_depth_dist,
            delaunay_num_threads,
        )
    ):
        raise ValueError("Delaunay tuning options require --mesher auto or delaunay")
    if mapper_ba_global_frames_ratio is not None and mapper_ba_global_frames_ratio <= 1:
        raise ValueError("mapper_ba_global_frames_ratio must be greater than 1")
    if mapper_ba_global_points_ratio is not None and mapper_ba_global_points_ratio <= 1:
        raise ValueError("mapper_ba_global_points_ratio must be greater than 1")
    if mapper_ba_global_max_refinements is not None and mapper_ba_global_max_refinements < 1:
        raise ValueError("mapper_ba_global_max_refinements must be at least 1")
    for option_name, option_value in (
        ("mapper_ba_local_max_num_iterations", mapper_ba_local_max_num_iterations),
        ("mapper_ba_global_max_num_iterations", mapper_ba_global_max_num_iterations),
    ):
        if option_value is not None and option_value < 1:
            raise ValueError(f"{option_name} must be at least 1")
    mapper_tuning_requested = any((
        mapper_single_model,
        mapper_no_extract_colors,
        mapper_ba_global_frames_ratio is not None,
        mapper_ba_global_points_ratio is not None,
        mapper_ba_global_max_refinements is not None,
        mapper_ba_global_ignore_redundant_points3d,
        mapper_ba_local_max_num_iterations is not None,
        mapper_ba_global_max_num_iterations is not None,
    ))
    if mapper_mode == "global" and mapper_tuning_requested:
        raise ValueError("incremental Mapper tuning options cannot be used with mapper_mode='global'")
    if dense_frame_stride < 1:
        raise ValueError("dense_frame_stride must be at least 1")
    if dense_anchor_mode not in {"uniform", "adaptive"}:
        raise ValueError("dense_anchor_mode must be 'uniform' or 'adaptive'")
    if dense_anchor_mode == "adaptive" and frame_manifest is None:
        raise ValueError("adaptive dense anchors require frame_manifest")
    if dense_target_references is not None and dense_target_references < 2:
        raise ValueError("dense_target_references must be at least 2")
    if dense_target_references is not None and dense_frame_stride != 1:
        raise ValueError("dense_target_references requires dense_frame_stride=1")
    if dense_source_images is not None and dense_source_images < 2:
        raise ValueError("dense_source_images must be at least 2")
    if dense_max_image_size is not None and dense_max_image_size < 320:
        raise ValueError("dense_max_image_size must be at least 320")
    if dense_num_iterations is not None and dense_num_iterations < 1:
        raise ValueError("dense_num_iterations must be positive")
    if dense_num_samples is not None and dense_num_samples < 1:
        raise ValueError("dense_num_samples must be positive")
    if dense_window_step is not None and dense_window_step < 1:
        raise ValueError("dense_window_step must be positive")
    if delaunay_max_proj_dist is not None and delaunay_max_proj_dist < 0:
        raise ValueError("delaunay_max_proj_dist must be non-negative")
    if not (
        delaunay_max_depth_dist is None or 0 <= delaunay_max_depth_dist <= 1
    ):
        raise ValueError("delaunay_max_depth_dist must be between 0 and 1")
    if delaunay_num_threads is not None and delaunay_num_threads < -1:
        raise ValueError("delaunay_num_threads must be -1 or a positive integer")
    if delaunay_num_threads == 0:
        raise ValueError("delaunay_num_threads cannot be zero")
    if not images_dir.is_dir() or not any(images_dir.glob("*.jpg")):
        raise FileNotFoundError(f"No JPG frames found in {images_dir}")
    if not references_path.is_file():
        raise FileNotFoundError(references_path)
    workspace.mkdir(parents=True, exist_ok=True)
    colmap = _require_colmap()
    report: dict = {
        "quality": quality,
        "mapper_mode": mapper_mode,
        "gps_prior_std_m": gps_prior_std_m if mapper_mode == "pose-prior" else None,
        "gps_prior_uncertainty_m": {
            "x": gps_prior_horizontal_std_m,
            "y": gps_prior_horizontal_std_m,
            "z": gps_prior_vertical_std_m,
        } if mapper_mode == "pose-prior" else None,
        "camera_calibration": camera_calibration,
        "spatial_matching": spatial_matching,
        "spatial_max_distance_m": spatial_max_distance_m if spatial_matching else None,
        "feature_type": feature_type,
        "feature_matcher": feature_matcher,
        "feature_type_colmap": feature_type_enum,
        "feature_matcher_colmap": feature_matcher_enum,
        "dense_frame_stride": dense_frame_stride,
        "dense_anchor_mode": dense_anchor_mode,
        "dense_target_references": dense_target_references,
        "dense_source_images": dense_source_images,
        "dense_max_image_size": dense_max_image_size,
        "dense_num_iterations": dense_num_iterations,
        "dense_num_samples": dense_num_samples,
        "dense_window_step": dense_window_step,
        "delaunay_max_proj_dist": delaunay_max_proj_dist,
        "delaunay_max_depth_dist": delaunay_max_depth_dist,
        "delaunay_num_threads": delaunay_num_threads,
        "mesher_requested": mesher,
        "mapper_ba_gpu_requested": mapper_ba_gpu,
        "mapper_tuning": {
            "single_model": mapper_single_model,
            "extract_colors": not mapper_no_extract_colors,
            "ba_global_frames_ratio": mapper_ba_global_frames_ratio,
            "ba_global_points_ratio": mapper_ba_global_points_ratio,
            "ba_global_max_refinements": mapper_ba_global_max_refinements,
            "ba_global_ignore_redundant_points3d": (
                mapper_ba_global_ignore_redundant_points3d
            ),
            "ba_local_max_num_iterations": mapper_ba_local_max_num_iterations,
            "ba_global_max_num_iterations": mapper_ba_global_max_num_iterations,
        },
        "sparse_only": sparse_only,
        "workspace": str(workspace),
        "stages": {},
        "_log_dir": str(workspace / "logs"),
        "_report_path": str(workspace / "run_report.partial.json"),
    }
    database = workspace / "database.db"
    sparse_root = workspace / "sparse"
    aligned = workspace / "aligned"
    dense = workspace / "dense"
    for directory in (sparse_root, aligned):
        directory.mkdir(parents=True, exist_ok=True)

    feature_gpu = (
        "--FeatureExtraction.use_gpu"
        if _help_has(colmap, "feature_extractor", "--FeatureExtraction.use_gpu")
        else "--SiftExtraction.use_gpu"
    )
    matching_gpu = (
        "--FeatureMatching.use_gpu"
        if _help_has(colmap, "sequential_matcher", "--FeatureMatching.use_gpu")
        else "--SiftMatching.use_gpu"
    )
    mask_options = ["--ImageReader.mask_path", str(Path(masks_dir))] if masks_dir else []
    image_reader_options = colmap_image_reader_options(camera_calibration)
    feature_type_options = []
    if feature_type != "sift" or _help_has(
        colmap, "feature_extractor", "--FeatureExtraction.type"
    ):
        if not _help_has(colmap, "feature_extractor", "--FeatureExtraction.type"):
            raise PipelineError(
                "Installed COLMAP does not support --FeatureExtraction.type; "
                "use SIFT or install a current ONNX-enabled COLMAP build"
            )
        feature_type_options = ["--FeatureExtraction.type", feature_type_enum]
    matching_type_options = []
    if feature_matcher != "bruteforce" or feature_type != "sift" or _help_has(
        colmap, "sequential_matcher", "--FeatureMatching.type"
    ):
        if not _help_has(colmap, "sequential_matcher", "--FeatureMatching.type"):
            raise PipelineError(
                "Installed COLMAP does not support --FeatureMatching.type; "
                "use SIFT brute-force or install a current ONNX-enabled COLMAP build"
            )
        matching_type_options = ["--FeatureMatching.type", feature_matcher_enum]
    run_command(
        "feature_extraction",
        [
            colmap,
            "feature_extractor",
            "--database_path",
            str(database),
            "--image_path",
            str(images_dir),
            *image_reader_options,
            *mask_options,
            *feature_type_options,
            feature_gpu,
            "1",
        ],
        report,
    )
    run_command(
        "sequential_matching",
        [
            colmap,
            "sequential_matcher",
            "--database_path",
            str(database),
            "--SequentialMatching.overlap",
            "10" if quality == "draft" else "20",
            *matching_type_options,
            matching_gpu,
            "1",
        ],
        report,
    )
    if spatial_matching:
        import subprocess

        spatial_help_result = subprocess.run(
            [colmap, "spatial_matcher", "--help"],
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
        )
        if spatial_help_result.returncode != 0:
            raise PipelineError("This COLMAP build does not support spatial_matcher")
        spatial_help = (spatial_help_result.stdout or "") + (spatial_help_result.stderr or "")
        spatial_options = []
        if "SpatialMatching.max_distance" in spatial_help:
            spatial_options += ["--SpatialMatching.max_distance", str(spatial_max_distance_m)]
        run_command(
            "spatial_matching",
            [
                colmap,
                "spatial_matcher",
                "--database_path",
                str(database),
                *matching_type_options,
                *spatial_options,
            ],
            report,
        )
    mapper_command_name = (
        "pose_prior_mapper" if mapper_mode == "pose-prior"
        else "global_mapper" if mapper_mode == "global"
        else "mapper"
    )
    mapper_help = ""
    if mapper_mode in {"pose-prior", "global"} or mapper_ba_gpu or mapper_tuning_requested:
        import subprocess

        mapper_help_result = subprocess.run(
            [colmap, mapper_command_name, "--help"],
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
        )
        mapper_help = (mapper_help_result.stdout or "") + (mapper_help_result.stderr or "")
        if mapper_help_result.returncode != 0 and mapper_mode in {"pose-prior", "global"}:
            raise PipelineError(
                f"This COLMAP build does not support {mapper_command_name}; use a current COLMAP build"
            )
    if mapper_mode == "global":
        calibrator_help = __import__("subprocess").run(
            [colmap, "view_graph_calibrator", "--help"],
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
        )
        if calibrator_help.returncode != 0:
            raise PipelineError(
                "Global SfM requires COLMAP view_graph_calibrator for this controlled experiment"
            )
        run_command(
            "view_graph_calibration",
            [colmap, "view_graph_calibrator", "--database_path", str(database)],
            report,
        )

    mapper_options = [] if mapper_mode == "global" else [
        "--Mapper.ba_refine_focal_length",
        "0" if camera_calibration and camera_calibration.get("fixed_intrinsics") else "1",
    ]
    if mapper_mode != "global" and camera_calibration and camera_calibration.get("fixed_intrinsics"):
        mapper_options += [
            "--Mapper.ba_refine_principal_point", "0",
            "--Mapper.ba_refine_extra_params", "0",
        ]
    if mapper_mode == "pose-prior" and "overwrite_priors_covariance" in mapper_help:
        mapper_options += ["--overwrite_priors_covariance", "1"]
        for axis, uncertainty in (
            ("x", gps_prior_horizontal_std_m),
            ("y", gps_prior_horizontal_std_m),
            ("z", gps_prior_vertical_std_m),
        ):
            mapper_options += [f"--prior_position_std_{axis}", str(uncertainty)]
    requested_mapper_options: list[tuple[str, str]] = []
    if mapper_single_model:
        requested_mapper_options.append(("--Mapper.multiple_models", "0"))
    if mapper_no_extract_colors:
        requested_mapper_options.append(("--Mapper.extract_colors", "0"))
    if mapper_ba_global_frames_ratio is not None:
        requested_mapper_options.append(
            ("--Mapper.ba_global_frames_ratio", str(mapper_ba_global_frames_ratio))
        )
    if mapper_ba_global_points_ratio is not None:
        requested_mapper_options.append(
            ("--Mapper.ba_global_points_ratio", str(mapper_ba_global_points_ratio))
        )
    if mapper_ba_global_max_refinements is not None:
        requested_mapper_options.append(
            ("--Mapper.ba_global_max_refinements", str(mapper_ba_global_max_refinements))
        )
    if mapper_ba_global_ignore_redundant_points3d:
        requested_mapper_options.append(
            ("--Mapper.ba_global_ignore_redundant_points3D", "1")
        )
    if mapper_ba_local_max_num_iterations is not None:
        requested_mapper_options.append(
            ("--Mapper.ba_local_max_num_iterations", str(mapper_ba_local_max_num_iterations))
        )
    if mapper_ba_global_max_num_iterations is not None:
        requested_mapper_options.append(
            ("--Mapper.ba_global_max_num_iterations", str(mapper_ba_global_max_num_iterations))
        )
    for option, value in requested_mapper_options:
        if option.lstrip("-") not in mapper_help:
            raise PipelineError(
                f"Installed COLMAP {mapper_command_name} does not support requested option {option}"
            )
        mapper_options += [option, value]
    ba_gpu_options = []
    if mapper_mode == "global":
        for option in ("--GlobalMapper.gp_use_gpu", "--GlobalMapper.ba_ceres_use_gpu"):
            if option.lstrip("-") in mapper_help:
                ba_gpu_options.append(option)
        if mapper_ba_gpu:
            for option in ba_gpu_options:
                mapper_options += [option, "1"]
        ba_gpu_option_name = ",".join(ba_gpu_options) if ba_gpu_options else None
    else:
        ba_gpu_option = re.search(r"(--[\w.]*ba_use_gpu)\b", mapper_help)
        if mapper_ba_gpu and ba_gpu_option:
            mapper_options += [ba_gpu_option.group(1), "1"]
        ba_gpu_options = [ba_gpu_option.group(1)] if ba_gpu_option else []
        ba_gpu_option_name = ba_gpu_option.group(1) if ba_gpu_option else None
    report["mapper_ba_gpu"] = {
        "requested": mapper_ba_gpu,
        "supported": bool(ba_gpu_options),
        "enabled": bool(mapper_ba_gpu and ba_gpu_options),
        "option": ba_gpu_option_name,
    }
    run_command(
        "sparse_mapping",
        [
            colmap,
            mapper_command_name,
            "--database_path",
            str(database),
            "--image_path",
            str(images_dir),
            "--output_path",
            str(sparse_root),
            *mapper_options,
        ],
        report,
    )
    sparse_model = _largest_model(sparse_root)
    analyzer_output = run_command(
        "sparse_analysis", [colmap, "model_analyzer", "--path", str(sparse_model)], report
    )
    registered = re.search(r"Registered images:\s*(\d+)", analyzer_output)
    reprojection = re.search(r"Mean reprojection error:\s*([\d.]+)", analyzer_output)
    report["sparse_metrics"] = {
        "registered_images": int(registered.group(1)) if registered else None,
        "mean_reprojection_error_px": float(reprojection.group(1)) if reprojection else None,
    }

    align_command = [
        colmap,
        "model_aligner",
        "--input_path",
        str(sparse_model),
        "--output_path",
        str(aligned),
        "--ref_images_path",
        str(references_path),
        "--ref_is_gps",
        "1",
        "--alignment_type",
        "enu",
    ]
    if _help_has(colmap, "model_aligner", "--alignment_max_error"):
        align_command += ["--alignment_max_error", "5.0"]
    run_command("gps_alignment", align_command, report)
    aligned_text = workspace / "aligned_text"
    aligned_text.mkdir(parents=True, exist_ok=True)
    run_command(
        "aligned_model_text_export",
        [
            colmap,
            "model_converter",
            "--input_path",
            str(aligned),
            "--output_path",
            str(aligned_text),
            "--output_type",
            "TXT",
        ],
        report,
    )
    if sparse_only:
        report["outputs"] = {
            "sparse_model": str(sparse_model),
            "aligned_model": str(aligned),
            "aligned_images_txt": str(aligned_text / "images.txt"),
        }
        report["total_seconds"] = round(
            sum(stage["seconds"] for stage in report["stages"].values()), 2
        )
        public_report = {key: value for key, value in report.items() if not key.startswith("_")}
        write_json(workspace / "run_report.json", public_report)
        return public_report
    run_command(
        "image_undistortion",
        [
            colmap,
            "image_undistorter",
            "--image_path",
            str(images_dir),
            "--input_path",
            str(aligned),
            "--output_path",
            str(dense),
            "--output_type",
            "COLMAP",
        ],
        report,
    )
    report["dense_reference_selection"] = _subsample_patch_match_references(
        dense,
        dense_frame_stride,
        selection_mode=dense_anchor_mode,
        frame_manifest=frame_manifest,
        max_source_images=dense_source_images,
        target_references=dense_target_references,
    )
    patch_size = dense_max_image_size or (1200 if quality == "draft" else 2000)
    patch_options = [
        "--PatchMatchStereo.max_image_size", str(patch_size),
        "--PatchMatchStereo.geom_consistency", "false" if quality == "draft" else "true",
        "--PatchMatchStereo.filter", "true",
    ]
    if dense_num_iterations is not None:
        patch_options += ["--PatchMatchStereo.num_iterations", str(dense_num_iterations)]
    if dense_num_samples is not None:
        patch_options += ["--PatchMatchStereo.num_samples", str(dense_num_samples)]
    if dense_window_step is not None:
        if not _help_has(colmap, "patch_match_stereo", "--PatchMatchStereo.window_step"):
            raise PipelineError("Installed COLMAP does not support --PatchMatchStereo.window_step")
        patch_options += ["--PatchMatchStereo.window_step", str(dense_window_step)]
    fusion_options = []
    if dense_max_image_size is not None and _help_has(
        colmap, "stereo_fusion", "--StereoFusion.max_image_size"
    ):
        fusion_options = ["--StereoFusion.max_image_size", str(dense_max_image_size)]
    run_command(
        "dense_stereo",
        [
            colmap,
            "patch_match_stereo",
            "--workspace_path",
            str(dense),
            "--workspace_format",
            "COLMAP",
            "--PatchMatchStereo.gpu_index",
            "0",
            *patch_options,
        ],
        report,
    )
    fused = dense / "fused.ply"
    run_command(
        "stereo_fusion",
        [
            colmap,
            "stereo_fusion",
            "--workspace_path",
            str(dense),
            "--workspace_format",
            "COLMAP",
            "--input_type",
            "geometric" if quality == "full" else "photometric",
            "--output_path",
            str(fused),
            "--StereoFusion.min_num_pixels",
            "5",
            *fusion_options,
        ],
        report,
    )
    mesh = dense / "mesh.ply"
    textured_mesh = None
    texture_image = None
    if make_mesh:
        delaunay_options = []
        requested_delaunay_options = [
            ("--DelaunayMeshing.max_proj_dist", delaunay_max_proj_dist),
            ("--DelaunayMeshing.max_depth_dist", delaunay_max_depth_dist),
            ("--DelaunayMeshing.num_threads", delaunay_num_threads),
        ]
        for option, value in requested_delaunay_options:
            if value is None:
                continue
            if not _help_has(colmap, "delaunay_mesher", option):
                raise PipelineError(f"Installed COLMAP does not support requested option {option}")
            delaunay_options += [option, str(value)]
        selected_mesher = (
            "delaunay" if mesher == "auto" and quality == "draft"
            else "poisson" if mesher == "auto"
            else mesher
        )
        if selected_mesher == "delaunay":
            # Delaunay is the fast, robust preview mesher. COLMAP 4.2's
            # Poisson surface trimmer can segfault on otherwise valid clouds.
            run_command(
                "delaunay_meshing",
                [
                    colmap,
                    "delaunay_mesher",
                    "--input_path",
                    str(dense),
                    "--output_path",
                    str(mesh),
                    "--input_type",
                    "dense",
                    *delaunay_options,
                ],
                report,
            )
            report["meshing_method"] = (
                "delaunay_draft" if mesher == "auto" else "delaunay"
            )
        elif selected_mesher == "advancing-front":
            import subprocess

            advancing_help = subprocess.run(
                [colmap, "advancing_front_mesher", "--help"],
                capture_output=True,
                text=True,
                errors="replace",
                check=False,
            )
            if advancing_help.returncode != 0:
                raise PipelineError(
                    "Installed COLMAP does not provide advancing_front_mesher; "
                    "install a current CGAL-enabled build"
                )
            run_command(
                "advancing_front_meshing",
                [
                    colmap,
                    "advancing_front_mesher",
                    "--input_path",
                    str(dense),
                    "--output_path",
                    str(mesh),
                ],
                report,
            )
            report["meshing_method"] = "advancing_front"
        else:
            try:
                run_command(
                    "poisson_meshing",
                    [colmap, "poisson_mesher", "--input_path", str(fused), "--output_path", str(mesh)],
                    report,
                )
                report["meshing_method"] = "poisson"
            except PipelineError as error:
                if mesher == "poisson":
                    raise
                report["poisson_meshing_error"] = str(error)
                run_command(
                    "delaunay_meshing",
                    [
                        colmap,
                        "delaunay_mesher",
                        "--input_path",
                        str(dense),
                        "--output_path",
                        str(mesh),
                        "--input_type",
                        "dense",
                        *delaunay_options,
                    ],
                    report,
                )
                report["meshing_method"] = "delaunay_fallback"
        cleaned_mesh = dense / "mesh_cleaned.ply"
        report["mesh_cleanup"] = _clean_mesher_output(mesh, cleaned_mesh, report)
        mesh = cleaned_mesh
        if _help_has(colmap, "mesh_texturer", "--output_path"):
            textured_dir = dense / "textured"
            try:
                run_command(
                    "mesh_texturing",
                    [
                        colmap,
                        "mesh_texturer",
                        "--workspace_path",
                        str(dense),
                        "--input_path",
                        str(mesh),
                        "--output_path",
                        str(textured_dir),
                    ],
                    report,
                )
                candidate_mesh = textured_dir / "mesh.ply"
                candidate_texture = textured_dir / "texture.png"
                textured_mesh = candidate_mesh if candidate_mesh.is_file() else None
                texture_image = candidate_texture if candidate_texture.is_file() else None
            except PipelineError as error:
                # Geometry remains useful if a particular COLMAP build cannot
                # texture a cleaned PLY; report the failure without losing it.
                report["mesh_texturing_error"] = str(error)
    report["outputs"] = {
        "point_cloud_ply": str(fused),
        "mesh_ply": str(mesh) if make_mesh else None,
        "textured_mesh_ply": str(textured_mesh) if textured_mesh else None,
        "texture_image": str(texture_image) if texture_image else None,
        "aligned_images_txt": str(aligned_text / "images.txt"),
    }
    report["total_seconds"] = round(sum(stage["seconds"] for stage in report["stages"].values()), 2)
    public_report = {key: value for key, value in report.items() if not key.startswith("_")}
    write_json(workspace / "run_report.json", public_report)
    return public_report
