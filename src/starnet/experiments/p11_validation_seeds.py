"""P11 prompt-map validation cases with a closed fresh-confirmation boundary."""

from __future__ import annotations

import copy
import hashlib
import itertools
import random
from typing import Any, Iterator

from starnet.experiments.p9_distribution_seeds import _base_opinion, _graph
from starnet.experiments.p9_distribution_seeds import seed_payload as p9_seed_payload
from starnet.experiments.seeds import SEED_SPECS, seed_payload as legacy_seed_payload


FAMILIES = ("er_resampled", "ba_resampled", "ws_resampled", "sbm_resampled")
RESPONSE_STRATA = ("independent", "persona_correlated")
STRESS_RESPONSE_STRATUM = "degree_correlated"
CONFIRMATION_REPETITIONS = (1401, 1402, 1403)
DEVELOPMENT_AMPLITUDES = {
    "base": (15.0, 10.0, -5.0),
    "wide": (24.0, 7.0, -12.0),
    "close": (6.0, 5.0, 4.0),
}
CONFIRMATION_CORE_AMPLITUDES = {
    "medium": (18.0, 8.0, -7.0),
    "compact": (8.0, 6.0, 3.0),
}


def _rng(family: str, repetition: int, stream: str) -> random.Random:
    material = f"SMP2026:P11:{family}:{repetition}:{stream}".encode("ascii")
    return random.Random(int.from_bytes(hashlib.sha256(material).digest()[:8], "big"))


def _permutations(values: tuple[float, float, float]):
    return tuple(itertools.permutations(values))


def _with_prompts(seed: dict[str, Any], values: tuple[float, float, float]) -> dict[str, Any]:
    result = copy.deepcopy(seed)
    result["prompts"] = {str(index): value for index, value in enumerate(values, 1)}
    return result


def development_cases() -> Iterator[tuple[str, str, tuple[float, float, float], dict[str, Any]]]:
    blocks = [
        (f"legacy:{family}:1", legacy_seed_payload(family, 50, 1))
        for family in SEED_SPECS
    ]
    blocks.extend(
        (f"p9:{family}:901:{stratum}", p9_seed_payload(family, 901, stratum))
        for family in FAMILIES
        for stratum in ("centered_independent", "negative_persona_aligned")
    )
    for block_id, seed in blocks:
        for amplitude, values in DEVELOPMENT_AMPLITUDES.items():
            for permutation in _permutations(values):
                case_id = block_id + ":" + amplitude + ":" + "_".join(str(value) for value in permutation)
                yield case_id, amplitude, permutation, _with_prompts(seed, permutation)


def _confirmation_base_seed(family: str, repetition: int, response_stratum: str) -> dict[str, Any]:
    graph = _graph(family, 50, _rng(family, repetition, "topology"))
    label_rng = _rng(family, repetition, "labels")
    labels = list(range(1, 51))
    label_rng.shuffle(labels)
    remap = dict(enumerate(labels))
    opinion_rng = _rng(family, repetition, "opinions")
    response_rng = _rng(family, repetition, f"responses:{response_stratum}")
    degrees = dict(graph.degree())
    minimum_degree, maximum_degree = min(degrees.values()), max(degrees.values())
    nodes = []
    for original in range(50):
        persona, opinion = _base_opinion(opinion_rng)
        if response_stratum == STRESS_RESPONSE_STRATUM:
            fraction = ((degrees[original] - minimum_degree)
                        / max(1, maximum_degree - minimum_degree))
            factor = min(1.5, max(
                0.2, 0.2 + 1.3 * fraction + response_rng.uniform(-0.06, 0.06),
            ))
        elif response_stratum == "independent" or persona == "中立":
            factor = response_rng.uniform(0.2, 1.5)
        else:
            bounds = {"和平": (1.05, 1.5), "暴力": (0.2, 0.65)}[persona]
            factor = response_rng.uniform(*bounds)
        nodes.append({"id": remap[original], "w": round(opinion, 6),
                      "persona": persona, "r": round(factor, 6), "comm_left": 3})
    nodes.sort(key=lambda item: item["id"])
    edges = sorted([min(remap[left], remap[right]), max(remap[left], remap[right])]
                   for left, right in graph.edges())
    return {"global_setting": {"max_budget": 100.0, "max_api_calls": 120},
            "original_total": round(sum(node["w"] for node in nodes), 6),
            "nodes": nodes, "edges": edges,
            "prompts": {"1": 15.0, "2": 10.0, "3": -5.0}}


def confirmation_cases(*, allow_confirmation: bool = False):
    """Yield the frozen 336-case fresh cohort only after explicit unlock."""
    if not allow_confirmation:
        raise ValueError("P11 fresh confirmation is reserved")
    blocks = [
        (family, repetition, response)
        for family in FAMILIES
        for repetition in CONFIRMATION_REPETITIONS
        for response in RESPONSE_STRATA
    ]
    for family, repetition, response in blocks:
        seed = _confirmation_base_seed(family, repetition, response)
        for amplitude, values in CONFIRMATION_CORE_AMPLITUDES.items():
            for permutation in _permutations(values):
                case_id = f"{family}:{repetition}:{response}:core:{amplitude}:" + "_".join(map(str, permutation))
                yield case_id, "core_" + amplitude, permutation, _with_prompts(seed, permutation)
    for family, repetition, response, mode, values in confirmation_edge_assignments():
        seed = _confirmation_base_seed(family, repetition, response)
        case_id = f"{family}:{repetition}:{response}:edge:{mode}:" + "_".join(map(str, values))
        yield case_id, "edge_" + mode, values, _with_prompts(seed, values)
    for family in FAMILIES:
        seed = _confirmation_base_seed(family, 1401, STRESS_RESPONSE_STRATUM)
        for values in _permutations(CONFIRMATION_CORE_AMPLITUDES["medium"]):
            case_id = f"{family}:1401:{STRESS_RESPONSE_STRATUM}:stress:medium:" + "_".join(map(str, values))
            yield case_id, "stress_degree", values, _with_prompts(seed, values)


def confirmation_edge_assignments():
    """Return balanced public design metadata without generating fresh seeds."""
    graph_blocks = [
        (family, repetition)
        for family in FAMILIES for repetition in CONFIRMATION_REPETITIONS
    ]
    tie_values = ((12.0, 12.0, -4.0), (12.0, -4.0, 12.0), (-4.0, 12.0, 12.0))
    negative = _permutations((-2.0, -6.0, -11.0))
    clipped = _permutations((90.0, 20.0, -10.0))
    rows = []
    for index, (family, repetition) in enumerate(graph_blocks):
        allocation = {
            "independent": (("tie", "zero") if index % 2 == 0
                            else ("all_negative", "clip")),
            "persona_correlated": (("all_negative", "clip") if index % 2 == 0
                                   else ("tie", "zero")),
        }
        values_by_mode = {
            "tie": tie_values[index % 3],
            "zero": (0.0, 0.0, 0.0),
            "all_negative": negative[index % 6],
            "clip": clipped[index % 6],
        }
        for response in RESPONSE_STRATA:
            for mode in allocation[response]:
                rows.append((family, repetition, response, mode, values_by_mode[mode]))
    return tuple(rows)


__all__ = [
    "CONFIRMATION_REPETITIONS", "DEVELOPMENT_AMPLITUDES", "FAMILIES",
    "RESPONSE_STRATA", "STRESS_RESPONSE_STRATUM", "confirmation_cases", "confirmation_edge_assignments",
    "development_cases",
]
