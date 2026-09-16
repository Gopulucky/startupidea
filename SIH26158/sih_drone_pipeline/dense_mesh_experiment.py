from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from .colmap_pipeline import _subsample_patch_match_references
from .export_gis import clean_mesh_file, export_products
from .geometry_compare import (
    compare_dsm_rasters,
    compare_meshes,
    compare_point_clouds,
    fingerprint_files,
    ply_header_counts,
)


DENSE_CONTROL = "d0_control_1088_i4_s15_src10"
MESH_CONTROL = "m0_proj_20_control"
CACHE_VERSION = 1


def default_dense_configs() -> dict[str, dict[str, Any]]:
    return {
        DENSE_CONTROL: {
            "max_image_size": 1088,
            "iterations": 4,
            "samples": 15,
            "source_images": 10,
            "window_step": 1,
            "stride": 2,
            "target_references": None,
        },
        "d1_iterations_3": {
            "max_image_size": 1088,
            "iterations": 3,
            "samples": 15,
            "source_images": 10,
            "window_step": 1,
            "stride": 2,
            "target_references": None,
        },
        "d2_samples_12": {
            "max_image_size": 1088,
            "iterations": 4,
            "samples": 12,
            "source_images": 10,
            "window_step": 1,
            "stride": 2,
            "target_references": None,
        },
        "d3_sources_8": {
            "max_image_size": 1088,
            "iterations": 4,
            "samples": 15,
            "source_images": 8,
            "window_step": 1,
            "stride": 2,
            "target_references": None,
        },
        "d4_exact_92_references": {
            "max_image_size": 1088,
            "iterations": 4,
            "samples": 15,
            "source_images": 10,
            "window_step": 1,
            "stride": 1,
            "target_references": 92,
        },
        "d5_window_step_2": {
            "max_image_size": 1088,
            "iterations": 4,
            "samples": 15,
            "source_images": 10,
            "window_step": 2,
            "stride": 2,
            "target_references": None,
        },
    }


def default_mesh_configs() -> dict[str, dict[str, float]]:
    return {
        MESH_CONTROL: {"max_proj_dist": 20.0},
        "m1_proj_24": {"max_proj_dist": 24.0},
        "m2_proj_28": {"max_proj_dist": 28.0},
    }


def _read_source_ids(path: Path) -> list[int]:
    with path.open(newline="", encoding="utf-8") as stream:
        return [int(row["source_frame"]) for row in csv.DictReader(stream)]


def _config_hash(config: dict) -> str:
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode("utf-8")).hexdigest()


def _run_logged(command: list[str], log_path: Path, cwd: Path, env: dict) -> tuple[int, float]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    with log_path.open("w", encoding="utf-8") as stream:
        result = subprocess.run(
            command,
            stdout=stream,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=cwd,
            env=env,
        )
    return result.returncode, time.perf_counter() - started


def _remove_local(path: Path, allowed_root: Path = Path("/content")) -> None:
    resolved = path.resolve()
    allowed = allowed_root.resolve()
    if allowed != resolved and allowed not in resolved.parents:
        raise ValueError(f"Refusing to remove path outside {allowed}: {resolved}")
    if path.is_dir():
        shutil.rmtree(path)


