from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class TelemetrySample:
    time_s: float
    latitude: float
    longitude: float
    altitude_m: float
    yaw_deg: float | None = None
    pitch_deg: float | None = None
    roll_deg: float | None = None


ALIASES = {
    "time_s": ("time_s", "timestamp_s", "seconds", "video_time_s"),
    "latitude": ("latitude", "lat", "gps_latitude"),
    "longitude": ("longitude", "lon", "lng", "gps_longitude"),
    "altitude_m": ("altitude_m", "alt_m", "altitude", "gps_altitude"),
    "yaw_deg": ("yaw_deg", "yaw", "heading"),
    "pitch_deg": ("pitch_deg", "pitch"),
    "roll_deg": ("roll_deg", "roll"),
}


def _field(row: dict[str, str], logical: str, required: bool = True) -> float | None:
    normalized = {key.strip().lower(): value for key, value in row.items() if key}
    for alias in ALIASES[logical]:
        value = normalized.get(alias)
        if value not in (None, ""):
            return float(value)
    if required:
        raise ValueError(f"Telemetry is missing required column: {ALIASES[logical][0]}")
    return None


def parse_csv(path: Path) -> list[TelemetrySample]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    return [
        TelemetrySample(
            time_s=float(_field(row, "time_s")),
            latitude=float(_field(row, "latitude")),
            longitude=float(_field(row, "longitude")),
            altitude_m=float(_field(row, "altitude_m")),
            yaw_deg=_field(row, "yaw_deg", False),
            pitch_deg=_field(row, "pitch_deg", False),
            roll_deg=_field(row, "roll_deg", False),
        )
        for row in rows
    ]


def _srt_seconds(value: str) -> float:
    hours, minutes, remainder = value.replace(",", ".").split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(remainder)


def parse_srt(path: Path) -> list[TelemetrySample]:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    blocks = re.split(r"\r?\n\s*\r?\n", text.strip())
    samples: list[TelemetrySample] = []
    for block in blocks:
        timestamp = re.search(r"(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->", block)
        lat = re.search(r"(?:latitude|lat)\s*[:=]\s*(-?\d+(?:\.\d+)?)", block, re.I)
        lon = re.search(r"(?:longitude|lon|lng)\s*[:=]\s*(-?\d+(?:\.\d+)?)", block, re.I)
        alt = re.search(
            r"(?:absolute[_ ]?altitude|abs[_ ]?alt|gps[_ ]?altitude)\s*[:=]\s*(-?\d+(?:\.\d+)?)",
            block,
            re.I,
        )
        if not alt:
            alt = re.search(
                r"(?:relative[_ ]?altitude|rel[_ ]?alt|altitude|alt)\s*[:=]\s*(-?\d+(?:\.\d+)?)",
                block,
                re.I,
            )
        if not (timestamp and lat and lon and alt):
            gps = re.search(
                r"GPS\s*\(?\s*(-?\d+(?:\.\d+)?)\s*[, ]+\s*(-?\d+(?:\.\d+)?)\s*[, ]+\s*(-?\d+(?:\.\d+)?)",
                block,
                re.I,
            )
            if timestamp and gps:
                lat, lon, alt = gps.group(1), gps.group(2), gps.group(3)
                samples.append(TelemetrySample(_srt_seconds(timestamp.group(1)), float(lat), float(lon), float(alt)))
            continue
        samples.append(
            TelemetrySample(
                _srt_seconds(timestamp.group(1)),
                float(lat.group(1)),
                float(lon.group(1)),
                float(alt.group(1)),
            )
        )
    return samples


def load_telemetry(path: str | Path) -> list[TelemetrySample]:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    samples = parse_srt(path) if path.suffix.lower() == ".srt" else parse_csv(path)
    samples = sorted(samples, key=lambda sample: sample.time_s)
    if len(samples) < 3:
        raise ValueError("At least three telemetry samples with time, GPS and altitude are required")
    return samples


def interpolate(samples: list[TelemetrySample], time_s: float) -> TelemetrySample:
    if time_s <= samples[0].time_s:
        return samples[0]
    if time_s >= samples[-1].time_s:
        return samples[-1]
    lo, hi = 0, len(samples) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if samples[mid].time_s <= time_s:
            lo = mid
        else:
            hi = mid
    left, right = samples[lo], samples[hi]
    ratio = (time_s - left.time_s) / (right.time_s - left.time_s)

    def mix(a: float, b: float) -> float:
        return a + ratio * (b - a)

    return TelemetrySample(
        time_s=time_s,
        latitude=mix(left.latitude, right.latitude),
        longitude=mix(left.longitude, right.longitude),
        altitude_m=mix(left.altitude_m, right.altitude_m),
    )


def write_frame_references(
    frame_records: Iterable,
    samples: list[TelemetrySample],
    output_path: str | Path,
) -> dict:
    """Write COLMAP's image-name/latitude/longitude/altitude reference file."""
    references = []
    for frame in frame_records:
        sample = interpolate(samples, float(frame.time_s))
        references.append((frame.image_name, sample.latitude, sample.longitude, sample.altitude_m, frame.time_s))
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as stream:
        for name, lat, lon, alt, _ in references:
            stream.write(f"{name} {lat:.10f} {lon:.10f} {alt:.3f}\n")
    if not references:
        raise ValueError("No frame references could be generated")

    # COLMAP's model_aligner uses the first GPS reference as the origin when
    # --alignment_type enu is selected. Every later conversion must use that
    # exact origin too; using an average position introduces a constant map
    # translation even when the reconstruction itself is accurate.
    _, origin_lat, origin_lon, origin_alt, _ = references[0]
    return {
        "count": len(references),
        "origin": {
            "latitude": origin_lat,
            "longitude": origin_lon,
            "altitude_m": origin_alt,
        },
        "origin_policy": "first_frame_reference",
    }
