#!/usr/bin/env python3
"""从规范源同步赛方要求的最小提交目录。"""

from __future__ import annotations

import shutil
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = PROJECT_ROOT / "src" / "starnet" / "submission"
TARGET_DIR = PROJECT_ROOT / "SMP_Starter_Kit" / "team_submission"
REQUIRED_FILES = ("config.json", "starnet_model.py")
REQUIRED_DIRECTORY = "prompt"


def require_source() -> None:
    missing = [name for name in REQUIRED_FILES if not (SOURCE_DIR / name).is_file()]
    if not (SOURCE_DIR / REQUIRED_DIRECTORY).is_dir():
        missing.append(REQUIRED_DIRECTORY + "/")
    if missing:
        raise SystemExit(f"提交源不完整，缺少: {', '.join(missing)}")


def main() -> None:
    require_source()
    TARGET_DIR.mkdir(parents=True, exist_ok=True)

    # Python 导入后的缓存不属于交付契约；仅删除这一类确定的生成物。
    cache_dir = TARGET_DIR / "__pycache__"
    if cache_dir.is_dir() and not cache_dir.is_symlink():
        shutil.rmtree(cache_dir)

    # 仅替换赛方契约明确的三个项目，避免误删未知的本地文件。
    for name in REQUIRED_FILES:
        target = TARGET_DIR / name
        if target.exists() or target.is_symlink():
            target.unlink()
        shutil.copy2(SOURCE_DIR / name, target)

    prompt_target = TARGET_DIR / REQUIRED_DIRECTORY
    if prompt_target.exists() or prompt_target.is_symlink():
        if prompt_target.is_dir() and not prompt_target.is_symlink():
            shutil.rmtree(prompt_target)
        else:
            prompt_target.unlink()
    shutil.copytree(SOURCE_DIR / REQUIRED_DIRECTORY, prompt_target)

    print(f"已同步提交目录: {TARGET_DIR.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
