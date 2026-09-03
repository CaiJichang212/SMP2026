#!/usr/bin/env python3
"""校验提交目录的文件布局、Python 语法和常见敏感内容。"""

from __future__ import annotations

import ast
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
                ast.parse(model_source, filename=str(model_file))
            except SyntaxError as exc:
                errors.append(f"starnet_model.py 语法错误: {exc}")
            else:
                if "from starnet" in model_source or "import starnet" in model_source:
                    errors.append("starnet_model.py 不能依赖 ZIP 外的 starnet 包")

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
