from __future__ import annotations

import hashlib
import json
import platform
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD_ROOT = ROOT / "build" / "offline_environment"
RELEASE_DIR = ROOT / "release"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(*command: str | Path) -> None:
    subprocess.run([str(part) for part in command], cwd=ROOT, check=True)


def project_version() -> str:
    document = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(document["project"]["version"])


def main() -> int:
    if sys.platform != "win32" or platform.machine().casefold() not in {"amd64", "x86_64"}:
        raise SystemExit("离线环境包必须在 Windows x64 上构建和验证")
    uv = shutil.which("uv")
    if uv is None:
        raise SystemExit("未找到 uv，请先安装 https://docs.astral.sh/uv/")

    version = project_version()
    bundle_name = f"nc_visual_cli-v{version}-python312-windows-x64-offline-env"
    bundle_dir = BUILD_ROOT / bundle_name
    wheelhouse = bundle_dir / "wheelhouse"
    requirements = bundle_dir / "requirements.lock"
    if BUILD_ROOT.exists():
        shutil.rmtree(BUILD_ROOT)
    wheelhouse.mkdir(parents=True)

    run(
        uv,
        "export",
        "--frozen",
        "--no-dev",
        "--no-emit-project",
        "--format",
        "requirements.txt",
        "--output-file",
        requirements,
    )
    run(
        uv,
        "tool",
        "run",
        "--python",
        "3.12",
        "--from",
        "pip",
        "pip",
        "download",
        "--require-hashes",
        "--only-binary=:all:",
        "--dest",
        wheelhouse,
        "--requirement",
        requirements,
    )
    run(
        uv,
        "build",
        "--wheel",
        "--out-dir",
        wheelhouse,
        "--no-create-gitignore",
    )

    wheels = sorted(wheelhouse.glob("*.whl"), key=lambda path: path.name.casefold())
    project_wheels = list(wheelhouse.glob(f"nc_visual_cli-{version}-*.whl"))
    if not wheels or len(project_wheels) != 1:
        raise SystemExit("离线环境 wheel 集合不完整")

    manifest = {
        "schema_version": "1.0.0",
        "project": "nc-visual-cli",
        "project_version": version,
        "python": "CPython 3.12 x64",
        "platform": "Windows x64",
        "install_command": (
            f'py -3.12 -m pip install --no-index --find-links wheelhouse '
            f'nc-visual-cli=={version}'
        ),
        "wheels": [
            {"file": path.name, "size_bytes": path.stat().st_size, "sha256": sha256(path)}
            for path in wheels
        ],
    }
    (bundle_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )
    (bundle_dir / "install.cmd").write_bytes(
        (
            "@echo off\r\n"
            "setlocal\r\n"
            f'py -3.12 -m pip install --no-index --find-links "%~dp0wheelhouse" '
            f"nc-visual-cli=={version}\r\n"
        ).encode("ascii")
    )
    (bundle_dir / "README.txt").write_text(
        (
            "nc_visual_cli offline Python environment\n"
            "========================================\n\n"
            "Target: CPython 3.12 x64 on Windows x64.\n"
            "The wheelhouse contains the project and all pinned runtime dependencies.\n\n"
            "Install without network access:\n"
            "  1. Install CPython 3.12 x64 with pip.\n"
            "  2. Run install.cmd from this directory.\n\n"
            "Manual command:\n"
            f"  py -3.12 -m pip install --no-index --find-links wheelhouse "
            f"nc-visual-cli=={version}\n"
        ),
        encoding="utf-8",
        newline="\n",
    )

    verify_venv = BUILD_ROOT / "verify_venv"
    run(uv, "venv", "--python", "3.12", "--seed", verify_venv)
    verify_python = verify_venv / "Scripts" / "python.exe"
    run(
        verify_python,
        "-m",
        "pip",
        "install",
        "--no-index",
        "--find-links",
        wheelhouse,
        f"nc-visual-cli=={version}",
    )
    run(verify_python, "-m", "nc_visual_cli", "--version")
    run(
        verify_python,
        "-m",
        "nc_visual_cli",
        ROOT / "demo_data",
        "--output",
        BUILD_ROOT / "verify_report",
        "--json",
    )

    RELEASE_DIR.mkdir(exist_ok=True)
    archive = RELEASE_DIR / f"{bundle_name}.zip"
    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for path in sorted(bundle_dir.rglob("*")):
            if path.is_file():
                bundle.write(path, Path(bundle_name) / path.relative_to(bundle_dir))
    checksum_path = archive.with_suffix(archive.suffix + ".sha256")
    checksum_path.write_bytes(f"{sha256(archive)}  {archive.name}\n".encode("ascii"))
    print(archive)
    print(checksum_path)
    print(f"wheels={len(wheels)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
