from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np

from .utils import PipelineError, write_json


def _run(args: argparse.Namespace) -> int:
    from .ai_masking import mask_dynamic_objects
    from .colmap_pipeline import reconstruct
    from .export_gis import export_products
    from .extract_keyframes import extract_keyframes
    from .telemetry import load_telemetry, write_frame_references
    from .validation import (
        gps_alignment_report, ground_truth_trajectory_report,
        independent_distance_report, surveyed_checkpoint_report,
    )

    started = time.perf_counter()
    output_dir = Path(args.output).resolve()
    workspace = Path(args.workspace).resolve()
    frames_dir = workspace / "images"
    frames_manifest = workspace / "frames.csv"
    output_dir.mkdir(parents=True, exist_ok=True)

    workflow_steps = {}
    step_started = time.perf_counter()
    print("1/5 Extracting ordered keyframes")
    frames = extract_keyframes(
        args.video,
        frames_dir,
        target_frames=args.target_frames,
        max_width=args.max_width,
        manifest_path=frames_manifest,
        sample_fps=args.sample_fps,
        max_frames=args.max_frames or (600 if args.quality == "draft" else 1200),
    )
    selection_path = frames_manifest.with_suffix(".selection.json")
    selection = json.loads(selection_path.read_text(encoding="utf-8")) if selection_path.is_file() else {}
    workflow_steps["keyframe_extraction"] = {
        "status": "passed", "seconds": round(time.perf_counter() - step_started, 2), "frames": len(frames),
        "sharpness_median": float(np.median([frame.sharpness for frame in frames])),
        "motion_score_median": float(np.median([frame.motion_score for frame in frames])),
        **selection,
    }
    step_started = time.perf_counter()
    telemetry = load_telemetry(args.telemetry)
    references = workspace / "frame_gps.txt"
    geo = write_frame_references(frames, telemetry, references)
    workflow_steps["telemetry_sync"] = {
        "status": "passed", "seconds": round(time.perf_counter() - step_started, 2),
        "samples": len(telemetry), "frame_references": geo["count"],
    }
    print(f"Prepared {len(frames)} frames and {geo['count']} GPS references")

    masks_dir = None
    ai_mask_report = None
    if args.ai_mask_dynamic:
        step_started = time.perf_counter()
        print("Applying AI segmentation masks to people, vehicles and animals")
        masks_dir = workspace / "masks"
        ai_mask_report = mask_dynamic_objects(frames_dir, masks_dir)
        workflow_steps["ai_dynamic_masking"] = {
            "status": "passed", "seconds": round(time.perf_counter() - step_started, 2), **ai_mask_report,
        }
    else:
        workflow_steps["ai_dynamic_masking"] = {"status": "skipped", "seconds": 0.0}

    print("2/5 Reconstructing and GPS-aligning with COLMAP")
    report = reconstruct(
        frames_dir,
        references,
        workspace,
        args.quality,
        make_mesh=not args.no_mesh,
        masks_dir=masks_dir,
    )
    logs_source = workspace / "logs"
    logs_target = output_dir / "logs"
    if logs_source.is_dir():
        shutil.copytree(logs_source, logs_target, dirs_exist_ok=True)
        for stage in report.get("stages", {}).values():
            if stage.get("log_file"):
                stage["log_file"] = str(logs_target / Path(stage["log_file"]).name)
    report["input"] = {
        "video": str(Path(args.video).resolve()),
        "telemetry": str(Path(args.telemetry).resolve()),
        "frames": len(frames),
    }
    report["georeference"] = geo
    report["ai_dynamic_masking"] = ai_mask_report
    report["workflow_steps"] = workflow_steps
    registered = report.get("sparse_metrics", {}).get("registered_images")
    report["sparse_metrics"]["input_frames"] = len(frames)
    report["sparse_metrics"]["registration_percent"] = (
        round(100 * registered / len(frames), 2) if registered is not None else None
    )

    print("3/5 Calculating GPS alignment diagnostics")
    step_started = time.perf_counter()
    validation = gps_alignment_report(
        report["outputs"]["aligned_images_txt"], frames_manifest, telemetry, geo["origin"]
    )
    if args.validation_distances:
        validation["independent_distances"] = independent_distance_report(args.validation_distances)
    if args.validation_checkpoints:
        validation["surveyed_checkpoints"] = surveyed_checkpoint_report(args.validation_checkpoints)
    if args.ground_truth_trajectory:
        validation["ground_truth_trajectory"] = ground_truth_trajectory_report(
            report["outputs"]["aligned_images_txt"], frames_manifest, args.ground_truth_trajectory
        )
    workflow_steps["validation"] = {"status": "passed", "seconds": round(time.perf_counter() - step_started, 2)}
    report["validation"] = validation

    print("4/5 Exporting GIS and viewer products")
    step_started = time.perf_counter()
    products = export_products(
        report["outputs"]["point_cloud_ply"],
        report["outputs"]["mesh_ply"],
        output_dir,
        geo["origin"],
        dsm_resolution_m=args.dsm_resolution,
        origin_policy=geo["origin_policy"],
        textured_mesh_path=report["outputs"].get("textured_mesh_ply"),
        texture_path=report["outputs"].get("texture_image"),
    )
    shutil.copy2(frames_manifest, output_dir / "frames.csv")
    if selection_path.is_file():
        shutil.copy2(selection_path, output_dir / "frames.selection.json")
    workflow_steps["product_export"] = {"status": "passed", "seconds": round(time.perf_counter() - step_started, 2)}
    report["products"] = products
    report["wall_clock_seconds"] = round(time.perf_counter() - started, 2)
    checkpoint_pass = validation.get("surveyed_checkpoints", {}).get("passes_one_metre_target")
    distance_pass = validation.get("independent_distances", {}).get("passes_one_metre_target")
    independent_pass = checkpoint_pass if checkpoint_pass is not None else distance_pass
    trajectory_pass = validation.get("ground_truth_trajectory", {}).get("passes_one_metre_position_target")
    absolute_gps_pass = validation.get("gps_alignment_rmse_m", float("inf")) <= 1.0
    report["targets"] = {
        "processing_under_15_minutes": report["wall_clock_seconds"] < 900,
        # Camera-trajectory agreement is useful validation, but it cannot prove
        # surface accuracy. Only independent surveyed scene measurements can.
        "one_metre_accuracy": independent_pass,
        "one_metre_surface_accuracy": independent_pass,
        "one_metre_absolute_camera_alignment": absolute_gps_pass,
        "one_metre_relative_trajectory": trajectory_pass,
        "accuracy_evidence": (
            "independent surveyed 3D checkpoints"
            if checkpoint_pass is not None
            else "independent surveyed distances"
            if distance_pass is not None
            else "none - camera trajectory is diagnostic only; supply surveyed distances or ground control"
        ),
    }
    write_json(output_dir / "run_report.json", report)
    write_json(output_dir / "viewer_metadata.json", {
        "origin": geo["origin"],
        "crs": products["crs"],
        "validation": validation,
        "processing_seconds": report["wall_clock_seconds"],
        "registration_percent": report["sparse_metrics"]["registration_percent"],
        "products": {
            **products,
            "las": "point_cloud.las",
            "geotiff_dsm": "dsm.tif",
            "glb": "model.glb" if products.get("glb") else None,
            "obj": "model.obj" if products.get("obj") else None,
            "mesh_ply": "mesh.ply" if products.get("mesh_ply") else None,
        },
    })
    print("5/5 Complete")
    print(f"Outputs: {output_dir}")
    return 0


