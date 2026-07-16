from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

VERSION = "2.0.0"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    if sys.version_info[:2] != (3, 12):
        raise SystemExit("发布包必须使用 Python 3.12 构建")
    root = Path(__file__).resolve().parents[1]
    build_dir = root / "build"
    dist_dir = root / "dist"
    release_dir = root / "release"
    for path in (build_dir, dist_dir):
        if path.exists():
            shutil.rmtree(path)
    release_dir.mkdir(exist_ok=True)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            str(root / "packaging" / "nc_visual_cli.spec"),
        ],
        cwd=root,
        check=True,
    )
    portable = dist_dir / "nc_visual_cli"
    for name in ("README.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "DESIGN_CONTRACT.md"):
        shutil.copy2(root / name, portable / name)
    executable = portable / "nc_visual_cli.exe"
    subprocess.run([str(executable), "--version"], cwd=portable, check=True)
    archive = release_dir / f"nc_visual_cli-v{VERSION}-windows-x64.zip"
    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for path in sorted(portable.rglob("*")):
            if path.is_file():
                bundle.write(path, Path("nc_visual_cli") / path.relative_to(portable))
    checksum = sha256(archive)
    checksum_path = archive.with_suffix(archive.suffix + ".sha256")
    checksum_path.write_bytes(f"{checksum}  {archive.name}\n".encode("ascii"))
    print(archive)
    print(checksum_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
