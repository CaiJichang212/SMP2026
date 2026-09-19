"""Public sandbox basis measurements; evaluator access stays in this harness."""
import argparse
import json
import resource
import sys
import time
from pathlib import Path

import networkx as nx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from starnet.local import RemoteEnv


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    graphs = {'path5': nx.path_graph(5), 'star6': nx.star_graph(5),
              'cycle6': nx.cycle_graph(6), 'clique5': nx.complete_graph(5),
              'barbell': nx.barbell_graph(3, 1),
              'ba9': nx.barabasi_albert_graph(9, 2, seed=791)}
    with output.open('a') as stream:
        for name, graph in graphs.items():
            for target in graph:
                seed = {'global_setting': {'max_budget': 100, 'max_api_calls': 120},
                        'original_total': 10,
                        'nodes': [{'id': n + 1, 'w': 10 if n == target else 0,
                                   'persona': '中立', 'r': 1, 'comm_left': 3} for n in graph],
                        'edges': [[u + 1, v + 1] for u, v in graph.edges],
                        'prompts': {'1': 15, '2': 10, '3': -5}}
                start = time.monotonic()
                env = RemoteEnv(seed)
                score = env.trigger_eval()
                row = {'graph': name, 'target': target, 'score': score,
                       'coefficient': score / 10, 'degrees': dict(graph.degree()),
                       'edges': list(graph.edges), 'seconds': time.monotonic() - start,
                       'http_calls': env.calls, 'steps': 0, 'llm_calls': 0,
                       'budget': 100, 'rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                       'evidence': 'official-sandbox-custom-seed'}
                stream.write(json.dumps(row) + '\n')
                stream.flush()
                print(json.dumps(row), flush=True)


if __name__ == '__main__':
    main()
