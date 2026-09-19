"""Audit real-LLM paired results, without treating failed runs as scores."""
import argparse
import datetime
import json
from pathlib import Path
import statistics


def audited_row(path):
    row = json.loads(path.read_text())
    audit = json.loads(path.with_name(path.stem + '-audit.json').read_text())
    pending, executed, cost = [], 0, 0
    actions = {}
    for event in audit:
        if 'approved' in event:
            pending = list(event['approved'])
        if 'executed' in event:
            action = event['executed']
            if not pending or pending.pop(0) != action:
                raise ValueError('unapproved action in ' + str(path))
            executed += 1
            cost += action['cost']
            actions[action['action']] = actions.get(action['action'], 0) + 1
    if abs(row['initial_budget'] - cost - row['remaining_budget']) > 1e-6:
        raise ValueError('budget does not match confirmed actions')
    limit = 250 if row['initial_budget'] >= 200 else 120
    if row['llm_calls'] > limit or row['steps'] > limit:
        raise ValueError('resource counter exceeded')
    return dict(row, authorized_actions=executed, action_counts=actions)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('directory', type=Path)
    ap.add_argument('--output', type=Path)
    args = ap.parse_args()
    pairs = []
    for baseline_path in sorted(args.directory.glob('*-baseline.json')):
        seed = baseline_path.name.split('-')[0]
        candidate_path = args.directory / (seed + '-candidate.json')
        if not candidate_path.exists():
            continue
        baseline, candidate = audited_row(baseline_path), audited_row(candidate_path)
        valid = ('budget', 'no_safe_candidate', 'llm_stop')
        if baseline['stop_reason'] not in valid or candidate['stop_reason'] not in valid:
            continue
        if baseline['seed_sha256'] != candidate['seed_sha256'] or baseline['llm_model'] != candidate['llm_model']:
            raise ValueError('noncomparable pair')
        pairs.append({'seed': seed, 'baseline': baseline, 'candidate': candidate,
                      'delta': candidate['score'] - baseline['score']})
    summary = {'recorded_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
               'evidence': 'official-sandbox-custom-seed-real-local-llm',
               'pairs': pairs, 'complete_pairs': len(pairs)}
    if pairs:
        summary.update(baseline_mean=statistics.mean(p['baseline']['score'] for p in pairs),
                       candidate_mean=statistics.mean(p['candidate']['score'] for p in pairs),
                       paired_mean_delta=statistics.mean(p['delta'] for p in pairs),
                       natural_mean=statistics.mean(p['baseline']['natural_score'] for p in pairs),
                       wins=sum(p['delta'] > .01 for p in pairs), losses=sum(p['delta'] < -.01 for p in pairs))
    body = json.dumps(summary, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(body + '\n')
    print(json.dumps({k: v for k, v in summary.items() if k != 'pairs'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
