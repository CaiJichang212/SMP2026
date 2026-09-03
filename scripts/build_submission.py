#!/usr/bin/env python3
"""从规范源同步赛方要求的最小提交目录。"""

from __future__ import annotations

import ast
import shutil
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = PROJECT_ROOT / "src" / "starnet" / "submission"
TARGET_DIR = PROJECT_ROOT / "SMP_Starter_Kit" / "team_submission"
REQUIRED_FILES = ("config.json", "starnet_model.py")
REQUIRED_DIRECTORY = "prompt"
INLINE_MODULES = (
    "src/starnet/model/blackboard.py",
    "src/starnet/policy/actions.py",
    "src/starnet/runtime/env_adapter.py",
    "src/starnet/policy/graph_analysis.py",
    "src/starnet/policy/candidates.py",
    "src/starnet/runtime/controller.py",
    "src/starnet/submission/starnet_model.py",
)


def require_source() -> None:
    missing = [name for name in REQUIRED_FILES if not (SOURCE_DIR / name).is_file()]
    if not (SOURCE_DIR / REQUIRED_DIRECTORY).is_dir():
        missing.append(REQUIRED_DIRECTORY + "/")
    if missing:
        raise SystemExit(f"提交源不完整，缺少: {', '.join(missing)}")


def strip_project_imports(source: str, path: Path) -> str:
    """移除内联后已不需要的项目导入，保留外部运行时依赖。"""
    tree = ast.parse(source, filename=str(path))
    skipped_lines: set[int] = set()
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom):
            continue
        module = node.module or ""
        if module == "__future__" or module == "starnet" or module.startswith("starnet."):
            skipped_lines.update(range(node.lineno, node.end_lineno + 1))
    return "".join(
        line
        for line_number, line in enumerate(source.splitlines(keepends=True), start=1)
        if line_number not in skipped_lines
    )


def assemble_model() -> str:
    """把经单元测试的纯 Python 策略模块收敛为赛方要求的单文件。"""
    chunks = ["from __future__ import annotations\n\n"]
    for relative_name in INLINE_MODULES:
        path = PROJECT_ROOT / relative_name
        if not path.is_file():
            raise SystemExit(f"无法组装提交文件，缺少策略模块: {relative_name}")
        source = path.read_text(encoding="utf-8")
        chunks.append(f"# Begin inline: {relative_name}\n")
        chunks.append(strip_project_imports(source, path))
        chunks.append(f"\n# End inline: {relative_name}\n\n")

    assembled = "".join(chunks).rstrip() + "\n"
    ast.parse(assembled, filename="starnet_model.py")
    return assembled


def main() -> None:
    require_source()
    TARGET_DIR.mkdir(parents=True, exist_ok=True)

    # Python 导入后的缓存不属于交付契约；仅删除这一类确定的生成物。
    cache_dir = TARGET_DIR / "__pycache__"
    if cache_dir.is_dir() and not cache_dir.is_symlink():
        shutil.rmtree(cache_dir)

    # 仅替换赛方契约明确的三个项目，避免误删未知的本地文件。
    for name in ("config.json",):
        target = TARGET_DIR / name
        if target.exists() or target.is_symlink():
            target.unlink()
        shutil.copy2(SOURCE_DIR / name, target)

    model_target = TARGET_DIR / "starnet_model.py"
    if model_target.exists() or model_target.is_symlink():
        model_target.unlink()
    model_target.write_text(assemble_model(), encoding="utf-8")

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
