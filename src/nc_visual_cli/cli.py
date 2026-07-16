from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Sequence

from . import __version__
from .errors import DataContractError, InputError
from .models import SCHEMA_VERSION
from .service import RunConfig, run_batch

EXIT_OK = 0
EXIT_INTERNAL = 1
EXIT_INPUT = 2
EXIT_DATA = 3
EXIT_PARTIAL = 4


class _InputArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise InputError(message)


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("必须大于 0")
    return parsed


def _positive_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("必须是大于 0 的有限数值")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = _InputArgumentParser(
        prog="nc_visual_cli",
        description="离线风场态势报告生成器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  nc_visual_cli G:\\data\\nc\n"
            "  nc_visual_cli G:\\data\\nc --output G:\\reports --latest-only\n"
            "  nc_visual_cli G:\\data\\nc --events events.geojson --assets assets.csv --json"
        ),
    )
    parser.add_argument("folder", type=Path, help="NC 文件夹，只扫描第一层 .nc 文件")
    parser.add_argument("--output", type=Path, help="报告目录，默认 <folder>/nc_visual_reports")
    parser.add_argument("--events", type=Path, help="事件点 GeoJSON 或 CSV")
    parser.add_argument("--assets", type=Path, help="设备点 GeoJSON 或 CSV")
    parser.add_argument("--boundary", type=Path, help="任务边界 GeoJSON")
    parser.add_argument(
        "--risk-horizon-min", type=_positive_int, default=20, help="理论平流时长，默认 20 分钟"
    )
    parser.add_argument(
        "--time-window-min", type=_positive_int, default=60, help="风玫瑰滚动窗口，默认 60 分钟"
    )
    parser.add_argument(
        "--max-event-wind-distance-km",
        type=_positive_float,
        default=10.0,
        help="事件使用最近受支持风格点的最大距离，默认 10 km",
    )
    parser.add_argument("--timezone", default="Asia/Shanghai", help="无时区时间的解释与显示时区")
    parser.add_argument(
        "--theme", choices=("dark", "light", "auto"), default="dark", help="报告默认主题"
    )
    parser.add_argument("--latest-only", action="store_true", help="只处理完整度最高且最新的一份 NC")
    parser.add_argument("--json", action="store_true", dest="json_output", help="stdout 只输出稳定 JSON")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _error_document(message: str, error_type: str) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "success": False,
        "results": [],
        "warnings": [],
        "batch_manifest_path": None,
        "elapsed_seconds": 0.0,
        "error": message,
        "error_type": error_type,
    }


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def _json_text(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def main(argv: Sequence[str] | None = None) -> int:
    _configure_stdio()
    raw_args = list(argv) if argv is not None else sys.argv[1:]
    json_output = "--json" in raw_args
    try:
        args = build_parser().parse_args(raw_args)
        logger = lambda message: print(message, file=sys.stderr)
        config = RunConfig(
            folder=args.folder,
            output=args.output,
            events=args.events,
            assets=args.assets,
            boundary=args.boundary,
            risk_horizon_min=args.risk_horizon_min,
            time_window_min=args.time_window_min,
            max_event_wind_distance_km=args.max_event_wind_distance_km,
            timezone=args.timezone,
            theme=args.theme,
            latest_only=args.latest_only,
        )
        result = run_batch(config, logger=None if args.json_output else logger)
        if args.json_output:
            print(_json_text(result.to_dict()))
        else:
            print(f"完成: {sum(1 for item in result.results if item['success'])}/{len(result.results)}", file=sys.stderr)
            print(f"批次清单: {result.batch_manifest_path}", file=sys.stderr)
        if result.partial:
            return EXIT_PARTIAL
        if not result.success:
            return EXIT_DATA
        return EXIT_OK
    except InputError as exc:
        if json_output:
            print(_json_text(_error_document(str(exc), type(exc).__name__)))
        else:
            print(f"输入错误: {exc}", file=sys.stderr)
        return EXIT_INPUT
    except DataContractError as exc:
        if json_output:
            print(_json_text(_error_document(str(exc), type(exc).__name__)))
        else:
            print(f"数据不兼容: {exc}", file=sys.stderr)
        return EXIT_DATA
    except Exception as exc:
        if json_output:
            print(_json_text(_error_document(str(exc), type(exc).__name__)))
        else:
            print(f"内部错误: {exc}", file=sys.stderr)
        return EXIT_INTERNAL


def entrypoint() -> None:
    raise SystemExit(main())
