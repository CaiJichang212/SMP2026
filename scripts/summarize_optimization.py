"""Summarize complete paired runs and empirical proxy errors, without secrets."""
import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from starnet.optimization_lab import ProxyEnv, TopologyBook, estimate


def summarize(path):
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    good = {(r['seed'], r['policy']): r for r in rows if r.get('status') == 'ok'}
    policies = sorted({r['policy'] for r in good.values()})
    seeds = sorted({r['seed'] for r in good.values()})
    paired = [s for s in seeds if all((s, p) in good for p in policies)]
    summary = {'complete_paired_seeds': paired, 'failed_attempts': sum(r.get('status') != 'ok' for r in rows), 'policies': {}}
    for p in policies:
        data = [good[s, p] for s in paired]
        deltas = [r['score'] - good[r['seed'], 'incumbent']['score'] for r in data] if 'incumbent' in policies else []
        summary['policies'][p] = {'mean': statistics.mean(r['score'] for r in data) if data else None,
                                  'wins_vs_incumbent': sum(d > .01 for d in deltas),
                                  'losses_vs_incumbent': sum(d < -.01 for d in deltas),
                                  'mean_delta': statistics.mean(deltas) if deltas else None,
                                  'worst_delta': min(deltas) if deltas else None,
                                  'max_steps': max((r['steps'] for r in data), default=0),
                                  'llm_calls': sum(r['llm_calls'] for r in data)}
    errors = []
    for r in good.values():
        if r['evidence'] != 'official-sandbox-custom-seed':
            continue
        trace_path = path.parent / ('%s-%s-trace.json' % (r['seed'], r['policy']))
        if r['policy'] == 'natural':
            seed = json.loads((path.parent / ('seed-%s.json' % r['seed'])).read_text())
            nodes = ProxyEnv(seed).nodes
        else:
            book = TopologyBook(r['nodes'])
            for event in json.loads(trace_path.read_text())['http']:
                if 'error_type' in event:
                    continue
                endpoint, args, result = event['endpoint'], event['arguments'], event['result']
                if endpoint == 'scan':
                    book.record_scan(args['node_id'], result['data'])
                elif endpoint == 'communicate':
                    book.record_comm({'node': args['node_id'], 'prompt_id': args['prompt_id']}, result)
                elif endpoint == 'shield':
                    book.record_shield(args['node_id'], result['success'])
                elif endpoint == 'cut':
                    book.record_cut(args['u'], args['v'], result['success'])
            nodes = book.nodes
        prediction = estimate(nodes)
        errors.append({'seed': r['seed'], 'policy': r['policy'], 'prediction': prediction,
                       'actual': r['score'], 'error': prediction - r['score'],
                       'relative_error_floor50': abs(prediction - r['score']) / max(50, abs(r['score']))})
    summary['proxy_errors'] = errors
    if errors:
        summary['proxy_mae'] = statistics.mean(abs(r['error']) for r in errors)
        summary['proxy_max_error'] = max(abs(r['error']) for r in errors)
        summary['proxy_relative_mae_floor50'] = statistics.mean(r['relative_error_floor50'] for r in errors)
    return summary


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('input', type=Path)
    ap.add_argument('--output', type=Path)
    args = ap.parse_args()
    result = summarize(args.input)
    body = json.dumps(result, indent=2)
    if args.output:
        args.output.write_text(body + '\n')
    print(body)
