import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from starnet.local import RemoteEnv


def response(value):
    item = Mock()
    item.json.return_value = value
    return item


class TransportTests(unittest.TestCase):
    def test_budget_read_retries_once(self):
        with patch('starnet.local.requests.Session') as session:
            client = session.return_value
            client.post.side_effect = [response({'session_id': 'test'}),
                                       requests.ReadTimeout('sensitive details'), response({'budget': 50})]
            env = RemoteEnv({})
            self.assertEqual(env.get_remaining_budget(), 50)
            self.assertEqual(client.post.call_count, 3)
            self.assertEqual(env.trace[1], {'endpoint': 'get_budget', 'error_type': 'ReadTimeout', 'retry': True})
            self.assertNotIn('sensitive details', str(env.trace))

    def test_mutations_never_retry(self):
        for endpoint in ['scan', 'communicate', 'cut', 'shield', 'evaluate']:
            with patch('starnet.local.requests.Session') as session:
                client = session.return_value
                client.post.side_effect = [response({'session_id': 'test'}), requests.ReadTimeout()]
                env = RemoteEnv({})
                with self.assertRaises(requests.ReadTimeout):
                    env.request(endpoint)
                self.assertEqual(client.post.call_count, 2)
                self.assertFalse(env.trace[-1]['retry'])

    def test_read_retry_is_bounded(self):
        with patch('starnet.local.requests.Session') as session:
            client = session.return_value
            client.post.side_effect = [response({'session_id': 'test'}), requests.ReadTimeout(), requests.ReadTimeout()]
            env = RemoteEnv({})
            with self.assertRaises(requests.ReadTimeout):
                env.get_remaining_budget()
            self.assertEqual(client.post.call_count, 3)
