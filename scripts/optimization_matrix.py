"""Serializable, resumable paired matrix; no-LLM controls, not submissions."""
import argparse
import hashlib
import json
import resource
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from starnet.local import RemoteEnv
from starnet.policy import ObservationBook
from starnet.optimization_lab import ProxyEnv, TopologyBook, make_matrix_seed, run_book
from starnet.topology import TopologyBook as ProductionBook


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', required=True)
    ap.add_argument('--seeds', default='120,121,122,123,124,125')
    ap.add_argument('--policies', default='natural,incumbent,greedy,completion')
    ap.add_argument('--remote', action='store_true')
    ap.add_argument('--nodes', type=int, default=50)
    ap.add_argument('--prompt-profile', choices=['standard', 'negative', 'zero'], default='standard')
    args = ap.parse_args()
    policies = args.policies.split(',')
    if set(policies) - {'natural', 'incumbent', 'greedy', 'completion', 'shield_only', 'low_probe', 'robust', 'production'}:
        ap.error('unknown policy label')
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    previous = [json.loads(line) for line in out.read_text().splitlines()] if out.exists() else []
    done = {(r['seed'], r['policy']) for r in previous if r.get('status') == 'ok'}
    with out.open('a') as stream:
        for index in map(int, args.seeds.split(',')):
            seed = make_matrix_seed(index, args.nodes)
            if args.prompt_profile != 'standard':
                seed['prompts'] = {'1': -5, '2': -10, '3': -15} if args.prompt_profile == 'negative' else {'1': 0, '2': 0, '3': 0}
            raw = json.dumps(seed, ensure_ascii=False, sort_keys=True).encode()
            digest = hashlib.sha256(raw).hexdigest()
            if any(r['seed'] == index and r['seed_sha256'] != digest for r in previous):
                raise ValueError('seed configuration changed; use a fresh output directory')
            (out.parent / ('seed-%s.json' % index)).write_bytes(raw)
            for policy in policies:
                if (index, policy) in done:
                    continue
                started = time.monotonic()
                row = {'seed': index, 'policy': policy, 'seed_sha256': hashlib.sha256(raw).hexdigest(),
                       'nodes': args.nodes, 'initial_budget': seed['global_setting']['max_budget'],
                       'llm_calls': 0, 'evidence': 'official-sandbox-custom-seed' if args.remote else 'proxy-simulation'}
                try:
                    env = RemoteEnv(seed) if args.remote else ProxyEnv(seed)
                    cls = ObservationBook if policy == 'incumbent' else ProductionBook if policy == 'production' else TopologyBook
                    book = cls(args.nodes)
                    book.use_completion = policy != 'greedy'
                    book.use_cuts = policy != 'shield_only'
                    book.calibration_low_degree = policy == 'low_probe'
                    book.robust_completion = policy == 'robust'
                    steps, actions = (0, []) if policy == 'natural' else run_book(env, book)
                    budget = env.get_remaining_budget()
                    score = env.trigger_eval()
                    row.update(status='ok', score=score, budget=budget, steps=steps, http_calls=env.calls,
                               action_counts={name: sum(a['action'] == name for a in actions) for name in ('scan', 'comm', 'shield', 'cut')})
                    (out.parent / ('%s-%s-trace.json' % (index, policy))).write_text(json.dumps({'actions': actions, 'http': env.trace}, ensure_ascii=False))
                except Exception as exc:
                    row.update(status='failed', error_type=type(exc).__name__)
                row.update(seconds=time.monotonic() - started, rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
                stream.write(json.dumps(row) + '\n')
                stream.flush()
                print(json.dumps(row), flush=True)
                if row['status'] != 'ok':
                    return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
