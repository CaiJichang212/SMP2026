#!/usr/bin/env python3
"""Run deterministic policy comparisons against the public-API local model.

The simulator deliberately keeps ``r`` inside the environment.  The
controller sees only the same scan and action-return fields exposed by the
starter kit.  This is a fast screening tool for policy shape, not evidence of
hidden leaderboard performance.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import json
from pathlib import Path
import random
from typing import Any

import networkx as nx

from starnet.experiments.seeds import SEED_SPECS, seed_payload
from starnet.model.blackboard import Blackboard
from starnet.policy.config import PolicyConfig, PolicyMode
from starnet.policy.structural import public_positive_graph_gate_closed
from starnet.policy.cmg import PredictiveState, SettlementPredictor
from starnet.runtime.controller import DeterministicScout, RuntimeController


PROMPT_VALUES = {1: 15.0, 2: 10.0, 3: -5.0}
MARGINAL_MULTIPLIERS = {1: 1.0, 2: 0.5, 3: 0.25}
INDEPENDENT_FAMILIES = (
    "grid_lattice",
    "cycle_chords",
    "two_block_bridge",
    "tree_broom",
)
HOLDOUT_FAMILIES = (
    "double_bridge_communities",
    "ring_of_cliques",
    "negative_hub_spokes",
)
VARIANTS = (
    "b1",
    "b1_partial_80pct",
    "public_greedy",
    "public_greedy_llm_mock",
    "public_adaptive_scan_80pct",
)


def independent_seed_payload(
    family: str, node_count: int = 50, repetition: int = 1
) -> dict[str, Any]:
    """Generate a topology-disjoint local validation seed.

    These graph constructors are separate from ``SEED_SPECS`` and are never
    used by the policy.  Their hidden ``r`` values remain environment-only.
    """
    if family not in INDEPENDENT_FAMILIES:
        raise ValueError(f"unknown independent family: {family}")
    if node_count <= 0 or repetition <= 0:
        raise ValueError("node_count and repetition must be positive")
    family_seed = sum((index + 1) * ord(char) for index, char in enumerate(family))
    rng = random.Random(20260908 + family_seed + node_count * 37 + repetition * 7919)
    if family == "grid_lattice":
        rows = max(2, int(node_count**0.5))
        while node_count % rows:
            rows -= 1
        graph = nx.grid_2d_graph(rows, node_count // rows)
        graph = nx.convert_node_labels_to_integers(graph)
    elif family == "cycle_chords":
        graph = nx.cycle_graph(node_count)
        graph.add_edges_from((node, (node + 3) % node_count) for node in range(node_count))
    elif family == "two_block_bridge":
        half = node_count // 2
        left = nx.random_regular_graph(4, half, seed=rng)
        right = nx.random_regular_graph(4, node_count - half, seed=rng)
        graph = nx.disjoint_union(left, right)
        graph.add_edge(half - 1, half)
    else:
        graph = nx.path_graph(node_count)
        for leaf in range(1, node_count, 7):
            graph.add_edge(0, leaf)
        for leaf in range(node_count // 2, node_count, 11):
            graph.add_edge(node_count // 2, leaf)
    graph.add_nodes_from(range(node_count))

    nodes: list[dict[str, Any]] = []
    for node_id in range(node_count):
        if family == "grid_lattice":
            persona = "和平" if rng.random() < 0.78 else "中立"
            weight = rng.uniform(4.0, 24.0) if persona == "和平" else rng.uniform(-2.0, 6.0)
        elif family == "two_block_bridge" and node_id < node_count // 2:
            persona, weight = "暴力", rng.uniform(-42.0, -16.0)
        elif family == "two_block_bridge":
            persona, weight = "和平", rng.uniform(8.0, 28.0)
        elif family == "tree_broom" and node_id % 5 == 0:
            persona, weight = "暴力", rng.uniform(-36.0, -10.0)
        else:
            roll = rng.random()
            persona = "和平" if roll < 0.42 else "中立" if roll < 0.8 else "暴力"
            weight = (
                rng.uniform(4.0, 26.0) if persona == "和平"
                else rng.uniform(-28.0, -4.0) if persona == "暴力"
                else rng.uniform(-8.0, 8.0)
            )
        nodes.append({
            "id": node_id + 1,
            "w": round(weight, 6),
            "persona": persona,
            "r": round(rng.uniform(0.2, 1.5), 6),
            "comm_left": 3,
        })
    return {
        "global_setting": {
            "max_budget": 100.0 if node_count <= 50 else 200.0,
            "max_api_calls": 120 if node_count <= 50 else 250,
        },
        "original_total": round(sum(node["w"] for node in nodes), 6),
        "nodes": nodes,
        "edges": [[left + 1, right + 1] for left, right in sorted(graph.edges)],
        "prompts": PROMPT_VALUES,
    }


def holdout_seed_payload(
    family: str, node_count: int = 50, repetition: int = 1
) -> dict[str, Any]:
    """Return a topology holdout excluded from all earlier local matrices.

    The designs deliberately stress decisions that the original ER/BA/WS/SBM
    and independent grid/cycle/tree blocks do not isolate: redundant bridges,
    component-wide propagation, and dangerous high-degree spokes.  Response
    factors are consumed by :class:`LocalPublicEnvironment` and never appear
    in a scan response or experiment report.
    """
    if family not in HOLDOUT_FAMILIES:
        raise ValueError(f"unknown holdout family: {family}")
    if node_count < 12 or repetition <= 0:
        raise ValueError("holdout node_count must be at least 12; repetition must be positive")
    family_seed = sum((index + 3) * ord(char) for index, char in enumerate(family))
    rng = random.Random(20260912 + family_seed + node_count * 509 + repetition * 10007)
    graph = nx.Graph()
    graph.add_nodes_from(range(node_count))
    if family == "double_bridge_communities":
        split = node_count // 2
        left, right = range(split), range(split, node_count)
        # Cycles make each side connected before sparse internal chords and two
        # independent inter-community routes are added.
        for group in (list(left), list(right)):
            graph.add_edges_from(zip(group, group[1:] + group[:1]))
            for index, node in enumerate(group):
                if index % 3 == 0:
                    graph.add_edge(node, group[(index + 3) % len(group)])
        graph.add_edges_from(((split - 1, split), (split // 2, split + split // 2)))
    elif family == "ring_of_cliques":
        clique_size = max(3, min(6, node_count // 5))
        groups = [list(range(start, min(start + clique_size, node_count))) for start in range(0, node_count, clique_size)]
        for group in groups:
            graph.add_edges_from(nx.complete_graph(group).edges)
        for left, right in zip(groups, groups[1:] + groups[:1]):
            graph.add_edge(left[-1], right[0])
    else:
        # Three negative hubs share a lightly connected periphery.  A policy
        # that only follows degree needs to distinguish the hub signs first.
        hubs = (0, node_count // 3, (2 * node_count) // 3)
        periphery = [node for node in range(node_count) if node not in hubs]
        graph.add_edges_from(zip(periphery, periphery[1:]))
        graph.add_edge(periphery[-1], periphery[0])
        for index, node in enumerate(periphery):
            graph.add_edge(hubs[index % len(hubs)], node)
            if index % 4 == 0:
                graph.add_edge(hubs[(index + 1) % len(hubs)], node)
        graph.add_edges_from(((hubs[0], hubs[1]), (hubs[1], hubs[2])))

    nodes: list[dict[str, Any]] = []
    for node_id in range(node_count):
        if family == "double_bridge_communities":
            persona = "暴力" if node_id < node_count // 2 else "和平"
            weight = rng.uniform(-34.0, -10.0) if persona == "暴力" else rng.uniform(7.0, 25.0)
        elif family == "ring_of_cliques":
            group_index = node_id // max(3, min(6, node_count // 5))
            persona = "暴力" if group_index % 3 == 0 else "和平" if group_index % 3 == 1 else "中立"
            weight = (rng.uniform(-30.0, -7.0) if persona == "暴力" else rng.uniform(6.0, 24.0) if persona == "和平" else rng.uniform(-5.0, 7.0))
        elif node_id in (0, node_count // 3, (2 * node_count) // 3):
            persona, weight = "暴力", rng.uniform(-46.0, -24.0)
        else:
            persona = "和平" if rng.random() < 0.58 else "中立"
            weight = rng.uniform(5.0, 25.0) if persona == "和平" else rng.uniform(-6.0, 6.0)
        nodes.append({"id": node_id + 1, "w": round(weight, 6), "persona": persona,
                      "r": round(rng.uniform(0.2, 1.5), 6), "comm_left": 3})
    return {
        "global_setting": {"max_budget": 100.0 if node_count <= 50 else 200.0,
                           "max_api_calls": 120 if node_count <= 50 else 250},
        "original_total": round(sum(node["w"] for node in nodes), 6),
        "nodes": nodes,
        "edges": [[left + 1, right + 1] for left, right in sorted(graph.edges)],
        "prompts": PROMPT_VALUES,
    }


class LocalPublicEnvironment:
    """Small public-API-compatible environment for policy screening."""

    def __init__(self, seed: Mapping[str, Any]) -> None:
        settings = seed["global_setting"]
        self.budget = float(settings["max_budget"])
        # Keep response factors in the environment's private state.  Neither
        # Blackboard nor scan/action results carry ``r``.
        self._response_factors = {int(node["id"]): float(node["r"]) for node in seed["nodes"]}
        self.nodes = {
            int(node["id"]): {key: value for key, value in node.items() if key != "r"}
            for node in seed["nodes"]
        }
        self.edges = {
            tuple(sorted((int(edge[0]), int(edge[1])))) for edge in seed["edges"]
        }
        self.prompts = {
            int(key): float(value)
            for key, value in dict(seed.get("prompts", PROMPT_VALUES)).items()
        }
        self.calls: list[tuple[Any, ...]] = []

    def get_remaining_budget(self) -> float:
        return self.budget

    def scan_node(self, node_id: int) -> dict[str, Any] | None:
        self.calls.append(("scan", node_id))
        if self.budget < 0.5 or node_id not in self.nodes:
            return None
        self.budget -= 0.5
        node = self.nodes[node_id]
        neighbors = sorted(
            right if left == node_id else left
            for left, right in self.edges
            if node_id in (left, right)
        )
        return {
            "w": float(node["w"]),
            "persona": str(node["persona"]),
            "comm_left": int(node.get("comm_left", 0)),
            "neighbors": neighbors,
        }

    def communicate(self, node_id: int, prompt_id: int) -> dict[str, Any]:
        self.calls.append(("comm", node_id, prompt_id))
        if self.budget < 2.0 or node_id not in self.nodes:
            return {"status": "budget_exhausted"}
        node = self.nodes[node_id]
        left = int(node.get("comm_left", 0))
        if left <= 0 or prompt_id not in self.prompts:
            return {"status": "max_comm_reached"}
        self.budget -= 2.0
        turn = 4 - left
        delta = self.prompts[prompt_id] * self._response_factors[node_id] * MARGINAL_MULTIPLIERS[turn]
        node["w"] = float(node["w"]) + delta
        node["comm_left"] = left - 1
        return {"status": "success", "new_w": node["w"]}

    def cut_link(self, left: int, right: int) -> bool:
        self.calls.append(("cut", left, right))
        edge = tuple(sorted((left, right)))
        if self.budget < 3.0 or edge not in self.edges:
            return False
        self.budget -= 3.0
        self.edges.remove(edge)
        return True

    def shield_node(self, node_id: int) -> bool:
        self.calls.append(("shield", node_id))
        if self.budget < 5.0 or node_id not in self.nodes:
            return False
        self.budget -= 5.0
        del self.nodes[node_id]
        self.edges = {edge for edge in self.edges if node_id not in edge}
        return True

    def evaluate(self) -> float:
        board = Blackboard()
        neighbors = {node_id: [] for node_id in self.nodes}
        for left, right in self.edges:
            if left in neighbors and right in neighbors:
                neighbors[left].append(right)
                neighbors[right].append(left)
        for node_id, node in sorted(self.nodes.items()):
            board.record_scan(
                node_id,
                {
                    "w": node["w"],
                    "persona": node["persona"],
                    "comm_left": node.get("comm_left", 0),
                    "neighbors": sorted(neighbors[node_id]),
                },
            )
        profile = type("Profile", (), {"model": "component_degree_plus_one"})()
        return SettlementPredictor(profile).score(PredictiveState.from_blackboard(board))


def run_variant(seed: Mapping[str, Any], variant: str) -> dict[str, Any]:
    env = LocalPublicEnvironment(seed)
    if variant in {"b1", "b1_partial_80pct"}:
        config = PolicyConfig(
            policy_mode=PolicyMode.B1_PERSUASION,
            enable_shield=False,
            enable_cut=False,
            max_llm_calls=0,
        )
    elif variant in {"public_greedy", "public_greedy_llm_mock", "public_adaptive_scan_80pct"}:
        config = PolicyConfig(
            policy_mode=PolicyMode.PUBLIC_GREEDY,
            enable_shield=True,
            enable_cut=True,
            max_llm_calls=240 if variant == "public_greedy_llm_mock" else 0,
        )
    else:
        raise ValueError(f"unknown variant: {variant}")
    def model_choice(payload: dict[str, Any]) -> dict[str, Any]:
        """Schema-faithful deterministic stand-in; never a quality estimate of an LLM."""
        candidate = payload["candidates"][0]
        return {
            "state_version": payload["state_version"], "mode": "single_action",
            "candidate_id": candidate["candidate_id"], "reason_code": "top_public_roi",
            "evidence_ids": [candidate["evidence_ids"][0]],
        }

    controller = RuntimeController(
        env,
        model_choice if variant == "public_greedy_llm_mock" else None,
        node_count=len(seed["nodes"]),
        initial_budget=env.get_remaining_budget(),
        config=config,
    )
    if variant == "b1_partial_80pct":
        controller.scout = DeterministicScout(int(len(seed["nodes"]) * 0.8))
    adaptive_decided = False
    while not controller.stopped:
        if variant == "public_adaptive_scan_80pct" and not adaptive_decided:
            scanned = len(controller.blackboard.scanned_ids)
            if scanned >= int(len(seed["nodes"]) * 0.8):
                adaptive_decided = True
                violent_negative_share = sum(
                    node.persona == "暴力" and node.w < 0.0
                    for node in controller.blackboard.nodes.values()
                ) / max(1, len(controller.blackboard.nodes))
                if (
                    violent_negative_share < 0.3
                    and not public_positive_graph_gate_closed(controller.blackboard)
                ):
                    controller.scout._next_node_id = len(seed["nodes"]) + 1
                    controller.policy_mode = PolicyMode.B1_PERSUASION
        controller.step()
        if controller.step_number > config.safety_step_limit(len(seed["nodes"])) + 2:
            raise RuntimeError("local controller did not stop")
    actions = {kind: sum(call[0] == kind for call in env.calls) for kind in ("scan", "comm", "cut", "shield")}
    return {
        "score": env.evaluate(),
        "actions": actions,
        "failures": controller.action_failures,
        "remaining_budget": env.get_remaining_budget(),
        "stop_reason": controller.stop_reason.value if controller.stop_reason else None,
        "llm_calls": controller.llm_calls,
    }


def bootstrap_ci(values: list[float], *, samples: int = 10_000) -> tuple[float, float]:
    """Deterministic percentile bootstrap for family-level paired deltas."""
    if not values:
        return (0.0, 0.0)
    rng = random.Random(20260908)
    means = sorted(
        sum(rng.choice(values) for _ in values) / len(values)
        for _ in range(samples)
    )
    return means[int(samples * 0.025)], means[int(samples * 0.975)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--block", choices=("existing", "independent", "holdout"), default="existing")
    parser.add_argument("--node-counts", nargs="+", type=int, default=[50])
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument(
        "--variants", nargs="+", choices=VARIANTS,
        help="Policy variants to pair against b1; defaults to b1 public_greedy.",
    )
    parser.add_argument("--include-llm-mock", action="store_true")
    parser.add_argument("--include-adaptive-scan", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.repetitions <= 0 or any(count <= 0 for count in args.node_counts):
        raise SystemExit("node counts and repetitions must be positive")
    if args.block == "existing":
        families, make_seed = SEED_SPECS, seed_payload
    elif args.block == "independent":
        families, make_seed = INDEPENDENT_FAMILIES, independent_seed_payload
    else:
        families, make_seed = HOLDOUT_FAMILIES, holdout_seed_payload
    requested_variants = list(args.variants or ("b1", "public_greedy"))
    if "b1" not in requested_variants:
        raise SystemExit("--variants must include b1 for paired evaluation")
    if args.include_llm_mock and "public_greedy_llm_mock" not in requested_variants:
        requested_variants.append("public_greedy_llm_mock")
    if args.include_adaptive_scan and "public_adaptive_scan_80pct" not in requested_variants:
        requested_variants.append("public_adaptive_scan_80pct")
    rows: list[dict[str, Any]] = []
    for family in families:
        for node_count in args.node_counts:
            for repetition in range(1, args.repetitions + 1):
                seed = make_seed(family, node_count, repetition)
                for variant in requested_variants:
                    result = run_variant(seed, variant)
                    rows.append({
                        "family": family,
                        "node_count": node_count,
                        "repetition": repetition,
                        "variant": variant,
                        **result,
                    })
    grouped: dict[tuple[str, int], dict[str, list[dict[str, Any]]]] = {}
    for row in rows:
        grouped.setdefault((row["family"], row["node_count"]), {}).setdefault(row["variant"], []).append(row)
    summary: list[dict[str, Any]] = []
    pairwise_summary: list[dict[str, Any]] = []
    for (family, node_count), variants in sorted(grouped.items()):
        b1_rows = variants["b1"]
        public_rows = variants.get("public_greedy", [])
        if len(b1_rows) == len(public_rows) and public_rows:
            b1_mean = sum(row["score"] for row in b1_rows) / len(b1_rows)
            public_mean = sum(row["score"] for row in public_rows) / len(public_rows)
            paired_deltas = [public["score"] - b1["score"] for b1, public in zip(b1_rows, public_rows)]
            structures = sum(
                row["actions"]["cut"] + row["actions"]["shield"] for row in public_rows
            )
            summary.append({
                "family": family,
                "node_count": node_count,
                "repetitions": len(b1_rows),
                "b1_mean": b1_mean,
                "public_greedy_mean": public_mean,
                "delta": public_mean - b1_mean,
                "minimum_paired_delta": min(paired_deltas),
                "structure_action_rate": structures / len(public_rows),
                "failures": sum(row["failures"] for row in b1_rows + public_rows),
            })
        for candidate, candidate_rows in sorted(variants.items()):
            if candidate == "b1" or len(candidate_rows) != len(b1_rows):
                continue
            deltas = [candidate_row["score"] - b1_row["score"] for b1_row, candidate_row in zip(b1_rows, candidate_rows)]
            candidate_calls = sum(sum(row["actions"].values()) for row in candidate_rows)
            candidate_failures = sum(row["failures"] for row in candidate_rows)
            pairwise_summary.append({
                "family": family,
                "node_count": node_count,
                "repetitions": len(b1_rows),
                "baseline": "b1",
                "candidate": candidate,
                "baseline_mean": sum(row["score"] for row in b1_rows) / len(b1_rows),
                "candidate_mean": sum(row["score"] for row in candidate_rows) / len(candidate_rows),
                "mean_paired_delta": sum(deltas) / len(deltas),
                "minimum_paired_delta": min(deltas),
                "loss_count": sum(delta < 0.0 for delta in deltas),
                "candidate_failures": candidate_failures,
                "candidate_failure_rate": candidate_failures / max(1, candidate_calls),
                "mean_actions": {
                    kind: sum(row["actions"][kind] for row in candidate_rows) / len(candidate_rows)
                    for kind in ("scan", "comm", "cut", "shield")
                },
            })
    payload = {
        "block": args.block,
        "families": list(families),
        "variants": requested_variants,
        "rows": rows,
        "summary": summary,
        "pairwise_summary": pairwise_summary,
    }
    if args.include_llm_mock:
        payload["llm_mock_summary"] = [
            {
                "family": family, "node_count": node_count,
                "mean_score": sum(row["score"] for row in variants["public_greedy_llm_mock"]) / len(variants["public_greedy_llm_mock"]),
                "mean_llm_calls": sum(row["llm_calls"] for row in variants["public_greedy_llm_mock"]) / len(variants["public_greedy_llm_mock"]),
                "failures": sum(row["failures"] for row in variants["public_greedy_llm_mock"]),
            }
            for (family, node_count), variants in sorted(grouped.items())
        ]
    if args.include_adaptive_scan:
        payload["adaptive_scan_summary"] = [
            {
                "family": family, "node_count": node_count,
                "mean_score": sum(row["score"] for row in variants["public_adaptive_scan_80pct"]) / len(variants["public_adaptive_scan_80pct"]),
                "delta_vs_public": (
                    sum(row["score"] for row in variants["public_adaptive_scan_80pct"])
                    - sum(row["score"] for row in variants["public_greedy"])
                ) / len(variants["public_adaptive_scan_80pct"]),
                "mean_scans": sum(row["actions"]["scan"] for row in variants["public_adaptive_scan_80pct"]) / len(variants["public_adaptive_scan_80pct"]),
                "failures": sum(row["failures"] for row in variants["public_adaptive_scan_80pct"]),
            }
            for (family, node_count), variants in sorted(grouped.items())
        ]
    family_deltas: dict[str, list[float]] = {}
    for item in summary:
        family_deltas.setdefault(item["family"], []).append(item["delta"])
    family_mean_deltas = {
        family: sum(values) / len(values)
        for family, values in sorted(family_deltas.items())
    }
    bootstrap = bootstrap_ci(list(family_mean_deltas.values()))
    payload["bootstrap"] = {
        "unit": "family mean across node counts",
        "samples": 10_000,
        "family_mean_deltas": family_mean_deltas,
        "mean_delta": sum(family_mean_deltas.values()) / max(1, len(family_mean_deltas)),
        "ci95": list(bootstrap),
    }
    payload["gate"] = {
        "family_mean_nonnegative": all(item["delta"] >= 0.0 for item in summary),
        "bootstrap_lower_nonnegative": bootstrap[0] >= 0.0,
        "zero_failures": all(item["failures"] == 0 for item in summary),
        "structure_action_observed": any(item["structure_action_rate"] > 0.0 for item in summary),
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
