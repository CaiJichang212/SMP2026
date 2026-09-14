from __future__ import annotations

import math
import unittest

from starnet.policy.guarded_response_mixture import GuardedResponseMixtureLedger


def aligned_ledger(degrees=None) -> GuardedResponseMixtureLedger:
    ledger = GuardedResponseMixtureLedger()
    ledger.configure_initial_degrees(degrees or {
        1: 1, 2: 2, 3: 3, 4: 4, 5: 1, 6: 2, 7: 3, 8: 4,
    })
    for node_id in range(1, 9):
        persona, response = ("和平", 1.2) if node_id <= 4 else ("暴力", 0.4)
        ledger.observe_node_first(node_id, persona, 0.0, 15.0 * response)
    return ledger


class GuardedResponseMixtureTests(unittest.TestCase):
    def test_full_public_guards_open_and_record_guarded_activation(self) -> None:
        ledger = aligned_ledger()
        self.assertTrue(ledger.gate_open())
        self.assertEqual(ledger.activation["accepted_observation_count"], 8)
        self.assertEqual(ledger.activation["dominant_model"], "aligned")
        self.assertLess(abs(ledger.activation["degree_response_correlation"]), 0.8)
        self.assertIsNone(ledger._mixture.activation)

    def test_gate_requires_frozen_degree_context_and_distinct_nodes(self) -> None:
        ledger = GuardedResponseMixtureLedger()
        before = ledger.weights()
        self.assertFalse(ledger.observe_node_first(1, "和平", 0.0, 18.0))
        self.assertEqual(ledger.weights(), before)
        self.assertFalse(ledger.gate_open())
        self.assertEqual(ledger.censored[-1]["reason"], "missing_initial_degree")

        configured = GuardedResponseMixtureLedger()
        self.assertTrue(configured.configure_initial_degrees({1: 2, 2: 2}))
        self.assertTrue(configured.configure_initial_degrees({1: 2, 2: 2}))
        self.assertFalse(configured.configure_initial_degrees({1: 3, 2: 2}))
        self.assertTrue(configured.observe_node_first(1, "和平", 0.0, 18.0))
        weights = configured.weights()
        self.assertFalse(configured.observe_node_first(1, "和平", 0.0, 18.0))
        self.assertEqual(configured.weights(), weights)
        self.assertEqual(configured.censored[-1]["reason"], "duplicate_node")

    def test_degree_correlation_blocks_an_otherwise_aligned_posterior(self) -> None:
        degrees = {node_id: node_id for node_id in range(1, 9)}
        ledger = GuardedResponseMixtureLedger()
        ledger.configure_initial_degrees(degrees)
        for node_id in range(1, 9):
            persona, response = ("暴力", 0.4) if node_id <= 4 else ("和平", 1.2)
            ledger.observe_node_first(node_id, persona, 0.0, 15.0 * response)
        self.assertGreaterEqual(abs(ledger._degree_correlation()), 0.8)
        self.assertFalse(ledger.gate_open())
        self.assertIsNone(ledger.activation)

    def test_persona_pair_evidence_is_required(self) -> None:
        ledger = GuardedResponseMixtureLedger()
        ledger.configure_initial_degrees({node_id: 2 for node_id in range(1, 9)})
        for node_id in range(1, 9):
            ledger.observe_node_first(node_id, "和平", 0.0, 18.0)
        self.assertGreaterEqual(ledger.weights()["aligned"], 0.99)
        self.assertEqual(ledger._degree_correlation(), 0.0)
        self.assertFalse(ledger.gate_open())

    def test_unknown_and_nonfinite_inputs_fail_closed(self) -> None:
        ledger = GuardedResponseMixtureLedger()
        ledger.configure_initial_degrees({1: 1, 2: 1, 3: 1})
        before = ledger.weights()
        self.assertFalse(ledger.observe_node_first(1, "unknown", 0.0, 10.0))
        self.assertFalse(ledger.observe_node_first(2, "和平", math.nan, 10.0))
        self.assertFalse(ledger.observe_node_first(3, "和平", "bad", 10.0))
        self.assertEqual(ledger.weights(), before)
        self.assertFalse(ledger.gate_open())

    def test_unknown_prediction_uses_observed_value_or_fixed_prior(self) -> None:
        ledger = GuardedResponseMixtureLedger()
        self.assertEqual(ledger.predict(1, "unknown", 1, {}, gated=True), 12.75)
        self.assertEqual(ledger.predict(1, "unknown", 2, {1: 8.0}, gated=True), 4.0)


if __name__ == "__main__":
    unittest.main()
