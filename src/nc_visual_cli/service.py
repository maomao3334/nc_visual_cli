from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import DataContractError, InputError
from .models import BatchResult, SCHEMA_VERSION
from .offline_report import load_default_boundary, render_offline_report
from .provenance import load_boundary, load_points
from .report_contract import build_report_contract
from .scanner import scan_folder, select_best
from .wind_analysis import analyze_dataset


@dataclass(slots=True)
class RunConfig:
    folder: Path
    output: Path | None = None
    events: Path | None = None
    assets: Path | None = None
    boundary: Path | None = None
    risk_horizon_min: int = 20
    time_window_min: int = 60
    max_event_wind_distance_km: float = 10.0
    timezone: str = "Asia/Shanghai"
    theme: str = "dark"
    latest_only: bool = False


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )
    os.replace(temporary, path)


def run_batch(
    config: RunConfig,
    logger: Callable[[str], None] | None = None,
) -> BatchResult:
    started = time.perf_counter()
    log = logger or (lambda _: None)
    try:
        ZoneInfo(config.timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise InputError(f"未知时区: {config.timezone}") from exc
    scans = scan_folder(config.folder)
    compatible = [item for item in scans if item.compatible]
    if not compatible:
        details = "; ".join(f"{item.path.name}: {item.error}" for item in scans)
        raise DataContractError(f"没有兼容的 NetCDF 文件。{details}")
    selected = [select_best(scans)] if config.latest_only else compatible
    output_dir = (config.output or config.folder / "nc_visual_reports").expanduser().resolve()
    if output_dir.exists() and not output_dir.is_dir():
        raise InputError(f"报告输出路径不是文件夹: {output_dir}")
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise InputError(f"无法创建报告输出文件夹 {output_dir}: {exc}") from exc
    events = load_points(config.events, "events")
    assets = load_points(config.assets, "assets")
    task_boundary = load_boundary(config.boundary)
    basemap = load_default_boundary()
    warnings: list[str] = []
    for item in scans:
        if not item.compatible:
            warnings.append(f"跳过 {item.path.name}: {item.error}")
    results: list[dict[str, object]] = []
    if not config.latest_only:
        results.extend(
            {
                "success": False,
                "source_path": str(item.path),
                "error": item.error or "NetCDF 数据契约不兼容",
                "error_type": "DataContractError",
            }
            for item in scans
            if not item.compatible
        )

    for position, scan in enumerate(selected, start=1):
        log(f"[{position}/{len(selected)}] 分析 {scan.path.name}")
        try:
            analysis = analyze_dataset(
                scan.path,
                scan_result=scan,
                timezone=config.timezone,
                time_window_min=config.time_window_min,
            )
            report_config = {
                "risk_horizon_min": config.risk_horizon_min,
                "time_window_min": config.time_window_min,
                "max_event_wind_distance_km": config.max_event_wind_distance_km,
                "timezone": config.timezone,
                "default_theme": config.theme,
                "latest_only": config.latest_only,
            }
            manifest = build_report_contract(
                analysis,
                events=events,
                assets=assets,
                boundary=task_boundary,
                config=report_config,
            )
            output = render_offline_report(
                manifest,
                analysis,
                output_dir,
                basemap=basemap,
                task_boundary=task_boundary,
            )
            results.append(
                {
                    "success": True,
                    "source_path": str(scan.path),
                    "source_sha256": analysis.source_sha256,
                    "html_path": str(output.html_path),
                    "manifest_path": str(output.manifest_path),
                    "output_mode": output.mode,
                    "payload_bytes": output.payload_bytes,
                    "warnings": analysis.warnings,
                }
            )
            warnings.extend(f"{scan.path.name}: {warning}" for warning in analysis.warnings)
            log(f"已生成 {output.html_path}")
        except Exception as exc:
            results.append(
                {
                    "success": False,
                    "source_path": str(scan.path),
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                }
            )
            warnings.append(f"{scan.path.name}: {exc}")
            log(f"处理失败 {scan.path.name}: {exc}")

    success_count = sum(1 for item in results if item["success"])
    partial = 0 < success_count < len(results)
    success = success_count == len(results) and bool(results)
    batch_manifest_path = output_dir / "batch_manifest.json"
    batch_document = {
        "schema_version": SCHEMA_VERSION,
        "success": success,
        "partial": partial,
        "input_folder": str(config.folder.resolve()),
        "scanned_files": [item.to_dict() for item in scans],
        "results": results,
        "warnings": warnings,
    }
    _atomic_json(batch_manifest_path, batch_document)
    return BatchResult(
        schema_version=SCHEMA_VERSION,
        success=success,
        results=results,
        warnings=warnings,
        batch_manifest_path=str(batch_manifest_path),
        elapsed_seconds=round(time.perf_counter() - started, 3),
        partial=partial,
    )
