#!/usr/bin/env python3
"""Account for a paired score difference using public action returns only."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import networkx as nx


def final_public_state(actions):
    graph = nx.Graph()
    opinions = {}
    communications = []
    for item in actions:
        if not item["success"]:
            continue
        kind = item["kind"]
        node = item["target_node_1"]
        result = item["public_result"]
        if kind == "scan":
            graph.add_node(node)
            opinions[node] = float(result["w"])
            graph.add_edges_from((node, other) for other in result["neighbors"])
        elif kind == "comm":
            opinions[node] = float(result["new_w"])
            communications.append(item)
        elif kind == "cut":
            graph.remove_edge(node, item["target_node_2"])
        elif kind == "shield":
            graph.remove_node(node)
            opinions.pop(node)
    erased = [item for item in communications if item["target_node_1"] not in graph]
    return graph, opinions, erased


def attribute(row):
    candidate = row["arms"]["p11"]
    baseline = row["arms"]["p9_no_probe"]
    new_graph, new_w, new_erased = final_public_state(candidate["action_log"])
    old_graph, old_w, old_erased = final_public_state(baseline["action_log"])
    same = (set(new_graph) == set(old_graph)
            and {frozenset(edge) for edge in new_graph.edges}
            == {frozenset(edge) for edge in old_graph.edges})
    report = {
        "case_id": row["case_id"], "seed_sha256": row["seed_sha256"],
        "scope": "public-trace accounting in the calibrated local model; not official-score attribution",
        "same_final_graph": same,
        "observed_score_difference": candidate["score"] - baseline["score"],
        "p11_communications_on_finally_removed_nodes": new_erased,
        "p9_communications_on_finally_removed_nodes": old_erased,
        "p11_erased_communication_budget": sum(
            item["budget_before"] - item["budget_after"] for item in new_erased
        ),
        "interpretation_limit": "The accounting is not an additive causal decomposition of probe selection, estimation, and structure policies.",
    }
    if not same:
        report["node_decomposition"] = None
        return report
    contributions = []
    for component in nx.connected_components(new_graph):
        scale = len(component) / sum(new_graph.degree(node) + 1 for node in component)
        for node in sorted(component):
            delta = new_w[node] - old_w[node]
            if abs(delta) <= 1e-10:
                continue
            influence = scale * (new_graph.degree(node) + 1)
            contributions.append({
                "node_id": node, "p11_final_w": new_w[node], "p9_final_w": old_w[node],
                "public_final_influence": influence, "score_contribution": influence * delta,
            })
    contributions.sort(key=lambda item: (item["score_contribution"], item["node_id"]))
    report["node_decomposition"] = contributions
    report["accounted_score_difference"] = sum(item["score_contribution"] for item in contributions)
    report["accounting_residual"] = report["observed_score_difference"] - report["accounted_score_difference"]
    if abs(report["accounting_residual"]) > 1e-6:
        raise ValueError("public final-state accounting does not match measured local score")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = json.loads(args.input.read_text())
    selected = [row for row in data["rows"] if row["case_id"] == args.case_id]
    if len(selected) != 1:
        raise ValueError("expected one exact case identity")
    report = attribute(selected[0])
    report["cohort_complete_at_analysis"] = data.get("complete", False)
    report["runtime_source_snapshot"] = data["config"]["source_snapshot"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: value for key, value in report.items()
                      if key not in ("runtime_source_snapshot", "node_decomposition")},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
