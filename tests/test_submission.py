import ast
import hashlib
import importlib.util
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from test_model import Env, LLM, fake

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from build_submission import build

class SubmissionTests(unittest.TestCase):
    def test_archive_is_reproducible_and_runs_outside_repo(self):
        with tempfile.TemporaryDirectory() as d:
            a=Path(d)/'a.zip';b=Path(d)/'b.zip'
            with patch('builtins.print'):
                build(a);build(b)
            self.assertEqual(hashlib.sha256(a.read_bytes()).digest(),hashlib.sha256(b.read_bytes()).digest())
            with zipfile.ZipFile(a) as z:
                self.assertEqual(set(z.namelist()),{'config.json','prompt/commander.txt','prompt/reflect.txt','starnet_model.py'})
                ast.parse(z.read('starnet_model.py').decode(),feature_version=(3,9))
                z.extractall(Path(d)/'extracted')
            spec=importlib.util.spec_from_file_location('test_zip_submission',Path(d)/'extracted/starnet_model.py')
            module=importlib.util.module_from_spec(spec)
            with patch.dict(sys.modules,{'agent_mesa':fake}):spec.loader.exec_module(module)
            model=module.ParticipantSquadModel(Env(),[{'node_count':1}],LLM())
            while not model.step():pass
            self.assertEqual(model.stop_reason,'no_safe_candidate')
            self.assertEqual(model.llm_calls,4)
