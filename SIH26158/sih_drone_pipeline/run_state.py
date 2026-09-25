from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import sys
from typing import Iterable, Mapping


def file_fingerprint(path: str | Path, *, full: bool = False) -> dict:
    """Fingerprint a file cheaply during a run or fully for a final release."""
    path = Path(path)
    stat = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        if full or stat.st_size <= 2 * 1024 * 1024:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        else:
            digest.update(stream.read(1024 * 1024))
            stream.seek(max(0, stat.st_size - 1024 * 1024))
            digest.update(stream.read(1024 * 1024))
    return {
        "path": str(path.resolve()),
        "size_bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": digest.hexdigest(),
        "hash_scope": "full" if full or stat.st_size <= 2 * 1024 * 1024 else "head_tail_1MiB",
    }


def software_provenance(extra: Mapping[str, object] | None = None) -> dict:
    result = {
        "python": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "pipeline_seed": 26158,
        "python_hash_seed": os.environ.get("PYTHONHASHSEED", "not_set"),
    }
    result.update(dict(extra or {}))
    return result


def safe_remove_tree(target: str | Path, allowed_root: str | Path) -> None:
    """Remove only a strict descendant of an explicitly supplied run root."""
    target = Path(target).resolve()
    allowed_root = Path(allowed_root).resolve()
    if target == allowed_root or allowed_root not in target.parents:
        raise ValueError(f"Refusing cleanup outside run root: {target}")
    if target.exists():
        shutil.rmtree(target)


class RunState:
    """Atomic, checksum-validated stage state for resumable notebook runs."""

    SCHEMA_VERSION = 1

    def __init__(self, path: str | Path, run_identity: Mapping[str, object]):
        self.path = Path(path)
        self.run_identity = dict(run_identity)
        self.payload = {
            "schema_version": self.SCHEMA_VERSION,
            "run_identity": self.run_identity,
            "stages": {},
        }
        if self.path.is_file():
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if loaded.get("schema_version") != self.SCHEMA_VERSION:
                raise ValueError("Unsupported run-state schema")
            if loaded.get("run_identity") != self.run_identity:
                raise ValueError("Run-state identity does not match current inputs/configuration")
            self.payload = loaded

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(self.payload, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def complete_stage(
        self,
        name: str,
        outputs: Iterable[str | Path],
        metadata: Mapping[str, object] | None = None,
    ) -> dict:
        if not name or not name.strip():
            raise ValueError("Stage name must not be empty")
        records = [file_fingerprint(item, full=True) for item in outputs]
        if not records:
            raise ValueError("A completed stage must declare at least one output")
        stage = {"status": "complete", "outputs": records, "metadata": dict(metadata or {})}
        self.payload["stages"][name] = stage
        self._write()
        return stage

    def stage_is_reusable(self, name: str) -> bool:
        stage = self.payload.get("stages", {}).get(name, {})
        if stage.get("status") != "complete":
            return False
        for expected in stage.get("outputs", []):
            path = Path(expected["path"])
            if not path.is_file():
                return False
            actual = file_fingerprint(path, full=True)
            if (
                actual["size_bytes"] != expected["size_bytes"]
                or actual["sha256"] != expected["sha256"]
            ):
                return False
        return True
