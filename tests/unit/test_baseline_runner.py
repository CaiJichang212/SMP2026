"""本地 OpenAI 兼容运行器的脱敏诊断辅助函数测试。"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from scripts.run_baseline_openai import (
    default_step_limit,
    make_runner_controller,
    resolve_log_dir,
    runner_configuration_data,
    runner_policy_config,
    seed_budget,
    seed_snapshot_matches,
)
from starnet.policy.config import PolicyConfig, PolicyMode


class BaselineRunnerTests(unittest.TestCase):
    def test_runner_keeps_qualified_p8_instead_of_replacing_it(self):
        class Base:
            def __init__(self, *args, **kwargs):
                self.options = kwargs
        class Qualified(Base):
            p8_mode = "conservative"
        config = PolicyConfig(policy_mode=PolicyMode.PUBLIC_GREEDY)
        kept = make_runner_controller(Qualified(), Base, None, None, initial_budget=100.0,
                                      node_count=50, stage="preliminary", config=config)
        self.assertIsInstance(kept, Qualified)
        self.assertEqual(kept.options["p8_mode"], "conservative")
        self.assertTrue(kept.options["require_stage_envelope"])
        fallback = make_runner_controller(Qualified(), Base, None, None, initial_budget=20.0,
                                          node_count=4, stage="preliminary", config=config)
        self.assertIs(type(fallback), Base)
        self.assertNotIn("p8_mode", fallback.options)

    def test_runner_keeps_p11_parameters_but_constructs_fresh_ledger(self):
        class Base:
            def __init__(self, *args, **kwargs):
                self.options = kwargs
        class PromptLearning(Base):
            p8_mode = "conservative"
            p11_experiment_mode = "prompt_learning"
            p11_max_probe_budget = 6.0
            p11_max_probe_nodes = 1
            p11_prompt_ledger = object()
        config = PolicyConfig(policy_mode=PolicyMode.PUBLIC_GREEDY)
        kept = make_runner_controller(
            PromptLearning(), Base, None, None, initial_budget=100.0,
            node_count=50, stage="preliminary", config=config,
        )
        self.assertIsInstance(kept, PromptLearning)
        self.assertEqual(kept.options["p8_mode"], "conservative")
        self.assertEqual(kept.options["max_probe_budget"], 6.0)
        self.assertEqual(kept.options["max_probe_nodes"], 1)
        self.assertNotIn("prompt_ledger", kept.options)

    def test_seed_budget_requires_numeric_max_budget(self) -> None:
        self.assertEqual(seed_budget({"global_setting": {"max_budget": 20}}), 20.0)
        self.assertIsNone(seed_budget({"global_setting": {"max_budget": "20"}}))

    def test_default_step_limit_reaches_beyond_full_competition_scan(self) -> None:
        self.assertEqual(default_step_limit(50, 100.0), 102)
        self.assertEqual(default_step_limit(100, 200.0), 202)

    def test_runner_preserves_submission_policy_and_only_adapts_step_fuse(self) -> None:
        submission = PolicyConfig(
            policy_mode=PolicyMode.PUBLIC_GREEDY,
            p0_exclusive=False,
            max_llm_calls=240,
            enable_public_comm_shield_guard=True,
        )

        adapted = runner_policy_config(submission, 37)

        self.assertEqual(adapted.max_steps, 38)
        self.assertEqual(adapted.policy_mode, PolicyMode.PUBLIC_GREEDY)
        self.assertEqual(adapted.max_llm_calls, 240)
        self.assertFalse(adapted.p0_exclusive)
        self.assertTrue(adapted.enable_public_comm_shield_guard)
        self.assertIsNone(submission.max_steps)

    def test_relative_log_dir_is_resolved_from_runner_invocation_directory(self) -> None:
        invocation_cwd = Path("/tmp/smp-runner-invocation")

        self.assertEqual(
            resolve_log_dir(Path("runs/smoke"), invocation_cwd),
            invocation_cwd / "runs/smoke",
        )
        self.assertEqual(
            resolve_log_dir(Path("/tmp/explicit-smoke"), invocation_cwd),
            Path("/tmp/explicit-smoke"),
        )

    def test_explicit_guard_override_is_local_and_requires_public_policy(self) -> None:
        submission = PolicyConfig(policy_mode=PolicyMode.PUBLIC_GREEDY)
        enabled = runner_policy_config(submission, 100, public_guard=True)
        disabled = runner_policy_config(enabled, 100, public_guard=False)
        self.assertTrue(enabled.enable_public_comm_shield_guard)
        self.assertFalse(disabled.enable_public_comm_shield_guard)
        self.assertFalse(submission.enable_public_comm_shield_guard)
        with self.assertRaises(ValueError):
            runner_policy_config(PolicyConfig(), 100, public_guard=True)

    def test_runner_configuration_hashes_exact_inputs_without_connection_secrets(self) -> None:
        config = PolicyConfig(
            policy_mode=PolicyMode.PUBLIC_GREEDY,
            max_llm_calls=240,
            enable_public_comm_shield_guard=True,
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            seed_path = root / "seed.json"
            submission_dir = root / "submission"
            submission_dir.mkdir()
            seed_path.write_bytes(b'{"seed":1}\n')
            (submission_dir / "config.json").write_bytes(b'{"person":[]}\n')
            (submission_dir / "starnet_model.py").write_bytes(b"class ParticipantSquadModel: pass\n")

            data = runner_configuration_data(
                runtime_config=config,
                seed_path=seed_path,
                submission_dir=submission_dir,
                model_name="test-model",
                stage=SimpleNamespace(value="preliminary"),
                node_count=4,
                initial_budget=20.0,
            )

        self.assertEqual(data["model"], "test-model")
        self.assertEqual(data["stage"], "preliminary")
        self.assertEqual(data["node_count"], 4)
        self.assertEqual(data["policy_config"]["max_llm_calls"], 240)
        self.assertTrue(data["policy_config"]["enable_public_comm_shield_guard"])
        self.assertEqual(len(data["seed_sha256"]), 64)
        self.assertEqual(set(data["submission_sha256"]), {"config.json", "starnet_model.py"})
        self.assertNotIn("api_key", data)
        self.assertNotIn("base_url", data)

    def test_seed_snapshot_requires_all_scanned_nodes_and_edges_to_match(self) -> None:
        seed = {
            "nodes": [
                {"id": 1, "w": -1.0, "persona": "暴力", "comm_left": 3},
                {"id": 2, "w": 2.0, "persona": "和平", "comm_left": 1},
            ],
            "edges": [[1, 2]],
        }
        nodes = {
            1: SimpleNamespace(w=-1.0, persona="暴力", comm_left=3),
            2: SimpleNamespace(w=2.0, persona="和平", comm_left=1),
        }

        self.assertTrue(seed_snapshot_matches(seed, nodes, {(1, 2)}))
        self.assertFalse(seed_snapshot_matches(seed, nodes, set()))
