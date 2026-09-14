from __future__ import annotations

import itertools
import unittest

from starnet.model.blackboard import Blackboard
from starnet.policy.prompt_calibration_experiment import (
    PromptCalibrationLedger, select_prompt_probe_nodes,
)


class PromptCalibrationTests(unittest.TestCase):
    def test_all_base_prompt_permutations_identify_unique_best_on_two_nodes(self):
        for strengths in itertools.permutations((15.0, 10.0, -5.0)):
            ledger = PromptCalibrationLedger()
            for node_id, response_factor in ((3, 0.4), (7, 1.3)):
                opinion = 0.0
                for turn, (prompt_id, strength) in enumerate(zip((1, 2, 3), strengths), 1):
                    new_w = opinion + strength * response_factor * (0.5 ** (turn - 1))
                    self.assertTrue(ledger.observe_success(
                        node_id, prompt_id, turn, opinion, new_w,
                    ))
                    opinion = new_w
            self.assertTrue(ledger.confident)
            self.assertEqual(ledger.calibrated_prompt_id,
                             max((1, 2, 3), key=lambda prompt_id: strengths[prompt_id - 1]))

    def test_zero_and_negative_values_are_valid_but_ties_fall_back(self):
        ledger = PromptCalibrationLedger(required_complete_nodes=1)
        opinion = 5.0
        for turn, strength in enumerate((-4.0, 0.0, -2.0), 1):
            new_w = opinion + strength * (0.5 ** (turn - 1))
            self.assertTrue(ledger.observe_success(1, turn, turn, opinion, new_w))
            opinion = new_w
        self.assertEqual(ledger.calibrated_prompt_id, 2)

        tied = PromptCalibrationLedger(required_complete_nodes=1)
        opinion = 0.0
        for turn in (1, 2, 3):
            new_w = opinion + 5.0 * (0.5 ** (turn - 1))
            tied.observe_success(1, turn, turn, opinion, new_w)
            opinion = new_w
        self.assertIsNone(tied.calibrated_prompt_id)
        self.assertEqual(tied.best_or_default(), 1)

    def test_tied_best_prompts_do_not_fall_back_to_known_harmful_default(self):
        ledger = PromptCalibrationLedger()
        for node_id, factor in ((1, 0.5), (2, 1.2)):
            opinion = 0.0
            for turn, strength in enumerate((-5.0, 15.0, 15.0), 1):
                new_w = opinion + strength * factor * (0.5 ** (turn - 1))
                ledger.observe_success(node_id, turn, turn, opinion, new_w)
                opinion = new_w
        self.assertTrue(ledger.confident)
        self.assertEqual(ledger.calibrated_prompt_ids, (2, 3))
        self.assertEqual(ledger.best_or_default(), 2)

    def test_zero_response_node_does_not_erase_one_informative_ranking(self):
        ledger = PromptCalibrationLedger()
        for node_id, factor in ((1, 0.0), (2, 1.0)):
            opinion = 0.0
            for turn, strength in enumerate((-5.0, 15.0, 10.0), 1):
                new_w = opinion + strength * factor * (0.5 ** (turn - 1))
                ledger.observe_success(node_id, turn, turn, opinion, new_w)
                opinion = new_w
        self.assertTrue(ledger.calibration_complete)
        self.assertFalse(ledger.confident)
        self.assertIsNone(ledger.calibrated_prompt_id)
        self.assertEqual(ledger.provisional_prompt_ids, (2,))
        self.assertEqual(ledger.informative_node_ids, (2,))
        self.assertEqual(ledger.best_or_default(), 2)

    def test_clipped_or_conflicting_nodes_do_not_claim_confidence(self):
        clipped = PromptCalibrationLedger(required_complete_nodes=1)
        self.assertFalse(clipped.observe_success(1, 1, 1, 99.0, 100.0))
        clipped.observe_success(1, 2, 2, 100.0, 99.0)
        clipped.observe_success(1, 3, 3, 99.0, 98.0)
        self.assertIsNone(clipped.calibrated_prompt_id)

        conflict = PromptCalibrationLedger()
        for node_id, values in ((1, (9.0, 5.0, 1.0)), (2, (1.0, 9.0, 5.0))):
            opinion = 0.0
            for turn, value in enumerate(values, 1):
                new_w = opinion + value * (0.5 ** (turn - 1))
                conflict.observe_success(node_id, turn, turn, opinion, new_w)
                opinion = new_w
        self.assertTrue(conflict.calibration_complete)
        self.assertFalse(conflict.confident)

    def test_failed_action_does_not_advance_prompt_sequence(self):
        ledger = PromptCalibrationLedger(required_complete_nodes=1)
        self.assertEqual(ledger.next_prompt(1), 1)
        self.assertFalse(ledger.observe_failure(1, 1, 1))
        self.assertEqual(ledger.next_prompt(1), 1)
        self.assertTrue(ledger.observe_success(1, 1, 1, 0.0, 5.0))
        self.assertEqual(ledger.next_prompt(1), 2)

    def test_probe_nodes_are_bounded_by_budget_and_public_low_degree_risk(self):
        board = Blackboard(node_count=5)
        data = {
            1: (10.0, "和平", [2]),
            2: (1.0, "中立", [1, 3]),
            3: (-20.0, "暴力", [2]),
            4: (70.0, "和平", []),
            5: (3.0, "和平", []),
        }
        for node_id, (weight, persona, neighbors) in data.items():
            board.record_scan(node_id, {"w": weight, "persona": persona,
                                        "comm_left": 3, "neighbors": neighbors})
        self.assertEqual(select_prompt_probe_nodes(board), (5, 1))
        self.assertEqual(select_prompt_probe_nodes(board, max_probe_budget=6.0), (5,))
        self.assertEqual(select_prompt_probe_nodes(board, max_probe_budget=5.9), ())


if __name__ == "__main__":
    unittest.main()
