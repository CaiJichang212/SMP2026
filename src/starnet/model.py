"""CaseVO agent; the injected LLM authorizes every executed action."""
import json
import os
import queue
import threading

import networkx as nx
try:
    from agent_mesa import AgentBase, ModelBase
except ModuleNotFoundError as exc:
    if exc.name != 'agent_mesa':
        raise
    from casevo import AgentBase, ModelBase

from .policy import ObservationBook, finite_number, validate_plan


class CommanderAgent(AgentBase):
    def __init__(self, unique_id, model, description, context):
        super().__init__(unique_id, model, description, context)
        self.prompt = model.prompt_factory.get_template('commander.txt')

    def decide(self, payload):
        result = queue.Queue(maxsize=1)
        def call():
            try:
                response = self.prompt.send_prompt({'state': json.dumps(payload, ensure_ascii=False)}, self, self.model)
                result.put((True, response))
            except Exception:
                result.put((False, None))
        # Timeout terminates this policy permanently; no overlapping replacement call.
        worker = threading.Thread(target=call, daemon=True)
        self.model.llm_calls += 1
        worker.start()
        worker.join(self.model.llm_timeout)
        if worker.is_alive():
            raise TimeoutError('LLM deadline exceeded')
        ok, raw = result.get_nowait()
        if not ok or not isinstance(raw, str):
            raise ValueError('LLM unavailable')
        raw = raw.strip()
        if raw.startswith('```') and raw.endswith('```'):
            raw = raw.split('\n', 1)[1].rsplit('```', 1)[0].strip()
        return json.loads(raw)

    def step(self):
        return None  # Model drives bounded decisions explicitly.


class ParticipantSquadModel(ModelBase):
    def __init__(self, host_env, person_list, llm):
        graph = nx.Graph()
        graph.add_node(0)
        super().__init__(graph, llm, prompt_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'prompt'))
        self.env = host_env
        initial = self.env.get_remaining_budget()
        if not finite_number(initial) or initial < 0:
            raise ValueError('invalid initial budget')
        # Official stages: 100/50 and 200/100. Test config may narrow the range.
        hard_limit = 250 if initial >= 200 else 120
        description = person_list[0] if person_list else {'role': '指挥官'}
        node_count = description.get('node_count', 100 if initial >= 200 else 50)
        if type(node_count) is not int or not 1 <= node_count <= 100:
            raise ValueError('invalid configured node count')
        self.max_steps = hard_limit
        self.max_llm_calls = hard_limit
        self.llm_timeout = 55.0
        self.steps = 0
        self.llm_calls = 0
        self.book = ObservationBook(node_count)
        self.pending = []
        self.audit = []
        self.stopped = False
        self.stop_reason = None
        self.commander = CommanderAgent(0, self, description, None)
        self.add_agent(self.commander, 0)

    def _stop(self, reason):
        self.stopped = True
        self.stop_reason = reason
        self.pending = []
        return 1

    def step(self):
        if self.stopped:
            return 1
        if self.steps >= self.max_steps:
            return self._stop('step_limit')
        self.steps += 1
        self.schedule.time += 1
        try:
            budget = self.env.get_remaining_budget()
            if not finite_number(budget):
                return self._stop('invalid_budget')
            if budget < 2:
                return self._stop('budget')
            if self.pending and not self.book.valid(self.pending[0], budget):
                self.pending = []
            if not self.pending:
                phase, candidates, batch_limit = self.book.candidates(budget)
                if not candidates:
                    return self._stop('no_safe_candidate')
                batch_limit = min(batch_limit, self.max_steps - self.steps + 1)
                node_ids = {a['node'] for a in candidates}
                observed = {n: {'w': x['w'], 'persona': x['persona'], 'comm_left': x['comm_left'], 'degree': len(x['neighbors'])}
                            for n,x in self.book.nodes.items() if n in node_ids}
                payload = {'phase': phase, 'budget': budget, 'batch_limit': batch_limit,
                           'steps_remaining': self.max_steps-self.steps+1,
                           'calls_remaining': self.max_llm_calls-self.llm_calls,
                           'known_nodes': len(self.book.nodes), 'node_count': self.book.node_count,
                           'nodes': observed, 'calibration': self.book.samples[:3] + self.book.samples[3:][-8:],
                           'last_feedback': self.book.last_feedback, 'candidates': candidates}
                for attempt in range(2):
                    if self.llm_calls >= self.max_llm_calls:
                        return self._stop('llm_limit')
                    try:
                        response = self.commander.decide(payload)
                        self.pending = validate_plan(response, candidates, batch_limit, self.book, budget)
                        self.audit.append({'step': self.steps, 'phase': phase, 'choices': response['choices'],
                                           'reason': response['reason'][:500], 'approved': list(self.pending)})
                        break
                    except TimeoutError:
                        return self._stop('llm_timeout')
                    except (ValueError, TypeError, KeyError, IndexError):
                        payload['correction'] = '上次JSON或计划无效。只选择合法候选编号，目标不重复，不超预算；也可choices=[]停止。'
                else:
                    return self._stop('invalid_llm_plan')
                if not self.pending:
                    return self._stop('llm_stop')
            action = self.pending.pop(0)
            # Query again immediately before applying an authorized action.
            budget = self.env.get_remaining_budget()
            if not self.book.valid(action, budget):
                return self._stop('action_invalidated')
            if action['action'] == 'scan':
                self.book.record_scan(action['node'], self.env.scan_node(action['node']))
            elif action['action'] == 'shield':
                self.book.record_shield(action['node'], self.env.shield_node(action['node']))
                self.pending = []
            else:
                result = self.env.communicate(action['node'], action['prompt_id'])
                delta = self.book.record_comm(action, result)
                expected = action.get('expected_delta_proxy')
                if delta <= 0 or (expected is not None and abs(delta-expected) > max(1.0, abs(expected)*.5)):
                    self.pending = []  # Surprising feedback requires a fresh LLM decision.
            self.audit.append({'step': self.steps, 'executed': action, 'feedback': self.book.last_feedback})
            return 0
        except Exception as exc:
            # Never print exception text: provider/client errors can contain secrets.
            self.audit.append({'step': self.steps, 'error_type': type(exc).__name__})
            return self._stop('environment_or_protocol_error')
