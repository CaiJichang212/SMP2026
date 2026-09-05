#!/usr/bin/env python3
"""使用 OpenAI API 兼容模型在官方沙盒上运行 V0 baseline。"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Mapping, Sequence
from uuid import uuid4

from casevo import LLM_INTERFACE

# ``python scripts/run_baseline_openai.py`` puts this directory, rather than
# the repository root, on ``sys.path``.  Keep the package import for tests and
# the sibling import for the documented direct-script entry point.
try:
    from scripts.openai_compat import DEFAULT_BASE_URL, DEFAULT_MODEL, OpenAICompatibleChat
except ModuleNotFoundError as exc:
    if exc.name != "scripts":
        raise
    from openai_compat import DEFAULT_BASE_URL, DEFAULT_MODEL, OpenAICompatibleChat


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STARTER_KIT = PROJECT_ROOT / "SMP_Starter_Kit"
DEFAULT_SERVER_URL = "http://8.222.218.162:5000"
MIN_INTERVENTION_COST = 2.0
STEP_TRANSITION_HEADROOM = 2
DEFAULT_LOG_DIR = PROJECT_ROOT / "runs" / "v0-baseline"


def load_local_env(path: Path) -> None:
    """加载本地测试所需变量，且不覆盖显式传入的环境变量。"""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", maxsplit=1)
        key = key.strip()
        if key not in {"SMP_LLM_API_KEY", "SMP_LLM_BASE_URL", "SMP_LLM_MODEL"}:
            continue
        value = value.strip().strip("\"'")
        os.environ.setdefault(key, value)


class DisabledEmbedding:
    """V0 不使用 CaseVO 记忆检索；保留 Chroma 所需的嵌入接口。"""

    def __call__(self, input: Sequence[str]) -> list[list[float]]:
        return [[0.0, 0.0, 0.0] for _ in input]

    def name(self) -> str:
        return "starnet_disabled_embedding"


class OpenAICompatibleLLM(LLM_INTERFACE):
    """CaseVO 的最小 OpenAI Chat Completions 兼容适配器。"""

    def __init__(self, api_key: str, base_url: str, model: str, timeout: float) -> None:
        self.chat = OpenAICompatibleChat(api_key, base_url, model, timeout)
        self.embedding = DisabledEmbedding()

    def send_message(self, prompt: str, json_flag: bool = False) -> str:
        return self.chat.complete_json(prompt)

    def send_embedding(self, text_list: Sequence[str]) -> list[list[float]]:
        return self.embedding(text_list)

    def get_lang_embedding(self) -> DisabledEmbedding:
        return self.embedding


def build_submission() -> None:
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "build_submission.py")],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "failed to build submission")


def seed_budget(seed: Mapping[str, object]) -> float | None:
    settings = seed.get("global_setting")
    if not isinstance(settings, Mapping):
        return None
    value = settings.get("max_budget")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def default_step_limit(node_count: int, initial_budget: float) -> int:
    """覆盖完整扫描、最密集干预和结束状态转换的本地安全上限。"""
    if node_count <= 0 or initial_budget < 0:
        raise ValueError("node_count must be positive and initial_budget must be non-negative")
    return node_count + int(initial_budget // MIN_INTERVENTION_COST) + STEP_TRANSITION_HEADROOM


def seed_snapshot_matches(
    seed: Mapping[str, object], nodes: Mapping[int, object], edges: set[tuple[int, int]]
) -> bool:
    expected_nodes = seed.get("nodes")
    expected_edges = seed.get("edges")
    if not isinstance(expected_nodes, list) or not isinstance(expected_edges, list):
        return False
    if len(expected_nodes) != len(nodes):
        return False

    for raw_node in expected_nodes:
        if not isinstance(raw_node, Mapping):
            return False
        node_id = raw_node.get("id")
        weight = raw_node.get("w")
        comm_left = raw_node.get("comm_left")
        if (
            isinstance(node_id, bool)
            or not isinstance(node_id, int)
            or isinstance(weight, bool)
            or not isinstance(weight, (int, float))
            or isinstance(comm_left, bool)
            or not isinstance(comm_left, int)
        ):
            return False
        observed = nodes.get(node_id)
        if (
            observed is None
            or getattr(observed, "w", None) != float(weight)
            or getattr(observed, "persona", None) != raw_node.get("persona")
            or getattr(observed, "comm_left", None) != comm_left
        ):
            return False

    normalized_edges: set[tuple[int, int]] = set()
    for raw_edge in expected_edges:
        if not isinstance(raw_edge, list) or len(raw_edge) != 2:
            return False
        left, right = raw_edge
        if (
            isinstance(left, bool)
            or not isinstance(left, int)
            or isinstance(right, bool)
            or not isinstance(right, int)
            or left == right
        ):
            return False
        normalized_edges.add((left, right) if left < right else (right, left))
    return edges == normalized_edges


def trace_identity(seed_path: Path) -> tuple[str, str, str]:
    """Return a UTC filename stem, readable seed label, and opaque run ID."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    seed_id = "".join(
        character if character.isalnum() or character in {"-", "_"} else "_"
        for character in seed_path.stem
    ).strip("_") or "seed"
    run_id = uuid4().hex[:12]
    return timestamp, seed_id, run_id


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=Path, default=STARTER_KIT / "custom_seeds" / "my_test_network.json")
    parser.add_argument("--server-url", default=DEFAULT_SERVER_URL)
    parser.add_argument("--model", default=os.getenv("SMP_LLM_MODEL", DEFAULT_MODEL))
    parser.add_argument(
        "--node-count",
        type=int,
        help="本地种子的节点数；省略时从 seed 的 nodes 数组推断，仅影响本地调试。",
    )
    parser.add_argument(
        "--stage",
        choices=("preliminary", "final"),
        help="显式资源阶段；省略时仅本地 runner 会把显式 100 节点覆盖映射为复赛。",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        help="覆盖自动计算的本地步数上限；省略时会覆盖完整扫描与干预阶段。",
    )
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=DEFAULT_LOG_DIR,
        help="JSONL 运行轨迹目录（默认: runs/v0-baseline/）。",
    )
    parser.add_argument("--no-console-log", action="store_true", help="关闭每步控制台摘要。")
    parser.add_argument("--no-trace", action="store_true", help="完全关闭诊断日志。")
    return parser.parse_args()


