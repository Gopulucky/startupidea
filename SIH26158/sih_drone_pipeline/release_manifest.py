from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .production_status import TerminalState


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_release_manifest(
    release_dir: str | Path,
    artifacts: Iterable[str | Path],
    *,
    terminal_state: str | TerminalState,
    terminal_reasons: Sequence[str],
    pipeline_version: str,
    input_fingerprints: Mapping[str, object],
    configuration: Mapping[str, object],
    runtime: Mapping[str, object],
    fallbacks: Sequence[Mapping[str, object]] = (),
    excluded_components: Sequence[Mapping[str, object]] = (),
) -> dict:
    """Write a checksum-backed manifest containing release artifacts only."""
    release_dir = Path(release_dir).resolve()
    release_dir.mkdir(parents=True, exist_ok=True)
    try:
        state = TerminalState(terminal_state)
    except ValueError as error:
        raise ValueError(f"Unknown terminal state: {terminal_state}") from error

    artifact_records = []
    seen: set[Path] = set()
    for item in artifacts:
        path = Path(item).resolve()
        if path in seen:
            continue
        seen.add(path)
        if not path.is_file():
            raise FileNotFoundError(path)
        try:
            relative = path.relative_to(release_dir)
        except ValueError as error:
            raise ValueError(
                f"Release artifact must be inside {release_dir}: {path}"
            ) from error
        artifact_records.append({
            "path": relative.as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        })
    artifact_records.sort(key=lambda row: row["path"])
    if not artifact_records:
        raise ValueError("A release must contain at least one artifact")

    manifest = {
        "schema_version": 1,
        "pipeline_version": pipeline_version,
        "terminal_state": state.value,
        "terminal_reasons": list(terminal_reasons),
        "input_fingerprints": dict(input_fingerprints),
        "configuration": dict(configuration),
        "runtime": dict(runtime),
        "fallbacks": list(fallbacks),
        "excluded_components": list(excluded_components),
        "artifacts": artifact_records,
    }
    path = release_dir / "release_manifest.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest

