"""Research-only topology proxy and paired fixtures; excluded from submission."""
import copy
import itertools
import random

import networkx as nx

from .policy import ObservationBook


def influence(nodes):
    remaining = set(nodes)
    result = {}
    while remaining:
        root = min(remaining)
        component, stack = {root}, [root]
        remaining.remove(root)
        while stack:
            for neighbor in nodes[stack.pop()]['neighbors']:
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    component.add(neighbor)
                    stack.append(neighbor)
        degrees = {n: 1 + sum(v in nodes for v in nodes[n]['neighbors']) for n in component}
        total = sum(degrees.values())
        result.update({n: len(component) * d / total for n, d in degrees.items()})
    return result


def estimate(nodes):
    return sum(nodes[n]['w'] * weight for n, weight in influence(nodes).items())


def changed(nodes, action):
    out = {n: dict(x, neighbors=list(x['neighbors'])) for n, x in nodes.items()}
    node = action['node']
    if action['action'] == 'shield':
        del out[node]
        for x in out.values():
            x['neighbors'] = [n for n in x['neighbors'] if n != node]
    elif action['action'] == 'cut':
        other = action['other']
        out[node]['neighbors'].remove(other)
        out[other]['neighbors'].remove(node)
    return out


class TopologyBook(ObservationBook):
    """Lab prototype: compare structural actions including remaining comm budget."""
    use_cuts = True
    use_completion = True
    calibration_low_degree = False
    robust_completion = False

    def valid(self, action, budget):
        if action.get('action') == 'cut':
            n, v = action.get('node'), action.get('other')
            return (type(n) is int and type(v) is int and budget >= 3
                    and n in self.nodes and v in self.nodes
                    and v in self.nodes[n]['neighbors'])
        if action.get('action') == 'shield':
            return type(action.get('node')) is int and budget >= 5 and action['node'] in self.nodes
        return super().valid(action, budget)

    def record_cut(self, node, other, success):
        if success is not True:
            raise ValueError('cut not confirmed')
        self.nodes[node]['neighbors'].remove(other)
        self.nodes[other]['neighbors'].remove(node)
        self.last_feedback = {'action': 'cut', 'node': node, 'other': other, 'success': True}

    def communication_options(self, nodes, budget):
        weights = influence(nodes)
        measured = sorted({s['prompt_id'] for s in self.samples})
        options = []
        for n, x in nodes.items():
            gains = [(self._gain(n, p)[0], p) for p in measured]
            gains = [(g, p) for g, p in gains if g is not None and g > 0]
            if not gains or x['comm_left'] <= 0:
                continue
            gain, pid = max(gains)
            for offset in range(x['comm_left']):
                delta = gain * .5 ** (3 - x['comm_left'] + offset)
                options.append({'action': 'comm', 'node': n, 'prompt_id': pid, 'cost': 2,
                                'expected_delta_proxy': delta, 'gain_proxy': delta * weights[n],
                                'utility_proxy': delta * weights[n] / 2, 'offset': offset})
        options.sort(key=lambda a: (-a['gain_proxy'], a['node'], a['offset']))
        return options

    def completion(self, nodes, budget):
        options = self.communication_options(nodes, budget)
        return estimate(nodes) + sum(a['gain_proxy'] for a in options[:int(budget // 2)])

    def candidates(self, budget):
        phase, base, limit = super().candidates(budget)
        if phase == 'calibrate' and self.calibration_target is None and self.calibration_low_degree:
            eligible = [n for n, x in self.nodes.items() if x['comm_left'] == 3]
            eligible.sort(key=lambda n: (self.nodes[n]['persona'] != '和平', len(self.nodes[n]['neighbors']), n))
            if eligible:
                base = [{'action': 'comm', 'node': n, 'prompt_id': p, 'cost': 2, 'effect': 'unknown'}
                        for n in eligible[:4] for p in (1, 2, 3)]
        if phase != 'intervene':
            return phase, base, limit
        options = self.communication_options(self.nodes, budget)
        comm = [a for a in options if a['offset'] == 0][:12] if budget >= 2 else []
        current = estimate(self.nodes)
        baseline = self.completion(self.nodes, budget)
        structures = []
        actions = [{'action': 'shield', 'node': n, 'cost': 5} for n in sorted(self.nodes)] if budget >= 5 else []
        if self.use_cuts and budget >= 3:
            actions += [{'action': 'cut', 'node': n, 'other': v, 'cost': 3}
                        for n in sorted(self.nodes) for v in self.nodes[n]['neighbors'] if n < v and v in self.nodes]
        for action in actions:
            after = changed(self.nodes, action)
            gain = estimate(after) - current
            future = self.completion(after, budget - action['cost']) - baseline
            robust = future - .5 * abs(future - gain)
            selection = robust if self.robust_completion else future
            if (selection if self.use_completion else gain) <= .01:
                continue
            structures.append(dict(action, gain_proxy=gain,
                                   utility_proxy=gain / action['cost'],
                                   completion_advantage=future,
                                   robust_advantage=robust,
                                   confidence='custom-sandbox-calibrated-proxy-not-official-formula'))
        structures.sort(key=lambda a: (-(a['robust_advantage'] if self.robust_completion else a['completion_advantage'] if self.use_completion else a['utility_proxy']), a['node']))
        for a in comm:
            a['completion_advantage'] = 0
        if self.use_completion:
            return phase, structures[:6] + comm, 1
        return phase, sorted(comm + structures[:6], key=lambda a: -a['utility_proxy']), 1


def make_matrix_seed(index, n=50):
    rng = random.Random(index)
    family = index % 6
    if family == 0:
        graph = nx.barabasi_albert_graph(n, 2, seed=index)
    elif family == 1:
        graph = nx.watts_strogatz_graph(n, 4, .15, seed=index)
    elif family == 2:
        graph = nx.gnp_random_graph(n, .12, seed=index)
    elif family == 3:
        graph = nx.stochastic_block_model([n // 2, n - n // 2], [[.2, .01], [.01, .2]], seed=index)
    elif family == 4:
        graph = nx.star_graph(n - 1)
        graph.add_edges_from((i, i + 1) for i in range(1, n - 1))
    else:
        graph = nx.disjoint_union(nx.path_graph(n // 2), nx.watts_strogatz_graph(n - n // 2, 4, .1, seed=index))
    nodes = []
    regime = (index // 6) % 4
    for i in range(n):
        persona = rng.choice(['和平', '中立', '暴力'])
        if regime == 0:
            w = rng.uniform(-35, 25)
        elif regime == 1:
            w = rng.uniform(5, 40) if persona == '和平' else rng.uniform(-60, 10)
        elif regime == 2:
            w = rng.uniform(-15, 50)
        else:
            w = rng.uniform(-65, -5)
        if family == 4 and i == 0:
            w = -65 if regime % 2 == 0 else 55
        r = {'和平': 1.4, '中立': .9, '暴力': .25}[persona] * rng.uniform(.6, 1.4)
        nodes.append({'id': i + 1, 'w': round(w, 4), 'r': round(r, 4), 'persona': persona, 'comm_left': 3})
    strengths = list(itertools.permutations([15, 10, -5]))[(index // 2) % 6]
    scale = [1, .4, 2][(index // 12) % 3]
    return {'global_setting': {'max_budget': 100 if n <= 50 else 200, 'max_api_calls': 120 if n <= 50 else 250},
            'original_total': round(sum(x['w'] for x in nodes), 4), 'nodes': nodes,
            'edges': [[u + 1, v + 1] for u, v in graph.edges],
            'prompts': {str(i + 1): v * scale for i, v in enumerate(strengths)}}


class ProxyEnv:
    """Simulator for screening only; seed internals never given to policy."""
    def __init__(self, seed):
        self.nodes = {x['id']: copy.deepcopy(x) for x in seed['nodes']}
        for x in self.nodes.values():
            x['neighbors'] = []
        for u, v in seed['edges']:
            self.nodes[u]['neighbors'].append(v)
            self.nodes[v]['neighbors'].append(u)
        self.prompts = seed['prompts']
        self.budget = seed['global_setting']['max_budget']
        self.calls = 0
        self.trace = []

    def get_remaining_budget(self):
        return self.budget

    def scan_node(self, node):
        self.budget -= .5
        return {k: copy.deepcopy(v) for k, v in self.nodes[node].items() if k in ('w', 'persona', 'comm_left', 'neighbors')}

    def communicate(self, node, prompt_id):
        x = self.nodes[node]
        self.budget -= 2
        x['w'] += self.prompts[str(prompt_id)] * x['r'] * .5 ** (3 - x['comm_left'])
        x['comm_left'] -= 1
        return {'status': 'success', 'new_w': x['w']}

    def shield_node(self, node):
        self.budget -= 5
        self.nodes = changed(self.nodes, {'action': 'shield', 'node': node})
        return True

    def cut_link(self, u, v):
        self.budget -= 3
        self.nodes = changed(self.nodes, {'action': 'cut', 'node': u, 'other': v})
        return True

    def trigger_eval(self):
        return estimate(self.nodes)


def run_book(env, book):
    steps, actions = 0, []
    limit = 120 if book.node_count <= 50 else 250
    while steps < limit:
        budget = env.get_remaining_budget()
        phase, candidates, _ = book.candidates(budget)
        if not candidates:
            break
        if phase == 'intervene' and type(book) is ObservationBook:
            action = max(candidates, key=lambda a: a['utility_proxy'])
        else:
            action = candidates[0]
        if not book.valid(action, budget):
            raise ValueError('invalid research action')
        n = action['node']
        if action['action'] == 'scan':
            book.record_scan(n, env.scan_node(n))
        elif action['action'] == 'comm':
            book.record_comm(action, env.communicate(n, action['prompt_id']))
        elif action['action'] == 'shield':
            book.record_shield(n, env.shield_node(n))
        else:
            book.record_cut(n, action['other'], env.cut_link(n, action['other']))
        steps += 1
        actions.append(action)
    return steps, actions
