from __future__ import annotations

import json
import re
import unittest
from unittest.mock import patch

from tests.integration.test_controller import FakeStarNetEnvironment
from starnet.policy import p11_qualification
from starnet.policy.config import PolicyMode
from starnet.runtime.p8_controller import P8RuntimeController
from starnet.runtime.p11_prompt_controller_experiment import PromptLearningRuntimeController
import starnet.submission.starnet_model as entry


class StubLLM:
    class Embedding:
        def __call__(self, input):
            return [[0.0] for _ in input]

        def name(self):
            return "test"

    def get_lang_embedding(self):
        return self.Embedding()

    def send_message(self, prompt, json_flag=False):
        ids = re.search(r"候选 ID：(\[[^\n]+\])", prompt)
        candidate_ids = json.loads(ids.group(1).replace("'", '"')) if ids else []
        return json.dumps({"state_version": 0, "mode": "single_action",
                           "candidate_id": candidate_ids[0] if candidate_ids else "none",
                           "reason_code": "test", "evidence_ids": candidate_ids[:1]})


class P11CanonicalActivationTests(unittest.TestCase):
    def test_disabled_qualification_keeps_canonical_p9(self):
        env = FakeStarNetEnvironment(50, 100.0)
        model = entry.ParticipantSquadModel(env, [{
            "role": "CommanderAgent", "experimental_policy_mode": "public_greedy",
            "experimental_p8_mode": "conservative",
            "experimental_p11_mode": "prompt_learning",
        }], StubLLM())
        self.assertIsInstance(model.controller, P8RuntimeController)
        self.assertNotIsInstance(model.controller, PromptLearningRuntimeController)

    def test_sealed_p11_activates_with_trimmed_standard_description(self):
        env = FakeStarNetEnvironment(50, 100.0)
        with patch.object(entry, "P11_CERTIFIED_MODE", "prompt_learning"), \
             patch.object(p11_qualification, "P11_CERTIFIED_MODE", "prompt_learning"), \
             patch.object(p11_qualification, "P11_GATE_REPORT_SHA256", "a" * 64), \
             patch.object(p11_qualification, "P11_GATE_REPORT_RELATIVE_PATH",
                          "experiments/reports/p11-release.json"):
            model = entry.ParticipantSquadModel(
                env, [{"role": "CommanderAgent"}], StubLLM(),
            )
        self.assertIsInstance(model.controller, PromptLearningRuntimeController)
        self.assertEqual(model.controller.p8_mode, "conservative")
        self.assertIs(model.controller.config.policy_mode, PolicyMode.PUBLIC_GREEDY)

    def test_explicit_unknown_p11_flag_fails_closed_to_p9(self):
        env = FakeStarNetEnvironment(50, 100.0)
        description = {
            "role": "CommanderAgent", "experimental_policy_mode": "public_greedy",
            "experimental_p8_mode": "conservative", "experimental_p11_mode": "unknown",
        }
        with patch.object(entry, "P11_CERTIFIED_MODE", "prompt_learning"), \
             patch.object(p11_qualification, "P11_CERTIFIED_MODE", "prompt_learning"), \
             patch.object(p11_qualification, "P11_GATE_REPORT_SHA256", "a" * 64), \
             patch.object(p11_qualification, "P11_GATE_REPORT_RELATIVE_PATH",
                          "experiments/reports/p11-release.json"):
            model = entry.ParticipantSquadModel(env, [description], StubLLM())
        self.assertIsInstance(model.controller, P8RuntimeController)
        self.assertNotIsInstance(model.controller, PromptLearningRuntimeController)


if __name__ == "__main__":
    unittest.main()
