from __future__ import annotations

import json
import os
import shutil
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

from jinja2 import Environment

from .models import DatasetAnalysis, ReportManifest, ReportOutput

DEFAULT_SPLIT_THRESHOLD_MB = 20.0
CHUNK_TARGET_BYTES = 4 * 1024 * 1024
_JSON_ENCODER = json.JSONEncoder(
    ensure_ascii=False,
    separators=(",", ":"),
    allow_nan=False,
)


def _compact_json(value: Any) -> str:
    return _JSON_ENCODER.encode(value).replace("</", "<\\/")


def _json_size_bytes(value: Any) -> int:
    return sum(
        len(part.replace("</", "<\\/").encode("utf-8"))
        for part in _JSON_ENCODER.iterencode(value)
    )


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def load_default_boundary() -> dict[str, Any]:
    asset = resources.files("nc_visual_cli").joinpath("assets/natural_earth_admin0.geojson")
    return json.loads(asset.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _template() -> str:
    return resources.files("nc_visual_cli").joinpath("templates/report.html").read_text(
        encoding="utf-8"
    )


def _frame_chunks(frames: dict[str, dict[str, Any]]) -> list[dict[str, dict[str, Any]]]:
    chunks: list[dict[str, dict[str, Any]]] = []
    current: dict[str, dict[str, Any]] = {}
    current_size = 2
    for key, frame in frames.items():
        entry_size = len(_compact_json({key: frame}).encode("utf-8"))
        if current and current_size + entry_size > CHUNK_TARGET_BYTES:
            chunks.append(current)
            current = {}
            current_size = 2
        current[key] = frame
        current_size += entry_size
    if current:
        chunks.append(current)
    return chunks


def _render_template(bootstrap: dict[str, Any], chunk_scripts: list[str]) -> str:
    environment = Environment(autoescape=False, keep_trailing_newline=True)
    template = environment.from_string(_template())
    return template.render(
        bootstrap_json=_compact_json(bootstrap),
        chunk_scripts=chunk_scripts,
    )


def render_offline_report(
    manifest: ReportManifest,
    analysis: DatasetAnalysis,
    output_dir: str | Path,
    basemap: dict[str, Any] | None = None,
    task_boundary: dict[str, Any] | None = None,
    split_threshold_mb: float = DEFAULT_SPLIT_THRESHOLD_MB,
) -> ReportOutput:
    destination = Path(output_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    stem = analysis.source_path.stem
    manifest_path = destination / f"{stem}_manifest.json"
    basemap = basemap if basemap is not None else load_default_boundary()
    base_payload = {
        "manifest": manifest.to_dict(),
        "analysis": analysis.report_payload(),
        "basemap": basemap,
        "task_boundary": task_boundary,
    }
    frames = base_payload["analysis"].pop("frames")
    frame_bytes = _json_size_bytes(frames)
    split_threshold_bytes = int(split_threshold_mb * 1024 * 1024)

    if frame_bytes <= split_threshold_bytes:
        html_path = destination / f"{stem}_report.html"
        manifest.outputs = {
            "mode": "single_file",
            "html": str(html_path),
            "manifest": str(manifest_path),
        }
        base_payload["manifest"] = manifest.to_dict()
        base_payload["analysis"]["frames"] = frames
        _atomic_text(html_path, _render_template(base_payload, []))
        obsolete_path = destination / f"{stem}_report"
        mode = "single_file"
    else:
        report_dir = destination / f"{stem}_report"
        temporary_dir = destination / f".{stem}_report.tmp"
        if temporary_dir.exists():
            shutil.rmtree(temporary_dir)
        temporary_dir.mkdir(parents=True)
        chunk_dir = temporary_dir / "chunks"
        chunk_dir.mkdir()
        chunks = _frame_chunks(frames)
        chunk_scripts: list[str] = []
        for index, chunk in enumerate(chunks, start=1):
            name = f"data_{index:03d}.js"
            content = "window.__NCV_FRAME_CHUNKS__.push(" + _compact_json(chunk) + ");"
            _atomic_text(chunk_dir / name, content)
            chunk_scripts.append(f"chunks/{name}")
        html_path = report_dir / "index.html"
        manifest.outputs = {
            "mode": "script_chunks",
            "html": str(html_path),
            "manifest": str(manifest_path),
            "chunks": str(report_dir / "chunks"),
        }
        base_payload["manifest"] = manifest.to_dict()
        _atomic_text(temporary_dir / "index.html", _render_template(base_payload, chunk_scripts))
        if report_dir.exists():
            shutil.rmtree(report_dir)
        os.replace(temporary_dir, report_dir)
        obsolete_path = destination / f"{stem}_report.html"
        mode = "script_chunks"

    _atomic_text(manifest_path, json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2))
    if obsolete_path.is_dir():
        shutil.rmtree(obsolete_path)
    elif obsolete_path.exists():
        obsolete_path.unlink()
    return ReportOutput(
        html_path=html_path,
        manifest_path=manifest_path,
        mode=mode,
        payload_bytes=frame_bytes,
    )
