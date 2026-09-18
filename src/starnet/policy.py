"""Public observations and advisory candidates; never makes the final decision."""
import math
import statistics


def finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


class ObservationBook:
    def __init__(self, node_count):
        self.node_count = node_count
        self.nodes = {}
        self.scanned = set()
        self.dead = set()
        self.samples = []
        self.calibration_target = None
        self.last_feedback = None

    def record_scan(self, node, result):
        self.scanned.add(node)
        if result is None:
            self.last_feedback = {'action': 'scan', 'node': node, 'found': False}
            return
        if not isinstance(result, dict) or not finite_number(result.get('w')):
            raise ValueError('invalid scan weight')
        left = result.get('comm_left')
        neighbors = result.get('neighbors')
        if type(left) is not int or not 0 <= left <= 3 or not isinstance(neighbors, list):
            raise ValueError('invalid scan metadata')
        if any(type(x) is not int or not 1 <= x <= self.node_count or x == node for x in neighbors):
            raise ValueError('invalid neighbor ID')
        self.nodes[node] = {'w': float(result['w']), 'persona': str(result.get('persona', '未知'))[:30],
                            'comm_left': left, 'neighbors': sorted(set(neighbors))}
        self.last_feedback = {'action': 'scan', 'node': node, 'found': True}

    def valid(self, action, budget):
        if not isinstance(action, dict) or not finite_number(budget):
            return False
        node = action.get('node')
        if type(node) is not int or not 1 <= node <= self.node_count:
            return False
        if action.get('action') == 'scan':
            return budget >= 2.5 and node not in self.scanned
        if action.get('action') == 'shield':
            return budget >= 5 and node in self.nodes and node not in self.dead and self.nodes[node]['w'] < -20 and len(self.nodes[node]['neighbors']) >= 3
        if action.get('action') == 'comm':
            p = action.get('prompt_id')
            return (budget >= 2 and node in self.nodes and self.nodes[node]['comm_left'] > 0
                    and type(p) is int and p in (1, 2, 3))
        return False

    def record_comm(self, action, result):
        node, pid = action['node'], action['prompt_id']
        if not isinstance(result, dict) or result.get('status') != 'success':
            if isinstance(result, dict) and result.get('status') == 'max_comm_reached':
                self.nodes[node]['comm_left'] = 0
            raise ValueError('communication not confirmed')
        if not finite_number(result.get('new_w')):
            raise ValueError('invalid communication feedback')
        current = self.nodes[node]
        delta = float(result['new_w']) - current['w']
        used = 3 - current['comm_left']
        sample = {'node': node, 'prompt_id': pid, 'persona': current['persona'],
                  'delta': delta, 'normalized_gain': delta / (.5 ** used)}
        self.samples.append(sample)
        if self.calibration_target is None:
            self.calibration_target = node
        current['w'] = float(result['new_w'])
        current['comm_left'] -= 1
        self.last_feedback = sample
        return delta

    def record_shield(self, node, success):
        if success is not True:
            raise ValueError('shield not confirmed')
        del self.nodes[node]
        self.dead.add(node)
        for x in self.nodes.values():
            x['neighbors'] = [n for n in x['neighbors'] if n != node]
        self.last_feedback = {'action': 'shield', 'node': node, 'success': True}

    def _gain(self, node, pid):
        persona = self.nodes[node]['persona']
        exact = [s['normalized_gain'] for s in self.samples if s['node'] == node and s['prompt_id'] == pid]
        same = [s['normalized_gain'] for s in self.samples if s['persona'] == persona and s['prompt_id'] == pid]
        all_samples = [s for s in self.samples if s['prompt_id'] == pid]
        if exact:
            return statistics.median(exact), 'same-node'
        if same:
            return statistics.median(same), 'same-persona-proxy'
        if all_samples:
            # Ordinal prior only, NOT an assertion about the engine's hidden r.
            factors = {'和平': 1.0, '中立': .65, '暴力': .2}
            s = all_samples[0]
            value = s['normalized_gain'] * factors.get(persona, .5) / factors.get(s['persona'], .5)
            return value, 'cross-persona-uncertain-proxy'
        return None, 'unknown'

    def candidates(self, budget):
        unknown = set(range(1, self.node_count + 1)) - self.scanned
        if unknown and budget >= 2.5:
            frontier = {n: sum(n in x['neighbors'] for x in self.nodes.values()) for n in unknown}
            ids = sorted(unknown, key=lambda n: (-frontier[n], n))[:16]
            return 'explore', [{'action': 'scan', 'node': n, 'cost': .5, 'observed_links': frontier[n]} for n in ids], 8
        if budget < 2:
            return 'stop', [], 0
        if self.calibration_target is None:
            eligible = [n for n, x in self.nodes.items() if x['comm_left'] > 0]
            eligible.sort(key=lambda n: (self.nodes[n]['comm_left'], self.nodes[n]['persona'] == '和平', len(self.nodes[n]['neighbors'])), reverse=True)
            return 'calibrate', [{'action': 'comm', 'node': n, 'prompt_id': p, 'cost': 2, 'effect': 'unknown'} for n in eligible[:4] for p in (1, 2, 3)], 1
        target = self.calibration_target
        measured = {s['prompt_id'] for s in self.samples if s['node'] == target}
        if target in self.nodes and self.nodes[target]['comm_left'] > 0 and len(measured) < 3:
            return 'calibrate', [{'action': 'comm', 'node': target, 'prompt_id': p, 'cost': 2, 'effect': 'unknown'} for p in (1, 2, 3) if p not in measured], 1
        candidates = []
        for n, x in self.nodes.items():
            if x['comm_left'] <= 0:
                continue
            for p in sorted(measured):
                gain, confidence = self._gain(n, p)
                if gain is None or gain <= 0:
                    continue
                delta = gain * (.5 ** (3 - x['comm_left']))
                candidates.append({'action': 'comm', 'node': n, 'prompt_id': p, 'cost': 2,
                                   'expected_delta_proxy': round(delta, 5),
                                   'utility_proxy': round(delta * (len(x['neighbors']) + 1) / 2, 5),
                                   'confidence': confidence})
        candidates.sort(key=lambda a: (-a['utility_proxy'], a['node'], a['prompt_id']))
        shields = [{'action': 'shield', 'node': n, 'cost': 5,
                    'utility_proxy': round(-x['w'] * (len(x['neighbors']) + 1) / 5, 5),
                    'confidence': 'negative-burden-only-not-marginal-score'}
                   for n, x in self.nodes.items() if budget >= 5 and x['w'] < -20 and len(x['neighbors']) >= 3]
        shields.sort(key=lambda a: -a['utility_proxy'])
        return 'intervene', candidates[:12] + shields[:4], 4

    def context(self):
        return {'nodes': self.nodes, 'calibration': self.samples[-12:], 'last_feedback': self.last_feedback}


def validate_plan(response, candidates, limit, book, budget):
    if not isinstance(response, dict) or not isinstance(response.get('reason'), str) or not response['reason'].strip():
        raise ValueError('reason required')
    choices = response.get('choices')
    if not isinstance(choices, list) or len(choices) > limit:
        raise ValueError('invalid plan length')
    selected = []
    targets = set()
    remaining = budget
    for choice in choices:
        if type(choice) is not int or not 0 <= choice < len(candidates):
            raise ValueError('invalid candidate index')
        action = dict(candidates[choice])
        if action['node'] in targets or not book.valid(action, remaining):
            raise ValueError('duplicate or unaffordable action')
        if action['action'] == 'shield' and len(choices) != 1:
            raise ValueError('shield requires replanning')
        remaining -= action['cost']
        targets.add(action['node'])
        selected.append(action)
    return selected
