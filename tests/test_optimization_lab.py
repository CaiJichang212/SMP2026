"""Research estimator invariants; remote accuracy is tested separately."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from starnet.optimization_lab import influence, changed, estimate, TopologyBook


class TopologyTests(unittest.TestCase):
    def test_components_and_isolates_keep_mass(self):
        nodes = {1: {'w': 10, 'neighbors': [2]}, 2: {'w': 10, 'neighbors': [1]},
                 3: {'w': -7, 'neighbors': []}}
        self.assertEqual(influence(nodes), {1: 1, 2: 1, 3: 1})
        self.assertEqual(estimate(nodes), 13)

    def test_removal_recomputes_neighbors_and_components(self):
        nodes = {1: {'w': -50, 'neighbors': [2, 3]},
                 2: {'w': 20, 'neighbors': [1]}, 3: {'w': 30, 'neighbors': [1]}}
        out = changed(nodes, {'action': 'shield', 'node': 1})
        self.assertEqual(estimate(out), 50)
        self.assertEqual(nodes[2]['neighbors'], [1])

    def test_cut_changes_both_ends_only_after_confirmation(self):
        book = TopologyBook(2)
        for n in (1, 2):
            book.record_scan(n, {'w': 0, 'neighbors': [3-n], 'comm_left': 3})
        action = {'action': 'cut', 'node': 1, 'other': 2}
        self.assertTrue(book.valid(action, 3))
        self.assertFalse(book.valid(action, 2.99))
        with self.assertRaises(ValueError):
            book.record_cut(1, 2, False)
        self.assertTrue(book.valid(action, 3))
        book.record_cut(1, 2, True)
        self.assertFalse(book.valid(action, 3))

    def test_estimator_constant_signal_and_empty(self):
        nodes = {n: {'w': 17, 'neighbors': [v for v in range(4) if v != n and (v == 0 or n == 0)]} for n in range(4)}
        self.assertAlmostEqual(estimate(nodes), 68)
        self.assertEqual(estimate({}), 0)
