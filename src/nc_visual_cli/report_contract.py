from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .models import DatasetAnalysis, ReportManifest, SCHEMA_VERSION
from .provenance import provenance_policy


def _boundary_summary(boundary: dict[str, Any] | None) -> dict[str, Any] | None:
    if boundary is None:
        return None
    boundary_type = boundary.get("type")
    if boundary_type == "FeatureCollection":
        feature_count = len(boundary.get("features") or [])
    else:
        feature_count = 1
    return {"type": boundary_type, "feature_count": feature_count}


def build_report_contract(
    analysis: DatasetAnalysis,
    events: list[dict[str, Any]] | None = None,
    assets: list[dict[str, Any]] | None = None,
    boundary: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
) -> ReportManifest:
    events = events or []
    assets = assets or []
    config = config or {}
    times = analysis.coordinates["time"]
    heights = analysis.coordinates["height_m"]
    latitudes = analysis.coordinates["lat"]
    longitudes = analysis.coordinates["lon"]
    return ReportManifest(
        metadata={
            "schema_version": SCHEMA_VERSION,
            "generator": "nc_visual_cli",
            "generator_version": "2.0.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "language": "zh-CN",
        },
        source={
            "file_name": analysis.source_path.name,
            "file_path": str(analysis.source_path),
            "sha256": analysis.source_sha256,
            "method_warning": "观测衍生插值产品；稀疏层不能解释为连续物理模拟场。",
        },
        dimensions=dict(analysis.dimensions),
        coordinates={
            "time": times,
            "height_m": heights,
            "lat_range": [min(latitudes), max(latitudes)],
            "lon_range": [min(longitudes), max(longitudes)],
            "gap_after_indices": analysis.coordinates["gap_after_indices"],
        },
        data_contract={
            "variable_mapping": dict(analysis.variable_mapping),
            "variable_units": dict(analysis.variable_units),
            "height_datum": analysis.height_datum,
            "time_kind": analysis.time_kind,
            "wind_speed_authority": "derived_from_u_v",
            "flow_direction_convention": "clockwise_from_north_where_wind_goes",
            "provenance_policy": provenance_policy(),
        },
        global_stats=dict(analysis.global_stats),
        quality={
            "status": analysis.quality_status,
            "levels": {
                "0": "missing",
                "1": "low_neighbor_support",
                "2": "acceptable_neighbor_support",
            },
        },
        events=events,
        assets=assets,
        boundary=_boundary_summary(boundary),
        config=config,
        warnings=list(analysis.warnings),
    )
