#!/usr/bin/env python3
"""Paired P7 score diagnostics; oracle values are not full-action bounds.

Only this offline runner reads custom-seed response factors. The production
policy receives public scan/action feedback through ``run_variant`` unchanged.
"""

from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import math
from pathlib import Path
import statistics
from typing import Any, Mapping

import networkx as nx

try:
    from scripts.run_local_policy_matrix import LocalPublicEnvironment, run_variant
except ModuleNotFoundError as exc:
    if exc.name != "scripts":
        raise
    from run_local_policy_matrix import LocalPublicEnvironment, run_variant
from starnet.experiments.p7_seeds import (
    CONFIRMATION_REPETITIONS,
    DEVELOPMENT_REPETITIONS,
    FAMILIES,
    R_STRATA,
    seed_payload,
)


def fixed_topology_coefficients(seed: Mapping[str, Any]) -> dict[int, float]:
    """Score sensitivity to each opinion under the calibrated local model."""
    graph = nx.Graph()
    graph.add_nodes_from(int(node["id"]) for node in seed["nodes"])
    graph.add_edges_from((int(left), int(right)) for left, right in seed["edges"])
    coefficients = {}
    for component in nx.connected_components(graph):
        denominator = sum(graph.degree(node) + 1 for node in component)
        coefficients.update({
            node: len(component) * (graph.degree(node) + 1) / denominator
            for node in component
        })
    return coefficients


def persuasion_oracle(
    seed: Mapping[str, Any], *, free_scan: bool = False,
) -> tuple[float, list[int]]:
    """Best fixed-topology prompt-1 allocation with known offline ``r``.

    Its knowledge and (for ``free_scan``) resources exceed the real policy's.
    It excludes every cut and shield, so it is not an all-action upper bound.
    """
    coefficients = fixed_topology_coefficients(seed)
    base = sum(coefficients[int(node["id"])] * float(node["w"]) for node in seed["nodes"])
    total_budget = float(seed["global_setting"]["max_budget"])
    scan_cost = 0.0 if free_scan else 0.5 * len(seed["nodes"])
    available_actions = max(0, math.floor((total_budget - scan_cost) / 2.0))
    prompts = {int(key): float(value) for key, value in seed["prompts"].items()}
    if 1 not in prompts:
        raise ValueError("P7 oracle requires prompt 1")
    prompt = prompts[1]
    if prompt <= 0 or prompt < max(prompts.values()):
        raise ValueError("P7 oracle requires prompt 1 to be the dominant positive prompt")

    response = {int(node["id"]): float(node["r"]) for node in seed["nodes"]}
    limits = {int(node["id"]): min(3, int(node["comm_left"])) for node in seed["nodes"]}
    first_turn = {node: 4 - remaining for node, remaining in limits.items()}
    multipliers = {1: 1.0, 2: 0.5, 3: 0.25}
    heap = [(-coefficients[node] * prompt * factor * multipliers[first_turn[node]],
             node, first_turn[node])
            for node, factor in response.items() if limits[node] > 0]
    heapq.heapify(heap)
    allocation: list[int] = []
    gain = 0.0
    while heap and len(allocation) < available_actions:
        negative_gain, node, turn = heapq.heappop(heap)
        if negative_gain >= 0:
            break
        gain -= negative_gain
        allocation.append(node)
        if turn < 3:
            heapq.heappush(heap, (
                -coefficients[node] * prompt * response[node] * multipliers[turn + 1],
                node,
                turn + 1,
            ))
    return base + gain, allocation


def diagnose(seed: Mapping[str, Any]) -> dict[str, Any]:
    """Pair deterministic PUBLIC_GREEDY with two offline oracle diagnostics."""
    natural = LocalPublicEnvironment(seed).evaluate()
    full_score, full_actions = persuasion_oracle(seed)
    free_score, free_actions = persuasion_oracle(seed, free_scan=True)
    policy = run_variant(seed, "public_greedy")
    if policy["failures"] or policy["actions"]["scan"] != len(seed["nodes"]):
        raise RuntimeError("P7 public_greedy comparison was not a valid full run")
    return {
        "natural_score": natural,
        "full_scan_fixed_topology_persuasion_oracle": full_score,
        "free_scan_fixed_topology_persuasion_oracle": free_score,
        "public_greedy_score": policy["score"],
        "full_scan_oracle_communications": len(full_actions),
        "free_scan_oracle_communications": len(free_actions),
        "public_greedy_actions": policy["actions"],
        "public_greedy_remaining_budget": policy["remaining_budget"],
        "public_greedy_failures": policy["failures"],
    }


def _mean(rows: list[dict[str, Any]], field: str) -> float:
    return statistics.fmean(row[field] for row in rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", choices=("development", "confirmation"), default="development")
    parser.add_argument("--families", nargs="+", choices=FAMILIES, default=list(FAMILIES))
    parser.add_argument("--strata", nargs="+", choices=tuple(R_STRATA), default=list(R_STRATA))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    repetitions = DEVELOPMENT_REPETITIONS if args.cohort == "development" else CONFIRMATION_REPETITIONS
    rows = []
    for family in args.families:
        for repetition in repetitions:
            for stratum in args.strata:
                seed = seed_payload(family, repetition, stratum)
                seed_digest = hashlib.sha256(json.dumps(seed, sort_keys=True).encode()).hexdigest()
                rows.append({
                    "family": family,
                    "repetition": repetition,
                    "r_stratum": stratum,
                    "seed_sha256": seed_digest,
                    **diagnose(seed),
                })
    score_fields = (
        "natural_score",
        "full_scan_fixed_topology_persuasion_oracle",
        "free_scan_fixed_topology_persuasion_oracle",
        "public_greedy_score",
    )
    strata_summary = []
    for stratum in args.strata:
        selected = [row for row in rows if row["r_stratum"] == stratum]
        strata_summary.append({"r_stratum": stratum, "cases": len(selected),
                               **{field: _mean(selected, field) for field in score_fields}})
    family_summary = []
    for family in args.families:
        selected = [row for row in rows if row["family"] == family]
        family_summary.append({"family": family, "cases": len(selected),
                               **{field: _mean(selected, field) for field in score_fields}})
    report = {
        "schema_version": 1,
        "purpose": "local diagnostics only; not a platform score or full-action-space upper bound",
        "cohort": args.cohort,
        "repetitions": repetitions,
        "r_strata": R_STRATA,
        "oracle_assumptions": "fixed topology, prompt 1, known seed r; full-scan costs 25, free-scan costs 0",
        "rows": rows,
        "family_summary": family_summary,
        "strata_summary": strata_summary,
        "overall": {"cases": len(rows), **{field: _mean(rows, field) for field in score_fields}},
    }
    output = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
