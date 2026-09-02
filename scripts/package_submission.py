#!/usr/bin/env python3
"""在通过校验后创建根目录无 team_submission 外壳的 ZIP。"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUBMISSION_DIR = PROJECT_ROOT / "SMP_Starter_Kit" / "team_submission"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "artifacts" / "submission"


def validate() -> None:
    command = [sys.executable, str(PROJECT_ROOT / "scripts" / "validate_submission.py")]
    result = subprocess.run(command, cwd=PROJECT_ROOT, check=False)
    if result.returncode:
        raise SystemExit("提交目录未通过校验，未创建 ZIP。")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--name", help="ZIP 文件名；省略时使用 UTC 时间戳")
    args = parser.parse_args()

    validate()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    name = args.name or f"smp2026_submission_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.zip"
    if not name.endswith(".zip"):
        name += ".zip"
    archive = output_dir / name

    with ZipFile(archive, "w", ZIP_DEFLATED) as zip_file:
        for path in sorted(SUBMISSION_DIR.rglob("*")):
            if path.is_file():
                zip_file.write(path, path.relative_to(SUBMISSION_DIR))

    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    manifest = archive.with_suffix(archive.suffix + ".sha256")
    manifest.write_text(f"{checksum}  {archive.name}\n", encoding="utf-8")
    print(f"已创建: {archive}")
    print(f"SHA256: {checksum}")


if __name__ == "__main__":
    main()
