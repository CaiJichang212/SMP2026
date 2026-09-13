#!/usr/bin/env python3
"""从规范源同步赛方要求的最小提交目录。"""

from __future__ import annotations

import ast
import argparse
import hashlib
import json
import shutil
from pathlib import Path

from submission_loader_compat import LOADER_COMPAT_PREAMBLE


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = PROJECT_ROOT / "src" / "starnet" / "submission"
TARGET_DIR = PROJECT_ROOT / "SMP_Starter_Kit" / "team_submission"
REQUIRED_FILES = ("config.json", "starnet_model.py")
REQUIRED_DIRECTORY = "prompt"
INLINE_MODULES = (
    "src/starnet/model/blackboard.py",
    "src/starnet/policy/actions.py",
    "src/starnet/policy/config.py",
    "src/starnet/policy/calibration.py",
    "src/starnet/policy/baseline.py",
    "src/starnet/runtime/env_adapter.py",
    "src/starnet/runtime/trace.py",
    "src/starnet/policy/graph_analysis.py",
    "src/starnet/policy/candidates.py",
    "src/starnet/policy/cmg.py",
    "src/starnet/policy/structural.py",
    "src/starnet/policy/budget_experiment.py",
    "src/starnet/policy/fast_settlement_experiment.py",
    "src/starnet/policy/p8_experiment.py",
    "src/starnet/policy/p8_qualification.py",
    "src/starnet/policy/adaptive.py",
    "src/starnet/runtime/stage.py",
    "src/starnet/runtime/controller.py",
    "src/starnet/runtime/p8_controller.py",
    "src/starnet/submission/starnet_model.py",
)


def require_source() -> None:
    missing = [name for name in REQUIRED_FILES if not (SOURCE_DIR / name).is_file()]
    if not (SOURCE_DIR / REQUIRED_DIRECTORY).is_dir():
        missing.append(REQUIRED_DIRECTORY + "/")
    if missing:
        raise SystemExit(f"提交源不完整，缺少: {', '.join(missing)}")


def verify_p8_release() -> None:
    """Do not package an enabled P8 flag with stale policy/evidence metadata."""
    from starnet.policy.p8_qualification import (
        P8_CERTIFIED_MODE, P8_GATE_REPORT_SHA256, P8_GATE_REPORT_RELATIVE_PATH, qualified_p8_mode,
    )
    config = json.loads((SOURCE_DIR / "config.json").read_text(encoding="utf-8"))
    requested = next((person.get("experimental_p8_mode") for person in config.get("person", [])
                      if isinstance(person, dict) and person.get("role") == "CommanderAgent"), None)
    if qualified_p8_mode(requested) is None:
        return
    report = PROJECT_ROOT / P8_GATE_REPORT_RELATIVE_PATH
    if not report.is_file() or hashlib.sha256(report.read_bytes()).hexdigest() != P8_GATE_REPORT_SHA256:
        raise SystemExit("P8 资格报告缺失或哈希不匹配。")
    evidence = json.loads(report.read_text(encoding="utf-8"))
    if "release_gate_pending" in evidence and evidence.get("release_gate_passed") is not True:
        raise SystemExit("策略统计门禁不能替代最终入口验证；发布证据尚未封存。")
    source_hashes = set(evidence.get("standard_audit", {}).get("reported_policy_hashes", {}).values())
    source = PROJECT_ROOT / "src/starnet/policy/p8_experiment.py"
    if source_hashes != {hashlib.sha256(source.read_bytes()).hexdigest()}:
        raise SystemExit("P8 策略源码已改变，必须重新验证资格后才能构建启用包。")
    if (evidence.get("selected_variant") != P8_CERTIFIED_MODE
            or evidence.get("variants", {}).get(P8_CERTIFIED_MODE, {}).get("mean_score_gate_passed") is not True):
        raise SystemExit("P8 资格报告未批准当前模式。")
    manifest_path = PROJECT_ROOT / "experiments/manifests/p8-release-sources-20260913.json"
    if not manifest_path.is_file():
        raise SystemExit("P8 运行源码审阅清单缺失。")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_paths = set(INLINE_MODULES) | {"src/starnet/submission/config.json"}
    expected_paths.update(str(path.relative_to(PROJECT_ROOT)) for path in (SOURCE_DIR / "prompt").rglob("*") if path.is_file())
    if (manifest.get("gate_report_sha256") != P8_GATE_REPORT_SHA256
            or set(manifest.get("files", {})) != expected_paths):
        raise SystemExit("P8 运行源码审阅清单与当前构建不一致。")
    for relative, digest in manifest["files"].items():
        if hashlib.sha256((PROJECT_ROOT / relative).read_bytes()).hexdigest() != digest:
            raise SystemExit(f"P8 已审阅运行源码发生变化: {relative}；请验证后更新资格记录。")


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
    chunks = ["from __future__ import annotations\n\n", LOADER_COMPAT_PREAMBLE, "\n"]
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--experimental-policy-mode",
        choices=("public_greedy",),
        help="写入显式实验配置；省略时严格使用规范源的 B1 默认配置。",
    )
    args = parser.parse_args()
    require_source()
    verify_p8_release()
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    # Python 导入后的缓存不属于交付契约；仅删除这一类确定的生成物。
    cache_dir = TARGET_DIR / "__pycache__"
    if cache_dir.is_symlink():
        cache_dir.unlink()
    elif cache_dir.is_dir():
        shutil.rmtree(cache_dir)

    # 仅替换赛方契约明确的三个项目，避免误删未知的本地文件。
    for name in ("config.json",):
        target = TARGET_DIR / name
        if target.exists() or target.is_symlink():
            target.unlink()
        if args.experimental_policy_mode is None:
            shutil.copy2(SOURCE_DIR / name, target)
        else:
            config = json.loads((SOURCE_DIR / name).read_text(encoding="utf-8"))
            config["policy_mode"] = args.experimental_policy_mode
            config["llm_schedule"] = "step"
            people = config.get("person")
            if not isinstance(people, list) or not people or not isinstance(people[0], dict):
                raise SystemExit("实验配置需要至少一个 person 对象")
            commander = next(
                (person for person in people if isinstance(person, dict) and person.get("role") == "CommanderAgent"),
                people[0],
            )
            config["person"] = [{**commander, "experimental_policy_mode": args.experimental_policy_mode}]
            target.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

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
    if args.experimental_policy_mode is None:
        shutil.copytree(SOURCE_DIR / REQUIRED_DIRECTORY, prompt_target)
    else:
        prompt_target.mkdir()
        for name in ("commander_react.txt", "reflect.txt"):
            shutil.copy2(SOURCE_DIR / REQUIRED_DIRECTORY / name, prompt_target / name)

    print(f"已同步提交目录: {TARGET_DIR.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
