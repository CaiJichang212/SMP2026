"""Empirical public-graph advice; the LLM still selects each action plan."""
from .policy import ObservationBook, finite_number


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
    def valid(self, action, budget):
        if not isinstance(action, dict) or not finite_number(budget):
            return False
        node = action.get('node')
        if action.get('action') == 'cut':
            other = action.get('other')
            return (type(node) is int and type(other) is int and budget >= 3
                    and node in self.nodes and other in self.nodes
                    and other in self.nodes[node]['neighbors']
                    and node in self.nodes[other]['neighbors'])
        if action.get('action') == 'shield':
            return type(node) is int and budget >= 5 and node in self.nodes
        return super().valid(action, budget)

    def record_cut(self, node, other, success):
        if success is not True:
            raise ValueError('cut not confirmed')
        self.nodes[node]['neighbors'].remove(other)
        self.nodes[other]['neighbors'].remove(node)
        self.last_feedback = {'action': 'cut', 'node': node, 'other': other, 'success': True}

    def communication_options(self, nodes):
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
                                'utility_proxy': delta * weights[n] / 2, 'offset': offset,
                                'confidence': self._gain(n, pid)[1]})
        options.sort(key=lambda a: (-a['gain_proxy'], a['node'], a['offset']))
        return options

    def completion(self, nodes, budget):
        options = self.communication_options(nodes)
        return estimate(nodes) + sum(a['gain_proxy'] for a in options[:int(budget // 2)])

    def candidates(self, budget):
        phase, base, limit = super().candidates(budget)
        if phase != 'intervene':
            return phase, base, limit
        options = self.communication_options(self.nodes)
        comm = [a for a in options if a['offset'] == 0][:12] if budget >= 2 else []
        current = estimate(self.nodes)
        baseline = self.completion(self.nodes, budget)
        structures = []
        actions = [{'action': 'shield', 'node': n, 'cost': 5} for n in sorted(self.nodes)] if budget >= 5 else []
        if budget >= 3:
            actions += [{'action': 'cut', 'node': n, 'other': v, 'cost': 3}
                        for n in sorted(self.nodes) for v in self.nodes[n]['neighbors'] if n < v and v in self.nodes]
        for action in actions:
            after = changed(self.nodes, action)
            gain = estimate(after) - current
            future = self.completion(after, budget - action['cost']) - baseline
            if future <= .01:
                continue
            # Endpoints suffice for a linear stress test of the communication tail.
            robust = future - .5 * abs(future - gain)
            structures.append(dict(action, gain_proxy=gain,
                                   utility_proxy=gain / action['cost'],
                                   completion_advantage=future, robust_advantage=robust,
                                   confidence='custom-sandbox-calibrated-proxy-not-official-formula'))
        structures.sort(key=lambda a: (-a['completion_advantage'], a['node']))
        for action in comm:
            action['completion_advantage'] = 0
        return phase, structures[:6] + comm, 1 if structures else 4