def _preflight(args: argparse.Namespace) -> int:
    from .preflight import inspect_environment

    result = inspect_environment(args.video, args.telemetry, args.workspace)
    write_json(Path(args.output), result)
    print(Path(args.output).read_text(encoding="utf-8"))
    return 0 if result["ready"] else 2


def _verify(args: argparse.Namespace) -> int:
    from .verify_outputs import verify_output_directory

    result = verify_output_directory(args.output)
    print(__import__("json").dumps(result, indent=2))
    return 0 if result["artifact_checks_pass"] else 2


def _validate_checkpoints(args: argparse.Namespace) -> int:
    """Attach post-reconstruction surveyed checkpoint evidence without rerunning MVS."""
    import json
    from .validation import surveyed_checkpoint_report

    output_dir = Path(args.output).resolve()
    report_path = output_dir / "run_report.json"
    if not report_path.is_file():
        raise FileNotFoundError(report_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    checkpoint_report = surveyed_checkpoint_report(args.checkpoints)
    report.setdefault("validation", {})["surveyed_checkpoints"] = checkpoint_report
    report.setdefault("targets", {})["one_metre_accuracy"] = checkpoint_report["passes_one_metre_target"]
    report["targets"]["one_metre_surface_accuracy"] = checkpoint_report["passes_one_metre_target"]
    report["targets"]["accuracy_evidence"] = "independent surveyed 3D checkpoints"
    write_json(report_path, report)
    print(__import__("json").dumps(checkpoint_report, indent=2))
    return 0 if checkpoint_report["passes_one_metre_target"] else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sih-drone",
        description="Single-pass drone video to georeferenced 3D products (SIH26158)",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    run = subcommands.add_parser("run", help="Run the complete Colab reconstruction workflow")
    run.add_argument("--video", required=True, help="1080p/4K drone video")
    run.add_argument("--telemetry", required=True, help="DJI SRT or normalized telemetry CSV")
    run.add_argument("--workspace", default="/content/sih_workspace", help="Fast temporary Colab workspace")
    run.add_argument("--output", required=True, help="Persistent output directory, normally in Google Drive")
    run.add_argument(
        "--target-frames",
        type=int,
        help="Fixed frame budget; omit for duration-adaptive selection",
    )
    run.add_argument("--max-width", type=int, default=1920)
    run.add_argument(
        "--sample-fps", type=float, default=1.0,
        help="Adaptive sampling rate when --target-frames is omitted (default: 1 frame/second)",
    )
    run.add_argument(
        "--max-frames", type=int,
        help="Cap adaptive selection (default: 600 draft, 1200 full)",
    )
    run.add_argument("--quality", choices=("draft", "full"), default="draft")
    run.add_argument("--dsm-resolution", type=float, default=0.5)
    run.add_argument("--no-mesh", action="store_true", help="Generate a point cloud only")
    run.add_argument("--validation-distances", help="Optional independent metric-distance CSV")
    run.add_argument(
        "--validation-checkpoints",
        help="CSV with surveyed and reconstructed XYZ checkpoint coordinates (at least three measured rows)",
    )
    run.add_argument("--ground-truth-trajectory", help="Optional independent time_s,x_m,y_m,z_m trajectory CSV")
    run.add_argument(
        "--ai-mask-dynamic",
        action="store_true",
        help="Use YOLO segmentation to exclude moving people, vehicles and animals",
    )
    run.set_defaults(handler=_run)
    preflight = subcommands.add_parser("preflight", help="Verify GPU, COLMAP, video, telemetry and disk space")
    preflight.add_argument("--video", required=True)
    preflight.add_argument("--telemetry", required=True)
    preflight.add_argument("--workspace", default="/content/sih_workspace")
    preflight.add_argument("--output", required=True, help="Preflight JSON path")
    preflight.set_defaults(handler=_preflight)
    verify = subcommands.add_parser("verify", help="Validate every expected output and stage log")
    verify.add_argument("--output", required=True, help="Completed pipeline output directory")
    verify.set_defaults(handler=_verify)
    checkpoints = subcommands.add_parser(
        "validate-checkpoints",
        help="Attach surveyed surface-checkpoint evidence to an existing reconstruction",
    )
    checkpoints.add_argument("--output", required=True, help="Completed pipeline output directory")
    checkpoints.add_argument("--checkpoints", required=True, help="Populated surveyed/reconstructed XYZ CSV")
    checkpoints.set_defaults(handler=_validate_checkpoints)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        raise SystemExit(args.handler(args))
    except (PipelineError, FileNotFoundError, ValueError, RuntimeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(2) from error
