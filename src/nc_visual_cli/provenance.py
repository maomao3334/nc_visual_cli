from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from .errors import InputError

EVENT_FIELDS = ("id", "name", "type", "lon", "lat", "start_time")
ASSET_FIELDS = ("id", "name", "type", "lon", "lat")
BOUNDARY_GEOMETRY_TYPES = {"Polygon", "MultiPolygon", "LineString", "MultiLineString"}


def source_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _as_coordinate(value: Any, field: str, origin: str) -> float:
    if isinstance(value, bool):
        raise InputError(f"{origin}: {field} 不是有效数字")
    try:
        coordinate = float(value)
    except (TypeError, ValueError) as exc:
        raise InputError(f"{origin}: {field} 不是有效数字") from exc
    if not math.isfinite(coordinate):
        raise InputError(f"{origin}: {field} 不是有限数值")
    if field == "lon" and not -180 <= coordinate <= 180:
        raise InputError(f"{origin}: lon 超出 [-180, 180]")
    if field == "lat" and not -90 <= coordinate <= 90:
        raise InputError(f"{origin}: lat 超出 [-90, 90]")
    return coordinate


def _as_text(value: Any, field: str, origin: str) -> str:
    if isinstance(value, (dict, list, tuple)):
        raise InputError(f"{origin}: {field} 不是有效文本")
    text = str(value).strip()
    if not text:
        raise InputError(f"{origin}: {field} 不能为空")
    return text


def _as_iso_datetime(value: Any, field: str, origin: str) -> str:
    text = _as_text(value, field, origin)
    candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise InputError(f"{origin}: {field} 不是有效 ISO-8601 时间") from exc
    return text


def _validate_point(item: dict[str, Any], fields: tuple[str, ...], origin: str) -> dict[str, Any]:
    missing = [field for field in fields if item.get(field) in (None, "")]
    if missing:
        raise InputError(f"{origin}: 缺少字段 {', '.join(missing)}")
    normalized = {field: item[field] for field in fields}
    normalized["id"] = _as_text(normalized["id"], "id", origin)
    normalized["name"] = _as_text(normalized["name"], "name", origin)
    normalized["type"] = _as_text(normalized["type"], "type", origin)
    normalized["lon"] = _as_coordinate(normalized["lon"], "lon", origin)
    normalized["lat"] = _as_coordinate(normalized["lat"], "lat", origin)
    if "start_time" in normalized:
        normalized["start_time"] = _as_iso_datetime(
            normalized["start_time"], "start_time", origin
        )
    if item.get("end_time") not in (None, ""):
        normalized["end_time"] = _as_iso_datetime(item["end_time"], "end_time", origin)
    if item.get("description") not in (None, ""):
        normalized["description"] = _as_text(item["description"], "description", origin)
    return normalized


def _read_json_object(source: Path, label: str) -> dict[str, Any]:
    try:
        document = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InputError(f"无法读取 {label}: {exc}") from exc
    if not isinstance(document, dict):
        raise InputError(f"{source}: JSON 根节点必须是对象")
    return document


def load_points(path: str | Path | None, kind: str) -> list[dict[str, Any]]:
    if path is None:
        return []
    source = Path(path).expanduser()
    if not source.is_file():
        raise InputError(f"{kind} 文件不存在: {source}")
    fields = EVENT_FIELDS if kind == "events" else ASSET_FIELDS
    rows: list[dict[str, Any]] = []
    suffix = source.suffix.casefold()
    if suffix in {".geojson", ".json"}:
        document = _read_json_object(source, f"{kind} GeoJSON")
        if document.get("type") != "FeatureCollection" or not isinstance(document.get("features"), list):
            raise InputError(f"{source}: 必须是 GeoJSON FeatureCollection")
        for index, feature in enumerate(document["features"], start=1):
            origin = f"{source} feature {index}"
            if not isinstance(feature, dict):
                raise InputError(f"{origin}: feature 必须是对象")
            geometry = feature.get("geometry")
            if not isinstance(geometry, dict):
                raise InputError(f"{origin}: geometry 必须是对象")
            if geometry.get("type") != "Point":
                raise InputError(f"{origin}: geometry 必须是 Point")
            coordinates = geometry.get("coordinates")
            if not isinstance(coordinates, (list, tuple)) or len(coordinates) < 2:
                raise InputError(f"{origin}: Point 坐标必须是至少含 lon/lat 的数组")
            properties = feature.get("properties")
            if not isinstance(properties, dict):
                raise InputError(f"{origin}: properties 必须是对象")
            item = dict(properties)
            item["lon"], item["lat"] = coordinates[:2]
            rows.append(_validate_point(item, fields, origin))
    elif suffix == ".csv":
        try:
            with source.open("r", encoding="utf-8-sig", newline="") as stream:
                for line_number, item in enumerate(csv.DictReader(stream), start=2):
                    rows.append(_validate_point(dict(item), fields, f"{source} 第 {line_number} 行"))
        except (OSError, UnicodeError, csv.Error) as exc:
            raise InputError(f"无法读取 {kind} CSV: {exc}") from exc
    else:
        raise InputError(f"{kind} 仅支持 .geojson/.json/.csv: {source}")

    identifier_counts = Counter(item["id"] for item in rows)
    duplicates = sorted(identifier for identifier, count in identifier_counts.items() if count > 1)
    if duplicates:
        raise InputError(f"{source}: id 重复: {', '.join(duplicates)}")
    return rows


