#!/usr/bin/env python3
"""Paired research policies on the official custom-seed sandbox, without LLM."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from SMP_Starter_Kit.api_client import RemoteStarNetEnv
from scripts.run_local_policy_matrix import LocalPublicEnvironment
from scripts.run_robust_search import BLOCKS, run_robust
from starnet.policy.config import PolicyConfig, PolicyMode
from starnet.runtime.controller import RuntimeController


class PairedEnvironment:
    """Runner-owned remote environment with a separate local replay checker."""

    def __init__(self, seed: dict, server_url: str, timeout: float) -> None:
        self.remote = RemoteStarNetEnv(server_url, seed, timeout=timeout)
        self.shadow = LocalPublicEnvironment(seed)
        self.response_error = 0.0
        self.remote_score: float | None = None
        self.local_score: float | None = None

    def get_remaining_budget(self) -> float:
        actual = self.remote.get_remaining_budget()
        if abs(actual - self.shadow.get_remaining_budget()) > 1e-6:
            raise RuntimeError("remote/local budget mismatch")
        return actual

    def scan_node(self, node_id: int):
        actual = self.remote.scan_node(node_id)
        expected = self.shadow.scan_node(node_id)
        if actual is None or expected is None:
            raise RuntimeError("scan failed during paired probe")
        if set(actual["neighbors"]) != set(expected["neighbors"]):
            raise RuntimeError("remote/local topology mismatch")
        self.response_error = max(self.response_error, abs(actual["w"] - expected["w"]))
        return actual

    def communicate(self, node_id: int, prompt_id: int):
        actual = self.remote.communicate(node_id, prompt_id)
        expected = self.shadow.communicate(node_id, prompt_id)
        if actual.get("status") != expected.get("status") or "new_w" not in actual:
            raise RuntimeError("remote/local communication mismatch")
        self.response_error = max(self.response_error, abs(actual["new_w"] - expected["new_w"]))
        return actual

    def cut_link(self, left: int, right: int):
        actual = self.remote.cut_link(left, right)
        expected = self.shadow.cut_link(left, right)
        if actual != expected:
            raise RuntimeError("remote/local cut mismatch")
        return actual

    def shield_node(self, node_id: int):
        actual = self.remote.shield_node(node_id)
        expected = self.shadow.shield_node(node_id)
        if actual != expected:
            raise RuntimeError("remote/local shield mismatch")
        return actual

    def evaluate(self) -> float:
        # Only this local runner calls settlement; no policy can trigger it.
        self.remote_score = self.remote.trigger_eval()
        self.local_score = self.shadow.evaluate()
        return self.remote_score


def run_baseline(seed: dict, env: PairedEnvironment) -> dict:
    config = PolicyConfig(policy_mode=PolicyMode.PUBLIC_GREEDY,
                          enable_cut=True, enable_shield=True, max_llm_calls=0)
    controller = RuntimeController(env, node_count=len(seed["nodes"]),
                                   initial_budget=env.get_remaining_budget(), config=config)
    while not controller.stopped:
        controller.step()
        if controller.step_number > 119:
            raise RuntimeError("baseline exceeded step limit")
    return {"score": env.evaluate(), "failures": controller.action_failures,
            "steps": sum(call[0] in {"scan", "comm", "cut", "shield"} for call in env.shadow.calls),
            "remaining_budget": env.get_remaining_budget()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--block", choices=tuple(BLOCKS), default="existing")
    parser.add_argument("--family", default="er_balanced")
    parser.add_argument("--repetition", type=int, default=301)
    parser.add_argument("--variants", nargs="+", choices=("baseline", "strict", "bounded"), default=["baseline"])
    parser.add_argument("--server-url", default="http://8.222.218.162:5000")
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    families, generator = BLOCKS[args.block]
    if args.family not in families or args.repetition not in (301, 302, 303):
        parser.error("select a development family and repetition 301-303")
    seed = generator(args.family, 50, args.repetition)
    report = {"family": args.family, "repetition": args.repetition, "node_count": 50,
              "seed_sha256": hashlib.sha256(json.dumps(seed, sort_keys=True).encode()).hexdigest(),
              "evaluation": "official custom-seed sandbox; deterministic research arms without LLM",
              "platform_score": None, "production_promotion_allowed": False, "rows": []}
    for variant in args.variants:
        started = time.perf_counter()
        env = PairedEnvironment(seed, args.server_url, args.timeout)
        result = (run_baseline(seed, env) if variant == "baseline" else
                  run_robust(seed, mode=variant, env_factory=lambda _: env))
        result.update({"variant": variant, "local_replay_score": env.local_score,
                       "settlement_residual": env.remote_score - env.local_score,
                       "maximum_response_error": env.response_error,
                       "seconds": time.perf_counter() - started})
        report["rows"].append(result)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps(result), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
