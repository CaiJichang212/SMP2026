import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from starnet.topology import TopologyBook, estimate, influence
from starnet.policy import validate_plan
from starnet.optimization_lab import TopologyBook as Prototype, ProxyEnv, make_matrix_seed


class TopologyPolicyTests(unittest.TestCase):
    def calibrated(self):
        book = TopologyBook(4)
        for n in range(1, 5):
            book.record_scan(n, {'w': -60 if n == 1 else 10, 'persona': '和平',
                                 'comm_left': 3 if n == 2 else 0, 'neighbors': []})
        for p in (1, 2, 3):
            book.record_comm({'node': 2, 'prompt_id': p}, {'status': 'success', 'new_w': 10})
        return book

    def test_negative_isolate_can_be_shielded(self):
        book = self.calibrated()
        _, choices, limit = book.candidates(10)
        self.assertEqual(choices[0]['action'], 'shield')
        self.assertEqual(choices[0]['node'], 1)
        self.assertEqual(choices[0]['gain_proxy'], 60)
        self.assertEqual(limit, 1)
        self.assertTrue(book.valid(choices[0], 5))

    def test_cut_validation_and_plan_isolation(self):
        book = self.calibrated()
        book.nodes[1]['neighbors'] = [2]
        book.nodes[2]['neighbors'] = [1]
        cut = {'action': 'cut', 'node': 1, 'other': 2, 'cost': 3}
        self.assertTrue(book.valid(cut, 3))
        for invalid in [dict(cut, other=True), dict(cut, other=3), dict(cut, node=True)]:
            self.assertFalse(book.valid(invalid, 3))
        self.assertFalse(book.valid(cut, float('nan')))
        self.assertFalse(book.valid([], 3))
        other = {'action': 'shield', 'node': 3, 'cost': 5}
        with self.assertRaises(ValueError):
            validate_plan({'choices': [0, 1], 'reason': 'stale'}, [cut, other], 4, book, 10)
        with self.assertRaises(ValueError):
            book.record_cut(1, 2, False)
        book.record_cut(1, 2, True)
        self.assertEqual(book.nodes[1]['neighbors'], [])
        self.assertFalse(book.valid(cut, 10))

    def test_constant_signal_mass_and_components(self):
        nodes = {1: {'w': 17, 'neighbors': [2]}, 2: {'w': 17, 'neighbors': [1]},
                 3: {'w': 17, 'neighbors': []}}
        self.assertEqual(estimate(nodes), 51)
        self.assertEqual(sum(influence(nodes).values()), 3)

    def test_selected_candidate_order_matches_measured_prototype(self):
        for seed_index in (120, 124, 135):
            env = ProxyEnv(make_matrix_seed(seed_index, n=10))
            reference = Prototype(10)
            for n in range(1, 11):
                reference.record_scan(n, env.scan_node(n))
            for _ in range(3):
                _, candidates, _ = reference.candidates(env.get_remaining_budget())
                action = candidates[0]
                reference.record_comm(action, env.communicate(action['node'], action['prompt_id']))
            book = TopologyBook(10)
            book.__dict__.update(copy.deepcopy(reference.__dict__))
            _, expected, _ = reference.candidates(30)
            _, actual, _ = book.candidates(30)
            keys = ('action', 'node', 'other', 'prompt_id', 'gain_proxy', 'completion_advantage', 'robust_advantage')
            self.assertEqual([{k: a.get(k) for k in keys} for a in expected],
                             [{k: a.get(k) for k in keys} for a in actual])

    def test_communication_candidates_have_distinct_targets(self):
        book = self.calibrated()
        book.nodes[3]['comm_left'] = 3
        book.nodes[4]['comm_left'] = 3
        book.samples[0]['normalized_gain'] = 15
        _, candidates, _ = book.candidates(30)
        nodes = [a['node'] for a in candidates if a['action'] == 'comm']
        self.assertEqual(len(nodes), len(set(nodes)))
