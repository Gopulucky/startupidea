from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .telemetry import load_telemetry


def _command_version(command: list[str]) -> dict:
    executable = shutil.which(command[0])
    if not executable:
        return {"available": False, "executable": None, "output": None}
    result = subprocess.run(command, capture_output=True, text=True, errors="replace", check=False)
    output = ((result.stdout or "") + (result.stderr or "")).strip()
    return {"available": result.returncode == 0, "executable": executable, "output": "\n".join(output.splitlines()[:12])}


def inspect_environment(video: str | Path, telemetry_path: str | Path, workspace: str | Path) -> dict:
    video, telemetry_path, workspace = Path(video), Path(telemetry_path), Path(workspace)
    checks = {
        "colmap": _command_version(["colmap", "-h"]),
        "ffmpeg": _command_version(["ffmpeg", "-version"]),
        "ffprobe": _command_version(["ffprobe", "-version"]),
        "nvidia_smi": _command_version(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"]),
    }
    video_info = {}
    if video.is_file() and checks["ffprobe"]["available"]:
        probe = subprocess.run(
            [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height,r_frame_rate,nb_frames:format=duration",
                "-of", "json", str(video),
            ],
            capture_output=True, text=True, errors="replace", check=False,
        )
        if probe.returncode == 0:
            video_info = json.loads(probe.stdout)
    telemetry_info = {"valid": False}
    try:
        samples = load_telemetry(telemetry_path)
        telemetry_info = {
            "valid": True,
            "samples": len(samples),
            "start_s": samples[0].time_s,
            "end_s": samples[-1].time_s,
            "latitude_range": [min(s.latitude for s in samples), max(s.latitude for s in samples)],
            "longitude_range": [min(s.longitude for s in samples), max(s.longitude for s in samples)],
            "altitude_range_m": [min(s.altitude_m for s in samples), max(s.altitude_m for s in samples)],
        }
    except Exception as error:
        telemetry_info["error"] = str(error)
    workspace.mkdir(parents=True, exist_ok=True)
    disk = shutil.disk_usage(workspace)
    checks["video"] = {"available": video.is_file(), "path": str(video), "probe": video_info}
    checks["telemetry"] = telemetry_info
    checks["workspace"] = {"path": str(workspace), "free_gb": round(disk.free / 1024**3, 2)}
    colmap_header = (checks["colmap"].get("output") or "").upper()
    colmap_cuda = "CUDA" in colmap_header and "WITHOUT CUDA" not in colmap_header and "NO CUDA" not in colmap_header
    duration_s = None
    try:
        duration_s = float(video_info.get("format", {}).get("duration"))
    except (TypeError, ValueError):
        pass
    telemetry_covers_video = bool(
        duration_s is not None
        and telemetry_info.get("valid")
        and telemetry_info.get("start_s", 1) <= 1.0
        and telemetry_info.get("end_s", 0) >= 0.9 * duration_s
    )
    checks["ready"] = all([
        checks["colmap"]["available"], checks["ffmpeg"]["available"], checks["ffprobe"]["available"],
        checks["nvidia_smi"]["available"],
        checks["video"]["available"], checks["telemetry"]["valid"], telemetry_covers_video,
        colmap_cuda, disk.free >= 10 * 1024**3,
    ])
    checks["colmap_cuda"] = colmap_cuda
    checks["telemetry_covers_video"] = telemetry_covers_video
    return checks