def main() -> int:
    load_local_env(PROJECT_ROOT / ".env")
    args = parse_args()
    api_key = os.getenv("SMP_LLM_API_KEY")
    if not api_key:
        raise SystemExit("缺少 SMP_LLM_API_KEY；请在 .env 或环境变量中配置本地测试密钥。")
    if args.max_steps is not None and args.max_steps <= 0:
        raise SystemExit("--max-steps 必须为正整数。")

    build_submission()
    sys.path.insert(0, str(STARTER_KIT))
    from api_client import RemoteStarNetEnv
    from team_submission.starnet_model import (
        ConsoleTraceSink,
        JsonlTraceSink,
        ParticipantSquadModel,
        PolicyConfig,
        ContestStage,
        RuntimeController,
        RuntimeTrace,
    )

    seed_path = args.seed.resolve()
    with seed_path.open(encoding="utf-8") as seed_file:
        seed = json.load(seed_file)
    seeded_node_count = len(seed.get("nodes", []))
    node_count = args.node_count if args.node_count is not None else seeded_node_count
    if node_count <= 0:
        raise SystemExit("无法从种子推断节点数；请通过 --node-count 指定正整数。")
    stage = (
        ContestStage(args.stage)
        if args.stage is not None
        else (ContestStage.FINAL if node_count == 100 else ContestStage.PRELIMINARY)
    )

    base_url = os.getenv("SMP_LLM_BASE_URL", DEFAULT_BASE_URL)
    llm = OpenAICompatibleLLM(api_key, base_url, args.model, args.timeout)
    env = RemoteStarNetEnv(api_url=args.server_url, custom_seed_data=seed, timeout=args.timeout)
    initial_budget = env.get_remaining_budget()
    max_steps = args.max_steps or default_step_limit(node_count, initial_budget)
    console_enabled = not args.no_trace and not args.no_console_log
    expected_budget = seed_budget(seed)
    budget_matches = (
        expected_budget is not None
        and math.isclose(initial_budget, expected_budget, rel_tol=0.0, abs_tol=1.0e-9)
    )
    if expected_budget is not None and not budget_matches and console_enabled:
        print(f"warning: seed budget={expected_budget}, server budget={initial_budget}; continuing")

    original_cwd = Path.cwd()
    trace: RuntimeTrace | None = None
    trace_path: Path | None = None
    os.chdir(STARTER_KIT / "team_submission")
    try:
        person_list = json.loads((STARTER_KIT / "team_submission" / "config.json").read_text(encoding="utf-8"))["person"]
        model = ParticipantSquadModel(host_env=env, person_list=person_list, llm=llm)
        # The submission default intentionally has no LLM calls.  This local
        # OpenAI-compatible run is the explicit retained three-call experiment.
        model.controller = RuntimeController(
            env,
            model.commander_agent.rank_candidates,
            initial_budget=initial_budget,
            node_count=node_count,
            stage=stage,
            config=PolicyConfig(max_llm_calls=3),
        )
        # 仅使小型自定义种子可完成一轮扫描；提交模型仍由公开预算推断正式赛制规模。
        model.controller.scout.node_count = node_count
        if not args.no_trace:
            timestamp, seed_id, run_id = trace_identity(seed_path)
            sinks: list[object] = []
            try:
                trace_path = args.log_dir.resolve() / f"{timestamp}_{seed_id}_{run_id}.jsonl"
                sinks.append(JsonlTraceSink(trace_path))
            except Exception:
                # Local filesystem diagnostics must not prevent the strategy from running.
                trace_path = None
            if console_enabled:
                sinks.append(ConsoleTraceSink())
            trace = RuntimeTrace(run_id=run_id, seed_id=seed_id, sinks=sinks)
            model.controller.attach_trace(trace)
        model_steps = 0
        snapshot_matches: bool | None = None
        while model_steps < max_steps:
            result = model.step()
            model_steps += 1
            if model.controller.last_action_error is not None:
                detail = getattr(env, "last_protocol_error", None) or model.controller.last_action_error
                model.controller.stop_for_runner_error()
                if trace is not None:
                    trace.close()
                raise RuntimeError(f"controller action error: {detail}")
            if model.controller.state.value == "ANALYZE" and snapshot_matches is None:
                snapshot_matches = seed_snapshot_matches(
                    seed, model.controller.blackboard.nodes, model.controller.blackboard.edges
                )
                if not snapshot_matches:
                    if console_enabled:
                        print("warning: scanned seed snapshot differs from requested seed; score is not comparable")
            if result == 1:
                break
        if not model.controller.stopped:
            model.controller.stop_for_step_limit()
    finally:
        os.chdir(original_cwd)

    pre_eval_budget = env.get_remaining_budget()
    score = env.trigger_eval()
    model.controller.record_evaluation(score, budget_before=pre_eval_budget)
    if snapshot_matches is None:
        snapshot_matches = False
    score_comparable = budget_matches and snapshot_matches
    stop_reason = model.controller.stop_reason.value if model.controller.stop_reason else "max_steps"
    if console_enabled:
        print(
            "baseline complete; "
            f"score={score}; pre_eval_budget={pre_eval_budget}; model_steps={model_steps}; "
            f"actions={model.controller.action_attempts}; successes={model.controller.action_successes}; "
            f"failures={model.controller.action_failures}; known_nodes={len(model.controller.blackboard.nodes)}; "
            f"dead_nodes={len(model.controller.blackboard.dead_nodes)}; candidates={len(model.controller.candidates)}; "
            f"llm_calls={model.controller.llm_calls}; stop_reason={stop_reason}; "
            f"seed_budget_match={budget_matches}; seed_snapshot_match={snapshot_matches}; "
            f"score_comparable={score_comparable}; debug_node_count={node_count}"
        )
    if trace is not None:
        trace.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
