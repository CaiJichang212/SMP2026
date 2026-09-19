import hashlib
import json
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from starnet.optimization_lab import make_matrix_seed


class MatrixTests(unittest.TestCase):
    def test_resume_cannot_relabel_existing_seed(self):
        seed = ROOT / 'data/optimization_matrix/seed-120.json'
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'results.jsonl'
            output.write_text(json.dumps({'seed': 120, 'policy': 'incumbent', 'status': 'ok',
                                          'seed_sha256': hashlib.sha256(seed.read_bytes()).hexdigest()}) + '\n')
            saved = Path(folder) / 'seed-120.json'
            saved.write_text('original seed must survive')
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/optimization_matrix.py'),
                                     '--seeds', '120', '--nodes', '100', '--output', str(output)],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('seed configuration changed', result.stderr)
            self.assertEqual(saved.read_text(), 'original seed must survive')

    def test_fixtures_reproduce_and_cover_permutations(self):
        permutations = set()
        for index in range(120, 144):
            path = ROOT / 'data/optimization_matrix' / ('seed-%s.json' % index)
            generated = make_matrix_seed(index)
            body = json.dumps(generated, ensure_ascii=False, sort_keys=True).encode()
            self.assertEqual(hashlib.sha256(path.read_bytes()).digest(), hashlib.sha256(body).digest())
            values = generated['prompts']
            permutations.add(tuple(sorted(values, key=lambda k: values[k])))
            self.assertEqual(len(generated['nodes']), 50)
            self.assertEqual(generated['global_setting']['max_api_calls'], 120)
        self.assertEqual(len(permutations), 6)
