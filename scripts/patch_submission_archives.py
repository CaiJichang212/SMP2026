#!/usr/bin/env python3
"""Patch legacy submission ZIPs for loader and framework-runtime compatibility."""

from __future__ import annotations

import argparse
import hashlib
import os
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from submission_loader_compat import (
    inject_cmg_symbol_collision_fix,
    inject_framework_compat,
    inject_loader_compat,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVE_DIR = PROJECT_ROOT / "artifacts" / "submission"
MODEL_MEMBER = "starnet_model.py"


def patch_archive(archive: Path, *, dry_run: bool) -> bool:
    """Patch exactly one root-level model member, preserving every other entry."""
    with ZipFile(archive, "r") as source:
        members = source.infolist()
        model_members = [member for member in members if member.filename == MODEL_MEMBER]
        if len(model_members) != 1:
            raise ValueError(f"{archive}: 必须且只能包含一个 {MODEL_MEMBER}")
        source_code = source.read(model_members[0]).decode("utf-8")
        patched_source, loader_changed = inject_loader_compat(source_code)
        patched_source, framework_changed = inject_framework_compat(patched_source)
        patched_source, cmg_changed = inject_cmg_symbol_collision_fix(patched_source)
        changed = loader_changed or framework_changed or cmg_changed
        if not changed:
            return False
        if dry_run:
            return True

        temporary = tempfile.NamedTemporaryFile(
            prefix=f".{archive.stem}.", suffix=".zip", dir=archive.parent, delete=False,
        )
        temporary_path = Path(temporary.name)
        temporary.close()
        try:
            with ZipFile(temporary_path, "w", ZIP_DEFLATED) as target:
                target.comment = source.comment
                for member in members:
                    payload = source.read(member)
                    if member.filename == MODEL_MEMBER:
                        payload = patched_source.encode("utf-8")
                    target.writestr(member, payload, compress_type=member.compress_type)
            os.replace(temporary_path, archive)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()

    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    manifest = archive.with_suffix(archive.suffix + ".sha256")
    manifest.write_text(f"{checksum}  {archive.name}\n", encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archives", nargs="*", type=Path, help="要修补的 ZIP；默认修补 artifacts/submission/*.zip")
    parser.add_argument("--dry-run", action="store_true", help="仅报告会被修补的 ZIP")
    args = parser.parse_args()

    archives = args.archives or sorted(DEFAULT_ARCHIVE_DIR.glob("*.zip"))
    if not archives:
        raise SystemExit("未找到提交 ZIP")
    for archive in archives:
        archive = archive.resolve()
        if not archive.is_file() or archive.suffix != ".zip":
            raise SystemExit(f"不是可修补的 ZIP: {archive}")
        changed = patch_archive(archive, dry_run=args.dry_run)
        status = "would patch" if args.dry_run else "patched"
        print(f"{status if changed else 'unchanged'}: {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