def _validate_position(value: Any, origin: str) -> None:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        raise InputError(f"{origin}: 坐标必须是至少含 lon/lat 的数组")
    _as_coordinate(value[0], "lon", origin)
    _as_coordinate(value[1], "lat", origin)


def _validate_line(value: Any, origin: str, minimum_points: int) -> None:
    if not isinstance(value, list) or len(value) < minimum_points:
        raise InputError(f"{origin}: 至少需要 {minimum_points} 个坐标点")
    for index, position in enumerate(value, start=1):
        _validate_position(position, f"{origin} 坐标 {index}")


def _validate_boundary_geometry(geometry: Any, origin: str) -> None:
    if not isinstance(geometry, dict):
        raise InputError(f"{origin}: geometry 必须是对象")
    geometry_type = geometry.get("type")
    if geometry_type not in BOUNDARY_GEOMETRY_TYPES:
        raise InputError(f"{origin}: 不支持的 geometry 类型 {geometry_type!r}")
    coordinates = geometry.get("coordinates")
    if geometry_type == "LineString":
        _validate_line(coordinates, origin, 2)
    elif geometry_type == "MultiLineString":
        if not isinstance(coordinates, list) or not coordinates:
            raise InputError(f"{origin}: MultiLineString 坐标不能为空")
        for index, line in enumerate(coordinates, start=1):
            _validate_line(line, f"{origin} 线 {index}", 2)
    elif geometry_type == "Polygon":
        if not isinstance(coordinates, list) or not coordinates:
            raise InputError(f"{origin}: Polygon 坐标不能为空")
        for index, ring in enumerate(coordinates, start=1):
            _validate_line(ring, f"{origin} 环 {index}", 4)
            if ring[0][:2] != ring[-1][:2]:
                raise InputError(f"{origin} 环 {index}: 首尾坐标必须闭合")
    else:
        if not isinstance(coordinates, list) or not coordinates:
            raise InputError(f"{origin}: MultiPolygon 坐标不能为空")
        for polygon_index, polygon in enumerate(coordinates, start=1):
            if not isinstance(polygon, list) or not polygon:
                raise InputError(f"{origin} 面 {polygon_index}: 坐标不能为空")
            for ring_index, ring in enumerate(polygon, start=1):
                ring_origin = f"{origin} 面 {polygon_index} 环 {ring_index}"
                _validate_line(ring, ring_origin, 4)
                if ring[0][:2] != ring[-1][:2]:
                    raise InputError(f"{ring_origin}: 首尾坐标必须闭合")


def _validate_boundary_document(document: dict[str, Any], origin: str) -> None:
    document_type = document.get("type")
    if document_type == "FeatureCollection":
        features = document.get("features")
        if not isinstance(features, list) or not features:
            raise InputError(f"{origin}: FeatureCollection 的 features 不能为空")
        for index, feature in enumerate(features, start=1):
            feature_origin = f"{origin} feature {index}"
            if not isinstance(feature, dict) or feature.get("type") != "Feature":
                raise InputError(f"{feature_origin}: 必须是 Feature 对象")
            _validate_boundary_geometry(feature.get("geometry"), feature_origin)
    elif document_type == "Feature":
        _validate_boundary_geometry(document.get("geometry"), f"{origin} feature")
    else:
        _validate_boundary_geometry(document, origin)


def load_boundary(path: str | Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    source = Path(path).expanduser()
    if not source.is_file():
        raise InputError(f"边界文件不存在: {source}")
    document = _read_json_object(source, "边界 GeoJSON")
    _validate_boundary_document(document, str(source))
    return document


def provenance_policy() -> dict[str, str]:
    return {
        "grid_policy": "already_gridded_nc_is_validated_not_refused_or_reinterpolated",
        "source_merge": "not_available_without_a_canonical_source_observation_schema",
    }