@dataclass
class DenseMeshExperiment:
    project_dir: Path
    reference_output: Path
    experiment_root: Path
    local_cache: Path = Path("/content/sih26158_dense_delaunay_cache")
    local_frontend: Path = Path("/content/sih26158_dense_delaunay_frontend")
    local_trial_root: Path = Path("/content/sih26158_dense_delaunay_trials")
    session_id: str = "unknown"

    def __post_init__(self) -> None:
        self.project_dir = Path(self.project_dir)
        self.reference_output = Path(self.reference_output)
        self.experiment_root = Path(self.experiment_root)
        self.cache_root = self.project_dir / "cache"
        self.cache_archive = self.cache_root / "shared_dense_template.tar.gz"
        self.cache_manifest_drive = self.cache_root / "shared_dense_template_manifest.json"
        self.cache_prep_output = self.experiment_root / "shared_sparse_preparation"
        self.dense_template = self.local_cache / "dense_template"
        self.reference = json.loads(
            (self.reference_output / "run_report.json").read_text(encoding="utf-8")
        )
        self.reference_ids = _read_source_ids(self.reference_output / "frames.csv")
        if len(self.reference_ids) != 253:
            raise ValueError("Accepted reference does not contain exactly 253 source frames")
        self.experiment_root.mkdir(parents=True, exist_ok=True)
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self.env = os.environ.copy()
        self.env["PYTHONPATH"] = str(self.project_dir) + os.pathsep + self.env.get(
            "PYTHONPATH", ""
        )

    def cache_files(self) -> list[Path]:
        return [
            self.local_cache / "frames.csv",
            self.dense_template / "sparse" / "cameras.bin",
            self.dense_template / "sparse" / "images.bin",
            self.dense_template / "sparse" / "points3D.bin",
            self.dense_template / "stereo" / "patch-match.full.cfg",
        ]

    def valid_local_cache(self) -> bool:
        manifest_path = self.local_cache / "cache_manifest.json"
        if not manifest_path.is_file() or not all(path.is_file() for path in self.cache_files()):
            return False
        if len(list((self.dense_template / "images").glob("*.jpg"))) < 205:
            return False
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            return bool(
                payload.get("cache_version") == CACHE_VERSION
                and _read_source_ids(self.local_cache / "frames.csv") == self.reference_ids
                and payload.get("fingerprint", {}).get("sha256")
                == fingerprint_files(self.cache_files())["sha256"]
            )
        except Exception:
            return False

    def _restore_cache(self) -> None:
        destination = Path("/content").resolve()
        with tarfile.open(self.cache_archive, "r:gz") as archive:
            for member in archive.getmembers():
                target = (destination / member.name).resolve()
                if target != destination and destination not in target.parents:
                    raise ValueError(f"Unsafe cache member: {member.name}")
            archive.extractall(destination)

    def prepare_cache(self, video: Path, telemetry: Path) -> dict:
        video, telemetry = Path(video), Path(telemetry)
        if not self.valid_local_cache() and self.cache_archive.is_file():
            _remove_local(self.local_cache)
            print("Restoring validated dense-screen cache from Drive...")
            self._restore_cache()
        if not self.valid_local_cache():
            if not video.is_file() or not telemetry.is_file():
                raise FileNotFoundError("Video and telemetry are required to prepare the cache")
            _remove_local(self.local_frontend)
            _remove_local(self.local_cache)
            self.local_cache.mkdir(parents=True)
            self.cache_prep_output.mkdir(parents=True, exist_ok=True)
            command = [
                sys.executable,
                "-m",
                "sih_drone_pipeline",
                "run",
                "--video",
                str(video),
                "--telemetry",
                str(telemetry),
                "--workspace",
                str(self.local_frontend),
                "--output",
                str(self.cache_prep_output),
                "--quality",
                "draft",
                "--target-frames",
                "253",
                "--max-width",
                "1920",
                "--keyframe-mode",
                "geometry",
                "--keyframe-decode-mode",
                "sequential",
                "--mapper",
                "pose-prior",
                "--gps-prior-std-m",
                "5.0",
                "--mapper-ba-gpu",
                "--mapper-no-extract-colors",
                "--mapper-ba-global-frames-ratio",
                "1.4",
                "--mapper-ba-global-points-ratio",
                "1.4",
                "--mapper-ba-global-max-refinements",
                "2",
                "--mapper-ba-global-ignore-redundant-points3d",
                "--sparse-only",
            ]
            print("Preparing shared robust sparse frontend:", " ".join(command))
            result = subprocess.run(command, cwd=self.project_dir, env=self.env)
            if result.returncode != 0:
                raise RuntimeError(f"Sparse preparation failed; inspect {self.cache_prep_output / 'logs'}")
            prep_report = json.loads(
                (self.cache_prep_output / "run_report.json").read_text(encoding="utf-8")
            )
            prepared_ids = _read_source_ids(self.local_frontend / "frames.csv")
            sparse_gates = {
                "same_253_frames": prepared_ids == self.reference_ids and len(prepared_ids) == 253,
                "registered_at_least_205": prep_report["sparse_metrics"]["registered_images"] >= 205,
                "reprojection_within_0_03_px": (
                    prep_report["sparse_metrics"]["mean_reprojection_error_px"]
                    <= self.reference["sparse_metrics"]["mean_reprojection_error_px"] + 0.03
                ),
                "gps_rmse_within_0_15_m": (
                    prep_report["validation"]["gps_alignment_rmse_m"]
                    <= self.reference["validation"]["gps_alignment_rmse_m"] + 0.15
                ),
            }
            if not all(sparse_gates.values()):
                raise RuntimeError(f"Shared sparse cache failed: {sparse_gates}")
            subprocess.run(
                [
                    "colmap",
                    "image_undistorter",
                    "--image_path",
                    str(self.local_frontend / "images"),
                    "--input_path",
                    str(self.local_frontend / "aligned"),
                    "--output_path",
                    str(self.dense_template),
                    "--output_type",
                    "COLMAP",
                ],
                check=True,
            )
            shutil.copy2(self.local_frontend / "frames.csv", self.local_cache / "frames.csv")
            selection = self.local_frontend / "frames.selection.json"
            if selection.is_file():
                shutil.copy2(selection, self.local_cache / selection.name)
            shutil.copy2(
                self.cache_prep_output / "run_report.json",
                self.local_cache / "sparse_prep_report.json",
            )
            patch_cfg = self.dense_template / "stereo" / "patch-match.cfg"
            shutil.copy2(patch_cfg, self.dense_template / "stereo" / "patch-match.full.cfg")
            manifest = {
                "cache_version": CACHE_VERSION,
                "created_utc": datetime.now(timezone.utc).isoformat(),
                "source_frames": 253,
                "registered_images": prep_report["sparse_metrics"]["registered_images"],
                "sparse_gates": sparse_gates,
                "fingerprint": fingerprint_files(self.cache_files()),
            }
            (self.local_cache / "cache_manifest.json").write_text(
                json.dumps(manifest, indent=2), encoding="utf-8"
            )
            temporary_archive = Path("/content/shared_dense_template.tar.gz")
            if temporary_archive.exists():
                temporary_archive.unlink()
            with tarfile.open(temporary_archive, "w:gz") as archive:
                archive.add(self.local_cache, arcname=self.local_cache.name)
            shutil.copy2(temporary_archive, self.cache_archive)
            shutil.copy2(
                self.local_cache / "cache_manifest.json", self.cache_manifest_drive
            )
        if not self.valid_local_cache():
            raise RuntimeError("Cache validation failed")
        return json.loads(
            (self.local_cache / "cache_manifest.json").read_text(encoding="utf-8")
        )

    @property
    def base_fingerprint(self) -> str:
        if not self.valid_local_cache():
            raise RuntimeError("Prepare the validated cache first")
        payload = json.loads(
            (self.local_cache / "cache_manifest.json").read_text(encoding="utf-8")
        )
        return payload["fingerprint"]["sha256"]

    def _clone_dense_template(self, name: str) -> tuple[Path, Path]:
        trial_root = self.local_trial_root / name
        _remove_local(trial_root)
        dense = trial_root / "dense"
        stereo = dense / "stereo"
        stereo.mkdir(parents=True)
        os.symlink(self.dense_template / "images", dense / "images", target_is_directory=True)
        os.symlink(self.dense_template / "sparse", dense / "sparse", target_is_directory=True)
        for cfg in (self.dense_template / "stereo").glob("*.cfg"):
            if cfg.name != "patch-match.cfg":
                shutil.copy2(cfg, stereo / cfg.name)
        shutil.copy2(
            self.dense_template / "stereo" / "patch-match.full.cfg",
            stereo / "patch-match.cfg",
        )
        (stereo / "depth_maps").mkdir()
        (stereo / "normal_maps").mkdir()
        return trial_root, dense

    def _dense_report_reusable(self, path: Path, expected_hash: str) -> bool:
        if not path.is_file():
            return False
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
            return bool(
                report.get("completed") is True
                and report.get("config_hash") == expected_hash
                and report.get("base_fingerprint") == self.base_fingerprint
                and (path.parent / "fused.ply").is_file()
                and (path.parent / "fused.ply.vis").is_file()
                and (path.parent / "products" / "point_cloud.ply").is_file()
                and (path.parent / "products" / "dsm.tif").is_file()
            )
        except Exception:
            return False

    def run_dense_trial(self, name: str, config: dict, force: bool = False) -> dict:
        config = dict(config)
        trial_output = self.experiment_root / "dense_trials" / name
        trial_output.mkdir(parents=True, exist_ok=True)
        report_path = trial_output / "trial_report.json"
        expected_hash = _config_hash(config)
        if not force and self._dense_report_reusable(report_path, expected_hash):
            print("Reusing completed dense trial:", name)
            return json.loads(report_path.read_text(encoding="utf-8"))
        trial_root, dense = self._clone_dense_template(name)
        selection = _subsample_patch_match_references(
            dense,
            config["stride"],
            selection_mode="adaptive",
            frame_manifest=self.local_cache / "frames.csv",
            max_source_images=config["source_images"],
            target_references=config["target_references"],
        )
        cfg_lines = (dense / "stereo" / "patch-match.cfg").read_text(
            encoding="utf-8"
        ).splitlines()
        selected_names = cfg_lines[::2]
        patch_command = [
            "colmap",
            "patch_match_stereo",
            "--workspace_path",
            str(dense),
            "--workspace_format",
            "COLMAP",
            "--PatchMatchStereo.gpu_index",
            "0",
            "--PatchMatchStereo.max_image_size",
            str(config["max_image_size"]),
            "--PatchMatchStereo.geom_consistency",
            "false",
            "--PatchMatchStereo.filter",
            "true",
            "--PatchMatchStereo.num_iterations",
            str(config["iterations"]),
            "--PatchMatchStereo.num_samples",
            str(config["samples"]),
            "--PatchMatchStereo.window_step",
            str(config["window_step"]),
        ]
        print("Running dense trial:", name, "references:", selection["selected_references"])
        patch_code, patch_seconds = _run_logged(
            patch_command, trial_output / "dense_stereo.log", self.project_dir, self.env
        )
        if patch_code != 0:
            raise RuntimeError(f"PatchMatch failed; inspect {trial_output / 'dense_stereo.log'}")
        fused = dense / "fused.ply"
        fusion_command = [
            "colmap",
            "stereo_fusion",
            "--workspace_path",
            str(dense),
            "--workspace_format",
            "COLMAP",
            "--input_type",
            "photometric",
            "--output_path",
            str(fused),
            "--StereoFusion.min_num_pixels",
            "5",
            "--StereoFusion.max_image_size",
            str(config["max_image_size"]),
        ]
        fusion_code, fusion_seconds = _run_logged(
            fusion_command, trial_output / "stereo_fusion.log", self.project_dir, self.env
        )
        visibility = Path(str(fused) + ".vis")
        if fusion_code != 0 or not fused.is_file() or not visibility.is_file():
            raise RuntimeError(f"Fusion failed; inspect {trial_output / 'stereo_fusion.log'}")
        shutil.copy2(fused, trial_output / "fused.ply")
        shutil.copy2(visibility, trial_output / "fused.ply.vis")
        products_dir = trial_output / "products"
        if products_dir.is_dir():
            shutil.rmtree(products_dir)
        products = export_products(
            fused,
            None,
            products_dir,
            self.reference["georeference"]["origin"],
            dsm_resolution_m=0.5,
            origin_policy=self.reference["georeference"]["origin_policy"],
        )
        raw_points, _ = ply_header_counts(fused)
        report: dict[str, Any] = {
            "completed": True,
            "name": name,
            "session_id": self.session_id,
            "base_fingerprint": self.base_fingerprint,
            "config": config,
            "config_hash": expected_hash,
            "selection": selection,
            "selected_reference_names_sha256": hashlib.sha256(
                "\n".join(selected_names).encode("utf-8")
            ).hexdigest(),
            "dense_stereo_seconds": round(patch_seconds, 2),
            "stereo_fusion_seconds": round(fusion_seconds, 2),
            "dense_plus_fusion_seconds": round(patch_seconds + fusion_seconds, 2),
            "raw_fused_points": raw_points,
            "filtered_points": products["point_count"],
            "dsm_valid_fraction": products["dsm"]["valid_fraction"],
            "fused_fingerprint": fingerprint_files(
                [trial_output / "fused.ply", trial_output / "fused.ply.vis"]
            ),
        }
        if name == DENSE_CONTROL:
            report["historical_cloud_comparison"] = compare_point_clouds(
                self.reference_output / "point_cloud.ply", products_dir / "point_cloud.ply"
            )
            report["historical_dsm_comparison"] = compare_dsm_rasters(
                self.reference_output / "dsm.tif", products_dir / "dsm.tif"
            )
            report["quality_gates"] = {"control_generated": True}
            report["quality_pass"] = True
            report["runtime_target_pass"] = False
        else:
            control_output = self.experiment_root / "dense_trials" / DENSE_CONTROL
            control_path = control_output / "trial_report.json"
            control_hash = _config_hash(default_dense_configs()[DENSE_CONTROL])
            if not self._dense_report_reusable(control_path, control_hash):
                raise RuntimeError("Run the D0 dense control first")
            control = json.loads(control_path.read_text(encoding="utf-8"))
            cloud = compare_point_clouds(
                control_output / "products" / "point_cloud.ply",
                products_dir / "point_cloud.ply",
            )
            dsm = compare_dsm_rasters(
                control_output / "products" / "dsm.tif", products_dir / "dsm.tif"
            )
            report["cloud_comparison_to_control"] = cloud
            report["dsm_comparison_to_control"] = dsm
            gates = {
                "raw_points_retain_95_percent": raw_points >= 0.95 * control["raw_fused_points"],
                "filtered_points_retain_95_percent": (
                    products["point_count"] >= 0.95 * control["filtered_points"]
                ),
                "dsm_fraction_retains_95_percent": (
                    products["dsm"]["valid_fraction"] >= 0.95 * control["dsm_valid_fraction"]
                ),
                "cloud_bidirectional_coverage_at_least_95_percent": (
                    cloud["bidirectional_coverage_fraction"] >= 0.95
                ),
                "cloud_symmetric_p95_at_most_0_5m": cloud["symmetric_p95_m"] <= 0.5,
                "dsm_same_crs_and_resolution": dsm["same_crs"] and dsm["same_resolution"],
                "dsm_mask_iou_at_least_90_percent": dsm["valid_mask_iou"] >= 0.90,
                "dsm_reference_coverage_at_least_90_percent": (
                    dsm["reference_mask_coverage"] >= 0.90
                ),
                "dsm_elevation_median_at_most_0_10m": (
                    dsm["elevation_abs_median_m"] <= 0.10
                ),
                "dsm_elevation_p95_at_most_0_50m": dsm["elevation_abs_p95_m"] <= 0.50,
            }
            report["quality_gates"] = gates
            report["quality_pass"] = all(gates.values())
            report["runtime_target_pass"] = (
                report["dense_plus_fusion_seconds"]
                <= 0.85 * control["dense_plus_fusion_seconds"]
            )
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        _remove_local(trial_root)
        return report

    def dense_decision(self, names: list[str]) -> dict:
        reports = []
        for name in names:
            path = self.experiment_root / "dense_trials" / name / "trial_report.json"
            if path.is_file():
                reports.append(json.loads(path.read_text(encoding="utf-8")))
        candidates = [
            report
            for report in reports
            if report["name"] != DENSE_CONTROL
            and report.get("quality_pass")
            and report.get("runtime_target_pass")
        ]
        winner = min(candidates, key=lambda item: item["dense_plus_fusion_seconds"]) if candidates else None
        decision = {
            "control": next((item for item in reports if item["name"] == DENSE_CONTROL), None),
            "trials_completed": [item["name"] for item in reports],
            "winner": winner,
            "screen_pass": winner is not None,
            "runtime_target": "at least 15% faster PatchMatch plus fusion than D0",
            "surface_accuracy": "Comparative consistency only; surveyed accuracy is not evaluated.",
        }
        (self.experiment_root / "dense_decision.json").write_text(
            json.dumps(decision, indent=2), encoding="utf-8"
        )
        return decision

    def _mesh_report_reusable(
        self, path: Path, expected_hash: str, fused_fingerprint: str
    ) -> bool:
        if not path.is_file():
            return False
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
            return bool(
                report.get("completed") is True
                and report.get("config_hash") == expected_hash
                and report.get("fused_fingerprint") == fused_fingerprint
                and (path.parent / "mesh_raw.ply").is_file()
                and (path.parent / "mesh_cleaned.ply").is_file()
            )
        except Exception:
            return False

    def run_mesh_trial(
        self,
        name: str,
        config: dict,
        dense_winner_name: str,
        force: bool = False,
    ) -> dict:
        config = dict(config)
        dense_output = self.experiment_root / "dense_trials" / dense_winner_name
        fused = dense_output / "fused.ply"
        visibility = dense_output / "fused.ply.vis"
        fused_fingerprint = fingerprint_files([fused, visibility])["sha256"]
        output = self.experiment_root / "mesh_trials" / name
        output.mkdir(parents=True, exist_ok=True)
        report_path = output / "trial_report.json"
        expected_hash = _config_hash(config)
        if not force and self._mesh_report_reusable(
            report_path, expected_hash, fused_fingerprint
        ):
            print("Reusing completed mesh trial:", name)
            return json.loads(report_path.read_text(encoding="utf-8"))
        trial_root = self.local_trial_root / f"mesh_{name}"
        _remove_local(trial_root)
        dense = trial_root / "dense"
        dense.mkdir(parents=True)
        os.symlink(self.dense_template / "sparse", dense / "sparse", target_is_directory=True)
        shutil.copy2(fused, dense / "fused.ply")
        shutil.copy2(visibility, dense / "fused.ply.vis")
        raw_mesh = trial_root / "mesh_raw.ply"
        command = [
            "colmap",
            "delaunay_mesher",
            "--input_path",
            str(dense),
            "--output_path",
            str(raw_mesh),
            "--input_type",
            "dense",
            "--DelaunayMeshing.max_proj_dist",
            str(config["max_proj_dist"]),
            "--DelaunayMeshing.num_threads",
            "-1",
        ]
        print("Running mesh trial:", name)
        return_code, meshing_seconds = _run_logged(
            command, output / "delaunay_meshing.log", self.project_dir, self.env
        )
        if return_code != 0 or not raw_mesh.is_file():
            raise RuntimeError(f"Delaunay failed; inspect {output / 'delaunay_meshing.log'}")
        cleanup_started = time.perf_counter()
        cleanup = clean_mesh_file(raw_mesh, trial_root / "mesh_cleaned.ply")
        cleanup_seconds = time.perf_counter() - cleanup_started
        shutil.copy2(raw_mesh, output / "mesh_raw.ply")
        shutil.copy2(trial_root / "mesh_cleaned.ply", output / "mesh_cleaned.ply")
        raw_vertices, raw_faces = ply_header_counts(raw_mesh)
        clean_vertices, clean_faces = ply_header_counts(trial_root / "mesh_cleaned.ply")
        log_text = (output / "delaunay_meshing.log").read_text(
            encoding="utf-8", errors="replace"
        )
        triangulation = re.search(
            r"Triangulation has\s+(\d+)\s+using\s+(\d+)\s+points", log_text
        )
        report: dict[str, Any] = {
            "completed": True,
            "name": name,
            "session_id": self.session_id,
            "config": config,
            "config_hash": expected_hash,
            "dense_winner_name": dense_winner_name,
            "fused_fingerprint": fused_fingerprint,
            "delaunay_seconds": round(meshing_seconds, 2),
            "cleanup_seconds": round(cleanup_seconds, 2),
            "raw_vertices": raw_vertices,
            "raw_faces": raw_faces,
            "clean_vertices": clean_vertices,
            "clean_faces": clean_faces,
            "cleanup": cleanup,
            "triangulation_vertices": int(triangulation.group(1)) if triangulation else None,
            "input_points_logged": int(triangulation.group(2)) if triangulation else None,
        }
        if name == MESH_CONTROL:
            report["quality_gates"] = {"control_generated": True}
            report["quality_pass"] = True
            report["runtime_target_pass"] = False
        else:
            control_output = self.experiment_root / "mesh_trials" / MESH_CONTROL
            control_path = control_output / "trial_report.json"
            control_hash = _config_hash(default_mesh_configs()[MESH_CONTROL])
            if not self._mesh_report_reusable(control_path, control_hash, fused_fingerprint):
                raise RuntimeError("Run the M0 mesh control first")
            control = json.loads(control_path.read_text(encoding="utf-8"))
            surface = compare_meshes(
                control_output / "mesh_cleaned.ply",
                output / "mesh_cleaned.ply",
                samples=100_000,
            )
            report["surface_comparison_to_control"] = surface
            baseline_oversized = (
                control["cleanup"]["removed_oversized_faces"]
                / max(1, control["cleanup"]["original_faces"])
            )
            candidate_oversized = (
                cleanup["removed_oversized_faces"] / max(1, cleanup["original_faces"])
            )
            gates = {
                "same_fused_cloud_and_visibility": (
                    fused_fingerprint == control["fused_fingerprint"]
                ),
                "mesh_components_at_most_7": 0 < cleanup["components_after"] <= 7,
                "bidirectional_surface_coverage_at_least_95_percent": (
                    surface["bidirectional_coverage_fraction"] >= 0.95
                ),
                "surface_symmetric_median_at_most_0_10m": (
                    surface["symmetric_median_m"] <= 0.10
                ),
                "surface_symmetric_p95_at_most_0_50m": surface["symmetric_p95_m"] <= 0.50,
                "surface_area_ratio_between_0_95_and_1_05": (
                    surface["surface_area_ratio"] is not None
                    and 0.95 <= surface["surface_area_ratio"] <= 1.05
                ),
                "xy_area_retains_95_percent": (
                    surface["xy_area_ratio"] is not None and surface["xy_area_ratio"] >= 0.95
                ),
                "winding_is_consistent": surface["candidate_winding_consistent"],
                "oversized_face_fraction_not_materially_worse": (
                    candidate_oversized <= baseline_oversized + 0.001
                ),
            }
            report["quality_gates"] = gates
            report["quality_pass"] = all(gates.values())
            report["runtime_target_pass"] = (
                meshing_seconds <= 0.85 * control["delaunay_seconds"]
            )
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        _remove_local(trial_root)
        return report

    def mesh_decision(self, names: list[str], fused_fingerprint: str) -> dict:
        reports = []
        for name in names:
            path = self.experiment_root / "mesh_trials" / name / "trial_report.json"
            if path.is_file():
                report = json.loads(path.read_text(encoding="utf-8"))
                if report.get("fused_fingerprint") == fused_fingerprint:
                    reports.append(report)
        candidates = [
            item
            for item in reports
            if item["name"] != MESH_CONTROL
            and item.get("quality_pass")
            and item.get("runtime_target_pass")
        ]
        winner = min(candidates, key=lambda item: item["delaunay_seconds"]) if candidates else None
        decision = {
            "fused_fingerprint": fused_fingerprint,
            "control": next((item for item in reports if item["name"] == MESH_CONTROL), None),
            "trials_completed": [item["name"] for item in reports],
            "winner": winner,
            "screen_pass": winner is not None,
            "surface_accuracy": "Comparative mesh consistency only; surveyed accuracy is not evaluated.",
        }
        (self.experiment_root / "mesh_decision.json").write_text(
            json.dumps(decision, indent=2), encoding="utf-8"
        )
        return decision

    def texture_mesh(self, mesh_path: Path, output: Path) -> dict:
        workspace = self.local_trial_root / "winner_texture_check"
        _remove_local(workspace)
        workspace.mkdir(parents=True)
        os.symlink(self.dense_template / "images", workspace / "images", target_is_directory=True)
        os.symlink(self.dense_template / "sparse", workspace / "sparse", target_is_directory=True)
        if output.is_dir():
            shutil.rmtree(output)
        command = [
            "colmap",
            "mesh_texturer",
            "--workspace_path",
            str(workspace),
            "--input_path",
            str(mesh_path),
            "--output_path",
            str(output),
        ]
        code, seconds = _run_logged(
            command,
            self.experiment_root / "winner_texture_check.log",
            self.project_dir,
            self.env,
        )
        files = sorted(str(path.relative_to(output)) for path in output.rglob("*") if path.is_file())
        return {
            "seconds": round(seconds, 2),
            "files": files,
            "pass": bool(
                code == 0
                and (output / "mesh.ply").is_file()
                and (output / "texture.png").is_file()
            ),
        }

    @staticmethod
    def dense_cli_args(config: dict) -> list[str]:
        arguments = [
            "--dense-frame-stride",
            str(config["stride"]),
            "--dense-anchor-mode",
            "adaptive",
            "--dense-source-images",
            str(config["source_images"]),
            "--dense-max-image-size",
            str(config["max_image_size"]),
            "--dense-num-iterations",
            str(config["iterations"]),
            "--dense-num-samples",
            str(config["samples"]),
            "--dense-window-step",
            str(config["window_step"]),
        ]
        if config["target_references"] is not None:
            arguments += ["--dense-target-references", str(config["target_references"])]
        return arguments

    def final_comparison(self, full_output: Path) -> dict:
        full_output = Path(full_output)
        candidate = json.loads((full_output / "run_report.json").read_text(encoding="utf-8"))
        candidate_ids = _read_source_ids(full_output / "frames.csv")
        cloud = compare_point_clouds(
            self.reference_output / "point_cloud.ply", full_output / "point_cloud.ply"
        )
        dsm = compare_dsm_rasters(
            self.reference_output / "dsm.tif", full_output / "dsm.tif"
        )
        mesh = compare_meshes(
            self.reference_output / "mesh.ply", full_output / "mesh.ply", samples=100_000
        )
        gates = {
            "same_ordered_253_source_frames": candidate_ids == self.reference_ids,
            "runtime_at_least_10_percent_faster": (
                candidate["wall_clock_seconds"] <= 0.90 * self.reference["wall_clock_seconds"]
            ),
            "registered_images_at_least_205": candidate["sparse_metrics"]["registered_images"] >= 205,
            "reprojection_at_most_reference_plus_0_03px": (
                candidate["sparse_metrics"]["mean_reprojection_error_px"]
                <= self.reference["sparse_metrics"]["mean_reprojection_error_px"] + 0.03
            ),
            "gps_rmse_at_most_reference_plus_0_15m": (
                candidate["validation"]["gps_alignment_rmse_m"]
                <= self.reference["validation"]["gps_alignment_rmse_m"] + 0.15
            ),
            "filtered_points_at_least_578644": candidate["products"]["point_count"] >= 578_644,
            "cloud_bidirectional_coverage_at_least_95_percent": (
                cloud["bidirectional_coverage_fraction"] >= 0.95
            ),
            "cloud_symmetric_p95_at_most_0_5m": cloud["symmetric_p95_m"] <= 0.5,
            "dsm_valid_fraction_at_least_0_135615": (
                candidate["products"]["dsm"]["valid_fraction"] >= 0.135615
            ),
            "dsm_mask_iou_at_least_90_percent": dsm["valid_mask_iou"] >= 0.90,
            "dsm_elevation_median_at_most_0_10m": dsm["elevation_abs_median_m"] <= 0.10,
            "dsm_elevation_p95_at_most_0_50m": dsm["elevation_abs_p95_m"] <= 0.50,
            "mesh_components_at_most_7": (
                0 < candidate["products"]["mesh_quality"]["components_after"] <= 7
            ),
            "mesh_bidirectional_coverage_at_least_95_percent": (
                mesh["bidirectional_coverage_fraction"] >= 0.95
            ),
            "mesh_symmetric_p95_at_most_0_50m": mesh["symmetric_p95_m"] <= 0.50,
            "mesh_surface_area_ratio_between_0_95_and_1_05": (
                mesh["surface_area_ratio"] is not None
                and 0.95 <= mesh["surface_area_ratio"] <= 1.05
            ),
            "textured_glb_created": (
                (full_output / "model.glb").is_file()
                and candidate["products"].get("textured_glb") is True
            ),
        }
        result = {
            "full_output": str(full_output),
            "reference_runtime_min": round(self.reference["wall_clock_seconds"] / 60, 2),
            "candidate_runtime_min": round(candidate["wall_clock_seconds"] / 60, 2),
            "speedup": self.reference["wall_clock_seconds"] / candidate["wall_clock_seconds"],
            "reference_stage_minutes": {
                name: round(self.reference["stages"][name]["seconds"] / 60, 2)
                for name in ("dense_stereo", "stereo_fusion", "delaunay_meshing", "mesh_cleanup")
            },
            "candidate_stage_minutes": {
                name: round(candidate["stages"][name]["seconds"] / 60, 2)
                for name in ("dense_stereo", "stereo_fusion", "delaunay_meshing", "mesh_cleanup")
            },
            "cloud_comparison": cloud,
            "dsm_comparison": dsm,
            "mesh_comparison": mesh,
            "quality_and_runtime_gates": gates,
            "recommended": all(gates.values()),
            "accuracy_boundary": (
                "Baseline-consistency checks only; surveyed checkpoints remain required."
            ),
        }
        (self.experiment_root / "final_decision.json").write_text(
            json.dumps(result, indent=2), encoding="utf-8"
        )
        return result
