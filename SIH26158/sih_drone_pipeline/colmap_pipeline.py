from __future__ import annotations

import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

from .utils import PipelineError, run_command, write_json


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


def reconstruct(
    images_dir: str | Path,
    references_path: str | Path,
    workspace: str | Path,
    quality: str = "draft",
    make_mesh: bool = True,
    masks_dir: str | Path | None = None,
) -> dict:
    """Run an ordered, GPS-aligned COLMAP reconstruction suitable for Colab GPU."""
    images_dir, references_path, workspace = Path(images_dir), Path(references_path), Path(workspace)
    if quality not in {"draft", "full"}:
        raise ValueError("quality must be 'draft' or 'full'")
    if not images_dir.is_dir() or not any(images_dir.glob("*.jpg")):
        raise FileNotFoundError(f"No JPG frames found in {images_dir}")
    if not references_path.is_file():
        raise FileNotFoundError(references_path)
    workspace.mkdir(parents=True, exist_ok=True)
    colmap = _require_colmap()
    report: dict = {
        "quality": quality,
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
    run_command(
        "feature_extraction",
        [
            colmap,
            "feature_extractor",
            "--database_path",
            str(database),
            "--image_path",
            str(images_dir),
            "--ImageReader.single_camera",
            "1",
            "--ImageReader.camera_model",
            "OPENCV",
            *mask_options,
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
            matching_gpu,
            "1",
        ],
        report,
    )
    run_command(
        "sparse_mapping",
        [
            colmap,
            "mapper",
            "--database_path",
            str(database),
            "--image_path",
            str(images_dir),
            "--output_path",
            str(sparse_root),
            "--Mapper.ba_refine_focal_length",
            "1",
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
    patch_options = (
        ["--PatchMatchStereo.max_image_size", "1200", "--PatchMatchStereo.geom_consistency", "false"]
        if quality == "draft"
        else ["--PatchMatchStereo.max_image_size", "2000", "--PatchMatchStereo.geom_consistency", "true"]
    )
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
        ],
        report,
    )
    mesh = dense / "mesh.ply"
    textured_mesh = None
    texture_image = None
    if make_mesh:
        if quality == "draft":
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
                ],
                report,
            )
            report["meshing_method"] = "delaunay_draft"
        else:
            try:
                run_command(
                    "poisson_meshing",
                    [colmap, "poisson_mesher", "--input_path", str(fused), "--output_path", str(mesh)],
                    report,
                )
                report["meshing_method"] = "poisson"
            except PipelineError as error:
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
