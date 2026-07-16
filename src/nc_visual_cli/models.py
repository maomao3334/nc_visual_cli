from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "2.0.0"


@dataclass(slots=True)
class ScanResult:
    path: Path
    size_bytes: int
    modified_at: str
    dimensions: dict[str, int] = field(default_factory=dict)
    variables: list[str] = field(default_factory=list)
    coordinate_names: dict[str, str] = field(default_factory=dict)
    variable_names: dict[str, str] = field(default_factory=dict)
    score: int = -1
    compatible: bool = False
    has_quality: bool = False
    error: str | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["path"] = str(self.path)
        return data


@dataclass(slots=True)
class DatasetAnalysis:
    source_path: Path
    source_sha256: str
    dimensions: dict[str, int]
    coordinates: dict[str, Any]
    variable_mapping: dict[str, str]
    variable_units: dict[str, str]
    height_datum: str
    time_kind: str
    quality_status: str
    global_stats: dict[str, float]
    frames: dict[str, dict[str, Any]]
    time_height: dict[str, Any]
    default_time_index: int
    default_height_index: int
    source_summary: list[list[str]]
    coordinate_status_summary: list[list[str]]
    warnings: list[str] = field(default_factory=list)

    def report_payload(self) -> dict[str, Any]:
        data = asdict(self)
        data["source_path"] = str(self.source_path)
        return data


@dataclass(slots=True)
class ReportManifest:
    metadata: dict[str, Any]
    source: dict[str, Any]
    dimensions: dict[str, int]
    coordinates: dict[str, Any]
    data_contract: dict[str, Any]
    global_stats: dict[str, float]
    quality: dict[str, Any]
    events: list[dict[str, Any]]
    assets: list[dict[str, Any]]
    boundary: dict[str, Any] | None
    config: dict[str, Any]
    warnings: list[str]
    outputs: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

@dataclass(slots=True)
class ReportOutput:
    html_path: Path
    manifest_path: Path
    mode: str
    payload_bytes: int


@dataclass(slots=True)
class BatchResult:
    schema_version: str
    success: bool
    results: list[dict[str, Any]]
    warnings: list[str]
    batch_manifest_path: str | None
    elapsed_seconds: float
    partial: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
