"""Strict P8 search summary audits."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.summarize_p8_search import summarize


def arm(score: float) -> dict:
    return {"score": score, "actions": {"scan": 50, "comm": 37, "cut": 0, "shield": 0},
            "failures": 0, "remaining_budget": 1.0, "steps": 87}


def report_rows(strata=("standard", "low")) -> dict:
    rows = []
    for stratum in strata:
        for variant, gain in (("first", 1.0), ("second", 2.0)):
            rows.append({"family": "random_tree", "repetition": 501, "r_stratum": stratum,
                         "seed_sha256": ("a" if stratum == "standard" else "b") * 64,
                         "variant": variant, "baseline": arm(100.0),
                         "candidate": arm(100.0 + gain), "delta": gain})
    return {"config": {"nodes": 50, "families": ["random_tree"], "repetitions": [501],
                       "variants": ["first", "second"], "strata": list(strata)},
            "policy_hash": "frozen-policy", "rows": rows}


class SummarizeP8SearchTests(unittest.TestCase):
    def write(self, folder: str, value: dict, name: str = "source.json") -> Path:
        path = Path(folder) / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def invoke(self, path: Path | list[Path], strata=("standard", "low")) -> dict:
        paths = path if isinstance(path, list) else [path]
        return summarize(paths, families=("random_tree",), repetitions=(501,),
                         strata=strata, variants=("first", "second"))

    def test_valid_matrix_is_separated_by_response_stratum(self) -> None:
        with TemporaryDirectory() as folder:
            result = self.invoke(self.write(folder, report_rows()))
        self.assertIsNone(result["cross_stratum_aggregate"])
        self.assertEqual(set(result["strata"]), {"standard", "low"})
        self.assertEqual(result["strata"]["standard"]["first"]["mean_delta"], 1.0)
        self.assertEqual(result["reported_policy_hashes"].popitem()[1], "frozen-policy")

    def test_missing_duplicate_and_wrong_delta_are_rejected(self) -> None:
        for mutation in ("missing", "duplicate", "delta"):
            with self.subTest(mutation=mutation), TemporaryDirectory() as folder:
                data = report_rows(strata=("standard",))
                if mutation == "missing":
                    data["rows"].pop()
                elif mutation == "duplicate":
                    data["rows"].append(dict(data["rows"][0]))
                else:
                    data["rows"][0]["delta"] = 9.0
                with self.assertRaises(ValueError):
                    self.invoke(self.write(folder, data), strata=("standard",))

    def test_cross_arm_seed_and_baseline_mismatch_are_rejected(self) -> None:
        for field in ("seed", "baseline", "baseline_actions"):
            with self.subTest(field=field), TemporaryDirectory() as folder:
                data = report_rows(strata=("standard",))
                if field == "seed":
                    data["rows"][1]["seed_sha256"] = "c" * 64
                else:
                    if field == "baseline":
                        data["rows"][1]["baseline"] = arm(99.0)
                        data["rows"][1]["delta"] = 3.0
                    else:
                        changed = data["rows"][1]["baseline"]
                        changed["actions"] = {"scan": 50, "comm": 35, "cut": 0, "shield": 1}
                        changed["remaining_budget"] = 0.0
                        changed["steps"] = 86
                with self.assertRaises(ValueError):
                    self.invoke(self.write(folder, data), strata=("standard",))

    def test_policy_hashes_must_be_complete_and_consistent_across_sources(self) -> None:
        for second_hash in (None, "different-policy"):
            with self.subTest(second_hash=second_hash), TemporaryDirectory() as folder:
                data = report_rows(strata=("standard",))
                first, second = dict(data), dict(data)
                first["config"] = {**data["config"], "variants": ["first"]}
                second["config"] = {**data["config"], "variants": ["second"]}
                first["rows"] = [row for row in data["rows"] if row["variant"] == "first"]
                second["rows"] = [row for row in data["rows"] if row["variant"] == "second"]
                if second_hash is None:
                    second.pop("policy_hash")
                else:
                    second["policy_hash"] = second_hash
                paths = [self.write(folder, first, "first.json"),
                         self.write(folder, second, "second.json")]
                with self.assertRaises(ValueError):
                    self.invoke(paths, strata=("standard",))

    def test_failed_or_invalid_budget_arm_is_rejected(self) -> None:
        for field in ("failures", "remaining_budget", "scan"):
            with self.subTest(field=field), TemporaryDirectory() as folder:
                data = report_rows(strata=("standard",))
                candidate = data["rows"][0]["candidate"]
                if field == "scan":
                    candidate["actions"]["scan"] = 49
                    candidate["steps"] = 86
                    candidate["remaining_budget"] = 1.5
                else:
                    candidate[field] = 1 if field == "failures" else 2.0
                with self.assertRaises(ValueError):
                    self.invoke(self.write(folder, data), strata=("standard",))


if __name__ == "__main__":
    unittest.main()
