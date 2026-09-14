"""Exact, auditable reuse helpers for P11 no-probe reference arms."""

from __future__ import annotations

import copy
import hashlib
import json


def json_digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def seed_without_prompts(seed: dict) -> str:
    public_and_hidden_state = {key: value for key, value in seed.items() if key != "prompts"}
    return json_digest(public_and_hidden_state)


def _prompt_strength(seed: dict, prompt_id: int) -> float:
    return float(seed["prompts"][str(prompt_id)])


def _assert_same_state(source_seed: dict, target_seed: dict) -> None:
    if seed_without_prompts(source_seed) != seed_without_prompts(target_seed):
        raise ValueError("reference reuse requires identical graph, opinions and response factors")


def reuse_prompt1_result(
    result: dict, source_seed: dict, target_seed: dict, *, source_case_id: str,
) -> dict:
    """Reuse an arm proven to dispatch only prompt 1 at the same strength."""
    _assert_same_state(source_seed, target_seed)
    if _prompt_strength(source_seed, 1) != _prompt_strength(target_seed, 1):
        raise ValueError("prompt-1 strength differs")
    for record in result["action_log"]:
        if record["kind"] == "comm" and record["prompt_id"] != 1:
            raise ValueError("reference used a non-prompt-1 action")
    reused = copy.deepcopy(result)
    reused["reference_cache"] = {
        "kind": "identical_prompt1_execution",
        "source_case_id": source_case_id,
        "source_action_log_sha256": result["action_log_sha256"],
    }
    return reused


def reuse_known_best_result(
    result: dict, source_seed: dict, target_seed: dict, *,
    source_prompt_id: int, target_prompt_id: int, source_case_id: str,
) -> dict:
    """Relabel a known-ID P9 trace when the dispatched strength is identical."""
    _assert_same_state(source_seed, target_seed)
    if (_prompt_strength(source_seed, source_prompt_id)
            != _prompt_strength(target_seed, target_prompt_id)):
        raise ValueError("known-best strengths differ")
    reused = copy.deepcopy(result)
    for record in reused["action_log"]:
        if record["kind"] != "comm":
            continue
        if (record.get("requested_prompt_id") != 1
                or record.get("dispatched_prompt_id") != source_prompt_id
                or record["prompt_id"] != source_prompt_id):
            raise ValueError("known-ID trace does not have the expected mapping")
        record["prompt_id"] = target_prompt_id
        record["dispatched_prompt_id"] = target_prompt_id
    reused["known_prompt_id"] = target_prompt_id
    reused["action_log_sha256"] = json_digest(reused["action_log"])
    reused["reference_cache"] = {
        "kind": "equal_strength_known_id_relabel",
        "source_case_id": source_case_id,
        "source_prompt_id": source_prompt_id,
        "target_prompt_id": target_prompt_id,
        "source_action_log_sha256": result["action_log_sha256"],
    }
    return reused


__all__ = [
    "reuse_known_best_result", "reuse_prompt1_result", "seed_without_prompts",
]
