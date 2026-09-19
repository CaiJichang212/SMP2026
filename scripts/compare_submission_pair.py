"""Serial old/new real-LLM ZIP runs; each episode has its own resource limit."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--baseline', required=True, type=Path)
    ap.add_argument('--candidate', required=True, type=Path)
    ap.add_argument('--seed-dir', required=True, type=Path)
    ap.add_argument('--seeds', default='120,124,134')
    ap.add_argument('--output', required=True, type=Path)
    ap.add_argument('--python', default='/home/ubuntu/SMP2026casevo/SMP2026/.venv/bin/python')
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, ANONYMIZED_TELEMETRY='False', UV_CACHE_DIR='/tmp/smp20260918-uv-cache')
    for offset, seed in enumerate(args.seeds.split(',')):
        order = [('baseline', args.baseline), ('candidate', args.candidate)]
        if offset % 2:
            order.reverse()
        for name, archive in order:
            result = args.output / ('%s-%s.json' % (seed, name))
            if result.exists():
                existing = json.loads(result.read_text())
                seed_file = args.seed_dir / ('seed-%s.json' % seed)
                if (existing['zip_sha256'] != hashlib.sha256(archive.read_bytes()).hexdigest()
                        or existing['seed_sha256'] != hashlib.sha256(seed_file.read_bytes()).hexdigest()):
                    raise RuntimeError('artifact changed; use a fresh output directory')
                if existing['stop_reason'] in ('budget', 'no_safe_candidate', 'llm_stop'):
                    print('Existing complete result: ' + str(result), flush=True)
                    continue
                raise RuntimeError('incomplete run requires a fresh output directory')
            command = ['bash', 'scripts/run_limited.sh', 'uv', 'run', '--no-project',
                       '--python', args.python, 'python', 'scripts/run_submission.py',
                       '--zip', str(archive), '--seed', str(args.seed_dir / ('seed-%s.json' % seed)),
                       '--output', str(result)]
            print('Starting %s seed%s' % (name, seed), flush=True)
            with (args.output / ('%s-%s-process.log' % (seed, name))).open('w') as log:
                completed = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=620)
            if completed.returncode:
                print('Run failed; inspect local process log. Exit=%s' % completed.returncode, flush=True)
                return 2
            row = json.loads(result.read_text())
            print(json.dumps({k: row[k] for k in ['seed', 'score', 'natural_score', 'steps', 'llm_calls', 'remaining_budget', 'seconds', 'stop_reason']}), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
