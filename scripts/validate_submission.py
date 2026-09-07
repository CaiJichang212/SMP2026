#!/usr/bin/env python3
"""校验提交目录的文件布局、Python 语法和常见敏感内容。"""

from __future__ import annotations

import ast
import importlib.util
import inspect
import re
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUBMISSION_DIR = PROJECT_ROOT / "SMP_Starter_Kit" / "team_submission"
REQUIRED_TOP_LEVEL = {"config.json", "prompt", "starnet_model.py"}
FORBIDDEN_NAMES = {".env", "__pycache__", ".DS_Store"}
SUSPICIOUS_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\b(?:sk|sk-proj)-[A-Za-z0-9_-]{16,}\b"),
)
FORBIDDEN_ENV_ACCESS = re.compile(r"self\.env\.(?:_[A-Za-z0-9_]+|end_turn)\b")


def fail(message: str) -> None:
    print(f"[失败] {message}", file=sys.stderr)


def validate_dynamic_loader_compatibility(model_file: Path) -> str | None:
    """Exercise the host pattern that omits ``sys.modules`` registration.

    This intentionally differs from a normal import: it catches the Python
    ``dataclasses`` failure that the competition host previously exposed.
    """
    module_name = "_submission_dynamic_loader_probe"
    previous = sys.modules.pop(module_name, None)
    previous_dont_write_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location(module_name, model_file)
        if spec is None or spec.loader is None:
            return "无法为 starnet_model.py 创建动态加载器"
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        candidate_cut = getattr(module, "_cut_candidates", None)
        cmg_cut = getattr(module, "_cmg_cut_candidates", None)
        if not callable(candidate_cut) or len(inspect.signature(candidate_cut).parameters) != 5:
            return "内联后的候选 cut helper 签名不是五参数"
        if not callable(cmg_cut) or len(inspect.signature(cmg_cut).parameters) != 2:
            return "内联后的 CMG cut helper 签名不是两参数"
    except Exception as exc:
        return f"动态加载兼容性失败: {type(exc).__name__}: {exc}"
    finally:
        sys.dont_write_bytecode = previous_dont_write_bytecode
        sys.modules.pop(module_name, None)
        if previous is not None:
            sys.modules[module_name] = previous
    return None


def main() -> int:
    errors: list[str] = []
    if not SUBMISSION_DIR.is_dir():
        errors.append("提交目录不存在")
    else:
        actual = {path.name for path in SUBMISSION_DIR.iterdir()}
        missing = REQUIRED_TOP_LEVEL.difference(actual)
        extras = actual.difference(REQUIRED_TOP_LEVEL)
        if missing:
            errors.append(f"缺少顶层项目: {sorted(missing)}")
        if extras:
            errors.append(f"存在不允许的顶层项目: {sorted(extras)}")
        if not (SUBMISSION_DIR / "prompt").is_dir():
            errors.append("prompt 不是目录")
        elif not any((SUBMISSION_DIR / "prompt").glob("*.txt")):
            errors.append("prompt/ 中没有提示词模板")

        model_file = SUBMISSION_DIR / "starnet_model.py"
        if model_file.is_file():
            try:
                model_source = model_file.read_text(encoding="utf-8")
                model_tree = ast.parse(model_source, filename=str(model_file))
            except SyntaxError as exc:
                errors.append(f"starnet_model.py 语法错误: {exc}")
            else:
                if "from starnet" in model_source or "import starnet" in model_source:
                    errors.append("starnet_model.py 不能依赖 ZIP 外的 starnet 包")
                static_casevo_import = any(
                    (isinstance(node, ast.ImportFrom) and node.module == "casevo")
                    or (
                        isinstance(node, ast.Import)
                        and any(alias.name == "casevo" for alias in node.names)
                    )
                    for node in ast.walk(model_tree)
                )
                if static_casevo_import:
                    errors.append("starnet_model.py 不能静态导入平台缺失的 casevo 包")
                compatibility_error = validate_dynamic_loader_compatibility(model_file)
                if compatibility_error is not None:
                    errors.append(compatibility_error)

        for path in SUBMISSION_DIR.rglob("*"):
            if path.name in FORBIDDEN_NAMES:
                errors.append(f"不允许的文件或目录: {path.relative_to(SUBMISSION_DIR)}")
            if path.is_file():
                content = path.read_text(encoding="utf-8", errors="ignore")
                if any(pattern.search(content) for pattern in SUSPICIOUS_PATTERNS):
                    errors.append(f"疑似私钥或 API Key: {path.relative_to(SUBMISSION_DIR)}")
                if path.name == "starnet_model.py" and FORBIDDEN_ENV_ACCESS.search(content):
                    errors.append("starnet_model.py 调用了环境私有方法或未公开的 end_turn")

    if errors:
        for error in errors:
            fail(error)
        return 1
    print("[通过] 提交目录结构、Python 语法和敏感内容检查均通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
